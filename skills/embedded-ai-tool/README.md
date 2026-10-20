# Embedded AI Tool (alpha)

A portable CLI and AI skill for profile-driven firmware inspection and development.
It speaks **OpenOCD Tcl RPC**, normally on port 6666. The connection is:

```text
eat / AI agent -> OpenOCD -> ST-Link or another supported probe -> target MCU
```

ST-Link support is provided through OpenOCD. There is no direct ST-Link USB,
STM32CubeProgrammer, ST-LINK GDB server, or telnet backend in this package.
Probe/MCU compatibility depends on your OpenOCD version, firmware and reviewed
configuration. Live hardware qualification is still pending; this is an alpha,
not a declaration of compatibility with every board.

## Install

Python 3.11+ is required. From the repository root:

```sh
python -m pip install ./skills/embedded-ai-tool
eat doctor
eat init debug/my-board --name my-board
```

OpenOCD is installed separately and must support the selected probe and MCU.
Complete the generated profile using your board documentation and real UID.
The target must expose an identity area readable in 8-bit accesses. Firmware
variables require an ELF/AXF with symbols and explicitly specified scalar types.

For AI use, copy the **whole skill folder** to the host application's skill directory
and read [SKILL.md](SKILL.md). The bundled `scripts/eat.py` works from any working
directory. Detailed [usage/profile documentation (Turkish)](references/usage.md)
and [measurement lessons (Turkish)](references/lessons.md) are included.

## Capabilities and limits

| Capability | Implementation / validation |
|---|---|
| ELF/AXF scalar symbols, source search | Local host functionality |
| UID, memory reads, timed JSONL traces | OpenOCD RPC; host and offline Tcl tests |
| Symbol reads / writes | Full file-backed PT_LOAD verification before access |
| Build | Trusted profile argv; shell disabled |
| Write / halt / resume / reset | Explicit `--execute`; identity guard |
| Flash | Local/shared filesystem; pinned ELF bytes, erase/write/verify/reset |
| ST-Link V2/V3 with OpenOCD | Adapter configuration supported by OpenOCD; no live qualification yet |
| Direct ST-Link without OpenOCD | Not implemented |
| Remote flash file transfer, DWARF structs/arrays, breakpoints, RTOS view | Not implemented |

Mutation commands default to a plan. Use `--execute` within the authorized task.
A timeout may leave a write or flash outcome unknown; mutations are not retried.
UID/build verification does not prove physical success. Reads are sequential,
not a real-time safety controller. OpenOCD RPC is a privileged unauthenticated
control interface: keep it local or behind an authenticated tunnel.

Profiles and local traces may contain firmware, hardware identities and paths;
keep them out of source distributions. The tool does not upload them to any service.

## Development and contributions

From this skill directory:

```sh
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
python -m ruff check scripts tests
python -m build
```

OpenOCD interpreter tests run with `noinit` and fake memory commands, without a
probe connection. They are skipped if OpenOCD is unavailable. CI defines Windows
and Linux / Python 3.11 and 3.14 jobs; a configured workflow is not a passed CI run.
Hardware reports should state probe model/firmware, MCU, OpenOCD version, wiring,
commands, expected/observed values and untested operations. Remove device IDs,
credentials and proprietary firmware from public issues.

Licensed under [MIT](LICENSE), including when the skill is copied independently.
`pyelftools` is an external dependency, and OpenOCD is a separately installed tool;
neither is bundled here.

Official references: [OpenOCD adapters](https://openocd.org/doc/html/Debug-Adapter-Configuration.html),
[Tcl RPC](https://openocd.org/doc/html/Tcl-Scripting-API.html).
