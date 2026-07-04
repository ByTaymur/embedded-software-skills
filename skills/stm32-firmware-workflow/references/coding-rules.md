# Working Discipline — Detail

Expansion of SKILL.md Sections 1–2. These are MAIN RULES; they apply to every project.

## CubeMX / .ioc authority

If the project uses STM32CubeMX, the generated structure is first priority:

1. Hardware/peripheral change → edit the `.ioc` first → **Code Generate**.
2. Build on the generated `MX_xxx_Init()` functions; do not rewrite them by hand.
3. Custom code goes **only** inside `/* USER CODE BEGIN x */ ... /* USER CODE END x */`. Code outside these blocks is wiped on generate.
4. Things CubeMX cannot generate (dual/simultaneous ADC, DMA chains, advanced TIM modes) are added inside USER CODE blocks; do not bypass generate.
5. **Do not touch:** the `while(1)` bodies of `HardFault_Handler`, `MemManage_Handler`, `BusFault_Handler`, `UsageFault_Handler`, `Error_Handler` (needed for debug).

Flow: **.ioc → Code Generate → add to USER CODE → commit.**

> Headless generate (without opening the IDE) is possible via CubeMX CLI/script; commands are kept per project in `CLAUDE.md`.
> If the project does not use CubeMX, skip this section; register correctness (below) becomes more critical.

## Non-blocking code

No blocking waits in main flow or control loops.

```c
// FORBIDDEN
HAL_Delay(10);              // blocking delay
while (!flag) { }           // busy-wait
for (i=0;i<N;i++){ slow(); }// long blocking loop

// CORRECT — non-blocking timing
static uint32_t last = 0u;
if ((HAL_GetTick() - last) >= 10u) { last = HAL_GetTick(); periodic(); }

// CORRECT — state machine
switch (state) {
  case S_IDLE:  break;
  case S_RUN:   break;
  case S_FAULT: break;
}
```

Exception: short, measured waits during init only (e.g. hardware reset time). Never in control/comms loops.

## Task placement (foreground / background)

For each new task, first ask: **"Is this time-critical?"**

- **Yes → ISR / control loop**: current/PWM update, encoder, protection/trip, control PI/PID. ISR stays short: read hardware, set flag, exit. No heavy work, blocking, `printf`, or dynamic allocation in an ISR.
- **No → main `while(1)` (background)**: telemetry/UART, temp/Vbus read, LED, watchdog feed, logging.

Do not put timing-disturbing work in an ISR; do not leave safety/control work to background.

## Single source of truth for parameters

Hardware/application constants (pole count, sensor sensitivity, frequencies, dead-time, thresholds) live in one config header. Never write the same constant in multiple places; a value changes only there. No magic numbers.

## Register / datasheet correctness

- Never invent a register address, bit field, or GPIO **alternate-function** mapping. If unsure, verify from the reference manual or rely on the `CLAUDE.md` pin table.
- TIM channel ↔ GPIO AF mappings are family-dependent (STM32F1 remap; F4/F7 AFx). Do not write an AF number without confirming it matches the family.
- In bit masks (`|=`, `&= ~`, `& mask`), confirm target bit positions against the datasheet; a bitwise/hex error silently produces wrong behavior.
- Power-stage values (PWM polarity, center-aligned period, dead-time counter) cause shoot-through if wrong; never change them by guessing.

## Documentation

When hardware/software changes, update the relevant section of the project `CLAUDE.md` in the same commit. Keep the pin table and "Known Issues" current so the next session does not re-discover a trap.
