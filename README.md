# 🤖 CrewAI + CockroachDB Joint PoC

> **From AI Demo → AI Business Process**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![CrewAI](https://img.shields.io/badge/CrewAI-1.14.7+-green.svg)](https://crewai.com)
[![CockroachDB](https://img.shields.io/badge/CockroachDB-Cloud-orange.svg)](https://cockroachlabs.com)

---

## The Story

Most companies experimenting with AI agents hit the same wall:

> The AI can reason. The AI can act.  
> But nobody knows **what it did**, **why it did it**, **whether it's reliable**, or **whether it can scale**.

**CrewAI** solves orchestration. **CockroachDB** solves operationalization.

Together they move customers from:

```
❌ AI Demo   →   ✅ AI Business Process
```

---

## The Executive Pitch

| Problem | Solution |
|---|---|
| AI can reason & act, but outputs vanish | CockroachDB persists every decision, reasoning chain, and output |
| No auditability or compliance trail | Every agent action is logged with timestamps and full context |
| AI agents can't collaborate at scale | Shared agent workspace in CockroachDB enables multi-agent coordination |
| Demo-grade infrastructure (Redis, SQLite) | Enterprise-grade: HA, replication, distributed, strongly consistent |
| No governance story for executives | Complete audit log: what, who, when, why — queryable forever |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     CrewAI Orchestration                     │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ Research     │  │ Risk         │  │ Recommendation   │  │
│  │ Agent        │→ │ Agent        │→ │ Agent            │  │
│  │              │  │              │  │                  │  │
│  │ Analyzes     │  │ Fraud Score  │  │ APPROVE/DENY/    │  │
│  │ claim docs   │  │ Risk flags   │  │ ESCALATE         │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└───────────────────────────┬─────────────────────────────────┘
                            │ Persist every step
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                       CockroachDB                            │
│                                                             │
│  agent_workflows   agent_actions   approval_queue           │
│  ─────────────     ─────────────   ──────────────           │
│  workflow_id       action_id       approval_id              │
│  status            agent_name      recommendation           │
│  input_data        output_data     reviewer                 │
│  started_at        task_name       status                   │
│                                    reviewed_at              │
│                                                             │
│  audit_log                                                  │
│  ─────────                                                  │
│  event_type  │  actor  │  timestamp  │  event_data (JSONB)  │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
                   👤 Human Reviewer
                   (Approves/Rejects)
```

---

## The 7 Sales Angles

### 1. 💾 Agent State Persistence
Without a database, agent outputs disappear. With CockroachDB, every agent run stores:
- Reasoning steps & decisions
- Task outputs
- Workflow status
- Exceptions & retries

**Outcome:** Traceability, auditability, compliance.

---

### 2. 👤 Human-in-the-Loop AI
Enterprises don't want `AI decides → AI executes`.  
They want `AI recommends → Human approves → AI executes`.

CockroachDB stores:
- Approval status
- Reviewer identity
- Timestamp
- Comments & version history

---

### 3. 🤝 Multi-Agent Collaboration
When Research Agent, Finance Agent, and Operations Agent need shared knowledge,  
CockroachDB becomes the **Shared Agent Workspace**:
- Agents write: `customer_profile`, `risk_scores`, `pricing_decisions`
- Other agents read it later
- Creates persistent, durable collaboration

---

### 4. 🏗️ Enterprise Reliability
Most AI demos store state in Redis, local files, or SQLite. That works for demos.  
CockroachDB offers:
- **High availability** — survives node failures
- **Replication** — data is never lost
- **Strong consistency** — no stale reads across agents
- **Fault tolerance** — agents don't lose memory when a server dies

---

### 5. 🌍 Global Agent Deployments
US agents + Europe agents + Asia agents all collaborating?  
CockroachDB provides:
- Distributed global database
- Single logical system
- Consistent state across regions

**Message:** *Run agents globally without building custom synchronization systems.*

---

### 6. 📋 AI Governance
Executives ask: *What did the AI do? Who approved it? What data did it use?*  
CockroachDB stores:
- Agent actions & task outputs
- Approvals with reviewer identity
- Full workflow transitions
- Immutable audit logs

**Key verticals:** Finance, Healthcare, Insurance, Government, Telecom

---

### 7. 🔄 AI Agents as Business Processes
Companies today run CRM, ERP, and ticketing workflows.  
Tomorrow they'll run **AI Workflows**.

| Role | Component |
|---|---|
| AI Workflow Engine | CrewAI |
| AI Workflow Database | CockroachDB |

---

## Industry Use Cases

### 🏦 Financial Services
| CrewAI | CockroachDB |
|---|---|
| Transaction research | Findings storage |
| Fraud detection | Decision records |
| Risk escalation | Approval workflows |
| | Full audit trail |

### 🏥 Insurance (This PoC)
| CrewAI | CockroachDB |
|---|---|
| Claims review agent | Policy history |
| Risk scoring agent | Claim records |
| Fraud detection agent | Approval workflows |
| | Agent decisions |

### 🎧 Customer Support
| CrewAI | CockroachDB |
|---|---|
| Ticket triage | Customer profile |
| Knowledge retrieval | Case history |
| Response drafting | Agent actions |
| | Resolution metrics |

---

## Partnership Positioning

> **CrewAI** gives organizations autonomous agents that can think and act.  
> **CockroachDB** gives those agents durable memory, shared state, governance, and enterprise-grade reliability.  
> Together they enable production-scale AI workflows that organizations can trust.

---

## Prerequisites

- Python 3.10+
- OpenAI Platform API Key → [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
- CockroachDB Cloud cluster → [cockroachlabs.cloud](https://cockroachlabs.cloud)
- `pip` package manager

> **Alternative LLM:** You can use Ollama locally instead of OpenAI — see [Ollama Setup](#ollama-local-setup) below.

---

## Setup & Installation

### Step 1: Clone the Repository

```bash
git clone https://github.com/murugaRocks/crewai-cockroachdb-poc.git
cd crewai-cockroachdb-poc
```

### Step 2: Create a Virtual Environment

```bash
python -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate          # Windows
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Configure Environment Variables

```bash
cp .env.example .env
nano .env  # or open with any editor
```

Fill in your credentials:

```env
OPENAI_API_KEY=sk-proj-your_openai_key_here
COCKROACHDB_URL=postgresql://username:password@your-cluster.cockroachdb.com:26257/defaultdb?sslmode=verify-full
```

### Step 5: Verify Environment

```bash
# Check OpenAI key is loaded
python -c "from dotenv import load_dotenv; load_dotenv(); import os; print(os.getenv('OPENAI_API_KEY')[:15])"

# Check CockroachDB connection
python -c "from database import get_connection; conn = get_connection(); print('✅ CockroachDB connected'); conn.close()"
```

### Step 6: Run the PoC

```bash
python main.py
```

---

## What to Expect

When you run `main.py`, you'll see:

```
============================================================
  CrewAI + CockroachDB Insurance Claims PoC
============================================================

📦 Connecting to CockroachDB...
✅ Database schema initialized successfully

🚀 Starting workflow for Claim: CLM-2024-00123
   Workflow ID: a1b2c3d4-...

🤖 Initializing CrewAI Agents...

🔄 Running CrewAI workflow...
[Research Agent]      → Analyzing claim documentation...
[Risk Agent]          → Evaluating fraud indicators...
[Recommendation Agent]→ Generating final recommendation...

💾 Persisting agent outputs to CockroachDB...

👤 Creating Human-in-the-Loop Approval Request...
   Approval Request ID: e5f6g7h8-...
   Status: PENDING HUMAN REVIEW

✅ Human approval recorded in CockroachDB

📋 Full Audit Trail (from CockroachDB):
------------------------------------------------------------
  [2024-01-15 10:00:01] WORKFLOW_STARTED       | Actor: system
  [2024-01-15 10:00:45] AGENT_ACTION_COMPLETED | Actor: system
  [2024-01-15 10:01:30] AGENT_ACTION_COMPLETED | Actor: system
  [2024-01-15 10:02:10] AGENT_ACTION_COMPLETED | Actor: system
  [2024-01-15 10:02:11] APPROVAL_REQUESTED     | Actor: system
  [2024-01-15 10:02:14] WORKFLOW_COMPLETED     | Actor: system

============================================================
  PoC Complete!
============================================================
```

---

## Ollama Local Setup

If you want to run without OpenAI API costs:

```bash
# Install Ollama
brew install ollama       # macOS

# Start Ollama
ollama serve

# Pull a model (in another terminal)
ollama pull llama3.1

# Update your .env
OPENAI_API_BASE=http://localhost:11434/v1
OPENAI_API_KEY=ollama
OPENAI_MODEL_NAME=llama3.1
```

---

## Project Structure

```
crewai-cockroachdb-poc/
├── README.md           # This file — story, setup, architecture
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variable template
├── .gitignore          # Git ignore rules
├── schema.sql          # CockroachDB schema (DDL)
├── main.py             # Entry point — orchestrates the full workflow
├── agents.py           # CrewAI agent definitions
├── tasks.py            # CrewAI task definitions
└── database.py         # CockroachDB connection & CRUD layer
```

---

## LLM Provider Options

| Provider | Setup Effort | Cost | Best For |
|---|---|---|---|
| OpenAI Platform | Low | Pay-per-use | Quick PoC |
| Azure OpenAI | Medium | Enterprise pricing | Enterprise demos |
| Ollama (local) | Low | Free | Internal demos |
| AWS Bedrock | Medium | Pay-per-use | AWS customers |
| Anthropic Claude | Low | Pay-per-use | Alternative to OpenAI |

---

## License

MIT — feel free to use this PoC as a foundation for customer demos and joint go-to-market activities.

---

*Built by [Muruga Balakrishnan](https://github.com/murugaRocks) — Sr. Partner Solutions Architect @ Cockroach Labs*
