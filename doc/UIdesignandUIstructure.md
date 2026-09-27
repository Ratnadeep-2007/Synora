# Synesis — Enterprise UI Design & UI Structure

**Status:** Canonical Enterprise UI Specification  
**Purpose:** Defines the production UI structure, visual system, placement, interaction behavior, states, accessibility, and information hierarchy for Synesis.

---

## 1. Product UI Purpose

Synesis is a serious project operating environment, not a prototype dashboard and not primarily a chatbot.

The UI is the human control room around this system:

```text
Sources
  ↓
Synesis Agent
  ↓
PostgreSQL / Project State / Evidence
  ↓
Governed Actions
  ↓
Living Excalidraw Workspace
```

The interface must make these questions easy to answer:

```text
What is true?
What changed?
Why?
What evidence supports it?
What is uncertain?
What needs approval?
What did the agent do?
What does the project workspace currently show?
```

Do not add UI because it looks "AI-powered". Every element must support understanding, control, evidence, or execution.

---

# 2. Core Product Interaction Model

There is one shared Synesis Agent across many projects.

```text
                    SYNESIS AGENT
                         |
          +--------------+--------------+
          |              |              |
       Project A      Project B      Project C
          |              |              |
       Context A       Context B       Context C
       State A         State B         State C
       Evidence A      Evidence B      Evidence C
       Tools A         Tools B         Tools C
       Excalidraw A    Excalidraw B    Excalidraw C
```

The UI must present the active project's context clearly.

BA, Planning, Functional, Technical, and Frappe are specialist capabilities coordinated by the Project Agent. They are not separate top-level agents in the primary product model.

---

# 3. Visual Personality

Synesis should feel:

```text
Precise
Calm
Intelligent
Trustworthy
Operational
Enterprise-grade
```

It must not feel:

```text
Cyberpunk
Game-like
Gimmicky
Over-automated
AI-toy-like
```

Avoid:

- purple/blue AI gradients
- neon glows
- glowing brains
- robots/humanoids
- decorative circuit patterns
- excessive blur
- excessive glass
- excessive rounded cards
- meaningless KPI walls
- fake confidence meters
- fake system health values
- permanent pulsing AI animations

---

# 4. Visual System

## 4.1 Canvas and surfaces

```text
Canvas       #F6F7F5
Surface      #FFFFFF
Surface Soft #FBFCFA
Border       #E7EAE5
Text Main    #171A17
Text Muted   #68706A
```

## 4.2 Accent

```text
Primary      #173F35
Primary 2    #285C4F
Primary Soft #E8F0EC
```

## 4.3 Status

```text
Info         #2F6B9A
Warning      #A87517
Danger       #B84B4B
Success      #2F7154
```

Use status colors sparingly. Never rely on color alone.

---

# 5. Typography

Primary typeface:

```text
Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif
```

Optional display face:

```text
Newsreader
```

Use Newsreader only for occasional large editorial page titles.

Type scale:

```text
Display      40px / 46px / 600
Page title   30px / 36px / 600
Section      20px / 26px / 600
Card title   16px / 22px / 600
Body         14px / 21px / 400
Small        12px / 18px / 500
Micro        11px / 16px / 600
```

Do not use giant 64–80px dashboard typography.

---

# 6. Layout System

Desktop:

```text
Sidebar             240px
Topbar               64px
Page padding         32px
Main max width       1440px
Primary gap          20–24px
```

Use a 12-column responsive grid.

Tablet:

```text
Collapsible sidebar
Page padding: 24px
```

Mobile:

```text
Drawer / bottom navigation
Page padding: 16px
```

The primary task must remain visually dominant on every screen.

---

# 7. Global Shell

Desktop:

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ S  Project: WorkSimplified ▼                 Search  Activity  User     │
├──────────────────┬──────────────────────────────────────────────────────┤
│                  │                                                      │
│ Overview         │                                                      │
│ Project State    │                     Main Workspace                   │
│ Excalidraw       │                                                      │
│ Meetings         │                                                      │
│ Evidence         │                                                      │
│ Decisions        │                                                      │
│ Conflicts        │                                                      │
│ Agent            │                                                      │
│ Sources          │                                                      │
│                  │                                                      │
│ Settings         │                                                      │
└──────────────────┴──────────────────────────────────────────────────────┘
```

Sidebar is navigation, not decoration.

Selected item:

- dark green text
- pale green background
- 3px left indicator
- no gradient

---

# 8. Topbar

Height:

```text
64px
```

Contents, left to right:

```text
Synesis mark
Project selector
Spacer
Global search
Activity
Help
User menu
```

Use restrained glass treatment only on the topbar:

```text
background: rgba(255,255,255,0.78)
backdrop-filter: blur(14px)
border-bottom: 1px solid #E7EAE5
```

The topbar must always expose the current project.

---

# 9. Project Selector

The selector is a primary control.

It must show:

```text
Project name
Workspace name
Environment where applicable
```

Opening it provides:

```text
Search projects
Recent projects
Create project
Switch project
```

Switching projects must change the entire application context safely.

---

# 10. Primary Navigation

Use exactly this primary enterprise structure:

```text
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
```

Do not create separate top-level navigation entries for BA, Planner, Functional, Tech, or Frappe.

---

# 11. Overview Screen

Purpose:

> Understand the current project in seconds.

Page structure:

```text
Page header
↓
Project Pulse
↓
Current State + Attention Required
↓
Recent Activity
↓
Excalidraw Preview
↓
Agent Activity
```

### Header

```text
WorkSimplified
Project overview
Last synchronized: 2 min ago
```

### Project Pulse

Show only real values:

```text
● Context synchronized
18 Requirements
7 Decisions
2 Open Conflicts
5 Open Questions
3 Pending Reviews
```

Clicking a metric opens the corresponding filtered page.

---

# 12. Overview — Current State

Left side of the main two-column area.

Display a compact visual summary of:

```text
Vision
Requirements
Architecture
Workflow
Decisions
```

Prefer visuals and short labels.

---

# 13. Overview — Attention Required

Right side of the main two-column area.

Only actionable items belong here.

Examples:

```text
Architecture proposal requires approval
Slack evidence conflicts with requirement
Google Meet transcript processing failed
Excalidraw synchronization pending
```

Every attention item contains:

```text
Issue
Why it matters
Current status
Primary action
```

No vague alerts.

---

# 14. Overview — Recent Activity

Use a vertical timeline:

```text
14:32  Project State changed
       Requirement REQ-021 approved

14:27  Decision confirmed
       Invoice approval workflow

14:22  Excalidraw synchronized
       Architecture node added

14:18  Slack event processed
       Candidate requirement detected
```

Each activity item can open the source record.

---

# 15. Overview — Excalidraw Preview

This is a first-class module, not a decoration.

```text
LIVING PROJECT WORKSPACE

● Synchronized
Updated 2 min ago

[Visual preview]

8 decisions
12 requirements
4 architecture groups
1 pending review

[Open Excalidraw]
```

Do not make the Overview canvas fully editable.

---

# 16. Project State Screen

Project State is the authoritative structured project representation.

Header:

```text
Project State
Current state: v18
Updated: 25 Sep · 14:32
[View history]
```

Tabs:

```text
Overview
Vision
Requirements
Architecture
Workflow
Decisions
Constraints
Assumptions
Questions
Risks
Dependencies
```

The version is a project-state control and historical record. Document metadata should not use artificial product release numbers.

---

# 17. Project State Layout

```text
┌──────────────────────────────────────────────────────────────┐
│ Project State                                                 │
├──────────────────────────────────────────────────────────────┤
│ Summary / current status                                      │
├──────────────────────────────────────┬───────────────────────┤
│ Main state content                   │ Context / evidence   │
│                                      │                       │
│ Requirements                         │ Why?                  │
│ Architecture                        │ Evidence              │
│ Decisions                           │ History               │
└──────────────────────────────────────┴───────────────────────┘
```

The state content is primary; context is secondary.

---

# 18. Project State History

History is chronological and immutable.

```text
v18  25 Sep 14:32  Requirement approved
v17  25 Sep 12:10  Architecture revised
v16  24 Sep 18:42  Decision confirmed
```

Selecting a version shows:

```text
Version
Reason
Actor
Source
Evidence
Changes
```

Rollback must be explicit and confirmation-gated.

---

# 19. State Change Review

Signature enterprise interaction:

```text
PROJECT STATE CHANGE

CURRENT
BA → Project → Functional → Tech

PROPOSED
Onboarding → BA → Project → Functional → Tech

WHY
Google Meet · Architecture Sync
14:24:12 · CEO

IMPACT
Changes approved workflow sequence

[Keep current] [Approve change]
```

For consequential changes, evidence must appear before the approval action.

---

# 20. Excalidraw Screen

Excalidraw is a primary application destination and the project's living visual workspace.

Layout:

```text
┌─────────────────────────────────────────────────────────────────┐
│ Excalidraw     ● Synchronized       Last update: 2 min ago      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│                                                                 │
│                         CANVAS                                  │
│                                                                 │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│ Recent visual changes | Pending proposals | Evidence           │
└─────────────────────────────────────────────────────────────────┘
```

The canvas gets the majority of the viewport.

---

# 21. Excalidraw Visual Principle

Mandatory rule:

> MINIMUM TEXT + MAXIMUM VISUAL EXPLANATION

Prefer:

- flow diagrams
- architecture maps
- dependency graphs
- timelines
- visual decision cards
- requirement nodes
- relationship diagrams
- compact status markers
- icons
- images
- arrows and grouping

Avoid:

- paragraphs
- transcript dumps
- meeting-summary walls
- long explanatory text
- duplicated statements
- large tables unless unavoidable

---

# 22. Visual Mapping Rules

```text
Process       → Flow diagram
Hierarchy     → Tree
Dependencies  → Graph
Timeline      → Timeline
Architecture  → System diagram
Decision      → Compact decision card
Requirement   → Requirement node/card
Conflict      → Side-by-side comparison
Risk          → Risk map
Relationship  → Connected nodes
Evidence      → Small source badge/link
```

The agent must choose the visual form that best explains the content.

---

# 23. Excalidraw Workspace Zones

A project canvas can contain visually separated regions:

```text
PROJECT OVERVIEW
VISION
REQUIREMENTS
DECISIONS
OPEN QUESTIONS
RISKS / CONFLICTS
ARCHITECTURE
WORKFLOW
DEPENDENCIES
EVIDENCE
AGENT OUTPUTS
```

These are visual areas, not separate database tables or required text headers.

---

# 24. Excalidraw Content Example

Instead of:

```text
The customer said the invoice must be approved before generation.
This was confirmed by the finance lead on 25 September.
```

Prefer:

```text
CUSTOMER
   ↓
┌────────────┐
│  APPROVAL  │ ✓
└─────┬──────┘
      ↓
┌────────────┐
│  INVOICE   │
└─────┬──────┘
      ↓
┌────────────┐
│  GENERATE  │
└────────────┘

Confirmed · Slack · 25 Sep
```

Evidence is linked through a small badge rather than a paragraph.

---

# 25. Excalidraw Synchronization Bar

Show one of:

```text
● Synchronized
● Updating
● Pending review
⚠ Out of date
✕ Synchronization failed
```

Always use icon + text.

If synchronization fails, say what was preserved.

Example:

```text
Excalidraw synchronization failed.
Project State is safe.
Last successful synchronization: 14:22
[Retry] [View details]
```

---

# 26. Excalidraw Visual Change Review

High-impact changes use a review surface:

```text
VISUAL CHANGE PROPOSAL

Current workspace
        vs
Proposed workspace

Reason
Evidence
Affected elements
Impact

[Keep current]
[Approve & apply]
```

Never silently overwrite the workspace.

---

# 27. Meetings Screen

Meetings is the source activity workspace.

Header:

```text
Meetings
[Search] [Source filter] [Status filter]
```

Each meeting row shows:

```text
Meeting name
Date/time
Participants
Transcript status
Processing status
Source
Action
```

Example:

```text
Product Architecture Sync
25 Sep · 14:00
6 participants
Transcript available · Processed
[Open]
```

---

# 28. Meeting Detail

Desktop uses two primary columns:

```text
┌────────────────────────────────┬─────────────────────────────┐
│ Transcript                     │ Intelligence                │
│                                │                             │
│ 14:24:12 CEO                   │ PROPOSAL                    │
│ "We should..."                 │ Move approval before...     │
│                                │                             │
│ 14:25:31 CTO                   │ [Review]                   │
│ "Let's discuss..."             │                             │
└────────────────────────────────┴─────────────────────────────┘
```

Both columns can scroll independently.

---

# 29. Transcript Block

Each transcript block contains:

```text
Timestamp
Speaker
Original text
```

Do not paraphrase the transcript in the transcript view.

Derived interpretation belongs in the Intelligence panel.

---

# 30. Meeting Intelligence

Display:

```text
Type
Statement
Status
Evidence
Action
```

Example:

```text
PROPOSAL
Move approval before invoice generation.
Status: Needs review
Meet · 14:24:12
[Why?]
```

Do not expose hidden chain-of-thought.

Show concise, inspectable evidence-backed explanations.

---

# 31. Evidence Screen

Evidence is a first-class trust surface.

Display:

```text
Evidence ID
Source
Actor / speaker
Timestamp
Content
Referenced knowledge
Referenced decisions
Referenced state changes
```

Users should be able to move from:

```text
Project State
→ Decision / Requirement
→ Evidence
→ Source
```

---

# 32. Evidence Drawer

The Evidence Drawer opens from the right without losing the user's context.

```text
┌───────────────────────────────────┐
│ WHY THIS EXISTS                   │
│                                   │
│ Decision DEC-019                  │
│                                   │
│ Source      Google Meet           │
│ Meeting     Architecture Sync     │
│ Speaker     CEO                   │
│ Timestamp   14:24:12              │
│                                   │
│ Evidence                            │
│ "Approval is required..."        │
│                                   │
│ Status      Confirmed              │
│                                   │
│ [Open meeting]                     │
└───────────────────────────────────┘
```

The drawer should be wide enough for comfortable reading but must not obscure the entire desktop by default.

---

# 33. Decisions Screen

Decisions are shown as an operational log.

Columns:

```text
Decision
Status
Source
Actor
Date
State impact
```

Statuses:

```text
Confirmed
Proposed
Superseded
Rejected
Needs review
```

Every meaningful decision links to evidence.

---

# 34. Decision Detail

Order:

```text
Decision
Statement
Status
Participants
Source
Evidence
State impact
History
```

Reversal and supersession must be visibly distinct from ordinary updates.

---

# 35. Conflict Center

Conflict Center is a review queue, not a warning wall.

Top area:

```text
Requires attention: 2
Under discussion: 3
Resolved: 14
```

Each conflict contains:

```text
Title
Type
Current state
New information
Source
Evidence
Impact
Status
Action
```

---

# 36. Conflict Detail

Always answer:

```text
What is current?
What changed?
Why did Synesis detect it?
What evidence supports it?
What could be affected?
What can the user do?
```

Actions:

```text
Approve
Keep current
Mark unresolved
Discuss
Open evidence
```

Never use a generic destructive action such as "Fix with AI".

---

# 37. Project Agent Screen

Present ONE shared Synesis Agent for the active project.

Header:

```text
SYNESIS AGENT ● Active

Project: WorkSimplified
Project State: v18
Context: Synchronized
Excalidraw: Synchronized
```

Then capabilities:

```text
CAPABILITIES

Business Analysis        Ready
Planning                  Ready
Functional Design        Ready
Technical Design         Ready
Frappe Engineering       Ready
```

---

# 38. Agent Activity

Show operational activity rather than hidden reasoning:

```text
14:25  Received Slack message
14:25  Retrieved relevant project context
14:26  Detected possible requirement change
14:26  Compared against Project State
14:26  Conflict created
14:27  Visual proposal generated
14:27  Awaiting approval
```

Do not expose private chain-of-thought.

---

# 39. Agent Run Detail

Display:

```text
Run ID
Project
Capability
Start time
End time
Status
State context
Inputs
Tools used
Outputs
Approval
Errors
```

Input/output references should be clickable where the user's permission allows it.

---

# 40. Agent Tool Activity

Use human-readable labels:

```text
Tool activity

Google Meet
Read transcript

PostgreSQL
Retrieved requirements

Excalidraw
Prepared visual update

Status: Awaiting approval
```

Never display secrets, tokens, or raw private prompts.

---

# 41. Sources Screen

Current sources:

```text
COMMUNICATION
Google Meet
Slack
WhatsApp (when enabled)

DESIGN
Excalidraw
```

Future connectors can be added without changing the page structure.

Each source card shows:

```text
Source
Connection state
Account / workspace
Permissions
Last sync
Health
Manage
Disconnect
```

---

# 42. Google Meet Source UI

```text
Google Meet
● Connected

Account
user@company.com

Permissions
Read Meet information and transcripts

Last sync
2 min ago

[Manage] [Sync now] [Disconnect]
```

Do not display OAuth secrets.

---

# 43. Slack Source UI

```text
Slack
● Connected

Workspace
Acme

Project channels
8

Last sync
1 min ago

[Manage] [Sync now] [Disconnect]
```

---

# 44. WhatsApp Source UI

When implemented:

```text
WhatsApp
● Connected

Session
Project Operations

Last sync
2 min ago

[Manage] [Disconnect]
```

Do not expose authentication/session secrets.

---

# 45. Excalidraw Source UI

```text
Excalidraw
● Synchronized

Workspace
WorkSimplified

Last update
2 min ago

[Open workspace] [Sync]
```

The same integration is used for input and output.

---

# 46. Create Project Flow

Project creation is a core workflow.

Use a focused full-page flow or modal sheet.

```text
1. Project name
2. What are you building?
3. Initial context
4. Connect tools
5. Create project
```

Do not expose internal database or agent infrastructure terminology to normal users.

---

# 47. Project Creation Completion

Show:

```text
PROJECT READY

WorkSimplified

Synesis Agent
● Active

Project State
Initialized

Excalidraw
● Ready

Connected sources
0

[Open project]
```

---

# 48. Global Search

Search the active project first.

Domains:

```text
Project State
Decisions
Requirements
Evidence
Meetings
Conflicts
Agent activity
Excalidraw references
Sources
```

Results must show why they matched.

Unauthorized results must never appear.

---

# 49. Command Palette

Keyboard:

```text
⌘ K
```

Actions:

```text
Search project
Open recent meeting
Review conflicts
View current state
Open Excalidraw
Connect source
Create requirement
Open agent
```

Keep it fast and compact.

---

# 50. Notifications

Notifications are operational, not promotional.

Valid examples:

```text
1 conflict requires review
Google Meet transcript is ready
Excalidraw synchronization failed
Source authorization expired
Agent action requires approval
```

Avoid fake urgency.

---

# 51. Settings

Structure settings as:

```text
Workspace
Members
Permissions
Sources
Security
Data & Retention
AI Governance
Notifications
Audit
```

Only authorized users see administrative sections.

---

# 52. Enterprise Administration

Administration must cover:

```text
Users
Memberships
Roles
Policies
Source connections
Retention
Audit
Security events
AI governance
System health
```

The interface should be dense and functional rather than decorative.

---

# 53. Permission UX

When permission is denied:

```text
You do not have permission to perform this action.

Required permission:
Approve Project State changes

Contact:
Workspace Administrator
```

Do not disclose information from inaccessible resources.

---

# 54. Confirmation Dialogs

Use confirmation for:

- disconnect source
- delete data
- rollback
- permission changes
- approve high-impact state change
- destructive external action

Example:

```text
Approve Project State Change?

This will change:
Agent Workflow

From:
BA → Project → Functional

To:
Onboarding → BA → Project → Functional

Evidence:
Meet #42 · 14:24:12

[Cancel] [Approve change]
```

---

# 55. Loading States

For long-running processing, show real stages:

```text
Processing meeting

✓ Retrieved transcript
✓ Normalized transcript
● Extracting project knowledge
○ Checking conflicts
○ Preparing visual update
```

Never display a generic spinner for an operation whose real stage is known.

---

# 56. Error States

Every error must answer:

```text
What failed?
What was preserved?
What can the user do?
```

Example:

```text
Excalidraw synchronization failed.

Project State is safe.

Last successful synchronization: 14:22

[Retry] [View details]
```

---

# 57. Empty States

Empty states should explain the meaning of the empty result.

New project:

```text
Your project is ready.

Connect a source or add initial context
to begin building project knowledge.
```

No conflicts:

```text
No conflicts

Synesis has not detected a contradiction
between the current project state and recent activity.
```

---

# 58. Status System

Use icon + text + restrained color:

```text
● Connected
● Working
● Waiting
● Requires review
● Failed
● Synchronized
● Pending
```

Do not use color as the sole status signal.

---

# 59. Buttons

Primary:

```text
Background #173F35
Text       #FFFFFF
Height     38px
Radius     7px
```

Secondary:

```text
Background #FFFFFF
Border     #D9DFD9
Text       #173F35
```

Tertiary:

```text
Transparent
Text #425249
```

Danger actions should require confirmation where destructive.

---

# 60. Border Radius

```text
2px   tags
6px   controls
8px   cards
12px  panels
16px  floating surfaces
```

Do not use oversized 24–32px rounding throughout the product.

---

# 61. Shadows

Default:

```text
0 4px 14px rgba(25,35,28,0.06)
```

Elevated:

```text
0 12px 30px rgba(25,35,28,0.09)
```

Use minimal shadows.

---

# 62. Glassmorphism

Allowed only for:

```text
Topbar
Command palette
Evidence drawer
Floating filters
Modal overlays
Transient review panels
```

Do not turn every card into glass.

---

# 63. Precision Neumorphism

Allowed only for:

```text
small toggles
segmented controls
compact icon actions
graph controls
```

Never use it for large content surfaces.

---

# 64. Tables

Use tables when the information is naturally tabular.

Prefer:

- clear headers
- compact rows
- subtle horizontal dividers
- hover state
- sorting
- filtering
- pagination when necessary

Avoid heavy boxed cells.

---

# 65. Forms

Every form field uses:

```text
Label
Input
Helper text when needed
Validation
Error
```

Never use placeholder text as the only label.

Validation must be specific and immediate.

---

# 66. Responsive Rules

## Desktop

Use multi-column layouts where the workflow benefits from simultaneous context.

## Tablet

Collapse secondary panels first. Preserve primary actions.

## Mobile

Prioritize:

```text
Overview
Conflicts
Meetings
Decisions
Project State
```

Complex graph interactions can switch to list/stacked representations.

Excalidraw may open as a dedicated canvas surface on small screens rather than being compressed into an unusable embedded frame.

---

# 67. Accessibility

Minimum:

- WCAG AA contrast
- keyboard navigation
- visible focus states
- semantic headings
- screen-reader labels
- logical tab order
- reduced motion support
- no color-only status indicators
- accessible dialogs and drawers
- accessible alternatives for important graph information

Visual effects must never reduce readability.

---

# 68. Keyboard Behavior

```text
⌘ K     Open command/search palette
Esc     Close dialog/drawer
Tab     Move between controls
Enter   Activate focused action
Arrow   Navigate menus/tabs where appropriate
```

All core workflows must work without a mouse.

---

# 69. Motion

Motion explains state and hierarchy.

Use:

```text
150–220ms transitions
Drawer slides
Subtle hover elevation
Tab transitions
Focused graph movement
```

Avoid:

- perpetual pulsing
- floating particles
- animated backgrounds
- AI avatars
- excessive parallax

---

# 70. Core Component Library

Build reusable components first:

```text
AppShell
Sidebar
Topbar
ProjectSelector
Search
CommandPalette
ProjectPulse
StatusBadge
DecisionCard
RequirementCard
ConflictCard
EvidenceDrawer
EvidenceCard
MeetingList
TranscriptBlock
IntelligenceItem
ProjectStatePanel
StateDiff
StateHistory
ApprovalDialog
ProjectAgentPanel
CapabilityCard
AgentActivityFeed
AgentRunDetail
ExcalidrawWorkspace
ExcalidrawSyncBar
SourceCard
SourceDetail
DataTable
EmptyState
Skeleton
Toast
Modal
NotificationCenter
AuditTimeline
```

Prefer shared components over page-specific visual duplication.

---

# 71. Information Hierarchy

Across the product, priority is:

```text
1. What changed?
2. What needs attention?
3. What is the current project state?
4. Why does Synesis believe it?
5. What action can the user take?
```

Not:

```text
1. AI branding
2. Decorative metrics
3. Animations
4. Chat
```

---

# 72. Trust and Provenance

Important objects must expose:

```text
Source
Timestamp
Actor
Evidence
State impact
```

The UI should support the path:

```text
Current State
   ↓
Change
   ↓
Decision / Requirement
   ↓
Evidence
   ↓
Source
```

This is a core product interaction, not an optional detail page.

---

# 73. Agent Transparency

Show operational facts:

```text
Retrieved 4 relevant requirements.
Detected a potential conflict.
Created a review proposal.
Prepared an Excalidraw update.
```

Do not show hidden chain-of-thought or private internal reasoning.

---

# 74. Project Context Safety

Every visible page must make the current project context obvious.

Every project-scoped request must be authorized server-side.

The UI must never imply that projects share memory or source access.

---

# 75. Data and UI Truthfulness

The UI must display backend reality.

Never display:

- fake metrics
- fake synchronization status
- fake connection status
- mocked records in production paths
- fabricated AI confidence
- simulated integrations as real

Seed/demo data must be clearly labeled and separated from real enterprise data.

---

# 76. Excalidraw Text Density Rule

This is a hard product rule:

> Excalidraw should use the smallest amount of text required to make the visual meaning clear.

Use:

```text
short labels
icons
nodes
arrows
relationships
visual grouping
small source references
```

Do not use Excalidraw as a document editor or transcript repository.

The visual workspace should explain the project at a glance.

---

# 77. Enterprise UI Quality Gate

A screen is ready only when:

```text
The active project is obvious.
The primary task is obvious.
Important state is real.
Evidence is reachable.
Status is explicit.
Permissions are respected.
Errors explain what was preserved.
High-impact actions show consequences.
No decorative element competes with project information.
```

---

# 78. Canonical Screen Map

```text
AUTHENTICATED APPLICATION
│
├── Overview
│   ├── Project Pulse
│   ├── Current State
│   ├── Attention
│   ├── Recent Activity
│   ├── Excalidraw Preview
│   └── Agent Activity
│
├── Project State
│   ├── Overview
│   ├── Vision
│   ├── Requirements
│   ├── Architecture
│   ├── Workflow
│   ├── Decisions
│   ├── Constraints
│   ├── Assumptions
│   ├── Questions
│   ├── Risks
│   ├── Dependencies
│   └── History
│
├── Excalidraw
│   ├── Living Canvas
│   ├── Sync Status
│   ├── Visual Changes
│   └── Pending Reviews
│
├── Meetings
│   ├── List
│   └── Detail
│       ├── Transcript
│       ├── Intelligence
│       └── Evidence
│
├── Evidence
│   └── Evidence Detail
│
├── Decisions
│   └── Decision Detail
│
├── Conflicts
│   └── Conflict Review
│
├── Agent
│   ├── Project Agent
│   ├── Capabilities
│   ├── Activity
│   └── Run Detail
│
├── Sources
│   ├── Source Catalog
│   └── Source Detail
│
└── Settings
    ├── Workspace
    ├── Members
    ├── Permissions
    ├── Sources
    ├── Security
    ├── Data & Retention
    ├── AI Governance
    ├── Notifications
    └── Audit
```

---

# 79. Final UI Principle

Synesis should feel like:

> **A serious enterprise project workspace with one intelligent agent continuously maintaining project understanding and a living visual Excalidraw workspace.**

The interface exists to make that system observable, explainable, controllable, and useful.

If an element does not improve project understanding, governance, evidence, or execution, remove it.
