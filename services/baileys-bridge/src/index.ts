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
  proto,
  WASocket,
} from "@whiskeysockets/baileys";
import { Boom } from "@hapi/boom";
import qrcode from "qrcode-terminal";
import path from "path";
import fs from "fs";
import http from "http";

const BACKEND_URL = process.env.SYNORA_BACKEND_URL || "http://localhost:8000";
const AUTH_DIR = path.join(__dirname, "../baileys_auth_info");

async function forwardMessageToSynora(payload: {
  message_id: string;
  sender_jid: string;
  sender_name: string;
  group_jid: string;
  group_name?: string;
  text: string;
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

  const sock = makeWASocket({
    auth: state,
    printQRInTerminal: false,
    syncFullHistory: false,
  });

  sock.ev.on("connection.update", (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      console.log("\n================ WHATSAPP BAILEYS QR CODE ================");
      console.log("Scan this QR code with WhatsApp on your phone (Linked Devices):");
      qrcode.generate(qr, { small: true });
      console.log("==========================================================\n");
    }

    if (connection === "close") {
      const shouldReconnect =
        (lastDisconnect?.error as Boom)?.output?.statusCode !== DisconnectReason.loggedOut;
      console.log(
        "[Synora Bridge] Connection closed due to",
        lastDisconnect?.error,
        ", reconnecting:",
        shouldReconnect
      );
      if (shouldReconnect) {
        connectToWhatsApp();
      }
    } else if (connection === "open") {
      console.log("✅ [Synora Bridge] Connected successfully to WhatsApp via Baileys WebSocket!");
      console.log(`[Synora Bridge] Forwarding group chat discussions to: ${BACKEND_URL}`);
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
      const text =
        msg.message.conversation ||
        msg.message.extendedTextMessage?.text ||
        msg.message.imageMessage?.caption ||
        "";

      if (!text.trim()) continue;

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

      console.log(`\n💬 [WhatsApp ${isGroup ? "Group: " + groupName : "DM"}] ${senderName}: ${text}`);

      try {
        const result: any = await forwardMessageToSynora({
          message_id: messageId,
          sender_jid: senderJid,
          sender_name: senderName,
          group_jid: remoteJid,
          group_name: groupName,
          text: text.trim(),
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
