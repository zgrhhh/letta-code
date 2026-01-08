"""
Local Test Runner for MSB Dataset Builder.

Runs pytest locally (when Docker is not available).
For production use, prefer docker_runner.py for isolation.
"""

import subprocess
import tempfile
import shutil
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


class LocalTestRunner:
    """
    Runs tests locally using subprocess.

    WARNING: This runner does not provide isolation.
    Use DockerTestRunner for production builds.
    """

    def __init__(
        self,
        repo_url: str = "https://github.com/pandas-dev/pandas.git",
        work_dir: Optional[Path] = None
    ):
        self.repo_url = repo_url
        self.work_dir = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="msb-"))
        self.repo_path = self.work_dir / "repo"

    def clone_repo(self, commit: str, shallow: bool = True) -> bool:
        """Clone the repository at a specific commit."""
        print(f"    Cloning repo to {self.repo_path}...")

        if self.repo_path.exists():
            # Reset to the target commit
            result = subprocess.run(
                ["git", "-C", str(self.repo_path), "fetch", "origin", commit],
                capture_output=True,
                text=True
            )
            result = subprocess.run(
                ["git", "-C", str(self.repo_path), "checkout", commit],
                capture_output=True,
                text=True
            )
            result = subprocess.run(
                ["git", "-C", str(self.repo_path), "reset", "--hard", commit],
                capture_output=True,
                text=True
            )
            return result.returncode == 0

        # Clone fresh
        clone_args = ["git", "clone"]
        if shallow:
            clone_args.extend(["--depth", "1"])
        clone_args.extend([self.repo_url, str(self.repo_path)])

        result = subprocess.run(clone_args, capture_output=True, text=True)

        if result.returncode != 0:
            # Try without shallow for specific commits
            clone_args = ["git", "clone", self.repo_url, str(self.repo_path)]
            result = subprocess.run(clone_args, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"    Clone failed: {result.stderr}")
            return False

        # Checkout specific commit
        result = subprocess.run(
            ["git", "-C", str(self.repo_path), "checkout", commit],
            capture_output=True,
            text=True
        )

        return result.returncode == 0

    def apply_patch(self, patch: str) -> bool:
        """Apply a patch to the repository."""
        patch_file = self.work_dir / "patch.diff"
        patch_file.write_text(patch)

        result = subprocess.run(
            ["git", "-C", str(self.repo_path), "apply", "--stat", str(patch_file)],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            # Try with more lenient options
            result = subprocess.run(
                ["git", "-C", str(self.repo_path), "apply", "--3way", str(patch_file)],
                capture_output=True,
                text=True
            )

        if result.returncode != 0:
            print(f"    Patch failed: {result.stderr}")
            return False

        # Actually apply the patch
        result = subprocess.run(
            ["git", "-C", str(self.repo_path), "apply", str(patch_file)],
            capture_output=True,
            text=True
        )

        return result.returncode == 0

    def collect_tests(self, test_files: list[str]) -> list[str]:
        """Collect test names without running them."""
        cmd = [
            "python", "-m", "pytest",
            "--collect-only", "-q",
            *test_files
        ]

        result = subprocess.run(
            cmd,
            cwd=str(self.repo_path),
            capture_output=True,
            text=True,
            timeout=120
        )

        tests = []
        for line in result.stdout.split("\n"):
            line = line.strip()
            if "::" in line and not line.startswith("<"):
                tests.append(line)

        return tests

    def run_tests(
        self,
        test_files: list[str],
        timeout: int = 300
    ) -> TestRunResult:
        """
        Run pytest on specific test files.

        Args:
            test_files: List of test file paths relative to repo root
            timeout: Timeout in seconds

        Returns:
            TestRunResult with test outcomes
        """
        cmd = [
            "python", "-m", "pytest",
            "--tb=no",
            "-v",
            "--no-header",
            "-q",
            *test_files
        ]

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                timeout=timeout
            )
            output = result.stdout + result.stderr
        except subprocess.TimeoutExpired:
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
            if "::" in line and " " in line:
                parts = line.rsplit(" ", 1)
                if len(parts) == 2:
                    test_name = parts[0].strip()
                    outcome = parts[1].strip().lower()

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
        print(f"    Checking out base commit: {base_commit[:8]}...")
        if not self.clone_repo(base_commit, shallow=False):
            raise RuntimeError(f"Failed to checkout {base_commit}")

        print(f"    Running tests BEFORE patch on {len(test_files)} files...")
        before_result = self.run_tests(test_files)
        print(f"      Before: {before_result.passed} passed, {before_result.failed} failed")

        # Get sets of test outcomes before patch
        before_passed = {t.name for t in before_result.tests if t.outcome == "passed"}
        before_failed = {t.name for t in before_result.tests if t.outcome == "failed"}

        print(f"    Applying patch...")
        if not self.apply_patch(patch):
            raise RuntimeError("Failed to apply patch")

        print(f"    Running tests AFTER patch...")
        after_result = self.run_tests(test_files)
        print(f"      After: {after_result.passed} passed, {after_result.failed} failed")

        # Get sets of test outcomes after patch
        after_passed = {t.name for t in after_result.tests if t.outcome == "passed"}

        # FAIL_TO_PASS: failed before, passed after
        fail_to_pass = list(before_failed & after_passed)

        # PASS_TO_PASS: passed both before and after
        pass_to_pass = list(before_passed & after_passed)

        print(f"    Identified {len(fail_to_pass)} FAIL_TO_PASS, {len(pass_to_pass)} PASS_TO_PASS")

        return fail_to_pass, pass_to_pass

    def cleanup(self):
        """Clean up temporary files."""
        if self.work_dir.exists() and str(self.work_dir).startswith("/tmp"):
            shutil.rmtree(self.work_dir, ignore_errors=True)


if __name__ == "__main__":
    # Quick test
    runner = LocalTestRunner()
    print(f"Work dir: {runner.work_dir}")
