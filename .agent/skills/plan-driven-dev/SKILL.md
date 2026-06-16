---
name: plan-driven-dev
description: >
  Use this skill whenever the user provides an implementation plan (with phases and sub-phases)
  and asks Claude Code to implement it. Triggers when a user says things like "here is my
  implementation plan", "implement this phase", "let's start with sub-phase X", "follow this
  plan and build it", or shares a structured plan document (markdown, text, or pasted content)
  describing what to build. Also trigger when a user pastes a phased plan with code snippets
  and says "implement this" or "let's build this". Always use this skill — do not wing it
  from the plan alone — because the skill defines exactly how to read code snippets, how to
  propose before writing, and how to pace implementation one sub-phase at a time.
---
 
# Plan-Driven Development Skill
 
This skill governs how Claude Code implements a project from a structured implementation plan
containing phases, sub-phases, descriptions, and code snippets.
 
---
 
## Core Philosophy
 
The plan is a **guide, not a script.**
 
- Code snippets in the plan show *intent and structure* — not final code to copy-paste.
- Your job is to understand what the snippet is trying to do and write **clean, working code**
  that actually fits the real project.
- Code should be easy to read and understand — not overly simple, not over-engineered.
  A junior dev should be able to follow it. A senior dev should not cringe at it.
- Every piece of code must properly integrate with the rest of the project (imports, shared
  state, APIs, naming conventions, file structure, etc.).
 
---
 
## Step 0: Parse the Plan
 
When the user provides a plan (in any format — markdown file, plain text, pasted content):
 
1. Read and parse all phases and sub-phases.
2. Print a clean summary of the full plan structure:
 
```
📋 Plan Overview
─────────────────
Phase 1: <Title>
  1.1 <Sub-phase title>
  1.2 <Sub-phase title>
 
Phase 2: <Title>
  2.1 <Sub-phase title>
  ...
 
Total: X phases, Y sub-phases
```
 
3. Ask: **"Which phase/sub-phase should we start with? Or should I begin from the top?"**
4. Wait for the user's answer before doing anything else.
 
---
 
## Step 1: Pre-Implementation Brief (before writing any code)
 
For each sub-phase you are about to implement, produce a **Pre-Implementation Brief** first.
Do NOT write any code yet.
 
### Format
 
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔧 Sub-phase X.Y — <Title>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 
📌 What this sub-phase does:
<2–4 sentence plain-English summary of the goal>
 
📁 Files I'll create or modify:
- path/to/file.ts  → [create] short reason
- path/to/other.ts → [modify] short reason
 
🧠 Key decisions I'm making:
- <Decision 1 and why — e.g. "Using a Map instead of array for O(1) lookups">
- <Decision 2 and why — e.g. "Splitting auth logic into its own helper to keep routes clean">
- <Any deviation from the plan snippet and why>
 
🔗 How this connects to the rest of the project:
- <What it depends on that already exists>
- <What future sub-phases will depend on this>
 
⚠️ Assumptions / things to confirm:
- <Anything unclear in the plan that you're making a call on>
- <Any env vars, configs, or external setup needed>
 
──────────────────────────────────────
Ready to implement. Type "go" to proceed, or give feedback first.
```
 
Wait for the user to say "go" (or "yes", "looks good", "proceed") before writing any code.
If they give feedback, revise the brief and ask again.
 
---
 
## Step 2: Implementation
 
Once approved, implement the sub-phase.
 
### Code Writing Rules
 
**Structure and logic:**
- Write real, working code — not placeholder stubs unless the plan explicitly calls for them.
- Make sure imports, exports, types, and function signatures actually match what exists in
  the project. Don't invent interfaces that don't exist yet.
- If a dependency (another module, a util, a type) doesn't exist yet, either create it as
  part of this sub-phase or flag it clearly.
 
**Reading plan snippets:**
- Treat snippets as pseudocode with hints. Ask: "What is this trying to accomplish?"
- Rewrite it properly with real logic, error handling, and correct types for the project.
- Do NOT copy snippets verbatim if they use placeholder names, dummy data, or are clearly
  incomplete.
 
**Code style:**
- Prefer clarity over cleverness. If there's a simple way and a clever way, pick simple.
- Use meaningful variable names. Avoid `data`, `res`, `tmp`, `obj` unless truly appropriate.
- Add short comments on anything non-obvious — not everywhere, just where a reader might pause.
- Keep functions focused. If a function is doing 3 different things, split it.
- Avoid deeply nested logic — flatten with early returns where it helps readability.
- Don't add extra abstraction layers unless the plan specifically calls for them or the
  project clearly needs them.
 
**Integration:**
- Match the file/folder structure already established in the project.
- Match naming conventions already in use (camelCase, snake_case, etc.).
- Reuse existing utilities, helpers, and types — don't duplicate them.
- If you're modifying an existing file, touch only what's needed for this sub-phase.
 
### After writing code
 
End with a short **Implementation Summary**:
 
```
✅ Sub-phase X.Y complete
 
What was built:
- <File 1>: <one-line description of what it does>
- <File 2>: <one-line description>
 
Notable decisions made during implementation:
- <Any meaningful deviation from the brief or plan>
 
Next up: Sub-phase X.Z — <Title>
Type "next" to continue, or ask questions first.
```
 
Then **stop and wait.** Do not move to the next sub-phase automatically.
 
---
 
## Step 3: Moving Between Sub-phases
 
- Only proceed to the next sub-phase when the user says so ("next", "continue", "let's go",
  "move on", etc.).
- At the start of each new sub-phase, repeat the Pre-Implementation Brief (Step 1).
- Keep track of what has been built so far so integration decisions stay consistent.
- If you notice something from a previous sub-phase needs to change based on what you're
  implementing now, flag it before implementing:
 
```
⚠️ Heads up: While preparing this sub-phase, I noticed that [X] from sub-phase Y.Z may
need a small adjustment to support this. Specifically: [what and why].
Should I make that change as part of this sub-phase?
```
 
---
 
## Handling Ambiguity
 
If the plan is unclear or contradicts itself:
- Make a reasonable call and clearly state it in the brief under "Assumptions".
- Don't silently guess — always surface your interpretation so the user can correct it.
 
If a code snippet in the plan is too high-level or missing key details:
- Fill in the gaps with sensible defaults for the tech stack in use.
- Mention what you filled in under "Key decisions".
 
---
 
## What NOT to do
 
- ❌ Don't implement multiple sub-phases in one go unless the user explicitly asks.
- ❌ Don't copy plan snippets verbatim without adapting them to the real project context.
- ❌ Don't write code before the user approves the brief.
- ❌ Don't skip the Implementation Summary — it helps the user track progress.
- ❌ Don't add unnecessary abstractions, factories, or design patterns the plan doesn't call for.
- ❌ Don't leave TODOs or stubs in the code unless explicitly planned (and if you do, mark them clearly).