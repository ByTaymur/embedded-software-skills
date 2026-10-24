#include "eat_link.h"

#define HEADER_BYTES 4u /* sync0 sync1 length_lo length_hi */
#define TRAILER_BYTES 2u
#define RESPONSE_DATA_MAX (EAT_LINK_MAX_PAYLOAD - 2u)

static const eat_link_port *port;
static uint32_t box_address;
static uint32_t box_words;

static uint8_t rx[EAT_LINK_MAX_PAYLOAD + TRAILER_BYTES];
static uint32_t rx_state; /* 0,1: sync; 2,3: length; 4: payload + crc */
static uint32_t rx_length;
static uint32_t rx_count;
static uint32_t rx_last_ms;

static uint8_t tx[HEADER_BYTES + EAT_LINK_MAX_PAYLOAD + TRAILER_BYTES];
static uint32_t tx_length; /* payload bytes so far */

uint16_t eat_link_crc16(const uint8_t *data, uint32_t length, uint16_t crc)
{
    uint32_t i;
    int bit;

    for (i = 0; i < length; i++) {
        crc ^= (uint16_t)(data[i] << 8);
        for (bit = 0; bit < 8; bit++) {
            crc = (crc & 0x8000u) ? (uint16_t)((crc << 1) ^ 0x1021u) : (uint16_t)(crc << 1);
        }
    }
    return crc;
}

static uint32_t get(const uint8_t *p, uint32_t bytes)
{
    uint32_t value = 0;
    uint32_t i;

    for (i = 0; i < bytes; i++) {
        value |= (uint32_t)p[i] << (8u * i);
    }
    return value;
}

static int put(uint32_t value, uint32_t bytes)
{
    uint32_t i;

    if (tx_length + bytes > EAT_LINK_MAX_PAYLOAD) {
        return 0;
    }
    for (i = 0; i < bytes; i++) {
        tx[HEADER_BYTES + tx_length++] = (uint8_t)(value >> (8u * i));
    }
    return 1;
}

static void respond(uint32_t status)
{
    uint16_t crc;

    tx[HEADER_BYTES + 1u] = (uint8_t)status;
    if (status != EAT_LINK_OK) {
        tx_length = 2u; /* no data on errors */
    }
    tx[0] = EAT_LINK_SYNC0;
    tx[1] = EAT_LINK_SYNC1;
    tx[2] = (uint8_t)tx_length;
    tx[3] = (uint8_t)(tx_length >> 8);
    crc = eat_link_crc16(&tx[2], 2u + tx_length, 0xFFFFu);
    tx[HEADER_BYTES + tx_length] = (uint8_t)crc;
    tx[HEADER_BYTES + tx_length + 1u] = (uint8_t)(crc >> 8);
    port->send(tx, HEADER_BYTES + tx_length + TRAILER_BYTES);
}

static int valid_access(uint32_t address, uint32_t width, uint32_t count)
{
    uint32_t bytes = width / 8u;

    if (width != 8u && width != 16u && width != 32u) {
        return 0;
    }
    return count > 0u && address % bytes == 0u && address <= 0xFFFFFFFFu - (count * bytes - 1u);
}

/* Runs one validated request; returns the response status. Response data is appended with put(). */
static uint32_t execute(uint32_t command, const uint8_t *args, uint32_t length)
{
    uint32_t address, width, count, i;

    switch (command) {
    case EAT_CMD_INFO:
        put(EAT_LINK_PROTOCOL, 1u);
        put(EAT_LINK_MAX_PAYLOAD, 2u);
        put(box_address, 4u);
        put(box_words, 4u);
        return EAT_LINK_OK;
    case EAT_CMD_READ:
    case EAT_CMD_WRITE:
        if (length < 7u) {
            return EAT_LINK_BAD_REQUEST;
        }
        address = get(args, 4u);
        width = args[4];
        count = get(args + 5, 2u);
        if (!valid_access(address, width, count)) {
            return EAT_LINK_ALIGNMENT;
        }
        if (command == EAT_CMD_READ) {
            if (count * (width / 8u) > RESPONSE_DATA_MAX) {
                return EAT_LINK_BAD_REQUEST;
            }
            for (i = 0; i < count; i++) {
                put(port->read(address + i * (width / 8u), width), width / 8u);
            }
            return EAT_LINK_OK;
        }
        if (length != 7u + count * (width / 8u)) {
            return EAT_LINK_BAD_REQUEST;
        }
        for (i = 0; i < count; i++) {
            port->write(address + i * (width / 8u), width, get(args + 7u + i * (width / 8u), width / 8u));
        }
        return EAT_LINK_OK;
    case EAT_CMD_MODIFY: {
        uint32_t mask, value, previous;

        if (length != 13u) {
            return EAT_LINK_BAD_REQUEST;
        }
        address = get(args, 4u);
        width = args[4];
        mask = get(args + 5, 4u);
        value = get(args + 9, 4u);
        if (!valid_access(address, width, 1u) || (value & ~mask) != 0u) {
            return EAT_LINK_ALIGNMENT;
        }
        previous = port->read(address, width);
        port->write(address, width, (previous & ~mask) | value);
        put(previous, 4u);
        return EAT_LINK_OK;
    }
    case EAT_CMD_INCREMENT_IF: {
        uint32_t check, expected;

        if (length != 12u) {
            return EAT_LINK_BAD_REQUEST;
        }
        check = get(args, 4u);
        expected = get(args + 4, 4u);
        address = get(args + 8, 4u);
        if (!valid_access(check, 32u, 1u) || !valid_access(address, 32u, 1u)) {
            return EAT_LINK_ALIGNMENT;
        }
        if (port->read(check, 32u) == expected) {
            port->write(address, 32u, port->read(address, 32u) + 1u);
            put(1u, 1u);
        } else {
            put(0u, 1u);
        }
        return EAT_LINK_OK;
    }
    default:
        return EAT_LINK_UNKNOWN;
    }
}

static void handle(const uint8_t *payload, uint32_t length)
{
    uint32_t guard_address, guard_length, i;

    tx_length = 0;
    put(length ? payload[0] : 0u, 1u); /* seq */
    put(EAT_LINK_OK, 1u);              /* status, patched by respond() */
    if (length < 8u) {
        respond(EAT_LINK_BAD_REQUEST);
        return;
    }
    guard_address = get(payload + 2, 4u);
    guard_length = payload[6];
    if (length < 7u + guard_length) {
        respond(EAT_LINK_BAD_REQUEST);
        return;
    }
    /* Identity first: a request meant for another board does nothing at all. */
    for (i = 0; i < guard_length; i++) {
        if (port->read(guard_address + i, 8u) != payload[7u + i]) {
            respond(EAT_LINK_IDENTITY);
            return;
        }
    }
    respond(execute(payload[1], payload + 7u + guard_length, length - 7u - guard_length));
}

void eat_link_init(const eat_link_port *link_port, uint32_t mailbox_address, uint32_t mailbox_words)
{
    port = link_port;
    box_address = mailbox_address;
    box_words = mailbox_words;
    rx_state = 0;
    rx_last_ms = port->millis();
}

void eat_link_rx(uint8_t byte)
{
    uint32_t now = port->millis();

    if (rx_state != 0u && (uint32_t)(now - rx_last_ms) > EAT_LINK_BYTE_TIMEOUT_MS) {
        rx_state = 0;
    }
    rx_last_ms = now;
    switch (rx_state) {
    case 0:
        rx_state = byte == EAT_LINK_SYNC0 ? 1u : 0u;
        break;
    case 1:
        rx_state = byte == EAT_LINK_SYNC1 ? 2u : (byte == EAT_LINK_SYNC0 ? 1u : 0u);
        break;
    case 2:
        rx_length = byte;
        rx_state = 3;
        break;
    case 3:
        rx_length |= (uint32_t)byte << 8;
        rx_count = 0;
        rx_state = (rx_length == 0u || rx_length > EAT_LINK_MAX_PAYLOAD) ? 0u : 4u;
        break;
    default:
        rx[rx_count++] = byte;
        if (rx_count == rx_length + TRAILER_BYTES) {
            uint8_t length_bytes[2];
            uint16_t crc;

            length_bytes[0] = (uint8_t)rx_length;
            length_bytes[1] = (uint8_t)(rx_length >> 8);
            crc = eat_link_crc16(length_bytes, 2u, 0xFFFFu);
            crc = eat_link_crc16(rx, rx_length, crc);
            rx_state = 0;
            if (crc == (uint16_t)get(rx + rx_length, 2u)) {
                handle(rx, rx_length); /* a corrupt frame gets no answer: the host times out */
            }
        }
        break;
    }
}
