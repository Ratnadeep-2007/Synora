"use client";

import React, { useEffect, useRef, useState } from "react";
import { clearCachedAuthToken, getAuthClient, isAuthEnabled } from "@/lib/auth";
import { api } from "@/lib/api";

async function clientResend(email: string): Promise<string> {
  const client = getAuthClient();
  if (!client) return "Authentication is unavailable.";
  try {
    const result = await client.emailOtp.sendVerificationOtp({ email, type: "email-verification" });
    return result.error?.message || "A new code was sent to your email.";
  } catch {
    return "Could not send a code. Please try again.";
  }
}

// Neon Auth is always-on and normally answers in seconds. If session
// restore stalls (network, cold edge), fail into the sign-in form with a
// message instead of spinning on "Loading session..." forever.
const SESSION_RESTORE_TIMEOUT_MS = 30_000;

function withTimeout<T>(promise: Promise<T>, ms: number, message: string): Promise<T> {
  return Promise.race([
    promise,
    new Promise<never>((_, reject) => setTimeout(() => reject(new Error(message)), ms)),
  ]);
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [signedIn, setSignedIn] = useState(false);
  const [mode, setMode] = useState<"sign-in" | "sign-up" | "verify">("sign-in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [otp, setOtp] = useState("");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [membership, setMembership] = useState<{ status: string; role: string } | null>(null);

  async function refreshMembership(): Promise<boolean> {
    try {
      const access = await api.getWorkspaceAccess();
      setMembership(access);
      setSignedIn(true);
      setMessage("");
      return true;
    } catch (error) {
      setSignedIn(false);
      const detail = error instanceof Error ? error.message : "Unknown workspace access error.";
      console.error("Synora workspace access failed after authentication:", error);
      setMessage(`You are signed in, but Synora could not load your workspace: ${detail}`);
      return false;
    }
  }

  useEffect(() => {
    const client = getAuthClient();
    if (!client) {
      setSignedIn(!isAuthEnabled());
      setLoading(false);
      return;
    }
    withTimeout(client.getSession(), SESSION_RESTORE_TIMEOUT_MS, "Session restore timed out. Please sign in again.").then(async ({ data, error }) => {
      if (data?.user) await refreshMembership();
      else {
        setSignedIn(false);
        if (error) {
          console.error("Could not restore Synora auth session:", error);
          setMessage(`Could not restore your sign-in session: ${error.message || "Please sign in again."}`);
        }
      }
    }).catch((error) => {
      setSignedIn(false);
      console.error("Could not restore Synora auth session:", error);
      setMessage(`Could not restore your sign-in session: ${error instanceof Error ? error.message : "Please sign in again."}`);
    }).finally(() => setLoading(false));
  }, []);

  // Ref guard (not just state): a double click or Enter+click in the same
  // frame must not create two sign-in/sign-up requests.
  const submitInFlight = useRef(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (submitInFlight.current) return;
    const client = getAuthClient();
    if (!client) return;
    submitInFlight.current = true;
    setPending(true);
    setMessage("");
    try {
      if (mode === "verify") {
        const verification = await client.emailOtp.verifyEmail({ email, otp });
        if (verification.error) {
          setMessage(verification.error.message || "Verification failed.");
          return;
        }
        const session = await client.getSession();
        if (session.data?.user) await refreshMembership();
        else { setMode("sign-in"); setMessage("Email verified. Sign in to continue."); }
        return;
      }
      const result = mode === "sign-in"
        ? await client.signIn.email({ email, password })
        : await client.signUp.email({ email, password, name });
      if (result.error) {
        setMessage(result.error.message || "Authentication failed.");
        if (mode === "sign-in" && result.error.message?.toLowerCase().includes("verif")) setMode("verify");
        return;
      }
      const session = await client.getSession();
      if (session.data?.user) {
        await refreshMembership();
      } else {
        setMessage("Enter the verification code sent to your email.");
        setMode("verify");
      }
    } catch (error) {
      console.error("Synora authentication flow failed:", error);
      setMessage(error instanceof Error ? error.message : "Authentication failed. Please try again.");
    } finally {
      submitInFlight.current = false;
      setPending(false);
    }
  }

  if (loading) return <main className="min-h-screen grid place-items-center bg-canvas text-text-muted"><div className="text-center space-y-2"><p>Loading session...</p><p className="text-xs">First load after idle can take up to a minute while the backend wakes up.</p></div></main>;
  if (signedIn && membership?.status === "pending") return (
    <main className="min-h-screen grid place-items-center bg-canvas px-4">
      <section className="w-full max-w-md rounded-2xl border border-border bg-surface p-8 shadow-xl">
        <p className="text-xs uppercase tracking-[0.2em] text-primary font-semibold">Synora workspace</p>
        <h1 className="mt-2 text-2xl font-semibold text-text-main">Waiting for workspace assignment</h1>
        <p className="mt-2 text-sm text-text-muted">Your account is verified. A workspace owner needs to assign your account before you can access shared projects.</p>
        <button type="button" onClick={async () => { await getAuthClient()?.signOut(); clearCachedAuthToken(); window.location.reload(); }} className="mt-5 rounded-lg border border-border px-4 py-2 text-xs font-semibold text-text-main">Sign out</button>
      </section>
    </main>
  );
  if (signedIn) return <>{children}</>;

  return (
    <main className="min-h-screen grid place-items-center bg-canvas px-4">
      <form onSubmit={submit} className="w-full max-w-md rounded-2xl border border-border bg-surface p-8 shadow-xl space-y-5">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-primary font-semibold">Synora</p>
          <h1 className="mt-2 text-2xl font-semibold text-text-main">{mode === "sign-in" ? "Sign in" : mode === "sign-up" ? "Create an account" : "Verify your email"}</h1>
          <p className="mt-1 text-sm text-text-muted">Access your projects and meeting evidence securely.</p>
        </div>
        {mode === "sign-up" && <label className="block text-sm text-text-main">Name<input required value={name} onChange={(event) => setName(event.target.value)} className="mt-1 w-full rounded-lg border border-border bg-canvas px-3 py-2" /></label>}
        <label className="block text-sm text-text-main">Email<input required type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} className="mt-1 w-full rounded-lg border border-border bg-canvas px-3 py-2" /></label>
        {mode === "verify" ? (
          <label className="block text-sm text-text-main">Email code<input required inputMode="numeric" autoComplete="one-time-code" value={otp} onChange={(event) => setOtp(event.target.value)} className="mt-1 w-full rounded-lg border border-border bg-canvas px-3 py-2" /></label>
        ) : (
          <label className="block text-sm text-text-main">Password<input required type="password" minLength={8} autoComplete={mode === "sign-in" ? "current-password" : "new-password"} value={password} onChange={(event) => setPassword(event.target.value)} className="mt-1 w-full rounded-lg border border-border bg-canvas px-3 py-2" /></label>
        )}
        {message && <p role="alert" className="text-sm text-primary">{message}</p>}
        {message.startsWith("You are signed in, but Synora could not load your workspace:") && (
          <button type="button" onClick={() => { setPending(true); void refreshMembership().finally(() => setPending(false)); }} className="w-full rounded-lg border border-border px-4 py-2 text-sm font-semibold text-text-main">Retry workspace connection</button>
        )}
        <button disabled={pending} className="w-full rounded-lg bg-primary px-4 py-2.5 font-semibold text-white disabled:opacity-60">{pending ? "Please wait..." : mode === "sign-in" ? "Sign in" : mode === "sign-up" ? "Create account" : "Verify email"}</button>
        {mode === "verify" && <button type="button" onClick={async () => { const result = await clientResend(email); setMessage(result); }} className="w-full text-sm text-primary">Send another code</button>}
        <button type="button" onClick={() => { setMode(mode === "sign-in" ? "sign-up" : "sign-in"); setMessage(""); }} className="w-full text-sm text-primary">
          {mode === "sign-in" ? "Create an account" : "Back to sign in"}
        </button>
      </form>
    </main>
  );
}
