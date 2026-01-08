# MSB Dataset Creation Plan

## Objective

Create a runnable multi-PR benchmark dataset that can be evaluated like SWE-bench.

**Scope**: Dataset creation only. Memory metrics come later.

## Core Principle

Each PR in a multi-PR sequence = one evaluation task

```
Sequence: PR1 → PR2 → PR3 → PR4

Evaluation:
  Task 1: Can agent solve PR1? (pass/fail)
  Task 2: Can agent solve PR2? (pass/fail)
  Task 3: Can agent solve PR3? (pass/fail)
  Task 4: Can agent solve PR4? (pass/fail)

Metrics:
  - Per-task pass rate
  - Sequence completion rate (all tasks in sequence pass)
```

## Dataset Schema (Minimal Viable)

```json
{
  "task_id": "pandas__pandas-PDEP14-001",
  "sequence_id": "pandas__pandas-PDEP14",
  "sequence_position": 1,
  "total_in_sequence": 5,

  "repo": "pandas-dev/pandas",
  "pr_number": 54533,
  "base_commit": "abc123def456...",

  "problem_statement": "Issue title and description...",
  "hints_text": "Optional hints from PR discussion...",

  "patch": "diff --git a/...",
  "test_patch": "diff --git a/pandas/tests/...",

  "FAIL_TO_PASS": ["pandas/tests/arrays/string_/test_string_arrow.py::TestArrowStringArray::test_numpy_semantics"],
  "PASS_TO_PASS": ["pandas/tests/arrays/string_/test_string.py::TestStringArray::test_basic"],

  "version": "2.1.0",
  "environment_setup_commit": "abc123def456..."
}
```

## Data Collection Pipeline

### Phase 1: Identify Multi-PR Sequences

**Input**: TIER 1 repos + tracker issues
**Output**: List of (repo, tracker_issue, enhancement_id)

```python
TARGETS = [
    # pandas
    ("pandas-dev/pandas", 54792, "PDEP-14"),  # String dtype - 20+ PRs
    ("pandas-dev/pandas", 49473, "PDEP-7"),   # Copy-on-Write - 50+ PRs
    ("pandas-dev/pandas", 63207, "PDEP-8"),   # Inplace deprecation

    # airflow
    ("apache/airflow", None, "AIP-10"),       # Multi-stage Docker - 3 PRs

    # numpy
    ("numpy/numpy", None, "NEP-49"),          # Data allocation
]
```

### Phase 2: Extract PR Chain

For each tracker issue:

1. **Find linked PRs**
   ```python
   # From issue timeline (cross-references)
   # From issue body (PR mentions like #12345)
   # From labels/milestones
   ```

2. **Filter to merged PRs only**
   ```python
   prs = [pr for pr in linked_prs if pr.merged_at is not None]
   ```

3. **Sort by merge date**
   ```python
   prs.sort(key=lambda p: p.merged_at)
   ```

4. **Get PR details**
   ```python
   for pr in prs:
       pr.base_commit = get_base_commit(pr)
       pr.patch = get_diff(pr, exclude_tests=True)
       pr.test_patch = get_diff(pr, only_tests=True)
       pr.files = get_changed_files(pr)
   ```

### Phase 3: Extract Problem Statement

For each PR:

```python
def get_problem_statement(pr):
    parts = []

    # PR title (usually descriptive)
    parts.append(f"# {pr.title}")

    # PR body (implementation details)
    if pr.body:
        parts.append(pr.body)

    # Linked issue if exists
    linked_issue = find_linked_issue(pr)
    if linked_issue:
        parts.append(f"## Related Issue\n{linked_issue.body}")

    return "\n\n".join(parts)
```

### Phase 4: Identify FAIL_TO_PASS Tests

**Strategy 1: Extract from test_patch (Primary)**

```python
def extract_new_tests(test_patch):
    """Find test functions added in the patch."""
    tests = []

    # Parse diff to find added test functions
    for hunk in parse_diff(test_patch):
        if hunk.is_addition:
            # Match: def test_xxx( or async def test_xxx(
            matches = re.findall(r'def (test_\w+)\(', hunk.content)
            for match in matches:
                test_path = f"{hunk.file}::{match}"
                tests.append(test_path)

    return tests
```

**Strategy 2: Parse CI logs (If available)**

```python
def get_tests_from_ci(pr):
    """Get test names from GitHub Actions / CI logs."""
    # GitHub API: GET /repos/{owner}/{repo}/actions/runs
    # Find run for PR, parse test output
    pass
```

**Strategy 3: Infer from modified test files**

```python
def infer_affected_tests(test_patch):
    """If a test file is modified, all tests in it might be affected."""
    affected_files = extract_modified_files(test_patch)
    return [f"{f}::*" for f in affected_files if '/test' in f]
```

### Phase 5: Identify PASS_TO_PASS Tests

```python
def get_pass_to_pass(pr, sequence_position, previous_prs):
    """Tests that should continue passing."""

    if sequence_position == 1:
        # First PR: use existing tests in affected modules
        return get_existing_tests_for_modules(pr.affected_modules)
    else:
        # Later PRs: include FAIL_TO_PASS from previous PRs
        pass_to_pass = []
        for prev_pr in previous_prs:
            pass_to_pass.extend(prev_pr.FAIL_TO_PASS)
        return pass_to_pass
```

### Phase 6: Validate Dataset

For each task, verify:

```python
def validate_task(task):
    errors = []

    # 1. Can checkout base_commit?
    result = run(f"git checkout {task.base_commit}")
    if result.returncode != 0:
        errors.append(f"Cannot checkout {task.base_commit}")

    # 2. Can apply patch?
    result = run(f"git apply --check", input=task.patch)
    if result.returncode != 0:
        errors.append(f"Patch does not apply cleanly")

    # 3. Do FAIL_TO_PASS tests exist?
    for test in task.FAIL_TO_PASS:
        if not test_exists(test):
            errors.append(f"Test not found: {test}")

    # 4. Do FAIL_TO_PASS tests actually fail before patch?
    # (This requires running tests - expensive but important)

    return errors
```

## Implementation Plan

### Step 1: Basic Data Collector
```
Input: repo, tracker_issue
Output: List of PRs with basic info
```

### Step 2: Patch Extractor
```
Input: PR number
Output: code_patch, test_patch, base_commit
```

### Step 3: Test Identifier
```
Input: test_patch
Output: FAIL_TO_PASS test names
```

### Step 4: Dataset Assembler
```
Input: All above
Output: JSONL file with complete tasks
```

### Step 5: Validator
```
Input: JSONL dataset
Output: Validation report (which tasks are runnable)
```

## Starting Point: One Complete Example

Before scaling, create ONE fully validated task:

**Target**: pandas PDEP-14, first PR (#54533)

```json
{
  "task_id": "pandas__pandas-PDEP14-001",
  "sequence_id": "pandas__pandas-PDEP14",
  "repo": "pandas-dev/pandas",
  "pr_number": 54533,
  "base_commit": "???",
  "problem_statement": "Implement Arrow String Array with NumPy semantics...",
  "patch": "...",
  "test_patch": "...",
  "FAIL_TO_PASS": ["???"],
  "PASS_TO_PASS": ["???"],
  "version": "2.1.0"
}
```

**Validation checklist:**
- [ ] Can clone pandas repo
- [ ] Can checkout base_commit
- [ ] Can apply patch
- [ ] Can run FAIL_TO_PASS tests (they fail before, pass after)
- [ ] Can run PASS_TO_PASS tests (they pass before and after)

## Evaluation (SWE-bench Style)

```python
def evaluate_task(task, agent_patch):
    """Evaluate a single task."""

    # Setup
    checkout(task.base_commit)
    setup_environment(task.version)

    # Apply agent's patch
    apply_result = apply_patch(agent_patch)
    if not apply_result.success:
        return {"resolved": False, "reason": "patch_failed"}

    # Run FAIL_TO_PASS tests
    f2p_results = run_tests(task.FAIL_TO_PASS)
    if not all(r.passed for r in f2p_results):
        return {"resolved": False, "reason": "fail_to_pass_failed"}

    # Run PASS_TO_PASS tests
    p2p_results = run_tests(task.PASS_TO_PASS)
    if not all(r.passed for r in p2p_results):
        return {"resolved": False, "reason": "regression"}

    return {"resolved": True}


def evaluate_sequence(sequence_tasks, agent_patches):
    """Evaluate a full multi-PR sequence."""

    results = []
    for task, patch in zip(sequence_tasks, agent_patches):
        result = evaluate_task(task, patch)
        results.append(result)

    return {
        "sequence_id": sequence_tasks[0].sequence_id,
        "total_tasks": len(sequence_tasks),
        "resolved_tasks": sum(1 for r in results if r["resolved"]),
        "fully_completed": all(r["resolved"] for r in results),
        "per_task_results": results
    }
```

## Metrics

| Metric | Formula |
|--------|---------|
| Task Pass Rate | resolved_tasks / total_tasks |
| Sequence Completion Rate | sequences_fully_completed / total_sequences |
| Position-wise Pass Rate | pass_rate at position N across all sequences |

## Directory Structure

```
msb-benchmark/
├── data/
│   ├── raw/                    # Raw GitHub data
│   │   ├── pandas-PDEP14/
│   │   │   ├── pr_54533.json
│   │   │   ├── pr_54585.json
│   │   │   └── ...
│   │   └── airflow-AIP10/
│   │       └── ...
│   ├── processed/              # Processed tasks
│   │   └── tasks.jsonl
│   └── validated/              # Validated subset
│       └── tasks_validated.jsonl
├── scripts/
│   ├── collect.ts              # Data collection
│   ├── process.ts              # Processing
│   ├── validate.ts             # Validation
│   └── evaluate.ts             # Evaluation harness
└── configs/
    └── targets.json            # Target repos/trackers
```

## Next Steps for Implementation

1. **Update `msb-data-collector.ts`** to output this schema
2. **Create `msb-validator.ts`** to check if tasks are runnable
3. **Test on ONE PR** from pandas PDEP-14 end-to-end
4. **Scale** to full sequences once validated

## What NOT to Do Yet

- Memory metrics (later phase)
- Forcing multi-session behavior (not our concern)
- Complex dependency resolution (keep it simple)
- Cross-repo tasks (start with single repo)
