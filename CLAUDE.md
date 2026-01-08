---
description: Use Bun instead of Node.js, npm, pnpm, or vite.
globs: "*.ts, *.tsx, *.html, *.css, *.js, *.jsx, package.json"
alwaysApply: false
---

Default to using Bun instead of Node.js.

- Use `bun <file>` instead of `node <file>` or `ts-node <file>`
- Use `bun test` instead of `jest` or `vitest`
- Use `bun build <file.html|file.ts|file.css>` instead of `webpack` or `esbuild`
- Use `bun install` instead of `npm install` or `yarn install` or `pnpm install`
- Use `bun run <script>` instead of `npm run <script>` or `yarn run <script>` or `pnpm run <script>`
- Bun automatically loads .env, so don't use dotenv.

## APIs

- `Bun.serve()` supports WebSockets, HTTPS, and routes. Don't use `express`.
- `bun:sqlite` for SQLite. Don't use `better-sqlite3`.
- `Bun.redis` for Redis. Don't use `ioredis`.
- `Bun.sql` for Postgres. Don't use `pg` or `postgres.js`.
- `WebSocket` is built-in. Don't use `ws`.
- Prefer `Bun.file` over `node:fs`'s readFile/writeFile
- Bun.$`ls` instead of execa.

## Testing

Use `bun test` to run tests.

```ts#index.test.ts
import { test, expect } from "bun:test";

test("hello world", () => {
  expect(1).toBe(1);
});
```

## Frontend

Use HTML imports with `Bun.serve()`. Don't use `vite`. HTML imports fully support React, CSS, Tailwind.

Server:

```ts#index.ts
import index from "./index.html"

Bun.serve({
  routes: {
    "/": index,
    "/api/users/:id": {
      GET: (req) => {
        return new Response(JSON.stringify({ id: req.params.id }));
      },
    },
  },
  // optional websocket support
  websocket: {
    open: (ws) => {
      ws.send("Hello, world!");
    },
    message: (ws, message) => {
      ws.send(message);
    },
    close: (ws) => {
      // handle close
    }
  },
  development: {
    hmr: true,
    console: true,
  }
})
```

HTML files can import .tsx, .jsx or .js files directly and Bun's bundler will transpile & bundle automatically. `<link>` tags can point to stylesheets and Bun's CSS bundler will bundle.

```html#index.html
<html>
  <body>
    <h1>Hello, world!</h1>
    <script type="module" src="./frontend.tsx"></script>
  </body>
</html>
```

With the following `frontend.tsx`:

```tsx#frontend.tsx
import React from "react";

// import .css files directly and it works
import './index.css';

import { createRoot } from "react-dom/client";

const root = createRoot(document.body);

export default function Frontend() {
  return <h1>Hello, world!</h1>;
}

root.render(<Frontend />);
```

Then, run index.ts

```sh
bun --hot ./index.ts
```

For more information, read the Bun API docs in `node_modules/bun-types/docs/**.md`.

---

# Letta Code Architecture Analysis

This section provides guidance to Claude Code (claude.ai/code) when working with code in this repository, with special focus on the cross-session memory implementation.

## Project Overview

Letta Code is a memory-first coding harness CLI built on top of the Letta API. Unlike session-based AI coding assistants, Letta Code works with persisted agents that maintain memory and learning across sessions. The same agent can be used for the entire lifecycle of a project.

**Key Philosophy**: Session-based tools (Claude Code, Codex, Gemini CLI) treat each conversation as independent. Letta Code maintains a stateful agent where:
- `/clear` resets the current session but memory persists
- Memory blocks store learned preferences, project knowledge, and user habits
- The agent improves over time through persistent learning

## Build & Development Commands

```bash
# Install dependencies
bun install

# Run from TypeScript sources (dev workflow)
bun run dev
bun run dev -- -p "Hello world"  # with args

# Build standalone binary
bun run build
bun link  # expose globally

# Linting and type checking
bun run lint        # check with biome
bun run fix         # auto-fix with biome
bun run typecheck   # TypeScript checking
bun run check       # full check script

# Testing
bun test                              # run all tests
bun test src/tests/memory.test.ts     # run single test
```

## Architecture: Cross-Session Memory System

### Memory Block System (`src/agent/memory.ts`)

Memory is organized into labeled blocks with different scopes:

**Global Blocks** (shared across projects):
- `persona` - Agent behavioral guidelines, learned adaptations
- `human` - User preferences, communication style

**Project Blocks** (per-directory):
- `project` - Project-specific commands, conventions, architecture
- `skills` - Available skill definitions (read-only)
- `loaded_skills` - Currently loaded skills (read-only)

Memory blocks are loaded from `.mdx` files in `src/agent/prompts/` with frontmatter containing label, description, and limits.

### Agent State Persistence (`src/settings-manager.ts`)

Three levels of settings storage:
1. **Global settings** (`~/.letta/settings.json`): API keys, pinned agents, global preferences
2. **Project settings** (`.letta/settings.json`): Project-shared blocks
3. **Local settings** (`.letta/settings.local.json`): Per-user agent binding, last used agent

The `lastAgent` field tracks which agent to resume in each project directory.

### Agent Creation & Resume Flow (`src/agent/create.ts`, `src/index.ts`)

1. On startup, checks for `lastAgent` in local project settings
2. If found, resumes that agent (preserving all memory blocks)
3. If not found, shows profile selector or creates new agent
4. Memory blocks are created via Letta API and attached by block ID
5. Skills are discovered from `.skills/` directories and injected into `skills` block

### Memory Initialization (`/init` command)

The `/init` command triggers `src/agent/prompts/init_memory.md` which:
1. Asks user upfront questions (research depth, identity, preferences)
2. Reads project files (README, package.json, git history)
3. Creates/updates memory blocks incrementally
4. Stores user preferences in `human` block, rules in `persona` block

### Memory Search & Recall (`src/skills/builtin/searching-messages/`)

Cross-session recall uses:
- `conversation_search` server tool - searches current agent's message history
- `search-messages.ts` script - standalone vector/FTS/hybrid search
- `recall` subagent - specialized agent for history search

### Memory Migration (`src/skills/builtin/migrating-memory/`)

Enables copying or sharing memory blocks between agents:
- `copy-block.ts` - Creates independent copy of a block
- `attach-block.ts` - Links same block to multiple agents (changes sync)

## Key Code Patterns

### Client-Side vs Server-Side Tools

Tools are split between:
- **Server tools** (attached to agent): `memory`, `web_search`, `conversation_search`, `fetch_webpage`
- **Client tools** (passed at runtime): `Read`, `Write`, `Bash`, `Glob`, `Grep`, etc.

The tool registry in `src/tools/manager.ts` manages client tool loading based on model type (Anthropic, OpenAI, Gemini).

### Skill System (`src/agent/skills.ts`)

Skills are discovered from three sources (in priority order):
1. Project skills: `.skills/` in current directory
2. Global skills: `~/.letta/skills/`
3. Bundled skills: `src/skills/builtin/`

Each skill is a directory with `SKILL.md` containing frontmatter (name, description) and instructions.

### Subagent System (`src/agent/subagents/`)

The `Task` tool spawns specialized subagents:
- `explore` - Codebase exploration
- `recall` - Conversation history search
- `plan` - Implementation planning
- `general-purpose` - Multi-step autonomous tasks

Subagent configs are in `src/agent/subagents/builtin/*.md`.

### Agent Context (`src/agent/context.ts`)

Global singleton providing current agent ID and skills directory to tools without parameter threading. Uses `Symbol.for()` to ensure singleton across Bun's bundled modules.

## Important Files for Memory Implementation

- `src/agent/memory.ts` - Memory block definitions and loading
- `src/agent/create.ts` - Agent creation with block attachment
- `src/settings-manager.ts` - Multi-level settings persistence
- `src/agent/prompts/init_memory.md` - Memory initialization prompt
- `src/agent/prompts/remember.md` - `/remember` command prompt
- `src/skills/builtin/initializing-memory/SKILL.md` - Full init skill
- `src/skills/builtin/migrating-memory/SKILL.md` - Block migration
- `src/skills/builtin/searching-messages/` - History search scripts

## Environment Variables

- `LETTA_API_KEY` - API key for Letta platform
- `LETTA_BASE_URL` - Custom server URL (default: Letta Cloud)
- `LETTA_AGENT_ID` - Override agent ID
- `LETTA_PARENT_AGENT_ID` - Parent agent for subagents
- `LETTA_ENABLE_LSP` - Enable LSP-enhanced Read tool

---

## Git Workflow (IMPORTANT)

This repo is a fork. Always follow this workflow to stay synced with upstream and avoid conflicts.

### Remotes Setup
```
origin  → letta-ai/letta-code  (upstream public repo, read-only)
myfork  → zgrhhh/letta-code    (our fork, read-write)
```

### Branch Strategy
- `main` - Keep clean and synced with origin (no direct work here)
- `zgr-dev` - Our development branch (all work happens here)

### Start of Session Workflow
```bash
# 1. Fetch latest from upstream
git fetch origin

# 2. Sync main with upstream
git checkout main
git merge origin/main
git push myfork main

# 3. Switch to dev branch and rebase
git checkout zgr-dev
git rebase main
```

### End of Session Workflow
```bash
# 1. Commit your work on zgr-dev
git add .
git commit -m "your message"

# 2. Push to fork
git push myfork zgr-dev

# 3. Optionally sync main again
git checkout main
git fetch origin
git merge origin/main
git push myfork main
```

### If zgr-dev doesn't exist yet
```bash
git checkout -b zgr-dev
git push -u myfork zgr-dev
```

### Resolving Rebase Conflicts
```bash
# If conflicts occur during rebase:
# 1. Edit conflicted files (look for <<<<<<< markers)
# 2. Stage resolved files
git add <resolved-file>
# 3. Continue rebase
git rebase --continue
# 4. Or abort if too messy
git rebase --abort
```

### Quick Reference
| Action | Command |
|--------|---------|
| Start session | `git fetch origin` |
| Sync main | `git checkout main && git merge origin/main` |
| Rebase dev | `git checkout zgr-dev && git rebase main` |
| Push work | `git push myfork zgr-dev` |
| Force push after rebase | `git push myfork zgr-dev --force` |
