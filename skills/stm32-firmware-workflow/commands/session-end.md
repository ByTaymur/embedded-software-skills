---
description: End a session — update dev log, commit, push the branch
---

Run in order:

1. Add an entry to the development log (the file named in the project `CLAUDE.md`, e.g. `docs/changelog/GUNLUK.md`):
   ```
   ## YYYY-MM-DD
   **Branch:** <branch>
   **Done:** ...
   **Files changed:** ...
   **Result:** ...
   **Next step:** ...
   ```
2. If hardware/software changed, update the relevant section of the project `CLAUDE.md`.
3. `git add -p`
4. `git commit -m "YYYY-MM-DD: <short description>"`
5. `git push origin <branch>`

Never commit/merge directly to `main`. Do not narrate; just execute. Reply to the user in Turkish.
