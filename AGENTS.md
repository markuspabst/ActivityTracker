# AGENTS.md

## Project Configuration

| Field | Value |
|---|---|
| Language / Runtime | Python >= 3.11 |
| Build Command | `briefcase build macOS` |
| Test Command | `pytest tests/ -v` |
| Lint Command | `ruff check activitytracker tests` |
| Type Check Command | `mypy activitytracker` |
| Run Command | `python3 -m activitytracker` |
| Entry Points | `activitytracker/__main__.py`, `activitytracker/app.py::main()` |
| Key Directories | `activitytracker/`, `tests/`, `locales/`, `scripts/` |
| Important Files | `pyproject.toml`, `pytest.ini`, `pylintrc` |
| Required Env Vars | None |
| Domain Glossary | See below |

If a field is blank, detect it from the repository before reading or writing code. Report what you detected in one line and proceed. Ask only if detection is genuinely ambiguous.

### Domain Glossary

- **Segment**: A continuous period of `active` or `idle` time with a start and end timestamp.
- **Day**: A calendar date plus its list of segments.
- **Idle threshold**: Maximum seconds of inactivity before the app switches from `active` to `idle`.
- **Optimization pipeline**: Filter boundary idle → fill gaps with idle → merge adjacent segments.
- **Newest-first**: CSV rows sorted descending by `date start`.

---

## Communication

Applies to all human-facing output: comments, commit messages, documentation, PR descriptions, chat replies.

### Written artifacts

- Fewest words that convey the meaning.
- Direct and factual. State uncertainty explicitly.
- No praise, flattery, or superlatives.
- Do not optimize for agreement.
- Give the cold hard truth.

### Explanations and replies

- Complete enough to be actionable. Terseness never overrides clarity.
- State uncertainty explicitly.
- Give the cold hard truth, including when the user's premise is wrong.
- Do not optimize for agreement.

The "fewest words" rule never applies to explanations of bugs, failures, or trade-offs.

Code identifiers follow the repository's existing naming conventions, not this rule.

---

## Before Making Changes

1. Read `AGENTS.md`.
2. Read `README.md`.
3. Read the relevant code before modifying it.
4. Understand existing patterns before introducing new ones.
5. Search for existing implementations before writing new ones.
6. State assumptions explicitly.

If requirements are ambiguous: stop and ask.

---

## Architecture

### Data Flow

```
[App ticks every 10 seconds]
  ActivityTrackerApp.update()
  ├─ platform_layer.get_idle_time()
  ├─ SessionTracker.on_tick()
  │   (updates session.days & current_segment)
  ├─ SessionTracker.save_all_days()   (if save_interval met)
  │   └─ PersistenceManager.save_segments()
  │       ├─ optimize_segments(): filter → fill gaps → merge
  │       └─ rewrite activities-{year}.csv (newest-first)
  ├─ optimize_csv()                   (throttled: max once per 4 h)
  │   └─ optimize_year_file()
  └─ AppMenu.update_ui()              (main thread on macOS)
```

### CSV is the single source of truth

All aggregates (`get_minutes_for_date`, `get_weekly_minutes`) derive directly from `activities-{year}.csv`. No separate daily-summary file exists.

### Newest-first CSV rows

Rows are written with the latest `date start` first. Tests inspecting row order must account for this.

### Optimization pipeline

`PersistenceManager.optimize_segments()` runs per day before persistence:

1. `_filter_idle_boundary_segments()` — drop idle before first active or after last active end.
2. `fill_gaps_with_idle()` — synthesize idle segments for internal same-day gaps.
3. `merge_segments_to_save()` — merge consecutive same-state segments when gap <= idle threshold.

### Optimization throttling

- `save_segments()` optimizes saved days on every call.
- `ActivityTrackerApp._save_and_optimize()` runs full-year `optimize_csv()`:
  - immediately on Force Save,
  - at most every `OPTIMIZE_INTERVAL_SECONDS` (4 hours) for automatic saves.

### Constants

- `activitytracker/persistence.py`: `DEFAULT_IDLE_THRESHOLD_SECONDS = 300`
- `activitytracker/tracking.py`: `DEFAULT_TARGET_SECONDS`, `DEFAULT_WEEKLY_TARGET_SECONDS`, `DEFAULT_SAVE_INTERVAL_SECONDS`, `SLEEP_GAP_THRESHOLD_SECONDS`
- `activitytracker/app.py`: `POLL_INTERVAL_SECONDS = 10`, `OPTIMIZE_INTERVAL_SECONDS = 4 * 3600`

### Datetime handling

The codebase uses naive local datetimes. Tests patch `datetime.now()` in `activitytracker.tracking` and `activitytracker.models` to freeze time. Do not introduce timezone-aware datetimes without an explicit requirement change.

---

## Code Style

### General

- Keep functions small and focused.
- Prefer simple over clever.
- Optimize for readability first.

### Constants

- No magic numbers or strings.
- Extract recurring or meaningful values into named constants.
- Use enums for constrained value sets.
- Values defined by standards or protocols must use constants.
- Keep obvious one-time values inline when extraction harms readability.

Good:

```python
DEFAULT_IDLE_THRESHOLD_SECONDS = 300
```

Bad:

```python
idle_threshold = 300
```

### Parameters

- No positional boolean arguments.

Bad:

```python
save(data, True)
```

Good:

```python
save(data, overwrite=True)
```

### Control Flow

- Reduce indentation.
- Avoid the arrow anti-pattern.
- Prefer early return / early continue.
- Keep the happy path visually dominant.

Bad:

```python
if valid:
    if ready:
        if enabled:
            run()
```

Good:

```python
if not valid:
    return
if not ready:
    return
if not enabled:
    return
run()
```

### Formatting

- Blank lines between logical blocks.
- Group related statements; separate unrelated concerns.
- Follow `ruff format`.

### Comments

Explain what, why, constraints, assumptions. Never explain obvious syntax.

Good:

```python
# Retry because backend commits are eventually consistent.
```

Bad:

```python
# Increment index.
index += 1
```

Use examples where useful. For larger systems, use ASCII diagrams.

---

## Language-Specific Rules

### Python

- Follow repository conventions first; otherwise PEP 8.
- Type hints on all new public functions and methods.
- Never use mutable default arguments. Use `None` and construct inside the function.
- Check optionality with `is None`, not truthiness.
- Use `is` only for identity against `None`, `True`, `False`, and singletons. Everything else uses `==`.
- Always use context managers for resources. Never bare open/close.
- Docstrings per PEP 257 for public modules, classes, and functions. Private helpers only when non-obvious.
- No wildcard imports. No imports inside functions except to break genuine import cycles.
- Prefer dataclasses over hand-written `__init__` when the class is a data holder.
- Minimize global state. Prefer explicit imports.

### Other Languages

When adding non-Python code, apply the relevant subset from `AGENTS_TEMPLATE.md`.

---

## Design

### Visibility

- Private by default for fields and functions.
- Increase visibility only when required by design.
- Treat visibility increases as architectural changes.

Require explicit approval before widening visibility.

### Abstraction

Program to levels of abstraction. Isolate low-level mechanics behind drivers, adapters, gateways, or repositories:

- Raw hardware I/O
- File I/O
- Socket streams
- Database drivers
- Serialization
- External APIs

Domain and application code work with domain concepts, not implementation details.

### Layering

Strict hierarchy:

```text
UI
↓
Application
↓
Domain
↓
Infrastructure
```

A layer calls only the layer directly below it. UI/controllers never call raw drivers or low-level network clients directly.

### Dependencies

Before adding a dependency:

1. Check existing dependencies.
2. Prefer the standard library.
3. Justify large dependencies.
4. Avoid overlapping libraries.
5. Commit the lockfile in the same change. Never hand-edit lockfiles.

---

## Scope of Changes

- Only touch code required by the task.
- No drive-by reformatting, cleanup, renames, or comment edits.
- No architecture changes unless required.
- No large rewrites without approval.
- Do not mix refactoring with feature work.
- Minimize the number of modified lines.

---

## Error Handling

- Fail fast on programmer errors.
- Return actionable errors with useful context.
- Never silently ignore failures.
- No empty catch blocks.
- Preserve root-cause information where practical.
- Retried operations must be idempotent, or guarded by a dedup key.
- Retry budgets and backoff must be bounded and explicit.
- Never retry on programmer errors, only on transient faults.

---

## Security

- Never hardcode secrets or commit credentials.
- Never commit `.env`. Document required variables in `.env.example` and the README.
- Treat all external input as untrusted: validate and sanitize.
- Sanitize file paths.
- Follow least privilege.
- Do not log secrets, tokens, or PII.

---

## Logging

- Use appropriate levels: debug, info, warn, error.
- Log at boundaries: external calls, failures, state transitions.
- Never log secrets, tokens, or PII.
- Redact known-sensitive fields before logging request or response objects.
- Prefer structured logs where the codebase already uses them.

---

## Concurrency

- Prefer immutability and message passing over shared mutable state.
- Document thread-safety in the type or function docstring.
- Never hold a lock across I/O or a callback.
- Add tests for concurrent code when practical.

CSV reads/writes in this project are serialized via `PersistenceManager.csv_transaction()` (an `RLock`) to avoid races with the background updater thread.

---

## Data and Time

- This project uses naive local datetimes intentionally. Do not change without approval.
- In general projects: store and transmit timestamps in UTC; never do naive local-time arithmetic.
- Represent money as integer minor units or a decimal type, never as float.

---

## Database and Schema

- Migrations must be reversible; include a down migration.
- Never run destructive migrations without explicit approval.
- Never edit an already-applied migration.

---

## Generated and Vendored Code

- Do not edit generated files by hand. Regenerate from source.
- Do not modify vendored code. Patch upstream or wrap it.

---

## Performance

- Measure before optimizing.
- Optimize bottlenecks, not assumptions.
- Favor clarity unless requirements demand otherwise.
- Document non-obvious optimizations.

---

## Testing

### Bug Fix Workflow

1. Write a test that reproduces the bug.
2. Verify the test fails.
3. Implement the fix.
4. Verify the test passes.
5. Run relevant regression tests.

Do not fix a bug before a failing test exists unless a test is technically impossible.

### New Features

1. Add or update tests.
2. Verify expected behavior.
3. Verify no regressions.

### Rules

- Never delete failing tests to make the build pass.
- Prefer deterministic tests.
- Keep tests readable.
- Test observable behavior.
- Unit tests exercise pure logic; do not reach into the database, network, or filesystem.
- Integration tests may use real dependencies but must be isolated and cleaned up.
- Do not mock what you own; mock only the boundary.

---

## Refactoring

Allowed: extract functions, improve naming, remove dead code, improve testability, simplify control flow.

Avoid: large rewrites without approval, mixing with feature work, unnecessary public API changes.

---

## Documentation

- Update the README when behavior, setup, or configuration changes.
- Update user-facing docs when user-facing behavior changes.
- Record non-obvious architectural decisions in an ADR if the repository uses them.
- Do not create documentation that was not requested.

---

## Commit Messages

Format:

```text
Subject

Body
```

Rules:

1. Blank line between subject and body.
2. Subject ≤ 50 characters (hard limit 72).
3. Capitalize the first letter.
4. No trailing period.
5. Imperative mood — test: "If applied, this commit will <subject>."
6. Wrap body at 72 characters.
7. Body explains what and why, not how.

---

## Workflow

After every meaningful change:

1. Build.
2. Run tests.
3. Run lint.
4. Run type checks.
5. Review modified files.

Before finishing:

- Tests, lint, type checks, formatting pass.
- Debug code and temporary files removed.

---

## Before Claiming Done

Run `git diff` and read every changed line as a reviewer:

- Is every changed line required by the task?
- Any debug code, debug logs, or commented-out code left behind?
- Any unrelated formatting churn?
- Any invariant weakened elsewhere by these changes?

If this review finds something, fix it before reporting completion.
Do not report a task as done without having read the diff.

---

## Git Rules

Never run a git command that discards work, rewrites history, or pushes to a remote, unless explicitly instructed. Examples:

```bash
git commit
git push
git rebase
git reset
git reset --hard
git clean -fd
git checkout -- .
git restore .
git stash drop
git branch -D
git tag -d
git filter-branch
```

---

## Agent-Specific Rules

- Preserve existing architecture.
- Follow local code patterns.
- Reuse existing utilities where appropriate.
- Prefer the smallest correct change.
- Do not invent APIs, files, commands, or behavior.
- Verify changes through tests whenever possible.

---

## When Rules Conflict

Priority, highest first:

1. Safety — do not break security, data integrity, or the build.
2. Correctness — the task's stated requirements.
3. Tests — reproduce, verify, regress.
4. Consistency with the existing codebase.
5. Minimal diff.
6. Style preferences.

If two rules are genuinely incompatible, stop and state the conflict.

---

## Verify Before Asserting

Before stating that a function, file, command, flag, or config option exists or behaves a certain way:

1. Grep for the symbol or search for the file.
2. Run `--help` or read the definition.
3. If you cannot verify, say "unverified" rather than stating it as fact.

---

## Do Not

- Write a helper for a single call site.
- Add "just in case" validation for internal inputs already validated at the boundary.
- Add logging on every function entry/exit.
- Leave `TODO`, `FIXME`, or commented-out code.
- Write docstrings for trivial getters or overrides.
- Catch `Exception` / `Error` / `error` broadly.
- Add a public method to every class you touch.
- Reformat files you did not otherwise need to change.
- Reimplement a utility that exists in the repo.
- Create a new file when an existing one would do.
- Add a base class or interface for a single implementation.

---

## If Blocked

If blocked (missing input, credentials, service, or file):

- Stop.
- Report the blocker in one line.
- State exactly what information or access would unblock you.

Do not attempt workarounds that modify infrastructure, secrets, or CI.

---

## This File

- Do not modify `AGENTS.md` unless the user explicitly asks.
- If a rule seems wrong, report it; do not silently edit around it.

---

## Definition of Done

### Verifiable — required

- Requirements satisfied.
- Build, tests, lint, type checks pass.
- `git diff --stat` shows only files required by the task.
- Bug fixes ship with a test that fails without the fix.
- No debug code, temp files, or commented-out code.
- Documentation updated when required.

### Judgment — required

- Solution is understandable by another engineer.
- No new abstractions for single use.
- No rules in this file were silently broken.
