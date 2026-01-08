#!/usr/bin/env bun
/**
 * Multi-Session Benchmark (MSB) Data Collector
 *
 * Mines multi-PR task sequences from TIER 1 repositories:
 * - pandas-dev/pandas (PDEPs + TRACKER issues)
 * - apache/airflow (AIPs)
 * - numpy/numpy (NEPs)
 *
 * Usage:
 *   bun scripts/msb-data-collector.ts --repo pandas-dev/pandas --tracker 54792
 *   bun scripts/msb-data-collector.ts --repo apache/airflow --aip 10
 */

import { parseArgs } from "util";

// ============================================================================
// Types
// ============================================================================

interface PRInfo {
  number: number;
  title: string;
  body: string;
  mergedAt: string | null;
  baseCommit: string;
  patch: string;
  testPatch: string;
  files: string[];
  dependsOn: number[];
}

interface Session {
  session_id: string;
  sequence_number: number;
  pr_number: number;
  base_commit: string;
  problem_statement: string;
  hints_text: string;
  patch: string;
  test_patch: string;
  FAIL_TO_PASS: string[];
  PASS_TO_PASS: string[];
  depends_on: string[];
  provides: string[];
  expected_memory_updates: Record<string, string[]>;
  required_memory_recall?: string[];
}

interface Task {
  task_id: string;
  repo: string;
  enhancement_id: string;
  tracker_issue: number | null;
  total_sessions: number;
  difficulty: "easy" | "medium" | "hard";
  sessions: Session[];
  memory_evaluation: {
    test_recall_at_sessions: number[];
    critical_facts: string[];
    pattern_tests?: Array<{
      pattern: string;
      expected_consistency: string;
    }>;
  };
}

// ============================================================================
// GitHub API Helpers
// ============================================================================

const GITHUB_TOKEN = process.env.GITHUB_TOKEN;

if (!GITHUB_TOKEN) {
  console.error("Error: GITHUB_TOKEN environment variable required");
  process.exit(1);
}

async function githubFetch(endpoint: string): Promise<unknown> {
  const response = await fetch(`https://api.github.com${endpoint}`, {
    headers: {
      Authorization: `Bearer ${GITHUB_TOKEN}`,
      Accept: "application/vnd.github.v3+json",
      "X-GitHub-Api-Version": "2022-11-28",
    },
  });

  if (!response.ok) {
    throw new Error(`GitHub API error: ${response.status} ${response.statusText}`);
  }

  return response.json();
}

async function getIssue(repo: string, issueNumber: number): Promise<{
  title: string;
  body: string;
  labels: Array<{ name: string }>;
}> {
  return githubFetch(`/repos/${repo}/issues/${issueNumber}`) as Promise<{
    title: string;
    body: string;
    labels: Array<{ name: string }>;
  }>;
}

async function getIssueTimeline(repo: string, issueNumber: number): Promise<Array<{
  event: string;
  source?: { issue?: { number: number; pull_request?: unknown } };
}>> {
  const events: Array<{
    event: string;
    source?: { issue?: { number: number; pull_request?: unknown } };
  }> = [];
  let page = 1;

  while (true) {
    const pageEvents = (await githubFetch(
      `/repos/${repo}/issues/${issueNumber}/timeline?per_page=100&page=${page}`
    )) as Array<{
      event: string;
      source?: { issue?: { number: number; pull_request?: unknown } };
    }>;

    if (pageEvents.length === 0) break;
    events.push(...pageEvents);
    page++;
  }

  return events;
}

async function getPullRequest(repo: string, prNumber: number): Promise<{
  number: number;
  title: string;
  body: string;
  merged_at: string | null;
  base: { sha: string };
  merge_commit_sha: string | null;
}> {
  return githubFetch(`/repos/${repo}/pulls/${prNumber}`) as Promise<{
    number: number;
    title: string;
    body: string;
    merged_at: string | null;
    base: { sha: string };
    merge_commit_sha: string | null;
  }>;
}

async function getPullRequestFiles(repo: string, prNumber: number): Promise<Array<{
  filename: string;
  status: string;
  patch?: string;
}>> {
  return githubFetch(`/repos/${repo}/pulls/${prNumber}/files`) as Promise<Array<{
    filename: string;
    status: string;
    patch?: string;
  }>>;
}

async function getPullRequestDiff(repo: string, prNumber: number): Promise<string> {
  const response = await fetch(
    `https://api.github.com/repos/${repo}/pulls/${prNumber}`,
    {
      headers: {
        Authorization: `Bearer ${GITHUB_TOKEN}`,
        Accept: "application/vnd.github.v3.diff",
        "X-GitHub-Api-Version": "2022-11-28",
      },
    }
  );

  if (!response.ok) {
    throw new Error(`GitHub API error: ${response.status}`);
  }

  return response.text();
}

// ============================================================================
// PR Analysis
// ============================================================================

function extractDependencies(prBody: string, existingPRs: number[]): number[] {
  const dependencies: number[] = [];

  // Pattern: "depends on #1234" or "requires #1234"
  const dependsOnPattern = /(?:depends on|requires|after|following)\s*#(\d+)/gi;
  let match;

  while ((match = dependsOnPattern.exec(prBody)) !== null) {
    const prNum = parseInt(match[1], 10);
    if (existingPRs.includes(prNum)) {
      dependencies.push(prNum);
    }
  }

  return [...new Set(dependencies)];
}

function splitPatch(fullDiff: string): { codePatch: string; testPatch: string } {
  const lines = fullDiff.split("\n");
  const codeLines: string[] = [];
  const testLines: string[] = [];

  let currentFile = "";
  let isTestFile = false;

  for (const line of lines) {
    if (line.startsWith("diff --git")) {
      currentFile = line;
      isTestFile = /\/tests?\//.test(line) || /test_\w+\.py/.test(line);
    }

    if (isTestFile) {
      testLines.push(line);
    } else {
      codeLines.push(line);
    }
  }

  return {
    codePatch: codeLines.join("\n"),
    testPatch: testLines.join("\n"),
  };
}

function extractTestNames(testPatch: string): string[] {
  const tests: string[] = [];
  const testPattern = /def (test_\w+)/g;
  let match;

  while ((match = testPattern.exec(testPatch)) !== null) {
    tests.push(match[1]);
  }

  return tests;
}

function inferProvides(prTitle: string, files: string[]): string[] {
  const provides: string[] = [];

  // Extract from title
  if (prTitle.toLowerCase().includes("add")) {
    provides.push(prTitle.replace(/^[^:]+:\s*/, ""));
  }

  // Extract from new files
  for (const file of files) {
    if (file.includes("new file")) {
      provides.push(`New file: ${file}`);
    }
  }

  return provides;
}

function inferMemoryUpdates(
  prTitle: string,
  prBody: string,
  files: string[]
): Record<string, string[]> {
  const updates: Record<string, string[]> = {
    project: [],
    persona: [],
  };

  // Extract key decisions from PR body
  const bulletPoints = prBody.match(/[-*]\s+([^\n]+)/g) || [];
  for (const point of bulletPoints.slice(0, 3)) {
    updates.project.push(point.replace(/^[-*]\s+/, ""));
  }

  // Add file locations
  const uniqueDirs = [...new Set(files.map((f) => f.split("/").slice(0, -1).join("/")))];
  if (uniqueDirs.length > 0 && uniqueDirs.length <= 3) {
    updates.project.push(`Changes in: ${uniqueDirs.join(", ")}`);
  }

  return updates;
}

// ============================================================================
// Tracker Mining
// ============================================================================

async function findLinkedPRs(repo: string, trackerIssue: number): Promise<number[]> {
  console.log(`Fetching timeline for ${repo}#${trackerIssue}...`);
  const timeline = await getIssueTimeline(repo, trackerIssue);

  const prNumbers: number[] = [];

  for (const event of timeline) {
    if (event.event === "cross-referenced" && event.source?.issue?.pull_request) {
      prNumbers.push(event.source.issue.number);
    }
  }

  // Also parse issue body for PR references
  const issue = await getIssue(repo, trackerIssue);
  const prPattern = /#(\d+)/g;
  let match;

  while ((match = prPattern.exec(issue.body)) !== null) {
    const num = parseInt(match[1], 10);
    if (!prNumbers.includes(num)) {
      prNumbers.push(num);
    }
  }

  console.log(`Found ${prNumbers.length} potential PRs`);
  return prNumbers;
}

async function buildPRChain(repo: string, prNumbers: number[]): Promise<PRInfo[]> {
  const prs: PRInfo[] = [];

  for (const prNum of prNumbers) {
    console.log(`Fetching PR #${prNum}...`);
    try {
      const pr = await getPullRequest(repo, prNum);

      // Skip unmerged PRs
      if (!pr.merged_at) {
        console.log(`  Skipping #${prNum} (not merged)`);
        continue;
      }

      const files = await getPullRequestFiles(repo, prNum);
      const diff = await getPullRequestDiff(repo, prNum);
      const { codePatch, testPatch } = splitPatch(diff);

      prs.push({
        number: pr.number,
        title: pr.title,
        body: pr.body || "",
        mergedAt: pr.merged_at,
        baseCommit: pr.base.sha,
        patch: codePatch,
        testPatch: testPatch,
        files: files.map((f) => f.filename),
        dependsOn: extractDependencies(pr.body || "", prNumbers),
      });

      // Rate limiting
      await new Promise((resolve) => setTimeout(resolve, 500));
    } catch (error) {
      console.log(`  Error fetching #${prNum}: ${error}`);
    }
  }

  // Sort by merge date
  prs.sort((a, b) => {
    if (!a.mergedAt || !b.mergedAt) return 0;
    return new Date(a.mergedAt).getTime() - new Date(b.mergedAt).getTime();
  });

  return prs;
}

// ============================================================================
// Task Generation
// ============================================================================

function generateTask(
  repo: string,
  enhancementId: string,
  trackerIssue: number | null,
  prs: PRInfo[]
): Task {
  const taskId = `${repo.replace("/", "__")}-${enhancementId}`.toLowerCase();
  const sessions: Session[] = [];

  for (let i = 0; i < prs.length; i++) {
    const pr = prs[i];
    const sessionId = `${taskId}-${String(i + 1).padStart(3, "0")}`;

    // Find dependencies among our sessions
    const dependsOn = pr.dependsOn
      .map((depPrNum) => {
        const depIndex = prs.findIndex((p) => p.number === depPrNum);
        if (depIndex >= 0) {
          return `${taskId}-${String(depIndex + 1).padStart(3, "0")}`;
        }
        return null;
      })
      .filter((d): d is string => d !== null);

    // Extract test names for FAIL_TO_PASS
    const newTests = extractTestNames(pr.testPatch);

    // Build session
    const session: Session = {
      session_id: sessionId,
      sequence_number: i + 1,
      pr_number: pr.number,
      base_commit: pr.baseCommit,
      problem_statement: `${pr.title}\n\n${pr.body.slice(0, 500)}...`,
      hints_text: i === 0 ? extractHints(pr.body) : "",
      patch: pr.patch,
      test_patch: pr.testPatch,
      FAIL_TO_PASS: newTests.slice(0, 5),
      PASS_TO_PASS: [],
      depends_on: dependsOn,
      provides: inferProvides(pr.title, pr.files),
      expected_memory_updates: inferMemoryUpdates(pr.title, pr.body, pr.files),
    };

    // Add memory recall requirements for later sessions
    if (i > 0) {
      session.required_memory_recall = sessions
        .slice(Math.max(0, i - 3), i)
        .flatMap((s) => s.provides.slice(0, 2));
    }

    sessions.push(session);
  }

  // Determine difficulty
  let difficulty: "easy" | "medium" | "hard" = "medium";
  if (prs.length <= 3) difficulty = "easy";
  else if (prs.length >= 10) difficulty = "hard";

  return {
    task_id: taskId,
    repo,
    enhancement_id: enhancementId,
    tracker_issue: trackerIssue,
    total_sessions: sessions.length,
    difficulty,
    sessions,
    memory_evaluation: {
      test_recall_at_sessions: [
        Math.floor(sessions.length / 2),
        sessions.length,
      ],
      critical_facts: sessions
        .flatMap((s) => s.expected_memory_updates.project)
        .slice(0, 5),
    },
  };
}

function extractHints(body: string): string {
  // Extract potential hints from PR body
  const hintPatterns = [
    /(?:note|hint|tip|suggestion):\s*([^\n]+)/gi,
    /(?:consider|try|use)\s+([^\n.]+)/gi,
  ];

  const hints: string[] = [];
  for (const pattern of hintPatterns) {
    let match;
    while ((match = pattern.exec(body)) !== null) {
      hints.push(match[1].trim());
    }
  }

  return hints.slice(0, 3).join(". ");
}

// ============================================================================
// Main
// ============================================================================

async function main() {
  const { values } = parseArgs({
    args: Bun.argv.slice(2),
    options: {
      repo: { type: "string", short: "r" },
      tracker: { type: "string", short: "t" },
      output: { type: "string", short: "o", default: "msb-task.json" },
      "enhancement-id": { type: "string", short: "e" },
      help: { type: "boolean", short: "h" },
    },
    strict: true,
  });

  if (values.help) {
    console.log(`
Multi-Session Benchmark Data Collector

Usage:
  bun scripts/msb-data-collector.ts --repo <owner/repo> --tracker <issue-number>

Options:
  -r, --repo           Repository (e.g., pandas-dev/pandas)
  -t, --tracker        Tracker issue number
  -e, --enhancement-id Enhancement ID (e.g., PDEP-14, AIP-10)
  -o, --output         Output file (default: msb-task.json)
  -h, --help           Show this help

Examples:
  # pandas PDEP-14 String Dtype
  bun scripts/msb-data-collector.ts \\
    --repo pandas-dev/pandas \\
    --tracker 54792 \\
    --enhancement-id PDEP-14

  # pandas PDEP-7 Copy-on-Write
  bun scripts/msb-data-collector.ts \\
    --repo pandas-dev/pandas \\
    --tracker 49473 \\
    --enhancement-id PDEP-7
    `);
    process.exit(0);
  }

  if (!values.repo || !values.tracker) {
    console.error("Error: --repo and --tracker are required");
    process.exit(1);
  }

  const repo = values.repo;
  const trackerIssue = parseInt(values.tracker, 10);
  const enhancementId = values["enhancement-id"] || `TRACKER-${trackerIssue}`;
  const outputFile = values.output || "msb-task.json";

  console.log(`\nMulti-Session Benchmark Data Collector`);
  console.log(`=====================================`);
  console.log(`Repository: ${repo}`);
  console.log(`Tracker Issue: #${trackerIssue}`);
  console.log(`Enhancement ID: ${enhancementId}`);
  console.log(`Output: ${outputFile}\n`);

  try {
    // Step 1: Find linked PRs
    const prNumbers = await findLinkedPRs(repo, trackerIssue);

    if (prNumbers.length === 0) {
      console.error("No PRs found in tracker issue");
      process.exit(1);
    }

    // Step 2: Build PR chain with details
    const prs = await buildPRChain(repo, prNumbers);
    console.log(`\nProcessed ${prs.length} merged PRs`);

    if (prs.length === 0) {
      console.error("No merged PRs found");
      process.exit(1);
    }

    // Step 3: Generate task
    const task = generateTask(repo, enhancementId, trackerIssue, prs);

    // Step 4: Write output
    await Bun.write(outputFile, JSON.stringify(task, null, 2));
    console.log(`\nTask written to ${outputFile}`);

    // Summary
    console.log(`\nTask Summary:`);
    console.log(`  ID: ${task.task_id}`);
    console.log(`  Sessions: ${task.total_sessions}`);
    console.log(`  Difficulty: ${task.difficulty}`);
    console.log(`  PRs: ${prs.map((p) => `#${p.number}`).join(", ")}`);
  } catch (error) {
    console.error(`Error: ${error}`);
    process.exit(1);
  }
}

main();
