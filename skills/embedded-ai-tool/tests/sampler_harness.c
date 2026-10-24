/* Reuse the simulated memory/link port without changing its existing tests. */
#include "link_harness.c"
#include "eat_sampler.h"
#define SAMPLE_BASE (RAM_BASE + 0x1000u)
static uint32_t channel_reads, memory_reads;
static uint32_t channel_read(uint32_t id) { channel_reads++; return id + now_ms; }
static uint32_t sample_memory(uint32_t address, uint32_t width)
{
    memory_reads++;
    return mem_read(address, width);
}
static const eat_sampler_port sampler_port = {channel_read, sample_memory, 0};
EXPORT void s_init(void)
{
    t_init(0);
    channel_reads = memory_reads = 0u;
    (void)eat_sampler_init(&sampler_port, &ram_words[0x1000u / 4u], 4u);
}
EXPORT void s_advance(uint32_t ms) { now_ms += ms; eat_sampler_tick(now_ms); }
EXPORT void s_sync(void) { eat_sampler_tick(now_ms); }
EXPORT void s_clock(uint32_t ms) { now_ms += ms; }
EXPORT uint32_t s_reads(void) { return channel_reads + memory_reads; }
EXPORT int s_push(uint32_t value)
{
    uint32_t values[1];
    values[0] = value;
    return eat_sampler_push(now_ms, values, 1u);
}
