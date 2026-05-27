#!/usr/bin/env bash

# ==============================================================================
# Agile Multi-Agent Governance Bootstrapper
# ==============================================================================
# This script initializes the folders, templates, and symlinks required to run
# structured Agile Sprints, parallel agent claiming, and strict governance.
#
# Usage:
#   1. Copy this script to the root of your new project.
#   2. Run: bash bootstrap-governance.sh
# ==============================================================================

set -euo pipefail

echo "======================================================================"
echo "Initializing Agile Multi-Agent Governance Framework..."
echo "======================================================================"

# 1. Create Folder Structure
echo "--> Creating required directories..."
mkdir -p docs/architecture \
         docs/sprints/specs \
         docs/handoffs/log \
         docs/archive \
         .agent/active \
         .github

# 2. Author .agent/governance.md
echo "--> Creating agent governance instructions..."
cat << 'EOF' > .agent/governance.md
# Multi-Agent Governance Model

To preserve the absolute operational integrity of this codebase during parallel agent development, all contributors (AI agents and human developers alike) **MUST** strictly adhere to this governance model.

---

## 1. The Core Operations Loop

Every session or task execution must follow these five steps in sequence:

1.  **Pre-Claim Check**: Read `AGENTS.md` to understand compiler commands and project guidelines. Review the active Sprint file (e.g. `docs/sprints/SPRINT_1.md`) and active claims in `.agent/active/claims.md` to ensure no other agent is editing the same module or file.
2.  **Task Locking (Claiming)**: Register your claim in `.agent/active/claims.md` under **Active Claims**. Change the task checkbox inside the active Sprint file from `[ ]` to `[/]` (In Progress) and append your agent signature. Add yourself to `.agent/active/roster.md`.
3.  **Incremental Execution**: Perform edits in small, logical chunks to prevent timeouts and merge conflicts. Run test suites and validation commands frequently.
4.  **Checkout & Release**: Upon finishing, move your claim to **Completed Claims** in `claims.md`, change the task checkbox to `[x]` (Complete) with completion notes in the active Sprint file, and move yourself from Active to the **Hall of Fame** in `roster.md`.
5.  **Handoff Writing**: When concluding a session or a major sprint milestone, compose a formal handoff log under `docs/handoffs/log/` and record it in `docs/handoffs/index.md`.

---

## 2. Collision Resiliency Rules

1.  **Granular Replacements**: Do not replace whole files when updating markdown ledgers or source code. Target specific lines to minimize merge conflict overlaps.
2.  **State Re-Verification**: If a replace command fails with "target content not found", immediately re-scan the file (`view_file`) before retrying.
3.  **One Claim Limit**: An agent may claim exactly *one* task at a time. No parallel batch-claiming is allowed.
EOF

# 3. Author .agent/active/claims.md
echo "--> Creating task claims ledger..."
cat << 'EOF' > .agent/active/claims.md
# Task Claims Ledger

This ledger acts as a concurrency lock to prevent parallel agents from executing overlapping tasks or editing the same files simultaneously.

---

## 1. Active Claims

| Task ID | Target Module / Files | Claiming Agent | Claim Date | Status |
|---------|-----------------------|----------------|------------|--------|
| - | - | - | - | - |

---

## 2. Completed Claims

| Task ID | Target Module / Files | Completed By | Completion Date | Scope / Output Summary |
|---------|-----------------------|--------------|-----------------|------------------------|
| - | - | - | - | - |
EOF

# 4. Author .agent/active/roster.md
echo "--> Creating agent roster ledger..."
cat << 'EOF' > .agent/active/roster.md
# Agent Roster & Hall of Fame

This file tracks the active contributors and preserves a historical log of their cumulative contributions.

---

## 1. Active Agents

| Agent Name | Active Role | Current Task | Session Start |
|------------|-------------|--------------|---------------|
| - | - | - | - |

---

## 2. Hall of Fame

| Contributor | Roles Played | Tasks Delivered | Total Sprints Active |
|-------------|--------------|-----------------|----------------------|
| - | - | - | - |
EOF

# 5. Author docs/sprints/SPRINT_LEDGER.md
echo "--> Creating central sprint ledger..."
cat << 'EOF' > docs/sprints/SPRINT_LEDGER.md
# Project Sprint Ledger

Welcome to the Project Sprint Ledger. This document acts as the centralized roadmap and status ledger for all Agile sprint iterations.

---

## 1. Project Roadmap & Iteration Summary

The project is structured into consecutive sprints designed to deliver programmatic features and stable user experience components.

*Update this section with your project timeline and high-level roadmap.*

---

## 2. Sprint Registry

| Sprint | Goal / Milestone | Focus Area | Status | Document |
|--------|------------------|------------|--------|----------|
| **Sprint 1** | Initial MVP Setup | Repository structures and baseline | **In Progress** | [Sprint 1 Plan](docs/sprints/SPRINT_1.md) |

---

## 3. Active Governance Invariant

All agents working on this repository **MUST** claim tasks inside the active sprint file and record their claims inside the `.agent/active/claims.md` registry *before* making any codebase changes.

For core developer rules and developer instructions, see [AGENTS.md](AGENTS.md).
EOF

# 6. Author docs/sprints/SPRINT_1.md
# Bug fix 1: pre-expand DATE so it resolves correctly in the heredoc
DATE=$(date +%Y-%m-%d)
echo "--> Creating initial Sprint 1 checklist template..."
cat << EOF > docs/sprints/SPRINT_1.md
# Sprint 1: Initial MVP Setup

**Status:** Active
**Author:** AI Product Lead
**Date:** $DATE
**Branch:** \`main\`

---

## 1. Active Task Registry

To enable parallel agent execution without file conflicts, tasks are broken down into granular work packages. Agents must claim individual tasks in \`.agent/active/claims.md\` and mark them here with \`[/]\` when starting, and \`[x]\` when completed.

- \`[ ]\` **Task 1: Project Environment Verification**
  *   **Objective**: Audit the development stack and verify base packages.
- \`[ ]\` **Task 2: Architectural Mapping**
  *   **Objective**: Build out the initial architecture handbook reference.

---

## 2. QA & Verification Protocol

Define standard build, compilation, and testing commands here to ensure that work is fully validated before checking out.
EOF

# 7. Author docs/handoffs/index.md
echo "--> Creating handoffs ledger index..."
cat << 'EOF' > docs/handoffs/index.md
# Handoff Ledger

This folder contains formal engineering handoffs between active AI sessions. Re-anchoring context ensures that the incoming developer or agent can immediately resume work without any ambiguity or redundant analysis.

---

## 1. Handoff Logs Registry

Below is a historical listing of all engineer and agent session handoffs:

| Date | Session Phase | Handoff Scope | Document Link |
|------|---------------|---------------|---------------|
| - | - | - | - |

---

## 2. Handoff Checklist Contract

When concluding a development session or transitioning a sprint milestone, the active agent or developer **MUST** compose a fresh handoff document under `docs/handoffs/log/` containing:
1.  **Status Summary**: What is currently running, tested, and fully functional.
2.  **Code Changes**: Detailed accounting of modified modules, hooks, database schemas, or visual layers.
3.  **Active Work Blockers**: Outstanding bugs, API failures, or items that need attention.
4.  **Actionable Tasks**: Precise next steps mapped directly to active Sprint deliverables.
EOF

# 8. Create unified AGENTS.md
echo "--> Initializing consolidated AGENTS.md rules engine..."
cat << 'EOF' > AGENTS.md
# Consolidated Developer & Agent Instructions

This is the single source of truth for repository guidelines, developer commands, Agile parallelization workflows, and technical standards. All contributing AI agents (Claude, Gemini, Cursor, Copilot/Codex) are bound by these rules.

---

## 1. Operational & CLI Reference

### Essential CLI Commands
*   **Type Checking**: *[Insert typecheck command, e.g., npm run tsc]*
*   **Production Build**: *[Insert build command, e.g., npm run build]*
*   **Test Suite**: *[Insert testing command, e.g., npm run test]*

### Text Formatting & Linting Style
*   **No Unicode Em-Dashes**: Pre-commit hooks reject em-dashes (`—`). Always use single hyphens (`-`) or restyle your sentences.

---

## 2. Agile Multi-Agent Governance

To execute tasks in parallel without merge collisions or overlapping efforts, follow these rules:
1.  **Check Claims Ledger**: Read `.agent/active/claims.md` and check if the module you plan to modify is currently locked by another agent.
2.  **Claim Your Task**: Add an active claim row in `claims.md`, change the task checkbox to `[/]` (In Progress) in the active sprint (e.g. `docs/sprints/SPRINT_1.md`), and add yourself to `.agent/active/roster.md`.
3.  **Perform Session Checkout**: On completion, move your claim to **Completed Claims** inside `claims.md`, change the task checkbox to `[x]` (Complete) in the active sprint file with brief notes, and move yourself to the **Hall of Fame** in `roster.md`.
4.  **Handoff Writing**: When concluding a session or a major sprint milestone, compose a formal handoff log under `docs/handoffs/log/` and record it in `docs/handoffs/index.md`.

---

## 3. Project Technical & Coding Rules

*[Add your framework-specific or project-specific coding rules, TypeScript standards, security rules, and performance guidelines here]*
EOF

# 9. Establish Symlinks
echo "--> Deploying symlink mesh..."

# Bug fix 2 & 3: guard against destroying real files; use ln -sf for idempotency
if [ -e "CLAUDE.md" ] && [ ! -L "CLAUDE.md" ]; then
  echo "WARNING: CLAUDE.md exists and is not a symlink — skipping"
else
  rm -f CLAUDE.md && ln -sf AGENTS.md CLAUDE.md
fi

if [ -e "GEMINI.md" ] && [ ! -L "GEMINI.md" ]; then
  echo "WARNING: GEMINI.md exists and is not a symlink — skipping"
else
  rm -f GEMINI.md && ln -sf AGENTS.md GEMINI.md
fi

if [ -e ".cursorrules" ] && [ ! -L ".cursorrules" ]; then
  echo "WARNING: .cursorrules exists and is not a symlink — skipping"
else
  rm -f .cursorrules && ln -sf AGENTS.md .cursorrules
fi

if [ -e ".github/copilot-instructions.md" ] && [ ! -L ".github/copilot-instructions.md" ]; then
  echo "WARNING: .github/copilot-instructions.md exists and is not a symlink — skipping"
else
  rm -f .github/copilot-instructions.md && ln -sf ../AGENTS.md .github/copilot-instructions.md
fi

echo "======================================================================"
echo "SUCCESS: Agile Multi-Agent Governance successfully bootstrapped!"
echo "Master rules file: AGENTS.md"
echo "Agile sprint center: docs/sprints/"
echo "Locks & Roster lockbox: .agent/"
echo "Symlinks created: CLAUDE.md, GEMINI.md, .cursorrules, .github/copilot-instructions.md"
echo "======================================================================"
