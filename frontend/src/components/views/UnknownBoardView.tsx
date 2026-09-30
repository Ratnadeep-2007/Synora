"use client";

import React from "react";
import { Inbox } from "lucide-react";
import { ExcalidrawCanvas } from "@/components/canvas/ExcalidrawCanvas";

interface UnknownNote {
  item_id: string;
  content: string;
  sender: string;
  source: string;
  suggested_project: string;
  reasons: string[];
  created_at: string | null;
}

interface UnknownBoardViewProps {
  board?: {
    version?: number;
    elements?: any[];
    app_state?: any;
    pending_notes?: UnknownNote[];
  } | null;
}

export function UnknownBoardView({ board }: UnknownBoardViewProps) {
  const notes = board?.pending_notes || [];
  return (
    <section className="rounded-2xl border border-dashed border-warning/30 bg-surface shadow-xs overflow-hidden">
      <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
        <div className="flex items-center gap-2">
          <Inbox className="h-4 w-4 text-warning" />
          <div>
            <h2 className="text-sm font-semibold text-text-main">Unknown Context board</h2>
            <p className="text-[11px] text-text-muted">
              Agent-kept notes the classifier could not place — each shows where it should go. No human triage needed.
            </p>
          </div>
        </div>
        <span className="rounded-full border border-warning/20 bg-warning/5 px-2.5 py-1 text-[10px] font-semibold text-warning">
          {notes.length} unassigned
        </span>
      </div>

      <div className="p-2">
        <ExcalidrawCanvas
          key={`unknown-${board?.version || 0}`}
          projectId="proj_unknown_context"
          projectName="Unknown Context Board"
          version={board?.version || 1}
          initialElements={board?.elements || []}
          initialAppState={board?.app_state}
          compareMode={false}
          onSaveCanvas={undefined}
          onExportJson={undefined}
        />
      </div>

      {notes.length > 0 && (
        <div className="space-y-2 border-t border-border px-5 py-4">
          {notes.map((note) => (
            <div key={note.item_id} className="rounded-lg border border-border bg-canvas p-3 text-xs">
              <div className="font-medium text-text-main line-clamp-2">{note.content}</div>
              <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] text-text-muted">
                <span>
                  {note.sender} via {note.source}
                </span>
                <span className="rounded-full bg-primary-soft px-2 py-0.5 font-semibold text-primary">
                  Should go to: {note.suggested_project || "no confident project yet"}
                </span>
              </div>
              {note.reasons.length > 0 && (
                <div className="mt-1 text-[11px] text-text-muted">
                  Why: {note.reasons.slice(0, 2).join("; ")}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
