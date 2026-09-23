"""Merge-import diffing: classify an incoming CSV against stored scores.

Records are matched by the ``(contestant, judge, item)`` triple — the same
natural key that the ``scores`` table enforces with its UNIQUE constraint.
Every record is classified into one of four buckets:

- ``added``:     the triple exists only in the incoming file (new record);
- ``unchanged``: the triple exists on both sides with the same score;
- ``changed``:   the triple exists on both sides but with different scores;
- ``removed``:   the triple exists only in the current session.

``changed`` and ``removed`` rows that carry an explicit adjudication are
flagged with ``decision_cleared`` so the caller can delete that adjudication
when applying the merge. ``unchanged`` rows keep their score, their
adjudication and the session's batch rules untouched.

The diff is a pure function over its inputs, therefore previews never touch
the database and cancelling a preview simply means discarding the result.
The incoming file is parsed by ``csv_io.parse_scores``, which already rejects
duplicate triples, so each triple appears at most once on either side.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

ADDED = "added"
UNCHANGED = "unchanged"
CHANGED = "changed"
REMOVED = "removed"

STATUSES = (ADDED, UNCHANGED, CHANGED, REMOVED)

STATUS_LABELS = {
    ADDED: "新增",
    UNCHANGED: "未变",
    CHANGED: "分数变更",
    REMOVED: "仅存在于当前会话",
}


def _triple(record: Mapping[str, Any]) -> tuple[str, str, str]:
    return record["contestant"], record["judge"], record["item"]


def build_merge_diff(
    existing: Sequence[Mapping[str, Any]],
    incoming: Sequence[Mapping[str, Any]],
    decisions: Mapping[int, tuple[bool, str]],
) -> dict[str, Any]:
    """Compare stored score records with parsed incoming CSV records.

    ``existing`` rows carry ``id``/``contestant``/``judge``/``item``/``score``
    (as returned by ``database.load_scores``); ``incoming`` rows carry the
    same fields except ``id`` (as returned by ``csv_io.parse_scores``).
    ``decisions`` maps score id to ``(use_raw, reason)``.

    Returns a counts dict plus per-row detail. Rows that appear in the
    incoming file are listed in incoming-file order (so the preview reads
    alongside the CSV); ``removed`` rows are appended last, in current
    session order.
    """
    existing_by_triple = {_triple(r): r for r in existing}

    counts = {
        ADDED: 0,
        UNCHANGED: 0,
        CHANGED: 0,
        REMOVED: 0,
        "decisions_cleared": 0,
    }
    rows: list[dict[str, Any]] = []

    for rec in incoming:
        triple = _triple(rec)
        old = existing_by_triple.get(triple)
        new_score = float(rec["score"])
        if old is None:
            status = ADDED
            score_id: int | None = None
            old_score: float | None = None
            has_decision = False
            decision_use_raw: bool | None = None
            decision_reason = ""
            decision_cleared = False
        else:
            score_id = old["id"]
            old_score = float(old["score"])
            verdict = decisions.get(score_id)
            if verdict is None:
                has_decision = False
                decision_use_raw = None
                decision_reason = ""
            else:
                has_decision = True
                decision_use_raw = bool(verdict[0])
                decision_reason = verdict[1] or ""
            status = CHANGED if new_score != old_score else UNCHANGED
            decision_cleared = status == CHANGED and has_decision

        counts[status] += 1
        if decision_cleared:
            counts["decisions_cleared"] += 1
        rows.append(
            {
                "status": status,
                "contestant": rec["contestant"],
                "judge": rec["judge"],
                "item": rec["item"],
                "score_id": score_id,
                "old_score": old_score,
                "new_score": new_score,
                "has_decision": has_decision,
                "decision_use_raw": decision_use_raw,
                "decision_reason": decision_reason,
                "decision_cleared": decision_cleared,
                "affected": status != UNCHANGED,
            }
        )

    incoming_triples = {_triple(r) for r in incoming}
    for old in existing:
        if _triple(old) in incoming_triples:
            continue
        score_id = old["id"]
        verdict = decisions.get(score_id)
        has_decision = verdict is not None
        decision_use_raw = bool(verdict[0]) if verdict else None
        decision_reason = (verdict[1] or "") if verdict else ""
        decision_cleared = has_decision
        counts[REMOVED] += 1
        if decision_cleared:
            counts["decisions_cleared"] += 1
        rows.append(
            {
                "status": REMOVED,
                "contestant": old["contestant"],
                "judge": old["judge"],
                "item": old["item"],
                "score_id": score_id,
                "old_score": float(old["score"]),
                "new_score": None,
                "has_decision": has_decision,
                "decision_use_raw": decision_use_raw,
                "decision_reason": decision_reason,
                "decision_cleared": decision_cleared,
                "affected": True,
            }
        )

    return {
        "counts": {
            **counts,
            "total_existing": len(existing),
            "total_incoming": len(incoming),
            "total_rows": len(rows),
        },
        "rows": rows,
    }
