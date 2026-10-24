#include "eat_interp.h"

/* Section ids: tasks, code, variables, parameters, events, allow, safe, native.
 * See interpreter-design.md for the serialized row contract. */
static const uint32_t row_bytes[9] = {0u,48u,8u,32u,20u,24u,48u,16u,0u};
static volatile uint8_t *bank(eat_interp *c, uint32_t n)
{ return (volatile uint8_t *)(void *)c->mb + EAT_INTERP_BANK0 + n * EAT_INTERP_IMAGE_BYTES; }
static uint32_t word(const volatile uint8_t *p) { return eat_ring_get(p); }
static volatile uint8_t *row(eat_interp *c, uint32_t n, uint32_t section, uint32_t i)
{ return bank(c,n) + c->image[n].offset[section] + row_bytes[section] * i; }
static uint32_t field(eat_interp *c, uint32_t n, uint32_t s, uint32_t i, uint32_t f)
{ return word(row(c,n,s,i) + 4u*f); }
static void decode(const volatile uint8_t *p, uint32_t *out, uint32_t count)
{ uint32_t i; for (i=0; i<count; i++) { out[i]=word(p+4u*i); } }
static uint32_t crc_step(uint32_t crc, const volatile uint8_t *p, uint32_t n)
{
    uint32_t i,j;
    for (i=0;i<n;i++) { crc ^= p[i]; for (j=0;j<8u;j++) { crc=(crc>>1)^((crc&1u)?0xEDB88320u:0u); } }
    return crc;
}
uint32_t eat_interp_crc32(const volatile uint8_t *p, uint32_t n)
{ return crc_step(0xFFFFFFFFu,p,n)^0xFFFFFFFFu; }
static int duration(uint32_t v) { return v && v<0x80000000u; }
static int due(uint32_t now, uint32_t end) { return (uint32_t)(now-end)<0x80000000u; }
static int same(const volatile uint8_t *a, const volatile uint8_t *b, uint32_t n)
{ uint32_t i; for(i=0;i<n;i++) { if(a[i]!=b[i]) { return 0; } } return 1; }
static void emit(eat_interp *c,uint32_t source,uint32_t kind,uint32_t channel,uint32_t value,uint32_t aux)
{ (void)eat_ring_emit(&c->ring,c->now,c->generation,(uint16_t)source,(uint8_t)kind,1u,channel,value,aux,c->port->publish); }
static void safe_rows(eat_interp *c)
{ uint32_t i; for(i=0;i<c->safe_count;i++) { c->port->safe_write(c->safe[i]); } }
void eat_interp_stop(eat_interp *c,uint32_t reason)
{
    uint32_t i;
    if (!c->initialized) { return; }
    for(i=0;i<EAT_INTERP_TASKS;i++) { c->task[i].state=0u; c->task[i].adc_mask=0u; }
    c->port->safe_stop(); safe_rows(c);
    c->event_read=c->event_write;
    c->fault=reason;
    c->run_state=reason==EAT_I_DEADMAN?EAT_I_STOPPED_DEADMAN:(reason?EAT_I_FAULT:EAT_I_STOPPED);
    if(reason==EAT_I_DEADMAN) { c->mb[17]++; }
    emit(c,0u,6u,0u,reason,0u);
}
void eat_interp_trap(eat_interp *c,uint32_t code)
{
    uint32_t sequence;
    if(!c->initialized) { return; }
    sequence=c->mb[45]|1u; c->mb[45]=sequence; c->port->publish();
    eat_interp_stop(c,EAT_I_PORT);
    c->mb[13]=code; c->mb[6]=3u; c->mb[42]=EAT_I_FAULT; c->mb[5]=c->mb[4];
    c->port->publish(); c->mb[45]=sequence+1u;
}
int eat_interp_event_push(eat_interp *c,uint32_t id,uint32_t kind,uint32_t value,uint32_t time)
{
    eat_interp_event *e;
    c->port->critical_enter();
    if((uint32_t)(c->event_write-c->event_read)>=EAT_INTERP_EVENTS) {
        c->fault=EAT_I_EVENT_OVERFLOW; c->port->critical_leave(); return 0;
    }
    e=&c->events[c->event_write%EAT_INTERP_EVENTS];
    e->id=id; e->kind=kind; e->value=value; e->time=time;
    c->port->publish(); c->event_write++; c->port->critical_leave(); return 1;
}
static uint32_t header(eat_interp *c)
{
    uint32_t n=c->candidate,i,j,type,off,len,count,head,sections;
    volatile uint8_t *p=bank(c,n);
    eat_interp_image *m=&c->image[n];
    for(i=0;i<9u;i++) { m->offset[i]=0u; m->count[i]=0u; }
    if(c->total<24u || word(p)!=0x49544145u || p[4]!=1u || p[5] ||
       word(p+8)!=c->total || word(p+12)!=1u || word(p+16)!=c->capability_hash) { return EAT_I_FORMAT; }
    head=(uint32_t)p[6]|((uint32_t)p[7]<<8); sections=word(p+20);
    if(sections!=7u || head!=24u+16u*sections || head>c->total) { return EAT_I_FORMAT; }
    for(i=0;i<sections;i++) {
        volatile uint8_t *d=p+24u+16u*i;
        type=word(d); off=word(d+4); len=word(d+8); count=word(d+12);
        if(type<1u || type>7u || m->offset[type] || off<head || off>c->total || len>c->total-off ||
           off%8u || count>c->total/row_bytes[type] || len!=count*row_bytes[type]) { return EAT_I_FORMAT; }
        for(j=0;j<i;j++) {
            volatile uint8_t *old=p+24u+16u*j;
            uint32_t start=word(old+4), size=word(old+8);
            if(len && size && off<start+size && start<off+len) { return EAT_I_FORMAT; }
        }
        m->offset[type]=off; m->count[type]=count;
    }
    if(m->count[1]>EAT_INTERP_TASKS || m->count[3]>EAT_INTERP_TASKS*EAT_INTERP_VARS ||
       m->count[4]>EAT_INTERP_PARAMS || m->count[5]>EAT_INTERP_SUBSCRIPTIONS ||
       m->count[6]>EAT_INTERP_ALLOW_ROWS || m->count[6]>16u || m->count[7]>EAT_INTERP_SAFE_ROWS) { return EAT_I_CAPACITY; }
    return EAT_I_OK;
}
static uint32_t owner(eat_interp *c,uint32_t n,uint32_t pc)
{
    uint32_t t;
    for(t=0;t<c->image[n].count[1];t++) {
        uint32_t first=field(c,n,1u,t,2u), count=field(c,n,1u,t,3u);
        if(pc>=first && pc-first<count) { return t; }
    }
    return EAT_INTERP_TASKS;
}
static uint32_t instruction(eat_interp *c,uint32_t n,uint32_t pc)
{
    volatile uint8_t *p;
    if(pc>=c->image[n].count[2]) { return EAT_I_PC; }
    p=row(c,n,2u,pc);
    uint32_t op=p[0],a=p[1],b=p[2],d=p[3],k=word(p+4),t=owner(c,n,pc),kind;
    if(t>=c->image[n].count[1]) { return EAT_I_PC; }
    if(op==0x26u || op==0x41u) { return EAT_I_DISABLED; }
    if(!c->port->opcode_cost(op) || c->port->opcode_cost(op)>EAT_INTERP_SLICE) { return EAT_I_RANGE; }
    if((op<0x20u || op>0x25u) && c->port->opcode_cost(op)!=1u) { return EAT_I_RANGE; }
    switch(op) {
    case 0x00: case 0x34: case 0x7F: return (a|b|d|k)?EAT_I_RESERVED:EAT_I_OK;
    case 0x01: if(b|d) { return EAT_I_RESERVED; } break;
    case 0x02: if(d|k) { return EAT_I_RESERVED; } if(b>=8u) { return EAT_I_INDEX; } break;
    case 0x03: case 0x04:
        if(b|d) { return EAT_I_RESERVED; }
        if(k>=field(c,n,1u,t,5u)) { return EAT_I_INDEX; } break;
    case 0x05:
        if(b|d) { return EAT_I_RESERVED; } if(k>=c->image[n].count[4]) { return EAT_I_INDEX; } break;
    case 0x09: case 0x0A:
        if(!EAT_INTERP_DIV) { return EAT_I_DISABLED; }
        /* fall through */
    case 0x06: case 0x07: case 0x08: case 0x0B: case 0x10:
        if(b>=8u || d>=8u) { return EAT_I_INDEX; }
        if((op==0x0Bu && k>4u) || (op==0x10u && k>5u) || (op!=0x0Bu && op!=0x10u && k)) { return EAT_I_RESERVED; } break;
    case 0x12: if(a) { return EAT_I_RESERVED; } /* fall through */
    case 0x11:
        if(b|d) { return EAT_I_RESERVED; }
        if(k>=c->image[n].count[2] || owner(c,n,k)!=t) { return EAT_I_PC; } break;
    case 0x20: case 0x21: case 0x22: case 0x23: case 0x24: case 0x25:
        if(d || (op!=0x24u && op!=0x25u && b) || ((op==0x22u || op==0x23u) && a)) { return EAT_I_RESERVED; }
        if(k>=c->image[n].count[6] || !(field(c,n,1u,t,6u)&(1u<<k))) { return EAT_I_ALLOW; }
        kind=field(c,n,6u,k,1u);
        if(kind!=(op<=0x22u?EAT_I_GPIO:(op<=0x24u?EAT_I_ADC:EAT_I_PWM_KIND))) { return EAT_I_ALLOW; }
        if((op==0x20u && field(c,n,6u,k,3u)!=0u) ||
           (op==0x21u && field(c,n,6u,k,3u)!=1u)) { return EAT_I_ALLOW; }
        if((op==0x23u || op==0x24u) && !EAT_INTERP_ADC) { return EAT_I_DISABLED; }
        if(op==0x25u && !EAT_INTERP_PWM) { return EAT_I_DISABLED; }
        if((op==0x24u || op==0x25u) && b>=8u) { return EAT_I_INDEX; }
        if(op==0x24u && a==b) { return EAT_I_INDEX; }
        break;
    case 0x30: case 0x31: case 0x32:
        if(b|d || (op==0x31u && a)) { return EAT_I_RESERVED; }
        if(k>=EAT_INTERP_TIMERS) { return EAT_I_INDEX; } break;
    case 0x33: case 0x40:
        if(d) { return EAT_I_RESERVED; }
        if(b>=8u || k>=c->image[n].count[5]) { return EAT_I_INDEX; }
        if(field(c,n,5u,k,3u)!=field(c,n,1u,t,0u)) { return EAT_I_ALLOW; } break;
    default: return EAT_I_OPCODE;
    }
    return a<8u?EAT_I_OK:EAT_I_INDEX;
}
static uint32_t definition(eat_interp *c,uint32_t section,uint32_t i)
{
    uint32_t n=c->candidate,j,k,r[12],mask;
    decode(row(c,n,section,i),r,row_bytes[section]/4u);
    if(section==1u) {
        if(!r[0] || r[0]>65535u || !r[3] || r[2]>c->image[n].count[2] || r[3]>c->image[n].count[2]-r[2] ||
           r[4]>c->image[n].count[3] || r[5]>c->image[n].count[3]-r[4] || r[5]>EAT_INTERP_VARS ||
           r[6]>>c->image[n].count[6] || r[10]!=EAT_INTERP_SLICE || r[11]) { return EAT_I_FORMAT; }
        for(j=0;j<i;j++) {
            uint32_t start=field(c,n,1u,j,2u), count=field(c,n,1u,j,3u);
            if(r[0]==field(c,n,1u,j,0u) || (r[2]<start+count && start<r[2]+r[3])) { return EAT_I_PC; }
            mask=field(c,n,1u,j,6u);
            for(k=0;k<c->image[n].count[6];k++) {
                uint32_t h;
                if(!(r[6]&(1u<<k))) { continue; }
                for(h=0;h<c->image[n].count[6];h++) {
                    if((mask&(1u<<h)) && field(c,n,6u,k,2u)==field(c,n,6u,h,2u)) { return EAT_I_ALLOW; }
                }
            }
        }
        for(j=0;j<r[5];j++) { if(field(c,n,3u,r[4]+j,0u)!=r[0]) { return EAT_I_INDEX; } }
    } else if(section==3u) {
        if(!r[1] || r[2]!=1u || r[3]!=1u || r[5]>r[4] || r[4]>r[6] || r[7]>1u) { return EAT_I_FORMAT; }
        for(j=0;j<i;j++) { if(r[0]==field(c,n,3u,j,0u) && r[1]==field(c,n,3u,j,1u)) { return EAT_I_INDEX; } }
    } else if(section==4u) {
        if(!r[0] || r[4]!=1u || r[2]>r[1] || r[1]>r[3]) { return EAT_I_RANGE; }
        for(j=0;j<i;j++) { if(r[0]==field(c,n,4u,j,0u)) { return EAT_I_INDEX; } }
    } else if(section==5u) {
        if(!r[0] || r[1]<1u || r[1]>5u || (r[4] && (r[1]!=3u || !duration(r[4]))) || r[5]) { return EAT_I_FORMAT; }
        for(j=0;j<c->image[n].count[1];j++) { if(r[3]==field(c,n,1u,j,0u)) { break; } }
        if(j==c->image[n].count[1]) { return EAT_I_INDEX; }
        for(j=0;j<i;j++) {
            if(r[0]==field(c,n,5u,j,0u) && (r[1]!=field(c,n,5u,j,1u) ||
               r[2]!=field(c,n,5u,j,2u) || r[3]==field(c,n,5u,j,3u))) { return EAT_I_INDEX; }
        }
    } else if(section==6u) {
        if(r[1]==4u || r[1]==5u) { return EAT_I_DISABLED; }
        if(!r[0] || r[1]<1u || r[1]>6u || r[8]>r[9] || r[10]>r[11] || !r[5] ||
           r[4]>0xFFFFFFFFu-(r[5]-1u) || (r[6]!=8u && r[6]!=16u && r[6]!=32u) ||
           r[4]%(r[6]/8u) || r[5]<r[6]/8u || !r[7] ||
           (r[6]<32u && (r[7]>>r[6]))) { return EAT_I_ALLOW; }
        if(!c->port->allow_check(r) || !c->port->resource_check(r)) { return EAT_I_ALLOW; }
        if((r[1]==2u && !EAT_INTERP_ADC) || (r[1]==3u && !EAT_INTERP_PWM)) { return EAT_I_DISABLED; }
        if(r[1]==EAT_I_ADC && (r[10]>=0x80000000u || r[11]>=0x80000000u)) { return EAT_I_RANGE; }
        for(j=0;j<i;j++) {
            if(r[0]==field(c,n,6u,j,0u) || r[2]==field(c,n,6u,j,2u)) { return EAT_I_INDEX; }
        }
        if((r[1]==EAT_I_GPIO && r[3]==1u) || r[1]==EAT_I_PWM_KIND) {
            for(j=0;j<c->image[n].count[7];j++) {
                uint32_t at=field(c,n,7u,j,0u);
                if(at>=r[4] && at-r[4]<r[5]) { break; }
            }
            if(j==c->image[n].count[7]) { return EAT_I_ALLOW; }
        }
    } else if(section==7u) {
        if((r[1]!=8u && r[1]!=16u && r[1]!=32u) || r[0]%(r[1]/8u) ||
           !r[2] || (r[1]<32u && (r[2]>>r[1])) || (r[3]&~r[2])) { return EAT_I_ALLOW; }
        if(!c->port->safe_check(r)) { return EAT_I_ALLOW; }
        for(j=0;j<i;j++) {
            if(r[0]==field(c,n,7u,j,0u) && (r[1]!=field(c,n,7u,j,1u) ||
               ((r[3]^field(c,n,7u,j,3u))&r[2]&field(c,n,7u,j,2u)))) { return EAT_I_ALLOW; }
        }
    }
    return EAT_I_OK;
}
static void verify(eat_interp *c)
{
    uint32_t error=0u,i,n;
    if(c->verify_phase==0u) {
        n=c->total-c->verify_index; if(n>64u) { n=64u; }
        c->crc=crc_step(c->crc,bank(c,c->candidate)+c->verify_index,n); c->verify_index+=n;
        if(c->verify_index<c->total) { return; }
        if((c->crc^0xFFFFFFFFu)!=c->expected_crc) { error=EAT_I_CRC; }
        else { error=header(c); }
        c->verify_phase=1u; c->verify_index=0u;
    } else {
        for(i=0;i<8u && c->verify_phase<=7u;i++) {
            if(c->verify_index>=c->image[c->candidate].count[c->verify_phase]) {
                c->verify_phase++; c->verify_index=0u; i--; continue;
            }
            error=c->verify_phase==2u?instruction(c,c->candidate,c->verify_index):definition(c,c->verify_phase,c->verify_index);
            c->verify_index++; if(error) { break; }
        }
    }
    if(error) { c->candidate_state=EAT_I_REJECTED; c->mb[38]=error; }
    else if(c->verify_phase>7u) { c->candidate_state=EAT_I_READY; }
}
static int unchanged(eat_interp *c,uint32_t old,uint32_t fresh)
{
    uint32_t n=c->candidate,a=c->active,j,k,old_count=0u,new_count=0u;
    uint32_t os=field(c,a,1u,old,2u),ns=field(c,n,1u,fresh,2u);
    if(field(c,a,1u,old,3u)!=field(c,n,1u,fresh,3u) || field(c,a,1u,old,5u)!=field(c,n,1u,fresh,5u) ||
       !same(row(c,a,3u,field(c,a,1u,old,4u)),row(c,n,3u,field(c,n,1u,fresh,4u)),32u*field(c,n,1u,fresh,5u))) { return 0; }
    for(j=0;j<16u;j++) {
        if(field(c,a,1u,old,6u)&(1u<<j)) { old_count++; }
        if(field(c,n,1u,fresh,6u)&(1u<<j)) { new_count++; }
    }
    if(old_count!=new_count) { return 0; }
    for(j=0;j<c->image[a].count[6];j++) {
        if(!(field(c,a,1u,old,6u)&(1u<<j))) { continue; }
        for(k=0;k<c->image[n].count[6];k++) {
            if((field(c,n,1u,fresh,6u)&(1u<<k)) && same(row(c,a,6u,j),row(c,n,6u,k),48u)) { break; }
        }
        if(k==c->image[n].count[6]) { return 0; }
    }
    for(j=0;j<field(c,n,1u,fresh,3u);j++) {
        volatile uint8_t *op=row(c,a,2u,os+j),*np=row(c,n,2u,ns+j);
        uint32_t ok=word(op+4),nk=word(np+4),kind=0u;
        if(!same(op,np,4u)) { return 0; }
        if(op[0]==0x11u || op[0]==0x12u) { if(ok-os!=nk-ns) { return 0; } }
        else {
            if(op[0]>=0x20u && op[0]<=0x25u) { kind=6u; }
            if(op[0]==0x33u || op[0]==0x40u) { kind=5u; }
            if(op[0]==5u) { if(field(c,a,4u,ok,0u)!=field(c,n,4u,nk,0u)) { return 0; } }
            else if(kind) { if(!same(row(c,a,kind,ok),row(c,n,kind,nk),row_bytes[kind])) { return 0; } }
            else if(ok!=nk) { return 0; }
        }
    }
    return 1;
}
static uint32_t commit(eat_interp *c)
{
    uint32_t n=c->candidate,i,j,k,old,old_allow=c->allow_count,old_safe=c->safe_count;
    uint32_t mapping[EAT_INTERP_TASKS], deadlines[EAT_INTERP_SUBSCRIPTIONS], used=0u;
    uint32_t adc_last[EAT_INTERP_ALLOW_ROWS],adc_used=0u;
    /* Find old task indices first. Runtime storage is permuted in place below. */
    for(i=0;i<c->image[n].count[1];i++) {
        mapping[i]=EAT_INTERP_TASKS;
        if(c->has_active) { for(j=0;j<c->image[c->active].count[1];j++) {
            if(field(c,n,1u,i,0u)==field(c,c->active,1u,j,0u)) { mapping[i]=j; break; }
        } }
    }
    /* Safe union has no third copy. Conservative capacity counts duplicate rows too. */
    if(old_safe+c->image[n].count[7]>EAT_INTERP_SAFE_ROWS) { return EAT_I_MIGRATION; }
    for(i=0;i<c->image[n].count[1];i++) {
        if(mapping[i]<i) { return EAT_I_MIGRATION; }
    }
    for(i=0;i<c->image[n].count[7];i++) {
        uint32_t r[4]; decode(row(c,n,7u,i),r,4u);
        for(j=0;j<old_safe;j++) {
            if(r[0]==c->safe[j][0] && (r[1]!=c->safe[j][1] || ((r[3]^c->safe[j][3])&r[2]&c->safe[j][2]))) { return EAT_I_MIGRATION; }
        }
    }
    for(i=0;i<EAT_INTERP_TASKS;i++) { if(c->task[i].adc_mask) { return EAT_I_MIGRATION; } }
    for(i=0;i<c->image[n].count[5];i++) {
        deadlines[i]=c->now+field(c,n,5u,i,4u);
        for(k=0;k<c->image[n].count[1];k++) {
            if(field(c,n,1u,k,0u)!=field(c,n,5u,i,3u) || mapping[k]>=EAT_INTERP_TASKS || !unchanged(c,mapping[k],k)) { continue; }
            for(j=0;j<c->image[c->active].count[5];j++) {
                if(same(row(c,n,5u,i),row(c,c->active,5u,j),24u)) { deadlines[i]=c->event_deadline[j]; break; }
            }
        }
    }
    for(i=0;i<c->image[n].count[6];i++) {
        uint32_t r[12]; decode(row(c,n,6u,i),r,12u);
        if(!c->port->resource_check(r)) { return EAT_I_ALLOW; }
        adc_last[i]=0u;
        for(j=0;j<old_allow;j++) {
            if(r[1]==EAT_I_ADC && c->allow[j][1]==EAT_I_ADC && r[2]==c->allow[j][2] && (c->adc_used&(1u<<j))) {
                adc_last[i]=c->adc_last[j]; adc_used|=1u<<i;
            }
        }
    }
    c->port->critical_enter();
    /* Install the validated union before any port operation can change hardware.
     * A trap during prepare must also have the new resources' safe rows. */
    for(i=0;i<c->image[n].count[7];i++) { decode(row(c,n,7u,i),c->safe[old_safe+i],4u); }
    c->port->publish(); c->safe_count=old_safe+c->image[n].count[7];
    /* Unchanged resources stay live; removed/changed resources are made safe first. */
    for(i=0;i<old_allow;i++) {
        int keep=0;
        for(j=0;j<c->image[n].count[1];j++) {
            if(mapping[j]<EAT_INTERP_TASKS && unchanged(c,mapping[j],j) &&
               (field(c,c->active,1u,mapping[j],6u)&(1u<<i))) { keep=1; }
        }
        if(!keep) {
            if(c->allow[i][1]==EAT_I_ADC) { c->port->analog_cancel(c->allow[i][2]); }
            if(c->allow[i][1]==EAT_I_PWM_KIND) { c->port->pwm_stop(c->allow[i][2]); }
            for(k=0;k<old_safe;k++) {
                if(c->safe[k][0]>=c->allow[i][4] && c->safe[k][0]-c->allow[i][4]<c->allow[i][5]) { c->port->safe_write(c->safe[k]); }
            }
            c->port->resource_release(c->allow[i]);
        }
    }
    for(i=0;i<c->image[n].count[6];i++) {
        uint32_t r[12]; int keep=0; decode(row(c,n,6u,i),r,12u);
        for(j=0;j<c->image[n].count[1];j++) {
            if(mapping[j]<EAT_INTERP_TASKS && unchanged(c,mapping[j],j) &&
               (field(c,n,1u,j,6u)&(1u<<i))) { keep=1; }
        }
        if(!keep) {
            for(j=0;j<c->image[n].count[7];j++) {
                uint32_t s[4]; decode(row(c,n,7u,j),s,4u);
                if(s[0]>=r[4] && s[0]-r[4]<r[5]) { c->port->safe_write(s); }
            }
        }
        if(!keep && c->port->resource_prepare(r)!=0) {
            c->port->safe_stop(); safe_rows(c);
            for(j=0;j<c->image[n].count[7];j++) { uint32_t s[4]; decode(row(c,n,7u,j),s,4u); c->port->safe_write(s); }
            c->port->critical_leave(); eat_interp_stop(c,EAT_I_PORT); return EAT_I_PORT;
        }
    }
    /* One task-sized temporary per permutation, no third program bank. */
    for(i=0;i<c->image[n].count[1];i++) {
        eat_interp_task fresh;
        uint32_t *clear=(uint32_t *)(void *)&fresh;
        for(j=0;j<sizeof fresh/sizeof(uint32_t);j++) { clear[j]=0u; }
        old=mapping[i];
        if(old<EAT_INTERP_TASKS && unchanged(c,old,i)) {
            fresh=c->task[old];
            fresh.pc=fresh.pc-field(c,c->active,1u,old,2u)+field(c,n,1u,i,2u);
            if(fresh.state==3u) {
                for(j=0;j<c->image[n].count[5];j++) {
                    if(same(row(c,c->active,5u,fresh.wait),row(c,n,5u,j),24u)) { fresh.wait=j; break; }
                }
                if(j==c->image[n].count[5]) { fresh.state=1u; fresh.pc=field(c,n,1u,i,2u); }
            }
        }
        else {
            fresh.pc=field(c,n,1u,i,2u); fresh.state=1u;
            for(j=0;j<field(c,n,1u,i,5u);j++) {
                uint32_t v=field(c,n,1u,i,4u)+j;
                fresh.var[j]=field(c,n,3u,v,4u);
                if(old<EAT_INTERP_TASKS && field(c,n,3u,v,7u)) {
                    for(k=0;k<field(c,c->active,1u,old,5u);k++) {
                        uint32_t ov=field(c,c->active,1u,old,4u)+k, value=c->task[old].var[k];
                        if(field(c,n,3u,v,1u)==field(c,c->active,3u,ov,1u) &&
                           field(c,n,3u,v,2u)==field(c,c->active,3u,ov,2u) &&
                           field(c,n,3u,v,3u)==field(c,c->active,3u,ov,3u) &&
                           value>=field(c,n,3u,v,5u) && value<=field(c,n,3u,v,6u)) { fresh.var[j]=value; }
                    }
                }
            }
        }
        c->task[i]=fresh; used++;
    }
    for(i=used;i<EAT_INTERP_TASKS;i++) { c->task[i].state=0u; }
    c->allow_count=c->image[n].count[6];
    for(i=0;i<c->allow_count;i++) { decode(row(c,n,6u,i),c->allow[i],12u); }
    for(i=0;i<c->allow_count;i++) { c->adc_last[i]=adc_last[i]; }
    c->adc_used=adc_used;
    for(i=0;i<c->image[n].count[7];i++) {
        for(j=0;j<4u;j++) { c->safe[i][j]=c->safe[old_safe+i][j]; }
    }
    c->port->publish(); c->safe_count=c->image[n].count[7];
    for(i=0;i<c->image[n].count[4];i++) { c->params[i]=field(c,n,4u,i,1u); }
    for(i=0;i<c->image[n].count[5];i++) {
        c->event_deadline[i]=deadlines[i];
    }
    /* Queued events are drained before the first new instruction. Only preserved
     * WAITING tasks can receive them; changed/new tasks have no subscription yet. */
    c->active=n; c->has_active=1u; c->generation++;
    c->run_state=EAT_I_RUNNING; c->fault=0u; c->candidate_state=EAT_I_EMPTY;
    c->heartbeat_ms=c->now; c->timeout=c->mb[15]; c->mb[14]=1u;
    c->mb[43]=c->expected_crc;
    c->port->publish(); c->port->critical_leave(); emit(c,0u,7u,0u,c->generation,0u); return EAT_I_OK;
}
static uint32_t command(eat_interp *c,uint32_t op,const uint32_t *a)
{
    uint32_t i,n;
    if(op==0x10u) {
        if(a[0]!=c->generation || c->generation==0xFFFFFFFFu) { return EAT_I_STALE_GENERATION; }
        if(c->candidate_state==EAT_I_RECEIVING || c->candidate_state==EAT_I_VERIFYING || c->candidate_state==EAT_I_READY) { return EAT_I_STATE; }
        if(a[1]<24u || a[1]>EAT_INTERP_IMAGE_BYTES) { return EAT_I_CAPACITY; }
        if(a[3]!=1u || !duration(c->mb[15]) || c->mb[14]!=1u) { return EAT_I_RANGE; }
        if(c->upload_id==0xFFFFFFFFu) { return EAT_I_STATE; }
        c->candidate=c->has_active?1u-c->active:0u; c->upload_id++;
        c->total=a[1]; c->expected_crc=a[2]; c->received=0u; c->candidate_state=EAT_I_RECEIVING;
        c->progress_ms=c->now; c->mb[39]=c->upload_id; return EAT_I_OK;
    }
    if(op>=0x11u && op<=0x14u) {
        if(a[0]!=c->upload_id) { return EAT_I_STATE; }
        if(op==0x14u) { c->candidate_state=EAT_I_EMPTY; return EAT_I_OK; }
        if(op==0x11u) {
            if(c->candidate_state!=EAT_I_RECEIVING || a[1]!=c->received || !a[2] || a[2]>128u ||
               a[2]>c->total-c->received || (a[2]%4u && a[2]!=c->total-c->received)) { return EAT_I_STATE; }
            if(eat_interp_crc32(bank(c,c->candidate)+a[1],a[2])!=a[3]) { c->candidate_state=EAT_I_REJECTED; return EAT_I_CRC; }
            c->received+=a[2]; c->progress_ms=c->now; return EAT_I_OK;
        }
        if(op==0x12u) {
            if(c->candidate_state!=EAT_I_RECEIVING || c->received!=c->total) { return EAT_I_STATE; }
            c->candidate_state=EAT_I_VERIFYING; c->crc=0xFFFFFFFFu; c->verify_phase=0u; c->verify_index=0u; return EAT_I_OK;
        }
        if(a[1]!=c->generation || c->generation==0xFFFFFFFFu) { return EAT_I_STALE_GENERATION; }
        if(c->candidate_state!=EAT_I_READY || !duration(c->mb[15]) || !c->mb[14]) { return EAT_I_STATE; }
        return commit(c);
    }
    if(a[0]!=c->generation || c->generation==0xFFFFFFFFu) { return EAT_I_STALE_GENERATION; }
    if(op==0x15u) { eat_interp_stop(c,0u); return EAT_I_OK; }
    if(!c->has_active || c->run_state!=EAT_I_RUNNING) { return EAT_I_STATE; }
    if(op==0x16u) {
        for(i=0;i<c->image[c->active].count[4];i++) {
            if(field(c,c->active,4u,i,0u)==a[1]) {
                if(a[2]<field(c,c->active,4u,i,2u) || a[2]>field(c,c->active,4u,i,3u)) { return EAT_I_RANGE; }
                c->params[i]=a[2]; c->generation++; return EAT_I_OK;
            }
        }
        return EAT_I_INDEX;
    }
    if(op==0x17u) {
        n=c->image[c->active].count[5];
        for(i=0;i<n;i++) {
            if(field(c,c->active,5u,i,0u)==a[1] && field(c,c->active,5u,i,1u)==5u) {
                return eat_interp_event_push(c,a[1],5u,a[2],c->now)?EAT_I_OK:EAT_I_EVENT_OVERFLOW;
            }
        }
        return EAT_I_ALLOW;
    }
    return EAT_I_OPCODE;
}
static uint32_t execute(eat_interp *c,uint32_t ti)
{
    eat_interp_task *t=&c->task[ti];
    uint32_t n=c->active,pc=t->pc,error=instruction(c,n,pc),op,a,b,d,k,x,y,v=0u;
    volatile uint8_t *p;
    int result=0;
    if(error) { return error; }
    p=row(c,n,2u,pc); op=p[0]; a=p[1]; b=p[2]; d=p[3]; k=word(p+4); x=t->reg[b]; y=t->reg[d];
    t->pc++;
    if(op>=0x20u && op<=0x25u) {
        uint32_t *h=c->allow[k];
        if(!(field(c,n,1u,ti,6u)&(1u<<k)) || !c->port->allow_check(h) || !c->port->resource_check(h)) { return EAT_I_ALLOW; }
        if(op==0x20u) {
            if(h[3]!=0u) { return EAT_I_ALLOW; }
            result=c->port->gpio_read(h[2],&v); if(v>1u) { return EAT_I_RANGE; } t->reg[a]=v;
        }
        if(op==0x21u) {
            v=t->reg[a]; if(v>1u || v<h[8] || v>h[9] || h[3]!=1u) { return EAT_I_ALLOW; }
            result=c->port->gpio_write(h[2],v);
        }
        if(op==0x22u) {
            uint32_t j;
            for(j=0;j<c->safe_count;j++) {
                if(c->safe[j][0]>=h[4] && c->safe[j][0]-h[4]<h[5]) { c->port->safe_write(c->safe[j]); }
            }
            result=c->port->gpio_configure(h[2],h[3]);
        }
        if(op==0x23u) {
            if(t->adc_mask) { return EAT_I_STATE; }
            if((c->adc_used&(1u<<k)) && (uint32_t)(c->now-c->adc_last[k])<h[10]) { return EAT_I_ALLOW; }
            result=c->port->analog_start(h[2]);
            if(result==0) {
                t->adc_mask|=1u<<k; t->adc_since=c->now;
                c->adc_last[k]=c->now; c->adc_used|=1u<<k;
            }
        }
        if(op==0x24u) {
            if(!(t->adc_mask&(1u<<k))) { return EAT_I_STATE; }
            result=c->port->analog_read(h[2],&v);
            t->reg[b]=result==0?1u:0u;
            if(result==0) {
                if(v<h[8] || v>h[9]) { return EAT_I_RANGE; }
                t->reg[a]=v; t->adc_mask&=~(1u<<k);
            }
            if(result==1) { result=0; }
        }
        if(op==0x25u) {
            v=t->reg[a]; if(v<h[8] || v>h[9] || x<h[10] || x>h[11]) { return EAT_I_ALLOW; }
            result=c->port->pwm_set(h[2],v,x);
        }
        return result?EAT_I_PORT:EAT_I_OK;
    }
    switch(op) {
    case 0x00: break;
    case 0x01: t->reg[a]=k; break;
    case 0x02: t->reg[a]=x; break;
    case 0x03: t->reg[a]=t->var[k]; break;
    case 0x04:
        v=field(c,n,1u,ti,4u)+k;
        if(t->reg[a]<field(c,n,3u,v,5u) || t->reg[a]>field(c,n,3u,v,6u)) { return EAT_I_RANGE; }
        t->var[k]=t->reg[a]; break;
    case 0x05: t->reg[a]=c->params[k]; break;
    case 0x06: t->reg[a]=x+y; break;
    case 0x07: t->reg[a]=x-y; break;
    case 0x08: t->reg[a]=x*y; break;
    case 0x09: case 0x0A:
        if(!y) { return EAT_I_RANGE; }
#if EAT_INTERP_DIV
        t->reg[a]=op==9u?x/y:x%y;
#endif
        break;
    case 0x0B:
        if(k>=3u && y>=32u) { return EAT_I_RANGE; }
        t->reg[a]=k==0u?(x&y):k==1u?(x|y):k==2u?(x^y):k==3u?(x<<y):(x>>y); break;
    case 0x10: t->reg[a]=k==0u?(x==y):k==1u?(x!=y):k==2u?(x<y):k==3u?(x<=y):k==4u?(x>y):(x>=y); break;
    case 0x11: if(t->reg[a]) { t->pc=k; } break;
    case 0x12: t->pc=k; break;
    case 0x30: case 0x32:
        if(!duration(t->reg[a])) { return EAT_I_RANGE; }
        t->timer[k]=c->now+t->reg[a]; t->timer_mask|=1u<<k;
        if(op==0x32u) { t->state=2u; t->wait=k; } break;
    case 0x31:
        if(!(t->timer_mask&(1u<<k))) { return EAT_I_STATE; }
        if(!due(c->now,t->timer[k])) { t->state=2u; t->wait=k; } break;
    case 0x33: t->state=3u; t->wait=k; t->event_a=a; t->event_b=b; break;
    case 0x34: t->state=4u; break;
    case 0x40:
        v=field(c,n,5u,k,1u);
        emit(c,field(c,n,1u,ti,0u),v,field(c,n,5u,k,2u),t->reg[a],x);
        if(v==4u && !eat_interp_event_push(c,field(c,n,5u,k,0u),v,t->reg[a],c->now)) { return EAT_I_EVENT_OVERFLOW; }
        break;
    case 0x7F:
        t->state=0u;
        for(k=0;k<c->allow_count;k++) {
            if(field(c,n,1u,ti,6u)&(1u<<k)) {
                uint32_t j,*h=c->allow[k];
                if(h[1]==EAT_I_ADC) { c->port->analog_cancel(h[2]); }
                if(h[1]==EAT_I_PWM_KIND) { c->port->pwm_stop(h[2]); }
                for(j=0;j<c->safe_count;j++) {
                    if(c->safe[j][0]>=h[4] && c->safe[j][0]-h[4]<h[5]) { c->port->safe_write(c->safe[j]); }
                }
            }
        }
        t->adc_mask=0u; break;
    default: return EAT_I_OPCODE;
    }
    return EAT_I_OK;
}
static void tick(eat_interp *c)
{
    uint32_t i,j,n=c->image[c->active].count[1],budget=EAT_INTERP_BUDGET;
    for(i=0;i<c->image[c->active].count[5];i++) {
        uint32_t period=field(c,c->active,5u,i,4u);
        if(period && due(c->now,c->event_deadline[i])) {
            uint32_t scheduled=c->event_deadline[i];
            c->event_deadline[i]+=((uint32_t)(c->now-scheduled)/period+1u)*period;
            if(!eat_interp_event_push(c,field(c,c->active,5u,i,0u),3u,0u,scheduled)) {
                eat_interp_stop(c,EAT_I_EVENT_OVERFLOW); return;
            }
        }
    }
    for(i=0;i<n;i++) {
        eat_interp_task *t=&c->task[i];
        if(t->adc_mask) {
            uint32_t h,deadline=100u;
            for(h=0;h<c->allow_count;h++) {
                if((t->adc_mask&(1u<<h)) && c->allow[h][11]) { deadline=c->allow[h][11]; }
            }
            if((uint32_t)(c->now-t->adc_since)>=deadline) { eat_interp_stop(c,EAT_I_PORT); return; }
        }
        if(t->state==4u) { t->state=1u; }
        if(t->state==2u && due(c->now,t->timer[t->wait])) {
            t->state=1u; emit(c,field(c,c->active,1u,i,0u),3u,t->wait,0u,0u);
        }
    }
    for(i=0;i<EAT_INTERP_EVENTS;i++) {
        eat_interp_event e;
        c->port->critical_enter(); c->port->acquire();
        if(c->event_read==c->event_write) { c->port->critical_leave(); break; }
        e=c->events[c->event_read%EAT_INTERP_EVENTS]; c->event_read++; c->port->critical_leave();
        for(j=0;j<n;j++) {
            eat_interp_task *t=&c->task[j];
            if(t->state==3u && field(c,c->active,5u,t->wait,0u)==e.id && field(c,c->active,5u,t->wait,1u)==e.kind) {
                t->reg[t->event_a]=e.value; t->reg[t->event_b]=e.time; t->state=1u;
            }
        }
    }
    for(i=0;i<n && budget;i++) {
        uint32_t index=(c->round_robin+i)%n,slice=0u;
        eat_interp_task *t=&c->task[index];
        while(t->state==1u && budget && slice<EAT_INTERP_SLICE) {
            uint32_t error,cost;
            if(t->pc>=c->image[c->active].count[2]) { eat_interp_stop(c,EAT_I_PC); return; }
            cost=c->port->opcode_cost(row(c,c->active,2u,t->pc)[0]);
            if(!cost || cost>EAT_INTERP_SLICE-slice) { eat_interp_stop(c,EAT_I_BUDGET_EXCEEDED); return; }
            if(cost>budget) { break; }
            budget-=cost; slice+=cost; error=execute(c,index);
            if(error) { c->mb[49]=field(c,c->active,1u,index,0u); eat_interp_stop(c,error); return; }
        }
        if(t->state==1u && slice==EAT_INTERP_SLICE) { eat_interp_stop(c,EAT_I_BUDGET_EXCEEDED); return; }
    }
    if(n) { c->round_robin=(c->round_robin+1u)%n; }
}
int eat_interp_init(eat_interp *c,const eat_interp_port *p,volatile uint32_t *mb,
                    uint32_t words,uint32_t boot,uint32_t hash,uint32_t timeout)
{
    uint32_t i; uint8_t *clear=(uint8_t *)(void *)c;
    for(i=0;i<sizeof *c;i++) { clear[i]=0u; }
    if(words<EAT_INTERP_WORDS || !duration(timeout) || !boot || !p || !p->millis ||
       !p->allow_check || !p->safe_check || !p->resource_check || !p->resource_prepare || !p->resource_release ||
       !p->gpio_read || !p->gpio_write || !p->gpio_configure ||
       (EAT_INTERP_ADC && (!p->analog_start || !p->analog_read || !p->analog_cancel)) ||
       (EAT_INTERP_PWM && (!p->pwm_set || !p->pwm_stop)) || !p->safe_stop || !p->safe_write ||
       !p->critical_enter || !p->critical_leave || !p->publish || !p->acquire || !p->opcode_cost) { return 0; }
    c->port=p; c->mb=mb; c->capability_hash=hash; c->timeout=timeout;
    for(i=0;i<words;i++) { mb[i]=0u; }
    if(!eat_ring_init(&c->ring,(volatile uint8_t *)(void *)mb+EAT_INTERP_RING,EAT_INTERP_RING_RECORDS)) { return 0; }
    mb[1]=2u; mb[14]=1u; mb[15]=timeout; mb[18]=46u; mb[19]=256u; mb[20]=256u;
    mb[21]=EAT_INTERP_BANK0; mb[22]=EAT_INTERP_BANK1; mb[23]=EAT_INTERP_IMAGE_BYTES;
    mb[24]=EAT_INTERP_RING; mb[25]=32u+EAT_INTERP_RING_RECORDS*32u; mb[44]=boot;
    /* Capability summary (native target words; images and ring remain little-endian). */
    mb[64]=1u; mb[65]=1u; mb[66]=hash; mb[67]=(EAT_INTERP_ADC?1u:0u)|(EAT_INTERP_PWM?2u:0u)|(EAT_INTERP_DIV?4u:0u);
    mb[68]=EAT_INTERP_TASKS; mb[69]=EAT_INTERP_VARS; mb[70]=EAT_INTERP_TIMERS;
    mb[71]=EAT_INTERP_BUDGET; mb[72]=EAT_INTERP_SLICE; mb[73]=1u;
    mb[74]=EAT_INTERP_ALLOW_ROWS; mb[75]=EAT_INTERP_SAFE_ROWS; mb[76]=EAT_INTERP_EVENTS;
    mb[77]=EAT_INTERP_IMAGE_BYTES; mb[78]=(uint32_t)sizeof *c;
    for(i=0;i<6u;i++) { mb[90u+i]=p->opcode_cost(0x20u+i); }
    c->now=p->millis(); c->last_tick=c->now; c->heartbeat_ms=c->now; c->initialized=1u;
    p->safe_stop(); p->publish(); mb[0]=EAT_INTERP_MAGIC; return 1;
}
void eat_interp_poll(eat_interp *c)
{
    uint32_t seq,error,a[8],i,previous[17],state_seq,changed=0u;
    if(!c->initialized) { return; }
    state_seq=c->mb[45];
    for(i=0;i<17u;i++) { previous[i]=c->mb[36u+i]; }
    c->now=c->port->millis(); c->mb[2]++; c->mb[45]++; c->port->publish(); c->port->acquire();
    if(c->mb[3]!=c->heartbeat) { c->heartbeat=c->mb[3]; c->heartbeat_ms=c->now; }
    if(c->run_state==EAT_I_RUNNING) {
        if(!c->mb[14] || (uint32_t)(c->now-c->heartbeat_ms)>=c->timeout) { eat_interp_stop(c,EAT_I_DEADMAN); }
        else if(c->fault) { eat_interp_stop(c,c->fault); }
    }
    if(c->candidate_state==EAT_I_RECEIVING && (uint32_t)(c->now-c->progress_ms)>=5000u) { c->candidate_state=EAT_I_EMPTY; }
    if(c->candidate_state==EAT_I_VERIFYING) { verify(c); }
    seq=c->mb[26];
    /* PARAM_SET and COMMIT are deferred to a tick boundary, before any task runs. */
    if(seq!=c->mb[36] && ((c->mb[27]!=0x16u && c->mb[27]!=0x13u) || c->now!=c->last_tick)) {
        for(i=0;i<8u;i++) { a[i]=c->mb[28u+i]; }
        c->mb[39]=0u;
        error=seq>c->mb[36] && seq!=0xFFFFFFFFu?command(c,c->mb[27],a):EAT_I_STATE;
        c->mb[37]=error?1u:0u; c->mb[38]=error;
        c->port->publish(); c->mb[36]=seq;
    }
    if(c->mb[4]!=c->mb[5]) { c->mb[13]=EAT_I_BUSY_PROGRAM; c->mb[6]=3u; c->mb[5]=c->mb[4]; }
    if(c->now!=c->last_tick) { c->last_tick=c->now; if(c->run_state==EAT_I_RUNNING) { tick(c); } }
    if(c->mb[50]!=c->mb[51]) {
        c->mb[52]=eat_ring_ack(&c->ring,c->mb[50])?0u:EAT_I_RANGE;
        c->port->publish(); c->mb[51]=c->mb[50];
    }
    c->mb[40]=c->generation; c->mb[41]=c->active; c->mb[42]=c->run_state;
    c->mb[46]=c->upload_id; c->mb[47]=c->received; c->mb[48]=c->candidate_state;
    for(i=0;i<EAT_INTERP_PARAMS;i++) { c->mb[80u+i]=c->params[i]; }
    c->mb[13]=c->fault;
    for(i=0;i<17u;i++) {
        if(i!=9u && i!=14u && previous[i]!=c->mb[36u+i]) { changed=1u; }
    }
    c->port->publish(); c->mb[45]=state_seq+(changed?2u:0u);
}
