#include "eat_ring.h"

uint32_t eat_ring_get(const volatile uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
void eat_ring_put(volatile uint8_t *p, uint32_t v)
{
    union { uint32_t value; uint8_t bytes[4]; } encoded;
    uint32_t i;
    for (i = 0; i < 4u; i++) { encoded.bytes[i] = (uint8_t)(v >> (8u * i)); }
    *(volatile uint32_t *)(void *)p = encoded.value;
}
int eat_ring_init(eat_ring *r, volatile uint8_t *p, uint32_t capacity)
{
    uint32_t i;
    if ((uintptr_t)p%4u || capacity > (0xFFFFFFFFu-32u)/32u ||
        (capacity && (capacity & (capacity - 1u)))) { return 0; }
    r->bytes = p; r->capacity = capacity;
    for (i = 0; i < 32u + capacity * 32u; i++) { p[i] = 0; }
    eat_ring_put(p, 1u); eat_ring_put(p + 4, 32u); eat_ring_put(p + 8, capacity);
    eat_ring_put(p + 24, 1000000u); eat_ring_put(p + 28, 1u);
    return 1;
}
int eat_ring_ack(eat_ring *r, uint32_t cursor)
{
    uint32_t read = eat_ring_get(r->bytes + 16), write = eat_ring_get(r->bytes + 12);
    if ((uint32_t)(cursor - read) > (uint32_t)(write - read)) { return 0; }
    eat_ring_put(r->bytes + 16, cursor); return 1;
}
int eat_ring_emit(eat_ring *r, uint32_t time, uint32_t gen, uint16_t source,
                  uint8_t kind, uint8_t flags, uint32_t channel, uint32_t value,
                  uint32_t aux, void (*publish)(void))
{
    volatile uint8_t *p = r->bytes;
    uint32_t write = eat_ring_get(p + 12);
    if (!r->capacity || (uint32_t)(write - eat_ring_get(p + 16)) >= r->capacity) {
        eat_ring_put(p + 20, eat_ring_get(p + 20) + 1u); return 0;
    }
    p += 32u + (write & (r->capacity - 1u)) * 32u;
    eat_ring_put(p + 4, time); eat_ring_put(p + 8, gen);
    p[12] = (uint8_t)source; p[13] = (uint8_t)(source >> 8); p[14] = kind; p[15] = flags;
    eat_ring_put(p + 16, channel); eat_ring_put(p + 20, value);
    eat_ring_put(p + 24, aux); eat_ring_put(p + 28, 0u);
    publish(); eat_ring_put(p, write); publish(); eat_ring_put(r->bytes + 12, write + 1u);
    return 1;
}
