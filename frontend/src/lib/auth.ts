"use client";

import { createAuthClient } from "@neondatabase/auth";
import { BetterAuthVanillaAdapter } from "@neondatabase/auth/vanilla/adapters";

declare global {
  interface Window {
    __SYNORA_AUTH_URL__?: string;
    __SYNORA_AUTH_MODE__?: "required" | "shared";
  }
}

function createSynoraAuthClient(url: string) {
  return createAuthClient(url, { adapter: BetterAuthVanillaAdapter() });
}

let authClient: ReturnType<typeof createSynoraAuthClient> | null = null;
let currentUrl = "";

export function isAuthEnabled(): boolean {
  if (typeof window !== "undefined" && window.__SYNORA_AUTH_MODE__ === "shared") return false;
  return Boolean(
    (typeof window !== "undefined" && window.__SYNORA_AUTH_URL__) ||
      process.env.NEXT_PUBLIC_NEON_AUTH_URL,
  );
}

export function getAuthClient() {
  if (typeof window !== "undefined" && window.__SYNORA_AUTH_MODE__ === "shared") return null;
  const url = (typeof window !== "undefined" && window.__SYNORA_AUTH_URL__) ||
    process.env.NEXT_PUBLIC_NEON_AUTH_URL || "";
  if (!url) return null;
  if (!authClient || currentUrl !== url) {
    authClient = createSynoraAuthClient(url);
    currentUrl = url;
  }
  return authClient;
}

// Session handling: the auth token is cached until shortly before it
// expires and concurrent callers share ONE in-flight token request. The
// app polls many endpoints in parallel; minting a token per API call was
// a network round-trip each (and could surface as failed requests).
let cachedToken: { token: string; expiresAtMs: number } | null = null;
let tokenInFlight: Promise<string | null> | null = null;
const TOKEN_REFRESH_MARGIN_MS = 60_000;

function tokenExpiryMs(token: string): number {
  try {
    const payload = token.split(".")[1];
    const json = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
    return typeof json.exp === "number" ? json.exp * 1000 : 0;
  } catch {
    return 0;
  }
}

export function clearCachedAuthToken(): void {
  cachedToken = null;
  tokenInFlight = null;
}

export async function getAuthToken(): Promise<string | null> {
  const now = Date.now();
  if (cachedToken && cachedToken.expiresAtMs - now > TOKEN_REFRESH_MARGIN_MS) {
    return cachedToken.token;
  }
  if (tokenInFlight) return tokenInFlight;
  tokenInFlight = (async () => {
    try {
      const client = getAuthClient();
      if (!client) return null;
      const { data, error } = await client.token();
      if (!error && data?.token) {
        const expiresAtMs = tokenExpiryMs(data.token);
        // Never cache a token we cannot date; treat it as single-use.
        cachedToken = expiresAtMs > now ? { token: data.token, expiresAtMs } : null;
        return data.token;
      }
      // Fallback: /token needs the cross-domain session cookie, which some
      // browsers block on XHR even with SameSite=None. The opaque session
      // token (already in the SDK's session) is accepted by the backend,
      // which validates it against the Neon Auth session table.
      const session = (await client.getSession()) as unknown as {
        data?: { session?: { token?: string; expiresAt?: string } } | null;
      };
      const sessionToken = session?.data?.session?.token;
      if (sessionToken) {
        const expMs = Date.parse(session?.data?.session?.expiresAt || "");
        cachedToken = { token: sessionToken, expiresAtMs: Number.isFinite(expMs) ? expMs : now + 5 * 60_000 };
        return sessionToken;
      }
      cachedToken = null;
      return null;
    } catch {
      cachedToken = null;
      return null;
    } finally {
      tokenInFlight = null;
    }
  })();
  return tokenInFlight;
}
