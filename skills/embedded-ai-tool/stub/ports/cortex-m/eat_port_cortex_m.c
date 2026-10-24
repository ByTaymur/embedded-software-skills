/* Architecture-defined SysTick registers; no peripheral or clock-tree assumptions. */
#include "eat_port_cortex_m.h"
#include "eat_stub_core.h"
#define SYST_CSR (*(volatile uint32_t *)0xE000E010u)
#define SYST_RVR (*(volatile uint32_t *)0xE000E014u)
#define SYST_CVR (*(volatile uint32_t *)0xE000E018u)
static volatile uint32_t ticks_ms;

int eat_port_cortex_m_init(uint32_t core_hz)
{
    uint32_t reload = core_hz / 1000u;
    if (core_hz % 1000u != 0u || reload == 0u || reload > 0x1000000u) return -1;
    SYST_CSR = 0u;
    ticks_ms = 0u;
    SYST_RVR = reload - 1u;
    SYST_CVR = 0u;
    SYST_CSR = 7u; /* ENABLE | TICKINT | CLKSOURCE (processor clock). */
    return 0;
}
void SysTick_Handler(void) { ++ticks_ms; }
uint32_t eat_port_cortex_m_millis(void) { return ticks_ms; }
void HardFault_Handler(void)
{
    eat_stub_fault(3u); /* Architecture exception number; valid even on Cortex-M0. */
    for (;;) { /* Fatal: never exception-return into the faulting instruction. */ }
}
