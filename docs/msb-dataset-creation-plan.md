# MSB Dataset Creation Plan (SWE-bench Compliant)

## Objective

Create a multi-PR benchmark dataset following **exactly** the SWE-bench methodology, adapted for PR sequences.

## SWE-bench Methodology (What We Must Follow)

Based on the [ICLR 2024 paper](https://arxiv.org/abs/2310.06770) and [official documentation](https://www.swebench.com/SWE-bench/):

### Three-Stage Pipeline

```
Stage I:   Repo Selection & Data Scraping
Stage II:  Attribute-Based Filtering
Stage III: Execution-Based Filtering (CRITICAL)
```

### How SWE-bench Identifies FAIL_TO_PASS Tests

**NOT from CI logs. NOT from parsing test_patch. ACTUAL EXECUTION.**

```
1. Checkout base_commit
2. Setup environment (install dependencies)
3. Run test suite → log_pre (record failing tests)
4. Apply gold patch
5. Run test suite → log_post (record passing tests)
6. Compare:
   - FAIL_TO_PASS = tests in log_pre(FAIL) ∩ log_post(PASS)
   - PASS_TO_PASS = tests in log_pre(PASS) ∩ log_post(PASS)
7. Filter out if no tests switch from FAIL → PASS
```

This is the **only** reliable way. We must do the same.

---

## MSB Pipeline (Adapted for Multi-PR)

### Stage I: Repo Selection & PR Chain Scraping

**Input**: Target repos with enhancement proposals

```python
TARGETS = [
    ("pandas-dev/pandas", 54792, "PDEP-14"),   # String dtype
    ("pandas-dev/pandas", 49473, "PDEP-7"),    # Copy-on-Write
    ("apache/airflow", None, "AIP-10"),        # Multi-stage Docker
]
```

**Process**:
```python
def scrape_pr_chain(repo, tracker_issue):
    # 1. Get all PRs linked to tracker
    prs = get_linked_prs(tracker_issue)

    # 2. Filter to merged only
    prs = [pr for pr in prs if pr.merged_at]

    # 3. Sort by merge date (chronological order)
    prs.sort(key=lambda p: p.merged_at)

    # 4. For each PR, collect:
    for pr in prs:
        pr.base_commit = pr.base.sha  # commit BEFORE this PR
        pr.merge_commit = pr.merge_commit_sha
        pr.patch = get_diff(pr)  # full diff
        pr.problem_statement = f"{pr.title}\n\n{pr.body}"
        pr.linked_issue = find_linked_issue(pr)

    return prs
```

**Output**: `{repo}-prs.jsonl` with raw PR data

### Stage II: Attribute-Based Filtering

**Criteria** (same as SWE-bench):
- [x] PR is merged
- [x] PR resolves/links to an issue (or is part of enhancement proposal)
- [x] PR modifies test files (indicates tests were added/updated)

```python
def attribute_filter(pr):
    # Must be merged
    if not pr.merged_at:
        return False

    # Must have test changes
    test_files = [f for f in pr.changed_files if is_test_file(f)]
    if not test_files:
        return False

    # Should link to issue or be part of enhancement
    if not pr.linked_issue and not pr.enhancement_id:
        return False

    return True
```

**Output**: `{repo}-candidates.jsonl` with filtered PRs

### Stage III: Execution-Based Filtering (CRITICAL)

This is where we identify FAIL_TO_PASS and PASS_TO_PASS by **actually running tests**.

```python
def execution_filter(pr, repo_path):
    """
    Run tests before and after patch to identify FAIL_TO_PASS.
    This is the SWE-bench methodology - no shortcuts.
    """

    # 1. Checkout base commit (before PR)
    git_checkout(pr.base_commit)

    # 2. Setup environment for this version
    setup_environment(pr.version)

    # 3. Run tests BEFORE patch
    log_pre = run_tests(repo_path)
    tests_failing_before = parse_failures(log_pre)
    tests_passing_before = parse_passes(log_pre)

    # 4. Apply the PR's patch
    apply_patch(pr.patch)

    # 5. Run tests AFTER patch
    log_post = run_tests(repo_path)
    tests_failing_after = parse_failures(log_post)
    tests_passing_after = parse_passes(log_post)

    # 6. Compute FAIL_TO_PASS and PASS_TO_PASS
    FAIL_TO_PASS = tests_failing_before & tests_passing_after
    PASS_TO_PASS = tests_passing_before & tests_passing_after

    # 7. Filter out if no fail-to-pass tests
    if len(FAIL_TO_PASS) == 0:
        return None  # Not a valid task instance

    return {
        "FAIL_TO_PASS": list(FAIL_TO_PASS),
        "PASS_TO_PASS": list(PASS_TO_PASS),
        "log_pre": log_pre,
        "log_post": log_post
    }
```

**Multi-PR Consideration**:

For PR sequences, PASS_TO_PASS grows with each PR:

```python
def build_sequence_tasks(pr_chain):
    tasks = []
    cumulative_pass_to_pass = set()

    for i, pr in enumerate(pr_chain):
        result = execution_filter(pr)
        if result is None:
            continue  # Skip invalid PRs

        task = {
            "task_id": f"{repo}__{enhancement}-{i+1:03d}",
            "sequence_id": f"{repo}__{enhancement}",
            "sequence_position": i + 1,
            "pr_number": pr.number,
            "base_commit": pr.base_commit,
            "problem_statement": pr.problem_statement,
            "patch": pr.patch,
            "test_patch": extract_test_patch(pr.patch),
            "FAIL_TO_PASS": result["FAIL_TO_PASS"],
            # PASS_TO_PASS includes all previous FAIL_TO_PASS
            "PASS_TO_PASS": list(
                set(result["PASS_TO_PASS"]) | cumulative_pass_to_pass
            ),
            "version": pr.version
        }
        tasks.append(task)

        # Add this PR's FAIL_TO_PASS to cumulative
        cumulative_pass_to_pass.update(result["FAIL_TO_PASS"])

    return tasks
```

---

## Environment Setup (Per Repo)

Following SWE-bench's `harness/constants.py` pattern:

```python
# configs/repo_configs.py

REPO_CONFIGS = {
    "pandas-dev/pandas": {
        "install_cmd": "pip install -e .",
        "test_cmd": "pytest {test_path} -x -v",
        "version_map": {
            "2.0": {"python": "3.10", "deps": ["numpy>=1.23"]},
            "2.1": {"python": "3.11", "deps": ["numpy>=1.24"]},
            "2.2": {"python": "3.11", "deps": ["numpy>=1.26"]},
        },
        "test_parser": "pytest_parser",
    },
    "apache/airflow": {
        "install_cmd": "pip install -e '.[devel]'",
        "test_cmd": "pytest {test_path} -x -v",
        "version_map": {
            "2.7": {"python": "3.10", "deps": []},
            "2.8": {"python": "3.11", "deps": []},
        },
        "test_parser": "pytest_parser",
    },
    "numpy/numpy": {
        "install_cmd": "pip install -e . --no-build-isolation",
        "test_cmd": "python -m pytest {test_path} -x -v",
        "version_map": {
            "1.24": {"python": "3.10", "deps": []},
            "1.25": {"python": "3.11", "deps": []},
            "1.26": {"python": "3.11", "deps": []},
        },
        "test_parser": "pytest_parser",
    },
}
```

---

## Test Result Parsing

SWE-bench uses repo-specific parsers. We need pytest parser:

```python
def pytest_parser(log_output: str) -> dict:
    """
    Parse pytest output to extract test results.

    Returns:
        {
            "passed": ["test_module.py::test_func1", ...],
            "failed": ["test_module.py::test_func2", ...],
            "error": ["test_module.py::test_func3", ...],
        }
    """
    results = {"passed": [], "failed": [], "error": []}

    # Parse pytest output
    # Example: "test_foo.py::test_bar PASSED"
    # Example: "test_foo.py::test_baz FAILED"

    for line in log_output.split("\n"):
        if " PASSED" in line:
            test_name = line.split(" PASSED")[0].strip()
            results["passed"].append(test_name)
        elif " FAILED" in line:
            test_name = line.split(" FAILED")[0].strip()
            results["failed"].append(test_name)
        elif " ERROR" in line:
            test_name = line.split(" ERROR")[0].strip()
            results["error"].append(test_name)

    return results
```

---

## Docker Environment (SWE-bench Style)

SWE-bench uses Docker for reproducibility. We should too:

```dockerfile
# Dockerfile.msb-runner
FROM python:3.11-slim

# Install git and build tools
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Clone repo (will be overwritten per task)
WORKDIR /workspace

# Entry point for test execution
COPY run_tests.py /run_tests.py
ENTRYPOINT ["python", "/run_tests.py"]
```

```python
# run_tests.py (inside container)
import subprocess
import json
import sys

def run_task(task):
    # 1. Checkout base commit
    subprocess.run(["git", "checkout", task["base_commit"]])

    # 2. Install
    subprocess.run(["pip", "install", "-e", "."])

    # 3. Run tests before patch
    result_pre = subprocess.run(
        ["pytest", "-v"] + task["test_files"],
        capture_output=True, text=True
    )

    # 4. Apply patch
    subprocess.run(["git", "apply"], input=task["patch"], text=True)

    # 5. Run tests after patch
    result_post = subprocess.run(
        ["pytest", "-v"] + task["test_files"],
        capture_output=True, text=True
    )

    return {
        "log_pre": result_pre.stdout + result_pre.stderr,
        "log_post": result_post.stdout + result_post.stderr
    }

if __name__ == "__main__":
    task = json.load(sys.stdin)
    result = run_task(task)
    json.dump(result, sys.stdout)
```

---

## Complete Pipeline Script

```python
#!/usr/bin/env python3
"""
MSB Dataset Builder - SWE-bench compliant multi-PR benchmark creation.

Usage:
    python msb_builder.py --repo pandas-dev/pandas --tracker 54792 --enhancement PDEP-14
"""

import argparse
import json
import subprocess
from pathlib import Path

# Stage I: Scrape PR chain
def stage_1_scrape(repo: str, tracker_issue: int) -> list:
    """Collect all PRs from tracker issue."""
    print(f"Stage I: Scraping PRs from {repo}#{tracker_issue}")

    # Use GitHub API to get linked PRs
    prs = github_get_linked_prs(repo, tracker_issue)
    prs = [pr for pr in prs if pr["merged_at"]]
    prs.sort(key=lambda p: p["merged_at"])

    print(f"  Found {len(prs)} merged PRs")
    return prs


# Stage II: Attribute filter
def stage_2_filter(prs: list) -> list:
    """Filter PRs by attributes (must have test changes)."""
    print("Stage II: Attribute filtering")

    filtered = []
    for pr in prs:
        files = pr["changed_files"]
        has_tests = any(is_test_file(f) for f in files)

        if has_tests:
            filtered.append(pr)
        else:
            print(f"  Filtered out PR #{pr['number']} (no test changes)")

    print(f"  {len(filtered)}/{len(prs)} PRs passed filter")
    return filtered


# Stage III: Execution filter (THE CRITICAL PART)
def stage_3_execute(prs: list, repo: str, work_dir: Path) -> list:
    """
    Run tests before/after each PR to identify FAIL_TO_PASS.

    THIS IS THE SWE-BENCH WAY. NO SHORTCUTS.
    """
    print("Stage III: Execution-based filtering")

    tasks = []
    cumulative_f2p = set()  # FAIL_TO_PASS from previous PRs

    for i, pr in enumerate(prs):
        print(f"  Processing PR #{pr['number']} ({i+1}/{len(prs)})")

        # Run in Docker for isolation
        result = run_in_docker(
            repo=repo,
            base_commit=pr["base_commit"],
            patch=pr["patch"],
            version=pr["version"]
        )

        if result is None:
            print(f"    Skipped (execution failed)")
            continue

        # Parse test results
        pre_results = pytest_parser(result["log_pre"])
        post_results = pytest_parser(result["log_post"])

        # Compute FAIL_TO_PASS
        failed_before = set(pre_results["failed"])
        passed_after = set(post_results["passed"])
        fail_to_pass = failed_before & passed_after

        if not fail_to_pass:
            print(f"    Skipped (no fail-to-pass tests)")
            continue

        # Compute PASS_TO_PASS (including previous F2P)
        passed_before = set(pre_results["passed"])
        pass_to_pass = (passed_before & passed_after) | cumulative_f2p

        # Build task instance
        task = {
            "task_id": f"{repo.replace('/', '__')}-{pr['number']}",
            "sequence_id": f"{repo.replace('/', '__')}-{enhancement}",
            "sequence_position": len(tasks) + 1,
            "repo": repo,
            "pr_number": pr["number"],
            "base_commit": pr["base_commit"],
            "problem_statement": pr["problem_statement"],
            "hints_text": pr.get("hints", ""),
            "patch": pr["patch"],
            "test_patch": extract_test_patch(pr["patch"]),
            "FAIL_TO_PASS": sorted(list(fail_to_pass)),
            "PASS_TO_PASS": sorted(list(pass_to_pass)),
            "version": pr["version"],
            "created_at": pr["merged_at"]
        }

        tasks.append(task)
        cumulative_f2p.update(fail_to_pass)

        print(f"    Added: {len(fail_to_pass)} F2P, {len(pass_to_pass)} P2P")

    print(f"  {len(tasks)}/{len(prs)} PRs produced valid tasks")
    return tasks


def run_in_docker(repo, base_commit, patch, version):
    """Run test execution in isolated Docker container."""

    task_input = {
        "repo": repo,
        "base_commit": base_commit,
        "patch": patch,
        "version": version
    }

    result = subprocess.run(
        [
            "docker", "run", "--rm", "-i",
            f"msb-runner:{repo.replace('/', '-')}",
        ],
        input=json.dumps(task_input),
        capture_output=True,
        text=True,
        timeout=600  # 10 min timeout
    )

    if result.returncode != 0:
        return None

    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tracker", type=int, required=True)
    parser.add_argument("--enhancement", required=True)
    parser.add_argument("--output", default="tasks.jsonl")
    args = parser.parse_args()

    # Stage I
    prs = stage_1_scrape(args.repo, args.tracker)

    # Stage II
    prs = stage_2_filter(prs)

    # Stage III
    tasks = stage_3_execute(prs, args.repo, Path("./work"))

    # Update total_in_sequence
    for task in tasks:
        task["total_in_sequence"] = len(tasks)

    # Write output
    with open(args.output, "w") as f:
        for task in tasks:
            f.write(json.dumps(task) + "\n")

    print(f"\nWrote {len(tasks)} tasks to {args.output}")


if __name__ == "__main__":
    main()
```

---

## Final Dataset Schema

```json
{
  "task_id": "pandas-dev__pandas-54533",
  "sequence_id": "pandas-dev__pandas-PDEP14",
  "sequence_position": 1,
  "total_in_sequence": 5,

  "repo": "pandas-dev/pandas",
  "pr_number": 54533,
  "base_commit": "a1b2c3d4e5f6...",

  "problem_statement": "Implement Arrow String Array with NumPy semantics\n\nCreate ArrowStringArrayNumpySemantics...",
  "hints_text": "Consider using StringDtype(storage='pyarrow_numpy')...",

  "patch": "diff --git a/pandas/core/arrays/string_arrow.py...",
  "test_patch": "diff --git a/pandas/tests/arrays/string_/test_string_arrow.py...",

  "FAIL_TO_PASS": [
    "pandas/tests/arrays/string_/test_string_arrow.py::TestArrowStringArrayNumpySemantics::test_nan_semantics",
    "pandas/tests/arrays/string_/test_string_arrow.py::TestArrowStringArrayNumpySemantics::test_dtype"
  ],
  "PASS_TO_PASS": [
    "pandas/tests/arrays/string_/test_string_arrow.py::TestArrowStringArray::test_basic"
  ],

  "version": "2.1.0",
  "environment_setup_commit": "a1b2c3d4e5f6...",
  "created_at": "2023-08-15T10:30:00Z"
}
```

---

## Evaluation (Same as SWE-bench)

```python
def evaluate(task, agent_patch):
    """
    Evaluate agent's patch against task.
    Same as SWE-bench evaluation.
    """

    # 1. Setup Docker environment
    container = setup_container(task["repo"], task["version"])

    # 2. Checkout base commit
    container.run(f"git checkout {task['base_commit']}")

    # 3. Apply agent's patch
    apply_result = container.run("git apply", input=agent_patch)
    if apply_result.returncode != 0:
        return {"resolved": False, "reason": "patch_failed"}

    # 4. Run FAIL_TO_PASS tests
    f2p_result = container.run(f"pytest {' '.join(task['FAIL_TO_PASS'])}")
    f2p_passed = parse_all_passed(f2p_result)

    if not f2p_passed:
        return {"resolved": False, "reason": "fail_to_pass_not_resolved"}

    # 5. Run PASS_TO_PASS tests
    p2p_result = container.run(f"pytest {' '.join(task['PASS_TO_PASS'])}")
    p2p_passed = parse_all_passed(p2p_result)

    if not p2p_passed:
        return {"resolved": False, "reason": "regression"}

    return {"resolved": True}
```

---

## Implementation Order

### Phase 1: Single PR Validation
1. Pick ONE PR from pandas PDEP-14 (#54533)
2. Manually run the execution filter
3. Verify FAIL_TO_PASS tests are correctly identified
4. Confirm evaluation works

### Phase 2: PR Chain
1. Extend to 5 PRs from PDEP-14
2. Verify cumulative PASS_TO_PASS works
3. Build automation

### Phase 3: Scale
1. Process full PDEP-14 (20+ PRs)
2. Add PDEP-7, AIP-10
3. Create full dataset

---

## Key Differences from Original Plan

| Aspect | Original Plan | SWE-bench Compliant |
|--------|---------------|---------------------|
| FAIL_TO_PASS identification | Parse test_patch | **Actually run tests** |
| Environment | Local | **Docker containers** |
| Test discovery | Infer from diff | **Execute and compare** |
| Validation | Check patch applies | **Full test execution** |

---

## References

- [SWE-bench GitHub](https://github.com/SWE-bench/SWE-bench)
- [SWE-bench Paper (ICLR 2024)](https://arxiv.org/abs/2310.06770)
- [SWE-bench Datasets Guide](https://www.swebench.com/SWE-bench/guides/datasets/)
- [SWE-bench Evaluation Guide](https://www.swebench.com/SWE-bench/guides/evaluation/)
