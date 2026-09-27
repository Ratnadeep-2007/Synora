# Synesis — Product UI/UX Design Specification

**Document:** DESIGN.md  
**Version:** 0.1  
**Status:** Draft — MVP  
**Visual direction:** Professional Light Theme + Editorial Glassmorphism + Precision Neumorphism  
**Product character:** Calm, intelligent, trustworthy, operational

---

## 1. Design Intent

Synesis should **not look like a generic AI SaaS dashboard**.

Avoid the common visual language of:

- excessive purple/blue gradients
- glowing AI orbs
- floating chatbot bubbles everywhere
- dark futuristic interfaces
- excessive glass blur
- meaningless KPI cards
- rounded cards nested inside rounded cards
- decorative AI-generated illustrations

The visual personality should communicate:

> **“This is the control room for serious project knowledge.”**

The interface should feel closer to a premium product operations tool than an AI toy.

### Design goals

1. **Attention-grabbing without being loud**
2. **Light and highly legible**
3. **Trustworthy**
4. **Information-dense but not cramped**
5. **Evidence and provenance should feel native**
6. **AI functionality should feel embedded in workflow, not advertised as magic**
7. **Human decisions should remain visually prominent**
8. **Every important state change should feel traceable**

---

# 2. Chosen Visual Style

## Editorial Glassmorphism + Precision Neumorphism

The product uses a restrained form of glassmorphism for surfaces and a subtle neumorphic treatment for controls.

### Why this combination

Pure glassmorphism often becomes:

- blurry
- decorative
- hard to read
- visually repetitive

Pure neumorphism often causes:

- weak contrast
- accessibility problems
- a dated “soft UI” appearance

Therefore Synesis uses them selectively.

### Glassmorphism

Use for:

- top navigation
- contextual command bars
- modal overlays
- floating filters
- transient review panels

Properties:

- translucent white surface
- 10–18px backdrop blur
- thin neutral border
- very subtle shadow

### Precision Neumorphism

Use only for:

- small toggle controls
- segmented controls
- compact actions
- status pills
- interactive graph controls

Do **not** use neumorphism for large content cards.

### Main content surfaces

The majority of the UI should still be clean, flat, editorial surfaces.

This keeps the product professional.

---

# 3. Visual Personality

The design should feel:

**Precise → Quiet → Intelligent → Human → Operational**

It should not feel:

**Futuristic → Cyberpunk → Magical → Playful → Over-automated**

A user should be able to spend 6 hours inside the application without visual fatigue.

---

# 4. Color System

## Base

The application uses a warm-neutral light canvas rather than pure white everywhere.

```text
Canvas       #F6F7F5
Surface      #FFFFFF
Surface Soft #FBFCFA
Border       #E7EAE5
Text Main    #171A17
Text Muted   #68706A
```

### Primary Accent

Use a restrained deep green.

```text
Primary      #173F35
Primary 2    #285C4F
Primary Soft #E8F0EC
```

The green reinforces:

- trust
- stability
- growth
- operational maturity

It also separates Synesis from the saturated-indigo AI SaaS aesthetic.

### Supporting accents

```text
Info         #2F6B9A
Warning      #A87517
Danger       #B84B4B
Success      #2F7154
```

These should be used sparingly.

### Principle

Do not color entire cards to communicate status.

Instead use:

- small status markers
- icons
- labels
- thin edge indicators
- small background tints

---

# 5. Typography

## Primary typeface

Use:

**Inter**

Fallback:

```text
Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif
```

## Optional editorial accent

For large page titles only, use:

**Newsreader**

This creates visual distinction without making the interface look like a magazine.

Example:

```text
Your project,
as it actually stands.
```

Newsreader should appear rarely.

---

# 6. Type Scale

```text
Display      40px / 46px / 600
Page title   30px / 36px / 600
Section      20px / 26px / 600
Card title   16px / 22px / 600
Body         14px / 21px / 400
Small        12px / 18px / 500
Micro        11px / 16px / 600
```

Avoid oversized 64–80px dashboard typography.

Synesis is about information, not visual spectacle.

---

# 7. Layout System

Use a 12-column responsive grid.

### Desktop

```text
Sidebar: 240px
Main content: flexible
Max content width: 1440px
Page padding: 32px
Column gap: 20–24px
```

### Tablet

```text
Sidebar collapses
Page padding: 24px
```

### Mobile

```text
Bottom / drawer navigation
Page padding: 16px
```

---

# 8. Global Shell

Desktop structure:

```text
┌──────────────────────────────────────────────────────────────┐
│ Synesis    Project: WorkSimplified ▼      Search   ● Ratna  │
├─────────────┬────────────────────────────────────────────────┤
│             │                                                │
│ Overview    │                                                │
│ Project     │                 Main Workspace                 │
│ Meetings    │                                                │
│ Decisions   │                                                │
│ Conflicts   │                                                │
│ Workforce   │                                                │
│ Sources     │                                                │
│             │                                                │
│             │                                                │
│ Settings    │                                                │
└─────────────┴────────────────────────────────────────────────┘
```

### Sidebar behavior

The sidebar should feel like a **navigation rail**, not a giant application chrome.

Selected item:

- dark green text
- pale green background
- 3px left indicator

Do not use huge gradient active states.

---

# 9. Top Navigation

The top bar uses restrained glassmorphism.

```text
height: 64px
background: rgba(255,255,255,0.78)
backdrop-filter: blur(14px)
border-bottom: 1px solid #E7EAE5
```

Contents:

```text
Breadcrumb / Project selector
Global search
Activity
Help
Avatar
```

### Project selector

Example:

```text
WorkSimplified
AI Work OS                          ▼
```

It should show:

- project name
- workspace name
- optional environment

---

# 10. Signature UI Element — Project Pulse

The home screen should have a compact “Project Pulse” module.

Example:

```text
PROJECT PULSE

● Stable context

12 decisions
04 open conflicts
07 unresolved questions
18 active requirements
```

The module should be visually distinctive but not flashy.

Use a thin vertical accent line and strong typography.

---

# 11. Overview Screen

## Objective

Answer within 5 seconds:

> What happened?
> What changed?
> What needs my attention?

### Layout

```text
┌─────────────────────────────────────────────────────────────┐
│ Good morning. Here's what changed.                         │
│                                                             │
│ 3 decisions   2 conflicts   7 questions   14 active tasks │
└─────────────────────────────────────────────────────────────┘

┌──────────────────────────────┬──────────────────────────────┐
│ CURRENT PROJECT STATE        │ ATTENTION REQUIRED           │
│                              │                              │
│ Agent Workflow               │ ⚠ Architecture conflict     │
│                              │                              │
│ Onboarding                   │ CEO proposed onboarding      │
│       ↓                      │ before BA.                   │
│ BA                           │                              │
│       ↓                      │ [Review conflict]            │
│ Project                      │                              │
│       ↓                      │                              │
│ Functional                   │                              │
└──────────────────────────────┴──────────────────────────────┘

RECENT PROJECT CHANGES

14:24  CEO proposed onboarding agent
14:27  Decision confirmed
14:32  Project State updated to v18
15:10  BA Agent received new context
```

### Attention card

This should be the most visually prominent card on the Overview page.

Use:

- white surface
- dark text
- subtle warning stripe on left
- small icon
- clear CTA

Avoid bright red/orange backgrounds.

---

# 12. Project State Screen

This is one of the core product screens.

### Header

```text
Project State

Current version
v18

Updated
23 Sep · 14:32

[ View history ]
```

### Tabs

```text
Overview
Vision
Requirements
Architecture
Agent Workflow
Decisions
Constraints
Assumptions
```

### Architecture / workflow view

Use React Flow.

Nodes should be rectangular with a slight 6–8px radius.

Example:

```text
┌───────────────┐
│ Onboarding    │
│ General Agent │
└───────┬───────┘
        ↓
┌───────────────┐
│ BA Agent      │
└───────┬───────┘
        ↓
┌───────────────┐
│ Project Agent │
└───────────────┘
```

### Node design

```text
background: #FFFFFF
border: #DDE3DD
radius: 8px
shadow: 0 4px 14px rgba(20,30,24,0.06)
```

Active node gets a 2px deep-green outline.

---

# 13. Decisions Screen

This should resemble a high-quality operational log rather than a CRM.

### Layout

```text
DECISIONS                                  [Search]

┌──────────────────────────────────────────────────────┐
│ DEC-019                            Confirmed          │
│ Add onboarding before BA                             │
│                                                      │
│ Product Architecture Meeting #42                    │
│ 23 Sep · 14:27                                      │
│                                                      │
│ CEO + CTO                                            │
│                                        [View evidence]│
└──────────────────────────────────────────────────────┘
```

### Status

Use small understated labels:

```text
Confirmed
Proposed
Superseded
Rejected
Needs review
```

---

# 14. Conflict Center

This should feel like a **review queue**.

Not a generic AI warning page.

### Layout

```text
CONFLICT CENTER

2 require attention
5 resolved this week

────────────────────────────────────────────

HIGH ATTENTION

Agent pipeline disagreement

Current state
BA → Project → Functional → Tech → Frappe

New proposal
Onboarding → BA → Project → Functional → Tech → Frappe

Detected because
The new proposal changes the approved sequence.

[ Review ]
```

### Conflict detail

Use a split comparison:

```text
CURRENT STATE               PROPOSED CHANGE

BA                          Onboarding
 ↓                             ↓
Project                      BA
 ↓                             ↓
Functional                  Project
 ↓                             ↓
Tech                        Functional
                              ↓
                            Tech
```

Then:

```text
Evidence
────────────────────────────
Google Meet · Meeting #42
14:24:12
CEO:
"We should add..."
```

### Actions

```text
[ Approve change ]
[ Keep current state ]
[ Mark as unresolved ]
```

Avoid a dangerous single button labelled “Fix with AI”.

---

# 15. Meeting Screen

The meeting view should look like a premium research/editorial interface.

### Header

```text
Product Architecture Meeting #42

23 Sep · 14:00
7 participants

[ Transcript ] [ Intelligence ] [ Evidence ]
```

### Transcript

Use a two-column layout:

```text
Transcript                         Intelligence

14:24:12                           PROPOSAL

CEO                                Add onboarding
"We should add a general          before BA.
onboarding agent..."
                                   [Review]
14:25:31
CTO
"Okay, let's discuss..."
```

The intelligence panel should scroll independently.

---

# 16. AI Extraction UI

Avoid showing chain-of-thought or hidden reasoning.

Instead show concise, inspectable explanations.

Good:

```text
Why was this classified as a proposal?

The speaker used tentative language
and no confirmation was detected.

Evidence →
```

Bad:

```text
Here is my complete internal reasoning...
```

The UI should expose **evidence and decision rules**, not hidden reasoning.

---

# 17. Evidence Drawer

The Evidence Drawer is a signature component.

When the user clicks “Why?”:

```text
                         ┌──────────────────────────────┐
                         │ WHY THIS EXISTS              │
                         │                              │
                         │ Decision DEC-019             │
                         │                              │
                         │ Source                       │
                         │ Google Meet                  │
                         │                              │
                         │ Meeting #42                  │
                         │ 23 Sep · 14:24:12            │
                         │                              │
                         │ CEO                           │
                         │ "We should add..."           │
                         │                              │
                         │ Status                       │
                         │ Confirmed                    │
                         │                              │
                         │ [Open meeting]               │
                         └──────────────────────────────┘
```

This drawer should slide from the right.

---

# 18. Project Agent & Workforce Control Center

The interface presents **ONE Project Agent** per project as the central intelligence entity, coordinating specialist execution capabilities:

```text
PROJECT AGENT (Central Intelligence Coordinator)  ● Active
Project Scope: Proj A (v18)
Memory / Context: 18 Requirements, 7 Decisions, 2 Open Questions
Living Workspace: Excalidraw Canvas Synchronized (v4)

SPECIALIST CAPABILITIES:
├── Business Analysis (BA)      ● Ready [Dispatch]
├── Project Planning            ● Ready [Dispatch]
├── Functional Architecture     ● Ready [Dispatch]
├── Technical Architecture      ● Ready [Dispatch]
└── Frappe Framework Eng.       ● Ready [Dispatch]
```

Clicking a specialist capability or the coordinator reveals:

```text
Project Agent Context & Lineage
────────────────────────────────
Project State v18
Working Memory: Active migration to Frappe v15
Active Constraints: No direct DB mutation without human gate

Recent Dispatched Action
─────────────────────────
Tech Capability: Proposed Redis caching layer
Derived from: Meeting #42 (Utterance 14)
Status: Pending Human Review in Architecture Workspace

Living Visual Workspace (Excalidraw)
─────────────────────────────────────
Decisions Rendered: 7 cards
Pipeline Nodes: 6
Human Review Gates: 1 pending
```

---

# 19. Sources Screen

Use a simple integration catalog.

```text
CONNECTED SOURCES

COMMUNICATION

Google Meet                    Connected
Slack                          Connected
Microsoft Teams                Connect
Zoom                           Connect

WORK

GitHub                         Connected
Linear                         Connect

DESIGN

Excalidraw                     Connect
```

### Connector card

```text
┌────────────────────────────────────────────┐
│ Google Meet                                │
│                                            │
│ ● Connected                                │
│                                            │
│ Last sync       2 min ago                  │
│ Meetings       128                         │
│                                            │
│ [Manage]                   [Disconnect]     │
└────────────────────────────────────────────┘
```

No giant logos taking half the screen.

---

# 20. Connector Detail

Show:

```text
Connection
────────────────────
Account
Permissions
Status
Last sync
Webhook status
Errors

Data scope
────────────────────
Meetings
Transcripts

Security
────────────────────
Token status
Last credential refresh
```

For security-sensitive controls, require confirmation.

---

# 21. Search

Global search is a major feature.

Search across:

```text
Meetings
Decisions
Requirements
Evidence
Project State
Conflicts
Agents
Sources
```

Example:

```text
Search:
"onboarding agent"

Results

DEC-019
Add onboarding before BA

MEETING #42
Product Architecture Meeting

REQ-014
Business context collection

CONFLICT #07
Agent sequence disagreement
```

Search results should show **why each result matched**.

---

# 22. Command Palette

Use:

```text
⌘ K
```

Actions:

```text
Search project
Open recent meeting
Review conflicts
View current state
Connect source
Create requirement
Open agent
```

This should be very fast.

---

# 23. Notifications

Notifications are operational, not promotional.

Good:

```text
1 new conflict requires review
```

Good:

```text
Google Meet transcript processing complete
```

Bad:

```text
Your AI just discovered something AMAZING!
```

Never use fake urgency.

---

# 24. Empty States

Empty states should teach the product.

Example:

```text
No conflicts

That's a good thing.

Synesis hasn't detected a contradiction
between current project knowledge and
recent activity.

When one appears, it will show up here.
```

This is much better than a decorative illustration.

---

# 25. Loading States

Use skeletons and progressive rendering.

Example:

```text
Project State
────────────────────

████████████████
████████

████████████
████████████
```

Do not make every screen show a pulsing AI animation.

---

# 26. Interaction Principles

## Principle 1 — Evidence before automation

The user should see supporting evidence before approving significant changes.

## Principle 2 — Suggestion before mutation

AI proposes; the system records; humans approve important changes.

## Principle 3 — Context is always nearby

Users should not have to leave the current screen to understand why something happened.

## Principle 4 — State is versioned

The UI should make it obvious when a project state changed.

## Principle 5 — No magical actions

Every automated action must have an explanation and source.

---

# 27. Motion

Motion should be subtle.

### Use

- 150–220ms transitions
- slide-in evidence drawers
- hover elevation changes
- smooth tab transitions
- graph node focus
- optimistic status updates

### Avoid

- floating particles
- neon glow
- excessive parallax
- full-page animated backgrounds
- continuously moving AI avatars

Motion should communicate state, not decorate the screen.

---

# 28. Border Radius

Use a restrained radius scale:

```text
2px   hairline / tags
6px   controls
8px   cards
12px  panels
16px  floating surfaces
```

Do not use 24–32px radius everywhere.

The product should feel structured, not toy-like.

---

# 29. Shadows

Use very light shadows.

Default:

```text
0 4px 14px rgba(25,35,28,0.06)
```

Elevated:

```text
0 12px 30px rgba(25,35,28,0.09)
```

Avoid huge soft shadows.

---

# 30. Glassmorphism Rules

Glass is allowed only where it helps hierarchy.

### Good

```text
Top navigation
Command palette
Evidence drawer
Floating filters
Modal confirmation
```

### Bad

```text
Every card
Every table
Every sidebar item
Every graph node
```

Overusing glass is the fastest way to make the product look AI-generated.

---

# 31. Neumorphism Rules

Use neumorphism only for:

```text
small switches
segmented controls
compact icon actions
graph controls
```

Never use it for:

```text
large content cards
tables
long forms
main dashboard sections
```

Accessibility always takes priority over visual style.

---

# 32. Tables

Tables should be clean and editorial.

```text
Decision       Status       Source       Updated

DEC-019        Confirmed    Meet #42     14:27
DEC-018        Confirmed    Slack        12:41
DEC-017        Superseded   Meet #39     Yesterday
```

Use row hover.

Avoid boxed cells.

Use dividers instead.

---

# 33. Forms

Forms should feel calm.

Label:

```text
Project description
```

Input:

```text
┌─────────────────────────────────────────┐
│ Describe what you're building...        │
│                                         │
└─────────────────────────────────────────┘
```

Do not put labels inside the input as the only affordance.

Validation should be immediate and specific.

---

# 34. Buttons

Primary:

```text
background: #173F35
text: #FFFFFF
radius: 7px
height: 38px
```

Secondary:

```text
background: #FFFFFF
border: #D9DFD9
text: #173F35
```

Tertiary:

```text
transparent
text: #425249
```

Danger:

Use an outlined or low-emphasis treatment until confirmed.

---

# 35. Status System

Use text + icon + color.

Example:

```text
● Connected
● Working
● Waiting
● Requires review
● Failed
```

Never rely on color alone.

---

# 36. Responsive Design

### Desktop

Three-column compositions can be used where useful.

### Tablet

Collapse sidebars and stack secondary panels.

### Mobile

Prioritize:

```text
Overview
Conflicts
Meetings
Decisions
```

Heavy graph interactions may switch to a list representation.

---

# 37. Accessibility

Minimum requirements:

- WCAG AA contrast
- keyboard navigation
- focus states
- visible active states
- reduced motion support
- screen-reader labels
- no color-only status indicators
- logical tab order

Glassmorphism must never reduce text contrast.

---

# 38. Design Tokens

Suggested token names:

```css
--canvas: #F6F7F5;
--surface: #FFFFFF;
--surface-soft: #FBFCFA;

--text: #171A17;
--text-muted: #68706A;

--border: #E7EAE5;
--border-strong: #D6DDD5;

--primary: #173F35;
--primary-soft: #E8F0EC;

--info: #2F6B9A;
--warning: #A87517;
--danger: #B84B4B;
--success: #2F7154;

--radius-sm: 6px;
--radius-md: 8px;
--radius-lg: 12px;
--radius-xl: 16px;
```

---

# 39. Component Library

Build reusable components before page-specific styling.

Required components:

```text
AppShell
Sidebar
Topbar
ProjectSelector
CommandPalette
Search
StatusBadge
MetricStrip
DecisionCard
ConflictCard
EvidenceDrawer
SourceCard
MeetingTimeline
TranscriptBlock
AgentCard
ProjectStateNode
StateVersionBadge
ReviewPanel
DataTable
EmptyState
Skeleton
Toast
Modal
```

---

# 40. Visual Hierarchy

The most important screen hierarchy should be:

```text
1. What changed?
2. What needs attention?
3. What is the current project state?
4. Why does the system believe it?
5. What can I do next?
```

Not:

```text
1. AI branding
2. Fancy metrics
3. Decorative graphs
4. Chat
5. Everything else
```

---

# 41. Homepage / Landing Page Direction

The marketing site should use the same visual system but with more editorial expression.

Hero:

```text
YOUR PROJECT,
AS IT ACTUALLY STANDS.

Synesis turns meetings, conversations,
decisions, and work artifacts into one
evidence-backed project state.

[See how it works]      [Start building]
```

Visual:

A live project-state graph on the right, with a subtle evidence trail.

Do not use:

- robot illustrations
- humanoid AI graphics
- glowing brains
- generic circuit patterns

---

# 42. Signature Brand Moment

The key visual interaction should be a **State Change Review**.

Example:

```text
A new statement arrives
        ↓
Synesis notices a difference
        ↓
──────────────────────────────

PROJECT STATE CHANGE

Current
BA → Project → Functional → Tech

Proposed
Onboarding → BA → Project → Functional → Tech

Why?
Google Meet · Product Architecture #42

──────────────────────────────

[ Keep current ]    [ Approve change ]
```

This interaction should feel unmistakably like Synesis.

It demonstrates the product's real value immediately.

---

# 43. Design Do / Don't

## DO

- use whitespace
- use restrained green accents
- use editorial typography selectively
- use evidence drawers
- use clean graphs
- use subtle glass surfaces
- use human review states
- use strong information hierarchy

## DON'T

- make everything rounded
- use gradients everywhere
- use neon colors
- use purple AI aesthetics
- fill dashboards with meaningless numbers
- put a chatbot in every corner
- hide important evidence behind multiple clicks
- make automation feel autonomous when it isn't

---

# 44. MVP Design Priority

Implement in this order:

### P0

1. Application shell
2. Overview
3. Meetings
4. Meeting detail
5. Project State
6. Conflict Center
7. Evidence Drawer

### P1

8. Decisions
9. Sources
10. AI Workforce
11. Search
12. Command Palette

### P2

13. Requirements
14. Architecture editor
15. Advanced project timeline
16. Administration

---

# 45. Recommended Frontend Stack

```text
Next.js
React
TypeScript

Tailwind CSS
shadcn/ui

TanStack Query
React Hook Form
Zod

React Flow

Lucide Icons

Framer Motion
```

Use the component system as a foundation, but avoid a visually generic “shadcn clone”.

Customize:

- spacing
- typography
- surfaces
- status treatments
- tables
- graph nodes
- review panels

---

# 46. Final Design Direction

Synesis should feel like:

> **Linear + Notion's clarity + an operations console + a subtle premium editorial layer.**

But it must not become a copy of any of them.

The identity comes from one unique interaction:

> **Every important piece of project knowledge can be traced from current state → change → evidence → source → human decision.**

That interaction should drive the UI.

The visual language exists to make that relationship obvious, trustworthy, and fast to understand.

---

# 47. Design North Star

When reviewing any screen, ask:

### “Does this help a serious team understand what is true, what changed, and why?”

If yes, keep it.

If it is merely there to make the interface look “AI-powered”, remove it.

---

# 48. First Design Deliverable

The first polished UI prototype should include:

```text
1. Overview
2. Project State
3. Conflict Center
4. Meeting Detail
5. Evidence Drawer
6. Sources
```

These six screens establish the product's identity and demonstrate the core value without requiring the entire platform to be complete.
