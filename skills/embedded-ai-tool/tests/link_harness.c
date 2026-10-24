/* Host test double: the real stub core and serial link over simulated target memory.
 * Built by tests/test_link.py; mirrors the fictional example board (RAM, peripherals, UID). */
#include "eat_link.h"
#include "eat_stub_core.h"

#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT
#endif

#define RAM_BASE 0x20000000u
#define RAM_SIZE 0x10000u
#define IO_BASE 0x50000000u
#define IO_SIZE 0x40000u
#define UID_BASE 0x50FF0000u
#define TX_MAX 8192

static uint32_t ram_words[RAM_SIZE / 4u]; /* word aligned: the core's mailbox lives at RAM_BASE */
#define ram ((uint8_t *)ram_words)
static uint8_t io[IO_SIZE];
static const uint8_t uid[4] = {0xa1, 0xb2, 0xc3, 0xd4};
static uint32_t now_ms;
static uint8_t tx[TX_MAX];
static int tx_count;
static int with_stub;

static uint8_t *cell(uint32_t address)
{
    if (address - RAM_BASE < RAM_SIZE) {
        return &ram[address - RAM_BASE];
    }
    if (address - IO_BASE < IO_SIZE) {
        return &io[address - IO_BASE];
    }
    return 0;
}

static uint32_t mem_read(uint32_t address, uint32_t width)
{
    uint32_t value = 0;
    uint32_t i;

    for (i = 0; i < width / 8u; i++) {
        uint8_t *p = cell(address + i);
        uint8_t byte = p ? *p : (address + i - UID_BASE < sizeof uid ? uid[address + i - UID_BASE] : 0u);
        value |= (uint32_t)byte << (8u * i);
    }
    return value;
}

static void mem_write(uint32_t address, uint32_t width, uint32_t value)
{
    uint32_t i;

    for (i = 0; i < width / 8u; i++) {
        uint8_t *p = cell(address + i);
        if (p) {
            *p = (uint8_t)(value >> (8u * i));
        }
    }
}

static uint32_t port_millis(void) { return now_ms; }

static void port_send(const uint8_t *data, uint32_t length)
{
    uint32_t i;

    for (i = 0; i < length && tx_count < TX_MAX; i++) {
        tx[tx_count++] = data[i];
    }
}

static void port_write_masked(uint32_t address, uint32_t width, uint32_t mask, uint32_t value)
{
    mem_write(address, width, (mem_read(address, width) & ~mask) | (value & mask));
}

static uint32_t port_call(uint32_t entry, const uint32_t args[4]) { return entry + args[0] + args[1]; }

static const eat_hal hal = {port_millis, port_write_masked, port_call};
static const eat_link_port link = {port_send, port_millis, mem_read, mem_write};

/* stub=1: the core runs with its mailbox at RAM_BASE (word-aligned host array). */
EXPORT void t_init(int stub)
{
    uint32_t i;

    for (i = 0; i < RAM_SIZE; i++) {
        ram[i] = 0;
    }
    for (i = 0; i < IO_SIZE; i++) {
        io[i] = 0;
    }
    now_ms = 0;
    tx_count = 0;
    with_stub = stub;
    if (stub) {
        eat_stub_init(&hal, (volatile uint32_t *)(void *)ram, 128u);
    }
    eat_link_init(&link, stub ? RAM_BASE : 0u, stub ? 128u : 0u);
}

/* Bytes from the host; the main loop then polls the core and 5 ms pass. */
EXPORT void t_feed(const uint8_t *data, int length)
{
    int i;

    for (i = 0; i < length; i++) {
        eat_link_rx(data[i]);
    }
    if (with_stub) {
        eat_stub_poll();
    }
    now_ms += 5u;
}

EXPORT void t_idle(uint32_t ms)
{
    uint32_t t;

    for (t = 0; t < ms; t += 5u) {
        now_ms += 5u;
        if (with_stub) {
            eat_stub_poll();
        }
    }
}

EXPORT int t_take(uint8_t *out, int max)
{
    int n = tx_count < max ? tx_count : max;
    int i;

    for (i = 0; i < n; i++) {
        out[i] = tx[i];
    }
    for (i = n; i < tx_count; i++) {
        tx[i - n] = tx[i];
    }
    tx_count -= n;
    return n;
}

EXPORT uint32_t t_crc(const uint8_t *data, uint32_t length) { return eat_link_crc16(data, length, 0xFFFFu); }
EXPORT uint32_t t_peek(uint32_t address, uint32_t width) { return mem_read(address, width); }
EXPORT void t_poke(uint32_t address, uint32_t width, uint32_t value) { mem_write(address, width, value); }
