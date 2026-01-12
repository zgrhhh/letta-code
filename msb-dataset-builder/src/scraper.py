"""
GitHub PR Scraper for MSB Dataset Builder.

Scrapes PRs from tracker issues like pandas PDEP-14 (#54792).
Uses requests library (no gh CLI dependency).
"""

import os
import re
from dataclasses import dataclass
from typing import Optional

import requests


@dataclass
class PRInfo:
    """Information about a pull request."""

    number: int
    title: str
    body: str
    base_sha: str
    head_sha: str
    merge_commit_sha: Optional[str]
    merged_at: Optional[str]
    diff_url: str
    html_url: str
    state: str

    # Extracted from diff
    patch: Optional[str] = None
    test_files_changed: list = None

    def __post_init__(self):
        if self.test_files_changed is None:
            self.test_files_changed = []


class GitHubAPI:
    """GitHub API client using requests."""

    BASE_URL = "https://api.github.com"

    def __init__(self, token: Optional[str] = None):
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.session = requests.Session()
        if self.token:
            self.session.headers["Authorization"] = f"token {self.token}"
        self.session.headers["Accept"] = "application/vnd.github.v3+json"

    def get(self, endpoint: str, params: dict = None) -> dict | list:
        """Make a GET request to the GitHub API."""
        url = f"{self.BASE_URL}{endpoint}"
        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def get_paginated(self, endpoint: str, params: dict = None) -> list:
        """Get all pages of a paginated endpoint."""
        params = params or {}
        params["per_page"] = 100
        results = []

        while True:
            response = self.session.get(f"{self.BASE_URL}{endpoint}", params=params)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, list):
                results.extend(data)
            else:
                results.append(data)

            # Check for next page
            if "next" in response.links:
                url = response.links["next"]["url"]
                params = {}  # URL includes params
                endpoint = url.replace(self.BASE_URL, "")
            else:
                break

        return results

    def get_diff(self, owner: str, repo: str, pr_number: int) -> str:
        """Get the diff for a PR."""
        url = f"{self.BASE_URL}/repos/{owner}/{repo}/pulls/{pr_number}"
        headers = {"Accept": "application/vnd.github.v3.diff"}
        response = self.session.get(url, headers=headers)
        response.raise_for_status()
        return response.text


def get_tracker_issue_prs(
    owner: str,
    repo: str,
    issue_number: int,
    api: GitHubAPI = None
) -> list[int]:
    """
    Extract PR numbers referenced in a tracker issue.

    Looks for:
    - PR links in the issue body
    - Cross-references in the timeline
    """
    api = api or GitHubAPI()

    # Get issue details
    issue = api.get(f"/repos/{owner}/{repo}/issues/{issue_number}")

    pr_numbers = set()

    # Extract PR numbers from issue body
    body = issue.get("body", "") or ""

    # Pattern: #12345 or owner/repo#12345 or full URLs
    patterns = [
        rf"https://github\.com/{owner}/{repo}/pull/(\d+)",
        rf"{owner}/{repo}#(\d+)",
        r"#(\d+)",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, body)
        for match in matches:
            pr_numbers.add(int(match))

    # Get timeline events for cross-references
    try:
        timeline = api.get_paginated(
            f"/repos/{owner}/{repo}/issues/{issue_number}/timeline"
        )

        for event in timeline:
            if event.get("event") == "cross-referenced":
                source = event.get("source", {}).get("issue", {})
                if source.get("pull_request"):
                    pr_numbers.add(source.get("number"))
    except Exception as e:
        print(f"  Warning: Could not fetch timeline: {e}")

    # Filter out the tracker issue itself
    pr_numbers.discard(issue_number)

    return sorted(pr_numbers)


def get_pr_info(owner: str, repo: str, pr_number: int, api: GitHubAPI = None) -> PRInfo:
    """Get detailed information about a specific PR."""
    api = api or GitHubAPI()

    pr = api.get(f"/repos/{owner}/{repo}/pulls/{pr_number}")

    return PRInfo(
        number=pr["number"],
        title=pr["title"],
        body=pr.get("body") or "",
        base_sha=pr["base"]["sha"],
        head_sha=pr["head"]["sha"],
        merge_commit_sha=pr.get("merge_commit_sha"),
        merged_at=pr.get("merged_at"),
        diff_url=pr["diff_url"],
        html_url=pr["html_url"],
        state=pr["state"],
    )


def get_pr_diff(owner: str, repo: str, pr_number: int, api: GitHubAPI = None) -> str:
    """Get the diff/patch for a PR."""
    api = api or GitHubAPI()
    return api.get_diff(owner, repo, pr_number)


def extract_test_files_from_diff(diff: str) -> list[str]:
    """Extract test file paths from a diff."""
    test_files = []

    # Look for file paths in diff headers
    for line in diff.split("\n"):
        if line.startswith("diff --git"):
            # Extract file path: diff --git a/path/to/file b/path/to/file
            match = re.search(r"diff --git a/(.*) b/", line)
            if match:
                path = match.group(1)
                if "test" in path.lower() or path.endswith("_test.py"):
                    test_files.append(path)

    return list(set(test_files))


def get_merged_prs_for_tracker(
    owner: str,
    repo: str,
    tracker_issue: int,
    limit: Optional[int] = None
) -> list[PRInfo]:
    """
    Get all merged PRs for a tracker issue, ordered by merge date.

    Args:
        owner: Repository owner (e.g., 'pandas-dev')
        repo: Repository name (e.g., 'pandas')
        tracker_issue: The tracker issue number
        limit: Optional limit on number of PRs to fetch

    Returns:
        List of PRInfo objects for merged PRs, ordered by merge date
    """
    api = GitHubAPI()

    print(f"Fetching PRs from tracker issue #{tracker_issue}...")
    pr_numbers = get_tracker_issue_prs(owner, repo, tracker_issue, api)
    print(f"Found {len(pr_numbers)} referenced PRs")

    if limit:
        pr_numbers = pr_numbers[:limit]

    prs = []
    for pr_num in pr_numbers:
        try:
            print(f"  Fetching PR #{pr_num}...")
            pr_info = get_pr_info(owner, repo, pr_num, api)

            # Only include merged PRs
            if pr_info.merged_at:
                # Get the diff
                diff = get_pr_diff(owner, repo, pr_num, api)
                pr_info.patch = diff
                pr_info.test_files_changed = extract_test_files_from_diff(diff)
                prs.append(pr_info)
                print(f"    Merged at: {pr_info.merged_at}, tests: {len(pr_info.test_files_changed)}")
            else:
                print(f"    Skipping (not merged, state: {pr_info.state})")

        except Exception as e:
            print(f"    Error fetching PR #{pr_num}: {e}")

    # Sort by merge date
    prs.sort(key=lambda p: p.merged_at or "")

    print(f"Found {len(prs)} merged PRs")
    return prs


if __name__ == "__main__":
    # Test with pandas PDEP-14
    prs = get_merged_prs_for_tracker("pandas-dev", "pandas", 54792, limit=5)
    for pr in prs:
        print(f"PR #{pr.number}: {pr.title}")
        print(f"  Merged: {pr.merged_at}")
        print(f"  Test files: {pr.test_files_changed}")
