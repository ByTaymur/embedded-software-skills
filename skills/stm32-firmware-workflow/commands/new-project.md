---
description: Start a new project — collect rules from the user, generate the project CLAUDE.md (sub-rules), confirm
---

When the project root has no `CLAUDE.md`, or we are setting up a new project:

1. Follow `references/new-project-bootstrap.md` from the `stm32-firmware-workflow` skill.
2. Ask the user (in Turkish) for every item: MCU, clock/power, **detailed pinout (pin, signal, direction/mode, AF, pull, speed, active/init, PCB traps)**, peripheral/DMA/IRQ map, software architecture, parameter source, known issues, file layout, git/session protocol, project-specific extra rules. Assume nothing; carry no values from other projects.
3. Fill `references/CLAUDE.md.template` with the answers and write it to the project root as `CLAUDE.md`.
4. Show a summary in Turkish, ask for confirmation. Once approved, run the project on these sub-rules + the skill's main rules.

Mark any unknown item "TBD"; never invent it. Reply to the user in Turkish.
