"use client";

import React from "react";
import { StatusBadge } from "./StatusBadge";

type SyncState = "synchronized" | "updating" | "pending" | "outdated" | "failed";

const SYNC_LABEL: Record<SyncState, string> = {
  synchronized: "Synchronized",
  updating: "Updating",
  pending: "Pending review",
  outdated: "Out of date",
  failed: "Synchronization failed",
};

const SYNC_KIND = {
  synchronized: "synchronized",
  updating: "working",
  pending: "pending",
  outdated: "review",
  failed: "failed",
} as const;

interface ExcalidrawSyncBarProps {
  status: SyncState;
  lastSyncAt?: string | null;
  preservedMessage?: string;
  onRetry?: () => void;
  onViewDetails?: () => void;
}

export function ExcalidrawSyncBar({
  status,
  lastSyncAt,
  preservedMessage = "Project State is safe.",
  onRetry,
  onViewDetails,
}: ExcalidrawSyncBarProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 bg-surface border border-border rounded-lg text-xs">
      <div className="flex items-center gap-3">
        <StatusBadge kind={SYNC_KIND[status]} label={SYNC_LABEL[status]} pulse={status === "updating"} />
        {lastSyncAt && (
          <span className="text-text-muted font-mono text-[11px]" suppressHydrationWarning>
            Last successful synchronization: {new Date(lastSyncAt).toLocaleString()}
          </span>
        )}
      </div>
      {status === "failed" ? (
        <div className="flex items-center gap-3">
          <span className="text-text-muted">{preservedMessage}</span>
          {onRetry && (
            <button onClick={onRetry} className="px-3 py-1 rounded-md bg-primary text-white text-xs font-semibold hover:bg-primary-hover transition-colors">
              Retry
            </button>
          )}
          {onViewDetails && (
            <button onClick={onViewDetails} className="text-primary hover:underline font-medium">
              View details
            </button>
          )}
        </div>
      ) : null}
    </div>
  );
}
