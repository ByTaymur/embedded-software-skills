# MIPS32 / XC32 mimari örneği

Chip register adresi içermez; donanımda doğrulanmadı. CP0 Count çekirdek saatinin
yarısında ilerler varsayımıyla `eat_port_pic32_init(core_hz)` çağırın. Bu varsayımı
hedefinizde doğrulayın; sıfır/tek Hz değerleri reddedilir. Ardından
`eat_embed_init(eat_port_pic32_millis, uart_send)` ve aynı ana döngüde UART RX →
`eat_link_rx()` → `eat_stub_poll()` kullanın.
`/* TODO(port): clock, pin mux, UART ve RX kuyruğunu uygulayın. */`

Millis yalnız tek foreground bağlamından çağrılır; en geç bir 32 bit Count turunda
bir çağırmak gerekir (sınır: `2^32 / (core_hz / 2)` saniye). Kesirli tick artığı
korunur. Saat değişince yeniden başlatın; sayaç debug/uyku durumunda durabilir.
CP0 Compare programlanmaz, mevcut timer kesmesi sahipliği değiştirilmez.

XC32 yolunda `<xc.h>` ve `_general_exception_handler` kullanılır; startup exception
ABI'sini, handler sahipliğini ve geçerli stack'i doğrulayın. Handler Cause değerini
`eat_stub_fault(cause)` yoluna verir ve dönmez. Zig derlemesi yalnız ortak CP0
assembly/C yolunu denetler; XC32 başlıkları ve exception bağlantısı burada derlenmez.

Mailbox ELF sembolüdür, linker değişikliği istemez. Profilin `live` alanı:

```json
{"entry_or": 0, "mailbox": {"symbol": "eat_mailbox"}}
```

Scratch için yürütülebilir RAM ve uygun KSEG alias gerekir. Cache'li veri adresinden
yazılan kod komut tarafında otomatik görünmeyebilir; linker/`EAT_SCRATCH_ATTR`, adres
alias eşlemesi, cache temizleme ve instruction hazard/barrier işlemleri integratöre
aittir. Gerektiğinde genel embed yerine özel `eat_hal`/`eat_link_port` kullanın.
