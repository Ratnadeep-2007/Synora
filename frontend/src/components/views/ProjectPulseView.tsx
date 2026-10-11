"use client";
import React from "react";
import { ArrowDown, ArrowRight, ArrowUpRight, Layers3, Settings2 } from "lucide-react";
import { CinematicMedia } from "@/components/common/CinematicMedia";
import { CandidateKnowledgeItem, Conflict, EvidenceItem, Project, ProjectState } from "@/lib/types";
import type { NavTab } from "@/components/layout/Shell";
interface ProjectPulseViewProps {
 project?: Project | null; state: ProjectState | null; conflicts: Conflict[]; evidence: EvidenceItem[];
 candidates?: CandidateKnowledgeItem[]; history?: Array<{version_number:number;reason?:string;created_at?:string}>;
 connections?: unknown[]; activeProjectName?: string; projectVersion?: number; projects?: Project[]; currentProjectId?: string;
 onSelectProject?: (id:string)=>void; onNavigateToTab:(tab:NavTab)=>void;
 onOpenEvidence:(title:string,type:string,ids:string[])=>void; onSyncAtlas?:()=>Promise<void>|void;
 onOpenAgentSheet?:()=>void; onOpenStoryModal?:()=>void; onReviewConflict?:(conflict:Conflict)=>void;
}
const destinations: Array<{tab:NavTab;title:string;detail:string}> = [
 {tab:"meetings",title:"The conversation",detail:"Recordings, transcripts and the details worth keeping."},
 {tab:"state",title:"The decisions",detail:"Approved requirements and a record of what changed."},
 {tab:"excalidraw",title:"The bigger picture",detail:"A shared canvas connecting the parts of your project."},
 {tab:"sources",title:"The source material",detail:"Connect the places where your team already works."}
];
export function ProjectPulseView({state,conflicts,evidence,activeProjectName,projectVersion,projects=[],currentProjectId,onSelectProject,onNavigateToTab,onOpenEvidence}:ProjectPulseViewProps) {
 const openConflicts=conflicts.filter(c=>["open","unresolved","under_review"].includes(c.status)).length;
 const version=projectVersion||state?.current_version||1;
 const decisions=state?.decisions||[]; const requirements=state?.requirements||[]; const latest=decisions[0];
 return <div className="studio-home">
  <header className="studio-header">
   <div className="studio-brand"><span className="studio-mark" aria-hidden>s<span>.</span></span><span>synora<span className="brand-caption">A shared record of the work.</span></span></div>
   <nav aria-label="Workspace navigation"><button onClick={()=>onNavigateToTab("state")}>Workspace</button><button onClick={()=>onNavigateToTab("excalidraw")}>Atlas</button><button onClick={()=>onNavigateToTab("sources")}>Sources</button></nav>
   <button className="studio-button studio-button--dark" onClick={()=>onNavigateToTab("meetings")}>Open meetings <ArrowUpRight size={15}/></button>
  </header>
  <section className="studio-intro">
   <div className="studio-intro-copy">
    <div className="studio-overline"><span className="studio-signal"/> THE PROJECT NOTEBOOK</div>
    <h1>Good work.<br/>Nothing <span>lost.</span></h1>
    <p>Keep the conversation, the decisions, and the reasons behind them. One considered place for everything your team knows.</p>
    <div className="studio-actions"><button className="studio-button studio-button--accent" onClick={()=>onNavigateToTab("state")}>Enter your workspace <ArrowRight size={16}/></button><button className="studio-text-link" onClick={()=>onNavigateToTab("excalidraw")}>Explore the Atlas <ArrowUpRight size={15}/></button></div>
    <div className="studio-footnote"><ArrowDown size={13}/> A little less searching. A lot more context.</div>
   </div>
   <aside className="project-notebook" aria-label="Current project summary">
    <div className="notebook-binding" aria-hidden>{Array.from({length:8},(_,i)=><i key={i}/>)}</div>
    <div className="notebook-top"><span>WORKING RECORD</span><span>No. {String(version).padStart(3,"0")}</span></div>
    <div className="notebook-project"><span>PROJECT</span><h2>{activeProjectName||"Your next project"}</h2>
    {projects.length>0&&<select aria-label="Select project" value={currentProjectId||""} onChange={e=>onSelectProject?.(e.target.value)}>{projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select>}</div>
    <div className="notebook-entry"><span className="studio-overline">{latest?"FROM YOUR DECISIONS":"ROOM FOR THE NEXT DECISION"}</span><p>{latest?.text||"Start with a conversation. Build a record you can return to."}</p>
    {latest?<button className="studio-text-link" onClick={()=>onOpenEvidence(latest.text,"Decision",latest.evidence_ids||[])}>View supporting evidence <ArrowUpRight size={13}/></button>:<button className="studio-text-link" onClick={()=>onNavigateToTab("meetings")}>Open meeting memory <ArrowUpRight size={13}/></button>}</div>
    <div className="notebook-stats"><div><strong>{evidence.length}</strong><span>Evidence items</span></div><div><strong>{decisions.length}</strong><span>Decisions</span></div><div><strong>{requirements.length}</strong><span>Requirements</span></div></div>
    <div className="notebook-bottom"><span>VERSION {version}</span><button onClick={()=>onNavigateToTab("state")}>{openConflicts?`${openConflicts} to review`:"View project state"} <ArrowUpRight size={12}/></button></div>
   </aside>
  </section>
  <div className="studio-section-heading"><span>01 / YOUR WORK, IN ORDER</span><span>Find the right starting point.</span></div>
  <section className="studio-directory" aria-label="Explore the workspace">{destinations.map((item,i)=><button key={item.tab} onClick={()=>onNavigateToTab(item.tab)}><span className="directory-number">0{i+1}</span><h2>{item.title}</h2><p>{item.detail}</p><ArrowUpRight className="directory-arrow" size={19}/></button>)}</section>
  <section className="studio-atlas-story"><div className="studio-atlas-visual"><CinematicMedia scroll/><span className="atlas-visual-caption">CONNECTIONS, MADE VISIBLE.</span><Layers3 className="atlas-visual-icon" size={36} strokeWidth={1}/></div><div className="studio-atlas-copy"><span className="studio-overline">02 / THE LIVING ATLAS</span><h2>Pull on a thread.<br/>See the whole story.</h2><p>A decision rarely stands alone. See the evidence it came from, the requirements it shapes, and where it fits in the project.</p><button className="studio-text-link" onClick={()=>onNavigateToTab("excalidraw")}>Open your Atlas <ArrowUpRight size={16}/></button></div></section>
  <footer className="studio-footer"><span>Synora / Made for work worth remembering.</span><button onClick={()=>onNavigateToTab("settings")}><Settings2 size={14}/> Workspace settings <ArrowUpRight size={13}/></button></footer>
 </div>;
}
