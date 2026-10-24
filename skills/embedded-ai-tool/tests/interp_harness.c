/* Host port: no hardware addresses or vendor headers. */
#include "eat_interp.h"
#include "eat_link.h"
#include "eat_stub_core.h"
#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT
#endif
static eat_interp ctx;
static uint32_t memory[EAT_INTERP_WORDS],pins[16],adc[16],duty[16],frequency[16];
static uint32_t now,denied,writes,stops,pending,cost,prepare_failure;
static uint8_t tx[8192];
static uint32_t tx_count;
static uint32_t millis(void) { return now; }
static void noop(void) { }
static int allow(const uint32_t *r)
{ return r[2]<16u && r[2]!=denied && r[4]==0x50000000u+4u*r[2] && r[5]==4u && r[6]==32u; }
static int safe(const uint32_t *r)
{ return r[0]>=0x50000000u && r[0]<0x50000040u && r[0]%4u==0u && r[1]==32u && r[2]==1u && !r[3]; }
static int prepare(const uint32_t *r) { return allow(r) && !prepare_failure?0:2; }
static void release(const uint32_t *r) { (void)r; }
static int gpio_read(uint32_t r,uint32_t *v) { *v=pins[r]; return 0; }
static int gpio_write(uint32_t r,uint32_t v) { pins[r]=v; writes++; return 0; }
static int gpio_mode(uint32_t r,uint32_t f) { (void)r; (void)f; return 0; }
static int analog_start(uint32_t r) { (void)r; return 0; }
static int analog_read(uint32_t r,uint32_t *v) { *v=adc[r]; return pending?1:0; }
static void analog_cancel(uint32_t r) { (void)r; }
static int pwm_set(uint32_t r,uint32_t d,uint32_t f) { duty[r]=d; frequency[r]=f; return 0; }
static void pwm_stop(uint32_t r) { duty[r]=0u; }
static void safe_stop(void) { uint32_t i; stops++; for(i=0;i<16u;i++) { duty[i]=0u; } }
static void safe_write(const uint32_t *r) { pins[(r[0]-0x50000000u)/4u]=r[3]; }
static uint32_t opcode_cost(uint32_t op) { return op>=0x20u && op<=0x25u?cost:1u; }
static const eat_interp_port port={millis,allow,safe,allow,prepare,release,gpio_read,gpio_write,
    gpio_mode,analog_start,analog_read,analog_cancel,pwm_set,pwm_stop,safe_stop,safe_write,
    noop,noop,noop,noop,opcode_cost};
static uint32_t read_memory(uint32_t address,uint32_t width)
{
    uint32_t value=0u,i,off=address-0x20000000u;
    const uint8_t *p=(const uint8_t *)(const void *)memory;
    if(address>=0x50FF0000u && address<0x50FF0004u) { return (0xD4C3B2A1u>>(8u*(address-0x50FF0000u)))&255u; }
    if(off>=sizeof memory || width/8u>sizeof memory-off) { return 0u; }
    for(i=0;i<width/8u;i++) { value|=(uint32_t)p[off+i]<<(8u*i); } return value;
}
static void write_memory(uint32_t address,uint32_t width,uint32_t value)
{
    uint32_t i,off=address-0x20000000u;
    uint8_t *p=(uint8_t *)(void *)memory;
    if(off>=sizeof memory || width/8u>sizeof memory-off) { return; }
    for(i=0;i<width/8u;i++) { p[off+i]=(uint8_t)(value>>(8u*i)); }
}
static void send(const uint8_t *p,uint32_t n)
{ uint32_t i; for(i=0;i<n && tx_count<sizeof tx;i++) { tx[tx_count++]=p[i]; } }
static const eat_link_port link={send,millis,read_memory,write_memory};
static void masked(uint32_t at,uint32_t width,uint32_t mask,uint32_t value)
{ write_memory(at,width,(read_memory(at,width)&~mask)|(value&mask)); }
static uint32_t call(uint32_t entry,const uint32_t args[4]) { (void)entry; (void)args; return 0u; }
static const eat_hal hal={millis,masked,call};
EXPORT void i_init(void)
{
    uint32_t i;
    now=0u; denied=99u; writes=0u; stops=0u; pending=0u; cost=1u; tx_count=0u; prepare_failure=0u;
    for(i=0;i<16u;i++) { pins[i]=0u; adc[i]=0u; duty[i]=0u; frequency[i]=0u; }
    eat_stub_init(&hal,memory,EAT_INTERP_WORDS);
    (void)eat_interp_init(&ctx,&port,memory,EAT_INTERP_WORDS,1u,123u,1000u);
    eat_stub_attach_interp(&ctx);
    eat_link_init(&link,0x20000000u,EAT_INTERP_WORDS);
}
EXPORT uint32_t *i_memory(void) { return memory; }
EXPORT void i_tick(uint32_t ms) { now+=ms; eat_stub_poll(); }
EXPORT void i_adc(uint32_t r,uint32_t value) { adc[r]=value; }
EXPORT void i_deny(uint32_t r) { denied=r; }
EXPORT void i_pending(uint32_t v) { pending=v; }
EXPORT void i_cost(uint32_t v) { cost=v; }
EXPORT void i_prepare_fail(uint32_t v) { prepare_failure=v; }
EXPORT void i_fault(uint32_t code) { eat_stub_fault(code); }
EXPORT uint32_t i_pwm(uint32_t r) { return duty[r]; }
EXPORT uint32_t i_pin(uint32_t r) { return pins[r]; }
EXPORT uint32_t i_writes(void) { return writes; }
EXPORT uint32_t i_stops(void) { return stops; }
EXPORT uint32_t i_var(uint32_t task,uint32_t slot) { return ctx.task[task].var[slot]; }
EXPORT uint32_t i_param(uint32_t slot) { return ctx.params[slot]; }
EXPORT uint32_t i_reg(uint32_t task,uint32_t slot) { return ctx.task[task].reg[slot]; }
EXPORT void i_event(uint32_t id,uint32_t value) { (void)eat_interp_event_push(&ctx,id,5u,value,now); }
EXPORT uint32_t i_crc(const uint8_t *data,uint32_t n) { return eat_interp_crc32(data,n); }
EXPORT uint32_t i_read(uint32_t a,uint32_t w) { return read_memory(a,w); }
EXPORT void i_write(uint32_t a,uint32_t w,uint32_t v) { write_memory(a,w,v); }
EXPORT void t_feed(const uint8_t *p,int n) { int i; for(i=0;i<n;i++) { eat_link_rx(p[i]); } now++; eat_stub_poll(); }
EXPORT int t_take(uint8_t *out,int max)
{
    uint32_t i,n=tx_count<(uint32_t)max?tx_count:(uint32_t)max;
    for(i=0;i<n;i++) { out[i]=tx[i]; }
    for(i=n;i<tx_count;i++) { tx[i-n]=tx[i]; } tx_count-=n; return (int)n;
}
