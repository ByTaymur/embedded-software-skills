# Feature Toggles

The skill is modular. Each feature can be turned ON `[x]` or OFF `[ ]` per project. The user controls this; respect it literally.

## Where toggles live

- **Per project:** the "Feature Toggles" block in the project root `CLAUDE.md` (copy it from `CLAUDE.md.template`). This wins.
- **No block present:** use the defaults below.

## Toggle list & defaults

| Toggle | Default | When ON | When OFF |
|--------|---------|---------|----------|
| `scope_guard` | ON | Warn + ask for confirmation before touching anything outside the literal request. | Proceed without the confirmation step (still stay reasonable). |
| `min_workload` | ON | Smallest possible change; append over rewrite; fewest files/lines. | No explicit minimality constraint. |
| `cubemx_first` | ON | `.ioc` is authoritative; custom code only in USER CODE blocks. | Edit code directly (hand-written LL / non-CubeMX projects). |
| `non_blocking` | ON | Forbid `HAL_Delay`/busy-wait in main flow; use `HAL_GetTick`/FSM. | Allow blocking style if the project uses it. |
| `task_placement` | ON | Enforce ISR (time-critical) vs background split. | No enforced split. |
| `register_verify` | ON | Require datasheet/AF verification before register/mask writes. | Trust provided values. |
| `single_source_params` | ON | All constants in one config header. | Allow scattered constants. |
| `deep_engineering` | ON | Load `embedded-engineering.md` (DMA/cache, volatile, MUST/MUST NOT). | Skip the deep reference. |
| `doc_sync` | ON | Update `CLAUDE.md` in the same commit as a hardware/software change. | Skip doc updates. |
| `git_protocol` | OFF | Branch-per-session, commit format, dev log, `--no-ff` merge. | Just commit normally; no branching/logging enforced. |
| `onboarding` | ON | Full new-project interview when no `CLAUDE.md` exists. | Ask only minimum blocking facts and proceed. |
| `terse_output` | ON | Short, direct replies; no long explanations unless asked. | Normal verbosity. |

## How to apply

1. At task start, read the project's toggle block.
2. For each feature, if OFF, do not apply its rule and do not silently re-enable it.
3. If the user says "X özelliğini kapat/aç", update the toggle block in `CLAUDE.md` (do not just acknowledge — edit the file), then confirm in Turkish.

## Copy-paste block (defaults)

```
## Feature Toggles
- [x] scope_guard
- [x] min_workload
- [x] cubemx_first
- [x] non_blocking
- [x] task_placement
- [x] register_verify
- [x] single_source_params
- [x] deep_engineering
- [x] doc_sync
- [ ] git_protocol
- [x] onboarding
- [x] terse_output
```
