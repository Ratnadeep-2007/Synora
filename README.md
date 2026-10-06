# Synora 🚀
> **Autonomous Multi-Channel Ingestion & Living Architecture Workspace**

Synora bridges unstructured discussions across communication channels (Google Meet transcripts, WhatsApp messages, and direct uploads) with a dynamic, living system architecture workspace powered by a single database-backed Excalidraw Project Atlas, deterministic pipeline synthesis, semantic project routing, and Gemini-driven architecture planning.

---

## 🌟 Key Features

1. **Multi-Channel Ingestion Engine**
   - **Google Meet & Calendar Integration**: Automatic sync, push notifications, and transcript parsing.
   - **WhatsApp Baileys Bridge**: Native multi-device WebSocket connection for real-time group and direct chat ingestion.
   - **Manual Transcript Uploader**: Instant text & file pipeline ingestion.
   - **Google Meet Vexa Capture**: Self-hosted bot capture with post-meeting Sarvam Saaras STT for accounts without native Meet transcripts.

2. **Shared Intelligence & Project Memory**
   - WhatsApp and Google Meet enter through source-specific adapters, then use the same normalized Evidence, Context Intelligence, Candidate Knowledge, and project-bounded Project Memory.
  - The Vexa path is only capture: Vexa records the Meet, Sarvam transcribes the completed recording, and the existing Synora pipeline handles routing, evidence, intelligence, memory and Excalidraw.
   - Meet adds a source-specific session projection for speakers, timestamps, routing/timeline windows, action items, decisions, requirements, and memory deltas without creating a second memory store.
   - A completed meeting is synchronized once into Synora's database; intelligence then runs from the persisted full transcript/evidence with zero additional Google API calls.
   - Routine evidence-backed memory updates are automatic; unresolved project routing is isolated in Unknown Context.

3. **AI Visual Canvas Engine (Excalidraw)**
   - Powered by **Gemini 3.8 Flash** for architecture planning and structured intelligence, with **Gemini Embedding 2** for semantic project retrieval.
   - Builds a single infinite **Project Atlas**: Context Inbox + fixed project columns, architecture-first composition, human-readable knowledge cards, evidence-linked revisions, and deterministic collision-safe layout.
   - Falls back to a deterministic geometric layout when the configured semantic provider is unavailable or rate-limited.

4. **Living Workspace & Project Management**
   - One infinite Excalidraw Project Atlas with stable non-overlapping project columns and live database synchronization.
   - Full project lifecycle tracking: requirements, decisions, tasks, and architecture state history.
   - Real-time notification center and source connection management.

---

## 🏗️ System Architecture

For a comprehensive breakdown of all 24 database models, 3 architectural pillars, API endpoints, and end-to-end data flows, see:
📖 **[SYNORA_COMPLETE_SYSTEM_ARCHITECTURE.md](./SYNORA_COMPLETE_SYSTEM_ARCHITECTURE.md)**

```
┌──────────────────────────────────────────────────────────────┐
│                    SYNORA PLATFORM                          │
├──────────────────────┬──────────────────────┬────────────────┤
│   Ingestion Layer    │   Synthesis Core     │ Living Canvas  │
│  - Google Meet       │  - Pipeline Engine   │ - Excalidraw   │
│  - WhatsApp Baileys  │  - Graph Builder     │ - NVIDIA NIM   │
│  - File/Text Upload  │  - Deterministic DB  │ - Live Sync    │
└──────────────────────┴──────────────────────┴────────────────┘
```

---

## 🛠️ Tech Stack

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy, SQLite/PostgreSQL, Pydantic v2, Pytest
- **Frontend**: Next.js 15 (App Router), TypeScript, Tailwind CSS, Lucide React, Excalidraw
- **Microservices**: Node.js Baileys Bridge (WhatsApp Web Multi-Device)
- **AI / LLM**: Gemini 3.8 Flash + Gemini Embedding 2 with Groq/NVIDIA failover and deterministic safety fallback

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.11+
- Node.js 18+ and npm
- (Optional) NVIDIA NIM API key for LLM visual generation

### 2. Environment Setup
Copy the example environment configuration:
```bash
cp .env.example .env
```
Fill in the credentials as needed:
- `NVIDIA_API_KEY`: Your NVIDIA NIM key (e.g. `nvapi-...`)
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`: For Google Workspace sync

### 3. Backend Setup
```bash
cd backend
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 4. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:3000` to access the Synora dashboard.

### 5. Running Tests
Run the complete backend test suite:
```bash
pytest backend/tests -v
```

---

## 📄 License
MIT License. Built with ❤️ by the Synora team.
