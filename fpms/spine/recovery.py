"""冷启动恢复流程 (FR-13)。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .models import ContextBundle, HeartbeatResult

if TYPE_CHECKING:
    from .store import Store
    from .heartbeat import Heartbeat
    from .focus import FocusScheduler
    from .bundle import BundleAssembler


def bootstrap(
    store: "Store",
    heartbeat: "Heartbeat",
    focus_scheduler: "FocusScheduler",
    bundle_assembler: "BundleAssembler",
    archive_module=None,
) -> ContextBundle:
    """Cold start recovery (FR-13). Returns initial context bundle.

    Sequence: SQLite → Heartbeat → Focus arbitration → Archive → Bundle → push
    Degradation: partial failure doesn't block bootstrap.
    """
    # Step 1: SQLite already connected (store initialized)

    # Step 2: Heartbeat scan
    try:
        hb_result = heartbeat.scan()
    except Exception:
        hb_result = HeartbeatResult()

    # Step 3: Focus arbitration
    # FocusScheduler.__init__ already loaded historical focus from session_state
    # arbitrate() merges historical (priority 4) with heartbeat candidates (priority 3)
    focus_state = focus_scheduler.arbitrate(
        candidates=hb_result.focus_candidates
    )

    # Step 4: Archive eligible candidates
    if archive_module is not None:
        for nid in hb_result.archive_candidates:
            try:
                archive_module.execute_archive(store, nid)
            except Exception:
                pass  # non-blocking

    # Step 5: Bundle assembly
    bundle = bundle_assembler.assemble(
        focus_node_id=focus_state.primary
    )
    return bundle
