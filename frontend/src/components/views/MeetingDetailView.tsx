"use client";

import React, { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, FileText, GitBranch, List, MessageSquareText, Trash2 } from "lucide-react";
import { CandidateKnowledgeItem } from "@/lib/types";
import { ExcalidrawCanvas } from "@/components/canvas/ExcalidrawCanvas";

interface MeetingDetailViewProps {
  meetingId: string;
  meetingData: any;
  meetingCanvas?: any;
  candidates: CandidateKnowledgeItem[];
  onBack: () => void;
  onOpenEvidence: (title: string, contextType: string, evidenceIds: string[]) => void;
  onDeleteMeeting?: (meetingId: string) => Promise<void>;
  onSaveCanvas?: (projectId: string, scene: { name?: string; elements: any[]; app_state?: any }) => Promise<void>;
}

type NoteElement = {
  id: string; type: string; text?: string; x?: number; y?: number; isDeleted?: boolean;
  customData?: { visual?: { type?: string; evidence_ids?: string[] } };
};
type NoteSection = { id: string; title: string; notes: { id: string; text: string; sourceIds: string[] }[] };

// The readable notes and diagram editor consume the same persisted notebook.
function notebookSections(elements: NoteElement[]): NoteSection[] {
  const sections: NoteSection[] = [];
  const ordered = elements.filter(element => !element.isDeleted && element.type === "text" && element.text?.trim())
    .sort((a, b) => (a.y || 0) - (b.y || 0) || (a.x || 0) - (b.x || 0));
  for (const element of ordered) {
    const visual = element.customData?.visual;
    if (visual?.type === "note_section_header") {
      sections.push({ id: element.id, title: element.text!.trim(), notes: [] });
    } else if (visual?.type === "note_block") {
      const text = element.text!.replace(/\s+/g, " ").trim();
      if (!text || /[\u0900-\u0dff]/.test(text) || /^English translation pending\b/i.test(text)) continue;
      if (!sections.length) sections.push({ id: "notes", title: "Meeting notes", notes: [] });
      const section = sections[sections.length - 1];
      const duplicate = section.notes.find(note => note.text.toLowerCase() === text.toLowerCase());
      if (duplicate) duplicate.sourceIds = Array.from(new Set([...duplicate.sourceIds, ...(visual.evidence_ids || [])]));
      else section.notes.push({ id: element.id, text, sourceIds: visual.evidence_ids || [] });
    }
  }
  return sections.filter(section => section.notes.length);
}

export function MeetingDetailView({ meetingId, meetingData, meetingCanvas, candidates, onBack, onOpenEvidence, onDeleteMeeting, onSaveCanvas }: MeetingDetailViewProps) {
  const [deleting, setDeleting] = useState(false);
  const [sourceIds, setSourceIds] = useState<string[]>([]);
  useEffect(() => { setSourceIds([]); }, [meetingId]);
  const meeting = meetingData?.meeting || meetingData || {};
  const entries: any[] = useMemo(() => ((meetingData?.transcripts || meetingData?.meeting?.transcripts || []) as any[])
    .flatMap(transcript => transcript.entries || [])
    .filter(entry => !["meeting title", "date", "participants", "meeting id"].includes(String(entry.participant_display_name || entry.participant_name || entry.speaker || "").toLowerCase()))
    .sort((a, b) => String(a.start_time || "").localeCompare(String(b.start_time || ""))), [meetingData]);
  const artifact = meetingCanvas?.artifact;
  const elements: NoteElement[] = artifact?.elements || [];
  const sections = useMemo(() => notebookSections(artifact?.elements || []), [artifact?.elements]);
  const noteCount = sections.reduce((count, section) => count + section.notes.length, 0);
  const hasDiagram = elements.some(element => !element.isDeleted && ["arrow", "line"].includes(element.type));
  const entryIds = new Set(entries.map(entry => entry.id));
  const activeCandidates = candidates.filter(candidate => !["superseded", "rejected"].includes(candidate.status));
  const pendingTranslations = artifact?.app_state?.meeting_canvas?.translation_pending_count || 0;

  const showSource = (ids: string[]) => {
    const linked = ids.filter(id => entryIds.has(id));
    setSourceIds(linked);
    if (linked[0]) document.getElementById(`transcript-${linked[0]}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };
  const deleteMeeting = async () => {
    if (!window.confirm("Delete this meeting and its transcript? Evidence rows are kept but unlinked so project knowledge keeps provenance.")) return;
    setDeleting(true);
    try { await onDeleteMeeting?.(meetingId); } finally { setDeleting(false); }
  };

  return (
    <div className="space-y-5 view-enter">
      <header className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <button type="button" onClick={onBack} className="inline-flex items-center gap-1.5 text-xs font-medium text-text-muted hover:text-text-main"><ArrowLeft className="h-4 w-4" /> Back to Meetings</button>
          {onDeleteMeeting && <button type="button" onClick={deleteMeeting} disabled={deleting} className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs text-danger hover:bg-danger/10 disabled:opacity-50"><Trash2 className="h-3.5 w-3.5" />{deleting ? "Deleting..." : "Delete meeting"}</button>}
        </div>
        <div><p className="text-xs font-medium text-text-muted">Meeting notes</p><h1 className="mt-1 text-2xl font-semibold tracking-tight text-text-main">{meeting.title || "Meeting"}</h1><p className="mt-1 text-xs text-text-muted">Follow the transcript, read the English notes, and explore the discussion visually.</p></div>
      </header>

      <div aria-label="Meeting notes workflow" className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3 text-xs">
        <a href="#meeting-transcript" className="inline-flex items-center gap-2 font-medium text-text-main"><MessageSquareText className="h-4 w-4 text-primary" />Transcript <span className="text-text-muted">{entries.length} turns</span></a><ArrowRight className="h-3.5 w-3.5 text-text-muted" aria-hidden="true" />
        <a href="#meeting-bullet-notes" className="inline-flex items-center gap-2 font-medium text-text-main"><List className="h-4 w-4 text-primary" />English notes <span className="text-text-muted">{noteCount || "Pending"}</span></a><ArrowRight className="h-3.5 w-3.5 text-text-muted" aria-hidden="true" />
        <a href="#meeting-diagrams" className="inline-flex items-center gap-2 font-medium text-text-main"><GitBranch className="h-4 w-4 text-primary" />Diagrams <span className="text-text-muted">{hasDiagram ? "Available" : "Pending"}</span></a>
      </div>

      <div className="grid min-w-0 items-start gap-5 xl:grid-cols-[minmax(280px,0.8fr)_minmax(0,2fr)]">
        <section id="meeting-transcript" aria-label="Meeting transcript" className="min-w-0 scroll-mt-24 overflow-hidden rounded-xl border border-border bg-surface xl:sticky xl:top-20">
          <div className="border-b border-border px-4 py-3"><h2 className="flex items-center gap-2 text-sm font-semibold text-text-main"><MessageSquareText className="h-4 w-4 text-primary" />Transcript</h2><p className="mt-1 text-[11px] text-text-muted">Original discussion, kept in the language spoken.</p></div>
          <div className="max-h-[400px] space-y-3 overflow-y-auto p-4 xl:max-h-[75vh]">
            {entries.length ? entries.map((entry, index) => {
              const name = entry.participant_display_name || entry.participant_name || entry.speaker || "Unknown Speaker";
              const selected = sourceIds.includes(entry.id);
              return <article key={entry.id || index} id={`transcript-${entry.id}`} aria-label={`Transcript turn ${index + 1}`} className={`scroll-mt-3 rounded-lg border p-3 transition-colors ${selected ? "border-primary bg-primary-soft ring-1 ring-primary/30" : "border-border bg-canvas/40"}`}>
                <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2 text-[10px] text-text-muted"><span className="font-semibold text-text-main">{name}</span>{entry.start_time && <time dateTime={entry.start_time}>{new Date(entry.start_time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time>}</div>
                <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-text-main">{entry.text}</p>{selected && <span className="mt-2 block text-[10px] font-medium text-primary">Source for selected note</span>}
              </article>;
            }) : <p className="py-8 text-center text-xs text-text-muted">The transcript will appear here when capture is processed.</p>}
          </div>
        </section>

        <div className="min-w-0 space-y-5">
          <section id="meeting-bullet-notes" aria-label="English bullet notes" className="scroll-mt-24 overflow-hidden rounded-xl border border-border bg-surface">
            <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-3"><div><h2 className="flex items-center gap-2 text-sm font-semibold text-text-main"><FileText className="h-4 w-4 text-primary" />English notes</h2><p className="mt-1 text-[11px] text-text-muted">Bullet points from the same notebook shown in the diagram workspace.</p></div><span className="shrink-0 rounded-md bg-canvas px-2 py-1 text-[10px] font-medium text-text-muted">Draft</span></div>
            <div className="max-h-[480px] space-y-5 overflow-y-auto p-5">
              {pendingTranslations > 0 && <p role="status" className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">{pendingTranslations} discussion {pendingTranslations === 1 ? "entry is" : "entries are"} waiting for English translation.</p>}
              {sections.length ? sections.map(section => <section key={section.id} aria-label={section.title}><h3 className="mb-2 text-xs font-semibold text-text-main">{section.title}</h3><ul className="list-disc space-y-3 pl-4 text-xs leading-relaxed text-text-main marker:text-text-muted">
                {section.notes.map(note => <li key={note.id} className="pl-1"><span className="break-words">{note.text}</span>{note.sourceIds.some(id => entryIds.has(id)) && <button type="button" onClick={() => showSource(note.sourceIds)} aria-label={`Show transcript source for: ${note.text}`} className="ml-2 inline-flex text-[10px] font-medium text-primary underline decoration-primary/30 underline-offset-2 hover:decoration-primary">Show source</button>}</li>)}
              </ul></section>) : <p className="py-6 text-xs text-text-muted">English bullet notes will appear here after the meeting is analyzed.</p>}
            </div>
          </section>

          <section id="meeting-diagrams" aria-label="Meeting diagrams and visual notes" className="min-w-0 scroll-mt-24 overflow-hidden rounded-xl border border-border bg-surface">
            <div className="border-b border-border px-5 py-3"><h2 className="flex items-center gap-2 text-sm font-semibold text-text-main"><GitBranch className="h-4 w-4 text-primary" />Diagrams &amp; visual notes</h2><p className="mt-1 text-[11px] text-text-muted">Explore the flow and relationships alongside the transcript. Use fullscreen for more room.</p></div>
            <div className="min-w-0 p-2">{artifact ? <ExcalidrawCanvas key={artifact.id} projectId={artifact.project_id} projectName={meeting.title || "Meeting notes"} version={artifact.version || 1} initialElements={artifact.elements || []} initialAppState={{ ...(artifact.app_state || {}), theme: "light", viewBackgroundColor: "#ffffff" }} onSaveCanvas={onSaveCanvas && artifact.project_id ? scene => onSaveCanvas(artifact.project_id, scene) : undefined} /> : <div className="flex min-h-[320px] items-center justify-center p-6 text-center text-xs text-text-muted">The diagram workspace will appear when meeting analysis is ready.</div>}</div>
          </section>

          <details className="rounded-xl border border-border bg-surface"><summary className="cursor-pointer px-5 py-3 text-xs font-semibold text-text-main">Review extracted items ({activeCandidates.length})</summary><div className="max-h-[420px] space-y-3 overflow-y-auto border-t border-border p-5">
            {activeCandidates.length ? activeCandidates.map(candidate => <article key={candidate.id} className="rounded-lg border border-border p-3"><div className="mb-2 flex flex-wrap gap-2 text-[10px] text-text-muted"><span className="capitalize">{candidate.category.replace(/_candidate$/, "").replace(/_/g, " ")}</span><span>{candidate.status || "Needs review"}</span></div><p className="text-xs leading-relaxed text-text-main">{candidate.content}</p><button type="button" onClick={() => onOpenEvidence(candidate.title, candidate.category, candidate.evidence_ids || [])} className="mt-2 text-[11px] font-medium text-primary underline underline-offset-2">View evidence</button></article>) : <p className="text-xs text-text-muted">No extracted items to review yet.</p>}
          </div></details>
        </div>
      </div>
    </div>
  );
}
