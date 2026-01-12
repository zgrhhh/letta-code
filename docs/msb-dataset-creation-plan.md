# MSB Dataset Creation Plan

SWE-bench compliant pipeline for creating Multi-Session Benchmark datasets.

## Core Principle: Actual Test Execution

**CRITICAL**: FAIL_TO_PASS tests must be identified by actually running pytest, NOT by:
- Parsing diff files
- Reading CI logs
- Inferring from test file names

## Pipeline Overview

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  1. Scrape PRs  │────▶│  2. Run Tests   │────▶│  3. Build JSONL │
│  from Tracker   │     │  in Docker      │     │  Dataset        │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## Step 1: Scrape PRs from Tracker Issue

### Input
- Repository: `pandas-dev/pandas`
- Tracker Issue: `#54792` (PDEP-14)

### Process
1. Use GitHub API to fetch tracker issue
2. Extract all PR references from issue body and timeline
3. For each merged PR, fetch:
   - `base_sha`: The commit BEFORE the PR was merged
   - `patch`: The full diff of the PR
   - `test_files_changed`: Test files modified in the PR

### Output
```python
PRInfo(
    number=54533,
    base_sha="abc123...",
    patch="diff --git a/pandas/...",
    test_files_changed=["pandas/tests/arrays/string_/test_string_arrow.py"]
)
```

## Step 2: Run Tests in Docker

### Environment
Use official pandas Docker setup or equivalent:
```dockerfile
FROM python:3.11
RUN pip install pandas[dev] pytest hypothesis pyarrow
```

### Process for Each PR

#### 2.1 Checkout Base Commit (BEFORE patch)
```bash
git checkout <base_sha>
pip install -e . --no-build-isolation
```

#### 2.2 Run Tests BEFORE Patch
```bash
pytest <test_files_changed> --tb=short -v
```
Record which tests PASS and which FAIL.

#### 2.3 Apply Patch
```bash
git apply patch.diff
```

#### 2.4 Run Tests AFTER Patch
```bash
pytest <test_files_changed> --tb=short -v
```
Record which tests PASS and which FAIL.

#### 2.5 Compute FAIL_TO_PASS and PASS_TO_PASS
```python
# Tests that failed BEFORE but pass AFTER = FAIL_TO_PASS
FAIL_TO_PASS = before_failed & after_passed

# Tests that passed BEFORE and AFTER = PASS_TO_PASS
PASS_TO_PASS = before_passed & after_passed
```

### Critical Validation

A valid SWE-bench instance MUST have:
1. At least 1 test in FAIL_TO_PASS (otherwise, what is the patch fixing/implementing?)
2. PASS_TO_PASS tests should not break (regression protection)

If FAIL_TO_PASS is empty:
- The PR might not include test changes
- The tests might already pass on base commit (test was added in different PR)
- The PR might be pure refactoring

## Step 3: Build SWE-bench Compatible JSONL

### Schema (per SWE-bench spec)

```json
{
  "instance_id": "pandas__pandas-PDEP14-001",
  "repo": "pandas-dev/pandas",
  "base_commit": "abc123...",
  "problem_statement": "Implement Arrow String Array with NumPy semantics...",
  "hints_text": "",
  "patch": "diff --git a/pandas/core/arrays/string_arrow.py ...",
  "test_patch": "diff --git a/pandas/tests/arrays/string_/test_string_arrow.py ...",
  "FAIL_TO_PASS": "[\"pandas/tests/arrays/string_/test_string_arrow.py::test_numpy_semantics\"]",
  "PASS_TO_PASS": "[\"pandas/tests/arrays/string_/test_string_arrow.py::test_existing_functionality\"]",
  "created": "2024-01-08T12:00:00Z",
  "version": "1.0.0"
}
```

### MSB Extensions

Additional fields for multi-session benchmarking:
```json
{
  "msb_task_id": "pandas__pandas-PDEP14",
  "msb_sequence_number": 1,
  "msb_total_sessions": 5,
  "msb_depends_on": "[]",
  "msb_enhancement_id": "PDEP-14"
}
```

## Validation with Single PR

Before processing entire tracker, validate pipeline with ONE PR:

### Validation PR: pandas #54533

This is the first PR of PDEP-14 (ArrowStringArrayNumpySemantics implementation).

#### Expected Results
- Base commit: Parent of merge commit
- Test files: `pandas/tests/arrays/string_/test_string_arrow.py`
- FAIL_TO_PASS: Should include new tests for ArrowStringArrayNumpySemantics
- PASS_TO_PASS: Should include existing string array tests

#### Validation Checklist
- [ ] PR scraped successfully
- [ ] Base commit checked out
- [ ] Tests run BEFORE patch (some should fail)
- [ ] Patch applied cleanly
- [ ] Tests run AFTER patch (previously failing now pass)
- [ ] FAIL_TO_PASS correctly identified
- [ ] JSONL output matches SWE-bench schema

## Scaling to Full Tracker

After single PR validation:

1. Process all merged PRs from tracker #54792
2. Order by merge date (creates session sequence)
3. Build dependency graph from PR cross-references
4. Generate multi-session JSONL dataset

## Error Handling

### Common Issues

1. **Patch doesn't apply**: Base commit might be wrong
2. **Tests timeout**: Increase Docker timeout, use subset of tests
3. **Missing dependencies**: Update Docker image with required packages
4. **Flaky tests**: Run tests multiple times, use median result

### Retry Strategy

```python
MAX_RETRIES = 3
for attempt in range(MAX_RETRIES):
    try:
        result = run_tests(test_files)
        break
    except TimeoutError:
        if attempt == MAX_RETRIES - 1:
            raise
        timeout *= 2  # Exponential backoff
```

## Usage

```bash
# Validate with single PR
python main.py single-pr pandas-dev pandas 54533

# Build full dataset from tracker
python main.py tracker pandas-dev pandas 54792 --enhancement-id PDEP-14
```
