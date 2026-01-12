#!/usr/bin/env python3
"""
MSB Dataset Builder CLI.

Builds SWE-bench compatible datasets for multi-session benchmarking.
Identifies FAIL_TO_PASS tests by actually running pytest in Docker.

Usage:
    # Build from a tracker issue
    python main.py tracker pandas-dev pandas 54792 --enhancement-id PDEP-14

    # Build from a single PR (for validation)
    python main.py single-pr pandas-dev pandas 54533

    # Build with PR limit for testing
    python main.py tracker pandas-dev pandas 54792 --limit 3

Examples:
    # pandas PDEP-14 String Dtype
    python main.py tracker pandas-dev pandas 54792 --enhancement-id PDEP-14

    # pandas PDEP-7 Copy-on-Write
    python main.py tracker pandas-dev pandas 49473 --enhancement-id PDEP-7
"""

import argparse
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.builder import MSBDatasetBuilder, build_single_pr


def cmd_tracker(args):
    """Build dataset from a tracker issue."""
    print(f"MSB Dataset Builder")
    print(f"=" * 60)
    print(f"Repository: {args.owner}/{args.repo}")
    print(f"Tracker Issue: #{args.tracker_issue}")
    print(f"Enhancement ID: {args.enhancement_id}")
    if args.limit:
        print(f"PR Limit: {args.limit}")
    print(f"Output: {args.output}")
    print(f"=" * 60)

    builder = MSBDatasetBuilder(
        owner=args.owner,
        repo=args.repo,
        output_dir=Path(args.output)
    )

    task = builder.build_from_tracker(
        tracker_issue=args.tracker_issue,
        enhancement_id=args.enhancement_id,
        limit=args.limit,
        skip_test_run=args.skip_tests
    )

    # Save outputs
    jsonl_path = builder.save_jsonl(task)
    json_path = builder.save_full_json(task)

    print(f"\n" + "=" * 60)
    print(f"BUILD COMPLETE")
    print(f"=" * 60)
    print(f"Task ID: {task.task_id}")
    print(f"Sessions: {task.total_sessions}")
    print(f"Difficulty: {task.difficulty}")
    print(f"\nOutputs:")
    print(f"  JSONL (SWE-bench): {jsonl_path}")
    print(f"  JSON (Full MSB):   {json_path}")

    # Summary
    total_f2p = sum(len(s.FAIL_TO_PASS) for s in task.sessions)
    total_p2p = sum(len(s.PASS_TO_PASS) for s in task.sessions)
    print(f"\nTest Statistics:")
    print(f"  Total FAIL_TO_PASS: {total_f2p}")
    print(f"  Total PASS_TO_PASS: {total_p2p}")


def cmd_single_pr(args):
    """Build dataset from a single PR for validation."""
    print(f"MSB Dataset Builder - Single PR Mode")
    print(f"=" * 60)
    print(f"Repository: {args.owner}/{args.repo}")
    print(f"PR: #{args.pr_number}")
    print(f"=" * 60)

    session = build_single_pr(
        owner=args.owner,
        repo=args.repo,
        pr_number=args.pr_number,
        output_dir=Path(args.output)
    )

    print(f"\n" + "=" * 60)
    print(f"VALIDATION COMPLETE")
    print(f"=" * 60)
    print(f"Session ID: {session.session_id}")
    print(f"\nTest Identification Results:")
    print(f"  FAIL_TO_PASS ({len(session.FAIL_TO_PASS)}):")
    for test in session.FAIL_TO_PASS[:10]:
        print(f"    - {test}")
    if len(session.FAIL_TO_PASS) > 10:
        print(f"    ... and {len(session.FAIL_TO_PASS) - 10} more")

    print(f"\n  PASS_TO_PASS ({len(session.PASS_TO_PASS)}):")
    for test in session.PASS_TO_PASS[:10]:
        print(f"    - {test}")
    if len(session.PASS_TO_PASS) > 10:
        print(f"    ... and {len(session.PASS_TO_PASS) - 10} more")


def main():
    parser = argparse.ArgumentParser(
        description="MSB Dataset Builder - Build SWE-bench datasets with FAIL_TO_PASS from actual test runs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Tracker command
    tracker_parser = subparsers.add_parser(
        "tracker",
        help="Build dataset from a tracker issue"
    )
    tracker_parser.add_argument("owner", help="Repository owner (e.g., pandas-dev)")
    tracker_parser.add_argument("repo", help="Repository name (e.g., pandas)")
    tracker_parser.add_argument("tracker_issue", type=int, help="Tracker issue number")
    tracker_parser.add_argument(
        "--enhancement-id", "-e",
        required=True,
        help="Enhancement identifier (e.g., PDEP-14)"
    )
    tracker_parser.add_argument(
        "--limit", "-l",
        type=int,
        help="Limit number of PRs to process"
    )
    tracker_parser.add_argument(
        "--output", "-o",
        default="output",
        help="Output directory (default: output)"
    )
    tracker_parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip running tests (for testing the pipeline)"
    )
    tracker_parser.set_defaults(func=cmd_tracker)

    # Single PR command
    single_parser = subparsers.add_parser(
        "single-pr",
        help="Build dataset from a single PR (for validation)"
    )
    single_parser.add_argument("owner", help="Repository owner")
    single_parser.add_argument("repo", help="Repository name")
    single_parser.add_argument("pr_number", type=int, help="PR number")
    single_parser.add_argument(
        "--output", "-o",
        default="output",
        help="Output directory (default: output)"
    )
    single_parser.set_defaults(func=cmd_single_pr)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
