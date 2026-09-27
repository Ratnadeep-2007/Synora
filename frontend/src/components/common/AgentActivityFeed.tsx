"use client";

import React from "react";

export interface AgentActivityItem {
  time: string;
  text: string;
}

interface AgentActivityFeedProps {
  items: AgentActivityItem[];
  title?: string;
}

export function AgentActivityFeed({ items, title = "Agent Activity" }: AgentActivityFeedProps) {
  return (
    <div className="p-6 rounded-xl bg-surface border border-border shadow-xs space-y-4">
      <h3 className="text-sm font-semibold text-text-main uppercase tracking-wider">{title}</h3>
      {items.length === 0 ? (
        <p className="text-xs text-text-muted">No operational activity recorded yet.</p>
      ) : (
        <div className="space-y-3">
          {items.map((item, idx) => (
            <div key={idx} className="flex items-start gap-4 text-xs">
              <span className="font-mono text-text-muted shrink-0 mt-0.5">{item.time}</span>
              <p className="text-text-main flex-1">{item.text}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
