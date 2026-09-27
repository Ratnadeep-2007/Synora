/**
 * Synora - WhatsApp Baileys Group Chat Bridge Daemon
 * 
 * Uses @whiskeysockets/baileys to connect to WhatsApp Web via WebSocket.
 * Listens for messages in WhatsApp group chats, formats them, and forwards them
 * to the Synora backend for automatic project identification and Excalidraw whiteboard updates.
 */

import makeWASocket, {
  DisconnectReason,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  Browsers,
  proto,
  WASocket,
  downloadMediaMessage,
} from "@whiskeysockets/baileys";
import { Boom } from "@hapi/boom";
import pino from "pino";
import qrcode from "qrcode-terminal";
import path from "path";
import fs from "fs";
import http from "http";


const BACKEND_URL = process.env.SYNORA_BACKEND_URL || "http://localhost:8000";
const AUTH_DIR = path.join(__dirname, "../baileys_auth_info");

async function reportSessionStatus(
  status: "connected" | "disconnected" | "reconnecting",
  activeGroupsCount: number | null = null
) {
  const url = `${BACKEND_URL}/connectors/whatsapp/session-status`;
  const postData = JSON.stringify({
    session_id: "baileys_default",
    status,
    active_groups_count: activeGroupsCount,
    connected_at: status === "connected" ? new Date().toISOString() : undefined,
    last_seen: new Date().toISOString(),
  });

  return new Promise((resolve) => {
    try {
      const parsedUrl = new URL(url);
      const req = http.request(
        {
          hostname: parsedUrl.hostname,
          port: parsedUrl.port || 80,
          path: parsedUrl.pathname,
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Content-Length": Buffer.byteLength(postData),
          },
        },
        (res) => {
          res.resume();
          resolve(true);
        }
      );
      req.on("error", () => {
        resolve(false);
      });
      req.write(postData);
      req.end();
    } catch {
      resolve(false);
    }
  });
}

async function forwardMessageToSynora(payload: {
  message_id: string;
  sender_jid: string;
  sender_name: string;
  group_jid: string;
  group_name?: string;
  text: string;
  audio_base64?: string;
  image_base64?: string;
  media_type?: "audio" | "image";
  mimetype?: string;
  timestamp?: number;
}) {

  const url = `${BACKEND_URL}/connectors/whatsapp/webhook`;
  const postData = JSON.stringify(payload);

  return new Promise((resolve, reject) => {
    const parsedUrl = new URL(url);
    const req = http.request(
      {
        hostname: parsedUrl.hostname,
        port: parsedUrl.port || 80,
        path: parsedUrl.pathname,
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(postData),
        },
      },
      (res) => {
        let body = "";
        res.on("data", (chunk) => (body += chunk));
        res.on("end", () => {
          try {
            const data = JSON.parse(body);
            resolve(data);
          } catch {
            resolve({ raw: body });
          }
        });
      }
    );

    req.on("error", (err) => {
      console.error(`[Synora Bridge] Error forwarding to Synora backend (${url}):`, err.message);
      reject(err);
    });

    req.write(postData);
    req.end();
  });
}

export async function connectToWhatsApp(): Promise<WASocket> {
  if (!fs.existsSync(AUTH_DIR)) {
    fs.mkdirSync(AUTH_DIR, { recursive: true });
  }

  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  let waVersion: [number, number, number] | undefined = undefined;

  try {
    const { version, isLatest } = await fetchLatestBaileysVersion();
    waVersion = version;
    console.log(`[Synora Bridge] WhatsApp Web protocol: v${version.join(".")} (isLatest: ${isLatest})`);
  } catch (err: any) {
    console.warn("[Synora Bridge] Could not fetch remote WhatsApp Web version, using default:", err.message);
  }

  const sock = makeWASocket({
    version: waVersion,
    auth: state,
    logger: pino({ level: "error" }),
    browser: Browsers.ubuntu("Chrome"),
    printQRInTerminal: false,
    syncFullHistory: false,
    generateHighQualityLinkPreview: false,
    defaultQueryTimeoutMs: undefined,
  });

  sock.ev.on("connection.update", (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      console.log("\n================ WHATSAPP BAILEYS QR CODE ================");
      console.log("Scan this QR code with WhatsApp on your phone (Linked Devices):");
      qrcode.generate(qr, { small: true });
      console.log("==========================================================\n");
      reportSessionStatus("disconnected", null);
    }

    if (connection === "close") {
      const statusCode = (lastDisconnect?.error as Boom)?.output?.statusCode;
      const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
      console.log(
        `[Synora Bridge] Connection closed (code: ${statusCode}, reason: ${lastDisconnect?.error?.message || lastDisconnect?.error || "unknown"}), reconnecting: ${shouldReconnect}`
      );
      reportSessionStatus(shouldReconnect ? "reconnecting" : "disconnected", null);

      // If logged out or unauthenticated, clean up stale credentials directory
      if (statusCode === DisconnectReason.loggedOut || statusCode === 401 || statusCode === 405) {
        console.log("[Synora Bridge] Authentication rejected or logged out. Resetting local auth keys...");
        try {
          fs.rmSync(AUTH_DIR, { recursive: true, force: true });
        } catch (e) {
          console.error("Failed to clean auth dir:", e);
        }
      }

      if (shouldReconnect) {
        setTimeout(() => {
          connectToWhatsApp();
        }, 3000);
      }
    } else if (connection === "open") {
      console.log("✅ [Synora Bridge] Connected successfully to WhatsApp via Baileys WebSocket!");
      console.log(`[Synora Bridge] Forwarding group chat discussions to: ${BACKEND_URL}`);

      const syncGroupCountAndReport = async () => {
        let groupCount = 0;
        try {
          const groups = await sock.groupFetchAllParticipating();
          groupCount = Object.keys(groups || {}).length;
        } catch {
          groupCount = 0;
        }
        await reportSessionStatus("connected", groupCount);
      };

      syncGroupCountAndReport();
      const heartbeat = setInterval(syncGroupCountAndReport, 30000);
      sock.ev.on("connection.update", (nextUpdate) => {
        if (nextUpdate.connection === "close") {
          clearInterval(heartbeat);
        }
      });
    }
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("messages.upsert", async (m) => {
    if (m.type !== "notify") return;

    for (const msg of m.messages) {
      if (!msg.message || msg.key.fromMe) continue;

      const remoteJid = msg.key.remoteJid || "";
      const isGroup = remoteJid.endsWith("@g.us");

      // Extract text content
      let text =
        msg.message.conversation ||
        msg.message.extendedTextMessage?.text ||
        msg.message.imageMessage?.caption ||
        "";

      let audioBase64: string | undefined = undefined;
      let imageBase64: string | undefined = undefined;
      let mediaType: "audio" | "image" | undefined = undefined;

      // Handle WhatsApp Voice Notes / Audio messages
      if (msg.message.audioMessage) {
        try {
          const buffer = (await downloadMediaMessage(
            msg,
            "buffer",
            {},
            {
              logger: pino({ level: "silent" }),
              reuploadRequest: sock.updateMediaMessage,
            }
          )) as Buffer;
          if (buffer && buffer.length > 0) {
            audioBase64 = buffer.toString("base64");
            mediaType = "audio";
            console.log(`  🎙️ Downloaded audio voice note (${(buffer.length / 1024).toFixed(1)} KB)`);
          }
        } catch (err: any) {
          console.warn(`  ⚠️ Failed to download voice note: ${err.message}`);
        }
      }

      // Handle WhatsApp Whiteboard / Diagram Images
      if (msg.message.imageMessage) {
        try {
          const buffer = (await downloadMediaMessage(
            msg,
            "buffer",
            {},
            {
              logger: pino({ level: "silent" }),
              reuploadRequest: sock.updateMediaMessage,
            }
          )) as Buffer;
          if (buffer && buffer.length > 0) {
            imageBase64 = buffer.toString("base64");
            mediaType = "image";
            console.log(`  🖼️ Downloaded diagram image (${(buffer.length / 1024).toFixed(1)} KB)`);
          }
        } catch (err: any) {
          console.warn(`  ⚠️ Failed to download image: ${err.message}`);
        }
      }

      if (!text.trim() && !audioBase64 && !imageBase64) continue;

      const senderJid = msg.key.participant || msg.participant || remoteJid;
      const senderName = msg.pushName || "WhatsApp User";
      const messageId = msg.key.id || `wamid_${Date.now()}`;

      let groupName = "WhatsApp Group";
      if (isGroup) {
        try {
          const meta = await sock.groupMetadata(remoteJid);
          groupName = meta.subject || groupName;
        } catch {
          groupName = `Group ${remoteJid.slice(0, 12)}`;
        }
      }

      const displayContent = text.trim() || (mediaType === "audio" ? "[Voice Note]" : "[Image]");
      console.log(`\n💬 [WhatsApp ${isGroup ? "Group: " + groupName : "DM"}] ${senderName}: ${displayContent}`);

      try {
        const result: any = await forwardMessageToSynora({
          message_id: messageId,
          sender_jid: senderJid,
          sender_name: senderName,
          group_jid: remoteJid,
          group_name: groupName,
          text: text.trim(),
          audio_base64: audioBase64,
          image_base64: imageBase64,
          media_type: mediaType,

          mimetype: (msg.message.audioMessage?.mimetype || msg.message.imageMessage?.mimetype) ?? undefined,
          timestamp: typeof msg.messageTimestamp === "number" ? msg.messageTimestamp : Date.now(),
        });




        if (result && result.matched_project) {
          console.log(`  🎯 Discovered Project: ${result.matched_project.name} (${result.matched_project.id})`);
          console.log(`  🧠 Confidence: ${(result.confidence * 100).toFixed(1)}% | Reason: ${result.reasoning}`);
          if (result.excalidraw_updated) {
            console.log(`  🎨 Excalidraw Whiteboard Updated! Artifact v${result.artifact_version} | Nodes Added: ${JSON.stringify(result.nodes_added)}`);
          }
        }
      } catch (err: any) {
        console.error("  ❌ Failed to process message in Synora:", err.message);
      }
    }
  });

  return sock;
}

// Interactive Simulation Mode for testing without physical WhatsApp device
async function runSimulator() {
  console.log("=== Synora WhatsApp Baileys Simulation Mode ===");
  console.log(`Target Backend: ${BACKEND_URL}`);

  const sampleMessages = [
    {
      name: "Healthcare Claims Engine (KYC Decision)",
      text: "Team, for the Healthcare Claims Engine, we have decided to integrate Digilocker KYC API for automatic claimant identity verification. Add Digilocker KYC component to the pipeline.",
    },
    {
      name: "Synesis Core Architecture (Redis Caching)",
      text: "For Core Architecture: let's switch session storage to Redis with JWT validation and remove in-memory dictionaries.",
    },
    {
      name: "Healthcare Claims (Fraud Detection)",
      text: "Regarding proj_17df42a9: Requirement confirmed that claims adjudication must pass through an AML Fraud Engine before approval.",
    },
  ];

  for (const sample of sampleMessages) {
    console.log(`\nSimulating: ${sample.name}`);
    console.log(`Message: "${sample.text}"`);
    try {
      const res: any = await forwardMessageToSynora({
        message_id: `wamid_sim_${Date.now()}_${Math.random().toString(36).substring(7)}`,
        sender_jid: "919876543210@s.whatsapp.net",
        sender_name: "Dr. Arvind (Lead Architect)",
        group_jid: "120363025812345678@g.us",
        group_name: "Synora Architecture & Engineering",
        text: sample.text,
      });

      console.log("Response:", JSON.stringify(res, null, 2));
    } catch (err: any) {
      console.error("Simulation error:", err.message);
    }
  }
}

// Entrypoint
if (process.argv.includes("--simulate")) {
  runSimulator();
} else {
  console.log("Starting Synora WhatsApp Baileys Bridge...");
  connectToWhatsApp().catch((err) => {
    console.error("Fatal error starting Baileys bridge:", err);
  });
}
