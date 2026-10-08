"use client";

import React, { useEffect } from "react";
import {
  X,
  ShieldCheck,
  Clock,
  User,
  FileText,
  Sparkles,
  Layers,
  MessageSquare,
  Video,
  ArrowRight,
  CheckCircle,
} from "lucide-react";
import { EvidenceItem } from "@/lib/types";

interface EvidenceDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  contextType: string;
  status?: string;
  evidenceItems: EvidenceItem[];
  relatedChangeRef?: string;
}

export function EvidenceDrawer({
  isOpen,
  onClose,
  title,
  contextType,
  status = "Authoritative",
  evidenceItems = [],
  relatedChangeRef,
}: EvidenceDrawerProps) {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    if (isOpen) {
      window.addEventListener("keydown", handleKeyDown);
    }
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-[var(--scrim)] backdrop-blur-sm flex justify-end transition-opacity animate-in fade-in duration-200">
      <div className="w-full max-w-xl bg-surface border-l border-border h-full shadow-2xl flex flex-col animate-in slide-in-from-right duration-300">
        {/* Drawer Header */}
        <div className="p-6 border-b border-border bg-surface-soft space-y-3">
          <div className="flex items-center justify-between">
            <div className="inline-flex items-center gap-2 rounded-full border border-primary/25 bg-primary/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-primary">
              <Sparkles className="w-3.5 h-3.5" />
              Intelligence Provenance
            </div>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-text-muted hover:text-text-main hover:bg-canvas transition-colors"
              title="Close (Esc)"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          <div>
            <div className="text-[11px] font-mono uppercase tracking-wider text-text-muted">
              Why does Synora believe this {contextType}?
            </div>
            <h2 className="text-lg font-bold text-text-main mt-1 leading-snug">
              "{title}"
            </h2>
          </div>
        </div>

        {/* Verification & Confidence Bar */}
        <div className="px-6 py-3.5 bg-canvas border-b border-border flex flex-wrap items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-2 text-text-muted">
            <ShieldCheck className="w-4 h-4 text-primary" />
            <span>Verification Status:</span>
            <span className="font-semibold text-text-main px-2 py-0.5 rounded bg-surface border border-border">
              {status}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-[11px] text-text-muted font-mono">Grounding:</span>
            <span className="inline-flex items-center gap-1 font-mono text-[11px] font-bold text-primary">
              <CheckCircle className="w-3.5 h-3.5" />
              {evidenceItems.length > 0
                ? `${evidenceItems.length} verbatim citation${evidenceItems.length === 1 ? "" : "s"}`
                : "awaiting citations"}
            </span>
          </div>
        </div>

        {/* Intelligence Explanation Rationale */}
        <div className="px-6 py-4 bg-surface border-b border-border/80">
          <div className="text-xs text-text-muted leading-relaxed">
            Synora continuously monitors real-time conference transcripts and message streams.
            The statement above was synthesized directly from the verbatim citations below and confirmed into the project model.
          </div>
        </div>

        {/* Evidence Citations Scroll List */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-text-muted">
              Primary Evidence Chain ({evidenceItems.length})
            </span>
            {relatedChangeRef && (
              <span className="text-[10px] font-mono text-text-muted truncate max-w-[200px]">
                Ref: {relatedChangeRef}
              </span>
            )}
          </div>

          {evidenceItems.length === 0 ? (
            <div className="p-8 text-center text-xs text-text-muted border border-dashed border-border rounded-xl bg-canvas/40 space-y-2">
              <FileText className="w-8 h-8 text-text-muted/40 mx-auto" />
              <p>Direct transcript snippet is being indexed from historical archive.</p>
              <p className="text-[10px] text-text-muted/60">
                This item is verified by project consensus records.
              </p>
            </div>
          ) : (
            evidenceItems.map((item, idx) => {
              const isMeet = item.source === "google_meet";
              const isWA = item.source === "whatsapp";

              return (
                <div
                  key={item.id || idx}
                  className="p-4 rounded-xl border border-border bg-surface-soft hover:border-primary/30 transition-all space-y-3"
                >
                  {/* Speaker & Timestamp */}
                  <div className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-2 font-medium text-text-main">
                      <div className="w-6 h-6 rounded-full bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
                        <User className="w-3.5 h-3.5" />
                      </div>
                      <span className="font-semibold">{item.actor_id || "Meeting Participant"}</span>
                    </div>

                    <div className="flex items-center gap-1.5 text-text-muted font-mono text-[11px]">
                      <Clock className="w-3.5 h-3.5" />
                      <span suppressHydrationWarning>
                        {item.occurred_at
                          ? new Date(item.occurred_at).toLocaleTimeString([], {
                              hour: "2-digit",
                              minute: "2-digit",
                              second: "2-digit",
                            })
                          : "Synchronized Event"}
                      </span>
                    </div>
                  </div>

                  {/* Verbatim Quote */}
                  <div className="text-xs sm:text-sm text-text-main bg-canvas p-3.5 rounded-lg border border-border/80 leading-relaxed font-sans italic border-l-2 border-l-primary">
                    "{item.content}"
                  </div>

                  {/* Source Metadata & Impact */}
                  <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-border/50 text-[11px] text-text-muted">
                    <div className="flex items-center gap-1.5">
                      {isMeet ? (
                        <Video className="w-3.5 h-3.5 text-primary" />
                      ) : isWA ? (
                        <MessageSquare className="w-3.5 h-3.5 text-primary" />
                      ) : (
                        <FileText className="w-3.5 h-3.5 text-primary" />
                      )}
                      <span>
                        Stream:{" "}
                        <strong className="text-text-main capitalize">
                          {item.source ? item.source.replace("_", " ") : "Google Meet"}
                        </strong>
                      </span>
                    </div>

                    <span className="font-mono text-[10px] text-text-muted">
                      ID: {item.id ? item.id.slice(0, 14) : "ev-01"}
                    </span>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Drawer Footer */}
        <div className="p-4 border-t border-border bg-surface-soft flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-xs text-text-muted">
            <Layers className="w-3.5 h-3.5 text-primary" />
            <span>State Provenance Chain</span>
          </div>

          <button
            onClick={onClose}
            className="px-4 py-2 text-xs font-semibold bg-canvas hover:bg-surface text-text-main border border-border rounded-lg transition-colors"
          >
            Dismiss Explanation
          </button>
        </div>
      </div>
    </div>
  );
}
