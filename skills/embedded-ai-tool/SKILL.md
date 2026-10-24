---
name: embedded-ai-tool
description: Live, policy-guarded access from an AI agent to a running microcontroller, through a debug probe (OpenOCD with ST-Link, J-Link, CMSIS-DAP, ...) or a serial link to a small stub in the firmware. Use when the user wants to see or change what a connected board does: read registers or variables by name (SVD/ELF), watch values over time, drive or reconfigure a pin (GPIO, PWM, UART recipes), measure signals on the target, load or change a small live program (thresholds, timers, events) without reflashing, check board identity and build, collect fault evidence, or build/flash firmware on request. Works for any MCU family through profile and data files. Not needed for source-only edits.
---

# Embedded AI Tool

Connects you to a real board so firmware work is measured, not guessed. Reply to the user in
their language. Everything board-specific (addresses, pins, limits, build commands) lives in the
target project's **profile** and data files, never in this skill.

## 1. Before anything: what is available?

1. **MCP tools present?** If tools named `mcp__embedded-ai-tool__*` (or an `embedded-ai-tool`
   MCP server) exist, use them — same commands over one held session, heartbeat included.
2. **Otherwise use the CLI:** `python "<this-skill-dir>/scripts/eat.py" --profile <board.json> <command>`.
   Resolve `<this-skill-dir>` from this file's location. Every command prints one JSON object.
   Missing dependencies: `python -m pip install "<this-skill-dir>"` (adds `pyserial` with `[serial]`).
3. **Profile present?** Look for the project's `board.json` (often `debug/<board>/board.json`,
   or as named in the project's agent instructions). No profile → onboarding in
   [references/usage.md](references/usage.md) ("Yeni kart"); ask only for facts that block you
   (UID location, memory ranges, probe config). Never invent addresses.
4. **Sanity check:** `doctor` (offline), then `identity` (is the expected board attached?).

## 2. Pick the operation

| The user wants to… | MCP tool | CLI | Read first |
|---|---|---|---|
| Confirm the right board / firmware | `target_identity`, `verify_build` | `identity`, `verify` | — |
| Read a register by name, decoded | `read_register`, `list_registers` | `reg read`, `reg list` | live-control.md §SVD |
| Read firmware variables | `read_variables`, `watch_variables` | `read`, `watch-variables` | usage.md |
| Read / write raw memory | `peek`, `poke` | `peek`, `poke` | live-control.md |
| Make a pin output/input/PWM/UART | `pin_list`, `pin_apply`, `pin_release`, `pin_restore` | `pin …` | live-control.md |
| Put every claimed pin in its safe state | `safe_state` | `safe` | — |
| Measure a signal on the target | `measure` | `measure` | stub-protocol.md §Örnekleyici |
| Run logic on the target, change it live | `program_get`, `program_set`, `task_add`, `task_remove`, `param_set`, `events_read` | `program …` | interpreter-design.md |
| Find out why it crashed | `fault_evidence` | `fault` | live-control.md §Fault |
| Run native code from RAM | `ram_build`, `ram_load`, `ram_run` | `ram …` | live-control.md §RAM |
| Build / flash / halt / reset | — (CLI only) | `build`, `flash`, `control` | usage.md |
| Check the stub on the board | `stub_status` | `stub status` | stub-protocol.md |

Pin, measure, program and RAM features need the **stub** linked into the firmware
([stub/README.md](stub/README.md)); reads, `poke`, build and flash do not.

## 3. Rules you must follow

1. **Plan, then execute.** Every mutating command returns a plan unless `--execute` (CLI) or
   `execute: true` (MCP) is given. Show the plan; execute only within what the user asked for.
2. **Never retry an uncertain mutation.** A timeout or `unknown_if_sent` may have happened on the
   board. Re-read identity and state, report what is unknown, let the user decide.
3. **Never widen permissions.** Do not edit `write_ranges`, `protected`, pin `functions` or limits to
   make a command pass. Never reconfigure debug or serial-link pins. Refusals are the policy working.
4. **Readback is not physical proof.** A register value says what was written, not what the pin did.
   Ask the user to observe, or measure. Application firmware may rewrite a pin you claimed: sample it.
5. **Stub outputs revert.** With the stub, claimed pins return to their safe state after
   `heartbeat_timeout_ms` unless `mcp`/`serve` keeps the heartbeat. Say so for one-shot commands.
6. **Emergency stop:** `safe_state` with `all: true, execute: true` (CLI `safe --all --execute`).
7. **Do not claim hardware support from host tests.** Check the evidence table in
   [references/live-control.md](references/live-control.md) (host test / board run / physical
   measurement) before saying something works on a board.
8. **Keep board data out of shared repos.** Profiles, UIDs, firmware images (ELF/AXF/HEX/BIN) and
   session logs stay in the target project or the user's machine.

## 4. Typical session

```text
python <tool> doctor
python <tool> --profile debug/my-board/board.json identity
python <tool> --profile debug/my-board/board.json reg read GPIOA.MODER
python <tool> --profile debug/my-board/board.json pin apply LED gpio_out --param level=1     # plan
python <tool> --profile debug/my-board/board.json pin apply LED gpio_out --param level=1 --execute
python <tool> --profile debug/my-board/board.json pin release LED --execute
```

Names (`LED`, `GPIOA.MODER`) come from the profile and its SVD; they are examples here.
Results and intent are recorded under `sessions/` (`--session-dir` to change).

## 5. Reference map (load on demand)

| File | When |
|---|---|
| [references/usage.md](references/usage.md) | Install, new board profile, OpenOCD config, build/flash, CLI flow |
| [references/live-control.md](references/live-control.md) | Live control, profile `live`/`pins` fields, SVD, MCP setup, evidence table, safety layers |
| [references/stub-protocol.md](references/stub-protocol.md) | Mailbox, serial link frame, sampler — when touching the stub or transport |
| [references/interpreter-design.md](references/interpreter-design.md) | Live programs on the target: JSON program, instruction set, limits |
| [references/lessons.md](references/lessons.md) | Interpreting measurements, planning a mutation, diagnosing timeouts |
| [stub/README.md](stub/README.md), [stub/ports/](stub/ports/) | Adding the stub to a firmware, example ports per architecture |

## 6. Maintaining this skill

Runtime `scripts/embedded_ai_tool/`, launcher `scripts/eat.py`, target C code `stub/`, tests `tests/`.
From the skill directory: `python -m pip install -e ".[dev]"`, `python -m pytest -q`,
`python -m ruff check .`, `python tests/package_smoke.py`. Unexpected skips fail the suite;
hardware tests run only with `EAT_HW_PROFILE` ([tests/hardware/README.md](tests/hardware/README.md)).
Status: alpha. Host tests are not board verification.
