"use client";

import { createAuthClient } from "@neondatabase/auth";
import { BetterAuthVanillaAdapter } from "@neondatabase/auth/vanilla/adapters";

declare global {
  interface Window {
    __SYNORA_AUTH_URL__?: string;
  }
}

function createSynoraAuthClient(url: string) {
  return createAuthClient(url, { adapter: BetterAuthVanillaAdapter() });
}

let authClient: ReturnType<typeof createSynoraAuthClient> | null = null;
let currentUrl = "";

export function isAuthEnabled(): boolean {
  return Boolean(
    (typeof window !== "undefined" && window.__SYNORA_AUTH_URL__) ||
      process.env.NEXT_PUBLIC_NEON_AUTH_URL,
  );
}

export function getAuthClient() {
  const url = (typeof window !== "undefined" && window.__SYNORA_AUTH_URL__) ||
    process.env.NEXT_PUBLIC_NEON_AUTH_URL || "";
  if (!url) return null;
  if (!authClient || currentUrl !== url) {
    authClient = createSynoraAuthClient(url);
    currentUrl = url;
  }
  return authClient;
}

export async function getAuthToken(): Promise<string | null> {
  const client = getAuthClient();
  if (!client) return null;
  const { data, error } = await client.token();
  if (error || !data?.token) return null;
  return data.token;
}
