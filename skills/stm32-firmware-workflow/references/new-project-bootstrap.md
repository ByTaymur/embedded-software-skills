# New-Project Onboarding — Rule Collection

Runs when the project root has no `CLAUDE.md` (sub-rules). Goal: without guessing, collect the project-specific data from the user, generate a sub-rule file (`CLAUDE.md`), get it confirmed, then start working. **Ask the user in Turkish.**

## Hard rules

- **Never assume** a project-specific value (MCU, pin, direction, AF, parameter, frequency, toolchain). If unknown, **ask**.
- **Do not carry** values from other projects or prior examples. Every project is collected from scratch.
- **Do not write code or edit the `.ioc` until the blocking gaps are filled.** Firmware behavior depends on hardware truth — a wrong pin direction or AF silently breaks the board.
- If a topic is unknown to the user right now, mark it "TBD" in the `CLAUDE.md`; never invent it.

## Interview (ask in Turkish; let the user answer what they know)

Ask grouped, a few at a time — do not dump all questions at once.

### A. Project & MCU
1. Project name and purpose — what device/firmware is this?
2. Exact MCU part number (e.g. STM32F103VCT6), package/pin count, core clock, Flash, SRAM.
3. Toolchain/IDE: Keil MDK? STM32CubeCLT + GCC/CMake? CubeIDE? What are the build & flash commands?
4. Is STM32CubeMX used? `.ioc` filename? Or hand-written register/LL?

### B. Clock tree & power
5. HSE/HSI source and value; PLL config; resulting SYSCLK and key peripheral clocks (APB1/APB2, timer clocks).
6. Power rails: input voltage, regulators, any high-voltage/power stage (DC-link voltage, etc.).
7. If a motor/power stage: gate driver part, IGBT/MOSFET, dead-time requirement, switching frequency.

### C. Pinout — detailed (firmware cannot proceed without this)
For every relevant pin, capture all of:
- **Pin** (e.g. PA8)
- **Signal/function** (e.g. TIM1_CH1, USART1_TX, ADC1_IN4, GPIO_LED)
- **Direction/mode**: input / output / analog / alternate-function / EXTI
- **AF number** if alternate-function (family-dependent: F1 uses remap, F4/F7 use AFx)
- **Pull**: up / down / none
- **Speed**: low / medium / high / very-high (for outputs/AF)
- **Active level / initial state** (active-high or -low; default driven state)
- **Note** (what it connects to on the PCB)

8. Provide the pin table above. Critically, capture **PCB hardware traps**:
   - Pins hard-wired to GND/VCC on the PCB (cannot be used as I/O).
   - Peripherals that are physically unavailable (pin conflict, not routed).
   - Required pin remaps (e.g. USART/TIM remap on F1).
   - Pins with external pull/level-shift/protection that constrain config.

### D. Peripheral & DMA map
9. Which peripherals are used and for what (TIMx → PWM/encoder, ADCx → which channels, USARTx → which link, SPI/I2C/CAN, etc.).
10. DMA streams/channels: which request maps to which stream, single/double buffer, priorities.
11. Interrupts: which IRQs are enabled, their NVIC priorities, which is the control-loop ISR (and its frequency).

### E. Software architecture
12. Control/timing structure: is there a control loop? frequency? which TIM/IRQ drives it? What runs in background (`while(1)`)?
13. State machine: states and transitions (e.g. INIT → ALIGN → RUN → FAULT).
14. Single source of truth for parameters: which config header? List the critical constants with value + unit + why.

### F. Project hygiene
15. Known issues / open problems / untested parts.
16. Git & session protocol: branch-per-session + development log wanted? Where is the log file? (See `git-workflow.md`.)
17. File layout: existing directory structure (firmware/, docs/, archive/, etc.).
18. Documentation map: which doc file answers which question.
19. Any project-specific rule that adds to or overrides the main rules?
20. Feature toggles: which skill features should be ON/OFF for this project? (Defaults in `feature-toggles.md`; e.g. turn `cubemx_first` OFF for hand-written LL projects, `git_protocol` ON if branch-per-session is wanted.)

## Generate & confirm

1. Fill `references/CLAUDE.md.template` with the collected answers.
2. Write it to the project root as `CLAUDE.md`.
3. **Show the user a summary in Turkish and ask for confirmation** ("eksik/yanlış var mı?").
4. On approval: the skill's main rules + this `CLAUDE.md`'s sub-rules now both apply. Begin executing the project on top of them.
5. In later sessions, whenever hardware/software changes, update `CLAUDE.md` in the same commit.
