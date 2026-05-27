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
