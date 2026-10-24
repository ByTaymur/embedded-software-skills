#include "eat_embed.h"
#include "eat_port_cortex_m.h"
/* TODO(port): implement clock/pin/UART initialization and return the actual core Hz. */
extern uint32_t port_board_init(void);
/* TODO(port): drain an IRQ-safe RX queue without blocking; return 0 when empty. */
extern int port_uart_take(uint8_t *byte);
/* TODO(port): send the complete frame, handling queue capacity and TX errors. */
extern void port_uart_send(const uint8_t *data, uint32_t length);
/* TODO(port): perform one bounded application step, including watchdog service. */
extern void port_app_step(void);
int main(void)
{
    uint8_t byte;
    if (eat_port_cortex_m_init(port_board_init()) != 0) return 1;
    eat_embed_init(eat_port_cortex_m_millis, port_uart_send);
    for (;;) {
        /* Bounded RX batch keeps polling alive during continuous traffic. */
        unsigned int i;
        for (i = 0u; i < 64u && port_uart_take(&byte); ++i) eat_link_rx(byte);
        eat_stub_poll();
        port_app_step();
    }
}
