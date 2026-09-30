"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { AlertTriangle, Info, Layers, Maximize2, Minimize2, ZoomIn } from "lucide-react";

export function sanitizeExcalidrawElements(elements: any[]): any[] {
  if (!Array.isArray(elements)) return [];
  return elements.map((el, idx) => {
    if (!el || typeof el !== "object") return null;
    const sanitized = { ...el };
    sanitized.id = String(sanitized.id || "el_" + idx);
    sanitized.type = String(sanitized.type || "rectangle");
    sanitized.x = Number.isFinite(Number(sanitized.x)) ? Number(sanitized.x) : 0;
    sanitized.y = Number.isFinite(Number(sanitized.y)) ? Number(sanitized.y) : 0;

    if (sanitized.type === "arrow" || sanitized.type === "line") {
      sanitized.width = Number.isFinite(Number(sanitized.width)) ? Number(sanitized.width) : 0;
      sanitized.height = Number.isFinite(Number(sanitized.height)) ? Number(sanitized.height) : 0;
      sanitized.points =
        Array.isArray(sanitized.points) && sanitized.points.length > 0
          ? sanitized.points.map((point: any) =>
              Array.isArray(point) && Number.isFinite(Number(point[0])) && Number.isFinite(Number(point[1]))
                ? [Number(point[0]), Number(point[1])]
                : [0, 0]
            )
          : [[0, 0], [100, 0]];
    } else {
      const width = Number(sanitized.width);
      const height = Number(sanitized.height);
      sanitized.width = Number.isFinite(width) && width >= 0 ? width : sanitized.type === "text" ? 120 : 160;
      sanitized.height = Number.isFinite(height) && height >= 0 ? height : sanitized.type === "text" ? 24 : 70;
    }

    sanitized.angle = Number.isFinite(Number(sanitized.angle)) ? Number(sanitized.angle) : 0;
    sanitized.roughness = Number.isFinite(Number(sanitized.roughness)) ? Number(sanitized.roughness) : 1;
    sanitized.opacity = Number.isFinite(Number(sanitized.opacity)) ? Number(sanitized.opacity) : 100;
    sanitized.isDeleted = Boolean(sanitized.isDeleted);
    sanitized.groupIds = Array.isArray(sanitized.groupIds) ? sanitized.groupIds : [];
    return sanitized;
  }).filter(Boolean);
}

class CanvasErrorBoundary extends React.Component<
  { children: React.ReactNode; onReset?: () => void },
  { hasError: boolean }
> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-[620px] flex-col items-center justify-center rounded-xl border border-border bg-canvas p-6 text-center">
          <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-warning/10 text-warning">
            <AlertTriangle className="h-5 w-5" />
          </div>
          <h3 className="text-sm font-semibold text-text-main">Canvas could not be rendered</h3>
          <p className="mt-1 max-w-md text-xs text-text-muted">The stored architecture remains intact in the database.</p>
          <button
            onClick={() => {
              this.setState({ hasError: false });
              this.props.onReset?.();
            }}
            className="mt-4 rounded-lg border border-border bg-surface px-3 py-2 text-xs font-semibold text-text-main hover:bg-canvas"
          >
            Reload canvas
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

const Excalidraw = dynamic(
  async () => {
    const module = await import("@excalidraw/excalidraw");
    return module.Excalidraw;
  },
  {
    ssr: false,
    loading: () => (
      <div className="flex min-h-[620px] flex-col items-center justify-center rounded-xl border border-border bg-canvas text-text-muted">
        <div className="h-7 w-7 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="mt-3 text-sm font-semibold text-text-main">Loading architecture…</p>
        <p className="mt-1 text-[11px] text-text-muted">Initializing visual workspace</p>
      </div>
    ),
  }
);

interface ExcalidrawCanvasProps {
  projectName?: string;
  version?: number;
  initialElements?: any[];
  initialAppState?: any;
  isSyncing?: boolean;
  onSyncAgentOutput?: () => Promise<void>;
  onSaveCanvas?: (scene: { name: string; elements: any[]; app_state?: any }) => Promise<void>;
  onExportJson?: () => void;
  compareMode?: boolean;
  compareElements?: any[];
  compareAddedIds?: string[];
  compareChangedIds?: string[];
  compareFromRevision?: number | null;
  compareToRevision?: number | null;
}

export function ExcalidrawCanvas({
  projectName = "Project",
  version = 1,
  initialElements = [],
  initialAppState,
  compareMode = false,
  compareElements = [],
  compareAddedIds = [],
  compareChangedIds = [],
  compareFromRevision = null,
  compareToRevision = null,
}: ExcalidrawCanvasProps) {
  const [excalidrawAPI, setExcalidrawAPI] = useState<any>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const visibleElements = useMemo(
    () => sanitizeExcalidrawElements(compareMode ? compareElements : initialElements),
    [compareMode, compareElements, initialElements]
  );
  const initialScene = useMemo(() => sanitizeExcalidrawElements(initialElements), [initialElements]);

  useEffect(() => {
    if (!excalidrawAPI || !visibleElements.length) return;
    try {
      excalidrawAPI.updateScene({
        elements: visibleElements,
        commitToHistory: false,
      });
      setTimeout(() => {
        try {
          excalidrawAPI.scrollToContent();
        } catch {}
      }, 100);
    } catch (error) {
      console.warn("Failed to update Excalidraw scene", error);
    }
  }, [excalidrawAPI, visibleElements]);

  const center = useCallback(() => {
    try {
      excalidrawAPI?.scrollToContent();
    } catch {}
  }, [excalidrawAPI]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && isFullscreen) setIsFullscreen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isFullscreen]);

  return (
    <div
      ref={containerRef}
      className={
        "flex flex-col overflow-hidden border border-border bg-surface " +
        (isFullscreen ? "fixed inset-0 z-50 rounded-none" : "rounded-xl")
      }
    >
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary">
            <Layers className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="truncate text-xs font-semibold text-text-main">{projectName}</h3>
              <span className="rounded-md bg-canvas px-1.5 py-0.5 font-mono text-[10px] text-text-muted">v{version}</span>
            </div>
            <p className="text-[10px] text-text-muted">
              {visibleElements.length} elements • AI-maintained • database-backed
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          {compareMode && compareFromRevision !== null && compareToRevision !== null && (
            <span className="hidden rounded-full border border-border bg-canvas px-2 py-1 text-[10px] font-medium text-text-muted sm:inline">
              r{compareFromRevision} → r{compareToRevision} • +{compareAddedIds.length} • ~{compareChangedIds.length}
            </span>
          )}
          <button
            onClick={center}
            className="rounded-lg border border-border bg-surface p-1.5 text-text-muted hover:bg-canvas hover:text-text-main"
            title="Center diagram"
          >
            <ZoomIn className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => setIsFullscreen((value) => !value)}
            className="rounded-lg border border-border bg-surface p-1.5 text-text-muted hover:bg-canvas hover:text-text-main"
            title={isFullscreen ? "Exit fullscreen" : "Fullscreen"}
          >
            {isFullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>

      <div className="relative w-full" style={{ height: isFullscreen ? "calc(100vh - 57px)" : "620px" }}>
        <CanvasErrorBoundary onReset={center}>
          <Excalidraw
            excalidrawAPI={(api) => setExcalidrawAPI(api)}
            viewModeEnabled={true}
            initialData={{
              elements: initialScene,
              appState: initialAppState || {
                viewBackgroundColor: "#ffffff",
                gridSize: 20,
                theme: "light",
              },
              scrollToContent: true,
            }}
            UIOptions={{
              canvasActions: {
                changeViewBackgroundColor: false,
                clearCanvas: false,
                export: false,
                loadScene: false,
                saveToActiveFile: false,
                toggleTheme: true,
              },
            }}
          />
        </CanvasErrorBoundary>
      </div>

      <div className="flex items-center justify-between gap-4 border-t border-border bg-surface/60 px-4 py-2 text-[10px] text-text-muted">
        <span className="inline-flex items-center gap-1.5">
          <Info className="h-3 w-3 text-primary" />
          Synora automatically updates this visual workspace from governed project information.
        </span>
        <span className="hidden font-mono sm:inline">View only</span>
      </div>
    </div>
  );
}