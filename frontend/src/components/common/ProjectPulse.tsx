"use client";

import React from "react";
import { ProjectState, Conflict } from "@/lib/types";
import { StatusBadge } from "./StatusBadge";

interface ProjectPulseProps {
  state: ProjectState | null;
  conflicts: Conflict[];
  pendingReviews?: number;
  synchronized?: boolean;
  onNavigate: (destination: "requirements" | "decisions" | "conflicts" | "questions" | "reviews") => void;
}

export function ProjectPulse({
  state,
  conflicts,
  pendingReviews = 0,
  synchronized = true,
  onNavigate,
}: ProjectPulseProps) {
  const reqs = state?.requirements?.length || 0;
  const decisions = state?.decisions?.length || 0;
  const questions = state?.open_questions?.length || 0;
  const openConflicts = conflicts.filter(
    (c) => c.status === "open" || c.status === "under_review"
  ).length;

  const metrics = [
    { label: "Requirements", value: reqs, dest: "requirements" as const },
    { label: "Decisions", value: decisions, dest: "decisions" as const },
    { label: "Open Conflicts", value: openConflicts, dest: "conflicts" as const, alert: openConflicts > 0 },
    { label: "Open Questions", value: questions, dest: "questions" as const },
    { label: "Pending Reviews", value: pendingReviews, dest: "reviews" as const },
  ];

  return (
    <div className="p-5 rounded-xl bg-surface border border-border shadow-xs flex flex-wrap items-center justify-between gap-6 relative overflow-hidden">
      <div className="absolute left-0 top-0 bottom-0 w-1 bg-primary" />
      <div>
        <div className="flex items-center gap-2 mb-1">
          <StatusBadge kind={synchronized ? "synchronized" : "waiting"} label={synchronized ? "Context synchronized" : "Sync pending"} pulse={synchronized} />
        </div>
        <div className="text-base font-semibold text-text-main">
          Version {state?.current_version || 1} · {state?.title || "Project"}
        </div>
      </div>
      <div className="flex items-center gap-8 text-sm">
        {metrics.map((m, idx) => (
          <React.Fragment key={m.label}>
            {idx > 0 && <div className="w-[1px] h-8 bg-border" />}
            <button onClick={() => onNavigate(m.dest)} className="text-left hover:opacity-80 transition-opacity" title={`Open ${m.label}`}>
              <span className="text-2xl font-semibold font-mono text-text-main block">
                {String(m.value).padStart(2, "0")}
              </span>
              <span className={`text-xs ${m.alert ? "text-warning font-medium" : "text-text-muted"}`}>{m.label}</span>
            </button>
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}
