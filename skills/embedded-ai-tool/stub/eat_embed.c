#include "eat_embed.h"

#include <stddef.h>

volatile uint32_t eat_mailbox[EAT_MAILBOX_WORDS];
#if EAT_SCRATCH_BYTES > 0
EAT_SCRATCH_ATTR uint32_t eat_scratch[(EAT_SCRATCH_BYTES + 3u) / 4u];
#endif

static uint32_t (*clock_ms)(void);

static uint32_t generic_millis(void) { return clock_ms(); }

static uint32_t generic_read(uint32_t address, uint32_t width)
{
    uintptr_t at = (uintptr_t)address;

    if (width == 8u) {
        return *(volatile uint8_t *)at;
    }
    if (width == 16u) {
        return *(volatile uint16_t *)at;
    }
    return *(volatile uint32_t *)at;
}

static void generic_write(uint32_t address, uint32_t width, uint32_t value)
{
    uintptr_t at = (uintptr_t)address;

    if (width == 8u) {
        *(volatile uint8_t *)at = (uint8_t)value;
    } else if (width == 16u) {
        *(volatile uint16_t *)at = (uint16_t)value;
    } else {
        *(volatile uint32_t *)at = value;
    }
}

static void generic_write_masked(uint32_t address, uint32_t width, uint32_t mask, uint32_t value)
{
    generic_write(address, width, (generic_read(address, width) & ~mask) | (value & mask));
}

static uint32_t generic_call(uint32_t entry, const uint32_t args[4])
{
    /* The host has applied any architecture call bits (profile live.entry_or). */
    uint32_t (*function)(uint32_t, uint32_t, uint32_t, uint32_t) =
        (uint32_t (*)(uint32_t, uint32_t, uint32_t, uint32_t))(uintptr_t)entry;
    return function(args[0], args[1], args[2], args[3]);
}

static const eat_hal hal = {generic_millis, generic_write_masked, generic_call};
static eat_link_port link;

void eat_embed_init(uint32_t (*millis)(void), void (*send)(const uint8_t *data, uint32_t length))
{
    clock_ms = millis;
    eat_stub_init(&hal, eat_mailbox, EAT_MAILBOX_WORDS);
    if (send != NULL) {
        link.send = send;
        link.millis = generic_millis;
        link.read = generic_read;
        link.write = generic_write;
        eat_link_init(&link, (uint32_t)(uintptr_t)eat_mailbox, EAT_MAILBOX_WORDS);
    }
}
