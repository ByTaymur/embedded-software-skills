# Embedded AI Tool (alpha)

A portable CLI and AI skill for profile-driven firmware inspection and development.
It speaks **OpenOCD Tcl RPC**, normally on port 6666. The connection is:

```text
eat / AI agent -> OpenOCD -> ST-Link or another supported probe -> target MCU
AI client --MCP (stdio)--> eat mcp -> OpenOCD -> probe -> MCU registers / RAM
AI client --MCP (stdio)--> eat mcp -> serial (UART/USB) -> stub link in the firmware -> MCU registers / RAM
```

ST-Link support is provided through OpenOCD. There is no direct ST-Link USB,
STM32CubeProgrammer, ST-LINK GDB server, or telnet backend in this package.
Probe/MCU compatibility depends on your OpenOCD version, firmware and reviewed
configuration. Hardware evidence so far is one STM32F732 (Cortex-M7) with ST-Link V3 (reads,
RAM writes, one GPIO pin recipe); the stub, dead-man, RAM calls and the serial link have not
run on hardware. See the
[evidence table](references/live-control.md#durum-kanıt-tablosu).
This is an alpha, not a declaration of compatibility with every board.

## Install

Python 3.11+ is required. From the repository root:

```sh
python -m pip install ./skills/embedded-ai-tool
eat doctor
eat init debug/my-board --name my-board
```

For serial transport, run `pip install "embedded-ai-tool[serial]"`.

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
| CMSIS-SVD register/bitfield names (`reg read`, `reg list`; MCP `read_register`, `list_registers`) | Vendor-neutral local parser, decoded fields/enums, policy and identity guards; host-tested only; SVD grants no permissions |
| UID, memory reads, timed JSONL traces | OpenOCD RPC; host and offline Tcl tests |
| Symbol reads / writes | Full file-backed PT_LOAD verification before access |
| Build | Trusted profile argv; shell disabled |
| Write / halt / resume / reset | Explicit `--execute`; identity guard |
| Flash | Local/shared filesystem; pinned ELF bytes, erase/write/verify/reset |
| Live RAM-only control: `peek`/`poke`, pin recipes, `safe`, RAM snippets, `serve` | Policy-bounded, never writes flash. On one STM32F732 via OpenOCD: reads, RAM writes, a GPIO pin recipe; the stub, dead-man and RAM calls **not yet on hardware** ([guide](references/live-control.md)) |
| MCP server (`eat mcp`, stdio, no extra dependency) | Live-control commands as MCP tools over one held session; read, write and pin tools run on one STM32F732 via ST-Link V3 + OpenOCD; other targets untested |
| Serial transport (`connection.transport: serial`) and `stub/eat_embed` integration | Probe-less live control through a stub linked into any firmware; host-tested against the real C code, compiles warning-free for ARM Cortex-M, RISC-V 32, MIPS32; **not yet run over a real UART** |
| Stub core (mailbox, dead-man, RAM call) | MCU-independent C in `stub/`, tested on the host against the Python client; **no MCU port or real pin data is included** |
| ST-Link V2/V3 with OpenOCD | Adapter configuration supported by OpenOCD; one ST-Link V3 + STM32F732 setup exercised, no other probe/MCU qualified |
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
python -m pytest -q
python -m ruff check .
python tests/package_smoke.py
```

OpenOCD interpreter tests run with `noinit` and fake memory commands, without a
probe connection. Unexpected skips fail the suite. Set `EAT_OPENOCD_TESTS=0`
to explicitly opt out of the interpreter tests (as Windows CI does); Linux CI
installs OpenOCD and runs them. Other environment-gated optional tests must use a
skip reason starting with `optional:`. C tests require gcc/cc or the `ziglang`
dev dependency; the cross-compile test requires `ziglang` on both platforms.
The package smoke script builds and installs a wheel in a fresh environment,
then checks installed resources, `eat doctor`, and the offline MCP handshake.
Use `python tests/package_smoke.py --offline --wheelhouse <wheel-directory>`
with locally installed build requirements and cached runtime dependency wheels
to run it without package-index access. CI defines Windows
and Linux / Python 3.11 and 3.14 jobs; a configured workflow is not a passed CI run.
Hardware reports should state probe model/firmware, MCU, OpenOCD version, wiring,
commands, expected/observed values and untested operations. Remove device IDs,
credentials and proprietary firmware from public issues.

Licensed under [MIT](LICENSE), including when the skill is copied independently.
`pyelftools` is an external dependency, and OpenOCD is a separately installed tool;
neither is bundled here.

Official references: [OpenOCD adapters](https://openocd.org/doc/html/Debug-Adapter-Configuration.html),
[Tcl RPC](https://openocd.org/doc/html/Tcl-Scripting-API.html).
