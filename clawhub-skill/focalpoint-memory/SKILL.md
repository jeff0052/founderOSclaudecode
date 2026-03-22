---
name: focalpoint-memory
description: "FocalPoint — AI cognitive operating system. Memory + attention management + workflow orchestration. Workbench prepares context before tasks. Three-Province review ensures quality. Never lose track of projects again."
version: "0.3.1"
metadata:
  openclaw:
    emoji: "🧠"
    homepage: "https://github.com/jeff0052/founderOSclaudecode"
    requires:
      bins:
        - python3
    install:
      - kind: uv
        package: focalpoint
        bins: [focalpoint]
---

# FocalPoint — AI Cognitive Operating System

Your AI forgets everything between conversations. FocalPoint fixes that.

**Memory + Attention + Workflow.** FocalPoint tracks your projects, prepares context before tasks, and uses a Three-Province review system for quality decisions.

## What You Get

- **Cross-conversation memory** — Start Monday, continue Wednesday, review Friday
- **Workbench** — AI prepares goal, knowledge, context, and subtasks before starting work
- **Role-based thinking** — Strategy, Review, and Execution roles see different perspectives
- **Three-Province review** — Decisions go through parallel review before execution
- **Knowledge documents** — Attach design docs to nodes with parent inheritance
- **Full-text search** — Find anything across titles, narratives, and knowledge
- **Proactive alerts** — "Task X has been blocked for 3 days"
- **Smart context loading** — Role-filtered, token-budgeted context assembly
- **GitHub + Notion sync** — Issues and pages auto-sync as FocalPoint nodes

## How It's Different

| | Mem0/Zep | **FocalPoint** |
|--|---------|----------|
| Remembers conversations | Yes | Yes |
| Tracks tasks & projects | No | **Yes** |
| Prepares work context | No | **Yes (workbench)** |
| Role-based perspectives | No | **Yes (3 roles)** |
| Decision review workflow | No | **Yes (Three-Province)** |
| Knowledge doc inheritance | No | **Yes** |
| Full-text search | No | **Yes (FTS5)** |
| Alerts about stuck work | No | **Yes (heartbeat)** |
| Manages token budget | No | **Yes (L0/L1/L2)** |
| GitHub/Notion integration | No | **Yes** |

**Other tools remember what was said. FocalPoint manages what needs to be done.**

## Setup

### 1. Install
```bash
pip install focalpoint
```

### 2. Add MCP server to openclaw.yaml
```yaml
mcp_servers:
  fpms:
    command: focalpoint
```

### 3. Restart OpenClaw

That's it. 22 tools are now available in your conversations.

## Work Mode (v0.3)

### Workbench — prepare before you work
```
You: "Work on the payment system task"
AI calls activate_workbench(node_id, role="execution")
→ Gets: goal, knowledge docs, context bundle, sorted subtasks,
  suggested next step, and execution role prompt
→ AI enters role, reads background, starts working
```

### Three-Province Review — quality decisions
```
Strategy (中书省): "Should we do this? What's the priority?"
Review (门下省):   "Any risks? Historical lessons?"
Engineer (尚书省): "Is this feasible? How to implement?"

Both Review + Engineer must approve before execution.
Max 3 rejections, then escalate to human.
```

### Knowledge Documents — persistent design context
```
You: "Save this architecture doc to the project"
AI calls set_knowledge(project_id, "architecture", content)
→ Child tasks inherit parent knowledge automatically
→ Task reads project overview without you re-explaining
```

## Use Cases

### Project tracking
```
You: "Create a project for the product launch with 3 tasks"
(Next day)
You: "What's the launch status?"
AI:  "3 tasks: 1 done, 1 active, 1 blocked. The blocked task
      is waiting on design review — it's been 2 days."
```

### Decision memory with categories
```
You: "We're going with Stripe for payments"
AI:  append_log(node_id, "Chose Stripe — better API, lower fees", category="decision")
(Two weeks later)
You: "Why did we pick Stripe?"
AI:  Searches decisions → "You decided on March 15 — better API and lower international fees."
```

### Full-text search
```
You: "Find everything related to caching decisions"
AI:  search_nodes(query="caching decisions")
→ Finds nodes by title, narrative content, and knowledge docs
```

## Available Tools (21)

| Tool | What it does |
|------|-------------|
| `bootstrap` | Load memory context (call at conversation start) |
| `heartbeat` | Scan for risks: blocked, stale, at-risk tasks |
| `activate_workbench` | **Prepare working context with role + knowledge** |
| `set_knowledge` | **Attach knowledge documents to nodes** |
| `get_knowledge` | **Read knowledge with parent inheritance** |
| `delete_knowledge` | **Delete knowledge document from a node** |
| `sansei_review` | **Three-Province parallel review** |
| `create_node` | Create a project/task/goal |
| `update_status` | Change status (inbox/active/waiting/done/dropped) |
| `append_log` | Record decisions, progress, risks (with category) |
| `get_context_bundle` | Get role-filtered, token-budgeted context |
| `search_nodes` | Find tasks by filters or full-text search |
| `get_node` | Get full details of a work item |
| `shift_focus` | Switch AI attention to a specific task |
| `expand_context` | See parent, children, dependencies |
| `update_field` | Update title, summary, deadline, etc. |
| `attach_node` / `detach_node` | Move tasks in hierarchy |
| `add_dependency` / `remove_dependency` | Manage task dependencies |
| `unarchive` | Restore completed/dropped tasks |
| `set_persistent` | Protect tasks from auto-archive |
| `get_assembly_trace` | Debug context assembly |

## Automatic Memory Rules

Follow these rules in EVERY conversation:

1. **Conversation start** → Call `bootstrap` to load memory
2. **Before starting a task** → `activate_workbench` to prepare context
3. **User makes a decision** → `append_log` with category="decision"
4. **Risk identified** → `append_log` with category="risk"
5. **Task progresses** → `update_status`
6. **Design conclusions** → `set_knowledge` to persist for future sessions
7. **Before conversation ends** → `append_log` key takeaways
8. **Every ~10 min** → `heartbeat` to check for risks

## Requirements

- Python 3.10+
- No external services — runs 100% locally on SQLite

## Links

- [GitHub](https://github.com/jeff0052/founderOSclaudecode)
- [PyPI](https://pypi.org/project/focalpoint/)
