/* Embedded AI Tool serial link: memory access over a byte stream (UART, USB CDC, ...) for targets
 * or setups without a debug probe. Architecture independent C99; the port supplies the hooks below.
 *
 * Frame (both directions, multi-byte fields little-endian regardless of the target byte order):
 *   0xEA 0x7E | length u16 | payload[length] | crc16 u16      crc16/CCITT-FALSE over length+payload
 * Request payload:  seq u8 | command u8 | guard_address u32 | guard_length u8 | guard bytes | arguments
 * Response payload: seq u8 | status u8 | data
 * A request runs only if the guard_length bytes at guard_address equal the guard bytes (the board
 * identity). Normative description: ../references/stub-protocol.md, checked against
 * scripts/embedded_ai_tool/link.py by the test suite.
 */
#ifndef EAT_LINK_H
#define EAT_LINK_H

#include <stdint.h>

#define EAT_LINK_PROTOCOL 1u
#define EAT_LINK_SYNC0 0xEAu
#define EAT_LINK_SYNC1 0x7Eu

#ifndef EAT_LINK_MAX_PAYLOAD
#define EAT_LINK_MAX_PAYLOAD 1024u
#endif
#ifndef EAT_LINK_BYTE_TIMEOUT_MS
#define EAT_LINK_BYTE_TIMEOUT_MS 100u /* a stalled partial frame is dropped */
#endif

#define EAT_CMD_INFO 0x01u         /* -> protocol u8, max_payload u16, mailbox_address u32, mailbox_words u32 */
#define EAT_CMD_READ 0x02u         /* address u32, width u8, count u16 -> values (width/8 bytes each) */
#define EAT_CMD_WRITE 0x03u        /* address u32, width u8, count u16, values */
#define EAT_CMD_MODIFY 0x04u       /* address u32, width u8, mask u32, value u32 -> previous u32 */
#define EAT_CMD_INCREMENT_IF 0x05u /* check_address u32, expected u32, address u32 -> done u8 */

#define EAT_LINK_OK 0u
#define EAT_LINK_BAD_REQUEST 1u
#define EAT_LINK_IDENTITY 2u
#define EAT_LINK_UNKNOWN 3u
#define EAT_LINK_ALIGNMENT 4u

typedef struct {
    /* Transmit a whole response frame. */
    void (*send)(const uint8_t *data, uint32_t length);
    /* Monotonic milliseconds (the stub core's clock can be reused). */
    uint32_t (*millis)(void);
    /* One aligned access of width_bits (8/16/32); generic ports use volatile pointers. */
    uint32_t (*read)(uint32_t address, uint32_t width_bits);
    void (*write)(uint32_t address, uint32_t width_bits, uint32_t value);
} eat_link_port;

/* mailbox_address/words are reported by INFO so the host can find the stub; pass 0 if unused. */
void eat_link_init(const eat_link_port *port, uint32_t mailbox_address, uint32_t mailbox_words);

/* Feed received bytes from the main loop (not from an interrupt that may preempt eat_stub_poll). */
void eat_link_rx(uint8_t byte);

uint16_t eat_link_crc16(const uint8_t *data, uint32_t length, uint16_t crc);

#endif
