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
  const [docFile, setDocFile] = useState<File | null>(null);
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<InputOutcome | null>(null);
  const inputClass = "w-full rounded-lg border border-border bg-canvas px-3 py-2 text-sm text-text-main";
  const buttonClass = "rounded-lg bg-primary px-4 py-2 text-sm text-white disabled:opacity-50";

  const pickImage = (file: File | null) => {
    setImageFile(file);
    setImagePreview((prev) => {
      if (prev.startsWith("blob:")) URL.revokeObjectURL(prev);
      return file ? URL.createObjectURL(file) : "";
    });
  };

  const run = async (action: () => Promise<InputOutcome>) => {
    setBusy(true); setError(""); setResult(null);
    try {
      const outcome = await action();
      setResult(outcome);
      setDocFile(null);
      pickImage(null);
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
    <div className="grid gap-5 md:grid-cols-3">
      <div className="space-y-3">
        <label htmlFor="manual-source" className="text-sm font-semibold text-text-main">Manual text</label>
        <textarea id="manual-source" className={inputClass} rows={5} value={text} maxLength={200000}
          onChange={e => setText(e.target.value)} placeholder="Paste decisions, requirements, notes or a transcript" />
        <button className={buttonClass} disabled={busy || !text.trim()} onClick={() => run(() => api.ingestManualText(text, target || undefined))}>Submit text</button>
      </div>
      <div className="space-y-3">
        <label htmlFor="source-doc" className="text-sm font-semibold text-text-main">Document upload</label>
        <input id="source-doc" className={inputClass} type="file" disabled={busy}
          accept=".txt,.md,.csv,.tsv,.vtt,.srt,.pdf,.docx" onChange={e => setDocFile(e.target.files?.[0] || null)} />
        <p className="text-xs text-text-muted">Up to 10 MB. Text documents, PDF or DOCX.</p>
        <button className={buttonClass} disabled={busy || !docFile} onClick={() => docFile && run(() => api.uploadSourceFile(docFile, target || undefined))}>Upload document</button>
      </div>
      <div className="space-y-3">
        <label htmlFor="source-image" className="text-sm font-semibold text-text-main">Image input</label>
        <input id="source-image" className={inputClass} type="file" disabled={busy}
          accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp" onChange={e => pickImage(e.target.files?.[0] || null)} />
        <p className="text-xs text-text-muted">PNG, JPEG or WebP up to 10 MB. Read by the vision provider; confident matches enter memory.</p>
        {imagePreview && (
          <img src={imagePreview} alt="Selected upload preview" className="max-h-36 rounded-lg border border-border object-contain" />
        )}
        <button className={buttonClass} disabled={busy || !imageFile} onClick={() => imageFile && run(() => api.uploadSourceFile(imageFile, target || undefined))}>Upload image</button>
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
