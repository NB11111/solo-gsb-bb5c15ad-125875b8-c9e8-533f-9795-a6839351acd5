"""Tests for merge-import diff classification."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.merge import (
    ADDED,
    CHANGED,
    REMOVED,
    UNCHANGED,
    build_merge_diff,
)


def rec(c, j, i, s, sid=None):
    row = {"contestant": c, "judge": j, "item": i, "score": s}
    if sid is not None:
        row["id"] = sid
    return row


class TestMergeDiff(unittest.TestCase):
    def setUp(self):
        self.existing = [
            rec("A", "J1", "P1", 8.0, sid=1),
            rec("A", "J2", "P1", 9.0, sid=2),
            rec("B", "J1", "P1", 7.0, sid=3),
        ]

    def test_classifies_all_four_buckets(self):
        incoming = [
            rec("A", "J1", "P1", 8.5),   # changed
            rec("A", "J2", "P1", 9.0),   # unchanged
            rec("C", "J1", "P1", 6.0),   # added
        ]
        diff = build_merge_diff(self.existing, incoming, {})
        c = diff["counts"]
        self.assertEqual(c[ADDED], 1)
        self.assertEqual(c[UNCHANGED], 1)
        self.assertEqual(c[CHANGED], 1)
        self.assertEqual(c[REMOVED], 1)
        self.assertEqual(c["total_existing"], 3)
        self.assertEqual(c["total_incoming"], 3)
        self.assertEqual(c["total_rows"], 4)

        by_triple = {(r["contestant"], r["judge"], r["item"]): r for r in diff["rows"]}
        changed = by_triple[("A", "J1", "P1")]
        self.assertEqual(changed["status"], CHANGED)
        self.assertEqual(changed["score_id"], 1)
        self.assertEqual(changed["old_score"], 8.0)
        self.assertEqual(changed["new_score"], 8.5)
        self.assertTrue(changed["affected"])

        same = by_triple[("A", "J2", "P1")]
        self.assertEqual(same["status"], UNCHANGED)
        self.assertEqual(same["score_id"], 2)
        self.assertFalse(same["affected"])
        self.assertFalse(same["decision_cleared"])

        added = by_triple[("C", "J1", "P1")]
        self.assertEqual(added["status"], ADDED)
        self.assertIsNone(added["score_id"])
        self.assertIsNone(added["old_score"])
        self.assertEqual(added["new_score"], 6.0)

        gone = by_triple[("B", "J1", "P1")]
        self.assertEqual(gone["status"], REMOVED)
        self.assertEqual(gone["score_id"], 3)
        self.assertEqual(gone["old_score"], 7.0)
        self.assertIsNone(gone["new_score"])

    def test_incoming_order_then_removed_last(self):
        incoming = [
            rec("C", "J1", "P1", 6.0),
            rec("A", "J1", "P1", 8.5),
            rec("A", "J2", "P1", 9.0),
        ]
        diff = build_merge_diff(self.existing, incoming, {})
        statuses = [(r["status"], r["contestant"]) for r in diff["rows"]]
        self.assertEqual(
            statuses,
            [(ADDED, "C"), (CHANGED, "A"), (UNCHANGED, "A"), (REMOVED, "B")],
        )

    def test_decision_flags_on_changed_and_removed(self):
        decisions = {
            1: (True, "人工保留"),   # changed score -> must be cleared
            2: (False, ""),         # unchanged score -> stays
            3: (True, "删除项裁决"),  # removed score -> must be cleared
        }
        incoming = [
            rec("A", "J1", "P1", 8.5),
            rec("A", "J2", "P1", 9.0),
        ]
        diff = build_merge_diff(self.existing, incoming, decisions)
        by_id = {r["score_id"]: r for r in diff["rows"]}
        self.assertTrue(by_id[1]["has_decision"])
        self.assertTrue(by_id[1]["decision_use_raw"])
        self.assertEqual(by_id[1]["decision_reason"], "人工保留")
        self.assertTrue(by_id[1]["decision_cleared"])

        self.assertTrue(by_id[2]["has_decision"])
        self.assertFalse(by_id[2]["decision_cleared"])

        self.assertTrue(by_id[3]["decision_cleared"])
        self.assertEqual(by_id[3]["decision_reason"], "删除项裁决")
        self.assertEqual(diff["counts"]["decisions_cleared"], 2)

    def test_changed_without_decision_is_not_counted(self):
        incoming = [
            rec("A", "J1", "P1", 8.5),
            rec("A", "J2", "P1", 9.0),
            rec("B", "J1", "P1", 7.0),
        ]
        diff = build_merge_diff(self.existing, incoming, {})
        self.assertEqual(diff["counts"][CHANGED], 1)
        self.assertEqual(diff["counts"]["decisions_cleared"], 0)
        changed = next(r for r in diff["rows"] if r["status"] == CHANGED)
        self.assertFalse(changed["has_decision"])
        self.assertFalse(changed["decision_cleared"])

    def test_everything_added_and_everything_removed(self):
        diff = build_merge_diff([], [rec("A", "J", "P", 1), rec("B", "J", "P", 2)], {})
        self.assertEqual(diff["counts"][ADDED], 2)
        self.assertEqual(diff["counts"]["total_rows"], 2)

        diff2 = build_merge_diff(self.existing, [], {})
        self.assertEqual(diff2["counts"][REMOVED], 3)
        self.assertEqual(diff2["counts"]["total_rows"], 3)

    def test_string_scores_parsed_to_float(self):
        diff = build_merge_diff(
            [rec("A", "J", "P", 8.0, sid=1)],
            [rec("A", "J", "P", "8.0")],
            {},
        )
        self.assertEqual(diff["rows"][0]["status"], UNCHANGED)
        self.assertEqual(diff["rows"][0]["new_score"], 8.0)


if __name__ == "__main__":
    unittest.main()
