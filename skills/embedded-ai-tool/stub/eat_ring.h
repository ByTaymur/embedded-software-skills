#ifndef EAT_RING_H
#define EAT_RING_H
#include <stdint.h>

/* Serialized little-endian event ring. The caller serializes producers and supplies barriers. */
typedef struct { volatile uint8_t *bytes; uint32_t capacity; } eat_ring;
uint32_t eat_ring_get(const volatile uint8_t *p);
void eat_ring_put(volatile uint8_t *p, uint32_t value);
int eat_ring_init(eat_ring *ring, volatile uint8_t *bytes, uint32_t capacity);
int eat_ring_ack(eat_ring *ring, uint32_t cursor);
int eat_ring_emit(eat_ring *ring, uint32_t timestamp, uint32_t generation,
                  uint16_t source, uint8_t kind, uint8_t flags,
                  uint32_t channel, uint32_t value, uint32_t aux,
                  void (*publish)(void));
#endif
