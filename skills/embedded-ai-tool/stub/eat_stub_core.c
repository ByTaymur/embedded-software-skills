#include "eat_stub_core.h"

static const eat_hal *hal;
static volatile uint32_t *mb;
static uint32_t mb_words;
static uint32_t last_host_hb;
static uint32_t last_change_ms;
static uint32_t was_armed;
static uint32_t fired;

static void apply_safe(void)
{
    uint32_t capacity = (mb_words - EAT_HEADER_WORDS) / EAT_SAFE_ROW_WORDS;
    uint32_t count = mb[EAT_W_SAFE_COUNT];
    uint32_t i;

    if (count > capacity) {
        count = capacity;
    }
    for (i = 0; i < count; i++) {
        volatile uint32_t *row = &mb[EAT_HEADER_WORDS + i * EAT_SAFE_ROW_WORDS];
        hal->write_masked(row[0], row[1], row[2], row[3]);
    }
}

static void fire_deadman(void)
{
    apply_safe();
    fired = 1;
    mb[EAT_W_DEADMAN_COUNT] = mb[EAT_W_DEADMAN_COUNT] + 1u;
    mb[EAT_W_STATUS] = EAT_DEADMAN;
}

void eat_stub_init(const eat_hal *port, volatile uint32_t *mailbox, uint32_t mailbox_words)
{
    uint32_t i;

    hal = port;
    mb = mailbox;
    mb_words = mailbox_words;
    for (i = 0; i < mailbox_words; i++) {
        mb[i] = 0;
    }
    last_host_hb = 0;
    last_change_ms = hal->millis();
    was_armed = 0;
    fired = 0;
    mb[EAT_W_VERSION] = EAT_PROTOCOL;
    mb[EAT_W_MAGIC] = EAT_MAGIC; /* last: the host treats the mailbox as valid only after this */
}

void eat_stub_poll(void)
{
    uint32_t now = hal->millis();
    uint32_t host_hb = mb[EAT_W_HOST_HB];
    uint32_t armed = mb[EAT_W_ARMED] != 0;
    uint32_t seq;

    mb[EAT_W_STUB_HB] = mb[EAT_W_STUB_HB] + 1u;

    /* Any host heartbeat change, or the moment the table is armed, restarts the countdown. */
    if (host_hb != last_host_hb || (armed && !was_armed)) {
        last_host_hb = host_hb;
        last_change_ms = now;
        if (fired) {
            fired = 0;
            if (mb[EAT_W_STATUS] == EAT_DEADMAN) {
                mb[EAT_W_STATUS] = EAT_IDLE;
            }
        }
    }
    was_armed = armed;

    if (armed && !fired && (uint32_t)(now - last_change_ms) >= mb[EAT_W_TIMEOUT_MS]) {
        fire_deadman();
    }

    seq = mb[EAT_W_CALL_SEQ];
    if (seq != mb[EAT_W_DONE_SEQ]) {
        uint32_t args[4];
        uint32_t i;

        for (i = 0; i < 4; i++) {
            args[i] = mb[EAT_W_ARGS + i];
        }
        mb[EAT_W_ERROR] = 0;
        mb[EAT_W_STATUS] = EAT_BUSY;
        mb[EAT_W_RESULT] = hal->call_entry(mb[EAT_W_ENTRY], args);
        mb[EAT_W_STATUS] = EAT_OK; /* dead-man history lives in EAT_W_DEADMAN_COUNT */
        mb[EAT_W_DONE_SEQ] = seq; /* last: the host waits for done_seq == call_seq */
    }
}

void eat_stub_fault(uint32_t code)
{
    /* A disarmed table is stale (released pins) or half rewritten by the host; never replay it. */
    if (mb[EAT_W_ARMED] != 0) {
        apply_safe();
    }
    mb[EAT_W_ERROR] = code;
    mb[EAT_W_RESULT] = 0;
    mb[EAT_W_STATUS] = EAT_FAULT;
    mb[EAT_W_DONE_SEQ] = mb[EAT_W_CALL_SEQ];
}
