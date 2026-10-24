# RISC-V 32 mimari örneği

Kart ve UART adresi içermez; donanımda doğrulanmadı. `eat_port_riscv_init(timer_hz)`
varsayılan olarak M-mode `mcycle` frekansını alır. `EAT_RISCV_USE_TIME` tanımlarsanız
`time`/`timeh` sayaçlarının gerçek frekansını verin. Sıfır frekans reddedilir.
Önce init, sonra `eat_embed_init(eat_port_riscv_millis, uart_send)` çağırın;
aynı ana döngüde UART RX kuyruğunu `eat_link_rx()` ile boşaltıp `eat_stub_poll()` çağırın.
`/* TODO(port): UART, clock, pin mux ve RX kuyruğunu uygulayın. */`

64 bit sayaç RV32 üzerinde high/low/high okuyarak tutarlı alınır. CSR erişim izni,
sayaçların durmaması ve sabit frekans integratörün sorumluluğudur. Saat değişiminde
yeniden başlatın; derleme testi çalışma zamanı CSR erişimini kanıtlamaz.

`mtvec` girişine düz C işlevini doğrudan bağlamayın. Startup trap wrapper'ı stack ve
registerları ABI'ye göre korur; `mcause` kesme bitini kontrol ederek kesmeleri ayrı
yönetir, yalnız senkron exception için `eat_port_riscv_exception(mcause)` çağırır.
Bu kanca `eat_stub_fault(mcause)` sonrasında dönmez. UART/clock/pin mux ve trap
kurulumu integratöre ait `TODO(port)` işleridir.

Profilin `live` alanı:

```json
{"entry_or": 0, "mailbox": {"symbol": "eat_mailbox"}}
```

Mailbox için linker değişikliği gerekmez. Bazı hedeflerde `eat_scratch` yalnız
yürütülebilir RAM'de bulunabilir: `EAT_SCRATCH_ATTR` ve linker bölümünü tüm
`eat_embed.c` derlemesine uygulayın; PMP/MPU izinlerini ve `fence.i`/cache bakımını
RAM yazımından sonra, çağrıdan önce sağlayın. Genel embed katmanı bu bakımı yapmaz;
gerekiyorsa kendi `eat_hal`/`eat_link_port` kancalarınızı kullanın.
