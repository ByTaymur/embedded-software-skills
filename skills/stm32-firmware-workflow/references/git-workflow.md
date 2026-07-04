# Git & Session Workflow

Applies when the project `CLAUDE.md` marks the session protocol as Active. If inactive, skip and just commit normally with the message format below.

## File layout conventions

A typical project separates active code, docs, and archive:

```
<project>/
├── CLAUDE.md                 # project memory (sub-rules) — read first
├── firmware/                 # ACTIVE code (changes go here)
│   ├── Src/ Inc/ Drivers/
│   └── <project>.ioc
├── docs/                     # documentation
│   ├── hardware/  software/  motors/
│   └── changelog/GUNLUK.md   # development log (updated each session end)
└── archive/                  # READ-ONLY old versions / reference projects
```

> Never edit `archive/`. Active work is in `firmware/`. Docs are updated in the same commit as the change they describe.

## Branch rule

Every new piece of work starts on its own branch. Never commit directly to `main`.

```
Branch name: YYYY-MM-DD-<topic>
Examples:    2026-06-03-pid-tuning | 2026-06-04-uart-debug | 2026-06-10-jupa-support
```

## Commit rule

Every change is committed; size does not matter. Message format:

```
YYYY-MM-DD: <what changed>
Example:    2026-06-02: <config-header> - updated <parameter> value
```

Use `git add -p` to stage deliberately. Keep commits focused (matches the scope contract).

## Session start

```bash
# 1. Push the previous branch if it has pending changes
git status
git push origin <previous-branch>     # skip if nothing pending

# 2. Update main
git checkout main
git pull

# 3. Open a new branch
git checkout -b YYYY-MM-DD-<topic>
```

Then read the project `CLAUDE.md` and give the user a 3–4 line summary (in Turkish): MCU, active parameters, open "Known Issues".

## Session end

```bash
# 1. Update the development log (docs/changelog/GUNLUK.md), entry format:
#    ## YYYY-MM-DD
#    **Branch:** <branch>
#    **Done:** ...
#    **Files changed:** ...
#    **Result:** ...
#    **Next step:** ...

# 2. If hardware/software changed, update the relevant CLAUDE.md section.

# 3. Commit and push
git add -p
git commit -m "YYYY-MM-DD: <description>"
git push origin <branch>
```

## Merge policy

```bash
git checkout main
git merge --no-ff YYYY-MM-DD-<topic>
git push
```

`--no-ff` keeps each work unit visible in history. Do not fast-forward or commit straight to `main`.

## Slash commands

- `/new-project` — onboarding interview → generate project `CLAUDE.md`.
- `/session-start` — push previous branch, update main, open new branch, summarize `CLAUDE.md`.
- `/session-end` — update dev log + `CLAUDE.md`, commit, push.

Copy `commands/*.md` into the project's `.claude/commands/` to enable them.
