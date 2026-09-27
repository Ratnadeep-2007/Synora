"use client";

import React from "react";
import { Clock, User } from "lucide-react";
import { StatusBadge } from "./StatusBadge";

interface DecisionCardProps {
  id?: string;
  text: string;
  status: "confirmed" | "proposed" | "superseded" | "rejected" | "needs_review";
  approvedBy?: string;
  date?: string;
  onOpenEvidence?: () => void;
}

const STATUS_LABEL: Record<DecisionCardProps["status"], string> = {
  confirmed: "Confirmed",
  proposed: "Proposed",
  superseded: "Superseded",
  rejected: "Rejected",
  needs_review: "Needs review",
};

const STATUS_KIND = {
  confirmed: "success",
  proposed: "info",
  superseded: "neutral",
  rejected: "failed",
  needs_review: "review",
} as const;

export function DecisionCard({
  id,
  text,
  status,
  approvedBy,
  date,
  onOpenEvidence,
}: DecisionCardProps) {
  return (
    <div className="p-5 rounded-lg bg-surface border border-border shadow-xs flex flex-col md:flex-row md:items-center justify-between gap-4">
      <div className="space-y-1.5 flex-1">
        <div className="flex items-center gap-2">
          <StatusBadge kind={STATUS_KIND[status]} label={STATUS_LABEL[status]} />
          {id && <span className="text-xs text-text-muted font-mono">{id}</span>}
        </div>
        <h3 className="text-sm font-semibold text-text-main leading-snug">{text}</h3>
        <div className="flex items-center gap-4 text-xs text-text-muted pt-1">
          <span className="flex items-center gap-1">
            <User className="w-3.5 h-3.5" />
            <span>Approved by: <strong className="text-text-main">{approvedBy || "Reviewer"}</strong></span>
          </span>
          {date && (
            <span className="flex items-center gap-1">
              <Clock className="w-3.5 h-3.5" />
              <span>{date}</span>
            </span>
          )}
        </div>
      </div>
      {onOpenEvidence && (
        <button
          onClick={onOpenEvidence}
          className="px-3 py-1.5 rounded-md text-xs font-semibold text-primary bg-primary-soft hover:bg-primary/20 border border-primary/20 transition-colors shrink-0"
        >
          Why?
        </button>
      )}
    </div>
  );
}
