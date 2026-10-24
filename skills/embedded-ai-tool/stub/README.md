# Stub: hedefte çalışan küçük yönetici

Bu klasördeki C kodu MCU'dan ve mimariden bağımsızdır (C99, yalnız `stdint.h`). Herhangi bir
32 bit hedefte (ARM Cortex-M, RISC-V, MIPS/PIC32, Xtensa…) mevcut bir firmware'e eklenir veya tek
başına küçük bir firmware olarak derlenir. **Belirli bir MCU için hazır firmware değildir**: saat,
başlangıç kodu ve fault/trap bağlantısı hedefin portudur. Bir hedefte ölçülene kadar o hedefte
çalıştığı iddia edilmez.

| Dosya | İşi |
|---|---|
| `eat_stub_core.c/.h` | Mailbox protokolü, dead-man zamanlayıcısı, RAM çağrı döngüsü |
| `eat_link.c/.h` | Seri bağlantı (UART, USB CDC…): debug probu olmadan bellek erişimi, her istekte kimlik koruması |
| `eat_embed.c/.h` | Mevcut firmware'e tek çağrıyla ekleme: global mailbox, genel bellek erişimi ve çağrı |

Protokoller: [../references/stub-protocol.md](../references/stub-protocol.md). Ana makine testleri
(`tests/test_stub.py`, `tests/test_link.py`) bu kaynakları derleyip Python istemcisiyle birlikte
çalıştırır ve ARM Cortex-M0, RISC-V 32, MIPS32 ve 64 bit host için uyarısız derlendiğini denetler
(gcc/cc veya `pip install ziglang`).

## Mevcut bir firmware'e ekleme (önerilen)

```c
#include "eat_embed.h"

int main(void)
{
    board_init();                                   /* uygulamanın kendi başlangıcı */
    eat_embed_init(app_millis, uart_send);          /* uart_send: seri bağlantı yoksa NULL */
    for (;;) {
        while (uart_has_byte()) {
            eat_link_rx(uart_read_byte());          /* seri bağlantı kullanılıyorsa */
        }
        eat_stub_poll();
        app_step();                                 /* uygulamanın döngüsü; uzun süre bloklamamalı */
    }
}

/* Mimarinin fault/trap/exception kancası (Cortex-M: HardFault_Handler, RISC-V: trap handler, ...) */
void fault_hook(void) { eat_stub_fault(0xF0u); for (;;) {} }
```

- Mailbox `eat_mailbox` adlı global dizidir. Profilde `"mailbox": {"symbol": "eat_mailbox"}` yazılır;
  ana makine adresi ve boyutu ELF'ten okur. Linker betiği veya sabit adres gerekmez.
- RAM'e kod yüklemek için `-DEAT_SCRATCH_BYTES=2048` ve profilde `"scratch": {"symbol": "eat_scratch"}`.
  Kodun yalnız belirli bir RAM'den çalışabildiği hedeflerde (ör. ayrı komut RAM'i) `EAT_SCRATCH_ATTR`
  ile o bölümü seç.
- Bellek erişimi `volatile` işaretçilerle, RAM çağrısı düz C fonksiyon işaretçisiyle yapılır. Hedef başka
  bir şey istiyorsa `eat_hal` / `eat_link_port` yapılarını kendi fonksiyonlarınla doldur.
- RTOS'ta `eat_stub_poll()` ve `eat_link_rx()` aynı görevden çağrılır; o görev kesmeden değil görev
  bağlamında çalışır.

## Tek başına stub firmware

`eat_embed.c` yerine kendi `main`/başlangıç kodunu yaz, `eat_hal` (ve seri bağlantı için
`eat_link_port`) yapısını doldur, `eat_stub_init()` / `eat_link_init()` çağır. Bu yol, hiç
uygulaması olmayan boş bir kartı canlı kontrol için hazırlamaktır.

## Port listesi (her hedef için)

1. Mailbox ve scratch ELF sembolüyle bulunur; sabit adres kullanıyorsan profil ve linker aynı olmalı.
2. Açılışta kullanılabilir pinleri güvenli duruma al (çevre birimi clock'u kapalı veya giriş).
3. Debug ve seri bağlantı pinlerini hiçbir zaman yeniden yapılandırma; profilde `protected` yap.
4. RAM parçası kesme kullanacaksa vektör/trap tablosunu ve sözleşmeyi belirt.
5. Düşük güç modlarında debug bellek erişimi ve UART alımı kesilebilir; canlı kontrol sırasında girme.
6. Watchdog varsa uygulamanın döngüsü besler; stub ana makine olmadan da çalışır.
7. Profilde `live.entry_or`: RAM çağrısında giriş adresine OR'lanan mimari bitleri (Cortex-M Thumb: 1).
8. MCU veri dosyasına pin/register tariflerini hedefin referans kılavuzundan yaz; tahmin etme.
9. Gerçek kartta sırayla ölç: `stub status` → `peek` UID → LED `pin apply` → seri bağlantı (kullanılıyorsa)
   → ana makineyi kapat ve dead-man'in pini güvenli duruma aldığını ölç.

## Derleme örnekleri

Komutlar yalnız biçimi gösterir; çekirdek, bayraklar ve linker betiği hedefe aittir.

```text
ARM Cortex-M : arm-none-eabi-gcc -mcpu=<çekirdek> -mthumb -Os -ffreestanding -Istub ...
RISC-V       : riscv32-unknown-elf-gcc -march=<isa> -mabi=<abi> -Os -ffreestanding -Istub ...
PIC32 (MIPS) : xc32-gcc -mprocessor=<parça> -Os -Istub ...
ESP32 (IDF)  : kaynakları bir IDF bileşenine ekle; Xtensa için derleme bu repoda denetlenmez
```

- [Cortex-M](ports/cortex-m/README.md), [RISC-V](ports/riscv/README.md), [ESP-IDF](ports/esp-idf/README.md), [MIPS32/PIC32](ports/pic32/README.md): mimari port örnekleri.
