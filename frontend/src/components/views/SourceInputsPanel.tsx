"use client";

import { useRef, useState } from "react";
import { Check, FileText, LoaderCircle, Plus, Upload, X } from "lucide-react";
import { api, type InputOutcome } from "@/lib/api";
import { Project } from "@/lib/types";

const MAX_BYTES = 10 * 1024 * 1024;
const DOCUMENTS = new Set(["txt", "md", "csv", "tsv", "vtt", "srt", "pdf", "docx"]);
const IMAGES = new Set(["png", "jpg", "jpeg", "webp"]);
const AUDIO = new Set(["mp3", "m4a", "ogg", "opus", "webm", "wav", "flac"]);
const ACCEPT = [Array.from(DOCUMENTS), Array.from(IMAGES), Array.from(AUDIO)].flat().map(extension => `.${extension}`).join(",");
type QueuedFile = { id: number; file: File; status: "queued" | "processing" | "saved" | "failed"; message?: string; transcript?: { text: string; artifactId?: string } };

function extension(file: File) { return file.name.split(".").pop()?.toLowerCase() || ""; }
function outcomeMessage(outcome: InputOutcome) {
  if (outcome.outcome === "duplicate") return "Already added";
  if (outcome.outcome === "unknown_context") return "Saved to Context Inbox for review";
  if (outcome.conflicts_detected) return `Saved · ${outcome.conflicts_detected} conflict${outcome.conflicts_detected === 1 ? "" : "s"} to review`;
  if (outcome.outcome === "resolved") return "Source saved";
  return outcome.reason || "Processed; no memory change";
}

export function SourceInputsPanel({ projects, selectedProject, onChanged }: {
  projects: Project[];
  selectedProject?: Project | null;
  onChanged?: () => Promise<void> | void;
}) {
  const [target, setTarget] = useState(selectedProject?.id || "");
  const [files, setFiles] = useState<QueuedFile[]>([]);
  const [text, setText] = useState("");
  const [showText, setShowText] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [progress, setProgress] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const nextId = useRef(0);
  const inFlight = useRef(false);
  const dragDepth = useRef(0);
  const targetProjectId = selectedProject?.id || target || undefined;
  const pendingFiles = files.filter(item => item.status === "queued" || item.status === "failed");

  const addFiles = (incoming: FileList | File[]) => {
    if (inFlight.current) return;
    setNotice("");
    const rejected: string[] = [];
    const accepted: QueuedFile[] = [];
    for (const file of Array.from(incoming)) {
      const ext = extension(file);
      if (!DOCUMENTS.has(ext) && !IMAGES.has(ext) && !AUDIO.has(ext)) {
        rejected.push(`${file.name}: this format is not supported yet.`);
      } else if (!file.size || file.size > MAX_BYTES) {
        rejected.push(`${file.name}: choose a non-empty file up to 10 MB.`);
      } else {
        accepted.push({ id: ++nextId.current, file, status: "queued" });
      }
    }
    setFiles(current => {
      const known = new Set(current.map(item => `${item.file.name}:${item.file.size}:${item.file.lastModified}`));
      return [...current, ...accepted.filter(item => {
        const key = `${item.file.name}:${item.file.size}:${item.file.lastModified}`;
        if (known.has(key)) return false;
        known.add(key);
        return true;
      })];
    });
    setError(rejected.join(" "));
    if (input.current) input.current.value = "";
  };

  const submit = async () => {
    if (inFlight.current || (!pendingFiles.length && !text.trim())) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    let saved = 0;
    const failures: string[] = [];
    const update = (id: number, patch: Partial<QueuedFile>) => setFiles(current => current.map(item => item.id === id ? { ...item, ...patch } : item));
    try {
      // Sequential uploads keep large audio/image requests and AI quotas bounded.
      for (const item of pendingFiles) {
        update(item.id, { status: "processing", message: undefined });
        try {
          let outcome: InputOutcome;
          if (AUDIO.has(extension(item.file))) {
            let transcript = item.transcript;
            if (!transcript) {
              setProgress(`Transcribing ${item.file.name}...`);
              const response = await api.transcribeContextAudio(item.file, targetProjectId, true);
              if (!response.success || !response.text.trim()) throw new Error(response.error || "No transcript was returned. Please retry.");
              transcript = { text: response.text, artifactId: response.artifact_id };
              update(item.id, { transcript });
            }
            setProgress(`Adding ${item.file.name}...`);
            outcome = await api.ingestManualText(transcript.text, targetProjectId, item.file.name, transcript.artifactId);
          } else {
            setProgress(`Processing ${item.file.name}...`);
            outcome = await api.uploadSourceFile(item.file, targetProjectId);
          }
          saved += 1;
          update(item.id, { status: "saved", message: outcomeMessage(outcome) });
        } catch (err: unknown) {
          const message = err instanceof Error ? err.message : "Could not process this file.";
          failures.push(`${item.file.name}: ${message}`);
          update(item.id, { status: "failed", message });
        }
      }
      if (text.trim()) {
        try {
          setProgress("Adding your note...");
          const outcome = await api.ingestManualText(text.trim(), targetProjectId, "Project context note");
          saved += 1;
          setText("");
          setNotice(outcomeMessage(outcome));
        } catch (err: unknown) {
          failures.push(err instanceof Error ? err.message : "Could not save your note.");
        }
      }
      if (saved) {
        setNotice(`${saved} source${saved === 1 ? "" : "s"} processed. Review extracted context and any conflicts.`);
        try { await onChanged?.(); } catch { setNotice("Sources saved. Reopen Project Context to refresh the results."); }
      }
      if (failures.length) setError(failures.join(" "));
    } finally {
      setProgress("");
      setBusy(false);
      inFlight.current = false;
    }
  };

  return (
    <section className="min-w-0 overflow-hidden rounded-xl border border-border bg-surface shadow-xs" aria-label="Add project context" aria-busy={busy}>
      <div className="px-5 pt-5 sm:px-6 sm:pt-6">
        <h2 className="text-sm font-semibold text-text-main">Add context</h2>
        <p className="mt-1 text-xs leading-relaxed text-text-muted">Drop your files here. Synora reads the content and connects it to {selectedProject?.name || "your project"}.</p>
        {!selectedProject && <label className="mt-4 block text-xs font-medium text-text-muted">Project
          <select className="mt-1.5 w-full rounded-lg border border-border bg-surface px-3 py-2.5 text-sm" value={target} disabled={busy} onChange={event => setTarget(event.target.value)}>
            <option value="">Automatically match a project</option>
            {projects.filter(project => project.id !== "proj_unknown_context").map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
          </select>
        </label>}
      </div>

      <div className="space-y-4 p-5 sm:p-6">
        <input ref={input} type="file" multiple accept={ACCEPT} disabled={busy} className="sr-only" aria-label="Choose context files" onChange={event => { if (event.target.files) addFiles(event.target.files); }} />
        <button type="button" disabled={busy} onClick={() => input.current?.click()}
          onDragEnter={event => { event.preventDefault(); if (busy) return; dragDepth.current += 1; setDragging(true); }}
          onDragOver={event => { event.preventDefault(); event.dataTransfer.dropEffect = busy ? "none" : "copy"; }}
          onDragLeave={event => { event.preventDefault(); dragDepth.current = Math.max(0, dragDepth.current - 1); if (!dragDepth.current) setDragging(false); }}
          onDrop={event => { event.preventDefault(); dragDepth.current = 0; setDragging(false); addFiles(event.dataTransfer.files); }}
          className={`flex min-h-52 w-full flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-8 text-center transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-wait disabled:opacity-60 ${dragging ? "border-primary bg-primary/5" : "border-border bg-canvas hover:border-border-active hover:bg-surface-muted/50"}`}>
          <span className="mb-3 grid h-11 w-11 place-items-center rounded-xl border border-border bg-surface text-text-muted"><Upload className="h-5 w-5" /></span>
          <span className="text-sm font-medium text-text-main">{dragging ? "Drop files to add them" : "Drag and drop files, or browse"}</span>
          <span className="mt-2 text-xs text-text-muted">Documents, images, transcripts and audio</span>
          <span className="mt-1 max-w-sm text-[10px] leading-relaxed text-text-dim">PDF, DOCX, TXT, Markdown, CSV, TSV, VTT, SRT, PNG, JPG, WebP, MP3, M4A, WAV, OGG, Opus, WebM, FLAC · up to 10 MB per file</span>
        </button>

        {files.length > 0 && <ul className="divide-y divide-border-subtle rounded-lg border border-border" aria-label="Selected files">{files.map(item => <li key={item.id} className="flex items-start gap-3 px-3 py-3">
          {item.status === "processing" ? <LoaderCircle className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-text-muted" /> : item.status === "saved" ? <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" /> : <FileText className="mt-0.5 h-4 w-4 shrink-0 text-text-muted" />}
          <div className="min-w-0 flex-1"><p className="truncate text-xs font-medium text-text-main">{item.file.name}</p><p className={`mt-1 break-words text-[10px] ${item.status === "failed" ? "text-danger" : "text-text-muted"}`}>{item.message || `${(item.file.size / 1024 / 1024).toFixed(2)} MB · ${item.status === "processing" ? "Processing" : "Ready to add"}`}</p></div>
          <button type="button" disabled={busy} aria-label={`Remove ${item.file.name}`} onClick={() => setFiles(current => current.filter(file => file.id !== item.id))} className="rounded p-1 text-text-muted hover:bg-canvas disabled:opacity-40"><X className="h-3.5 w-3.5" /></button>
        </li>)}</ul>}

        <button type="button" disabled={busy} onClick={() => setShowText(current => !current)} aria-expanded={showText} aria-controls="context-text-input" className="inline-flex items-center gap-1.5 text-xs font-medium text-text-muted hover:text-text-main disabled:opacity-50"><Plus className="h-3.5 w-3.5" />{showText ? "Hide text editor" : "Or paste text"}</button>
        {showText && <div id="context-text-input"><label htmlFor="context-note" className="sr-only">Text or transcript</label><textarea id="context-note" value={text} maxLength={200000} disabled={busy} onChange={event => setText(event.target.value)} rows={6} placeholder="Paste notes, requirements, or a transcript..." className="w-full resize-y rounded-lg border border-border bg-surface px-3 py-2.5 text-sm leading-relaxed outline-none focus:border-border-active focus:ring-2 focus:ring-black/5" /><p className="mt-1 text-right text-[10px] text-text-dim">{text.length.toLocaleString()} / 200,000</p></div>}

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border-subtle pt-4">
          <p className="max-w-sm text-[10px] leading-relaxed text-text-dim">Original sources stay linked. Conflicting changes are held for review.</p>
          <button type="button" onClick={() => { void submit(); }} disabled={busy || (!pendingFiles.length && !text.trim())} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-primary px-4 text-xs font-semibold text-white transition hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50">{busy ? <><LoaderCircle className="h-3.5 w-3.5 animate-spin" />Processing...</> : "Add to project"}</button>
        </div>
        {progress && <p role="status" className="text-xs text-text-muted">{progress}</p>}
        {notice && <p role="status" className="rounded-lg border border-border bg-canvas px-3 py-2 text-xs text-text-main">{notice}</p>}
        {error && <p role="alert" className="rounded-lg border border-danger/20 bg-danger/5 px-3 py-2 text-xs text-danger">{error}</p>}
      </div>
    </section>
  );
}
