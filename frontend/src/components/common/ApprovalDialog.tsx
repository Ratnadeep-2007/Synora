"use client";

import React, { useState } from "react";
import { X, AlertTriangle } from "lucide-react";

interface ApprovalDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (note?: string) => Promise<void> | void;
  title: string;
  changeLabel: string;
  fromValue: string;
  toValue: string;
  evidenceRef?: string;
  confirmingLabel?: string;
}

export function ApprovalDialog({
  isOpen,
  onClose,
  onConfirm,
  title,
  changeLabel,
  fromValue,
  toValue,
  evidenceRef,
  confirmingLabel = "Approve change",
}: ApprovalDialogProps) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  if (!isOpen) return null;

  const handleConfirm = async () => {
    try {
      setBusy(true);
      await onConfirm(note || undefined);
      setNote("");
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-[var(--scrim)] backdrop-blur-xs flex items-center justify-center p-4">
      <div className="w-full max-w-md rounded-2xl bg-surface border border-border shadow-2xl p-6 space-y-5">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-warning/10 text-warning flex items-center justify-center border border-warning/20">
              <AlertTriangle className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-text-main">{title}</h3>
              <p className="text-xs text-text-muted">This will change: {changeLabel}</p>
            </div>
          </div>
          <button onClick={onClose} className="text-text-muted hover:text-text-main p-1 rounded-md">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="space-y-2 text-xs">
          <div className="p-3 rounded-lg bg-canvas border border-border">
            <span className="text-[10px] uppercase font-semibold text-text-muted block mb-1">From</span>
            <span className="text-text-main font-medium break-all">{fromValue}</span>
          </div>
          <div className="p-3 rounded-lg bg-primary-soft/50 border border-primary/20">
            <span className="text-[10px] uppercase font-semibold text-primary block mb-1">To</span>
            <span className="text-primary font-medium break-all">{toValue}</span>
          </div>
          {evidenceRef && (
            <div className="text-[11px] text-text-muted">
              <strong>Evidence:</strong> {evidenceRef}
            </div>
          )}
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-semibold text-text-main">Reviewer note (optional)</label>
          <textarea
            rows={2}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Why is this change correct?"
            className="w-full px-3 py-2 text-xs rounded-lg bg-canvas border border-border focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary text-text-main resize-none"
          />
        </div>

        <div className="flex items-center justify-end gap-2 pt-1">
          <button
            onClick={onClose}
            className="px-3.5 py-2 text-xs font-semibold text-text-muted hover:text-text-main rounded-lg hover:bg-canvas transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={busy}
            className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover rounded-lg shadow-xs transition-colors disabled:opacity-50"
          >
            {busy ? "Applying..." : confirmingLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
