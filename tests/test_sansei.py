"""Tests for 三省 Protocol — parallel review with rejection loop."""

from __future__ import annotations
import pytest
from fpms.spine import SpineEngine


@pytest.fixture
def engine(tmp_path):
    return SpineEngine(
        db_path=str(tmp_path / "test.db"),
        events_path=str(tmp_path / "events.jsonl"),
        narratives_dir=str(tmp_path / "narratives"),
    )


def _create(engine, title, **kw):
    params = {"title": title, "is_root": True, **kw}
    return engine.execute_tool("create_node", params).data["id"]


class TestSanseiProtocol:

    def test_review_result_structure(self, engine):
        nid = _create(engine, "Feature X", summary="New feature")
        engine.execute_tool("update_status", {"node_id": nid, "new_status": "active"})
        result = engine.sansei_review(nid, proposal="Build payment system")
        assert "review_verdict" in result
        assert "engineer_verdict" in result
        assert "approved" in result
        assert "rejection_count" in result

    def test_both_approve_means_approved(self, engine):
        nid = _create(engine, "Simple", summary="Easy")
        engine.execute_tool("update_status", {"node_id": nid, "new_status": "active"})
        result = engine.sansei_review(nid, proposal="Add a button",
            review_verdict={"approved": True, "reason": "No risk"},
            engineer_verdict={"approved": True, "reason": "Feasible"})
        assert result["approved"] is True

    def test_review_rejects_means_not_approved(self, engine):
        nid = _create(engine, "Risky", summary="Risky")
        engine.execute_tool("update_status", {"node_id": nid, "new_status": "active"})
        result = engine.sansei_review(nid, proposal="Delete all data",
            review_verdict={"approved": False, "reason": "Too risky"},
            engineer_verdict={"approved": True, "reason": "Feasible"})
        assert result["approved"] is False

    def test_engineer_rejects_means_not_approved(self, engine):
        nid = _create(engine, "Impossible", summary="Hard")
        engine.execute_tool("update_status", {"node_id": nid, "new_status": "active"})
        result = engine.sansei_review(nid, proposal="Rewrite in Haskell",
            review_verdict={"approved": True, "reason": "No risk"},
            engineer_verdict={"approved": False, "reason": "Not feasible"})
        assert result["approved"] is False

    def test_rejection_count_tracked(self, engine):
        nid = _create(engine, "Iterating", summary="Will iterate")
        engine.execute_tool("update_status", {"node_id": nid, "new_status": "active"})
        r1 = engine.sansei_review(nid, proposal="v1",
            review_verdict={"approved": False, "reason": "Needs work"},
            engineer_verdict={"approved": True, "reason": "OK"})
        assert r1["rejection_count"] == 1
        r2 = engine.sansei_review(nid, proposal="v2",
            review_verdict={"approved": False, "reason": "Still bad"},
            engineer_verdict={"approved": True, "reason": "OK"})
        assert r2["rejection_count"] == 2

    def test_max_3_rejections_escalates(self, engine):
        nid = _create(engine, "Stuck", summary="Stuck")
        engine.execute_tool("update_status", {"node_id": nid, "new_status": "active"})
        for i in range(3):
            engine.sansei_review(nid, proposal=f"attempt {i+1}",
                review_verdict={"approved": False, "reason": f"Nope {i+1}"},
                engineer_verdict={"approved": True, "reason": "OK"})
        r4 = engine.sansei_review(nid, proposal="attempt 4",
            review_verdict={"approved": False, "reason": "Nope 4"},
            engineer_verdict={"approved": True, "reason": "OK"})
        assert r4["escalate_to_human"] is True

    def test_rejection_reason_logged_to_narrative(self, engine):
        nid = _create(engine, "Logged", summary="With logs")
        engine.execute_tool("update_status", {"node_id": nid, "new_status": "active"})
        engine.sansei_review(nid, proposal="Bad idea",
            review_verdict={"approved": False, "reason": "Historical lesson: failed before"},
            engineer_verdict={"approved": True, "reason": "OK"})
        from fpms.spine import narrative as narr
        text = narr.read_narrative(engine._narratives_dir, nid)
        assert "Historical lesson" in text

    def test_approval_logged_to_narrative(self, engine):
        nid = _create(engine, "Approved", summary="Good")
        engine.execute_tool("update_status", {"node_id": nid, "new_status": "active"})
        engine.sansei_review(nid, proposal="Build payment",
            review_verdict={"approved": True, "reason": "OK"},
            engineer_verdict={"approved": True, "reason": "OK"})
        from fpms.spine import narrative as narr
        text = narr.read_narrative(engine._narratives_dir, nid)
        assert "三省审查通过" in text

    def test_invalid_node_raises(self, engine):
        with pytest.raises(ValueError, match="not found"):
            engine.sansei_review("nonexistent-9999", proposal="test")
