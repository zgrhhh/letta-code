# Multi-Session Benchmark (MSB) Design

A benchmark for evaluating LLM agents on multi-PR, cross-session software engineering tasks, inspired by SWE-bench but designed specifically for testing persistent memory and incremental implementation capabilities like those in Letta Code.

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Design Philosophy](#design-philosophy)
3. [Schema Specification](#schema-specification)
4. [Task Types](#task-types)
5. [Evaluation Metrics](#evaluation-metrics)
6. [Data Sources](#data-sources)
7. [Data Collection Strategy](#data-collection-strategy)
8. [Example Tasks](#example-tasks)

---

## Executive Summary

### Problem Statement

SWE-bench evaluates single-issue, single-PR tasks. However, real-world software engineering often involves:
- **Multi-PR features** that span days/weeks (e.g., pandas PDEP-14 with 20+ PRs)
- **Incremental implementation** where each PR builds on previous work
- **Cross-session context** where developers remember decisions from past sessions
- **Accumulated knowledge** about project conventions, architecture, and patterns

### Our Solution: Multi-Session Benchmark (MSB)

MSB extends SWE-bench to evaluate:
1. **Cross-session memory**: Can the agent remember what it learned in session 1 when working on session 3?
2. **Incremental implementation**: Can the agent build on its own previous work?
3. **Knowledge accumulation**: Does the agent get better at the project over time?
4. **Coordination**: Can the agent track dependencies between related tasks?

### Key Differentiator: Letta Code Baseline

Unlike session-based tools (Claude Code, Codex, Gemini CLI) where each conversation is independent, Letta Code maintains a **stateful agent** with persistent memory blocks. This benchmark tests exactly these capabilities:

| Capability | Session-based Agents | Letta Code (Memory-first) |
|------------|---------------------|---------------------------|
| Context retention | Per-session only | Persists across sessions |
| Learning | Resets each time | Accumulates over time |
| Project knowledge | Must rediscover | Stored in memory blocks |
| Previous decisions | Lost | Recalled from memory |

---

## Design Philosophy

### 1. Realistic Multi-PR Patterns

Based on our research into TIER 1 repos:

- **pandas PDEPs**: Features implemented across 20+ PRs with TRACKER issues
- **Airflow AIPs**: Explicit multi-step implementation plans (3-10 PRs)
- **NumPy NEPs**: Progressive implementation over multiple PRs

### 2. Session Boundaries

Each "session" represents a distinct interaction where:
- The agent receives a task description
- The agent may (or may not) have access to previous memory
- The agent produces a patch
- The session ends (context would normally be lost)

### 3. Memory Testing Dimensions

| Dimension | What We Test | Example |
|-----------|--------------|---------|
| **Factual recall** | Can agent remember specific decisions? | "In PR1, we decided to use `storage='pyarrow'`" |
| **Pattern recognition** | Can agent apply learned conventions? | "This repo uses `@gen_cluster` for async tests" |
| **Dependency tracking** | Can agent track what depends on what? | "PR3 requires the helper from PR2" |
| **Error learning** | Can agent avoid repeating past mistakes? | "Last time I forgot to run mypy" |

---

## Schema Specification

### Task Instance Schema (JSONL)

```json
{
  // ===== CORE IDENTIFIERS =====
  "task_id": "pandas__pandas-PDEP14-string-dtype",
  "repo": "pandas-dev/pandas",
  "enhancement_id": "PDEP-14",  // PDEP, AIP, NEP, or issue number
  "tracker_issue": 54792,       // GitHub issue tracking the full implementation

  // ===== MULTI-SESSION STRUCTURE =====
  "sessions": [
    {
      "session_id": "pandas__pandas-PDEP14-001",
      "sequence_number": 1,
      "pr_number": 54533,
      "base_commit": "abc123...",

      // Task description (what the agent sees)
      "problem_statement": "Implement Arrow String Array compatible with NumPy semantics...",
      "hints_text": "Consider using StringDtype(storage='pyarrow_numpy')...",

      // Gold solution (for evaluation)
      "patch": "diff --git a/pandas/core/...",
      "test_patch": "diff --git a/pandas/tests/...",

      // Test specification
      "FAIL_TO_PASS": ["test_arrow_string_numpy_semantics"],
      "PASS_TO_PASS": ["test_existing_string_functionality"],

      // Memory expectations (what should be learned)
      "expected_memory_updates": {
        "project": ["Arrow StringArray uses storage='pyarrow_numpy'"],
        "persona": ["Run tests with PANDAS_COPY_ON_WRITE=1"]
      },

      // Dependencies
      "depends_on": [],  // First session has no dependencies
      "provides": ["ArrowStringArrayNumpySemantics class"]
    },
    {
      "session_id": "pandas__pandas-PDEP14-002",
      "sequence_number": 2,
      "pr_number": 54585,
      "base_commit": "def456...",  // After PR1 merged

      "problem_statement": "Configure NaN as na_value for pyarrow_numpy StringDtype...",
      "hints_text": "",  // Less hints in later sessions - agent should remember

      "patch": "diff --git a/pandas/core/...",
      "test_patch": "diff --git a/pandas/tests/...",

      "FAIL_TO_PASS": ["test_nan_as_na_value"],
      "PASS_TO_PASS": ["test_arrow_string_numpy_semantics"],  // PR1's test

      // Memory recall requirements (what should be remembered from PR1)
      "required_memory_recall": [
        "ArrowStringArrayNumpySemantics uses storage='pyarrow_numpy'"
      ],

      "expected_memory_updates": {
        "project": ["pyarrow_numpy variant uses np.nan for missing values"]
      },

      "depends_on": ["pandas__pandas-PDEP14-001"],
      "provides": ["NaN semantics for pyarrow strings"]
    }
    // ... more sessions
  ],

  // ===== TASK METADATA =====
  "total_sessions": 5,
  "difficulty": "hard",
  "estimated_complexity": {
    "files_touched": 15,
    "total_lines_changed": 500,
    "cross_file_dependencies": 8
  },

  // ===== MEMORY EVALUATION CONFIG =====
  "memory_evaluation": {
    "test_recall_at_sessions": [3, 5],  // Test memory at session 3 and 5
    "critical_facts": [
      "storage='pyarrow_numpy' is the new default",
      "np.nan used for missing values",
      "Tests run with PANDAS_COPY_ON_WRITE=1"
    ],
    "pattern_tests": [
      {
        "pattern": "Adding methods to StringDtype",
        "expected_consistency": "Use _wrap_reduction_result pattern"
      }
    ]
  }
}
```

### Prediction Schema (JSONL)

```json
{
  "task_id": "pandas__pandas-PDEP14-string-dtype",
  "session_id": "pandas__pandas-PDEP14-002",
  "model_name_or_path": "letta-code-v1",

  // The generated patch
  "model_patch": "diff --git a/pandas/core/...",

  // Memory state after session (for memory evaluation)
  "memory_state": {
    "project": "Current project memory block content...",
    "persona": "Current persona memory block content...",
    "human": "Current human preference memory..."
  },

  // Optional: reasoning trace
  "reasoning": "Based on my memory from session 1, I know that..."
}
```

---

## Task Types

### Type 1: Sequential Implementation (Linear Chain)

**Pattern**: PR1 → PR2 → PR3 → PR4

**Example**: Airflow AIP-10 Multi-stage Docker
```
Session 1: Create multi-stage Dockerfile (AIRFLOW-4115)
Session 2: Add CI/Main image variants (AIRFLOW-4116)  [depends on 1]
Session 3: Integrate with Travis CI (AIRFLOW-4117)    [depends on 2]
```

**Memory Test**: Session 3 requires understanding the Dockerfile structure from Session 1.

### Type 2: Parallel Implementation (Tracker Pattern)

**Pattern**: One tracker issue, many independent PRs

**Example**: pandas PDEP-7 Copy-on-Write Methods
```
Session 1: Implement CoW for `head`/`tail` (#49963)
Session 2: Implement CoW for `drop` (#49689)
Session 3: Implement CoW for `fillna` (#51279)
...
Session N: Implement CoW for `transform` (#53747)
```

**Memory Test**: Each session should apply the same pattern (`copy(deep=None)`, test with `using_copy_on_write` fixture). Agent should learn pattern from session 1 and apply consistently.

### Type 3: Refactoring Chain (Breaking Change)

**Pattern**: Implement → Deprecate → Migrate → Remove

**Example**: pandas PDEP-14 Storage Option Renaming
```
Session 1: Implement pyarrow_numpy variant (#54533)
Session 2: Add na_value keyword, plan rename (#59330)
Session 3: Deprecate old naming (#60152)
Session 4: Update all usages (#59758)
Session 5: Remove deprecated code (#59376)
```

**Memory Test**: Agent must track the rename across sessions and remember migration status.

### Type 4: Cross-Component Feature

**Pattern**: Changes span multiple subsystems

**Example**: NumPy NEP 49 Data Allocation
```
Session 1: Design C-API changes (historical PR #390)
Session 2: Implement handler struct (PR #17582 part 1)
Session 3: Add Python bindings (PR #17582 part 2)
Session 4: Document and test (follow-up)
```

**Memory Test**: Agent must maintain mental model of how C and Python layers interact.

---

## Evaluation Metrics

### 1. Task Resolution (from SWE-bench)

| Metric | Description |
|--------|-------------|
| **Resolve Rate** | % of sessions where patch passes FAIL_TO_PASS tests |
| **Regression Rate** | % of sessions where PASS_TO_PASS tests break |
| **Sequence Completion** | % of full task sequences completed |

### 2. Memory Metrics (MSB-specific)

| Metric | Description |
|--------|-------------|
| **Recall Accuracy** | Can agent answer questions about previous sessions? |
| **Pattern Consistency** | Does agent apply learned patterns consistently? |
| **Dependency Awareness** | Does agent correctly identify what it needs from prior work? |
| **Memory Efficiency** | Is memory block content relevant and concise? |

### 3. Incremental Learning Score

```python
def incremental_learning_score(task_results):
    """
    Measures if agent improves over the course of a task.

    A score > 1.0 means agent gets better over sessions.
    A score < 1.0 means agent degrades (forgetting).
    """
    early_sessions = task_results[:len(task_results)//2]
    late_sessions = task_results[len(task_results)//2:]

    early_success = sum(s.resolved for s in early_sessions) / len(early_sessions)
    late_success = sum(s.resolved for s in late_sessions) / len(late_sessions)

    return late_success / early_success if early_success > 0 else late_success
```

### 4. Cross-Session Coherence Score

```python
def coherence_score(session_patches):
    """
    Measures if patches are consistent with each other.

    Checks:
    - Naming conventions match across sessions
    - Code style is consistent
    - No contradictory changes
    """
    # Implementation would analyze patches for consistency
    pass
```

### 5. Evaluation Protocol

```
For each task T with sessions [S1, S2, ..., Sn]:

  For session Si in [S1, S2, ..., Sn]:
    1. SETUP: Checkout base_commit, apply patches from S1..S(i-1)

    2. MEMORY INJECTION (for memory-first agents):
       - Provide memory state from previous sessions
       - For baseline agents: provide summary prompt

    3. TASK EXECUTION:
       - Present problem_statement
       - Agent generates patch
       - Record memory updates

    4. EVALUATION:
       - Apply agent patch
       - Run FAIL_TO_PASS tests (must pass)
       - Run PASS_TO_PASS tests (must pass)
       - Check memory recall questions

    5. MEMORY TEST (at designated sessions):
       - Ask recall questions about previous sessions
       - Score factual accuracy
       - Assess pattern recognition

Final Scores:
  - Task Resolution: % sessions resolved
  - Memory Recall: % recall questions correct
  - Learning Curve: Incremental learning score
  - Coherence: Cross-session coherence score
```

---

## Data Sources

### Primary Sources (TIER 1)

| Repository | Enhancement System | Multi-PR Pattern | Example Tasks |
|------------|-------------------|------------------|---------------|
| [pandas-dev/pandas](https://github.com/pandas-dev/pandas) | PDEPs + TRACKER | 20-50 PRs per feature | PDEP-7 (50+ PRs), PDEP-14 (20+ PRs), PDEP-8 |
| [apache/airflow](https://github.com/apache/airflow) | AIPs | 3-10 explicit steps | AIP-10, AIP-7, AIP-67 |
| [numpy/numpy](https://github.com/numpy/numpy) | NEPs | Progressive implementation | NEP-49, NEP-51, NEP-47 |

### Multi-PR Evidence

#### pandas
- **PDEP-14 String Dtype** ([#54792](https://github.com/pandas-dev/pandas/issues/54792)): 20+ PRs
  - Main implementation: #54533, #54585, #54720, #54591
  - Refactoring: #59330, #59758, #60152
  - Testing: #58459, #59329, #59437

- **PDEP-7 Copy-on-Write** ([#49473](https://github.com/pandas-dev/pandas/issues/49473)): 50+ PRs
  - Each method gets its own PR
  - Consistent pattern: lazy copy with `copy(deep=None)`

#### Airflow
- **AIP-10 Multi-stage Docker**: 3 sequential PRs
  - AIRFLOW-4115 (#4936): Foundation
  - AIRFLOW-4116 (#4937): CI variants
  - AIRFLOW-4117 (#4938): Travis integration

#### NumPy
- **NEP-49 Data Allocation**: Multiple PRs over years
  - Historical: #5457, #5470, #390
  - Main: #17582

---

## Data Collection Strategy

### Phase 1: Identify Multi-PR Tasks

```python
# Pseudocode for mining multi-PR tasks

def find_tracker_issues(repo):
    """Find issues labeled as TRACKER or referencing PDEPs/AIPs/NEPs."""
    issues = github.search_issues(
        repo=repo,
        labels=["TRACKER", "High level tracker"],
        body_contains=["PDEP", "AIP", "NEP"]
    )
    return issues

def extract_pr_sequence(tracker_issue):
    """Extract ordered sequence of PRs from tracker issue."""
    prs = []
    for reference in tracker_issue.timeline:
        if reference.type == "cross-reference" and reference.is_pr:
            prs.append({
                "pr_number": reference.pr_number,
                "merged_at": reference.merged_at,
                "depends_on": extract_dependencies(reference)
            })
    return sorted(prs, key=lambda p: p["merged_at"])
```

### Phase 2: Build Session Sequences

```python
def build_session_sequence(pr_chain):
    """Convert PR chain to session sequence."""
    sessions = []
    cumulative_state = {}

    for i, pr in enumerate(pr_chain):
        session = {
            "session_id": f"{repo}-{tracker}-{i+1:03d}",
            "sequence_number": i + 1,
            "pr_number": pr["pr_number"],
            "base_commit": get_base_commit(pr),
            "problem_statement": extract_problem_statement(pr),
            "patch": extract_code_patch(pr),
            "test_patch": extract_test_patch(pr),
            "depends_on": [s["session_id"] for s in sessions
                          if s["pr_number"] in pr["depends_on"]],
            "expected_memory_updates": infer_memory_updates(pr, cumulative_state)
        }

        # Update cumulative state
        cumulative_state.update(analyze_changes(pr))
        sessions.append(session)

    return sessions
```

### Phase 3: Generate Memory Tests

```python
def generate_memory_tests(sessions):
    """Generate memory recall questions for each session."""
    for i, session in enumerate(sessions):
        if i == 0:
            continue  # First session has nothing to recall

        # Factual recall questions
        session["memory_recall_questions"] = []
        for prev in sessions[:i]:
            questions = generate_factual_questions(prev)
            session["memory_recall_questions"].extend(questions)

        # Pattern recognition tests
        if i >= 2:
            session["pattern_tests"] = detect_patterns(sessions[:i])
```

### Phase 4: Validation

```python
def validate_task(task):
    """Ensure task is solvable and well-formed."""
    checks = [
        # Each session can be checked out independently
        all(can_checkout(s["base_commit"]) for s in task["sessions"]),

        # Tests are deterministic
        all(tests_are_stable(s) for s in task["sessions"]),

        # Dependencies are acyclic
        is_dag(task["sessions"], key=lambda s: s["depends_on"]),

        # Patches apply cleanly in sequence
        patches_apply_sequentially(task["sessions"])
    ]
    return all(checks)
```

---

## Example Tasks

### Example 1: pandas PDEP-14 String Dtype (Type 3: Refactoring Chain)

```json
{
  "task_id": "pandas__pandas-PDEP14-string-dtype",
  "repo": "pandas-dev/pandas",
  "enhancement_id": "PDEP-14",
  "tracker_issue": 54792,
  "total_sessions": 5,
  "difficulty": "hard",

  "sessions": [
    {
      "session_id": "pandas__pandas-PDEP14-001",
      "sequence_number": 1,
      "pr_number": 54533,
      "problem_statement": "Implement an Arrow-backed String Array that is compatible with NumPy semantics. The new StringDtype variant should use storage='pyarrow_numpy' and return np.nan for missing values instead of pd.NA. This maintains backwards compatibility for users who expect NaN behavior.",
      "hints_text": "Look at ArrowStringArray implementation. Consider creating ArrowStringArrayNumpySemantics class that inherits from ArrowExtensionArray.",
      "FAIL_TO_PASS": ["pandas/tests/arrays/string_/test_string_arrow.py::test_numpy_semantics_nan"],
      "depends_on": [],
      "provides": ["ArrowStringArrayNumpySemantics class", "StringDtype(storage='pyarrow_numpy')"],
      "expected_memory_updates": {
        "project": ["String dtype has two variants: pyarrow (pd.NA) and pyarrow_numpy (np.nan)", "New ArrowStringArrayNumpySemantics in pandas/core/arrays/string_arrow.py"]
      }
    },
    {
      "session_id": "pandas__pandas-PDEP14-002",
      "sequence_number": 2,
      "pr_number": 54585,
      "problem_statement": "Configure NaN as the default na_value for the pyarrow_numpy StringDtype variant. Ensure missing values are represented as np.nan consistently throughout operations.",
      "hints_text": "",
      "FAIL_TO_PASS": ["pandas/tests/arrays/string_/test_string_arrow.py::test_na_value_is_nan"],
      "depends_on": ["pandas__pandas-PDEP14-001"],
      "provides": ["np.nan as na_value for pyarrow_numpy"],
      "required_memory_recall": ["ArrowStringArrayNumpySemantics uses storage='pyarrow_numpy'"],
      "expected_memory_updates": {
        "project": ["pyarrow_numpy StringDtype uses np.nan as na_value, not pd.NA"]
      }
    },
    {
      "session_id": "pandas__pandas-PDEP14-003",
      "sequence_number": 3,
      "pr_number": 59330,
      "problem_statement": "Refactor the storage option naming. Change from storage='pyarrow_numpy' to storage='pyarrow' with na_value=np.nan keyword argument. This provides a cleaner API for users.",
      "hints_text": "",
      "FAIL_TO_PASS": ["pandas/tests/arrays/string_/test_string_dtype.py::test_new_storage_api"],
      "depends_on": ["pandas__pandas-PDEP14-001", "pandas__pandas-PDEP14-002"],
      "provides": ["New StringDtype API: storage='pyarrow', na_value=np.nan"],
      "required_memory_recall": [
        "Current API uses storage='pyarrow_numpy'",
        "na_value is np.nan for numpy semantics variant"
      ],
      "expected_memory_updates": {
        "project": ["StringDtype API changed: storage='pyarrow' + na_value keyword replaces storage='pyarrow_numpy'"]
      }
    }
  ],

  "memory_evaluation": {
    "test_recall_at_sessions": [3, 5],
    "critical_facts": [
      "pyarrow_numpy uses np.nan for missing values",
      "API transitioned from storage='pyarrow_numpy' to storage='pyarrow' + na_value",
      "ArrowStringArrayNumpySemantics is the backing array class"
    ]
  }
}
```

### Example 2: pandas PDEP-7 Copy-on-Write (Type 2: Parallel Pattern)

```json
{
  "task_id": "pandas__pandas-PDEP7-cow-methods",
  "repo": "pandas-dev/pandas",
  "enhancement_id": "PDEP-7",
  "tracker_issue": 49473,
  "total_sessions": 10,
  "difficulty": "medium",

  "pattern_to_learn": {
    "description": "Add Copy-on-Write lazy copy optimization to DataFrame/Series methods",
    "steps": [
      "1. Update method to use copy(deep=None) for lazy copy",
      "2. Add test in pandas/tests/copy_view/test_methods.py",
      "3. Test with PANDAS_COPY_ON_WRITE=1 environment variable",
      "4. Use using_copy_on_write fixture for conditional tests"
    ]
  },

  "sessions": [
    {
      "session_id": "pandas__pandas-PDEP7-001",
      "sequence_number": 1,
      "pr_number": 49963,
      "problem_statement": "Add Copy-on-Write optimization to DataFrame.head() and DataFrame.tail() methods. These should use lazy copy semantics when CoW is enabled.",
      "hints_text": "Use copy(deep=None) to trigger lazy copy. Add tests in pandas/tests/copy_view/test_methods.py. Run with PANDAS_COPY_ON_WRITE=1.",
      "FAIL_TO_PASS": ["pandas/tests/copy_view/test_methods.py::test_head_cow", "pandas/tests/copy_view/test_methods.py::test_tail_cow"],
      "depends_on": [],
      "expected_memory_updates": {
        "project": ["CoW pattern: use copy(deep=None) for lazy copy", "CoW tests go in pandas/tests/copy_view/test_methods.py", "Run CoW tests with PANDAS_COPY_ON_WRITE=1"],
        "persona": ["When implementing CoW for a method: 1) copy(deep=None), 2) test in test_methods.py, 3) use using_copy_on_write fixture"]
      }
    },
    {
      "session_id": "pandas__pandas-PDEP7-002",
      "sequence_number": 2,
      "pr_number": 49689,
      "problem_statement": "Add Copy-on-Write optimization to DataFrame.drop() method.",
      "hints_text": "",
      "FAIL_TO_PASS": ["pandas/tests/copy_view/test_methods.py::test_drop_cow"],
      "depends_on": [],
      "required_memory_recall": ["CoW uses copy(deep=None)", "Tests in test_methods.py"],
      "pattern_consistency_test": {
        "must_use": ["copy(deep=None)"],
        "must_test_in": ["pandas/tests/copy_view/test_methods.py"]
      }
    },
    {
      "session_id": "pandas__pandas-PDEP7-003",
      "sequence_number": 3,
      "pr_number": 50429,
      "problem_statement": "Add Copy-on-Write optimization to DataFrame.dropna() method.",
      "hints_text": "",
      "FAIL_TO_PASS": ["pandas/tests/copy_view/test_methods.py::test_dropna_cow"],
      "depends_on": [],
      "required_memory_recall": ["CoW pattern from sessions 1-2"],
      "pattern_consistency_test": {
        "must_use": ["copy(deep=None)"],
        "must_follow_pattern": true
      }
    }
    // ... sessions 4-10 for other methods
  ],

  "memory_evaluation": {
    "test_recall_at_sessions": [5, 10],
    "pattern_tests": [
      {
        "question": "What function call triggers lazy copy in CoW implementation?",
        "expected": "copy(deep=None)"
      },
      {
        "question": "Where should CoW tests be placed?",
        "expected": "pandas/tests/copy_view/test_methods.py"
      },
      {
        "question": "What fixture is used for CoW conditional tests?",
        "expected": "using_copy_on_write"
      }
    ]
  }
}
```

### Example 3: Airflow AIP-10 (Type 1: Sequential Chain)

```json
{
  "task_id": "airflow__airflow-AIP10-docker",
  "repo": "apache/airflow",
  "enhancement_id": "AIP-10",
  "tracker_issue": null,
  "total_sessions": 3,
  "difficulty": "medium",

  "sessions": [
    {
      "session_id": "airflow__airflow-AIP10-001",
      "sequence_number": 1,
      "pr_number": 4936,
      "jira_ticket": "AIRFLOW-4115",
      "problem_statement": "Convert the Airflow Dockerfile to use multi-stage builds. The current mono-layered Dockerfile should be restructured to use Docker's multi-stage capabilities while maintaining Python 3.6 compatibility. No functional changes to image behavior.",
      "hints_text": "Use Docker multi-stage builds with FROM ... AS stage_name syntax. Keep the main image functionality identical.",
      "FAIL_TO_PASS": ["tests/docker/test_dockerfile.py::test_multistage_structure"],
      "depends_on": [],
      "provides": ["Multi-stage Dockerfile structure"],
      "expected_memory_updates": {
        "project": ["Dockerfile uses multi-stage builds", "Stages: base, build, main", "Python 3.6 only at this stage"]
      }
    },
    {
      "session_id": "airflow__airflow-AIP10-002",
      "sequence_number": 2,
      "pr_number": 4937,
      "jira_ticket": "AIRFLOW-4116",
      "problem_statement": "Expand the multi-stage Dockerfile to support both primary (slim) and CI (full) image variants. Add a build script that can create either variant from the same Dockerfile.",
      "hints_text": "",
      "FAIL_TO_PASS": ["tests/docker/test_dockerfile.py::test_slim_variant", "tests/docker/test_dockerfile.py::test_ci_variant"],
      "depends_on": ["airflow__airflow-AIP10-001"],
      "provides": ["Slim and Full image variants", "Build script"],
      "required_memory_recall": ["Multi-stage structure from session 1", "Stage names: base, build, main"],
      "expected_memory_updates": {
        "project": ["Two image variants: slim (production) and full (CI)", "Build script handles variant selection"]
      }
    },
    {
      "session_id": "airflow__airflow-AIP10-003",
      "sequence_number": 3,
      "pr_number": 4938,
      "jira_ticket": "AIRFLOW-4117",
      "problem_statement": "Integrate the new multi-stage Docker images into Travis CI. Update CI configuration to use the new image variants instead of the previous incubator-ci image.",
      "hints_text": "",
      "FAIL_TO_PASS": ["tests/ci/test_travis_config.py::test_uses_new_images"],
      "depends_on": ["airflow__airflow-AIP10-001", "airflow__airflow-AIP10-002"],
      "provides": ["Travis CI integration"],
      "required_memory_recall": [
        "Dockerfile has slim and full variants",
        "Build script from session 2"
      ],
      "expected_memory_updates": {
        "project": ["Travis CI uses new multi-stage images", "CI pulls full variant for testing"]
      }
    }
  ],

  "memory_evaluation": {
    "test_recall_at_sessions": [3],
    "critical_facts": [
      "Multi-stage build has stages: base, build, main",
      "Two variants: slim (production), full (CI)",
      "Build script selects variant"
    ]
  }
}
```

---

## Comparison with SWE-bench

| Aspect | SWE-bench | MSB (Ours) |
|--------|-----------|------------|
| Task granularity | Single issue/PR | Multi-PR sequences |
| Sessions | 1 | 2-50+ |
| Memory testing | None | Core feature |
| Dependency tracking | None | Explicit |
| Pattern learning | Not evaluated | Scored |
| Task types | Fix issue | Implement feature |
| Evaluation | Pass tests | Pass tests + memory recall |

---

## Future Extensions

1. **Cross-Repo Tasks**: Tasks spanning dask/dask and dask/distributed
2. **Long-horizon Tasks**: 6+ month feature implementations
3. **Collaborative Tasks**: Multiple agents working on related PRs
4. **Memory Compression**: Evaluate memory efficiency as task grows

---

## References

- [SWE-bench](https://github.com/SWE-bench/SWE-bench) - Original benchmark
- [pandas PDEPs](https://pandas.pydata.org/pdeps/) - Enhancement proposals
- [Airflow AIPs](https://cwiki.apache.org/confluence/display/AIRFLOW/Airflow+Improvement+Proposals) - Airflow proposals
- [NumPy NEPs](https://numpy.org/neps/) - NumPy proposals
- [Letta Code](https://github.com/letta-ai/letta-code) - Memory-first coding harness

## Sources

- [pandas PDEP-14 Tracker Issue #54792](https://github.com/pandas-dev/pandas/issues/54792)
- [pandas PDEP-7 CoW Tracker Issue #49473](https://github.com/pandas-dev/pandas/issues/49473)
- [pandas PDEP-8 Tracker Issue #63207](https://github.com/pandas-dev/pandas/issues/63207)
- [Airflow AIP-10 Multi-stage Docker](https://cwiki.apache.org/confluence/display/AIRFLOW/AIP-10+Multi-layered+and+multi-stage+official+Airflow+CI+image)
- [NumPy NEP-49 Data Allocation](https://numpy.org/neps/nep-0049-data-allocation-strategies.html)
- [SWE-bench Datasets Guide](https://www.swebench.com/SWE-bench/guides/datasets/)
- [SWE-bench on Hugging Face](https://huggingface.co/datasets/SWE-bench/SWE-bench)
