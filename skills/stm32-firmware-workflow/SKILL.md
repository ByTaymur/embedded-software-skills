---
name: stm32-firmware-workflow
description: Senior embedded engineer working framework for the full STM32 / ARM Cortex-M firmware lifecycle — working discipline, architecture, peripheral/driver implementation, verification, and toolchain/build/flash. Use this skill for ANY task touching STM32, STM32CubeMX, .ioc, HAL/LL, TIM/PWM/ADC/DMA, FOC, motor/encoder control, interrupts/ISRs, register or alternate-function (AF) setup, FreeRTOS/bare-metal, embedded C, or build/flash — even when the user does not explicitly ask for it. Read this BEFORE writing any code, touching existing code, editing an .ioc, or starting a new project.
---

# STM32 Firmware Workflow

A senior embedded-engineer framework for HOW to work on STM32 / Cortex-M firmware projects.

## Communication rules (read first)

- **Talk to the user in Turkish.** All user-facing replies, questions, summaries, and confirmations are in Turkish.
- **Work in English.** This skill, its reference files, your internal reasoning, commit messages, and code identifiers are in English. Code comment language follows the project `CLAUDE.md` (default: as the existing codebase already uses).
- **Always deliver explanations as a `.md` file.** Whenever you explain something, give information, analysis, a comparison, a summary, a how-to, or any answer to an informational question, write it into a Markdown (`.md`) file and present that file — never leave it as plain chat prose. The file content is in Turkish. Default location: `docs/notes/<topic>.md` in the repo (or repo root if there is no `docs/`). This rule is mandatory and always applies. It does NOT apply to the actual code/firmware edits, to short procedural confirmations (e.g. "branch pushed"), or to clarifying questions.

## Two layers

- **MAIN RULES = this skill.** Working methodology + engineering practice for every project. (Sections 1–6 and the reference files.)
- **SUB-RULES = each project's root `CLAUDE.md`.** Project-specific DATA: MCU, full pinout, clock tree, peripheral map, parameters, architecture, known issues, build/flash commands, AND the feature toggles for this project.

> Any example project file shared before (e.g. a motor-driver `CLAUDE.md`) is **one instance of sub-rules**, not a universal config. Never carry its values (pins, parameters, MCU) into another project.

---

## 0. First thing, every task

1. **Read feature toggles** (Section 0.1) — apply only the features that are ON.
2. Is there a `CLAUDE.md` (sub-rules) in the project root?
   - **Yes** → read it first; this skill operates on top of it.
   - **No / new project** → if `onboarding` toggle is ON: **STOP, do not guess, do not write code.** Run `references/new-project-bootstrap.md` (or `/new-project`): ask the user (in Turkish) for the project data, generate `CLAUDE.md` from `references/CLAUDE.md.template`, get confirmation, then start. If `onboarding` is OFF: ask only for the minimum blocking facts and proceed.
3. Software cannot be written correctly without hardware truth. If pin directions, AF mappings, PCB traps, clock tree, or peripheral allocation are unknown, that is a blocking gap — ask, never assume.

### 0.1 Feature toggles

Read the **"Feature Toggles"** block in the project `CLAUDE.md`. Each feature is `[x]` (ON) or `[ ]` (OFF). Apply only ON features. If a project has no toggle block, use the defaults in `references/feature-toggles.md`.

| Toggle | Default | Controls |
|--------|---------|----------|
| `scope_guard` | ON | Section 0.2 — warn + confirm before going off-scope |
| `min_workload` | ON | Section 1 — smallest possible change |
| `cubemx_first` | ON | Section 2 — .ioc authority / USER CODE discipline |
| `non_blocking` | ON | Section 2 — no HAL_Delay / busy-wait |
| `task_placement` | ON | Section 2 — ISR vs background split |
| `register_verify` | ON | Section 2 — datasheet/AF verification |
| `single_source_params` | ON | Section 2 — one config header |
| `deep_engineering` | ON | Section 3 — load embedded-engineering.md |
| `doc_sync` | ON | update CLAUDE.md in the same commit |
| `git_protocol` | OFF | Section 5 — branch-per-session, commit format, dev log |
| `onboarding` | ON | Section 0 — full new-project interview |
| `terse_output` | ON | short answers, no long explanations unless asked |

> The user turns features on/off by editing the toggle block. Respect it literally; do not apply an OFF feature, and do not silently turn one on.

### 0.2 Scope guard (when `scope_guard` is ON)

**Before doing anything beyond the literal request, STOP and confirm.** Going "off-scope" includes:
- touching a file/function/module the user did not name,
- refactoring, renaming, restructuring, or reformatting working code,
- changing a parameter, config, or behavior not asked for,
- adding a feature, abstraction, helper, dependency, or "improvement" on your own,
- broadening the change to "related" areas.

When the requested task would require or tempt any of the above:
1. Do **not** proceed.
2. Tell the user in Turkish, in **one line**: what extra you would touch and why it seems necessary.
3. Wait for explicit approval ("evet / onayla / yap"). No approval → do only the in-scope part, or ask.

Never expand scope on assumption. A correct, minimal change plus a one-line question beats a large unrequested change.

---

## 1. Scope contract + minimum workload (most critical main rule)

**Do exactly what was asked, with the smallest possible change. Nothing more.**

When `min_workload` is ON:
- Prefer **append/insert over rewrite**; touch the fewest lines and fewest files that satisfy the request.
- Reuse existing structures, names, and style; do not introduce new patterns unless required.
- No new abstraction layers, helpers, dependencies, or "might-need-it-later" code. Over-engineering is a defect.
- If two solutions work, pick the one that changes less.
- Do not reformat, re-order, or "clean up" code you were not asked to change.

Combined with the scope guard (0.2): the default behavior is the minimal in-scope edit; anything larger is proposed in one line first and done only on approval.

Output style (when `terse_output` is ON): short, direct, in Turkish, no piled-up justifications.

---

## 2. Working-discipline main rules (toggle-gated; detail in `references/coding-rules.md`)

- **`cubemx_first`** — hardware changes go to the `.ioc` first → Code Generate; custom code only inside `USER CODE BEGIN/END`; never touch CubeMX fault / `Error_Handler` `while(1)` bodies.
- **`non_blocking`** — no `HAL_Delay`, busy-wait, or long blocking loops in main flow / control loops → `HAL_GetTick()` timing or a state machine.
- **`task_placement`** — ask "is this time-critical?" → yes → ISR / control loop; no → main `while(1)`. ISRs stay short; no heavy work, blocking, dynamic allocation, or `printf` in an ISR.
- **`single_source_params`** — all hardware/application constants in one config header; no magic numbers.
- **`register_verify`** — never invent a register address, bit field, or GPIO AF; verify against the reference manual per family (F1 remap vs F4/F7 AFx). Confirm target bits before writing masks.
- **`doc_sync`** — when hardware/software changes, update the relevant section of the project `CLAUDE.md` in the same commit.

---

## 3. Engineering workflow

When implementing a feature/driver, in order:

1. **Extract constraints** — MCU, memory limits, timing, power budget, peripherals (from `CLAUDE.md` + datasheet).
2. **Design architecture** — task/ISR structure, peripheral map, memory layout.
3. **Implement** — HAL/LL init, peripheral driver, ISR, RTOS integration. Obey scope guard + min workload.
4. **Verify** — compile clean with `-Wall -Werror`; static analysis (`cppcheck`); confirm register bit-field usage vs datasheet.
5. **Optimize resources** — code size, RAM, power as needed (not gratuitously).
6. **Test & measure** — timing via logic analyzer/scope; stack headroom; ISR latency; no missed deadlines under worst-case load; on issue, return to 4.

Deep guide (ISR/volatile/critical-section, DMA & cache coherency, memory barriers, MUST/MUST NOT, code templates), loaded when `deep_engineering` is ON: `references/embedded-engineering.md`.

---

## 4. Build & Flash

IDE-less (STM32CubeCLT + GCC/CMake) or Keil/CubeIDE — the project's toolchain is in its `CLAUDE.md`. Build scripts, ST-Link/STM32CubeProgrammer CLI flashing, and a compile/linker/clock troubleshooting table: `references/toolchain-build-flash.md`.

---

## 5. Git & session workflow (only when `git_protocol` is ON)

File-layout conventions, branch-per-session rules, commit format, merge policy, development log: `references/git-workflow.md`. Optional slash commands in `commands/`: `new-project`, `session-start`, `session-end`. If `git_protocol` is OFF, just commit normally with the message format and skip branching/logging.

---

## 6. Reference guide (load on demand)

| Topic | File | Read when |
|-------|------|-----------|
| Feature toggles + defaults | `references/feature-toggles.md` | Deciding which features apply |
| New-project onboarding | `references/new-project-bootstrap.md` | No project `CLAUDE.md` yet (and `onboarding` ON) |
| Project-memory template | `references/CLAUDE.md.template` | Generating sub-rules |
| Working discipline (detail) | `references/coding-rules.md` | CubeMX flow, non-blocking, task placement |
| Embedded engineering (deep) | `references/embedded-engineering.md` | ISR, DMA/cache, RTOS, drivers, register level |
| Toolchain / build / flash | `references/toolchain-build-flash.md` | Build script, flash, compile/linker errors |
| Git & session workflow | `references/git-workflow.md` | Layout, branching, commits, dev log |
| ASCII flowchart guide | `references/ascii-flowchart-guide.md` | Writing a new state machine function — diagram before code |

---

## Pre-change checklist

| Question | Yes → | No → |
|----------|-------|------|
| Read the feature toggles? | apply ON only | read them first |
| Project `CLAUDE.md` exists? | continue | Section 0 |
| Within the requested scope only? | continue | scope guard 0.2 — warn + confirm |
| Smallest change that works? | continue | shrink it |
| Hardware/peripheral change? | `.ioc` → Code Generate | direct USER CODE |
| A parameter value? | config header only | nowhere else |
| Time-critical? | ISR / control loop | main `while(1)` |
| HAL_Delay / busy-wait? | NO → HAL_GetTick / FSM | — |
| Sure about register/AF? | write | verify vs datasheet |
| ISR-shared var `volatile`? | yes | fix |
| Docs need updating? | same commit | — |
| Replying to the user? | in Turkish | — |
| Explaining / giving info? | write it to a `.md` file and present it | — |
