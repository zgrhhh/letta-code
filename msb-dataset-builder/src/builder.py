"""
MSB Dataset Builder.

Builds SWE-bench compatible datasets from multi-PR tracker issues.
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from .scraper import PRInfo, get_merged_prs_for_tracker

# Try Docker first, fall back to local runner
try:
    from .docker_runner import DockerTestRunner as TestRunner
    RUNNER_TYPE = "docker"
except ImportError:
    from .local_runner import LocalTestRunner as TestRunner
    RUNNER_TYPE = "local"


@dataclass
class SessionData:
    """Data for a single session in the MSB dataset."""

    session_id: str
    sequence_number: int
    pr_number: int
    base_commit: str

    # Task description
    problem_statement: str
    hints_text: str

    # Solution
    patch: str
    test_patch: str

    # Test specification (identified by running tests)
    FAIL_TO_PASS: list[str]
    PASS_TO_PASS: list[str]

    # Dependencies
    depends_on: list[str]
    provides: list[str]

    # Metadata
    expected_memory_updates: dict


@dataclass
class TaskData:
    """Data for a complete MSB task (multi-session)."""

    task_id: str
    repo: str
    enhancement_id: str
    tracker_issue: int

    sessions: list[SessionData]

    total_sessions: int
    difficulty: str

    created_at: str
    version: str = "1.0.0"


class MSBDatasetBuilder:
    """
    Builds MSB datasets from GitHub tracker issues.

    The key differentiator from SWE-bench: FAIL_TO_PASS is identified by
    actually running pytest, not by parsing diffs or CI logs.
    """

    def __init__(
        self,
        owner: str,
        repo: str,
        output_dir: Path = Path("output"),
        work_dir: Optional[Path] = None
    ):
        self.owner = owner
        self.repo = repo
        self.output_dir = output_dir
        self.work_dir = work_dir

        self.output_dir.mkdir(parents=True, exist_ok=True)

    def build_from_tracker(
        self,
        tracker_issue: int,
        enhancement_id: str,
        limit: Optional[int] = None,
        skip_test_run: bool = False
    ) -> TaskData:
        """
        Build an MSB task from a tracker issue.

        Args:
            tracker_issue: GitHub issue number for the tracker
            enhancement_id: Enhancement identifier (e.g., 'PDEP-14')
            limit: Optional limit on number of PRs to process
            skip_test_run: If True, skip running tests (for testing)

        Returns:
            TaskData with all sessions
        """
        print(f"Building MSB task for {self.owner}/{self.repo} #{tracker_issue}")
        print(f"Enhancement: {enhancement_id}")
        print("-" * 60)

        # Step 1: Scrape PRs from tracker
        prs = get_merged_prs_for_tracker(
            self.owner, self.repo, tracker_issue, limit=limit
        )

        if not prs:
            raise ValueError(f"No merged PRs found for tracker #{tracker_issue}")

        print(f"\nProcessing {len(prs)} merged PRs...")

        # Step 2: Build sessions from PRs
        sessions = []
        task_id = f"{self.owner}__{self.repo}-{enhancement_id}".replace("/", "__")

        for i, pr in enumerate(prs):
            print(f"\n[{i+1}/{len(prs)}] Processing PR #{pr.number}: {pr.title}")

            session = self._build_session(
                pr=pr,
                task_id=task_id,
                sequence_number=i + 1,
                previous_sessions=sessions,
                skip_test_run=skip_test_run
            )

            sessions.append(session)

        # Step 3: Create task
        task = TaskData(
            task_id=task_id,
            repo=f"{self.owner}/{self.repo}",
            enhancement_id=enhancement_id,
            tracker_issue=tracker_issue,
            sessions=sessions,
            total_sessions=len(sessions),
            difficulty=self._estimate_difficulty(sessions),
            created_at=datetime.now().isoformat()
        )

        return task

    def _build_session(
        self,
        pr: PRInfo,
        task_id: str,
        sequence_number: int,
        previous_sessions: list[SessionData],
        skip_test_run: bool = False
    ) -> SessionData:
        """Build a session from a PR."""
        session_id = f"{task_id}-{sequence_number:03d}"

        # Extract problem statement from PR body
        problem_statement = self._extract_problem_statement(pr)

        # Identify FAIL_TO_PASS by running tests
        fail_to_pass = []
        pass_to_pass = []

        if not skip_test_run and pr.test_files_changed:
            try:
                print(f"  Using {RUNNER_TYPE} test runner...")
                runner = TestRunner(work_dir=self.work_dir)
                fail_to_pass, pass_to_pass = runner.identify_fail_to_pass(
                    base_commit=pr.base_sha,
                    patch=pr.patch,
                    test_files=pr.test_files_changed
                )
            except Exception as e:
                print(f"  Warning: Test run failed: {e}")
            finally:
                if 'runner' in locals() and hasattr(runner, 'cleanup'):
                    runner.cleanup()

        # Infer dependencies from previous sessions
        depends_on = self._infer_dependencies(pr, previous_sessions)

        # Extract what this PR provides
        provides = self._extract_provides(pr)

        return SessionData(
            session_id=session_id,
            sequence_number=sequence_number,
            pr_number=pr.number,
            base_commit=pr.base_sha,
            problem_statement=problem_statement,
            hints_text="",  # Can be populated later
            patch=pr.patch or "",
            test_patch=self._extract_test_patch(pr.patch or ""),
            FAIL_TO_PASS=fail_to_pass,
            PASS_TO_PASS=pass_to_pass,
            depends_on=depends_on,
            provides=provides,
            expected_memory_updates={}
        )

    def _extract_problem_statement(self, pr: PRInfo) -> str:
        """Extract a problem statement from PR title and body."""
        # Use title as the main statement
        statement = pr.title

        # Add first paragraph of body if it's informative
        if pr.body:
            lines = pr.body.strip().split("\n\n")
            if lines and len(lines[0]) > 50:
                statement += f"\n\n{lines[0]}"

        return statement

    def _extract_provides(self, pr: PRInfo) -> list[str]:
        """Extract what a PR provides (new classes, functions, etc.)."""
        provides = []

        if pr.patch:
            # Look for new class definitions
            import re
            classes = re.findall(r"^\+class (\w+)", pr.patch, re.MULTILINE)
            provides.extend([f"{c} class" for c in classes])

            # Look for new function definitions
            funcs = re.findall(r"^\+def (\w+)", pr.patch, re.MULTILINE)
            provides.extend([f"{f} function" for f in funcs[:5]])  # Limit

        return provides

    def _infer_dependencies(
        self,
        pr: PRInfo,
        previous_sessions: list[SessionData]
    ) -> list[str]:
        """Infer dependencies from previous sessions."""
        # Simple heuristic: check if PR body mentions previous PRs
        depends_on = []

        if pr.body:
            for prev in previous_sessions:
                if f"#{prev.pr_number}" in pr.body:
                    depends_on.append(prev.session_id)

        return depends_on

    def _extract_test_patch(self, patch: str) -> str:
        """Extract only the test-related parts of a patch."""
        lines = patch.split("\n")
        test_lines = []
        in_test_file = False

        for line in lines:
            if line.startswith("diff --git"):
                in_test_file = "test" in line.lower()

            if in_test_file:
                test_lines.append(line)

        return "\n".join(test_lines)

    def _estimate_difficulty(self, sessions: list[SessionData]) -> str:
        """Estimate task difficulty based on sessions."""
        total_lines = sum(
            len(s.patch.split("\n")) for s in sessions
        )

        if total_lines < 100:
            return "easy"
        elif total_lines < 500:
            return "medium"
        else:
            return "hard"

    def save_jsonl(self, task: TaskData, filename: str = None) -> Path:
        """Save task data as JSONL (SWE-bench compatible format)."""
        filename = filename or f"{task.task_id}.jsonl"
        output_path = self.output_dir / filename

        # Convert to SWE-bench compatible format
        # Each session becomes a separate entry
        with open(output_path, "w") as f:
            for session in task.sessions:
                entry = {
                    "instance_id": session.session_id,
                    "repo": task.repo,
                    "base_commit": session.base_commit,
                    "problem_statement": session.problem_statement,
                    "hints_text": session.hints_text,
                    "patch": session.patch,
                    "test_patch": session.test_patch,
                    "FAIL_TO_PASS": json.dumps(session.FAIL_TO_PASS),
                    "PASS_TO_PASS": json.dumps(session.PASS_TO_PASS),

                    # MSB-specific fields
                    "msb_task_id": task.task_id,
                    "msb_sequence_number": session.sequence_number,
                    "msb_total_sessions": task.total_sessions,
                    "msb_depends_on": json.dumps(session.depends_on),
                    "msb_enhancement_id": task.enhancement_id,
                    "created": task.created_at,
                    "version": task.version
                }
                f.write(json.dumps(entry) + "\n")

        print(f"\nSaved {len(task.sessions)} sessions to {output_path}")
        return output_path

    def save_full_json(self, task: TaskData, filename: str = None) -> Path:
        """Save full task data as JSON (includes all MSB metadata)."""
        filename = filename or f"{task.task_id}.json"
        output_path = self.output_dir / filename

        # Convert dataclasses to dict
        def to_dict(obj):
            if hasattr(obj, "__dataclass_fields__"):
                return {k: to_dict(v) for k, v in asdict(obj).items()}
            elif isinstance(obj, list):
                return [to_dict(item) for item in obj]
            else:
                return obj

        with open(output_path, "w") as f:
            json.dump(to_dict(task), f, indent=2)

        print(f"Saved full task data to {output_path}")
        return output_path


def build_single_pr(
    owner: str,
    repo: str,
    pr_number: int,
    output_dir: Path = Path("output")
) -> SessionData:
    """
    Build a session from a single PR for validation.

    This is useful for testing the pipeline with a single PR before
    processing an entire tracker.
    """
    from .scraper import get_pr_info, get_pr_diff, extract_test_files_from_diff

    print(f"Building session for {owner}/{repo} PR #{pr_number}")
    print("-" * 60)

    # Get PR info
    pr = get_pr_info(owner, repo, pr_number)
    print(f"PR: {pr.title}")
    print(f"State: {pr.state}")
    print(f"Base: {pr.base_sha[:8]}")

    # Get diff
    pr.patch = get_pr_diff(owner, repo, pr_number)
    pr.test_files_changed = extract_test_files_from_diff(pr.patch)
    print(f"Test files: {pr.test_files_changed}")

    # Build session
    builder = MSBDatasetBuilder(owner, repo, output_dir)
    session = builder._build_session(
        pr=pr,
        task_id=f"{owner}__{repo}-{pr_number}",
        sequence_number=1,
        previous_sessions=[]
    )

    # Save as single-session task
    task = TaskData(
        task_id=f"{owner}__{repo}-{pr_number}",
        repo=f"{owner}/{repo}",
        enhancement_id=f"PR-{pr_number}",
        tracker_issue=pr_number,
        sessions=[session],
        total_sessions=1,
        difficulty="medium",
        created_at=datetime.now().isoformat()
    )

    builder.save_jsonl(task)
    builder.save_full_json(task)

    return session


if __name__ == "__main__":
    # Test with pandas PR #54533 (first PDEP-14 PR)
    session = build_single_pr("pandas-dev", "pandas", 54533)
    print(f"\nSession ID: {session.session_id}")
    print(f"FAIL_TO_PASS: {session.FAIL_TO_PASS}")
    print(f"PASS_TO_PASS: {session.PASS_TO_PASS}")
