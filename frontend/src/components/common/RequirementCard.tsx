"use client";

import React from "react";

interface RequirementCardProps {
  id?: string;
  title: string;
  content: string;
  onOpenEvidence?: () => void;
}

export function RequirementCard({ id, title, content, onOpenEvidence }: RequirementCardProps) {
  return (
    <div className="py-3 flex items-start justify-between gap-4">
      <div>
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-text-main">{title}</span>
          {id && <span className="text-[11px] font-mono text-text-muted">{id}</span>}
        </div>
        <div className="text-xs text-text-muted mt-0.5 leading-relaxed">{content}</div>
      </div>
      {onOpenEvidence && (
        <button
          onClick={onOpenEvidence}
          className="px-2 py-1 rounded text-[11px] font-semibold text-primary bg-primary-soft hover:bg-primary/20 border border-primary/20 shrink-0 transition-colors"
        >
          Why?
        </button>
      )}
    </div>
  );
}
