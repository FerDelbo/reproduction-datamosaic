# DataMosaic: Document-to-Database Extraction

DataMosaic bridges the gap between unstructured enterprise knowledge and
structured analytics. While Large Language Models (LLMs) excel at processing
local text, they often struggle with global database semantics—failing to
respect schemas, foreign keys, and integrity constraints.

DataMosaic solves this by mediating between LLM extraction and strict database
logic. Instead of a one-shot prompt, it uses an orchestrator-managed closed
loop to ensure the final database is not just filled with text, but is
structurally sound and analytically useful.

This repository contains the **full open-source release**, including the
algorithm core (`modules/`), a Flask + WebSocket backend (`backend/`),
a React + TypeScript frontend (`frontend/`), and an evaluation harness.

---

## 📄 Papers

This work is associated with two publications:

[1] **Zhengxuan Zhang**, Zhuowen Liang, Jiazhuo Chen, Haixun Wang, and Nan Tang. *Document-to-Database: Extraction Meets Relational Semantics.* VLDB, 2026.

[2] **Zhengxuan Zhang**, Zhuowen Liang, Haixun Wang, and Nan Tang. *DataMosaic: An Interactive Demonstration of Constraint-Driven Document-to-Database Construction.* VLDB Demo, 2026.

---

## ✨ Key Features

- **🏗️ Schema-Driven Extraction.** DataMosaic takes an ER schema (with
  integrity and business constraints) as input and ensures the extracted data
  actually fits your database structure.
- **🔄 Closed-Loop Refinement.** Implements an Extraction → Verification →
  Repair loop. It detects constraint violations (e.g., broken foreign keys)
  and performs targeted re-extraction to fix them.
- **🛡️ Semantic Consistency.** Distinguishes between intrinsic document
  ambiguity and correctable extraction errors.
- **🔌 Pluggable Architecture.** Supports third-party LLM extractors,
  domain-specific verifiers, and custom repair operators via the MCP
  (Multi-Constraint-Plugin) registry.
- **🖥️ Full-stack UI.** A React frontend lets you upload documents, define
  schemas (form-based or natural language), watch the agent loop run in
  real-time, and inspect / export the resulting database.

---

## 📁 Repository Layout

```
DataMosaic/
├── backend/                      # Flask API + WebSocket service
│   ├── app.py                    # Service entry point
│   ├── config.py                 # Paths, CORS, ports
│   ├── routes/                   # REST endpoints
│   │   ├── file_routes.py        # Upload / file listing
│   │   ├── doc2db_routes.py      # Extraction jobs & SSE stream
│   │   ├── memory_routes.py      # Snapshots / violations / fixes
│   │   ├── database_routes.py    # SQLite DB management
│   │   └── settings_routes.py    # Model & API key settings
│   ├── utils/                    # File / history / websocket helpers
│   └── websocket_signals.py      # Realtime signal broadcaster
│
├── frontend/                     # React + TypeScript SPA
│   ├── public/                   # Static assets
│   ├── src/
│   │   ├── App.tsx               # Root component
│   │   ├── components/           # Layout, panels, dialogs
│   │   │   ├── Doc2DBProcessor/  # Main extraction UI (config, steps, results)
│   │   │   ├── Doc2DBHistoryPanel.tsx
│   │   │   ├── DatabaseManager.tsx
│   │   │   └── FileLibraryWithUpload.tsx
│   │   ├── hooks/                # useFiles, usePanel, useDoc2DB
│   │   ├── services/             # WebSocket client
│   │   ├── constants/            # Theme & config (models, project)
│   │   └── styles/
│   ├── package.json
│   └── tsconfig.json
│
├── modules/                      # Core algorithm (the "DataMosaic" engine)
│   ├── agents/
│   │   ├── extractor/            # Entity & relation extractors (base + utils)
│   │   ├── verifier/             # MCP router + MCP-based verifier
│   │   ├── fixer/                # MCP-based repair operators
│   │   ├── orchestrator/         # Unified/parallel orchestrators, signal coordinator
│   │   └── mcp/                  # Pluggable constraint servers
│   │       ├── config/           # MCP plugin configuration
│   │       └── ...               # structure / value / logic / type /
│   │                               # temporal / aggregation / reference /
│   │                               # format / data quality
│   ├── core/                     # IO + ID generation (io.py, ids.py)
│   ├── memory/                   # Memory manager, snapshots, tables,
│   │                             # violations, fixes
│   ├── services/                 # Doc2DBService (used by the Flask backend)
│   ├── signals/                  # Internal signal bus (core + handlers)
│   └── utils/                    # Orchestrator logging, task helpers
│
├── llm/                          # LLM client routers (GPT / DeepSeek / Qwen)
│   ├── main.py                   # Unified get_answer() entry
│   ├── global_config.py          # Current model selector
│   ├── gpt.py / qwen.py / deepseek.py / utils.py
│   └── .env.example              # Copy to .env and fill in your keys
│
├── dataset/                      # Open-source evaluation datasets
│   ├── FinanceDB/ LegalDB/ PaperDB/ StudentDB/
│   │   └── <case>/docs/          # Per-case documents + schema
│
├── tests/                        # Unit tests (service, memory manager)
│
├── scripts/                      # Convenience launchers
│   ├── start_backend.sh
│   └── start_frontend.sh
│
├── test_dataset_evaluate.py      # Full system evaluation script
├── llm_evaluate.py               # LLM-only baseline evaluator
├── update_experiment/            # Schema-update robustness experiments
│   └── C01_... C12_...           # Add / delete / update scenarios
├── results.md                    # Published evaluation comparison
├── requirements.txt
└── README.md
```

---

## 🚀 Quick Start

### Prerequisites
- Python **3.8+**
- Node.js **18+** and npm
- One LLM API key (OpenAI-compatible, DeepSeek, or Qwen/DashScope)

### 1. Clone & install Python dependencies

```bash
cd DataMosaic
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure API keys

```bash
cp llm/.env.example llm/.env
# Edit llm/.env with your real keys, then:
```

`llm/.env` example:

```env
API_KEY=sk-...
API_URL=https://api.openai.com/v1
DEEPSEEK_KEY=...
DEEPSEEK_URL=https://api.deepseek.com
QWEN_KEY=...
QWEN_URL=https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
```

### 3. Start the backend

```bash
./scripts/start_backend.sh
# or manually:
#   cd backend && python app.py
```

The backend exposes:
- `http://localhost:5000` — REST API
- `ws://localhost:8765` — realtime signal stream

### 4. Start the frontend (in a second terminal)

```bash
./scripts/start_frontend.sh
# or manually:
#   cd frontend && npm install && npm start
```

Open <http://localhost:3000> in your browser.

---

## 🧪 Evaluation

### Full system evaluation

```bash
python test_dataset_evaluate.py --dataset FinanceDB --case case1 --model gpt-4o
```

Parameters:
| Flag | Description |
|---|---|
| `--dataset` | `FinanceDB`, `PaperDB`, `StudentDB`, or `LegalDB` |
| `--case` | Test case within the dataset (e.g. `case1`) |
| `--model` | LLM model identifier (e.g. `gpt-4o`, `claude-3-5-sonnet`, `qwen2.5-72b-instruct`) |
| `--run_name` | Custom output run identifier |

### LLM-only baseline

```bash
python llm_evaluate.py --dataset FinanceDB --case case1 --model gpt-4o
```

Metrics produced: **Precision / Recall / F1 / LLM-Score (0–100)**.
See `results.md` for a published comparison.

---

## 🔌 REST API (highlights)

| Endpoint | Purpose |
|---|---|
| `GET  /api/health` | Health check |
| `POST /api/upload/batch` | Upload one or more documents |
| `GET  /api/files` | List uploaded documents |
| `POST /api/doc2db/process` | Start an extraction job |
| `GET  /api/doc2db/stream/<task_id>` | Server-Sent Events progress stream |
| `GET  /api/doc2db/status/<task_id>` | Poll task status |
| `GET  /api/doc2db/history` | List historical runs |
| `GET  /api/memory/snapshots/<run_id>` | Inspect table snapshots |
| `GET  /api/memory/violations/<run_id>` | Inspect detected violations |
| `GET  /api/memory/fixes/<run_id>` | Inspect repair operations |
| `GET  /api/databases` / `POST .../tables` | SQLite database management |
| `GET  /api/settings` / `POST /api/settings` | Read / update active model and keys |

---

## 🧩 Architecture in One Picture

```
                ┌──────────────────────────────────────────────┐
   Documents ──▶│  Extractor (entities + relations)            │
                │  └─ LLM calls via llm.main.get_answer()      │
                └───────────┬──────────────────────────────────┘
                            ▼
                ┌──────────────────────────────────────────────┐
                │  Verifier (MCP plugins)                      │
                │  structure / type / value / logic / format / │
                │  temporal / reference / aggregation / DQ     │
                └───────────┬──────────────────────────────────┘
                            ▼ violations
                ┌──────────────────────────────────────────────┐
                │  Fixer  (targeted re-extraction / repair)    │
                └───────────┬──────────────────────────────────┘
                            ▼
                ┌──────────────────────────────────────────────┐
                │  Orchestrator (signal-driven closed loop)    │
                │  → memory snapshots → final DB instance      │
                └──────────────────────────────────────────────┘
```

The full pipeline is exposed both as a **service** (`modules.services.Doc2DBService`,
used by the Flask backend) and as an **importable Python library** (use the
modules directly without the HTTP layer).

---

## 📦 What is *not* included (by design)

To keep this repository clean and reproducible we exclude:

- `backend/history/`, `backend/output/`, `backend/uploads/`, `backend/logs/` — runtime artifacts
- `frontend/node_modules/`, `frontend/build/` — install / build outputs
- `llm/.env` — your private credentials (only `.env.example` is shipped)

These paths are pre-listed in `.gitignore`.

---

## 📜 License

Released under the project's open-source license. See `LICENSE` (if present)
for full terms.

## 🙏 Acknowledgements

DataMosaic uses [Material-UI](https://mui.com) for the frontend.
