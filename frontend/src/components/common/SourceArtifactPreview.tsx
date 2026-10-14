"use client";

import React, { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { SourceArtifactInfo } from "@/lib/types";

export function SourceArtifactPreview({ evidenceId, artifactId, onUseTranscript }: {
  evidenceId?: string | null; artifactId?: string | null; onUseTranscript?: (text: string) => void;
}) {
  const [artifacts, setArtifacts] = useState<SourceArtifactInfo[]>([]);
  const [urls, setUrls] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const urlsRef = useRef<Record<string, string>>({});
  const needsPoll = useRef(true);
  useEffect(() => {
    let cancelled = false;
    setArtifacts([]);
    setError("");
    Object.values(urlsRef.current).forEach((url) => URL.revokeObjectURL(url));
    urlsRef.current = {};
    setUrls({});
    needsPoll.current = true;
    const load = async () => {
      try {
        const rows = artifactId ? [await api.getSourceArtifact(artifactId)] : evidenceId ? await api.getSourceArtifacts(evidenceId) : [];
        if (!cancelled) {
          setArtifacts(rows);
          needsPoll.current = rows.some((row) => row.status !== "complete");
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load original source");
      }
    };
    void load();
    const timer = window.setInterval(() => { if (needsPoll.current) void load(); }, 10000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [evidenceId, artifactId]);
  useEffect(() => {
    return () => { Object.values(urlsRef.current).forEach((url) => URL.revokeObjectURL(url)); };
  }, []);

  const original = async (artifact: SourceArtifactInfo) => {
    setLoadingId(artifact.id);
    setError("");
    try {
      const blob = await api.getSourceOriginal(artifact.id);
      if (urlsRef.current[artifact.id]) URL.revokeObjectURL(urlsRef.current[artifact.id]);
      urlsRef.current = { ...urlsRef.current, [artifact.id]: URL.createObjectURL(blob) };
      setUrls(urlsRef.current);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Original source unavailable");
    } finally { setLoadingId(null); }
  };
  if (!artifacts.length && !error) return null;
  return <div className="mt-3 space-y-2">
    {error && <p role="status" className="text-[11px] text-warning">{error}</p>}
    {artifacts.map((artifact) => <article key={artifact.id} className="rounded-lg border border-border bg-canvas p-3">
      <div className="flex items-center justify-between gap-3"><span className="truncate text-xs font-medium">{artifact.filename}</span><span className="text-[10px] text-text-muted">{artifact.status === "complete" ? "Processed" : artifact.status === "failed" ? "Needs retry" : "Processing pending"}</span></div>
      {artifact.error && <p className="mt-1 text-[11px] text-warning">{artifact.error}</p>}
      <div className="mt-2 flex flex-wrap gap-3 text-[11px]">
        {!urls[artifact.id] && <button type="button" disabled={loadingId === artifact.id} onClick={() => original(artifact)} className="text-primary hover:underline">{loadingId === artifact.id ? "Loading original…" : "Inspect original"}</button>}
        {urls[artifact.id] && <a href={urls[artifact.id]} download={artifact.filename} className="text-primary hover:underline">Download original</a>}
        {artifact.status !== "complete" && <button type="button" onClick={async () => { try { const result = await api.retrySourceArtifact(artifact.id); needsPoll.current = true; setArtifacts((prev) => prev.map((row) => row.id === artifact.id ? result.artifact : row)); } catch (err) { setError(err instanceof Error ? err.message : "Could not retry source"); } }} className="text-primary hover:underline">Retry extraction</button>}
        {onUseTranscript && artifact.text && artifact.status === "complete" && <button type="button" onClick={() => onUseTranscript(artifact.text || "")} className="text-primary hover:underline">Review this transcript</button>}
      </div>
      {urls[artifact.id] && ["image/png", "image/jpeg", "image/webp", "image/gif"].includes(artifact.mime_type) && <img src={urls[artifact.id]} alt={`Original ${artifact.filename}`} className="mt-3 max-h-80 w-full rounded-md object-contain" />}
      {urls[artifact.id] && artifact.mime_type.startsWith("audio/") && <audio src={urls[artifact.id]} controls preload="metadata" className="mt-3 w-full" />}
      {artifact.segments?.length ? <details className="mt-2 text-[11px] text-text-muted"><summary className="cursor-pointer">Transcript timestamps</summary>{artifact.segments.slice(0, 30).map((segment, index) => <p key={index} className="mt-1"><span className="font-mono">{Math.round(segment.start || 0)}s–{Math.round(segment.end || 0)}s</span> {segment.text}</p>)}</details> : null}
    </article>)}
  </div>;
}
