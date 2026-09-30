"use client";

import React, { useEffect, useState, useRef, useCallback } from "react";
import dynamic from "next/dynamic";
import {
  Sparkles,
  RefreshCw,
  Save,
  Maximize2,
  Minimize2,
  ZoomIn,
  Download,
  CheckCircle2,
  Layers,
  Info,
  AlertTriangle,
} from "lucide-react";

// Robust sanitizer ensuring element geometry never passes NaN, null, or undefined to RoughJS / path-data-parser
export function sanitizeExcalidrawElements(elements: any[]): any[] {
  if (!Array.isArray(elements)) return [];
  return elements
    .map((el, idx) => {
      if (!el || typeof el !== "object") return null;
      const sanitized = { ...el };

      sanitized.id = String(sanitized.id || `el_${idx}_${Date.now()}`);
      sanitized.type = String(sanitized.type || "rectangle");

      // Validate numeric coordinates
      sanitized.x = Number.isFinite(Number(sanitized.x)) ? Number(sanitized.x) : 0;
      sanitized.y = Number.isFinite(Number(sanitized.y)) ? Number(sanitized.y) : 0;

      if (sanitized.type === "arrow" || sanitized.type === "line") {
        sanitized.width = Number.isFinite(Number(sanitized.width)) ? Number(sanitized.width) : 0;
        sanitized.height = Number.isFinite(Number(sanitized.height)) ? Number(sanitized.height) : 0;
        if (!Array.isArray(sanitized.points) || sanitized.points.length === 0) {
          sanitized.points = [[0, 0], [100, 0]];
        } else {
          sanitized.points = sanitized.points.map((pt: any) =>
            Array.isArray(pt) && Number.isFinite(Number(pt[0])) && Number.isFinite(Number(pt[1]))
              ? [Number(pt[0]), Number(pt[1])]
              : [0, 0]
          );
        }
      } else {
        const w = Number(sanitized.width);
        const h = Number(sanitized.height);
        sanitized.width = Number.isFinite(w) && w >= 0 ? w : (sanitized.type === "text" ? 120 : 160);
        sanitized.height = Number.isFinite(h) && h >= 0 ? h : (sanitized.type === "text" ? 24 : 70);
      }

      // Validate roundness object
      if (sanitized.roundness) {
        if (
          typeof sanitized.roundness !== "object" ||
          sanitized.roundness === null ||
          !Number.isFinite(Number(sanitized.roundness.type))
        ) {
          sanitized.roundness = null;
        } else {
          sanitized.roundness = {
            type: Number(sanitized.roundness.type),
            ...(Number.isFinite(Number(sanitized.roundness.value)) ? { value: Number(sanitized.roundness.value) } : {}),
          };
        }
      }

      sanitized.angle = Number.isFinite(Number(sanitized.angle)) ? Number(sanitized.angle) : 0;
      sanitized.roughness = Number.isFinite(Number(sanitized.roughness)) ? Number(sanitized.roughness) : 1;
      sanitized.opacity = Number.isFinite(Number(sanitized.opacity)) ? Number(sanitized.opacity) : 100;
      sanitized.isDeleted = Boolean(sanitized.isDeleted);
      sanitized.groupIds = Array.isArray(sanitized.groupIds) ? sanitized.groupIds : [];

      return sanitized;
    })
    .filter(Boolean);
}

// React error boundary isolating Excalidraw runtime/rendering exceptions
interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class CanvasErrorBoundary extends React.Component<
  { children: React.ReactNode; onReset?: () => void },
  ErrorBoundaryState
> {
  constructor(props: any) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error("Excalidraw runtime error caught by boundary:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="w-full h-full min-h-[580px] flex flex-col items-center justify-center bg-canvas p-6 text-center border border-border rounded-xl">
          <div className="w-12 h-12 rounded-full bg-amber-500/10 text-amber-500 flex items-center justify-center mb-3">
            <AlertTriangle className="w-6 h-6" />
          </div>
          <h3 className="text-sm font-semibold text-text-main mb-1">Canvas Render Issue Encountered</h3>
          <p className="text-xs text-text-muted max-w-md mb-4">
            An element shape or drawing path could not be parsed by the canvas engine. The scene has been protected from corruption.
          </p>
          <button
            onClick={() => {
              this.setState({ hasError: false, error: null });
              if (this.props.onReset) this.props.onReset();
            }}
            className="px-3.5 py-1.5 text-xs font-medium bg-primary text-white hover:bg-primary/90 rounded-lg transition-colors shadow-2xs"
          >
            Reload Canvas
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

// Dynamically import Excalidraw with SSR disabled since it relies heavily on browser Canvas & window APIs
const Excalidraw = dynamic(
  async () => {
    const mod = await import("@excalidraw/excalidraw");
    return mod.Excalidraw;
  },
  {
    ssr: false,
    loading: () => (
      <div className="w-full h-full min-h-[580px] flex flex-col items-center justify-center bg-canvas/80 text-text-muted gap-3 border border-border rounded-xl">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        <div className="text-center space-y-1">
          <p className="text-sm font-semibold text-text-main">Loading Interactive Excalidraw Canvas...</p>
          <p className="text-xs text-text-muted font-mono">Initializing Visual Workspace</p>
        </div>
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
  isSyncing = false,
  onSyncAgentOutput,
  onSaveCanvas,
  onExportJson,
  compareMode = false,
  compareElements = [],
  compareAddedIds = [],
  compareChangedIds = [],
  compareFromRevision = null,
  compareToRevision = null,
}: ExcalidrawCanvasProps) {
  const [excalidrawAPI, setExcalidrawAPI] = useState<any>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const rawVisibleElements = compareMode ? compareElements : initialElements;
  const visibleElements = React.useMemo(
    () => sanitizeExcalidrawElements(rawVisibleElements),
    [rawVisibleElements]
  );
  const sanitizedInitialElements = React.useMemo(
    () => sanitizeExcalidrawElements(initialElements),
    [initialElements]
  );
  const [elementCount, setElementCount] = useState(visibleElements?.length || 0);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const lastRenderedKeyRef = useRef<string>("");
  const currentKey = `${version}_${compareMode ? "cmp" : "norm"}_${visibleElements?.length || 0}`;

  // Update the canvas whenever the current workspace or compare overlay changes.
  // Compare mode is intentionally view-only and does not write ghost elements back.
  useEffect(() => {
    if (excalidrawAPI && visibleElements && visibleElements.length > 0) {
      if (lastRenderedKeyRef.current === currentKey) {
        return;
      }
      lastRenderedKeyRef.current = currentKey;
      try {
        excalidrawAPI.updateScene({
          elements: visibleElements,
          commitToHistory: !compareMode,
        });
        setElementCount(visibleElements.length);
        // Center view on content after slight render delay
        setTimeout(() => {
          try {
            excalidrawAPI.scrollToContent();
          } catch {
            // Ignore if layout hasn't settled
          }
        }, 150);
      } catch (err) {
        console.warn("Failed to update Excalidraw scene:", err);
      }
    }
  }, [excalidrawAPI, visibleElements, compareMode, currentKey]);

  // Center view on content
  const handleCenterView = useCallback(() => {
    if (excalidrawAPI) {
      try {
        excalidrawAPI.scrollToContent();
      } catch (err) {
        console.warn("Error centering canvas:", err);
      }
    }
  }, [excalidrawAPI]);

  // Save current canvas state back to backend database
  const handleSave = async () => {
    if (!excalidrawAPI || !onSaveCanvas) return;
    try {
      setIsSaving(true);
      const elements = excalidrawAPI.getSceneElements();
      const appState = excalidrawAPI.getAppState();

      await onSaveCanvas({
        name: `${projectName} Architecture Scene`,
        elements: Array.from(elements || []),
        app_state: {
          viewBackgroundColor: appState?.viewBackgroundColor || "#ffffff",
          gridSize: appState?.gridSize || 20,
        },
      });

      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 2500);
    } catch (err: any) {
      alert(`Failed to save canvas to project state: ${err.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  // Keyboard shortcut for Esc to exit fullscreen
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isFullscreen) {
        setIsFullscreen(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isFullscreen]);

  return (
    <div
      ref={containerRef}
      className={`transition-all duration-300 flex flex-col bg-surface border border-border shadow-xs ${
        isFullscreen
          ? "fixed inset-0 z-50 rounded-none w-screen h-screen bg-canvas"
          : "rounded-xl overflow-hidden w-full"
      }`}
    >
      {/* Clean Canvas Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 bg-surface border-b border-border text-xs">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-md bg-primary-soft text-primary flex items-center justify-center font-bold">
            <Layers className="w-3.5 h-3.5" />
          </div>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-text-main text-xs">
              {projectName} Diagram
            </span>
            <span className="px-1.5 py-0.5 rounded text-[10px] font-mono text-text-muted bg-canvas border border-border">
              v{version}
            </span>
            <span className="text-[11px] text-text-muted">
              • {elementCount} elements
            </span>
            {compareMode && compareFromRevision !== null && compareToRevision !== null && (
              <>
                <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-primary-soft text-primary border border-primary/20">
                  Compare r{compareFromRevision} → r{compareToRevision}
                </span>
                <span className="text-[10px] text-text-muted font-mono">
                  +{compareAddedIds.length} added • ~{compareChangedIds.length} changed
                </span>
              </>
            )}
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-1.5">
          {onSaveCanvas && (
            <button
              onClick={handleSave}
              disabled={isSaving || compareMode}
              className={`px-3 py-1 text-xs font-medium rounded-lg flex items-center gap-1.5 transition-colors shadow-2xs border ${
                saveSuccess
                  ? "bg-emerald-500 text-white border-emerald-600"
                  : "bg-surface hover:bg-surface/80 text-text-main border-border"
              }`}
              title="Save any visual canvas edits back to the project state"
            >
              {saveSuccess ? (
                <>
                  <CheckCircle2 className="w-3.5 h-3.5 text-white" />
                  <span>Saved</span>
                </>
              ) : (
                <>
                  <Save className="w-3.5 h-3.5 text-text-muted" />
                  <span>{isSaving ? "Saving..." : "Save Edits"}</span>
                </>
              )}
            </button>
          )}

          <button
            onClick={handleCenterView}
            className="px-2.5 py-1 text-xs font-medium text-text-muted hover:text-text-main bg-surface hover:bg-surface/80 border border-border rounded-lg flex items-center gap-1 transition-colors"
            title="Center diagram on screen"
          >
            <ZoomIn className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Center</span>
          </button>

          <button
            onClick={() => setIsFullscreen((prev) => !prev)}
            className="p-1 text-text-muted hover:text-text-main bg-surface hover:bg-surface/80 border border-border rounded-lg flex items-center justify-center transition-colors"
            title={isFullscreen ? "Exit Fullscreen" : "Fullscreen"}
          >
            {isFullscreen ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>

      {/* Embedded Excalidraw Component Container */}
      <div
        className="excalidraw-wrapper w-full relative transition-all"
        style={{
          height: isFullscreen ? "calc(100vh - 54px)" : "620px",
        }}
      >
        <CanvasErrorBoundary onReset={handleCenterView}>
          <Excalidraw
            excalidrawAPI={(api) => setExcalidrawAPI(api)}
            initialData={{
              elements: sanitizedInitialElements,
              appState: initialAppState || {
                viewBackgroundColor: "#ffffff",
                gridSize: 20,
                theme: "light",
              },
              scrollToContent: true,
            }}
            UIOptions={{
              canvasActions: {
                changeViewBackgroundColor: true,
                clearCanvas: true,
                export: false,
                loadScene: false,
                saveToActiveFile: false,
                toggleTheme: true,
              },
            }}
          />
        </CanvasErrorBoundary>
      </div>

      {/* Canvas Footnote */}
      <div className="px-4 py-2 bg-surface/50 border-t border-border flex items-center justify-between text-[11px] text-text-muted">
        <div className="flex items-center gap-1.5">
          <Info className="w-3 h-3 text-primary" />
          <span>
            {compareMode
              ? "Compare view: historical elements are ghosted; added elements are highlighted in green; changed elements are highlighted in amber."
              : "The Synora Agent compiles the living visual workspace from governed project information."}
          </span>
        </div>
        <div className="font-mono text-[10px]">
          Press <strong>Space + Drag</strong> to pan • <strong>Ctrl + Scroll</strong> to zoom
        </div>
      </div>
    </div>
  );
}
