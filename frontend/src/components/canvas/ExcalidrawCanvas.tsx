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
} from "lucide-react";

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
}: ExcalidrawCanvasProps) {
  const [excalidrawAPI, setExcalidrawAPI] = useState<any>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [elementCount, setElementCount] = useState(initialElements?.length || 0);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Update canvas scene when new elements arrive from workspace sync
  useEffect(() => {
    if (excalidrawAPI && initialElements && initialElements.length > 0) {
      try {
        excalidrawAPI.updateScene({
          elements: initialElements,
          commitToHistory: true,
        });
        setElementCount(initialElements.length);
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
  }, [excalidrawAPI, initialElements]);

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
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-1.5">
          {onSaveCanvas && (
            <button
              onClick={handleSave}
              disabled={isSaving}
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
        <Excalidraw
          excalidrawAPI={(api) => setExcalidrawAPI(api)}
          initialData={{
            elements: initialElements,
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
      </div>

      {/* Canvas Footnote */}
      <div className="px-4 py-2 bg-surface/50 border-t border-border flex items-center justify-between text-[11px] text-text-muted">
        <div className="flex items-center gap-1.5">
          <Info className="w-3 h-3 text-primary" />
          <span>
            Synora maintains the living visual workspace from project evidence, approved state, and reviewed visual proposals.
          </span>
        </div>
        <div className="font-mono text-[10px]">
          Press <strong>Space + Drag</strong> to pan • <strong>Ctrl + Scroll</strong> to zoom
        </div>
      </div>
    </div>
  );
}
