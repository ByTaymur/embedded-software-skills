/* Embedded AI Tool stub core: mailbox protocol, dead-man timer, RAM-call dispatcher.
 *
 * MCU independent. A port supplies the three hal functions plus startup code; see README.md.
 * Word layout and ownership are normative in ../references/stub-protocol.md and are checked
 * against the host implementation (scripts/embedded_ai_tool/live.py) by the test suite.
 */
#ifndef EAT_STUB_CORE_H
#define EAT_STUB_CORE_H

#include <stdint.h>
#include "eat_interp.h"

#define EAT_MAGIC 0x53544145u /* bytes "EATS" in little-endian memory */
#define EAT_PROTOCOL 1u

#define EAT_W_MAGIC 0
#define EAT_W_VERSION 1
#define EAT_W_STUB_HB 2
#define EAT_W_HOST_HB 3
#define EAT_W_CALL_SEQ 4
#define EAT_W_DONE_SEQ 5
#define EAT_W_STATUS 6
#define EAT_W_ENTRY 7
#define EAT_W_ARGS 8
#define EAT_W_RESULT 12
#define EAT_W_ERROR 13
#define EAT_W_ARMED 14
#define EAT_W_TIMEOUT_MS 15
#define EAT_W_SAFE_COUNT 16
#define EAT_W_DEADMAN_COUNT 17
#define EAT_HEADER_WORDS 18
#define EAT_SAFE_ROW_WORDS 4

enum { EAT_IDLE = 0, EAT_BUSY = 1, EAT_OK = 2, EAT_FAULT = 3, EAT_DEADMAN = 4 };

typedef struct {
    /* Monotonic milliseconds; wraparound is handled. */
    uint32_t (*millis)(void);
    /* reg = (reg & ~mask) | (value & mask), using a width_bits (8/16/32) access. */
    void (*write_masked)(uint32_t address, uint32_t width_bits, uint32_t mask, uint32_t value);
    /* Call code at entry with four arguments and return its result. The host has already applied
     * any architecture call bits from the profile (live.entry_or, e.g. Cortex-M Thumb bit). */
    uint32_t (*call_entry)(uint32_t entry, const uint32_t args[4]);
} eat_hal;

/* Zeroes the mailbox, publishes magic/version. mailbox_words must be >= EAT_HEADER_WORDS + 4. */
void eat_stub_init(const eat_hal *hal, volatile uint32_t *mailbox, uint32_t mailbox_words);

/* Call from the main loop, never from an interrupt that the called RAM code may block. */
void eat_stub_poll(void);

/* Call from the fault handler: replays the safe table, records the fault and marks the call failed. */
void eat_stub_fault(uint32_t code);

#if EAT_INTERP_ENABLE
/* Initialize the separate port/context with eat_interp_init first, then attach it.
 * v1 dispatch and safe table are replaced only after this explicit registration. */
void eat_stub_attach_interp(eat_interp *ctx);
#endif

#endif
