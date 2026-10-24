#ifndef EAT_INTERP_H
#define EAT_INTERP_H
#include <stdint.h>
#include "eat_ring.h"

#ifndef EAT_INTERP_ENABLE
#define EAT_INTERP_ENABLE 0
#endif
#ifndef EAT_INTERP_TASKS
#define EAT_INTERP_TASKS 4u
#endif
#ifndef EAT_INTERP_VARS
#define EAT_INTERP_VARS 16u
#endif
#ifndef EAT_INTERP_TIMERS
#define EAT_INTERP_TIMERS 2u
#endif
#ifndef EAT_INTERP_IMAGE_BYTES
#define EAT_INTERP_IMAGE_BYTES 2048u
#endif
#ifndef EAT_INTERP_ALLOW_ROWS
#define EAT_INTERP_ALLOW_ROWS 16u
#endif
#ifndef EAT_INTERP_SAFE_ROWS
#define EAT_INTERP_SAFE_ROWS 16u
#endif
#ifndef EAT_INTERP_RING_RECORDS
#define EAT_INTERP_RING_RECORDS 32u
#endif
#ifndef EAT_INTERP_EVENTS
#define EAT_INTERP_EVENTS 16u
#endif
#ifndef EAT_INTERP_ADC
#define EAT_INTERP_ADC 1
#endif
#ifndef EAT_INTERP_PWM
#define EAT_INTERP_PWM 1
#endif
#ifndef EAT_INTERP_DIV
#define EAT_INTERP_DIV 1
#endif
#ifndef EAT_INTERP_IRQ
#define EAT_INTERP_IRQ 0
#endif
#ifndef EAT_INTERP_NATIVE
#define EAT_INTERP_NATIVE 0
#endif
#if EAT_INTERP_IRQ || EAT_INTERP_NATIVE
#error "IRQ and native calls are disabled in this interpreter slice"
#endif
#define EAT_INTERP_PARAMS 8u
#define EAT_INTERP_SUBSCRIPTIONS 16u
#ifndef EAT_INTERP_BUDGET
#define EAT_INTERP_BUDGET 64u
#endif
#ifndef EAT_INTERP_SLICE
#define EAT_INTERP_SLICE 16u
#endif
#define EAT_INTERP_MAGIC 0x32544145u
#define EAT_INTERP_BANK0 512u
#define EAT_INTERP_BANK1 (EAT_INTERP_BANK0 + EAT_INTERP_IMAGE_BYTES)
#define EAT_INTERP_RING (EAT_INTERP_BANK1 + EAT_INTERP_IMAGE_BYTES)
#define EAT_INTERP_BYTES (EAT_INTERP_RING + 32u + 32u * EAT_INTERP_RING_RECORDS)
#define EAT_INTERP_WORDS ((EAT_INTERP_BYTES + 3u) / 4u)
#if EAT_INTERP_TASKS < 1 || EAT_INTERP_VARS < 1 || EAT_INTERP_TIMERS < 1 || EAT_INTERP_TIMERS > 32
#error "Interpreter task/variable/timer capacities are invalid"
#endif
#if EAT_INTERP_ALLOW_ROWS < 1 || EAT_INTERP_ALLOW_ROWS > 16 || EAT_INTERP_SAFE_ROWS < 1 || EAT_INTERP_EVENTS < 1
#error "Interpreter allow/safe/event capacities are invalid"
#endif
#if EAT_INTERP_IMAGE_BYTES < 136 || EAT_INTERP_IMAGE_BYTES % 8
#error "Interpreter image capacity must be an eight-byte multiple, at least 136"
#endif
#if EAT_INTERP_RING_RECORDS && (EAT_INTERP_RING_RECORDS & (EAT_INTERP_RING_RECORDS - 1))
#error "Interpreter ring capacity must be zero or a power of two"
#endif

enum { EAT_I_OK, EAT_I_FORMAT, EAT_I_CAPACITY, EAT_I_OPCODE, EAT_I_RESERVED,
       EAT_I_INDEX, EAT_I_PC, EAT_I_ALLOW, EAT_I_DISABLED, EAT_I_CRC,
       EAT_I_STATE, EAT_I_STALE_GENERATION, EAT_I_BUDGET_EXCEEDED,
       EAT_I_EVENT_OVERFLOW, EAT_I_DEADMAN, EAT_I_PORT, EAT_I_RANGE,
       EAT_I_MIGRATION, EAT_I_BUSY_PROGRAM };
enum { EAT_I_EMPTY, EAT_I_RECEIVING, EAT_I_VERIFYING, EAT_I_READY, EAT_I_REJECTED };
enum { EAT_I_STOPPED, EAT_I_RUNNING, EAT_I_STOPPED_DEADMAN, EAT_I_FAULT };
enum { EAT_I_GPIO = 1, EAT_I_ADC, EAT_I_PWM_KIND, EAT_I_IRQ_KIND, EAT_I_NATIVE_KIND, EAT_I_SAMPLE };
/* Hooks return 0=complete, 1=pending (ADC only), 2=error. All hooks are bounded.
 * Envelope checks must include application ownership and declared WCET <= slice.
 * Rows are decoded host integers, never hardware pointers. */
typedef struct {
    uint32_t (*millis)(void);
    int (*allow_check)(const uint32_t row[12]);
    int (*safe_check)(const uint32_t row[4]);
    int (*resource_check)(const uint32_t row[12]);
    int (*resource_prepare)(const uint32_t row[12]);
    void (*resource_release)(const uint32_t row[12]);
    int (*gpio_read)(uint32_t resource, uint32_t *value);
    int (*gpio_write)(uint32_t resource, uint32_t value);
    int (*gpio_configure)(uint32_t resource, uint32_t function);
    int (*analog_start)(uint32_t resource);
    int (*analog_read)(uint32_t resource, uint32_t *value);
    void (*analog_cancel)(uint32_t resource);
    int (*pwm_set)(uint32_t resource, uint32_t duty, uint32_t frequency);
    void (*pwm_stop)(uint32_t resource);
    void (*safe_stop)(void);
    void (*safe_write)(const uint32_t row[4]);
    void (*critical_enter)(void);
    void (*critical_leave)(void);
    void (*publish)(void);
    void (*acquire)(void);
    uint32_t (*opcode_cost)(uint32_t opcode);
} eat_interp_port;

typedef struct { uint32_t offset[9], count[9]; } eat_interp_image;
typedef struct {
    uint32_t pc, reg[8], var[EAT_INTERP_VARS], timer[EAT_INTERP_TIMERS];
    uint32_t timer_mask, state, wait, event_a, event_b;
    uint32_t adc_mask, adc_since;
} eat_interp_task;
typedef struct { uint32_t id, value, time, kind; } eat_interp_event;
typedef struct {
    const eat_interp_port *port;
    volatile uint32_t *mb;
    eat_ring ring;
    eat_interp_image image[2];
    eat_interp_task task[EAT_INTERP_TASKS];
    uint32_t allow[EAT_INTERP_ALLOW_ROWS][12], safe[EAT_INTERP_SAFE_ROWS][4];
    uint32_t params[EAT_INTERP_PARAMS], allow_count, safe_count;
    uint32_t adc_last[EAT_INTERP_ALLOW_ROWS], adc_used;
    eat_interp_event events[EAT_INTERP_EVENTS];
    uint32_t event_deadline[EAT_INTERP_SUBSCRIPTIONS];
    uint32_t event_read, event_write, active, has_active, generation, run_state, fault;
    uint32_t candidate, candidate_state, upload_id, total, received, expected_crc, crc;
    uint32_t verify_phase, verify_index, progress_ms, heartbeat, heartbeat_ms, timeout;
    uint32_t now, last_tick, round_robin, capability_hash, initialized;
} eat_interp;

uint32_t eat_interp_crc32(const volatile uint8_t *data, uint32_t length);
int eat_interp_init(eat_interp *ctx, const eat_interp_port *port,
                    volatile uint32_t *mailbox, uint32_t words,
                    uint32_t boot_id, uint32_t capability_hash, uint32_t timeout_ms);
void eat_interp_poll(eat_interp *ctx);
void eat_interp_stop(eat_interp *ctx, uint32_t reason);
/* Fault/trap handler publication; the architecture's handler must not resume bytecode. */
void eat_interp_trap(eat_interp *ctx, uint32_t code);
/* ISR-safe bounded enqueue. Overflow latches a fault; safe hooks run in poll context. */
int eat_interp_event_push(eat_interp *ctx, uint32_t id, uint32_t kind, uint32_t value, uint32_t time);
#endif
