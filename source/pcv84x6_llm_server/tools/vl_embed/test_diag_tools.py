#!/usr/bin/env python3
"""Board-free tests for the MYS-2913 diagnostic tooling.

These run anywhere: no NPU, no libsophon, no model. They exist because the
tooling's failure modes are dangerous in a way that is easy to miss -- a script
that deletes a caller's directory, or that reports success after a failed step,
would corrupt evidence rather than just fail.

Covered here:
  * a sentinel directory passed as a work dir is refused and left untouched
  * an existing work dir is refused by both the build and run scripts
  * a failed downstream step (bad package root, unreachable repo, unparsable
    trial JSON) makes the tool exit non-zero
  * aggregate.py rejects missing / corrupt / load-failed trial files
  * repeat_compare.py classifies unknown errors as other_error, not input_error

Run: python3 tools/vl_embed/test_diag_tools.py -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, **kw)


class SentinelProtection(unittest.TestCase):
    """A directory the caller owns must never be deleted or reused."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mys2913-test."))
        self.sentinel = self.tmp / "caller-data"
        self.sentinel.mkdir()
        self.marker = self.sentinel / "precious.txt"
        self.marker.write_text("must survive\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def assert_sentinel_intact(self):
        self.assertTrue(self.marker.exists(), "sentinel file was deleted")
        self.assertEqual(self.marker.read_text(), "must survive\n")

    def test_build_script_refuses_existing_work_dir(self):
        pkg = self.tmp / "pkg"
        (pkg / "native" / "src").mkdir(parents=True)
        done = run(["bash", str(HERE / "MYS-2913-build-diag.sh"),
                    str(pkg), str(self.sentinel)])
        self.assertNotEqual(done.returncode, 0,
                            "build script accepted an existing work dir")
        self.assertIn("refusing", (done.stdout + done.stderr).lower())
        self.assert_sentinel_intact()

    def test_run_from_clean_refuses_existing_work_dir(self):
        # The clone never starts, so this needs no network.
        done = run(["bash", str(HERE / "run_from_clean.sh"),
                    "some-branch", str(self.sentinel)])
        self.assertNotEqual(done.returncode, 0,
                            "run_from_clean accepted an existing work dir")
        self.assertIn("refusing", (done.stdout + done.stderr).lower())
        self.assert_sentinel_intact()

    def test_copy_chain_build_refuses_existing_dir(self):
        done = run(["bash", str(HERE / "copy_chain_build.sh"), str(self.sentinel)])
        self.assertNotEqual(done.returncode, 0,
                            "copy_chain_build accepted an existing dir")
        self.assert_sentinel_intact()


class FailurePropagation(unittest.TestCase):
    """A failed step must produce a non-zero exit, never a silent success."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mys2913-test."))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_build_script_fails_on_bad_package_root(self):
        empty = self.tmp / "not-a-package"
        empty.mkdir()
        work = self.tmp / "work"
        done = run(["bash", str(HERE / "MYS-2913-build-diag.sh"),
                    str(empty), str(work)])
        self.assertNotEqual(done.returncode, 0,
                            "build script succeeded on a package root without native/src")

    def test_build_script_fails_without_libsophon(self):
        pkg = self.tmp / "pkg"
        (pkg / "native" / "src").mkdir(parents=True)
        work = self.tmp / "work"
        env = dict(os.environ, LIBSOPHON=str(self.tmp / "no-such-libsophon"))
        done = run(["bash", str(HERE / "MYS-2913-build-diag.sh"),
                    str(pkg), str(work)], env=env)
        self.assertNotEqual(done.returncode, 0,
                            "build script succeeded without libsophon headers")

    def test_aggregate_fails_on_missing_file(self):
        out = self.tmp / "agg.json"
        done = run([sys.executable, str(HERE / "aggregate.py"),
                    "arm", str(out), str(self.tmp / "does-not-exist.json")])
        self.assertNotEqual(done.returncode, 0, "aggregate accepted a missing file")
        self.assertFalse(out.exists() and json.loads(out.read_text())["complete"],
                         "aggregate marked an incomplete arm as complete")

    def test_aggregate_fails_on_corrupt_json(self):
        bad = self.tmp / "bad.json"
        bad.write_text("{not json")
        done = run([sys.executable, str(HERE / "aggregate.py"),
                    "arm", str(self.tmp / "agg.json"), str(bad)])
        self.assertNotEqual(done.returncode, 0, "aggregate accepted corrupt JSON")

    def test_aggregate_fails_on_load_failed_trial(self):
        trial = self.tmp / "t.json"
        trial.write_text(json.dumps({"trials": [
            {"load_failed": "RuntimeError: bmodel loading failed", "counts": {}}]}))
        done = run([sys.executable, str(HERE / "aggregate.py"),
                    "arm", str(self.tmp / "agg.json"), str(trial)])
        self.assertNotEqual(done.returncode, 0,
                            "aggregate accepted a trial that never loaded")

    def test_aggregate_succeeds_on_clean_trial(self):
        trial = self.tmp / "t.json"
        trial.write_text(json.dumps({"trials": [
            {"counts": {"ok": 3}, "forward_executed": 3, "distinct_vectors": 1,
             "successful_vectors": 3, "worst_cosine": 1.0}]}))
        done = run([sys.executable, str(HERE / "aggregate.py"),
                    "arm", str(self.tmp / "agg.json"), str(trial)])
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_empty_trials_are_not_complete(self):
        trial = self.tmp / "empty.json"
        trial.write_text('{"trials": []}')
        done = run([sys.executable, str(HERE / "aggregate.py"), "arm",
                    str(self.tmp / "agg.json"), str(trial)])
        self.assertNotEqual(done.returncode, 0)

    def test_load_failure_exits_nonzero_single_and_isolated(self):
        for trials in (1, 2):
            with self.subTest(trials=trials):
                out = self.tmp / f"load-{trials}.json"
                done = run([sys.executable, str(HERE / "repeat_compare.py"),
                            "--library", "/nonexistent/diag.so", "--config", str(self.tmp),
                            "--model", "/nonexistent/model", "--trials", str(trials),
                            "--output", str(out)])
                self.assertNotEqual(done.returncode, 0)
                self.assertEqual(json.loads(out.read_text())["trials_load_failed"], trials)

    def test_verify_propagates_api_and_control_failures_and_cleans(self):
        # Exercise the real wrapper with deterministic build/probe executables,
        # without requiring an NPU or invoking a compiler.
        fixture = self.tmp / "wrapper"
        fixture.mkdir()
        shutil.copy(HERE / "verify.sh", fixture / "verify.sh")
        (fixture / "MYS-2913-build-diag.sh").write_text(
            '#!/bin/bash\nmkdir "$2"\nexit "${BUILD_RC:-0}"\n')
        (fixture / "copy_chain_build.sh").write_text(
            '#!/bin/bash\nmkdir "$1"\n'
            'cp "$PROBE_SOURCE" "$1/copy-chain"\nchmod +x "$1/copy-chain"\n')
        probe = fixture / "probe"
        probe.write_text('#!/bin/bash\nif [ "$3" = --fence ]; then '
                         'exit "$CONTROL_RC"; else exit "$BASELINE_RC"; fi\n')
        scratch = self.tmp / "scratch"
        scratch.mkdir()
        for build, baseline, control, expected in ((0, 1, 0, 0), (0, 0, 0, 0),
                                                  (0, 7, 0, 7), (0, 1, 1, 1),
                                                  (0, 1, 124, 124), (9, 0, 0, 1)):
            with self.subTest(build=build, baseline=baseline, control=control):
                env = dict(os.environ, TMPDIR=str(scratch), PROBE_SOURCE=str(probe),
                           BUILD_RC=str(build), BASELINE_RC=str(baseline),
                           CONTROL_RC=str(control))
                done = run(["bash", str(fixture / "verify.sh"), str(fixture)], env=env)
                self.assertEqual(done.returncode, expected, done.stdout + done.stderr)
                self.assertEqual(list(scratch.iterdir()), [])


class Classification(unittest.TestCase):
    """Unknown errors must not be relabelled as input rejections."""

    def test_unknown_error_is_other_error_and_execution_unknown(self):
        sys.path.insert(0, str(HERE))
        import repeat_compare

        self.assertEqual(repeat_compare.classify({"ok": False, "error": "kaboom"}),
                         "other_error")
        self.assertIsNone(repeat_compare.forward_executed("other_error"),
                          "unknown error must not assert the forward did not run")
        self.assertEqual(
            repeat_compare.classify({"ok": False,
                                     "error": "RuntimeError: encoder returned a zero vector"}),
            "zero")
        self.assertEqual(
            repeat_compare.classify({"ok": False,
                                     "error": "RuntimeError: NPU engine faulted; reload required"}),
            "refused")
        self.assertFalse(repeat_compare.forward_executed("refused"))
        self.assertTrue(repeat_compare.forward_executed("zero"))
        self.assertEqual(repeat_compare.classify(
            {"ok": False, "error": "device copy exceeds graph buffer"}), "other_error")


class Syntax(unittest.TestCase):
    def test_python_files_compile(self):
        for name in ("repeat_compare.py", "repeat_probe.py", "aggregate.py",
                     "repeat_probe_service.py", "test_diag_tools.py"):
            path = HERE / name
            done = run([sys.executable, "-m", "py_compile", str(path)])
            self.assertEqual(done.returncode, 0, f"{name}: {done.stderr}")

    def test_shell_scripts_parse(self):
        for name in ("MYS-2913-build-diag.sh", "run_from_clean.sh",
                     "sites.sh", "copy_chain_build.sh", "verify.sh"):
            done = run(["bash", "-n", str(HERE / name)])
            self.assertEqual(done.returncode, 0, f"{name}: {done.stderr}")


if __name__ == "__main__":
    unittest.main()
