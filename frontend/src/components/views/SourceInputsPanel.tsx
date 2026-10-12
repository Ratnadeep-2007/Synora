"use client";

import { useState } from "react";
import { api, InputOutcome } from "@/lib/api";
import { Project } from "@/lib/types";

export function SourceInputsPanel({ projects, onChanged }: {
  projects: Project[];
  onChanged?: () => Promise<void> | void;
}) {
  const [target, setTarget] = useState("");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<InputOutcome | null>(null);
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

  return <section className="space-y-5 rounded-2xl border border-border bg-surface p-6">
    <div>
      <h2 className="text-lg font-bold text-text-main">Add source evidence</h2>
      <p className="text-sm text-text-muted">Submit text, documents or images. Matching uploads enter project memory; unmatched uploads are ignored. Unresolved manual text goes to the context inbox.</p>
    </div>
    <label className="block space-y-1 text-sm text-text-muted">
      <span>Project routing</span>
      <select className={inputClass} value={target} disabled={busy} onChange={e => setTarget(e.target.value)}>
        <option value="">Automatically match a project</option>
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
        <label htmlFor="source-file" className="text-sm font-semibold text-text-main">Document or image upload</label>
        <input id="source-file" className={inputClass} type="file" disabled={busy}
          accept=".txt,.md,.csv,.tsv,.vtt,.srt,.pdf,.docx,.png,.jpg,.jpeg,.webp" onChange={e => setFile(e.target.files?.[0] || null)} />
        <p className="text-xs text-text-muted">Up to 10 MB. Text documents, PDF, DOCX, PNG, JPEG or WebP. Images use the configured vision provider.</p>
        <button className={buttonClass} disabled={busy || !file} onClick={() => file && run(() => api.uploadSourceFile(file, target || undefined))}>Upload evidence</button>
      </div>
    </div>
    {busy && <p role="status" className="text-sm text-text-muted">Processing evidence…</p>}
    {error && <p role="alert" className="text-sm text-danger">{error}</p>}
    {result && <div role="status" className="rounded-lg border border-border p-3 text-sm text-text-main">
      <strong>{result.outcome === "unknown_context" ? "Saved to Unknown Context — assign it below" : result.outcome === "resolved" ? "Evidence routed to project" : result.outcome === "duplicate" ? "Already submitted" : "Ignored — no matching project or relevant content"}</strong>
      <p className="text-text-muted">{result.reason}</p>
      {result.evidence_id && <p className="text-xs text-text-muted">Evidence: {result.evidence_id}</p>}
    </div>}
  </section>;
}
