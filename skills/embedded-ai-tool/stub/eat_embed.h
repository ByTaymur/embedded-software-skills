/* Embedded AI Tool: drop-in integration for an existing firmware on any 32-bit MCU.
 *
 *   #include "eat_embed.h"
 *   eat_embed_init(app_millis, uart_send);      // uart_send may be NULL (debug probe only)
 *   for (;;) {
 *       while (uart_has_byte()) eat_link_rx(uart_read_byte());
 *       eat_stub_poll();
 *       #if EAT_SAMPLER_SLOTS > 0
 *       eat_sampler_tick(app_millis());       // now_ms; call here OR from a periodic timer ISR
 *       #endif
 *       app_step();
 *   }
 *   // fault / trap handler of your architecture:  eat_stub_fault(code);
 *
 * The host finds the mailbox through the ELF symbol `eat_mailbox` (profile: "mailbox": {"symbol":
 * "eat_mailbox"}), so no linker script or fixed address is needed. Generic memory access uses
 * volatile pointers and RAM calls use a plain C function pointer; override with your own port
 * (eat_stub_core.h / eat_link.h) where the architecture needs something else.
 */
#ifndef EAT_EMBED_H
#define EAT_EMBED_H

#include <stdint.h>

#include "eat_link.h"
#include "eat_stub_core.h"
#include "eat_sampler.h"

#ifndef EAT_SAMPLER_SLOTS
#define EAT_SAMPLER_SLOTS 0u
#endif
#if EAT_SAMPLER_SLOTS > 0
extern volatile uint32_t eat_samples[EAT_SAMPLER_WORDS(EAT_SAMPLER_SLOTS)];
#endif

#ifndef EAT_MAILBOX_WORDS
#if EAT_INTERP_ENABLE
#define EAT_MAILBOX_WORDS EAT_INTERP_WORDS
#else
#define EAT_MAILBOX_WORDS 64u /* header 18 words + 11 safe-state rows */
#endif
#endif

/* Bytes of RAM for host-loaded code (ram load/run); 0 disables. Some architectures can only run code
 * from particular RAM: put that section/attribute in EAT_SCRATCH_ATTR. */
#ifndef EAT_SCRATCH_BYTES
#define EAT_SCRATCH_BYTES 0u
#endif
#ifndef EAT_SCRATCH_ATTR
#define EAT_SCRATCH_ATTR
#endif

extern volatile uint32_t eat_mailbox[EAT_MAILBOX_WORDS];
#if EAT_SCRATCH_BYTES > 0
extern EAT_SCRATCH_ATTR uint32_t eat_scratch[(EAT_SCRATCH_BYTES + 3u) / 4u];
#endif

/* millis: monotonic milliseconds. send: transmits serial link frames, or NULL without a serial link. */
void eat_embed_init(uint32_t (*millis)(void), void (*send)(const uint8_t *data, uint32_t length));

#endif
