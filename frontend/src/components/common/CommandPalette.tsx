"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";

export interface CommandAction {
  id: string;
  label: string;
  hint?: string;
  run: () => void;
}

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  actions: CommandAction[];
}

export function CommandPalette({ isOpen, onClose, actions }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return actions;
    return actions.filter(
      (a) => a.label.toLowerCase().includes(q) || (a.hint || "").toLowerCase().includes(q)
    );
  }, [actions, query]);

  useEffect(() => {
    if (isOpen) {
      setQuery("");
      setActiveIndex(0);
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [isOpen]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  if (!isOpen) return null;

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") onClose();
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, filtered.length - 1));
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    }
    if (e.key === "Enter") {
      const action = filtered[activeIndex];
      if (action) {
        action.run();
        onClose();
      }
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-start justify-center pt-[12vh] p-4" onClick={onClose}>
      <div
        className="w-full max-w-lg rounded-2xl bg-surface/95 border border-border shadow-2xl overflow-hidden"
        style={{ backdropFilter: "blur(14px)", WebkitBackdropFilter: "blur(14px)" }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Command palette"
      >
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
          <Search className="w-4 h-4 text-text-muted" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKey}
            placeholder="Type a command…"
            aria-label="Command palette search"
            className="flex-1 bg-transparent text-sm text-text-main placeholder:text-text-muted focus:outline-none"
          />
          <kbd className="text-[10px] font-mono text-text-muted border border-border rounded px-1.5 py-0.5 bg-canvas">
            ESC
          </kbd>
        </div>
        <div className="max-h-72 overflow-y-auto p-1.5">
          {filtered.length === 0 ? (
            <div className="px-4 py-6 text-center text-xs text-text-muted">No matching actions.</div>
          ) : (
            filtered.map((action, idx) => (
              <button
                key={action.id}
                onMouseEnter={() => setActiveIndex(idx)}
                onClick={() => {
                  action.run();
                  onClose();
                }}
                className={`w-full text-left px-3 py-2 rounded-md text-xs flex items-center justify-between transition-colors ${
                  idx === activeIndex ? "bg-primary-soft text-primary font-semibold" : "text-text-main"
                }`}
              >
                <span>{action.label}</span>
                {action.hint && <span className="text-[11px] text-text-muted font-mono">{action.hint}</span>}
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
