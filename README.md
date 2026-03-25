# FocalPoint — AI Cognitive Operating System

**Memory + Attention Management + Workflow Orchestration.** FocalPoint gives your AI persistent memory, a workbench for task preparation, role-based thinking, and proactive risk alerts.

```bash
pip install focalpoint
```

## The Problem

AI agents forget everything between conversations. Existing memory tools (Mem0, Zep) store conversation snippets. But **remembering what was said is not the same as managing what needs to be done.**

## What FocalPoint Does

```
1. REMEMBER    — Structured memory across conversations (not just chat history)
2. PREPARE     — Workbench loads goal, knowledge, context, and subtasks before work
3. THINK       — Three roles (Strategy/Review/Execution) see different perspectives
4. REVIEW      — Three-Province protocol: parallel review before major decisions
5. ALERT       — Proactive heartbeat: "Task X is blocked for 3 days"
6. SEARCH      — Full-text search across titles, narratives, and knowledge docs
7. SYNC        — Bidirectional GitHub + Notion integration
```

## How It Compares

| Capability | Mem0 | Zep | Letta | CrewAI | Claude | **FocalPoint** |
|---|---|---|---|---|---|---|
| Persistent memory | Yes | Yes | Yes | Yes | Yes | **Yes** |
| Task lifecycle management | - | - | - | Partial | - | **Yes** |
| Dependency graph (DAG) | - | - | - | - | - | **Yes** |
| Proactive alerts | - | - | - | - | - | **Yes** |
| Knowledge docs + inheritance | - | - | - | - | Partial | **Yes** |
| Role-based context | - | - | - | Partial | - | **Yes** |
| Decision review workflow | - | - | - | - | - | **Yes** |
| Full-text search | Vector | Vector | Vector | - | - | **FTS5** |
| MCP native | - | - | - | - | Proprietary | **Yes** |
| Zero external deps | Partial | Partial | Yes | Yes | - | **Yes (SQLite only)** |

## Quick Start

### MCP Server (recommended)

```bash
pip install focalpoint
```

**Claude Desktop** (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "fpms": {
      "command": "focalpoint"
    }
  }
}
```

**OpenClaw**: Search `focalpoint-memory` in ClawHub and install.

23 tools are now available. Start a conversation and say `bootstrap`.

### Python API

```python
from fpms.spine import SpineEngine

engine = SpineEngine(db_path="./data/fpms.db")

# Cold start
bundle = engine.bootstrap()

# Create work items
engine.execute_tool("create_node", {
    "title": "Ship MVP", "node_type": "project", "is_root": True
})

# Prepare work context
workbench = engine.activate_workbench(node_id, role="execution")
# Returns: goal, knowledge, context, subtasks, suggested_next, role_prompt

# Proactive risk scan
alerts = engine.heartbeat()
```

## Analytics Dashboard

Monitor your FocalPoint usage with a visual HTML dashboard:

```bash
focalpoint-stats --html
```

This generates a dashboard in your browser showing:
- **Health Score** (0-100) across 5 dimensions
- Node status distribution, tool usage, token efficiency
- **Node Browser** — click any node to view its narrative history and knowledge docs

Other output formats:
```bash
focalpoint-stats          # Text report in terminal
focalpoint-stats --json   # Raw JSON for scripts
```

Or ask your AI in Claude Desktop: **"调用 get_stats"**

## Work Mode

### Workbench — prepare before you work

```
You: "Work on the payment system task"
AI calls activate_workbench(node_id, role="execution")
-> Gets: goal, knowledge docs, context bundle, sorted subtasks,
   suggested next step, and execution role prompt
-> AI enters role, reads background, starts working
```

### Three Roles

| Role | Focus | Sees |
|------|-------|------|
| **Strategy** | Should we do this? Priority? | Decisions + feedback |
| **Review** | Any risks? Historical lessons? | Risk notes + progress |
| **Execution** | How to build it? | Technical details + progress |

### Three-Province Review

For major decisions: Strategy produces requirements -> Review + Engineer review in parallel -> Both approve or reject -> Max 3 rejections then escalate to human.

### Knowledge Documents

Attach design docs to nodes. Child tasks inherit parent knowledge automatically.

```
project "Payment System"
|-- overview.md        <- Project background
|-- architecture.md    <- Design docs
|
\-- task "Implement API"
    -> Inherits overview + architecture automatically
```

## Available Tools (23)

| Category | Tools |
|----------|-------|
| **Write (11)** | create_node, update_status, update_field, attach/detach_node, add/remove_dependency, append_log, unarchive, set_persistent, set_knowledge |
| **Read (5)** | get_node, search_nodes, get_knowledge, delete_knowledge, get_assembly_trace |
| **Cognitive (4)** | bootstrap, heartbeat, activate_workbench, get_context_bundle |
| **Review (1)** | sansei_review |
| **Runtime (1)** | shift_focus |

## Architecture

```
Brain (LLM)              Spine (FocalPoint engine)
  |                         |
  | -- Tool Call -->        | Validate -> Write SQLite -> Narrative -> Audit
  |                         |
  | <-- Context ---         | Assemble L0/L1/L2 -> Trim -> Inject prompt
```

**Brain** = LLM. Only reads context and issues Tool Calls.
**Spine** = Deterministic engine. All logic here. LLM never touches storage directly.

Storage: Pure SQLite. No vector DB, no Redis, no PostgreSQL.

## Stats

| Metric | Value |
|--------|-------|
| Tests | 667 |
| MCP Tools | 23 |
| External dependencies | 0 |
| Cold start | < 100ms |
| Supported LLMs | Any (via MCP) |

## Requirements

- Python 3.10+
- No external services — runs 100% locally on SQLite

## License

[Business Source License 1.1](LICENSE) — Free to use, modify, and deploy. Cannot be used to build a competing commercial memory service. Converts to Apache 2.0 on 2030-03-22.

## Links

- [PyPI](https://pypi.org/project/focalpoint/)
- [ClawHub](https://lobehub.com/skills/openclaw-skills-focalpoint-memory)
- [Product Introduction](docs/marketing/PRODUCT-INTRO.md)
- [Usage Guide](docs/marketing/USAGE-GUIDE.md)
- [Work Mode Guide](docs/WORK-MODE-GUIDE.md)
