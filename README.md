# embedded-software-skills

![How the repo works: rule, board, code, evidence, record](docs/media/repo-simulasyonu.gif)

*Example scenario: the travel time and current limits of a parking gate are measured on the board
and written into the code. Numbers are illustrative.*

Skills, commands and agents that let an AI coding agent (Claude Code, Codex and others) work on
embedded firmware the way a careful engineer does: follow project rules, **measure on the real board**,
change code from measurements, prove the result, and keep a record. The centrepiece,
[`embedded-ai-tool`](skills/embedded-ai-tool/SKILL.md), gives the agent live, policy-guarded access to
a running microcontroller over a debug probe or a serial link, for any MCU family.

## For AI agents: start here

1. A **skill** is a folder with a `SKILL.md`. Its front matter (`name`, `description`) says when to use
   it; its body says how. Read the `SKILL.md` before acting, then open `references/` files only when
   the body points you there.
2. Pick the skill from the table below by what the user asked, not by keywords alone.
3. Everything project-specific (pins, addresses, limits, build commands, board identity) lives in the
   **target project** — its agent instructions (`CLAUDE.md`, `AGENTS.md`) and its board profile —
   never in these skills. Read those first; ask the user only for facts that block you.
4. Mutating hardware actions are always **plan first, execute on approval**, and are never retried
   automatically after an uncertain result.

| The user wants to… | Use | Entry point |
| --- | --- | --- |
| Read, measure or change what a **connected board** does (registers, variables, pins, PWM, signals, a live program), check board identity, build or flash | `embedded-ai-tool` | [SKILL.md](skills/embedded-ai-tool/SKILL.md); MCP tools `mcp__embedded-ai-tool__*` if registered |
| Work on an **STM32 / Cortex-M firmware project** (CubeMX `.ioc`, HAL/LL, timers, ADC, DMA, ISRs, FreeRTOS, build/flash discipline) | `stm32-firmware-workflow` | [SKILL.md](skills/stm32-firmware-workflow/SKILL.md), commands in `skills/stm32-firmware-workflow/commands/` |
| **Edit firmware C/H source** only, with a per-session QA log, no build or flash | `firmware-source-editor` | [SKILL.md](skills/firmware-source-editor/SKILL.md) |
| Have **two agents do the same task independently** and cross-check plans and results | `ikiz` | [SKILL.md](skills/ikiz/SKILL.md) |
| Answer a hard technical question with a **parse → reason → write** model chain | `multi-model-pipeline` | [SKILL.md](skills/multi-model-pipeline/SKILL.md) (needs `ANTHROPIC_API_KEY`) |
| Read or write **Obsidian** notes (QA logs, decisions, session journals) | `obsidian-agent` | [SKILL.md](skills/obsidian-agent/SKILL.md) (needs an Obsidian MCP server) |
| Build **Grafana** dashboards / manage **Datadog** logs | `third-party/dashboarding`, `third-party/dd-logs` | vendored, own licenses |

Skills combine: a typical firmware change uses `stm32-firmware-workflow` for discipline,
`firmware-source-editor` for the edit and `embedded-ai-tool` to measure before and after.

## Install

### Claude Code

```bash
# all projects
cp -r skills/<skill-name> ~/.claude/skills/
# one project
cp -r skills/<skill-name> <project>/.claude/skills/
# optional: commands and agents
cp commands/*.md ~/.claude/commands/
cp agents/*.md ~/.claude/agents/
```

### Codex

```bash
cp -r skills/<skill-name> ~/.codex/skills/
```

`skills/embedded-ai-tool/agents/openai.yaml` provides Codex's display name and default prompt.

### Other agents

Copy the skill folder anywhere the agent can read and tell it to follow `skills/<name>/SKILL.md`.
The files are plain Markdown and Python; nothing is tied to one vendor. Symlinks instead of copies
keep installed skills in sync with this repo.

### embedded-ai-tool runtime

Python 3.11+. From the repository root:

```bash
python -m pip install "./skills/embedded-ai-tool"            # adds the `eat` command
python -m pip install "./skills/embedded-ai-tool[serial]"    # + serial transport (pyserial)
eat doctor
```

OpenOCD is installed separately when you use a debug probe (any probe and MCU OpenOCD supports).
The serial transport needs no probe: link the stub from `skills/embedded-ai-tool/stub/` into your
firmware ([stub/README.md](skills/embedded-ai-tool/stub/README.md), example ports for Cortex-M,
RISC-V, PIC32 and ESP-IDF in `stub/ports/`).

Create a board profile in your firmware project (never in this repo):

```bash
eat init debug/my-board --name my-board     # template; fill UID location, memory ranges, OpenOCD configs
```

Details: [references/usage.md](skills/embedded-ai-tool/references/usage.md) (profile, OpenOCD,
build/flash) and [references/live-control.md](skills/embedded-ai-tool/references/live-control.md)
(live control, pins, SVD, MCP).

### Register the MCP server (recommended for agents)

The MCP server keeps one session to the board, feeds the stub heartbeat and exposes 25 tools
(identity, registers by SVD name, variables, watch, peek/poke, pins, safe state, measure, live
program, fault evidence, RAM code). With `"openocd": {"autostart": true, ...}` in the profile it
starts and stops OpenOCD itself.

Claude Code:

```bash
claude mcp add --scope local embedded-ai-tool -- \
  python /path/to/skills/embedded-ai-tool/scripts/eat.py \
  --profile /path/to/project/debug/my-board/board.json --session-dir /path/to/project/sessions mcp
```

Codex (`~/.codex/config.toml`):

```toml
[mcp_servers.embedded-ai-tool]
command = "python"
args = ["/path/to/skills/embedded-ai-tool/scripts/eat.py",
        "--profile", "/path/to/project/debug/my-board/board.json", "mcp"]
```

Restart the client; tools appear as `mcp__embedded-ai-tool__<tool>`. Mutating tools return a plan
until called with `execute: true`; keep them on the client's approval prompt and allow read-only
tools if you like.

## Safety model (embedded-ai-tool)

- Every request to the board re-checks the board's unique ID in the same request; a swapped board
  never receives a write.
- Permissions live in the profile file (read/write ranges, protected ranges, allowed pins and
  functions, limits). No MCP tool can widen them; there is no raw command escape hatch.
- A pin claim first arms a safe-state table in the stub; if the host goes silent, the stub applies it
  (dead-man). Live programs run under an instruction budget and a second allow check on the target.
- SVD files give names, never permissions. Registers whose read has side effects are never read.

## Status

Alpha. CI runs the full host test suite (C stub code included) on Windows and Linux, Python 3.11 and
3.14. Hardware evidence so far: one STM32F732 (Cortex-M7) with ST-Link V3 — reads, RAM writes and one
GPIO pin recipe. The stub, dead-man, serial link, sampler and interpreter have host tests only. The
[evidence table](skills/embedded-ai-tool/references/live-control.md#durum-kanıt-tablosu) separates host
tests, board runs and physical measurements; only the last two support a hardware claim.

## Repository layout

```text
skills/<name>/SKILL.md        entry point of each skill (front matter + instructions)
skills/<name>/references/     detail loaded on demand
skills/<name>/commands/       slash commands that belong to one skill
skills/embedded-ai-tool/      Python tool (scripts/), target C code (stub/), tests (tests/)
commands/                     commands not tied to one skill (firmware-status)
agents/                       reviewer, simplifier, skeptic sub-agents
docs/                         notes and media
```

## Contributing

- **Neutral content:** no project names, absolute paths, board profiles, device IDs, firmware
  images or pin constants. Code and protocols stay MCU-family neutral; chip facts go in data files.
- **Self-contained skills:** a skill carries its own `references/` and `commands/`; `SKILL.md` stays
  short and points to detail (progressive disclosure).
- **Evidence, not claims:** new hardware capability gets a row in the evidence table; host tests are
  not board proof.
- **Tests:** in `skills/embedded-ai-tool/`: `python -m pip install -e ".[dev]"`,
  `python -m pytest -q`, `python -m ruff check .`. Unexpected skips fail the suite.

## Türkçe özet

Bu depo, yapay zekâ kod ajanlarının gömülü yazılımda dikkatli bir mühendis gibi çalışmasını sağlayan
skill, komut ve ajanları içerir: proje kurallarına uy, **gerçek kartta ölç**, ölçüme göre kodu değiştir,
sonucu kanıtla, kayıt tut. Ana parça `embedded-ai-tool`, debug probu (OpenOCD) veya seri bağlantı
üzerinden çalışan bir mikrodenetleyiciye politika korumalı canlı erişim verir; her MCU ailesi için
profil ve veri dosyalarıyla çalışır. Ayrıntılı başvuru belgeleri Türkçedir
(`skills/embedded-ai-tool/references/`).

## License

[MIT](LICENSE). Exception: `skills/third-party/` skills are vendored and keep their own licenses —
`dashboarding` (Grafana, Apache-2.0) and `dd-logs` (Datadog, MIT); each `LICENSE` file stays with it.
