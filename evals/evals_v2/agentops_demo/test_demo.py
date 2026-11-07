"""Local checks for the mock pipeline only; never invoke real application paths."""

import copy
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("demo", Path(__file__).with_name("demo.py"))
demo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(demo)


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.release = demo.manifest("passing-release", "a" * 40, "123", "1", "demo/example")
        self.outcomes = {job: {"result": "success"} for job in demo.JOBS.values()}
        self.env = {
            "GITHUB_SHA": "a" * 40,
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_REPOSITORY": "demo/example",
            "DEMO_SCENARIO": "passing-release",
            "GITHUB_STEP_SUMMARY": str(self.root / "job-summary.md"),
            "GITHUB_OUTPUT": str(self.root / "job-output"),
        }

    def prepare(self):
        demo.write(self.root / "release-manifest.json", self.release)
        for metric in demo.METRICS:
            demo.write(self.root / f"{metric}.json", demo.evidence(self.release, metric))

    def cli(self, *args, expected=0, **env):
        result = subprocess.run(
            [sys.executable, str(demo.HERE / "demo.py"), *args, "--evidence", str(self.root)],
            env={**os.environ, **self.env, **env},
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def test_passing_end_to_end_same_candidate(self):
        self.cli("manifest", "--scenario", "passing-release", "--output", str(self.root))
        build_text = (self.root / "build-summary.md").read_text()
        for value in (
            "a" * 40,
            "sha256:",
            "v21",
            "demo-prompt-r7",
            "demo-runtime-r3",
            "mock-model-deployment",
            "demo-model-2026-01",
            "mock-no-auto-upgrade",
            "demo-dataset-r1",
            "demo-evaluators-r1",
            "mock-judge-2026-01",
        ):
            self.assertIn(value, build_text)
        self.assertNotIn(demo.DISCLAIMER, build_text)
        for metric in demo.METRICS:
            self.cli("evaluate", "--metric", metric, "--output", str(self.root))
        self.cli("gate", "--output", str(self.root / "gate"), NEEDS_JSON=json.dumps(self.outcomes))
        decision = demo.read(self.root / "gate/decision.json")
        self.assertTrue(decision["eligible"])
        gate_text = (self.root / "gate/summary.md").read_text()
        self.assertEqual(gate_text.count(demo.DISCLAIMER), 1)
        self.assertIn("N/A", gate_text)
        self.assertIn("Pinning an agent version does not freeze", gate_text)
        demo.write(self.root / "decision.json", decision)
        for stage in ("staging", "smoke"):
            self.cli("simulate", "--stage", stage, "--output", str(self.root / stage))
        self.cli("promote", "--output", str(self.root / "promotion"))
        serving = demo.read(self.root / "promotion/mock-serving.json")
        self.assertEqual(serving["serving"], "v21")
        self.assertEqual(serving["manifest"], demo.read(self.root / "release-manifest.json"))
        text = (self.root / "promotion/summary.md").read_text()
        self.assertIn("Mock serving version changed", text)
        self.assertNotIn(demo.DISCLAIMER, text)
        self.assertNotIn("Evaluation overview", text)
        for stage in ("staging", "smoke"):
            self.assertNotIn(demo.DISCLAIMER, (self.root / stage / "summary.md").read_text())

    def test_groundedness_alone_fails_and_keeps_evidence(self):
        self.env["DEMO_SCENARIO"] = "blocked-by-groundedness"
        self.cli("manifest", "--scenario", self.env["DEMO_SCENARIO"], "--output", str(self.root))
        for metric in demo.METRICS:
            self.cli(
                "evaluate",
                "--metric",
                metric,
                "--output",
                str(self.root),
                expected=1 if metric == "groundedness" else 0,
            )
            self.assertTrue((self.root / f"{metric}.json").exists())
        self.outcomes["eval_groundedness"]["result"] = "failure"
        self.cli("gate", "--output", str(self.root / "gate"), expected=1, NEEDS_JSON=json.dumps(self.outcomes))
        decision = demo.read(self.root / "gate/decision.json")
        self.assertFalse(decision["eligible"])
        text = (self.root / "gate/summary.md").read_text()
        self.assertIn("groundedness: 2.667 < required 4", text)
        self.assertIn("Mock serving version remains v13", text)
        self.assertEqual(text.count(demo.DISCLAIMER), 1)
        demo.write(self.root / "decision.json", decision)
        self.cli("promote", "--output", str(self.root / "promotion"), expected=1)
        self.assertFalse((self.root / "promotion/mock-serving.json").exists())

    def test_missing_corrupt_incomplete_and_wrong_candidate_block(self):
        self.prepare()
        path = self.root / "groundedness.json"
        good = path.read_text()
        cases = [
            "{",
            "null",
            "[]",
            "{}",
            good.replace('"v21"', '"v22"'),
            good.replace('"score": 4.333333333333333', '"score": 5'),
        ]
        for bad in cases:
            with self.subTest(bad=bad):
                path.write_text(bad)
                _, errors = demo.collect(self.release, self.root, self.outcomes)
                self.assertTrue(errors)
        path.unlink()
        _, errors = demo.collect(self.release, self.root, self.outcomes)
        self.assertTrue(errors)

    def test_bool_cannot_replace_numeric_and_duplicate_json_keys_rejected(self):
        self.prepare()
        path = self.root / "task-adherence.json"
        value = demo.read(path)
        value["score"] = True
        path.write_text(json.dumps(value))
        self.assertTrue(demo.collect(self.release, self.root, self.outcomes)[1])
        path.write_text('{"score": 1, "score": 1}')
        self.assertTrue(demo.collect(self.release, self.root, self.outcomes)[1])

    def test_job_failure_skip_or_missing_blocks_even_when_scores_pass(self):
        self.prepare()
        for status in ("failure", "skipped", "cancelled", None):
            with self.subTest(status=status):
                self.outcomes["eval_groundedness"]["result"] = status
                self.assertTrue(demo.collect(self.release, self.root, self.outcomes)[1])
        del self.outcomes["eval_groundedness"]
        self.assertTrue(demo.collect(self.release, self.root, self.outcomes)[1])

    def test_missing_manifest_produces_blocked_summary_and_false_output(self):
        self.cli("gate", "--output", str(self.root / "gate"), expected=1, NEEDS_JSON="{}")
        self.assertIn("eligible=false", (self.root / "job-output").read_text())
        self.assertIn("BLOCKED", (self.root / "gate/summary.md").read_text())

    def test_invalid_evidence_summary_does_not_display_na_or_pass(self):
        self.prepare()
        (self.root / "groundedness.json").write_text('{"score": 5}')
        self.cli("gate", "--output", str(self.root / "gate"), expected=1, NEEDS_JSON=json.dumps(self.outcomes))
        decision = demo.read(self.root / "gate/decision.json")
        self.assertFalse(decision["eligible"])
        text = (self.root / "gate/summary.md").read_text()
        self.assertIn("| groundedness | 1–5 | INVALID / MISSING | 4 | BLOCKED |", text)
        self.assertIn("invalid or missing evidence", text)
        self.assertNotIn("eligible=true", (self.root / "job-output").read_text())

    def test_promotion_rejects_missing_or_malformed_decision(self):
        self.prepare()
        self.cli("promote", "--output", str(self.root / "missing-decision"), expected=1)
        demo.write(self.root / "decision.json", {"eligible": 1, "errors": [], "manifest": self.release})
        self.cli("promote", "--output", str(self.root / "invalid-decision"), expected=1)
        self.assertFalse((self.root / "invalid-decision/mock-serving.json").exists())

    def test_manifest_binds_actual_run_and_mock_versions(self):
        self.assertRegex(self.release["simulated_release"]["image"], r"@sha256:[0-9a-f]{64}$")
        for section, key, value in (
            ("actual_github_metadata", "source_sha", "b" * 40),
            ("simulated_release", "candidate_version", "v99"),
            ("simulated_release", "model", {}),
        ):
            changed = copy.deepcopy(self.release)
            changed[section][key] = value
            with patch.dict(os.environ, self.env):
                with self.assertRaises(ValueError):
                    demo.validate_manifest(changed)

    def test_fixture_inapplicable_and_invalid_scores_fail_closed(self):
        original = demo.read(demo.HERE / "fixtures.json")
        for value in (None, True, float("nan"), -1, 6, "5"):
            changed = copy.deepcopy(original)
            changed["passing-release"]["wiki-answer-supported"]["groundedness"] = value
            with patch.object(demo, "read", return_value=changed):
                with self.assertRaises(ValueError):
                    demo.fixture("passing-release")
        changed = copy.deepcopy(original)
        changed["passing-release"]["tool-retry"]["groundedness"] = 5
        with patch.object(demo, "read", return_value=changed):
            with self.assertRaises(ValueError):
                demo.fixture("passing-release")

    def test_threshold_equality_passes(self):
        self.assertTrue(demo.evidence(self.release, "task-adherence")["passed"])
        blocked = demo.manifest("blocked-by-groundedness", "a" * 40, "123", "1", "demo/example")
        passing_rows = demo.fixture("passing-release")
        failing_rows = demo.fixture("blocked-by-groundedness")
        for case in demo.CASES:
            for metric in demo.METRICS:
                if metric != "groundedness":
                    self.assertEqual(passing_rows[case][metric], failing_rows[case][metric])
        self.assertFalse(demo.evidence(blocked, "groundedness")["passed"])

    def test_workflow_graph_and_fail_closed_conditions(self):
        workflow = (demo.HERE.parents[2] / ".github/workflows/demo-agentops.yml").read_text()
        blocks = dict(
            re.findall(r"^  (\w+):\n(.*?)(?=^  \w+:\n|\Z)", workflow.split("jobs:\n", 1)[1], re.MULTILINE | re.DOTALL)
        )
        expected_names = {
            "build": "Build",
            "gate": "AgentOps quality gate",
            "staging": "Deploy to staging",
            "smoke": "Smoke tests",
            "production": "Promote to production",
            **{
                job: f"Eval — {name}"
                for job, name in zip(
                    demo.JOBS.values(),
                    ("Wiki claims", "Wiki accuracy", "Groundedness", "Task adherence", "Tool-call accuracy"),
                    strict=True,
                )
            },
        }
        self.assertEqual(set(blocks), set(expected_names))
        for job, name in expected_names.items():
            self.assertIn(f"    name: {name}\n", blocks[job])
        self.assertNotIn("needs:", blocks["build"])
        self.assertIn('manifest --scenario "$DEMO_SCENARIO"', blocks["build"])
        self.assertIn("demo-output/build-summary.md", blocks["build"])
        self.assertIn("demo-output/release-manifest.json", blocks["build"])
        for job in demo.JOBS.values():
            self.assertIn("    needs: build\n", blocks[job])
            self.assertIn("        if: always()\n        uses: actions/upload-artifact@v4", blocks[job])
            self.assertIn(f"      - {job}\n", blocks["gate"])
        self.assertIn("    if: always()\n", blocks["gate"])
        self.assertIn("eligible: ${{ steps.decision.outputs.eligible }}", blocks["gate"])
        self.assertIn("    needs: gate\n", blocks["staging"])
        release_condition = "needs.gate.result == 'success' && needs.gate.outputs.eligible == 'true'"
        self.assertIn(f"    if: {release_condition}\n", blocks["staging"])
        self.assertIn("    needs: staging\n", blocks["smoke"])
        self.assertNotIn("    if:", blocks["smoke"])
        self.assertIn("    needs: [gate, smoke]\n", blocks["production"])
        self.assertIn(f"    if: {release_condition} && needs.smoke.result == 'success'\n", blocks["production"])
        self.assertNotIn("continue-on-error", workflow)
        self.assertIn("name: DEMO — AgentOps CI/CD\n", workflow)
        self.assertEqual(
            re.findall(r"^  (\w+):", workflow.split("on:\n", 1)[1].split("permissions:")[0], re.M),
            ["workflow_dispatch"],
        )
        for gate_status, eligible, smoke_status, allowed in (
            ("success", "true", "success", True),
            ("failure", "true", "success", False),
            ("success", "false", "success", False),
            ("success", "", "success", False),
            ("skipped", "true", "success", False),
            ("success", "true", "skipped", False),
        ):
            self.assertEqual(gate_status == "success" and eligible == "true" and smoke_status == "success", allowed)


if __name__ == "__main__":
    unittest.main()
