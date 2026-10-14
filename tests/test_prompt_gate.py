import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "system"))

import prompt_gate as pg  # noqa: E402

RUBRIC = pg.load_rubric(ROOT / "config" / "prompt-rubric.json")
DIM_IDS = [d["id"] for d in RUBRIC["dimensions"]]

PROMPT = """# Task: summarize a repository's test suite

## Objective
Produce a one-page summary of every test file in the repository.

## Definition of done
Every file under tests/ appears exactly once with its pass/fail status.

## Failure and stop path
If the test runner is missing, stop and report the missing tool by name.

## Evidence
Attach the raw runner output and the command that produced it.

## Assumptions
ASSUMED: the runner is pytest. Verify before running.
"""


def scorecard(text=PROMPT, scores=None, **overrides):
    values = scores or [9.6] * len(DIM_IDS)
    card = {
        "rubric_version": RUBRIC["version"],
        "content_sha256": pg.sha256_text(text),
        "drafter_context_id": "draft-ctx-1",
        "scorer_context_id": "score-ctx-1",
        "scores": {
            dim: {"score": value, "justification": "meets anchor", "evidence": "line 4"}
            for dim, value in zip(DIM_IDS, values)
        },
    }
    card.update(overrides)
    return card


def signed_rubric():
    rubric = copy.deepcopy(RUBRIC)
    rubric["status"] = "signed_off"
    return rubric


class RubricTests(unittest.TestCase):
    def test_shipped_rubric_is_pending_signoff_and_weights_sum_to_one(self):
        self.assertEqual(RUBRIC["status"], "pending_signoff")
        self.assertEqual(sum(d["weight_hundredths"] for d in RUBRIC["dimensions"]), 100)

    def test_bad_weights_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = copy.deepcopy(RUBRIC)
            bad["dimensions"][0]["weight_hundredths"] += 1
            path = Path(tmp) / "r.json"
            path.write_text(json.dumps(bad))
            with self.assertRaises(pg.GateError):
                pg.load_rubric(path)


    def write(self, tmp, rubric):
        path = Path(tmp) / "r.json"
        path.write_text(json.dumps(rubric))
        return path

    def test_gates_are_data_driven(self):
        rubric = copy.deepcopy(RUBRIC)
        rubric["gates"].append({"id": "G6", "label": "rollback stated", "required_heading": "rollback"})
        with tempfile.TemporaryDirectory() as tmp:
            loaded = pg.load_rubric(self.write(tmp, rubric))
        self.assertEqual([g["id"] for g in pg.lint_gates(PROMPT, loaded) if not g["passed"]], ["G6"])

    def test_gate_without_a_check_is_rejected(self):
        for bad in (
            {"id": "G6", "label": "no check"},
            {"id": "G6", "label": "typo", "required_headng": "rollback"},
            {"id": "G6", "label": "empty", "required_heading": " "},
            {"id": "G6", "label": "empty", "forbidden_phrases": []},
        ):
            rubric = copy.deepcopy(RUBRIC)
            rubric["gates"].append(bad)
            with tempfile.TemporaryDirectory() as tmp, self.assertRaises(pg.GateError, msg=bad):
                pg.load_rubric(self.write(tmp, rubric))


class GateLintTests(unittest.TestCase):
    def test_complete_prompt_passes_all_gates(self):
        self.assertTrue(all(g["passed"] for g in pg.lint_gates(PROMPT, RUBRIC)))

    def test_missing_heading_fails(self):
        text = PROMPT.replace("## Assumptions", "## Notes")
        failed = [g["id"] for g in pg.lint_gates(text, RUBRIC) if not g["passed"]]
        self.assertEqual(failed, ["G4"])

    def test_empty_section_fails(self):
        text = PROMPT.replace("Attach the raw runner output and the command that produced it.", "")
        failed = [g["id"] for g in pg.lint_gates(text, RUBRIC) if not g["passed"]]
        self.assertEqual(failed, ["G3"])

    def test_heading_inside_code_fence_does_not_count(self):
        text = PROMPT.replace("## Assumptions\n", "```\n## Assumptions\n```\n")
        self.assertIn("G4", [g["id"] for g in pg.lint_gates(text, RUBRIC) if not g["passed"]])

    def test_context_reference_fails_self_containment(self):
        text = PROMPT + "\nUse the format as discussed.\n"
        failed = [g["id"] for g in pg.lint_gates(text, RUBRIC) if not g["passed"]]
        self.assertEqual(failed, ["G5"])


class GateVocabularyTests(unittest.TestCase):
    """Pins a known property: G1-G4 are a heading schema, not a substance check."""

    OUTSIDER = PROMPT.replace("## Definition of done", "## Success criteria") \
        .replace("## Failure and stop path", "## If things go wrong") \
        .replace("## Evidence", "## Proof required") \
        .replace("## Assumptions", "## What we're taking for granted")

    def test_same_substance_other_vocabulary_is_vetoed(self):
        failed = [g["id"] for g in pg.lint_gates(self.OUTSIDER, RUBRIC) if not g["passed"]]
        self.assertEqual(failed, ["G1", "G2", "G3", "G4"])

    def test_vague_bodies_under_house_headings_pass_gates(self):
        vague = "\n".join(
            f"## {h}\nTBD, use judgment." for h in
            ("Objective", "Definition of done", "Failure and stop", "Evidence", "Assumptions")
        )
        self.assertTrue(all(g["passed"] for g in pg.lint_gates(vague, RUBRIC)))


class EvaluateTests(unittest.TestCase):
    def test_pass(self):
        verdict = pg.evaluate(PROMPT, scorecard(), RUBRIC)
        self.assertEqual(verdict["status"], pg.PASS, verdict)
        self.assertEqual(verdict["weighted"], 9.6)

    def test_exact_bar_passes_where_float_math_would_block(self):
        scores = [9.2, 9.5, 9.4, 9.5, 9.2, 9.6, 10.0, 9.8, 9.3, 9.9]
        floaty = 0.0
        for value, dim in zip(scores, RUBRIC["dimensions"]):
            floaty += value * (dim["weight_hundredths"] / 100)
        self.assertLess(floaty, 9.5)  # the defect this module exists to avoid
        verdict = pg.evaluate(PROMPT, scorecard(scores=scores), RUBRIC)
        self.assertEqual(verdict["status"], pg.PASS, verdict)
        self.assertEqual(verdict["weighted"], 9.5)

    def test_exact_bar_is_order_invariant(self):
        # Float summation of this case flips sign with dimension order; integer math must not.
        scores = dict(zip(DIM_IDS, [9.2, 9.5, 9.4, 9.5, 9.2, 9.6, 10.0, 9.8, 9.3, 9.9]))
        weight = {d["id"]: d["weight_hundredths"] for d in RUBRIC["dimensions"]}
        orders = {
            "shipped": list(DIM_IDS),
            "reversed": list(reversed(DIM_IDS)),
            "weight_desc": sorted(DIM_IDS, key=lambda d: -weight[d]),
            "weight_asc": sorted(DIM_IDS, key=lambda d: weight[d]),
            "alphabetical": sorted(DIM_IDS),
        }
        float_signs = set()
        for name, order in orders.items():
            floaty = 0.0
            for dim in order:
                floaty += scores[dim] * (weight[dim] / 100)
            float_signs.add(floaty >= 9.5)
            rubric = copy.deepcopy(RUBRIC)
            rubric["dimensions"] = [next(d for d in RUBRIC["dimensions"] if d["id"] == i) for i in order]
            card = scorecard(scores=[scores[d] for d in DIM_IDS])
            verdict = pg.evaluate(PROMPT, card, rubric)
            self.assertEqual((name, verdict["status"], verdict["weighted"]), (name, pg.PASS, 9.5))
        self.assertEqual(float_signs, {True, False})  # the hazard is real in float, absent here

    def test_floor_breach_blocks_high_average(self):
        scores = [10.0] * len(DIM_IDS)
        scores[DIM_IDS.index("token_economy")] = 8.9
        verdict = pg.evaluate(PROMPT, scorecard(scores=scores), RUBRIC)
        self.assertEqual(verdict["status"], pg.BLOCK_FLOOR)
        self.assertGreaterEqual(verdict["weighted"], 9.5)

    def test_gate_veto_ignores_perfect_score(self):
        text = PROMPT.replace("## Definition of done", "## Goal")
        verdict = pg.evaluate(text, scorecard(text=text, scores=[10.0] * len(DIM_IDS)), RUBRIC)
        self.assertEqual(verdict["status"], pg.BLOCK_GATE)

    def test_below_bar_names_weakest_three(self):
        scores = [9.3] * len(DIM_IDS)
        scores[0], scores[1], scores[2] = 9.0, 9.1, 9.2
        verdict = pg.evaluate(PROMPT, scorecard(scores=scores), RUBRIC)
        self.assertEqual(verdict["status"], pg.REVISE)
        self.assertEqual([w["id"] for w in verdict["weakest"]], DIM_IDS[:3])

    def test_unevidenced_ten_is_capped(self):
        card = scorecard(scores=[10.0] * len(DIM_IDS))
        card["scores"]["idempotence"]["evidence"] = ""
        verdict = pg.evaluate(PROMPT, card, RUBRIC)
        self.assertEqual(verdict["status"], pg.PASS)
        self.assertTrue(any("idempotence: 10.0 capped to 9.8" in n for n in verdict["notes"]))
        self.assertEqual(verdict["weighted"], 9.988)

    def test_cap_boundary(self):
        for raw, evidence, expected in ((9.9, "", 9.8), (9.8, "", 9.8), (9.9, "line 3", 9.9)):
            card = scorecard()
            card["scores"]["idempotence"].update(score=raw, evidence=evidence)
            verdict = pg.evaluate(PROMPT, card, RUBRIC)
            got = (96 * 94 + int(round(expected * 10)) * 6) / 1000
            self.assertEqual(verdict["weighted"], got, (raw, evidence))

    def test_self_scoring_is_invalid(self):
        card = scorecard(scorer_context_id="draft-ctx-1")
        self.assertEqual(pg.evaluate(PROMPT, card, RUBRIC)["status"], pg.INVALID)

    def test_scorecard_for_other_text_is_invalid(self):
        card = scorecard(text=PROMPT + " ")
        self.assertEqual(pg.evaluate(PROMPT, card, RUBRIC)["status"], pg.INVALID)

    def test_stale_rubric_version_is_invalid(self):
        card = scorecard(rubric_version="0.0.1")
        self.assertEqual(pg.evaluate(PROMPT, card, RUBRIC)["status"], pg.INVALID)

    def test_malformed_scores_are_invalid(self):
        for mutate in (
            lambda c: c["scores"].pop("idempotence"),
            lambda c: c["scores"]["idempotence"].update(score=9.55),
            lambda c: c["scores"]["idempotence"].update(score=True),
            lambda c: c["scores"]["idempotence"].update(justification=" "),
            lambda c: c["scores"].update(idempotence=9.6),
        ):
            card = scorecard()
            mutate(card)
            self.assertEqual(pg.evaluate(PROMPT, card, RUBRIC)["status"], pg.INVALID, card)


class GuardTests(unittest.TestCase):
    def history(self, *strategies, last=pg.REVISE):
        return [{"status": last, "strategy": s} for s in strategies]

    def test_sequence(self):
        nxt = lambda h: pg.next_action(h, RUBRIC)["action"]  # noqa: E731
        self.assertEqual(nxt([]), "draft")
        self.assertEqual(nxt(self.history("a")), "revise")
        self.assertEqual(nxt(self.history("a", "a")), "revise")
        self.assertEqual(nxt(self.history("a", "a", "a")), "diagnose")
        self.assertEqual(nxt(self.history("a", "a", "a", "b")), "escalate")

    def test_reused_strategy_after_diagnose_escalates_with_reason(self):
        rubric = copy.deepcopy(RUBRIC)
        rubric["promotion"]["max_revisions"] = 5
        result = pg.next_action(self.history("a", "a", "a", "a"), rubric)
        self.assertEqual(result["action"], "escalate")
        self.assertIn("reused", result["reason"])
        self.assertEqual(pg.next_action(self.history("a", "a", "a", "b"), rubric)["action"], "revise")

    def test_pass_and_invalid_short_circuit(self):
        self.assertEqual(pg.next_action(self.history("a", last=pg.PASS), RUBRIC)["action"], "promote")
        self.assertEqual(pg.next_action(self.history("a", last=pg.INVALID), RUBRIC)["action"], "rescore")


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_promotion_refused_until_signoff(self):
        result = pg.promote(PROMPT, scorecard(), RUBRIC, self.lib, "test-summary")
        self.assertEqual(result["status"], "refused")
        self.assertFalse((self.lib / "index.json").exists())

    def test_promotion_refused_when_not_passing(self):
        scores = [9.0] * len(DIM_IDS)
        result = pg.promote(PROMPT, scorecard(scores=scores), signed_rubric(), self.lib, "test-summary")
        self.assertEqual(result["status"], "refused")

    def test_promote_idempotent_versioned_and_reversible(self):
        rubric = signed_rubric()
        first = pg.promote(PROMPT, scorecard(), rubric, self.lib, "test-summary")
        self.assertEqual(first["status"], "promoted")
        self.assertEqual(pg.promote(PROMPT, scorecard(), rubric, self.lib, "test-summary")["status"], "skipped")

        text2 = PROMPT + "\n## Output\nMarkdown table.\n"
        second = pg.promote(text2, scorecard(text=text2), rubric, self.lib, "test-summary")
        self.assertEqual(second["version"], 2)
        index = json.loads((self.lib / "index.json").read_text())
        self.assertEqual(index["entries"]["test-summary"]["versions"][1]["parent"], 1)
        self.assertTrue((self.lib / "evidence" / "test-summary" / "v2.scorecard.json").exists())

        back = pg.rollback(self.lib, "test-summary")
        self.assertEqual((back["from"], back["to"]), (2, 1))
        index = json.loads((self.lib / "index.json").read_text())
        self.assertEqual(index["entries"]["test-summary"]["current"], 1)
        pg.rollback(self.lib, "test-summary")
        with self.assertRaises(pg.GateError):
            pg.rollback(self.lib, "test-summary")
        self.assertTrue((self.lib / "entries" / "test-summary" / "v2.md").exists())

    def test_rubric_bump_marks_entries_stale(self):
        pg.promote(PROMPT, scorecard(), signed_rubric(), self.lib, "test-summary")
        bumped = signed_rubric()
        bumped["version"] = "1.0.0"
        self.assertEqual(pg.stale(self.lib, bumped)["stale"][0]["slug"], "test-summary")
        self.assertEqual(pg.stale(self.lib, signed_rubric())["stale"], [])

    def test_slug_traversal_rejected(self):
        with self.assertRaises(pg.GateError):
            pg.promote(PROMPT, scorecard(), signed_rubric(), self.lib, "../escape")


class DocConsistencyTests(unittest.TestCase):
    DOC = (ROOT / "docs" / "graph-loop-prompting.md").read_text(encoding="utf-8")
    CAL = ROOT / "prompt-library" / "calibration" / "rubric-0.1.0"

    def test_doc_states_the_configured_thresholds(self):
        promo = RUBRIC["promotion"]
        for needle in (
            f"min(dimension) ≥ {promo['floor_tenths'] / 10:.1f}",
            f"weighted ≥ {promo['bar_thousandths'] / 1000:.1f}",
            f"{promo['max_revisions']} failed revisions",
            f"Rubric `{RUBRIC['version']}` is **pending sign-off**" if RUBRIC["status"] == "pending_signoff"
            else f"Rubric `{RUBRIC['version']}` is **signed off**",
        ):
            self.assertIn(needle, self.DOC)

    def test_calibration_table_matches_stored_scorecards(self):
        rubric = copy.deepcopy(RUBRIC)
        rubric["version"] = "0.1.0"
        texts = {"weak": (self.CAL / "weak.md").read_text(),
                 "strong": (self.CAL / "strong.md").read_text()}
        for card_path in sorted(self.CAL.glob("card-*.json")):
            kind, scorer = card_path.stem.split("-")[1:]
            verdict = pg.evaluate(texts[kind], json.loads(card_path.read_text()), rubric)
            row = f"| {scorer} | {verdict['weighted']:.3f} | {verdict['min']} | {verdict['status']} |"
            self.assertIn(row, self.DOC, card_path.name)


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = pg.main(list(argv))
        return code, json.loads(out.getvalue())

    def test_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            prompt, card = tmp / "p.md", tmp / "s.json"
            prompt.write_text(PROMPT)
            card.write_text(json.dumps(scorecard()))
            self.assertEqual(self.run_cli("evaluate", "--prompt", str(prompt), "--scorecard", str(card))[0], 0)
            code, out = self.run_cli(
                "promote", "--prompt", str(prompt), "--scorecard", str(card), "--slug", "x", "--library", str(tmp / "lib")
            )
            self.assertEqual((code, out["status"]), (1, "refused"))
            self.assertEqual(self.run_cli("lint", "--prompt", str(tmp / "missing.md"))[0], 2)


if __name__ == "__main__":
    unittest.main()
