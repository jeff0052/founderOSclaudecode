# v1 Cognitive Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the cognitive layer — risk detection, status rollup, dashboard, heartbeat, focus management, context bundle assembly, archive scanning, and cold start recovery — so the engine can "think".

**Architecture:** 8 new modules in `fpms/spine/` building on v0's foundation (schema, models, store, validator, tools, narrative, command_executor). Risk marks are computed dynamically (never stored). Rollup is recursive bottom-up. Bundle assembles 4 layers (L0/L_Alert/L1/L2) with token budget trimming. All config values reference SYSTEM-CONFIG.md, never hardcoded. **compression.py is deferred to v2** per ARCHITECTURE.md §Implementation Priority — v1 bundle.py will load `compressed_summary` if it exists (written manually or by future v2), but no compression engine is built in v1.

**Tech Stack:** Python 3.9+, SQLite (WAL), pytest, pydantic (for inputs), dataclasses (internal)

**Source docs:**
- PRD: `V4/2-requirements/PRD-functional.md` (FR-3 through FR-13)
- PRD: `V4/2-requirements/PRD-context-lifecycle.md`
- Architecture: `V4/3-architecture/ARCHITECTURE.md`
- Config: `V4/SYSTEM-CONFIG.md`
- Dev guide: `V4/4-implementation/CLAUDE.md`

---

## File Structure

```
fpms/spine/
├── risk.py              # CREATE — Risk mark computation (blocked/at-risk/stale)
├── rollup.py            # CREATE — Recursive rollup_status bottom-up
├── dashboard.py         # CREATE — L0 global dashboard tree rendering
├── heartbeat.py         # CREATE — Heartbeat scan, alerts, Anti-Amnesia, dedup
├── focus.py             # CREATE — Focus scheduler, arbitration, stash, decay
├── bundle.py            # CREATE — Context bundle assembly (L0/L_Alert/L1/L2)
├── archive.py           # CREATE — Archive candidate scanning
├── recovery.py          # CREATE — Cold start bootstrap flow (FR-13)
├── __init__.py          # MODIFY — Wire new modules into SpineEngine
├── store.py             # MODIFY — Add get_children_all (include archived) for rollup
├── models.py            # MODIFY — Add RollupResult, HeartbeatResult, FocusState dataclasses

tests/
├── test_risk.py         # CREATE
├── test_rollup.py       # CREATE
├── test_dashboard.py    # CREATE
├── test_heartbeat.py    # CREATE
├── test_focus.py        # CREATE
├── test_bundle.py       # CREATE
├── test_archive.py      # CREATE
├── test_recovery.py     # CREATE
├── test_v1_e2e.py       # CREATE — End-to-end integration (5 scenarios)
```

## Execution Order (Dependency Graph)

```
Batch 1 (parallel, no dependencies):
  Task 1: risk.py + rollup.py
  Task 2: dashboard.py
  Task 3: focus.py
  Task 4: archive.py

Batch 2 (depends on Task 1):
  Task 5: heartbeat.py

Batch 3 (depends on Tasks 1-5):
  Task 6: bundle.py

Batch 4 (depends on Tasks 1-6):
  Task 7: recovery.py + SpineEngine wiring

Batch 5 (depends on all):
  Task 8: v1 integration verification
```

---

## Task 1: risk.py + rollup.py

**Files:**
- Create: `fpms/spine/risk.py`
- Create: `fpms/spine/rollup.py`
- Modify: `fpms/spine/models.py` (add RollupResult dataclass)
- Modify: `fpms/spine/store.py` (add `get_children_all` including archived)
- Test: `tests/test_risk.py`
- Test: `tests/test_rollup.py`

**Context needed:**
- PRD-functional §FR-5.2 (risk marks), §FR-5.3 (rollup)
- CLAUDE.md §Risk Marks, §Rollup
- SYSTEM-CONFIG.md §heartbeat.stale_threshold (72h), §interrupt

**Key behaviors:**
- Risk marks are pure functions: `compute_risk_marks(node, dependencies, now) -> set[str]`
- `blocked`: self not terminal AND any depends_on target status ≠ done (dropped does NOT unblock)
- `at-risk`: deadline < NOW()+48h AND not terminal
- `stale`: active/waiting AND status_changed_at < NOW()-7d (use SYSTEM-CONFIG threshold)
- Terminal nodes (done/dropped) NEVER get risk marks
- Rollup is recursive bottom-up: leaf status propagates up via parent edges
- Archived children MUST be included in rollup (denominator preservation)
- inbox children are EXCLUDED from rollup
- Rollup priority: active > waiting > (all terminal: any done → done, all dropped → dropped)

- [ ] **Step 1: Add models**

Add to `fpms/spine/models.py`:
```python
@dataclass
class RiskMarks:
    blocked: bool = False
    at_risk: bool = False
    stale: bool = False
    blocked_by: list[str] = field(default_factory=list)  # node_ids causing block
    deadline_hours: float | None = None  # hours until deadline (if at_risk)

@dataclass
class RollupResult:
    node_id: str
    rollup_status: str  # inbox|active|waiting|done|dropped
    has_risk_children: bool = False
    risk_summary: list[str] = field(default_factory=list)
```

- [ ] **Step 2: Add store.get_children_all**

Add to `fpms/spine/store.py`:
```python
def get_children_all(self, node_id: str) -> List[Node]:
    """获取全部子节点（含已归档），用于 rollup 计算。"""
    cols = self._node_columns()
    sql = "SELECT * FROM nodes WHERE parent_id=?"
    rows = self._conn.execute(sql, (node_id,)).fetchall()
    return [_row_to_node(r, cols) for r in rows]
```

- [ ] **Step 3: Write failing test for risk.py**

Create `tests/test_risk.py`:
```python
"""Risk mark computation tests (FR-5.2)."""
import pytest
from datetime import datetime, timezone, timedelta
from fpms.spine.models import Node
from fpms.spine import risk

class TestBlocked:
    def test_blocked_when_dependency_not_done(self, store_fixture):
        """Node with depends_on target status=active → blocked."""
    def test_not_blocked_when_dependency_done(self, store_fixture):
        """Node with depends_on target status=done → not blocked."""
    def test_not_blocked_when_dependency_dropped(self, store_fixture):
        """dropped does NOT unblock — blocked persists."""
    def test_terminal_node_never_blocked(self, store_fixture):
        """done/dropped nodes never get blocked mark."""
    def test_no_dependencies_not_blocked(self, store_fixture):
        """Node with no depends_on → not blocked."""

class TestAtRisk:
    def test_at_risk_within_48h(self):
        """deadline < NOW()+48h and not terminal → at_risk."""
    def test_not_at_risk_far_deadline(self):
        """deadline > NOW()+48h → not at_risk."""
    def test_not_at_risk_terminal(self):
        """done/dropped with close deadline → not at_risk."""
    def test_not_at_risk_no_deadline(self):
        """No deadline → not at_risk."""

class TestStale:
    def test_stale_after_threshold(self):
        """active node, status_changed_at > 7d ago → stale."""
    def test_not_stale_within_threshold(self):
        """active node, status_changed_at < 7d → not stale."""
    def test_not_stale_inbox(self):
        """inbox uses created_at, not status_changed_at (FR-7)."""
    def test_not_stale_terminal(self):
        """done/dropped → not stale."""
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest tests/test_risk.py -v`
Expected: ImportError or FAIL (risk module not implemented)

- [ ] **Step 5: Implement risk.py**

Create `fpms/spine/risk.py`:
```python
"""风险标记计算 — blocked/at-risk/stale，纯函数，不持久化。"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, List, Set
from .models import Node, RiskMarks

if TYPE_CHECKING:
    from .store import Store

# Thresholds from SYSTEM-CONFIG.md (loaded at module level)
# heartbeat.stale_threshold = 72 hours = 3 days (NOT 7 days — 7d is archive cooldown)
# interrupt.at_risk_deadline_hours = 48 hours
_STALE_THRESHOLD_HOURS = 72  # TODO: load from SYSTEM-CONFIG.md at init
_AT_RISK_THRESHOLD_HOURS = 48
_TERMINAL_STATES = {"done", "dropped"}


def compute_risk_marks(
    node: Node,
    store: "Store",
    now: datetime | None = None,
) -> RiskMarks:
    """Compute risk marks for a single node. Pure function of current state + clock."""
    if now is None:
        now = datetime.now(timezone.utc)

    marks = RiskMarks()

    # Terminal nodes never get risk marks
    if node.status in _TERMINAL_STATES:
        return marks

    # 1. blocked: any depends_on target not done
    deps = store.get_dependencies(node.id)
    blocked_by = [d.id for d in deps if d.status != "done"]
    if blocked_by:
        marks.blocked = True
        marks.blocked_by = blocked_by

    # 2. at-risk: deadline within threshold
    if node.deadline:
        try:
            dl = datetime.fromisoformat(node.deadline.replace("Z", "+00:00"))
            hours_left = (dl - now).total_seconds() / 3600
            if hours_left < _AT_RISK_THRESHOLD_HOURS:
                marks.at_risk = True
                marks.deadline_hours = hours_left
        except (ValueError, AttributeError):
            pass

    # 3. stale: no status change for threshold hours (SYSTEM-CONFIG: 72h)
    if node.status in ("active", "waiting") and node.status_changed_at:
        try:
            changed = datetime.fromisoformat(
                node.status_changed_at.replace("Z", "+00:00")
            )
            hours_since = (now - changed).total_seconds() / 3600
            if hours_since >= _STALE_THRESHOLD_HOURS:
                marks.stale = True
        except (ValueError, AttributeError):
            pass

    return marks


def compute_risk_marks_batch(
    nodes: List[Node],
    store: "Store",
    now: datetime | None = None,
) -> dict[str, RiskMarks]:
    """Compute risk marks for multiple nodes. Returns {node_id: RiskMarks}."""
    if now is None:
        now = datetime.now(timezone.utc)
    return {n.id: compute_risk_marks(n, store, now) for n in nodes}
```

- [ ] **Step 6: Run risk tests**

Run: `pytest tests/test_risk.py -v`
Expected: ALL PASSED

- [ ] **Step 7: Write failing test for rollup.py**

Create `tests/test_rollup.py`:
```python
"""Recursive rollup computation tests (FR-5.3)."""
import pytest
from fpms.spine import rollup

class TestRollupBasic:
    def test_leaf_node_returns_own_status(self, store_fixture):
        """No children → rollup = own status."""
    def test_active_child_propagates(self, store_fixture):
        """Any child active → parent rollup = active."""
    def test_waiting_child_propagates(self, store_fixture):
        """Any child waiting → parent rollup = waiting."""
    def test_all_done_propagates(self, store_fixture):
        """All children done → parent rollup = done."""
    def test_all_dropped_propagates(self, store_fixture):
        """All children dropped → parent rollup = dropped."""
    def test_mixed_terminal_with_done(self, store_fixture):
        """Mix of done+dropped, any done → rollup = done."""

class TestRollupInbox:
    def test_inbox_excluded_from_rollup(self, store_fixture):
        """Inbox children do not participate in rollup."""

class TestRollupArchived:
    def test_archived_children_included(self, store_fixture):
        """Archived children MUST be in rollup (denominator preservation)."""

class TestRollupRecursive:
    def test_three_level_rollup(self, store_fixture):
        """goal→project→task: task done → project rollup done → goal rollup done."""

class TestRollupRiskExposure:
    def test_risk_children_exposure(self, store_fixture):
        """Child with risk marks → parent has_risk_children=True."""
```

- [ ] **Step 8: Run test to verify it fails**

Run: `pytest tests/test_rollup.py -v`
Expected: FAIL

- [ ] **Step 9: Implement rollup.py**

Create `fpms/spine/rollup.py`:
```python
"""递归冒泡 — rollup_status 从叶子向上传播。"""
from __future__ import annotations
from typing import TYPE_CHECKING, Dict, List
from .models import Node, RollupResult, RiskMarks

if TYPE_CHECKING:
    from .store import Store

_TERMINAL_STATES = {"done", "dropped"}


def compute_rollup(
    node_id: str,
    store: "Store",
    risk_marks_map: dict[str, RiskMarks] | None = None,
    _cache: dict[str, RollupResult] | None = None,
) -> RollupResult:
    """Compute rollup_status for a node, recursing into children.

    Uses get_children_all (includes archived) per FR-5.3.
    Excludes inbox children from rollup per FR-7.
    """
    if _cache is None:
        _cache = {}
    if node_id in _cache:
        return _cache[node_id]

    node = store.get_node(node_id)
    if node is None:
        result = RollupResult(node_id=node_id, rollup_status="dropped")
        _cache[node_id] = result
        return result

    # Get ALL children including archived (denominator preservation)
    children = store.get_children_all(node_id)

    # Exclude inbox children
    eligible = [c for c in children if c.status != "inbox"]

    if not eligible:
        result = RollupResult(node_id=node_id, rollup_status=node.status)
        _cache[node_id] = result
        return result

    # Recurse into children
    child_rollups = []
    has_risk_children = False
    risk_summary = []
    for child in eligible:
        cr = compute_rollup(child.id, store, risk_marks_map, _cache)
        child_rollups.append(cr)
        if cr.has_risk_children:
            has_risk_children = True
            risk_summary.extend(cr.risk_summary)
        # Check direct child risk marks
        if risk_marks_map and child.id in risk_marks_map:
            child_risk = risk_marks_map[child.id]
            if child_risk.blocked or child_risk.at_risk or child_risk.stale:
                has_risk_children = True
                marks = []
                if child_risk.blocked:
                    marks.append("blocked")
                if child_risk.at_risk:
                    marks.append("at-risk")
                if child_risk.stale:
                    marks.append("stale")
                risk_summary.append(f"{child.id}: {','.join(marks)}")

    statuses = [cr.rollup_status for cr in child_rollups]

    # Priority rules (first match wins)
    if "active" in statuses:
        rollup_status = "active"
    elif "waiting" in statuses:
        rollup_status = "waiting"
    elif all(s in _TERMINAL_STATES for s in statuses):
        rollup_status = "done" if "done" in statuses else "dropped"
    else:
        rollup_status = node.status  # fallback

    result = RollupResult(
        node_id=node_id,
        rollup_status=rollup_status,
        has_risk_children=has_risk_children,
        risk_summary=risk_summary,
    )
    _cache[node_id] = result
    return result
```

- [ ] **Step 10: Run rollup tests**

Run: `pytest tests/test_rollup.py -v`
Expected: ALL PASSED

- [ ] **Step 11: Commit**

```bash
git add fpms/spine/risk.py fpms/spine/rollup.py fpms/spine/models.py fpms/spine/store.py tests/test_risk.py tests/test_rollup.py
git commit -m "feat(v1): risk mark computation + recursive rollup"
```

---

## Task 2: dashboard.py

**Files:**
- Create: `fpms/spine/dashboard.py`
- Test: `tests/test_dashboard.py`

**Context needed:**
- PRD-functional §FR-3 (global dashboard projection)
- CLAUDE.md §Context Bundle (L0)

**Key behaviors:**
- Tree rendering based on parent_id edges with indentation
- Zone 0 (top): inbox nodes with no parent
- Zone 1: active business forest (tree-indented)
- Each line: `[status_icon] {node_id}: {title} (risk_marks / deadline)`
- Token budget ~500-1k tokens
- Truncation: fold healthy branches, keep risk paths expanded
- Sorting: risk severity descending within each level

- [ ] **Step 1: Write failing test**

Create `tests/test_dashboard.py` covering: tree rendering, Zone 0/1 separation, risk sorting, token truncation, archived exclusion, large tree handling.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dashboard.py -v`

- [ ] **Step 3: Implement dashboard.py**

Create `fpms/spine/dashboard.py` with:
- `render_dashboard(store, risk_fn, max_tokens=1000) -> str`
- Zone 0: inbox nodes, max 5
- Zone 1: tree-walk from roots, indent by depth
- Sort siblings by risk severity
- Fold healthy branches when over budget

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_dashboard.py -v`
Expected: ALL PASSED

- [ ] **Step 5: Commit**

```bash
git add fpms/spine/dashboard.py tests/test_dashboard.py
git commit -m "feat(v1): L0 global dashboard tree rendering"
```

---

## Task 3: focus.py

**Files:**
- Create: `fpms/spine/focus.py`
- Modify: `fpms/spine/models.py` (add FocusState dataclass)
- Test: `tests/test_focus.py`

**Context needed:**
- PRD-functional §FR-9 (focus selection and scheduling)
- PRD-context-lifecycle §5 (focus switching)
- SYSTEM-CONFIG.md §focus (max 1 primary + 2 secondary, 24h stash decay)

**Key behaviors:**
- Focus state: primary (1) + secondary (max 2), stored in session_state
- `shift_focus(node_id)` → old primary goes to secondary (LRU eviction)
- Stash: interrupted focuses pushed LIFO, max 2, 24h decay
- Decay: focus untouched for 3 days → auto-demote
- No-focus mode: only L0 + L_Alert
- Priority: user-driven > event-driven > time-driven > historical

- [ ] **Step 1: Add FocusState model**

```python
@dataclass
class FocusState:
    primary: str | None = None
    secondary: list[str] = field(default_factory=list)
    stash: list[dict] = field(default_factory=list)  # [{node_id, stashed_at, reason}]
    last_touched: dict[str, str] = field(default_factory=dict)  # node_id → ISO timestamp
```

- [ ] **Step 2: Write failing test**

Create `tests/test_focus.py` covering: shift_focus, LRU eviction, stash push/pop, stash decay, 3-day untouched decay, no-focus mode, priority arbitration.

- [ ] **Step 3: Run test to verify it fails**

- [ ] **Step 4: Implement focus.py**

Create `fpms/spine/focus.py` with:
- `FocusScheduler.__init__(store)` — loads FocusState from `session_state['focus_list']` JSON. Validates each restored node_id exists and is not archived. Invalid nodes silently removed.
- `shift_focus(node_id) -> FocusState` — validates node exists + not archived, old primary→secondary (LRU evict if >2), persist to session_state
- `touch(node_id)` — resets decay timer in `last_touched`, persist
- `tick(now) -> FocusState` — check 3-day decay (remove untouched), check 24h stash expiry (write to narrative + remove), persist changes. **Must be called by bundle.assemble() before building L2.**
- `get_state() -> FocusState`
- `arbitrate(candidates, user_focus=None) -> FocusState` — priority: user_focus > candidates[0] > historical (from session_state). Validates all candidates, returns updated state, persists.
- `_persist()` — writes current FocusState to `store.set_session('focus_list', ...)`

- [ ] **Step 5: Run tests**

- [ ] **Step 6: Commit**

```bash
git add fpms/spine/focus.py fpms/spine/models.py tests/test_focus.py
git commit -m "feat(v1): focus scheduler with LRU, stash, and decay"
```

---

## Task 4: archive.py

**Files:**
- Create: `fpms/spine/archive.py`
- Test: `tests/test_archive.py`

**Context needed:**
- PRD-functional §FR-6 (topological safety archiving)
- SYSTEM-CONFIG.md §archive (7 day cooldown)
- CLAUDE.md §Archive

**Key behaviors:**
- Archive conditions (ALL must be true): terminal status + 7d cooldown + no active dependents + no active descendants
- `is_persistent=true` → exempt from archiving
- Bottom-up: children must be archived before parent
- `scan_archive_candidates(store, now) -> list[str]` — returns node_ids eligible
- `execute_archive(store, node_id)` — sets archived_at

- [ ] **Step 1: Write failing test**

Create `tests/test_archive.py` covering: eligible nodes, cooldown not met, active dependents block, active descendants block, persistent exempt, bottom-up order.

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement archive.py**

```python
def scan_archive_candidates(store, now=None) -> list[str]:
    """Find nodes eligible for archiving."""

def execute_archive(store, node_id) -> bool:
    """Archive a single node. Returns True if archived."""
```

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Commit**

```bash
git add fpms/spine/archive.py tests/test_archive.py
git commit -m "feat(v1): topological safety archive scanning"
```

---

## Task 5: heartbeat.py

**Files:**
- Create: `fpms/spine/heartbeat.py`
- Modify: `fpms/spine/models.py` (add HeartbeatResult dataclass)
- Test: `tests/test_heartbeat.py`

**Context needed:**
- PRD-functional §FR-8 (heartbeat protocol)
- SYSTEM-CONFIG.md §heartbeat (15min interval, 72h stale threshold)
- CLAUDE.md §Heartbeat

**Key behaviors:**
- Reuses risk.py for risk detection (DRY — no hardcoded thresholds)
- Alert types: urgent_deadline, critical_blocked, deadline_warning, stale_warning, inbox_stale
- Output: `HeartbeatResult` with alerts + focus_candidates
- Top 3 alerts max per heartbeat
- Dedup: same alert_type + node_id → suppress until state changes
- Anti-Amnesia: re-push after 24h if no substantive action
- `append_log` does NOT reset Anti-Amnesia timer
- Dedup state stored in session_state.last_alerts
- Inbox stale uses created_at (not status_changed_at, per FR-7)

- [ ] **Step 1: Add HeartbeatResult + DedupeRecord models**

```python
@dataclass
class HeartbeatAlert:
    alert_type: str  # urgent_deadline|critical_blocked|deadline_warning|stale_warning|inbox_stale
    severity: int  # 1=highest
    node_id: str
    message: str
    suggested_action: str

@dataclass
class DedupeRecord:
    """Anti-Amnesia dedup state per alert, stored in session_state.last_alerts."""
    alert_type: str
    node_id: str
    last_pushed_at: str  # ISO timestamp — when alert was last pushed to agent
    last_acted_at: str   # ISO timestamp — reset ONLY on substantive action (not append_log)

@dataclass
class HeartbeatResult:
    alerts: list[HeartbeatAlert] = field(default_factory=list)
    focus_candidates: list[str] = field(default_factory=list)
    archive_candidates: list[str] = field(default_factory=list)
    nodes_scanned: int = 0
```

- [ ] **Step 2: Write failing test**

Create `tests/test_heartbeat.py` covering: risk→alert mapping, Top 3 limit, dedup (same alert not re-pushed), Anti-Amnesia (re-push after 24h), append_log not resetting timer, inbox stale detection, focus candidate generation from high-priority alerts.

- [ ] **Step 3: Run test to verify it fails**

- [ ] **Step 4: Implement heartbeat.py**

Create `fpms/spine/heartbeat.py` with:
- `Heartbeat.__init__(store, risk_module, archive_module)`
- `scan(now=None) -> HeartbeatResult`
  - Step 1: Get all active/waiting/inbox nodes
  - Step 2: Compute risk marks via risk.py (DRY, no threshold duplication)
  - Step 3: Map risks to alerts (priority table from FR-8)
  - Step 4: Load dedup state from `session_state['last_alerts']` (list of DedupeRecord JSON)
  - Step 5: Dedup — for each alert, check if same (alert_type, node_id) exists in dedup:
    - If exists AND node had substantive action since last_pushed_at → reset, re-push
    - If exists AND no action AND < 24h since push → suppress (not re-pushed)
    - If exists AND no action AND >= 24h since push → **Anti-Amnesia forced re-push**
    - If not exists → new alert, push
  - Step 6: Generate focus candidates from high-priority alerts (severity 1-2)
  - Step 7: Scan archive candidates via `archive.scan_archive_candidates(store, now)`
  - Step 8: Update dedup state in session_state, return Top 3 alerts + candidates
- `_is_substantive_action(tool_name) -> bool` — ONLY: update_status, update_field, attach_node, detach_node, add_dependency, remove_dependency. **append_log is NOT substantive** (prevents "append garbage to bypass Anti-Amnesia")
- `_check_last_acted(node_id, since) -> bool` — queries audit_outbox for substantive tool calls on this node since given timestamp

- [ ] **Step 5: Run tests**

- [ ] **Step 6: Commit**

```bash
git add fpms/spine/heartbeat.py fpms/spine/models.py tests/test_heartbeat.py
git commit -m "feat(v1): heartbeat with Anti-Amnesia and alert dedup"
```

---

## Task 6: bundle.py

**Files:**
- Create: `fpms/spine/bundle.py`
- Test: `tests/test_bundle.py`

**Context needed:**
- PRD-functional §FR-10 (bundle assembly), §FR-4 (DCP)
- PRD-context-lifecycle §2 (context composition), §3 (lifecycle)
- SYSTEM-CONFIG.md §budget
- CLAUDE.md §Context Bundle

**Key behaviors:**
- Assembly order: L0 → L_Alert → L1 → L2
- L0: dashboard.py tree render (~500-1k tokens)
- L_Alert: heartbeat alerts (~500 tokens)
- L1: parent summary, children Top15, depends_on Top10, depended_by Top10, siblings Top10
- L2: focus node full skeleton + compressed_summary (if exists) + recent narrative (3 days or 5 entries)
- Token budget check + trim (iron law: causality > relationships)
- Trim order: siblings → children → depended_by → depends_on → parent → L2 content
- Assembly Trace logging to assembly_traces.jsonl
- No-focus mode: only L0 + L_Alert
- Token estimation: len(text) // 4 (rough heuristic)

- [ ] **Step 1: Write failing test**

Create `tests/test_bundle.py` covering: 4-layer assembly order, token budget trimming, trim priority order, assembly trace generation, no-focus mode (L0 + L_Alert only), empty DB (cold start) no crash, L1 Top15/Top10 limits, compressed summary priority over raw narrative.

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement bundle.py**

Create `fpms/spine/bundle.py` with:
- `BundleAssembler.__init__(store, dashboard_mod, heartbeat_mod, focus_mod, risk_mod, rollup_mod, narrative_mod)`
- `assemble(focus_node_id=None, now=None) -> ContextBundle`
  - **Before L2**: calls `focus_mod.tick(now)` to handle decay/stash expiry
  - Assembles L0 → L_Alert → L1 → L2 in order
- `_build_l0() -> str` — delegates to dashboard.render_dashboard()
- `_build_l_alert(heartbeat_result) -> str` — renders Top 3 alerts as markdown
- `_build_l1(focus_node_id) -> str` — **CRITICAL: Depth=1 only for children (FR-10 严禁跨代递归展开)**
  - parent: `store.get_parent(focus_node_id)` → summary
  - children: `store.get_children(focus_node_id)` → **direct children only**, sort by risk, Top 15, fold rest as count
  - depends_on: `store.get_dependencies(focus_node_id)` → Top 10
  - depended_by: `store.get_dependents(focus_node_id)` → Top 10
  - siblings: `store.get_siblings(focus_node_id)` → Top 10
- `_build_l2(focus_node_id) -> str` — full skeleton + compressed_summary (if exists, priority) + recent narrative (3 days or 5 entries)
- `_trim_to_budget(bundle, max_tokens) -> ContextBundle` — trim order: siblings → children → depended_by → depends_on → parent → L2 (last resort)
- `_write_assembly_trace(trace_data)` — append to assembly_traces.jsonl
- `_estimate_tokens(text) -> int` — uses SYSTEM-CONFIG coefficients: 1.3 tokens/word (EN), 2.0 tokens/char (ZH). Auto-detect based on Unicode ratio.

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Commit**

```bash
git add fpms/spine/bundle.py tests/test_bundle.py
git commit -m "feat(v1): context bundle assembly with 4-layer trim"
```

---

## Task 7: recovery.py + SpineEngine wiring

**Files:**
- Create: `fpms/spine/recovery.py`
- Modify: `fpms/spine/__init__.py` (wire all v1 modules)
- Test: `tests/test_recovery.py`

**Context needed:**
- PRD-functional §FR-13 (context recovery flow)
- CLAUDE.md §Cold Start

**Key behaviors:**
- Cold start sequence: Open SQLite → Generate L0 → Heartbeat scan → Focus arbitration → Bundle assembly → Push bootstrap context
- Graceful degradation: dashboard fails → rebuild from SQL; focus lost → no-focus mode; narrative corrupt → skip L2; SQLite corrupt → disaster recovery mode
- Bootstrap budget: ≤ typical bundle budget

- [ ] **Step 1: Write failing test**

Create `tests/test_recovery.py` covering: full bootstrap flow, focus restoration from session_state, degradation when focus invalid, empty DB bootstrap, recovery with pending alerts.

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement recovery.py**

```python
def bootstrap(store, heartbeat, focus_scheduler, bundle_assembler, archive_mod) -> ContextBundle:
    """Cold start recovery (FR-13). Returns initial context bundle.

    Sequence: SQLite → L0 → Heartbeat → Focus arbitration → Archive → Bundle → push
    Degradation: partial failure doesn't block bootstrap.
    """
    # Step 1: Already connected to SQLite (store initialized)

    # Step 2: Heartbeat scan (generates alerts + focus candidates)
    try:
        hb_result = heartbeat.scan()
    except Exception:
        hb_result = HeartbeatResult()  # degrade: no alerts

    # Step 3: Focus arbitration
    # FocusScheduler.__init__ already loaded historical focus from session_state.
    # arbitrate() merges historical focus (priority 4) with heartbeat candidates (priority 3).
    # Invalid/archived historical focuses were already cleaned in __init__.
    focus_state = focus_scheduler.arbitrate(
        candidates=hb_result.focus_candidates
    )
    # If no valid focus found → no-focus mode (only L0 + L_Alert)

    # Step 4: Execute archive for eligible candidates
    for nid in hb_result.archive_candidates:
        try:
            archive_mod.execute_archive(store, nid)
        except Exception:
            pass  # archive failure is non-blocking

    # Step 5: Bundle assembly
    bundle = bundle_assembler.assemble(
        focus_node_id=focus_state.primary
    )
    return bundle
```

- [ ] **Step 4: Wire SpineEngine**

Modify `fpms/spine/__init__.py` to:
- Import and initialize all v1 modules
- Replace v0 placeholder implementations with v1 modules
- `get_context_bundle()` → delegates to BundleAssembler
- `heartbeat()` → delegates to Heartbeat.scan()
- `bootstrap()` → delegates to recovery.bootstrap()

- [ ] **Step 5: Run tests**

- [ ] **Step 6: Commit**

```bash
git add fpms/spine/recovery.py fpms/spine/__init__.py tests/test_recovery.py
git commit -m "feat(v1): cold start recovery + SpineEngine v1 wiring"
```

---

## Task 8: v1 Integration Verification

**Files:**
- Create: `tests/test_v1_e2e.py`

**Scenarios:**

### Scenario 1: Cold start → bundle assembly
- [ ] Empty DB → bootstrap → returns valid ContextBundle with L0 only

### Scenario 2: Multi-level rollup
- [ ] Create goal→project→task tree → task done → project rollup=done → goal rollup=done

### Scenario 3: Heartbeat alerts
- [ ] Create stale node (7+ days) → heartbeat scan → stale alert generated → L_Alert contains it

### Scenario 4: Focus lifecycle
- [ ] shift_focus(A) → shift_focus(B) → A in secondary → decay A after 3 days → A removed

### Scenario 5: Archive lifecycle
- [ ] Node done for 7+ days, no dependents → archive scan → archived_at set → unarchive restores

### Full integration verification:

- [ ] **Step 1: Write e2e tests**
- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -v`
Expected: ALL PASSED (v0 + v1 tests)

- [ ] **Step 3: Run invariant tests specifically**

Run: `pytest tests/invariants/ -v`
Expected: ALL PASSED

- [ ] **Step 4: Commit**

```bash
git add tests/test_v1_e2e.py
git commit -m "test(v1): integration verification - 5 scenarios"
```

---

## v1 Acceptance Criteria

From PRD §Appendix 7 and TASK-DECOMPOSITION.md §T1.7:

### Cognitive Layer
- [ ] Risk marks computed dynamically (never stored)
- [ ] Rollup recursive bottom-up, includes archived children
- [ ] Dashboard tree rendering with risk sorting + truncation
- [ ] Heartbeat generates alerts from risk engine (DRY)
- [ ] Anti-Amnesia: re-push after 24h, append_log doesn't reset
- [ ] Alert dedup in session_state.last_alerts

### Focus & Bundle
- [ ] Focus arbitration: user > event > time > historical
- [ ] Focus decay: 3 days untouched → demote
- [ ] Stash: LIFO, max 2, 24h decay
- [ ] Bundle: L0 → L_Alert → L1 → L2 assembly order
- [ ] Token trim: causality > relationships
- [ ] Assembly trace logging

### Archive & Recovery
- [ ] Archive: terminal + 7d + no active deps + no active descendants
- [ ] Persistent nodes exempt
- [ ] Cold start: SQLite → L0 → Heartbeat → Focus → Bundle → push
- [ ] Degradation: partial failure doesn't block bootstrap

### Final
- [ ] `pytest tests/ -v` → ALL PASSED (v0 258 + v1 new tests)
- [ ] v1 acceptance checklist fully verified
