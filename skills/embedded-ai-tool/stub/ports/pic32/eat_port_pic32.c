#include "eat_port_pic32.h"
#include "eat_stub_core.h"
#ifdef __XC32
#include <xc.h>
#endif
static uint32_t previous, frequency, milliseconds;
static uint64_t remainder;
static uint32_t count(void)
{
#ifdef __XC32
    return (uint32_t)_CP0_GET_COUNT();
#else
    uint32_t value;
    __asm__ volatile ("mfc0 %0, $9" : "=r"(value));
    return value;
#endif
}
int eat_port_pic32_init(uint32_t core_hz)
{
    if (core_hz < 2u || core_hz % 2u != 0u) return -1;
    frequency = core_hz / 2u;
    previous = count();
    milliseconds = 0u;
    remainder = 0u;
    return 0;
}
uint32_t eat_port_pic32_millis(void)
{
    uint32_t now = count();
    /* Call at least once per Count wrap; only one foreground caller. */
    remainder += (uint64_t)(uint32_t)(now - previous) * 1000u;
    previous = now;
    milliseconds += (uint32_t)(remainder / frequency);
    remainder %= frequency;
    return milliseconds;
}
void eat_port_pic32_exception(uint32_t cause)
{
    eat_stub_fault(cause);
    for (;;) { }
}
#ifdef __XC32
/* TODO(port): verify the startup exception ABI and handler ownership for your XC32 runtime. */
void _general_exception_handler(void)
{
    eat_port_pic32_exception((uint32_t)_CP0_GET_CAUSE());
}
#endif
