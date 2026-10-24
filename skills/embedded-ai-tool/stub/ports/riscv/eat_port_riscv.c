#include "eat_port_riscv.h"
#include "eat_stub_core.h"
/* Define EAT_RISCV_USE_TIME for the time CSR instead of machine-mode mcycle. */
static uint32_t frequency;
static uint64_t origin;
static uint64_t counter(void)
{
    uint32_t hi, lo, again;
    do {
#ifdef EAT_RISCV_USE_TIME
        __asm__ volatile ("csrr %0, timeh" : "=r"(hi));
        __asm__ volatile ("csrr %0, time" : "=r"(lo));
        __asm__ volatile ("csrr %0, timeh" : "=r"(again));
#else
        __asm__ volatile ("csrr %0, mcycleh" : "=r"(hi));
        __asm__ volatile ("csrr %0, mcycle" : "=r"(lo));
        __asm__ volatile ("csrr %0, mcycleh" : "=r"(again));
#endif
    } while (hi != again);
    return ((uint64_t)hi << 32) | lo;
}
int eat_port_riscv_init(uint32_t timer_hz)
{
    if (timer_hz == 0u) return -1;
    frequency = timer_hz;
    origin = counter();
    return 0;
}
uint32_t eat_port_riscv_millis(void)
{
    uint64_t elapsed = counter() - origin;
    return (uint32_t)((elapsed / frequency) * 1000u +
                      ((elapsed % frequency) * 1000u) / frequency);
}
void eat_port_riscv_exception(uint32_t mcause)
{
    /* TODO(port): call from an ABI-safe trap wrapper ONLY for synchronous exceptions.
     * Save registers/establish a valid stack; dispatch interrupts separately. */
    eat_stub_fault(mcause);
    for (;;) { }
}
