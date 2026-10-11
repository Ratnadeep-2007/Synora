"use client";

import { useState } from "react";
import { api, InputOutcome } from "@/lib/api";
import { Project } from "@/lib/types";
import { ExcalidrawCanvas } from "../canvas/ExcalidrawCanvas";

export function SourceInputsPanel({ projects, onChanged }: {
  projects: Project[];
  onChanged?: () => Promise<void> | void;
}) {
  const [target, setTarget] = useState("");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [channel, setChannel] = useState("");
  const [cursor, setCursor] = useState<string | undefined>();
  const [drawing, setDrawing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<InputOutcome | null>(null);
  const [channelResult, setChannelResult] = useState("");
  const inputClass = "w-full rounded-lg border border-border bg-canvas px-3 py-2 text-sm text-text-main";
  const buttonClass = "rounded-lg bg-primary px-4 py-2 text-sm text-white disabled:opacity-50";

  const run = async (action: () => Promise<InputOutcome>) => {
    setBusy(true); setError(""); setResult(null);
    try {
      const outcome = await action();
      setResult(outcome);
      await onChanged?.();
    } catch (err) { setError(err instanceof Error ? err.message : "Submission failed"); }
    finally { setBusy(false); }
  };

  const syncChannel = async () => {
    setBusy(true); setError(""); setChannelResult("");
    try {
      const response = await api.syncSlackChannel(channel.trim(), target || undefined, cursor);
      setCursor(response.next_cursor);
      const unknown = response.outcomes.filter(o => o.outcome === "unknown_context").length;
      setChannelResult(response.rate_limited
        ? `Slack rate limit reached. Retry in ${response.retry_after_seconds || 5} seconds.`
        : `${response.messages_fetched} messages fetched; ${unknown} sent to the context inbox.`);
      await onChanged?.();
    } catch (err) { setError(err instanceof Error ? err.message : "Channel sync failed"); }
    finally { setBusy(false); }
  };

  return <section className="space-y-5 rounded-2xl border border-border bg-surface p-6">
    <div>
      <h2 className="text-lg font-bold text-text-main">Add source evidence</h2>
      <p className="text-sm text-text-muted">Submit text, documents or a drawing. Automatic routing sends uncertain input to the context inbox for review.</p>
    </div>
    <label className="block space-y-1 text-sm text-text-muted">
      <span>Project routing</span>
      <select className={inputClass} value={target} disabled={busy} onChange={e => { setTarget(e.target.value); setCursor(undefined); }}>
        <option value="">Automatically resolve / Unknown Context</option>
        {projects.filter(p => p.id !== "proj_unknown_context" && !(p as any).is_system).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
    </label>
    <div className="grid gap-5 md:grid-cols-2">
      <div className="space-y-3">
        <label htmlFor="manual-source" className="text-sm font-semibold text-text-main">Manual text</label>
        <textarea id="manual-source" className={inputClass} rows={5} value={text} maxLength={200000}
          onChange={e => setText(e.target.value)} placeholder="Paste decisions, requirements, notes or a transcript" />
        <button className={buttonClass} disabled={busy || !text.trim()} onClick={() => run(() => api.ingestManualText(text, target || undefined))}>Submit text</button>
      </div>
      <div className="space-y-3">
        <label htmlFor="source-file" className="text-sm font-semibold text-text-main">File or drawing upload</label>
        <input id="source-file" className={inputClass} type="file" disabled={busy}
          accept=".txt,.md,.csv,.tsv,.vtt,.srt,.pdf,.docx,.json,.excalidraw" onChange={e => setFile(e.target.files?.[0] || null)} />
        <p className="text-xs text-text-muted">Up to 10 MB. Text documents, PDF, DOCX or Excalidraw JSON with text labels.</p>
        <button className={buttonClass} disabled={busy || !file} onClick={() => file && run(() => api.uploadSourceFile(file, target || undefined))}>Upload evidence</button>
        <button className="block text-sm text-primary" onClick={() => setDrawing(!drawing)}>{drawing ? "Close drawing input" : "Draw with Excalidraw"}</button>
      </div>
    </div>
    {drawing && <div className="h-[560px]">
      <ExcalidrawCanvas projectName="Source drawing" onSaveCanvas={async scene => {
        if (busy) return;
        await run(() => api.ingestDrawing(scene, target || undefined));
      }} />
    </div>}
    <div className="space-y-3 border-t border-border pt-4">
      <h3 className="font-semibold text-text-main">Slack channel</h3>
      <p className="text-xs text-text-muted">Set SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET on the server and invite the bot to your channel. Signed events and channel history use the same routing pipeline.</p>
      <div className="flex gap-2">
        <input aria-label="Slack channel ID" className={inputClass} placeholder="Channel ID (C…)" value={channel} disabled={busy}
          onChange={e => { setChannel(e.target.value); setCursor(undefined); }} />
        <button className={buttonClass} disabled={busy || !channel.trim()} onClick={syncChannel}>{cursor ? "Fetch next page" : "Sync channel"}</button>
      </div>
      {channelResult && <p role="status" className="text-sm text-text-muted">{channelResult}</p>}
    </div>
    {busy && <p role="status" className="text-sm text-text-muted">Processing evidence…</p>}
    {error && <p role="alert" className="text-sm text-danger">{error}</p>}
    {result && <div role="status" className="rounded-lg border border-border p-3 text-sm text-text-main">
      <strong>{result.outcome === "unknown_context" ? "Saved to Unknown Context — assign it below" : result.outcome === "resolved" ? "Evidence routed to project" : result.outcome === "duplicate" ? "Already submitted" : "Ignored casual conversation"}</strong>
      <p className="text-text-muted">{result.reason}</p>
      {result.evidence_id && <p className="text-xs text-text-muted">Evidence: {result.evidence_id}</p>}
    </div>}
  </section>;
}
