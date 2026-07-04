---
description: Start a session — push previous branch, update main, open a new branch, summarize project CLAUDE.md
---

Run in order, show output:

1. `git status` — if there are pending changes, push the current branch: `git push origin <branch>`.
2. `git checkout main && git pull`
3. Ask the user (in Turkish) for the session topic, then `git checkout -b YYYY-MM-DD-<topic>` (today's date).
4. Read the project `CLAUDE.md` and give a 3–4 line summary in Turkish: MCU, active parameters, open "Known Issues".

If there is no `CLAUDE.md`, switch to the `/new-project` flow. Do not narrate; just execute. Reply in Turkish.
