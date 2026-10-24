#ifndef EAT_PORT_CORTEX_M_H
#define EAT_PORT_CORTEX_M_H
#include <stdint.h>
int eat_port_cortex_m_init(uint32_t core_hz);
uint32_t eat_port_cortex_m_millis(void);
void SysTick_Handler(void);
void HardFault_Handler(void);
#endif
