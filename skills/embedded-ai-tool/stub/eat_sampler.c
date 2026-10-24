#include "eat_sampler.h"
#include <stddef.h>

static const eat_sampler_port *port;
static volatile uint32_t *buf;
static uint32_t capacity, count, period, last_ms;
static uint32_t channels[EAT_SAMPLER_CHANNELS][3];

static void barrier(void)
{
    if (port != NULL && port->barrier != NULL) { port->barrier(); }
}

static uint32_t memory_read(uint32_t address, uint32_t width)
{
    uintptr_t at = (uintptr_t)address;
    if (port != NULL && port->read_memory != NULL) { return port->read_memory(address, width); }
    if (width == 8u) { return *(volatile uint8_t *)at; }
    if (width == 16u) { return *(volatile uint16_t *)at; }
    return *(volatile uint32_t *)at;
}

int eat_sampler_init(const eat_sampler_port *hooks, volatile uint32_t *buffer, uint32_t slots)
{
    uint32_t i;
    buf = NULL;
    if (buffer == NULL || slots == 0u || slots > 65536u || (slots & (slots - 1u)) != 0u) { return 0; }
    port = hooks;
    capacity = slots;
    buf = buffer;
    for (i = 0; i < EAT_SAMPLER_WORDS(slots); i++) { buf[i] = 0u; }
    count = 0u;
    buf[EAT_S_VERSION] = EAT_SAMPLER_VERSION;
    buf[EAT_S_SLOTS] = slots;
    buf[EAT_S_MAX_CHANNELS] = EAT_SAMPLER_CHANNELS;
    barrier();
    buf[EAT_S_MAGIC] = EAT_SAMPLER_MAGIC;
    return 1;
}

static int configure(void)
{
    uint32_t i, j, allows = buf[EAT_S_ALLOW_COUNT];
    count = buf[EAT_S_COUNT];
    period = buf[EAT_S_PERIOD];
    if (count == 0u || count > EAT_SAMPLER_CHANNELS || period == 0u || period > 0x7FFFFFFFu ||
        allows > EAT_SAMPLER_ALLOW) { return 0; }
    for (i = 0; i < count; i++) {
        uint32_t allowed = 0u;
        for (j = 0; j < 3u; j++) { channels[i][j] = buf[EAT_SAMPLER_CHANNEL_BASE + i * 3u + j]; }
        if (channels[i][0] == EAT_S_PORT) {
            if (port == NULL || port->read_channel == NULL) { return 0; }
        } else if (channels[i][0] == EAT_S_MEMORY) {
            uint32_t address = channels[i][1], width = channels[i][2];
            if ((width != 8u && width != 16u && width != 32u) || address % (width / 8u) != 0u ||
                address > 0xFFFFFFFFu - (width / 8u - 1u)) { return 0; }
            for (j = 0; j < allows; j++) {
                if (buf[EAT_SAMPLER_ALLOW_BASE + j * 2u] == address &&
                    buf[EAT_SAMPLER_ALLOW_BASE + j * 2u + 1u] == width) { allowed = 1u; }
            }
            if (!allowed) { return 0; }
        } else { return 0; }
    }
    return 1;
}

int eat_sampler_push(uint32_t now_ms, const uint32_t *values, uint32_t n)
{
    uint32_t i, write, read, seq, stored = 0u;
    if (buf == NULL || buf[EAT_S_ENABLE] == 0u || buf[EAT_S_STATE] != 1u || n != count || values == NULL) {
        return 0;
    }
    buf[EAT_S_EPOCH]++;
    barrier();
    seq = buf[EAT_S_SEQUENCE] + 1u;
    write = buf[EAT_S_WRITE];
    read = buf[EAT_S_READ];
    barrier();
    if ((uint32_t)(write - read) >= capacity) {
        buf[EAT_S_OVERRUN]++;
    } else {
        volatile uint32_t *row = &buf[EAT_SAMPLER_DATA + (write & (capacity - 1u)) * EAT_SAMPLER_ROW];
        row[0] = seq;
        row[1] = now_ms;
        for (i = 0; i < EAT_SAMPLER_CHANNELS; i++) { row[2u + i] = i < count ? values[i] : 0u; }
        barrier();
        buf[EAT_S_WRITE] = write + 1u;
        stored = 1u;
    }
    buf[EAT_S_SEQUENCE] = seq;
    buf[EAT_S_TIME] = now_ms;
    barrier();
    buf[EAT_S_EPOCH]++;
    return (int)stored;
}

void eat_sampler_tick(uint32_t now_ms)
{
    uint32_t i, values[EAT_SAMPLER_CHANNELS];
    if (buf == NULL) { return; }
    if (buf[EAT_S_ENABLE] == 0u) {
        if (buf[EAT_S_STATE] != 0u) {
            buf[EAT_S_EPOCH]++;
            barrier();
            buf[EAT_S_TIME] = now_ms; /* include idle/stalled time before stop in measured rate */
            barrier();
            buf[EAT_S_EPOCH]++;
            barrier();
            buf[EAT_S_STATE] = 0u; /* acknowledge only after producer is quiescent */
        }
        return;
    }
    if (buf[EAT_S_STATE] == 0u) {
        barrier();
        if (!configure()) { buf[EAT_S_ERROR] = 1u; buf[EAT_S_STATE] = 2u; return; }
        last_ms = now_ms;
        buf[EAT_S_EPOCH]++;
        barrier();
        buf[EAT_S_TIME] = now_ms;
        buf[EAT_S_START_TIME] = now_ms;
        buf[EAT_S_START_SEQUENCE] = buf[EAT_S_SEQUENCE];
        buf[EAT_S_START_OVERRUN] = buf[EAT_S_OVERRUN];
        buf[EAT_S_ERROR] = 0u;
        barrier();
        buf[EAT_S_EPOCH]++;
        barrier();
        buf[EAT_S_STATE] = 1u;
        return;
    }
    if (buf[EAT_S_STATE] != 1u || (uint32_t)(now_ms - last_ms) < period) { return; }
    last_ms = now_ms; /* no fabricated catch-up samples after a delayed tick */
    for (i = 0; i < count; i++) {
        values[i] = channels[i][0] == EAT_S_MEMORY ? memory_read(channels[i][1], channels[i][2]) :
            port->read_channel(channels[i][1]);
    }
    (void)eat_sampler_push(now_ms, values, count);
}
