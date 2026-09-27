# Synora UI Design and Structure

## Product posture
A serious enterprise project control room. The UI makes project truth, change, evidence, uncertainty, agent activity, approvals, and visual architecture observable.

## Navigation
Overview
Project State
Excalidraw
Meetings
Evidence
Decisions
Conflicts
Agent
Sources
Settings

## Agent view
Show exactly one shared Synora Agent.

Show specialist capabilities as capabilities/modules:
BA, Project Planning, Functional, Technical, Frappe.

Do not label them as separate agents.

## Project selector
Projects are context/security boundaries. Switching project changes the agent's active context; it does not create or switch to another agent.

## Excalidraw
Full visual workspace. Minimum text, maximum visuals. Show:
architecture, workflows, dependencies, decisions, requirements, risks/questions, and concise provenance markers.

Visual change review:
Current → Proposed → Diff → Evidence → Approval.

## Trust surfaces
Important objects expose:
source, timestamp, actor, evidence, state impact.

Use the path:
Current State → Change → Decision/Requirement → Evidence → Source.

## Status
Use explicit text and icon:
Connected, Working, Waiting, Requires review, Failed, Synchronized, Pending.

Never rely on color alone.

## Visual language
Warm canvas #F6F7F5, white #FFFFFF, deep green #173F35, subtle border #E7EAE5. Inter typography. Restrained glass only for top-level transient surfaces. No purple AI gradients, neon, robot avatars, or decorative animation.

## Enterprise UX
Errors explain what failed, what was preserved, and what the user can do. Loading states show real processing stages. Destructive and high-impact actions require confirmation.

## Accessibility
Keyboard navigation, visible focus, WCAG AA contrast, semantic headings, screen-reader labels, reduced motion, accessible dialogs, and non-color-only status indicators.
