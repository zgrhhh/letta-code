"""
Docker Test Runner for MSB Dataset Builder.

Runs pytest in isolated Docker containers to identify FAIL_TO_PASS tests.
"""

import subprocess
import json
import tempfile
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class TestResult:
    """Result of running a test."""

    name: str
    outcome: str  # 'passed', 'failed', 'error', 'skipped'
    duration: float
    message: Optional[str] = None


@dataclass
class TestRunResult:
    """Result of a full test run."""

    success: bool
    total: int
    passed: int
    failed: int
    skipped: int
    errors: int
    tests: list[TestResult]
    raw_output: str


class DockerTestRunner:
    """
    Runs tests in Docker containers for pandas.

    Uses the official pandas development Docker image.
    """

    # Official pandas Docker image for testing
    PANDAS_IMAGE = "python:3.11-slim"

    def __init__(
        self,
        repo_url: str = "https://github.com/pandas-dev/pandas.git",
        work_dir: Optional[Path] = None
    ):
        self.repo_url = repo_url
        self.work_dir = work_dir or Path(tempfile.mkdtemp(prefix="msb-"))
        self.container_name = None

    def _run_docker(
        self,
        cmd: list[str],
        image: str = None,
        workdir: str = "/pandas",
        timeout: int = 600
    ) -> subprocess.CompletedProcess:
        """Run a command in a Docker container."""
        image = image or self.PANDAS_IMAGE

        docker_cmd = [
            "docker", "run", "--rm",
            "-v", f"{self.work_dir}:/pandas",
            "-w", workdir,
            image
        ] + cmd

        return subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )

    def clone_repo(self, commit: str) -> bool:
        """Clone the repository at a specific commit."""
        repo_path = self.work_dir / "repo"

        if repo_path.exists():
            # Reset to the target commit
            result = subprocess.run(
                ["git", "-C", str(repo_path), "fetch", "--all"],
                capture_output=True
            )
            result = subprocess.run(
                ["git", "-C", str(repo_path), "checkout", commit],
                capture_output=True
            )
            result = subprocess.run(
                ["git", "-C", str(repo_path), "reset", "--hard", commit],
                capture_output=True
            )
        else:
            # Clone fresh
            result = subprocess.run(
                ["git", "clone", "--depth", "100", self.repo_url, str(repo_path)],
                capture_output=True
            )
            if result.returncode != 0:
                print(f"Clone failed: {result.stderr}")
                return False

            # Fetch the specific commit
            result = subprocess.run(
                ["git", "-C", str(repo_path), "fetch", "--depth", "100", "origin", commit],
                capture_output=True
            )

            result = subprocess.run(
                ["git", "-C", str(repo_path), "checkout", commit],
                capture_output=True
            )

        return result.returncode == 0

    def apply_patch(self, patch: str) -> bool:
        """Apply a patch to the repository."""
        repo_path = self.work_dir / "repo"
        patch_file = self.work_dir / "patch.diff"

        # Write patch to file
        patch_file.write_text(patch)

        # Apply patch
        result = subprocess.run(
            ["git", "-C", str(repo_path), "apply", str(patch_file)],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            print(f"Patch failed: {result.stderr}")
            return False

        return True

    def run_tests(
        self,
        test_files: list[str],
        timeout: int = 600,
        collect_only: bool = False
    ) -> TestRunResult:
        """
        Run pytest on specific test files.

        Args:
            test_files: List of test file paths relative to repo root
            timeout: Timeout in seconds
            collect_only: If True, only collect tests without running

        Returns:
            TestRunResult with test outcomes
        """
        repo_path = self.work_dir / "repo"

        # Build pytest command
        pytest_args = [
            "python", "-m", "pytest",
            "--tb=short",
            "-v",
            "--no-header",
            "-q",
        ]

        if collect_only:
            pytest_args.append("--collect-only")

        pytest_args.extend(test_files)

        # Create a script to install deps and run tests
        script = f"""#!/bin/bash
set -e
cd /pandas/repo
pip install -e . --no-build-isolation -q 2>/dev/null || true
pip install pytest hypothesis pyarrow -q 2>/dev/null || true
{' '.join(pytest_args)} 2>&1 || true
"""

        script_path = self.work_dir / "run_tests.sh"
        script_path.write_text(script)
        script_path.chmod(0o755)

        # Run in Docker
        try:
            result = self._run_docker(
                ["/bin/bash", "/pandas/run_tests.sh"],
                workdir="/pandas",
                timeout=timeout
            )
            output = result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            output = "TIMEOUT"
            return TestRunResult(
                success=False,
                total=0,
                passed=0,
                failed=0,
                skipped=0,
                errors=1,
                tests=[],
                raw_output="Test run timed out"
            )

        # Parse pytest output
        return self._parse_pytest_output(output)

    def _parse_pytest_output(self, output: str) -> TestRunResult:
        """Parse pytest output to extract test results."""
        tests = []
        passed = 0
        failed = 0
        skipped = 0
        errors = 0

        lines = output.split("\n")

        for line in lines:
            line = line.strip()

            # Parse test result lines like:
            # test_file.py::test_name PASSED
            # test_file.py::test_name FAILED
            if "::" in line:
                parts = line.split()
                if len(parts) >= 2:
                    test_name = parts[0]
                    outcome = parts[-1].lower()

                    if outcome in ("passed", "failed", "error", "skipped"):
                        tests.append(TestResult(
                            name=test_name,
                            outcome=outcome,
                            duration=0.0
                        ))

                        if outcome == "passed":
                            passed += 1
                        elif outcome == "failed":
                            failed += 1
                        elif outcome == "skipped":
                            skipped += 1
                        elif outcome == "error":
                            errors += 1

        return TestRunResult(
            success=(failed == 0 and errors == 0),
            total=len(tests),
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=errors,
            tests=tests,
            raw_output=output
        )

    def identify_fail_to_pass(
        self,
        base_commit: str,
        patch: str,
        test_files: list[str]
    ) -> tuple[list[str], list[str]]:
        """
        Identify FAIL_TO_PASS and PASS_TO_PASS tests.

        This runs tests before and after applying the patch to determine:
        - FAIL_TO_PASS: Tests that fail before patch but pass after
        - PASS_TO_PASS: Tests that pass both before and after

        Args:
            base_commit: The commit to test against (before patch)
            patch: The patch content to apply
            test_files: List of test files to run

        Returns:
            Tuple of (fail_to_pass, pass_to_pass) test names
        """
        print(f"  Checking out base commit: {base_commit[:8]}...")
        if not self.clone_repo(base_commit):
            raise RuntimeError(f"Failed to checkout {base_commit}")

        print(f"  Running tests BEFORE patch on {len(test_files)} files...")
        before_result = self.run_tests(test_files)
        print(f"    Before: {before_result.passed} passed, {before_result.failed} failed")

        # Get sets of test outcomes before patch
        before_passed = {t.name for t in before_result.tests if t.outcome == "passed"}
        before_failed = {t.name for t in before_result.tests if t.outcome == "failed"}

        print(f"  Applying patch...")
        if not self.apply_patch(patch):
            raise RuntimeError("Failed to apply patch")

        print(f"  Running tests AFTER patch...")
        after_result = self.run_tests(test_files)
        print(f"    After: {after_result.passed} passed, {after_result.failed} failed")

        # Get sets of test outcomes after patch
        after_passed = {t.name for t in after_result.tests if t.outcome == "passed"}
        after_failed = {t.name for t in after_result.tests if t.outcome == "failed"}

        # FAIL_TO_PASS: failed before, passed after
        fail_to_pass = list(before_failed & after_passed)

        # PASS_TO_PASS: passed both before and after
        pass_to_pass = list(before_passed & after_passed)

        print(f"  Identified {len(fail_to_pass)} FAIL_TO_PASS, {len(pass_to_pass)} PASS_TO_PASS")

        return fail_to_pass, pass_to_pass

    def cleanup(self):
        """Clean up temporary files and containers."""
        import shutil
        if self.work_dir.exists():
            shutil.rmtree(self.work_dir, ignore_errors=True)


if __name__ == "__main__":
    # Test with a simple example
    runner = DockerTestRunner()

    # Test cloning
    print("Testing clone...")
    result = runner.clone_repo("main")
    print(f"Clone result: {result}")
