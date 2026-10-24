---
name: embedded-ai-tool
description: Develop and inspect firmware using profile-driven OpenOCD access through ST-Link or another supported debug probe. Use for live memory readings, ELF/AXF symbol inspection, timed traces, identity/build verification, and requested build, flash, or target control. Source-only edits do not require this skill.
---

# Embedded AI Tool

Use the bundled JSON CLI to connect firmware development with measured target behavior.
Communicate with the user in Turkish. This skill is a host tool, not a board-specific
firmware project. Keep MCU data, paths, limits, and build commands in the target project's profile.

## Entry point and setup

Resolve this skill's installed directory from this file. Run the bundled
`scripts/eat.py` with Python 3.11+; do not assume the current working directory is
the skill directory. It imports the adjacent package and needs no sibling repository.
Install the skill package with `python -m pip install "<skill-directory>"` in the
chosen environment if dependencies are absent. This also provides `eat`.

Read [references/usage.md](references/usage.md) when creating a profile, configuring
OpenOCD, or using build/flash. Read [references/lessons.md](references/lessons.md)
when interpreting live data, planning a mutation, or diagnosing a timeout.

## Work from project truth

Read the target project's agent instructions and hardware/build documentation.
Reuse its profile if present. For a new profile, use `init` and fill in the actual
MCU UID location, byte order, memory ranges, ELF hash, and variable types from
verified documentation. Ask only for missing facts that block the requested work.
The generated template deliberately cannot connect until these facts are supplied.

ST-Link is a probe; the API is **OpenOCD Tcl RPC**, normally port 6666. Telnet and
GDB ports are different protocols. Use an existing prepared server or the project's
reviewed OpenOCD configs. Do not terminate another debug session automatically.

## Commands

From the target project's working directory, replacing `<tool>` with the resolved
path to this skill's `scripts/eat.py`:

```text
python <tool> doctor
python <tool> init debug/my-board --name my-board
python <tool> --profile debug/my-board/board.json identity
python <tool> --profile debug/my-board/board.json verify
python <tool> --profile debug/my-board/board.json read counter temperature
python <tool> --profile debug/my-board/board.json reg read PORT.MODE PORT.MODE.STATE  # reg list [PERIPHERAL] [--filter TEXT] is offline
python <tool> --profile debug/my-board/board.json watch counter --duration 10 --interval 0.1
python <tool> --profile debug/my-board/board.json search counter
python <tool> --profile debug/my-board/board.json build
python <tool> --profile debug/my-board/board.json write counter 42
python <tool> --profile debug/my-board/board.json flash
```

`symbols <elf>` and `probe-uid <documented-address> <byte-size>` support onboarding;
see the usage reference. Names in examples are illustrative, not required variables.
JSON outputs and operation intent/results are recorded under `sessions/` in the
working directory; set `--session-dir` to the project's required evidence directory.

## Execution and evidence

- `write`, `build`, `flash`, `openocd`, and `control` return an offline plan unless
  `--execute` is supplied. Use it only within the user's authorized task. Existing
  authorization persists; the tool adds no interactive approval loop.
- Verify physical target UID and the relevant build before interpreting symbol-based
  readings. `write` also compares all file-backed flash PT_LOAD bytes before writing,
  then checks UID in the same Tcl request as the mutation. An ELF hash alone is not
  proof that the board is running that build.
- Use only reviewed profile variables and limits for writes. Register access width
  and read side effects come from the MCU manual. Do not reuse another board's values.
- A timed-out mutation may have happened. Do not retry it automatically; reacquire
  identity and state, and report what remains unknown.
- Traces are sequential observations, not atomic snapshots or real-time control.
  Readback is not proof of physical success. Evaluate the project's actual acceptance criteria.
- Flash uses a file visible to both tool and OpenOCD. Remote file transfer is not
  implemented. Socket close never resets/resumes the CPU or shuts down the server.

## Live RAM-only control (stub mode)

When the user wants the AI to drive pins and peripherals directly from RAM, with no
firmware flashed per task, read [references/live-control.md](references/live-control.md)
first (and [references/stub-protocol.md](references/stub-protocol.md) when touching the
mailbox). Commands: `peek`, `poke`, `pin list|apply|release|restore`, `safe`,
`ram build|load|run`, `stub status`, `serve`, `mcp`. Mutations are plans until `--execute`.
Profiles choose `connection.transport`: `openocd` (debug probe) or `serial` (the stub's UART/USB link,
for probe-less targets or families OpenOCD does not cover). If the `embedded-ai-tool` MCP server is connected, prefer its tools (`peek`, `pin_apply`, …):
they are the same commands over one held session; mutating tools need `execute: true`.

- Never invent MCU facts. Pin/function/register recipes come from a reviewed MCU data
  file (`live.mcu_db`); the files under `references/examples/` are fictional.
- Only profile pins, functions and ranges are allowed. Never lift a `protected` pin or
  range, and never reconfigure debug pins. Do not widen `write_ranges` to make a command pass.
- After `pin apply`, measure the physical result (readback is only a register check). If a
  step is `partial` or `unknown_if_sent`, do not retry; measure, then choose `pin release`,
  `pin restore` or `safe`. Use `safe --all --execute` as the emergency stop.
- With a stub configured, outputs revert after `heartbeat_timeout_ms` unless `serve` or
  `mcp` is running. Tell the user this when a one-shot command is expected to persist.
- The stub core is MCU-independent and host-tested only. A port for the user's MCU and
  measurement on a real board are required before claiming it works on hardware.

For source changes, follow the target project's editing discipline. If installed,
`stm32-firmware-workflow` and `firmware-source-editor` complement this tool;
neither is required to run this self-contained skill on other supported targets.
The CLI supplies no LLM/web server and no universal motor-control routines; `mcp` is a
stdio MCP server that the AI client itself starts.

This release is alpha. ST-Link is supported through OpenOCD; direct ST-Link USB
and ST-LINK GDB server backends are not implemented. See the support matrix in
[README.md](README.md) and the evidence table in
[references/live-control.md](references/live-control.md) (host test / board run / physical
measurement) before making compatibility claims; only the last two columns support one.

## Tool maintenance

Runtime: `scripts/embedded_ai_tool/` (`live.py` is the live-control module); launcher:
`scripts/eat.py`; stub core: `stub/`; tests: `tests/` (`test_stub.py` compiles the stub
with `gcc`/`cc` and is skipped without a C compiler).
From the skill directory run `python -m unittest discover -s tests -v` and
`python -m ruff check scripts tests`. Tests load the bundled package, not a globally
installed copy. Report skipped optional OpenOCD tests. Host tests do not count as
live board/firmware verification. Keep profiles, traces, credentials, generated
packages, and raw test/build logs outside the skill's maintained resources.
