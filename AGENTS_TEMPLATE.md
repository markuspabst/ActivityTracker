# AGENTS.md

## Project Configuration

| Field | Value |
|---|---|
| Language / Runtime | |
| Build Command | |
| Test Command | |
| Lint Command | |
| Type Check Command | |
| Run Command | |
| Entry Points | |
| Key Directories | |
| Important Files | |
| Required Env Vars | |
| Domain Glossary | (see below) |

If a field is blank, detect it from the repository (`package.json`, `Cargo.toml`, `Makefile`, CI config, lockfiles) before reading or writing code. Report what you detected in one line and proceed. Ask only if detection is genuinely ambiguous.

### Domain Glossary

- `<term>`: `<one-line meaning>`
- `<term>`: `<one-line meaning>`

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

```cpp
constexpr int HttpOk = 200;
```

Bad:

```cpp
if (response.code == 200) {}
```

### Parameters

- No positional boolean arguments.

Bad:

```cpp
Save(data, true);
```

Good (Python):

```python
Save(data, overwrite=True)
```

Good (typed languages):

```cpp
Save(data, SaveMode::Overwrite);
```

- In statically typed languages, prefer enums or option objects over booleans.
- In Python, keyword booleans are acceptable when the parameter name states the meaning.

### Control Flow

- Reduce indentation.
- Avoid the arrow anti-pattern.
- Prefer early return / early continue.
- Keep the happy path visually dominant.

Exception: in C, once a resource has been acquired, prefer `goto cleanup` over early return so every error path frees the resource. See Language-Specific Rules → C.

Bad:

```cpp
if (valid) {
    if (ready) {
        if (enabled) {
            Run();
        }
    }
}
```

Good:

```cpp
if (!valid) return;
if (!ready) return;
if (!enabled) return;
Run();
```

### Formatting

- Blank lines between logical blocks.
- Group related statements; separate unrelated concerns.
- Follow repository formatter settings if present.

### Comments

Explain what, why, constraints, assumptions. Never explain obvious syntax.

Good:

```cpp
// Retry because backend commits are eventually consistent.
```

Bad:

```cpp
// Increment index.
index++;
```

Use examples where useful. For larger systems, use ASCII diagrams:

```text
+-----------+     +-----------+     +-----------+
| UI        | --> | Service   | --> | Storage   |
+-----------+     +-----------+     +-----------+
```

---

## Language-Specific Rules

Language-specific rules override the general style rules when they conflict.

### C / C++ / C# / Java / Go

- Always use braces, even for single-line blocks.
- Keep scope as small as possible.

### C

- Every allocation has exactly one matching free on every path, including error paths. Prefer `goto cleanup` over early return once a resource is held.
- Document ownership for every pointer parameter and return: caller-owned, callee-owned, or borrowed.
- Never use `strcpy`, `strcat`, `sprintf`, `gets`. Use `strlcpy`, `strncat`, `snprintf`, `fgets` with explicit bounds.
- Every header has an include guard or `#pragma once`.
- Use `enum` or `static const` for constants; reserve `#define` for macros and conditional compilation.
- Check integer arithmetic for overflow and unsigned wraparound.
- No implicit casts. Cast explicitly, and only when correct.
- Build with `-Wall -Wextra -Werror`. Run tests under ASan and UBSan.
- Errors are returned, not signaled by sentinel values mixed into valid output. Use `errno` for system failures.

### C++

- Prefer RAII.
- Prefer smart pointers over raw ownership. `std::unique_ptr` by default; `std::shared_ptr` only when sharing is required by the design.
- Never `new` or `delete` directly. Use `std::make_unique` / `std::make_shared`.
- Rule of Zero; if forced, Rule of Five with `= default`.
- Move constructors, move assignment, and `swap` are `noexcept`.
- Destructors do not throw.
- Use `const` wherever practical. Use `constexpr` for compile-time values.
- Prefer `std::string_view` and `std::span` for non-owning parameters.
- Prefer `std::optional` / `std::expected` over sentinel values.
- Prefer STL algorithms over hand-rolled loops when they fit.
- Mark overrides `override`; mark closed methods `final`.

### Python

- Follow repository conventions first; otherwise PEP 8.
- Type hints on all new public functions and methods.
- Never use mutable default arguments. Use `None` and construct inside the function.
- Check optionality with `is None`, not truthiness. `if not value` is a different question.
- Use `is` only for identity against `None`, `True`, `False`, and singletons. Everything else uses `==`.
- Always use context managers for resources: `with open(...)`, `with lock`, `with session`. Never bare open/close.
- Docstrings per PEP 257 for public modules, classes, and functions. Private helpers only when non-obvious.
- No wildcard imports. No imports inside functions except to break genuine import cycles.
- Prefer dataclasses over hand-written `__init__` when the class is a data holder.
- Minimize global state. Prefer explicit imports.

### Rust

- Prefer ownership-safe designs.
- Avoid unnecessary cloning.
- Use `Result` and `Option` idiomatically.
- Prefer compile-time correctness over runtime checks.

### Go

- Follow standard Go formatting.
- Return early on errors.
- Keep interfaces small.
- Avoid unnecessary abstractions.

---

## Design

### Visibility

- Private by default for fields and functions.
- Increase visibility only when required by design.
- Treat visibility increases as architectural changes.

Require explicit approval before changing `private → internal/protected/public` or `internal → public`.

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

- A layer may only call the layer directly below it.
- Never bypass intermediate layers.
- Never punch holes through the architecture.

Forbidden: `UI → Database`, `UI → Hardware Driver`, `Controller → SQL`, `Controller → Socket`.

Required: `UI → Application → Domain → Infrastructure`.

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
- Redact known-sensitive fields (`authorization`, `cookie`, `password`, `token`, `secret`, `api_key`) before logging request or response objects.
- Prefer structured logs where the codebase already uses them.

---

## Concurrency

- Prefer immutability and message passing over shared mutable state.
- Document thread-safety in the type or function docstring.
- Never hold a lock across I/O or a callback.
- Add tests for concurrent code when practical.

---

## Data and Time

- Store and transmit timestamps in UTC.
- Never do naive local-time arithmetic.
- Represent money as integer minor units or a decimal type, never as float.

---

## Database and Schema

- Migrations must be reversible; include a down migration.
- Never run destructive migrations (`DROP`, `TRUNCATE`, column removal) without explicit approval.
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

Examples:

```text
Fix timeout handling
```

```text
Add retry for transient errors
```

If the repository already enforces a commit convention (commitlint, husky, PR template, CI lint), follow the repository's convention instead of the rules above.

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
