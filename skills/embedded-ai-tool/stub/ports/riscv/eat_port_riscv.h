#ifndef EAT_PORT_RISCV_H
#define EAT_PORT_RISCV_H
#include <stdint.h>
int eat_port_riscv_init(uint32_t timer_hz);
uint32_t eat_port_riscv_millis(void);
void eat_port_riscv_exception(uint32_t mcause);
#endif
