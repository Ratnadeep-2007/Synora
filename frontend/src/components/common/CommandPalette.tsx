"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  BrainCircuit,
  Command,
  FileText,
  FolderKanban,
  HelpCircle,
  Layers,
  PenTool,
  Plug,
  Search,
  Settings,
  Sparkles,
  Video,
  X,
  Zap,
} from "lucide-react";
import { NavTab } from "@/components/layout/Shell";
import { Project, ProjectState } from "@/lib/types";

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  onNavigateToTab: (tab: NavTab) => void;
  currentTab?: NavTab;
  projects: Project[];
  currentProjectId?: string | null;
  onSelectProject: (projectId: string) => void;
  onOpenStoryModal?: () => void;
  onOpenAgentSheet?: () => void;
  onSyncAtlas?: () => void;
  state?: ProjectState | null;
  onOpenEvidence?: (title: string, contextType: string, evidenceIds: string[]) => void;
}

interface CommandItem {
  id: string;
  category: "Navigation" | "Intelligence Actions" | "Projects" | "Knowledge";
  title: string;
  subtitle?: string;
  icon: React.ComponentType<{ className?: string }>;
  action: () => void;
  badge?: string;
}

export function CommandPalette({
  isOpen,
  onClose,
  onNavigateToTab,
  currentTab,
  projects,
  currentProjectId,
  onSelectProject,
  onOpenStoryModal,
  onOpenAgentSheet,
  onSyncAtlas,
  state,
  onOpenEvidence,
}: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isOpen) {
      setQuery("");
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 60);
    }
  }, [isOpen]);

  const items: CommandItem[] = useMemo(() => {
    const list: CommandItem[] = [];

    // 1. Navigation
    list.push({
      id: "nav-pulse",
      category: "Navigation",
      title: "Project Pulse",
      subtitle: "Living intelligence overview and meaningful event stream",
      icon: Activity,
      action: () => {
        onNavigateToTab("overview");
        onClose();
      },
      badge: "1",
    });

    list.push({
      id: "nav-state",
      category: "Navigation",
      title: "Project State",
      subtitle: "The project's authoritative brain: vision, decisions & topology",
      icon: Layers,
      action: () => {
        onNavigateToTab("state");
        onClose();
      },
      badge: "2",
    });

    list.push({
      id: "nav-atlas",
      category: "Navigation",
      title: "Living Project Atlas",
      subtitle: "Infinite external visual architecture maintained by Synora",
      icon: PenTool,
      action: () => {
        onNavigateToTab("excalidraw");
        onClose();
      },
      badge: "3",
    });

    list.push({
      id: "nav-meetings",
      category: "Navigation",
      title: "Timeline & Meetings",
      subtitle: "Speech transcripts and derived project intelligence",
      icon: Video,
      action: () => {
        onNavigateToTab("meetings");
        onClose();
      },
      badge: "4",
    });

    list.push({
      id: "nav-sources",
      category: "Navigation",
      title: "Connected Sources",
      subtitle: "Google Meet OAuth and WhatsApp stream connections",
      icon: Plug,
      action: () => {
        onNavigateToTab("sources");
        onClose();
      },
      badge: "5",
    });

    list.push({
      id: "nav-settings",
      category: "Navigation",
      title: "Settings & Workspace",
      subtitle: "Workspace preferences and system identity",
      icon: Settings,
      action: () => {
        onNavigateToTab("settings");
        onClose();
      },
    });

    // 2. Intelligence Actions
    if (onOpenAgentSheet) {
      list.push({
        id: "act-agent",
        category: "Intelligence Actions",
        title: "Open Synora Agent Surface",
        subtitle: "Inspect cognitive focus, dispatch specialist capabilities",
        icon: BrainCircuit,
        action: () => {
          onClose();
          onOpenAgentSheet();
        },
      });
    }

    if (onSyncAtlas) {
      list.push({
        id: "act-sync-atlas",
        category: "Intelligence Actions",
        title: "Synchronize Project Atlas",
        subtitle: "Rebuild and align infinite Excalidraw canvas to current state",
        icon: Sparkles,
        action: () => {
          onClose();
          onSyncAtlas();
        },
      });
    }

    if (onOpenStoryModal) {
      list.push({
        id: "act-storytelling",
        category: "Intelligence Actions",
        title: "How Synora Works (Pipeline Walkthrough)",
        subtitle: "Step through the live pipeline from raw speech to living architecture",
        icon: Zap,
        action: () => {
          onClose();
          onOpenStoryModal();
        },
      });
    }

    // 3. Project Switching
    projects.forEach((p) => {
      if (p.id !== currentProjectId) {
        list.push({
          id: `proj-${p.id}`,
          category: "Projects",
          title: `Switch to ${p.name}`,
          subtitle: p.description || "Project intelligence workspace",
          icon: FolderKanban,
          action: () => {
            onSelectProject(p.id);
            onClose();
          },
        });
      }
    });

    // 4. Knowledge items if matching
    if (state) {
      (state.decisions || []).slice(0, 5).forEach((d, idx) => {
        list.push({
          id: `decision-${d.id || idx}`,
          category: "Knowledge",
          title: `Decision: ${d.text}`,
          subtitle: `${d.evidence_ids?.length || 0} citations • Provenance backed`,
          icon: FileText,
          action: () => {
            onNavigateToTab("state");
            if (onOpenEvidence && d.evidence_ids?.length) {
              onOpenEvidence(d.text, "Decision", d.evidence_ids);
            }
            onClose();
          },
        });
      });

      (state.requirements || []).slice(0, 5).forEach((r, idx) => {
        list.push({
          id: `req-${r.id || idx}`,
          category: "Knowledge",
          title: `Requirement: ${r.title}`,
          subtitle: r.content,
          icon: FileText,
          action: () => {
            onNavigateToTab("state");
            if (onOpenEvidence && r.evidence_ids?.length) {
              onOpenEvidence(r.title, "Requirement", r.evidence_ids);
            }
            onClose();
          },
        });
      });
    }

    return list;
  }, [
    onNavigateToTab,
    onClose,
    onOpenAgentSheet,
    onSyncAtlas,
    onOpenStoryModal,
    projects,
    currentProjectId,
    onSelectProject,
    state,
    onOpenEvidence,
  ]);

  const filteredItems = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (item) =>
        item.title.toLowerCase().includes(q) ||
        (item.subtitle && item.subtitle.toLowerCase().includes(q)) ||
        item.category.toLowerCase().includes(q)
    );
  }, [items, query]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((prev) => (prev + 1) % Math.max(1, filteredItems.length));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((prev) => (prev - 1 + filteredItems.length) % Math.max(1, filteredItems.length));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (filteredItems[selectedIndex]) {
        filteredItems[selectedIndex].action();
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center p-4 sm:pt-20 bg-[var(--scrim)] backdrop-blur-md animate-in fade-in duration-200"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl overflow-hidden rounded-2xl border border-border bg-surface shadow-2xl animate-in slide-in-from-bottom duration-200"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        {/* Input Bar */}
        <div className="flex items-center gap-3 border-b border-border px-4 py-3.5 bg-surface-soft/60">
          <Search className="h-4 w-4 text-text-muted shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type a command or search project intelligence (e.g. Atlas, Decision, Supabase)..."
            className="flex-1 bg-transparent text-sm text-text-main placeholder:text-text-dim focus:outline-none"
          />
          <kbd className="hidden sm:inline-flex items-center gap-1 rounded bg-surface-muted px-1.5 py-0.5 text-[10px] font-mono text-text-muted border border-border">
            ESC
          </kbd>
        </div>

        {/* List of Results */}
        <div ref={listRef} className="max-h-[380px] overflow-y-auto p-2 divide-y divide-border/20">
          {filteredItems.length === 0 ? (
            <div className="py-12 text-center text-xs text-text-muted">
              No matching commands or intelligence found for &quot;{query}&quot;
            </div>
          ) : (
            filteredItems.map((item, idx) => {
              const isSelected = idx === selectedIndex;
              const Icon = item.icon;
              return (
                <div
                  key={item.id}
                  onClick={item.action}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  className={`flex items-center justify-between gap-3 px-3.5 py-2.5 rounded-xl cursor-pointer transition-colors ${
                    isSelected
                      ? "bg-primary-soft text-text-main border border-primary/30"
                      : "text-text-muted hover:bg-surface-soft border border-transparent"
                  }`}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div
                      className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
                        isSelected ? "bg-primary text-white" : "bg-surface-muted text-text-muted"
                      }`}
                    >
                      <Icon className="h-4 w-4" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-xs font-semibold text-text-main">
                          {item.title}
                        </span>
                        <span className="text-[10px] uppercase tracking-wider text-text-dim font-mono">
                          {item.category}
                        </span>
                      </div>
                      {item.subtitle && (
                        <p className="truncate text-[11px] text-text-muted">{item.subtitle}</p>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    {item.badge && (
                      <kbd className="rounded bg-surface-muted px-1.5 py-0.5 font-mono text-[10px] text-text-muted border border-border">
                        {item.badge}
                      </kbd>
                    )}
                    {isSelected && <ArrowRight className="h-3.5 w-3.5 text-primary" />}
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Footer shortcuts */}
        <div className="flex items-center justify-between border-t border-border bg-surface-soft/80 px-4 py-2.5 text-[11px] text-text-dim">
          <div className="flex items-center gap-3">
            <span>
              <kbd className="font-mono text-[10px] text-text-muted">↑</kbd> <kbd className="font-mono text-[10px] text-text-muted">↓</kbd> to navigate
            </span>
            <span>
              <kbd className="font-mono text-[10px] text-text-muted">↵</kbd> to execute
            </span>
          </div>
          <span className="flex items-center gap-1.5 font-mono text-[10px] text-text-muted">
            <Command className="h-3 w-3 text-primary" /> Synora Intelligence Command
          </span>
        </div>
      </div>
    </div>
  );
}
