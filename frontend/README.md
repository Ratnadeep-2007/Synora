# Synesis Frontend — Living Visual Workspace & Project Agent Console

Production Next.js 14 (App Router) interface for Synesis, featuring an embedded native **Excalidraw Visual Workspace** powered by `@excalidraw/excalidraw`, real-time project switching, candidate knowledge review, and multi-source evidence provenance.

---

## Key Features

1. **Embedded Interactive Excalidraw Canvas**
   - Renders `@excalidraw/excalidraw` directly in the browser with full interactive whiteboard support (pan, zoom, draw, select, shape, text).
   - **Primary Agent Output**: The Project Agent directly renders System Architecture flows, emerald Living Decision Cards (with source citations and immutable evidence IDs), and active scope requirements onto the whiteboard.
   - **Two-Way Synchronization**:
     - *Agent ➔ Canvas*: One-click "Sync Agent Output" or auto-sync upon state changes re-draws the living canvas with latest state and evidence.
     - *Canvas ➔ State*: "Save Canvas to State" commits manual whiteboard edits back into the project's authoritative Excalidraw artifact.
   - Fullscreen expansion mode (`Esc` to exit).

2. **Multi-Project Workspace Switcher**
   - Easily switch between isolated projects (`Project A`, `Project B`, etc.).
   - Each project has its own dedicated **Project Agent**, memory context, authoritative state, and Excalidraw whiteboard.
   - Quick **"+ Create New Project"** modal automatically provisions a new Project Agent and Excalidraw canvas.

3. **Output Safety & Proposal Reviews (Role B)**
   - Displays structured visual diffs before diagram modifications mutate authoritative state.
   - Human review gates (Approve / Reject) for safety.

4. **Multi-Source Ingestion & Provenance Console**
   - Google Meet native REST API v2 integration.
   - Slack bot & channel event synchronization.
   - Evidence inspector with speaker utterances, timestamps, and confidence scores.

---

## Getting Started

### Development Server

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser.

### Production Build

```bash
npm run build
npm run start
```
