#ifndef EAT_PORT_PIC32_H
#define EAT_PORT_PIC32_H
#include <stdint.h>
int eat_port_pic32_init(uint32_t core_hz);
uint32_t eat_port_pic32_millis(void);
void eat_port_pic32_exception(uint32_t cause);
#endif
