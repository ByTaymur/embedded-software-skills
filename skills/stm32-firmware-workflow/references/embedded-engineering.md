# Embedded Engineering — Deep Reference

Combines the engineering core of three skills (arm-cortex-expert, embedded-systems, stm32-development-workflow) with the user's rules. Read for ISR, DMA/cache, RTOS, peripheral driver, and register-level work.

## MUST DO

- Use `volatile` for hardware registers and any variable shared with an ISR.
- Keep ISRs short; defer heavy work to a task/background.
- Use a watchdog (IWDG/WWDG) for reliability; feed it in the main loop.
- Protect shared resources with proper synchronization / critical sections.
- Handle all error conditions; check return codes.
- Account for timing constraints and jitter.
- Document resource usage (flash, RAM, power).
- Be aware of float cost without an FPU; prefer fixed-point if no FPU.

## MUST NOT DO

- Block inside an ISR (delay, busy-wait, blocking I/O).
- Dynamic allocation without bounds checking; none at all on control/ISR paths.
- Skip critical-section protection.
- Ignore hardware errata/limits.
- Access a shared resource without synchronization.
- Hardcode hardware-specific values (use the config header, then `CLAUDE.md`).
- Ignore power-consumption requirements.

## ISR ↔ task sharing (volatile + critical section)

```c
/* shared with ISR: volatile required */
static volatile uint8_t g_rx_flag = 0;
static volatile uint8_t g_rx_byte = 0;

void USART2_IRQHandler(void) {              /* short: read, set flag, exit */
    if (USART2->SR & USART_SR_RXNE) {
        g_rx_byte = (uint8_t)(USART2->DR & 0xFF);  /* read clears RXNE */
        g_rx_flag = 1;
    }
}

void process_rx(void) {                     /* background consumes */
    if (g_rx_flag) {
        __disable_irq();                    /* enter critical section */
        uint8_t b = g_rx_byte; g_rx_flag = 0;
        __enable_irq();                     /* exit critical section  */
        handle_byte(b);
    }
}
```

Protect non-atomic access to multi-byte shared data with a critical section (`__disable_irq`/`__enable_irq`) or appropriate synchronization.

## DMA & cache coherency, memory barriers (Cortex-M7 / STM32F7/H7)

- On D-cache-enabled cores (F7/H7), mind coherency for DMA buffers:
  - **Before** a DMA transmit: write the source to memory → `SCB_CleanDCache_by_Addr()`.
  - **After** a DMA receive: before reading the buffer → `SCB_InvalidateDCache_by_Addr()`.
  - Align DMA buffers to the cache line (32 bytes); or define a non-cacheable region via the MPU.
- Use barriers `__DMB()`/`__DSB()`/`__ISB()` where register/flag ordering matters (e.g. after NVIC config, before sleep, on vector-table relocation).
- Enable a peripheral's clock (`RCC->...ENR`) before configuring it; a few cycles may be needed after clock enable.

## Verification & test

1. Compile clean with `-Wall -Werror`.
2. Static analysis: `cppcheck --enable=all`.
3. Confirm register bit-field usage against the datasheet.
4. Measure timing with a logic analyzer/oscilloscope.
5. Stack headroom: `uxTaskGetStackHighWaterMark()` (RTOS) or stack painting; verify ISR latency and no missed deadlines under worst-case load.
6. On any issue → return to architecture/implementation.

## Bare-metal TIM interrupt skeleton (reference)

```c
void TIM2_IRQHandler(void) {
    if (TIM2->SR & TIM_SR_UIF) {
        TIM2->SR &= ~TIM_SR_UIF;            /* clear update flag */
        /* control/work here — keep it short */
    }
}

void tim2_init(void) {
    RCC->APB1ENR |= RCC_APB1ENR_TIM2EN;     /* clock first */
    TIM2->PSC  = PSC_VAL;
    TIM2->ARR  = ARR_VAL;
    TIM2->DIER |= TIM_DIER_UIE;
    TIM2->CR1  |= TIM_CR1_CEN;
    NVIC_SetPriority(TIM2_IRQn, PRIO);
    NVIC_EnableIRQ(TIM2_IRQn);
}
```

> PSC/ARR/PRIO and the TIM choice are project-specific → config header + `CLAUDE.md`. Values here are placeholders, not to be copied.

## Output template (when implementing a feature)

1. Hardware init (clock, peripheral, GPIO).
2. Driver (HAL/LL layer, ISR).
3. Application code (RTOS task or main loop).
4. Resource summary (flash, RAM, power estimate).
5. Short rationale for timing/optimization decisions.
