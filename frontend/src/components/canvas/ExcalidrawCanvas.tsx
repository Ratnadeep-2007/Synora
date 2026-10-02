"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { AlertTriangle, Check, Eye, Info, Layers, Maximize2, Minimize2, PenTool, Save, ZoomIn } from "lucide-react";

export function sanitizeExcalidrawElements(elements: any[]): any[] {
  if (!Array.isArray(elements)) return [];
  const elementMap = new Map<string, any>();
  for (const el of elements) {
    if (el && typeof el === "object" && el.id) {
      elementMap.set(String(el.id), el);
    }
  }

  return elements.map((el, idx) => {
    if (!el || typeof el !== "object") return null;
    const sanitized = { ...el };
    sanitized.id = String(sanitized.id || "el_" + idx);
    sanitized.type = String(sanitized.type || "rectangle");
    sanitized.x = Number.isFinite(Number(sanitized.x)) ? Number(sanitized.x) : 0;
    sanitized.y = Number.isFinite(Number(sanitized.y)) ? Number(sanitized.y) : 0;

    if (sanitized.type === "arrow" || sanitized.type === "line") {
      const srcId = sanitized.startBinding?.elementId;
      const dstId = sanitized.endBinding?.elementId;
      const srcEl = srcId ? elementMap.get(srcId) : null;
      const dstEl = dstId ? elementMap.get(dstId) : null;

      if (srcEl && dstEl && (sanitized.x === 0 || !sanitized.points || sanitized.points.length < 2)) {
        const srcX = Number(srcEl.x) || 0;
        const srcY = Number(srcEl.y) || 0;
        const srcW = Number(srcEl.width) || 220;
        const srcH = Number(srcEl.height) || 92;
        const dstX = Number(dstEl.x) || 0;
        const dstY = Number(dstEl.y) || 0;
        const dstW = Number(dstEl.width) || 220;
        const dstH = Number(dstEl.height) || 92;

        let startX = srcX + srcW;
        let startY = srcY + srcH / 2;
        let endX = dstX;
        let endY = dstY + dstH / 2;

        if (dstX < srcX - 10) {
          startX = srcX + srcW / 2;
          startY = srcY + srcH;
          endX = dstX + dstW / 2;
          endY = dstY;
        } else if (Math.abs(dstX - srcX) <= 10) {
          startX = srcX + srcW / 2;
          startY = srcY + srcH;
          endX = dstX + dstW / 2;
          endY = dstY;
        }

        const dx = endX - startX;
        const dy = endY - startY;
        sanitized.x = startX;
        sanitized.y = startY;
        sanitized.width = Math.max(1, Math.abs(dx));
        sanitized.height = Math.max(1, Math.abs(dy));
        sanitized.points = [[0, 0], [dx, dy]];
      } else {
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
      }
    } else {
      const width = Number(sanitized.width);
      const height = Number(sanitized.height);
      sanitized.width = Number.isFinite(width) && width >= 0 ? width : sanitized.type === "text" ? 120 : 160;
      sanitized.height = Number.isFinite(height) && height >= 0 ? height : sanitized.type === "text" ? 24 : 70;
    }

    if (sanitized.type === "text") {
      sanitized.text = typeof sanitized.text === "string" ? sanitized.text : "";
      sanitized.originalText =
        typeof sanitized.originalText === "string" && sanitized.originalText
          ? sanitized.originalText
          : sanitized.text;
      sanitized.fontSize =
        Number.isFinite(Number(sanitized.fontSize)) && Number(sanitized.fontSize) > 0
          ? Number(sanitized.fontSize)
          : 16;
      sanitized.fontFamily =
        Number.isFinite(Number(sanitized.fontFamily)) ? Number(sanitized.fontFamily) : 1;
      sanitized.textAlign =
        typeof sanitized.textAlign === "string" && sanitized.textAlign
          ? sanitized.textAlign
          : "center";
      sanitized.verticalAlign =
        typeof sanitized.verticalAlign === "string" && sanitized.verticalAlign
          ? sanitized.verticalAlign
          : "middle";
      sanitized.lineHeight =
        Number.isFinite(Number(sanitized.lineHeight)) && Number(sanitized.lineHeight) > 0
          ? Number(sanitized.lineHeight)
          : 1.25;
      sanitized.baseline =
        Number.isFinite(Number(sanitized.baseline)) ? Number(sanitized.baseline) : 14;
      sanitized.autoResize =
        sanitized.autoResize !== undefined ? Boolean(sanitized.autoResize) : true;
    }

    sanitized.angle = Number.isFinite(Number(sanitized.angle)) ? Number(sanitized.angle) : 0;
    sanitized.roughness = Number.isFinite(Number(sanitized.roughness)) ? Number(sanitized.roughness) : 1;
    sanitized.opacity = Number.isFinite(Number(sanitized.opacity)) ? Number(sanitized.opacity) : 100;
    sanitized.isDeleted = Boolean(sanitized.isDeleted);
    sanitized.groupIds = Array.isArray(sanitized.groupIds) ? sanitized.groupIds : [];

    // Critical Excalidraw rendering and hit-testing properties:
    // Excalidraw's isTransparent() calls element.backgroundColor.length. If undefined, it crashes fatally.
    sanitized.backgroundColor =
      typeof sanitized.backgroundColor === "string" && sanitized.backgroundColor.trim()
        ? sanitized.backgroundColor
        : "transparent";
    sanitized.strokeColor =
      typeof sanitized.strokeColor === "string" && sanitized.strokeColor.trim()
        ? sanitized.strokeColor
        : "#1e1e1e";
    sanitized.fillStyle =
      typeof sanitized.fillStyle === "string" && sanitized.fillStyle.trim()
        ? sanitized.fillStyle
        : "solid";
    sanitized.strokeWidth =
      Number.isFinite(Number(sanitized.strokeWidth)) && Number(sanitized.strokeWidth) > 0
        ? Number(sanitized.strokeWidth)
        : 1;
    sanitized.strokeStyle =
      typeof sanitized.strokeStyle === "string" && sanitized.strokeStyle.trim()
        ? sanitized.strokeStyle
        : "solid";

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
  projectId?: string | null;
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
  readOnly?: boolean;
}

const EXCALIDRAW_UI_OPTIONS = {
  canvasActions: {
    changeViewBackgroundColor: true,
    clearCanvas: false,
    export: {
      saveFileToDisk: true,
    },
    loadScene: false,
    saveToActiveFile: false,
    toggleTheme: true,
  },
};

export function ExcalidrawCanvas({
  projectId,
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
  readOnly = false,
  onSaveCanvas,
}: ExcalidrawCanvasProps) {
  const [excalidrawAPI, setExcalidrawAPI] = useState<any>(null);
  const [isEditable, setIsEditable] = useState(false);

  useEffect(() => {
    if (readOnly) setIsEditable(false);
  }, [readOnly]);

  const [isSaving, setIsSaving] = useState(false);
  const isDirtyRef = useRef(false);
  const appliedSceneKeyRef = useRef<string | null>(null);
  const lastCenteredTargetRef = useRef<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const visibleElements = useMemo(
    () => sanitizeExcalidrawElements(compareMode ? compareElements : initialElements),
    [compareMode, compareElements, initialElements]
  );

  const initialData = useMemo(() => {
    return {
      elements: sanitizeExcalidrawElements(compareMode ? compareElements : initialElements),
      appState: {
        viewBackgroundColor: "#ffffff",
        gridSize: 20,
        theme: "light",
        ...(initialAppState || {}),
      },
      scrollToContent: false,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleExcalidrawAPI = useCallback((api: any) => {
    setExcalidrawAPI(api);
  }, []);

  const handleCanvasChange = useCallback((elements: readonly any[]) => {
    if (isEditable && !readOnly) {
      isDirtyRef.current = true;
    }
  }, [isEditable, readOnly]);

  useEffect(() => {
    if (!excalidrawAPI) return;

    const currentTarget = `${projectId || "project"}:${compareMode ? "compare" : "live"}`;
    const sceneFingerprint = `${currentTarget}:${version}:${visibleElements.length}`;

    // Center on initial mount or when switching project / compare target
    if (lastCenteredTargetRef.current !== currentTarget && visibleElements.length > 0) {
      lastCenteredTargetRef.current = currentTarget;
      isDirtyRef.current = false;
      appliedSceneKeyRef.current = sceneFingerprint;

      try {
        excalidrawAPI.updateScene({
          elements: visibleElements,
          commitToHistory: false,
        });
      } catch (err) {
        console.warn("Failed to load initial Excalidraw scene", err);
      }

      const centerTimer = setTimeout(() => {
        try {
          excalidrawAPI.scrollToContent(undefined, {
            fitToViewport: true,
            viewportZoomFactor: 0.85,
            animate: false,
          });
        } catch {}
      }, 150);

      return () => clearTimeout(centerTimer);
    }

    // If identical scene is already loaded, skip to avoid gesture interruptions
    if (appliedSceneKeyRef.current === sceneFingerprint) return;

    // In active manual edit mode with unsaved changes, protect user drawings from external polling
    if (isDirtyRef.current && isEditable && !readOnly) {
      return;
    }

    // If user is currently dragging/typing, defer update
    try {
      const appState = excalidrawAPI.getAppState?.();
      if (appState?.draggingElement || appState?.resizingElement || appState?.editingElement) {
        const timer = setTimeout(() => {
          if (appliedSceneKeyRef.current !== sceneFingerprint) {
            appliedSceneKeyRef.current = sceneFingerprint;
            excalidrawAPI.updateScene({
              elements: visibleElements,
              commitToHistory: false,
            });
          }
        }, 600);
        return () => clearTimeout(timer);
      }
    } catch {}

    appliedSceneKeyRef.current = sceneFingerprint;

    try {
      excalidrawAPI.updateScene({
        elements: visibleElements,
        commitToHistory: false,
      });
    } catch (error) {
      console.warn("Failed to update Excalidraw scene", error);
    }
  }, [excalidrawAPI, projectId, compareMode, version, visibleElements, isEditable, readOnly]);

  const center = useCallback(() => {
    try {
      excalidrawAPI?.scrollToContent(undefined, {
        fitToViewport: true,
        viewportZoomFactor: 0.85,
        animate: true,
      });
    } catch {}
  }, [excalidrawAPI]);

  const handleSave = useCallback(async () => {
    if (!excalidrawAPI || !onSaveCanvas) return;
    try {
      setIsSaving(true);
      const elements = excalidrawAPI.getSceneElements();
      const appState = excalidrawAPI.getAppState();
      await onSaveCanvas({
        name: projectName,
        elements: (elements || []).filter((el: any) => !el.isDeleted),
        app_state: {
          viewBackgroundColor: appState?.viewBackgroundColor || "#ffffff",
          gridSize: appState?.gridSize || 20,
          theme: appState?.theme || "light",
        },
      });
      isDirtyRef.current = false;
      appliedSceneKeyRef.current = [
        projectId || "project",
        "live",
        String((version || 1) + 1),
        String(elements?.length || 0),
      ].join(":");
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 2500);
    } catch (error) {
      console.error("Failed to save Excalidraw diagram:", error);
      alert("Failed to save diagram changes. Please try again.");
    } finally {
      setIsSaving(false);
    }
  }, [excalidrawAPI, onSaveCanvas, projectName, projectId, version]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && isFullscreen) setIsFullscreen(false);
      if (!readOnly && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s" && onSaveCanvas) {
        event.preventDefault();
        handleSave();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isFullscreen, handleSave, onSaveCanvas, readOnly]);

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

        <div className="flex items-center gap-2">
          {compareMode && compareFromRevision !== null && compareToRevision !== null && (
            <span className="hidden rounded-full border border-border bg-canvas px-2 py-1 text-[10px] font-medium text-text-muted sm:inline">
              r{compareFromRevision} → r{compareToRevision} • +{compareAddedIds.length} • ~{compareChangedIds.length}
            </span>
          )}

          {/* Mode toggle */}
          {!readOnly && (
            <button
              onClick={() => setIsEditable((val) => !val)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-xs font-medium text-text-muted hover:bg-canvas hover:text-text-main transition-colors"
              title={isEditable ? "Switch to read-only preview mode" : "Switch to editable canvas mode"}
            >
              {isEditable ? (
                <>
                  <Eye className="h-3.5 w-3.5 text-primary" />
                  <span className="hidden sm:inline">Preview</span>
                </>
              ) : (
                <>
                  <PenTool className="h-3.5 w-3.5 text-primary" />
                  <span className="hidden sm:inline">Edit Mode</span>
                </>
              )}
            </button>
          )}

          {/* Save Diagram button */}
          {onSaveCanvas && !readOnly && (
            <button
              onClick={handleSave}
              disabled={isSaving}
              className="inline-flex items-center gap-1.5 rounded-lg border border-primary/20 bg-primary px-3 py-1.5 text-xs font-medium text-white shadow-xs hover:bg-primary-hover disabled:opacity-50 transition-colors"
              title="Save diagram changes to database (Ctrl+S)"
            >
              {isSaving ? (
                <>
                  <div className="h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />
                  <span>Saving…</span>
                </>
              ) : saveSuccess ? (
                <>
                  <Check className="h-3.5 w-3.5" />
                  <span>Saved!</span>
                </>
              ) : (
                <>
                  <Save className="h-3.5 w-3.5" />
                  <span>Save</span>
                </>
              )}
            </button>
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

      <div className="excalidraw-wrapper relative w-full" style={{ height: isFullscreen ? "calc(100vh - 57px)" : "620px" }}>
        <CanvasErrorBoundary onReset={center}>
          <Excalidraw
            excalidrawAPI={handleExcalidrawAPI}
            onChange={handleCanvasChange}
            viewModeEnabled={readOnly || !isEditable}
            initialData={initialData}
            UIOptions={EXCALIDRAW_UI_OPTIONS}
          />
        </CanvasErrorBoundary>
      </div>

      <div className="flex items-center justify-between gap-4 border-t border-border bg-surface/60 px-4 py-2 text-[10px] text-text-muted">
        <span className="inline-flex items-center gap-1.5">
          <Info className="h-3 w-3 text-primary" />
          {readOnly
            ? "Atlas is AI-maintained and database-backed. Use the Context Inbox below for the only human routing step."
            : isEditable
            ? "Live editing enabled. Draw, add shapes, or modify components freely and click 'Save' (or Ctrl+S) to persist."
            : "Synora automatically updates this visual workspace from governed project information."}
        </span>
        <span className="hidden font-mono sm:inline">
          {isEditable ? (
            <span className="inline-flex items-center gap-1.5 font-semibold text-primary">
              <span className="h-1.5 w-1.5 rounded-full bg-success animate-pulse" />
              Editable
            </span>
          ) : (
            <span className="text-text-muted">View only</span>
          )}
        </span>
      </div>
    </div>
  );
}