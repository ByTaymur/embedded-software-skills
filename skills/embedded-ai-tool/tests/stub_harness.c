/* Host-side test double for the stub core. Built by tests/test_stub.py into a shared library. */
#include "eat_stub_core.h"

#include <setjmp.h>

#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT
#endif

#define LOG_MAX 64

static uint32_t now_ms;
static uint32_t log_rows[LOG_MAX][4];
static int log_count;
static uint32_t last_entry;
static jmp_buf poll_env;

/* Calling this entry models a hard fault: the handler runs and never returns into the poll loop. */
#define FAULT_ENTRY 0xDEAD0001u

static uint32_t port_millis(void) { return now_ms; }

static void port_write_masked(uint32_t address, uint32_t width, uint32_t mask, uint32_t value)
{
    if (log_count < LOG_MAX) {
        log_rows[log_count][0] = address;
        log_rows[log_count][1] = width;
        log_rows[log_count][2] = mask;
        log_rows[log_count][3] = value;
    }
    log_count++;
}

static uint32_t port_call(uint32_t entry, const uint32_t args[4])
{
    last_entry = entry;
    if (entry == FAULT_ENTRY) {
        eat_stub_fault(0xBADu);
        longjmp(poll_env, 1);
    }
    return args[0] + args[1];
}

static const eat_hal port = {port_millis, port_write_masked, port_call};

EXPORT void t_init(uint32_t *mailbox, uint32_t words)
{
    now_ms = 0;
    log_count = 0;
    eat_stub_init(&port, mailbox, words);
}

EXPORT void t_advance(uint32_t ms)
{
    now_ms += ms;
    if (setjmp(poll_env) == 0) {
        eat_stub_poll();
    }
}

EXPORT int t_log_count(void) { return log_count; }
EXPORT uint32_t t_log_get(int row, int field) { return log_rows[row][field]; }
EXPORT uint32_t t_last_entry(void) { return last_entry; }
