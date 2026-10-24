/* Architecture-neutral SPSC sampler. Normative ownership: stub-protocol.md. */
#ifndef EAT_SAMPLER_H
#define EAT_SAMPLER_H
#include <stdint.h>
#define EAT_SAMPLER_MAGIC 0x504D5345u
#define EAT_SAMPLER_VERSION 1u
#define EAT_SAMPLER_CHANNELS 8u
#define EAT_SAMPLER_ALLOW 8u
#define EAT_SAMPLER_HEADER 19u
#define EAT_SAMPLER_ALLOW_BASE 19u
#define EAT_SAMPLER_CHANNEL_BASE 35u
#define EAT_SAMPLER_DATA 59u
#define EAT_SAMPLER_ROW 10u
#define EAT_SAMPLER_WORDS(slots) (EAT_SAMPLER_DATA + (slots) * EAT_SAMPLER_ROW)
#define EAT_S_MAGIC 0u
#define EAT_S_VERSION 1u
#define EAT_S_SLOTS 2u
#define EAT_S_MAX_CHANNELS 3u
#define EAT_S_COUNT 4u
#define EAT_S_PERIOD 5u
#define EAT_S_WRITE 6u
#define EAT_S_READ 7u
#define EAT_S_OVERRUN 8u
#define EAT_S_TIME 9u
#define EAT_S_SEQUENCE 10u
#define EAT_S_ENABLE 11u
#define EAT_S_STATE 12u
#define EAT_S_ALLOW_COUNT 13u
#define EAT_S_EPOCH 14u
#define EAT_S_ERROR 15u
#define EAT_S_START_TIME 16u
#define EAT_S_START_SEQUENCE 17u
#define EAT_S_START_OVERRUN 18u
#define EAT_S_MEMORY 0u
#define EAT_S_PORT 1u

/* barrier must order shared RAM against probe/link access, including cache maintenance
 * where needed. NULL is only valid for strongly ordered, coherent memory. All accesses
 * must be atomic aligned 32-bit transfers. There is exactly one non-reentrant producer. */
typedef struct {
    uint32_t (*read_channel)(uint32_t channel_id);
    /* NULL uses the built-in volatile memory-word reader (8/16/32 bits). */
    uint32_t (*read_memory)(uint32_t address, uint32_t width_bits);
    void (*barrier)(void);
} eat_sampler_port;

/* slots: power of two, 1..65536; array has EAT_SAMPLER_WORDS(slots) words.
 * Initialization happens before exposing the array to the host. Returns 0 on error. */
int eat_sampler_init(const eat_sampler_port *port, volatile uint32_t *buffer, uint32_t slots);
void eat_sampler_tick(uint32_t now_ms);
/* Future producers use the same format; call instead of tick, from the SAME producer
 * context. Configuration handshake still runs through tick. count must match config. */
int eat_sampler_push(uint32_t now_ms, const uint32_t *values, uint32_t count);
#endif
