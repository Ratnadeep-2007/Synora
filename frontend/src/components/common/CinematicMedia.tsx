"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUpRight, Pause, Play } from "lucide-react";

export function CinematicMedia({ scroll = false }: { scroll?: boolean }) {
  const host = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const [paused, setPaused] = useState(false);
  useEffect(() => {
    const el = video.current;
    const box = host.current;
    if (!el || !box) return;
    const reduced = matchMedia("(prefers-reduced-motion: reduce)");
    const connection = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
    let visible = false;
    let frame = 0;
    const update = () => {
      frame = 0;
      if (paused || reduced.matches || connection?.saveData || !visible || document.hidden) { el.pause(); return; }
      if (!el.getAttribute("src")) { el.src = "/media/synora-flow.mp4"; el.load(); }
      if (!scroll) { void el.play().catch(() => {}); return; }
      el.pause();
      const rect = box.getBoundingClientRect();
      const progress = Math.max(0, Math.min(1, (innerHeight - rect.top) / (innerHeight + rect.height)));
      box.style.setProperty("--story-progress", String(progress));
      const target = progress * Math.max(0, el.duration - .05);
      if (Number.isFinite(target) && !el.seeking && Math.abs(el.currentTime - target) > .035) el.currentTime = target;
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(update); };
    const observer = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; schedule(); });
    observer.observe(box);
    el.addEventListener("loadedmetadata", schedule);
    el.addEventListener("seeked", schedule);
    if (scroll) window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    document.addEventListener("visibilitychange", schedule);
    reduced.addEventListener("change", schedule);
    return () => {
      observer.disconnect(); cancelAnimationFrame(frame); el.pause();
      el.removeEventListener("loadedmetadata", schedule); el.removeEventListener("seeked", schedule);
      window.removeEventListener("scroll", schedule); window.removeEventListener("resize", schedule);
      document.removeEventListener("visibilitychange", schedule); reduced.removeEventListener("change", schedule);
    };
  }, [paused, scroll]);
  return <div ref={host} className={`cinematic-media ${scroll ? "cinematic-media--scroll" : ""}`}>
    <video ref={video} muted playsInline loop={!scroll} preload="none" poster="/media/synora-flow.jpg" aria-hidden="true" />
    <div className="cinematic-shade" />
    <button type="button" className="motion-control" aria-pressed={paused} aria-label={paused ? "Enable background motion" : "Pause background motion"} onClick={() => setPaused(v => !v)}>
      {paused ? <Play size={12} /> : <Pause size={12} />} {paused ? "Motion paused" : scroll ? "Scroll motion" : "Ambient motion"}
    </button>
  </div>;
}

export function MemoryStory({ onOpenAtlas }: { onOpenAtlas: () => void }) {
  return <section className="memory-story" aria-label="From conversation to clarity">
    <CinematicMedia scroll />
    <div className="memory-story-content">
      <span className="cinematic-eyebrow">CONNECTED BY CONTEXT</span>
      <h2>Every conversation.<br /><em>A clearer picture.</em></h2>
      <p>Follow the thread from what was said to what matters. Your evidence, decisions and architecture, connected in one living Atlas.</p>
      <button type="button" onClick={onOpenAtlas}>Explore your Atlas <ArrowUpRight size={16} /></button>
      <div className="story-chapters"><span>01 / Capture</span><span>02 / Understand</span><span>03 / Connect</span></div>
    </div>
  </section>;
}
