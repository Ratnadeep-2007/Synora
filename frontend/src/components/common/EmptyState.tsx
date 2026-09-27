"use client";

import React from "react";
import { CheckCircle2, Inbox } from "lucide-react";

interface EmptyStateProps {
  title: string;
  description: string;
  action?: React.ReactNode;
  icon?: "inbox" | "success";
}

export function EmptyState({ title, description, action, icon = "inbox" }: EmptyStateProps) {
  const Icon = icon === "success" ? CheckCircle2 : Inbox;
  return (
    <div className="p-12 text-center bg-surface rounded-xl border border-border space-y-3">
      <Icon className={`w-8 h-8 mx-auto ${icon === "success" ? "text-success" : "text-text-muted opacity-40"}`} />
      <p className="font-semibold text-text-main text-sm">{title}</p>
      <p className="text-xs text-text-muted max-w-md mx-auto">{description}</p>
      {action && <div className="pt-2 flex items-center justify-center gap-3">{action}</div>}
    </div>
  );
}
