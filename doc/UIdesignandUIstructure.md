# Synora UI Design and Structure

## Product Posture
A serious enterprise project control room. The UI makes project truth, change, evidence, uncertainty, agent activity, approvals, and visual architecture observable.

## Core Navigation
- **Overview**: Executive project health, active sources, recent proposals, and state velocity.
- **Project State**: Authoritative, versioned state view (vision, requirements, decisions, architecture).
- **Excalidraw**: Living visual workspace with Current mode, Compare mode, and revision history.
- **Meetings**: Segment-level Google Meet viewer with per-segment project routing badges and timestamps.
- **Unknown Context (Triage)**: Quarantine queue for unresolved/ambiguous events with candidate matching and triage actions.
- **Evidence**: Immutable evidence repository with source provenance and extraction links.
- **Decisions & Conflicts**: Governed architectural choices and detected system contradictions.
- **Agent**: Single shared Synora Agent dashboard showing active capabilities and execution telemetry.
- **Sources**: Connectors (Google Meet, WhatsApp Baileys, Slack, Excalidraw).
- **Settings**: RBAC, tenant configuration, and policy thresholds.

## Agent View: One Shared Synora Agent
- The UI renders **one shared Synora Agent**.
- Specialist roles (Business Analysis, Project Planning, Functional Analysis, Technical Architecture, Frappe/ERP) are presented as **modular capabilities**, never as separate user-facing chatbots or distinct agent personas.
- The active project selector defines the context and security boundary for the agent.

## Unknown Context & Human Triage Surface
- Quarantined events (`proj_unknown_context`) display:
  - Source snippet and metadata (e.g. sender, group name, time).
  - Extracted knowledge preview (identified requirements, proposals, questions).
  - Ranked project match candidates with deterministic score, semantic score, and confidence percentage.
- Three primary triage buttons:
  - **Assign to Project**: Opens modal to confirm project assignment and merge evidence.
  - **Keep Unknown**: Dismisses triage prompt while retaining quarantined evidence.
  - **Create New Project**: Launches project creation wizard pre-populated with evidence.

## Excalidraw Living Visual Workspace
- **Current Mode**: Real-time canvas rendering the latest committed `VisualRevision`.
- **Compare Mode**: Visual comparison interface between two revisions:
  - Added elements highlighted in emerald green.
  - Removed elements highlighted in muted red.
  - Modified elements highlighted in amber.
  - Summary stats pill: `+N added | -M removed | ~K changed`.
- **Revision History Slider**: Chronological timeline displaying sequential revisions (`rev_1`, `rev_2`, ...) with author, commit message, and timestamp.
- **VisualPlan Proposal Banner**: Displays pending visual change proposals generated from multi-source evidence, showing the visual diff preview with **Approve Proposal** and **Reject Proposal** actions.

## Google Meet Multi-Segment Timeline
- Transcript view renders segmented cards split by speaker turns and time gaps ($\ge 45$s).
- Each segment has independent routing badges (e.g. `[Synora: 94%]`, `[Healthcare Claims: 88%]`, `[Unknown Context: Triage]`).
- Clicking any segment highlights its corresponding extracted requirements, decisions, and Excalidraw updates.

## Visual Language & Design System
- Warm canvas background `#F6F7F5`, clean white surfaces `#FFFFFF`, deep forest green `#173F35`, and subtle borders `#E7EAE5`.
- Infrastructure nodes: `#e0e7ff` fill with `#3730a3` stroke.
- Inter typography with tabular numerals for metrics and timestamps.
- Zero decorative neon, purple AI gradients, or robotic chatbot illustrations.
- Full WCAG 2.2 AA accessibility, visible focus indicators, and screen-reader accessible interactive tables.
