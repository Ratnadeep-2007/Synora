"use client";

import React from "react";
import { X, ShieldCheck, Clock, User, Link as LinkIcon, FileText } from "lucide-react";
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
  evidenceItems,
  relatedChangeRef,
}: EvidenceDrawerProps) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-text-main/20 backdrop-blur-xs flex justify-end transition-opacity">
      <div className="w-full max-w-lg bg-surface border-l border-border h-full shadow-2xl flex flex-col animate-in slide-in-from-right duration-200">
        {/* Header */}
        <div className="p-6 border-b border-border flex items-center justify-between bg-surface-soft">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-primary px-2 py-0.5 rounded bg-primary-soft border border-primary/20">
                Evidence Provenance
              </span>
              <span className="text-[11px] font-medium text-text-muted capitalize">
                {contextType}
              </span>
            </div>
            <h2 className="text-base font-semibold text-text-main leading-snug line-clamp-2">
              {title}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-text-muted hover:text-text-main hover:bg-canvas transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Status / Attribution bar */}
        <div className="px-6 py-3 bg-canvas border-b border-border flex items-center justify-between text-xs">
          <div className="flex items-center gap-1.5 text-text-muted">
            <ShieldCheck className="w-4 h-4 text-primary" />
            <span>Verification Status:</span>
            <span className="font-semibold text-text-main capitalize">{status}</span>
          </div>
          {relatedChangeRef && (
            <div className="flex items-center gap-1 text-text-muted truncate max-w-[200px]">
              <LinkIcon className="w-3.5 h-3.5 text-primary" />
              <span className="truncate">{relatedChangeRef}</span>
            </div>
          )}
        </div>

        {/* Content list */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          <div className="text-xs font-semibold uppercase tracking-wider text-text-muted">
            Supporting Evidence ({evidenceItems.length})
          </div>

          {evidenceItems.length === 0 ? (
            <div className="p-8 text-center text-sm text-text-muted border border-dashed border-border rounded-lg bg-canvas/50">
              No direct transcript snippets linked to this item.
            </div>
          ) : (
            evidenceItems.map((item, idx) => (
              <div
                key={item.id || idx}
                className="p-4 rounded-lg border border-border bg-surface shadow-xs space-y-2.5"
              >
                <div className="flex items-center justify-between text-xs text-text-muted">
                  <div className="flex items-center gap-1.5 font-medium text-text-main">
                    <User className="w-3.5 h-3.5 text-primary" />
                    <span>{item.actor_id || "Meeting Participant"}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <Clock className="w-3.5 h-3.5" />
                    <span suppressHydrationWarning>{item.occurred_at ? new Date(item.occurred_at).toLocaleTimeString() : "Conference"}</span>
                  </div>
                </div>

                <div className="text-sm text-text-main bg-canvas/60 p-3 rounded border border-border/60 leading-relaxed font-sans italic">
                  "{item.content}"
                </div>

                <div className="flex items-center justify-between text-[11px] text-text-muted pt-1 border-t border-border/40">
                  <div className="flex items-center gap-1">
                    <FileText className="w-3 h-3 text-primary" />
                    <span>Source: <strong className="text-text-main">{item.source || "Google Meet"}</strong></span>
                  </div>
                  <span className="font-mono text-[10px] text-text-muted">{item.id}</span>
                </div>
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-border bg-surface-soft flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 text-xs font-medium bg-canvas hover:bg-border/60 text-text-main border border-border rounded-md transition-colors"
          >
            Close Provenance
          </button>
        </div>
      </div>
    </div>
  );
}
