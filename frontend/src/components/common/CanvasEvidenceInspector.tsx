"use client";
import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { EvidenceItem } from "@/lib/types";
import { SourceArtifactPreview } from "./SourceArtifactPreview";

export function CanvasEvidenceInspector({ provenance, onClose }: { provenance: any; onClose: () => void }) {
  const [sources, setSources] = useState<EvidenceItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [missing, setMissing] = useState(0);
  const ids: string[] = provenance?.evidence_ids || [];
  const key = ids.join(",");
  useEffect(() => {
    let cancelled = false;
    setSources([]);
    setLoading(true);
    Promise.allSettled(ids.slice(0, 12).map((id) => api.getEvidenceById(id))).then((results) => {
      if (cancelled) return;
      setSources(results.flatMap((result) => result.status === "fulfilled" ? [result.value] : []));
      setMissing(results.filter((result) => result.status === "rejected").length);
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
    // IDs fully identify the requested citations.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return <aside className="absolute bottom-3 right-3 top-3 z-20 w-[min(360px,calc(100%-24px))] overflow-auto rounded-xl border border-border bg-surface p-4 shadow-xl" aria-label="Canvas source inspector">
    <div className="flex items-center justify-between gap-3"><h3 className="text-sm font-semibold">Source & claim details</h3><button type="button" onClick={onClose} className="text-xs text-text-muted hover:text-text-main">Close</button></div>
    <span className="mt-2 inline-block rounded border border-border px-2 py-1 text-[10px] capitalize">{provenance.record_status || provenance.support_type || "Source evidence"}</span>
    {provenance.claim_ids?.length > 0 && <p className="mt-2 break-all font-mono text-[10px] text-text-muted">Claim: {provenance.claim_ids.join(", ")}</p>}
    {loading && <p role="status" className="mt-3 text-xs text-text-muted">Loading citations…</p>}
    {!loading && !sources.length && <p className="mt-3 text-xs text-text-muted">No persisted source citation is available. Treat this element as a visual inference.</p>}
    {missing > 0 && <p className="mt-2 text-[11px] text-warning">{missing} citation(s) unavailable or outside your access.</p>}
    {sources.map((source) => <article key={source.id} className="mt-3 rounded-lg border border-border p-3">
      <div className="flex items-center justify-between text-[10px] text-text-muted"><span>{source.source.replace(/_/g, " ")}</span><span>{source.occurred_at ? new Date(source.occurred_at).toLocaleString() : ""}</span></div>
      <p className="mt-2 whitespace-pre-wrap text-xs leading-relaxed">{source.content}</p>
      <SourceArtifactPreview evidenceId={source.id} />
    </article>)}
  </aside>;
}
