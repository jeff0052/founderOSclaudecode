# FPMS — Focal Point Memory System

**The attention manager for AI agents.** FPMS gives your AI persistent memory, structured work tracking, and proactive risk alerts — so it never forgets what it's working on.

```bash
pip install fpms
```

## The Problem

AI agents forget everything between conversations. Even with 1M token context windows, they can't:

- Remember what they were working on yesterday
- Notice that a task has been stuck for 3 days
- Prioritize which information to load when context is limited
- Track projects across multiple conversations

Existing memory tools (Mem0, Zep) store conversation snippets. But **remembering what was said is not the same as managing what needs to be done.**

## What FPMS Does

FPMS is a **cognitive engine** that manages your AI's attention:

```
1. REMEMBER   — Persistent work items across conversations
2. FOCUS      — Token-budgeted context loading (only load what matters)
3. ALERT      — Proactive heartbeat: "Task X is blocked for 3 days"
4. STRUCTURE  — Projects → Milestones → Tasks with dependencies
```

## How It Compares

| Capability | Mem0 | Zep | Letta | OpenViking | **FPMS** |
|-----------|------|-----|-------|------------|----------|
| Conversation memory | Yes | Yes | Yes | Yes | Via prompt rules |
| Token budget management | No | No | Yes | Yes | **Yes (L0/L1/L2/L_Alert)** |
| Structured work items | No | No | No | No | **Yes** |
| Parent-child hierarchy | No | No | No | No | **Yes (unlimited depth)** |
| Task dependencies | No | No | No | No | **Yes** |
| Proactive risk alerts | No | No | No | No | **Yes (heartbeat)** |
| Anti-Amnesia | No | No | No | No | **Yes** |
| Status lifecycle | No | No | No | No | **Yes (inbox/active/waiting/done)** |
| Auto-archive | No | No | No | No | **Yes** |
| External sync (GitHub) | No | No | No | No | **Yes** |

**Other tools remember what was said. FPMS manages what needs to be done.**

## Who Is FPMS For?

### Solo founders & indie hackers
You juggle 10 projects across multiple AI conversations. FPMS keeps track so your AI always knows the full picture.

**Example:** You tell Claude "let's work on the auth system" — FPMS loads all related context: the task was created last week, you decided on JWT over sessions, there's a blocking dependency on the user model.

### AI agent builders
You're building autonomous agents that run for hours. Without FPMS, they lose track of priorities and forget completed work.

**Example:** Your agent runs a heartbeat scan every 10 minutes and discovers: "Task 'Deploy to staging' has been active for 2 days with no progress. 'Fix login bug' is blocked by 'Update user model' which is still in inbox."

### Teams using AI assistants
Multiple people interact with AI on the same project. FPMS provides a shared memory layer so the AI has continuity regardless of who's talking to it.

**Example:** Alice tells Claude to create a new API endpoint. Bob asks Claude about project status the next day — FPMS shows the endpoint task is active and 60% complete.

## Use Cases

### 1. Project Management with AI Memory
```
You: "Create a project for the Q2 product launch"
AI:  → create_node(title="Q2 Product Launch", node_type="project", is_root=True)

You: "Add tasks: redesign landing page, setup analytics, write launch email"
AI:  → creates 3 child task nodes under the project

(Next day, new conversation)
You: "What's the status of the launch?"
AI:  → bootstrap() loads context
     → "Q2 Product Launch: 3 tasks, 0 completed. 'Redesign landing page'
        has been in inbox for 2 days — should I activate it?"
```

### 2. Decision Tracking
```
You: "We're going with Stripe instead of PayPal for payments"
AI:  → append_log(node_id="payments-task", content="Decision: Stripe over PayPal.
       Reason: better API, lower fees for international transactions")

(Two weeks later)
You: "Why did we pick Stripe again?"
AI:  → get_node() → reads decision log
     → "You chose Stripe on March 15 because of better API and lower
        international fees"
```

### 3. Risk Detection
```
(Agent runs heartbeat automatically)
AI:  → heartbeat() detects:
     - "Deploy to prod" BLOCKED for 4 days (dependency on code review)
     - "Update docs" STALE — no activity for 7 days
     - "Fix memory leak" AT RISK — deadline is tomorrow, still active

AI:  → "I found 3 issues: a blocked deploy, stale docs, and an at-risk
        memory leak fix due tomorrow. Want me to help prioritize?"
```

### 4. GitHub Integration
```
Your GitHub issues automatically sync into FPMS:

  GitHub Issue #42 "Add dark mode"  →  FPMS node (synced)
  GitHub Issue #43 "Fix crash"      →  FPMS node (synced)

AI can now reason across your codebase AND your task list:
  "Issue #42 has been open for 2 weeks and assigned to you.
   The related PR was merged yesterday — should I close it?"
```

### 5. Cross-Conversation Continuity
```
Conversation 1 (Monday):
  You: "Start working on the API refactor"
  AI:  → creates node, status: active

Conversation 2 (Wednesday):
  You: "Continue where we left off"
  AI:  → bootstrap() → "You started the API refactor on Monday.
         Last log: refactored /users endpoint, /orders is next."

Conversation 3 (Friday):
  You: "How's the refactor going?"
  AI:  → heartbeat() → "API refactor is active, 2/5 endpoints done.
         At current pace, you'll finish next Wednesday."
```

## Quick Start

### Option 1: MCP Server (recommended)

Works with Claude Desktop, Claude Code, and OpenClaw.

```bash
pip install fpms
fpms  # starts MCP server on stdio
```

**Claude Desktop** (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "fpms": {
      "command": "fpms"
    }
  }
}
```

**OpenClaw** (`openclaw.yaml`):
```yaml
mcp_servers:
  fpms:
    command: fpms
```

### Option 2: Python API

```python
from fpms.spine import SpineEngine

engine = SpineEngine(db_path="./data/fpms.db")

# Cold start — load memory context
bundle = engine.bootstrap()

# Create and manage work items
engine.execute_tool("create_node", {
    "title": "Ship MVP", "node_type": "project", "is_root": True
})

# Proactive risk scan
alerts = engine.heartbeat()
```

## Architecture

```
AI Agent (Claude / GPT / OpenClaw)
    |
    v  MCP Tool Call (stdio)
+----------------------------------+
|  mcp_server.py                   |  18 MCP tools (FastMCP)
|    +------------------------+    |
|    |    SpineEngine         |    |  Core engine
|    |  +---------+--------+  |    |
|    |  | Tools   | Heart- |  |    |
|    |  | Execute | beat   |  |    |
|    |  | Store   | Bundle |  |    |
|    |  | Valid   | Risk   |  |    |
|    |  +---------+--------+  |    |
|    |  Adapters (GitHub...)  |    |
|    +------------------------+    |
+----------------------------------+
    |
    v
  SQLite + Narrative Markdown
```

**18 MCP Tools:** `create_node`, `update_status`, `update_field`, `attach_node`, `detach_node`, `add_dependency`, `remove_dependency`, `append_log`, `unarchive`, `set_persistent`, `shift_focus`, `expand_context`, `get_node`, `search_nodes`, `get_assembly_trace`, `heartbeat`, `bootstrap`, `get_context_bundle`

## Key Concepts

| Concept | Description |
|---------|-------------|
| **Node** | A work item (project, task, goal, milestone) with status lifecycle |
| **Heartbeat** | Periodic scan that detects blocked, stale, and at-risk nodes |
| **Context Bundle** | Token-budgeted payload (L0 dashboard + L1 neighborhood + L2 detail) |
| **Anti-Amnesia** | Mechanism that prevents AI from forgetting active work mid-conversation |
| **Rollup** | Child task completion automatically bubbles up to parent nodes |
| **Narrative** | Markdown log of decisions, events, and progress for each node |

## Requirements

- Python 3.10+
- No external services needed — runs 100% locally on SQLite

## License

[Business Source License 1.1](LICENSE) — Free to use, modify, and deploy. Cannot be used to build a competing commercial memory service. Converts to Apache 2.0 on 2030-03-22.

## Links

- [GitHub](https://github.com/jeff0052/founderOSclaudecode)
- [PyPI](https://pypi.org/project/fpms/)
- [ClawHub](https://clawhub.ai/skills/fpms-memory)
- [Usage Guide](docs/USAGE-GUIDE.md)
