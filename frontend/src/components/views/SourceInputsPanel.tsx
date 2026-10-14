"use client";

import { useState } from "react";
import { SourceArtifactPreview } from "@/components/common/SourceArtifactPreview";
import { AudioLines, FileText, ImagePlus, LoaderCircle, Upload } from "lucide-react";
import { api, InputOutcome } from "@/lib/api";
import { Project } from "@/lib/types";

export function SourceInputsPanel({ projects, selectedProject, onChanged }: {
  projects: Project[];
  selectedProject?: Project | null;
  onChanged?: () => Promise<void> | void;
}) {
  const [target, setTarget] = useState(selectedProject?.id || "");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [docFile, setDocFile] = useState<File | null>(null);
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [audioArtifactId, setAudioArtifactId] = useState<string | undefined>();
  const [retainOriginal, setRetainOriginal] = useState(true);
  const [imagePreview, setImagePreview] = useState("");
  const [busy, setBusy] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [transcriptNote, setTranscriptNote] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState<InputOutcome | null>(null);
  const targetProjectId = selectedProject?.id || target || undefined;
  const inputClass = "w-full rounded-lg border border-border bg-surface px-3 py-2.5 text-sm text-text-main placeholder:text-text-dim outline-none transition focus:border-border-active focus:ring-2 focus:ring-black/5";
  const buttonClass = "inline-flex h-9 items-center justify-center gap-2 rounded-lg bg-primary px-3.5 text-xs font-semibold text-white transition hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50";

  const pickImage = (file: File | null) => {
    setImageFile(file);
    setImagePreview((prev) => {
      if (prev.startsWith("blob:")) URL.revokeObjectURL(prev);
      return file ? URL.createObjectURL(file) : "";
    });
  };

  const run = async (action: () => Promise<InputOutcome>) => {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const outcome = await action();
      setResult(outcome);
      if (outcome.outcome === "resolved" || outcome.outcome === "duplicate") {
        setText("");
        setTitle("");
        setDocFile(null);
        setAudioFile(null);
        setAudioArtifactId(undefined);
        pickImage(null);
        setTranscriptNote("");
      }
      await onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Submission failed");
    } finally {
      setBusy(false);
    }
  };

  const transcribe = async () => {
    if (!audioFile) return;
    setTranscribing(true);
    setError("");
    setTranscriptNote("");
    try {
      const response = await api.transcribeContextAudio(audioFile, targetProjectId, retainOriginal);
      setAudioArtifactId(response.artifact_id);
      if (!response.success) throw new Error(response.error || "Transcription needs a retry. The original recording is retained.");
      setText(response.text);
      setTitle(`Audio transcript — ${response.filename}`);
      const duration = response.duration_seconds ? ` · ${Math.round(response.duration_seconds)} sec` : "";
      setTranscriptNote(`Transcript ready${duration}. Review or edit it before adding it to project memory.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Audio transcription failed");
    } finally {
      setTranscribing(false);
    }
  };

  return (
    <section className="overflow-hidden rounded-xl border border-border bg-surface shadow-xs">
      <div className="border-b border-border-subtle px-5 py-4 sm:px-6">
        <div className="flex items-start gap-3">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-border bg-surface-muted text-text-muted"><Upload className="h-4 w-4" /></span>
          <div>
            <h2 className="text-sm font-semibold text-text-main">Add project context</h2>
            <p className="mt-1 text-xs leading-relaxed text-text-muted">Add a focused note, document, transcript, or audio. Synora extracts useful facts and keeps the original evidence linked for traceability.</p>
          </div>
        </div>
        {!selectedProject && (
          <label className="mt-4 block max-w-sm space-y-1.5 text-xs font-medium text-text-muted">
            Route to project
            <select className={inputClass} value={target} disabled={busy || transcribing} onChange={(event) => setTarget(event.target.value)}>
              <option value="">Automatically match a project</option>
              {projects.filter((project) => project.id !== "proj_unknown_context" && !(project as any).is_system).map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
            </select>
          </label>
        )}
      </div>

      <div className="grid gap-0 lg:grid-cols-[1.1fr_.9fr]">
        <div className="space-y-4 border-b border-border-subtle p-5 sm:p-6 lg:border-b-0 lg:border-r">
          <div>
            <label htmlFor="context-title" className="mb-1.5 block text-xs font-semibold text-text-main">Source title <span className="font-normal text-text-dim">(optional)</span></label>
            <input id="context-title" className={inputClass} value={title} maxLength={255} onChange={(event) => setTitle(event.target.value)} placeholder="e.g. Product discovery meeting — Oct 13" />
          </div>
          <div>
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <label htmlFor="manual-source" className="text-xs font-semibold text-text-main">Text or transcript</label>
              <span className="text-[10px] tabular-nums text-text-dim">{text.length.toLocaleString()} / 200,000</span>
            </div>
            <textarea id="manual-source" className={`${inputClass} min-h-52 resize-y leading-relaxed`} rows={9} value={text} maxLength={200000} disabled={busy || transcribing}
              onChange={(event) => setText(event.target.value)} placeholder="Paste meeting notes, decisions, requirements, or a transcript…" />
            {transcriptNote && <p className="mt-2 text-[11px] leading-relaxed text-text-muted" role="status">{transcriptNote}</p>}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border-subtle pt-4">
            <p className="max-w-sm text-[10px] leading-relaxed text-text-dim">Useful project facts are extracted into memory. The source remains available as evidence; repeated facts are deduplicated by the memory pipeline.</p>
            <button className={buttonClass} disabled={busy || transcribing || !text.trim()} onClick={() => run(() => api.ingestManualText(text, targetProjectId, title.trim() || "Project context note", audioArtifactId))}>
              {busy ? <><LoaderCircle className="h-3.5 w-3.5 animate-spin" /> Processing…</> : "Add to project memory"}
            </button>
          </div>
        </div>

        <div className="space-y-5 p-5 sm:p-6">
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-text-main"><FileText className="h-3.5 w-3.5 text-text-muted" /> Documents and images</div>
            <label htmlFor="source-doc" className="flex min-h-24 cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed border-border bg-canvas px-4 py-4 text-center transition hover:border-border-active hover:bg-surface-muted/60">
              <Upload className="mb-2 h-4 w-4 text-text-muted" />
              <span className="text-xs font-medium text-text-main">{docFile?.name || "Choose a document"}</span>
              <span className="mt-1 text-[10px] text-text-dim">TXT, Markdown, CSV, VTT, SRT, PDF or DOCX · max 10 MB</span>
              <input id="source-doc" className="sr-only" type="file" disabled={busy} accept=".txt,.md,.csv,.tsv,.vtt,.srt,.pdf,.docx" onChange={(event) => setDocFile(event.target.files?.[0] || null)} />
            </label>
            <button className={`${buttonClass} mt-2`} disabled={busy || !docFile} onClick={() => docFile && run(() => api.uploadSourceFile(docFile, targetProjectId, title.trim() || undefined))}>Process document</button>
          </div>

          <div className="border-t border-border-subtle pt-5">
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-text-main"><ImagePlus className="h-3.5 w-3.5 text-text-muted" /> Image or whiteboard</div>
            <label htmlFor="source-image" className="flex min-h-20 cursor-pointer items-center gap-3 rounded-lg border border-dashed border-border bg-canvas px-4 py-3 transition hover:border-border-active hover:bg-surface-muted/60">
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-border bg-surface text-text-muted"><ImagePlus className="h-4 w-4" /></span>
              <span className="min-w-0"><span className="block truncate text-xs font-medium text-text-main">{imageFile?.name || "Choose an image"}</span><span className="mt-1 block text-[10px] text-text-dim">PNG, JPG or WebP · max 10 MB</span></span>
              <input id="source-image" className="sr-only" type="file" disabled={busy} accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp" onChange={(event) => pickImage(event.target.files?.[0] || null)} />
            </label>
            {imagePreview && <img src={imagePreview} alt="Selected context upload preview" className="mt-2 max-h-32 rounded-md border border-border object-contain" />}
            <button className={`${buttonClass} mt-2`} disabled={busy || !imageFile} onClick={() => imageFile && run(() => api.uploadSourceFile(imageFile, targetProjectId, title.trim() || undefined))}>Analyze image</button>
          </div>

          <div className="border-t border-border-subtle pt-5">
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-text-main"><AudioLines className="h-3.5 w-3.5 text-text-muted" /> Audio recording</div>
            <label htmlFor="context-audio" className="flex min-h-20 cursor-pointer items-center gap-3 rounded-lg border border-dashed border-border bg-canvas px-4 py-3 transition hover:border-border-active hover:bg-surface-muted/60">
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-border bg-surface text-text-muted"><AudioLines className="h-4 w-4" /></span>
              <span className="min-w-0"><span className="block truncate text-xs font-medium text-text-main">{audioFile?.name || "Choose an audio file"}</span><span className="mt-1 block text-[10px] text-text-dim">MP3, M4A, WAV, OGG, WebM or FLAC · max 10 MB</span></span>
              <input id="context-audio" className="sr-only" type="file" disabled={busy || transcribing} accept="audio/*,.mp3,.m4a,.ogg,.opus,.webm,.wav,.flac" onChange={(event) => { setAudioFile(event.target.files?.[0] || null); setTranscriptNote(""); }} />
            </label>
            <button className={`${buttonClass} mt-2`} disabled={!audioFile || busy || transcribing} onClick={transcribe}>
              {transcribing ? <><LoaderCircle className="h-3.5 w-3.5 animate-spin" /> Transcribing…</> : "Transcribe to editable text"}
            </button>
            <label className="mt-3 flex items-center gap-2 text-[11px] text-text-muted"><input type="checkbox" checked={retainOriginal} onChange={(event) => setRetainOriginal(event.target.checked)} />Keep the original recording with the transcript</label>
            <p className="mt-2 text-[10px] leading-relaxed text-text-dim">Review the transcript before submitting. Retained recordings remain available for source inspection and retry.</p>
            <SourceArtifactPreview artifactId={audioArtifactId} onUseTranscript={setText} />
          </div>
        </div>
      </div>

      {(error || result) && <div className="border-t border-border-subtle px-5 py-4 sm:px-6">
        {error && <p role="alert" className="rounded-lg border border-danger/20 bg-danger/5 px-3 py-2 text-xs text-danger">{error}</p>}
        {result && <div role="status" className="rounded-lg border border-border bg-surface-muted/60 px-3.5 py-3 text-xs">
          <strong className="text-text-main">{result.outcome === "unknown_context" ? "Saved in Context Inbox for review" : result.outcome === "resolved" && result.conflicts_detected ? `${result.conflicts_detected} conflict${result.conflicts_detected === 1 ? "" : "s"} need review` : result.outcome === "resolved" ? "Source added to project memory" : result.outcome === "duplicate" ? "This source was already submitted" : "No project memory change"}</strong>
          <p className="mt-1 leading-relaxed text-text-muted">{result.conflicts_detected ? "The conflicting proposal was held out of memory. Review it below before deciding whether to replace the current project decision." : result.reason}</p>
          {!!result.candidates_created && <p className="mt-1 text-[10px] text-text-dim">{result.candidates_created} memory candidate{result.candidates_created === 1 ? "" : "s"} extracted · evidence ID {result.evidence_id || "pending"}</p>}
        </div>}
      </div>}
    </section>
  );
}
