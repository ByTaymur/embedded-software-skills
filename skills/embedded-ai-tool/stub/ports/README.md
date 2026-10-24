# Mimari port örnekleri ve doğrulama kaydı

Bu dizindeki örnekler chip/kart tanımı değildir. Çekirdek ve Python paketi değiştirilmedi.
Saat ağacı, UART ve pin mux işleri `TODO(port)` kancalarıyla integratöre bırakıldı.

- [Cortex-M](cortex-m/README.md): SysTick, HardFault ve UART ana döngü örneği.
- [RISC-V](riscv/README.md): mcycle/time, exception kancası ve executable RAM koşulları.
- [ESP-IDF](esp-idf/README.md): bileşen, esp_timer ve tek FreeRTOS/UART görevi.
- [MIPS32/PIC32](pic32/README.md): CP0 Count, XC32 exception kancası ve KSEG koşulları.
- [Donanım kabul testleri](../../tests/hardware/README.md): opt-in status, UID, LED,
  seri round-trip, kullanıcı RAM parçası ve dead-man geri okuması/fiziksel ölçüm süreci.

2026-10-24 doğrulaması: `tests/test_ports.py`, Zig ile Cortex-M0 Thumb portunu ve
main örneğini, RV32 mcycle ve time yollarını, MIPS32 little-endian ortak kodunu
`-std=c99 -ffreestanding -Wall -Wextra -Werror` ile derledi. Bunlar object derleme
kontrolleridir; startup/linker bağlantısı veya gerçek donanım kabulü değildir.
ESP-IDF SDK/toolchain olmadığı için bileşen derlenmedi. XC32 bulunmadığından
XC32 başlığı ve runtime exception handler bağlantısı derlenmedi.

`skills/embedded-ai-tool/` altında tam `python -m pytest -q`: 111 başarılı test,
75 başarılı alt test; profil verilmediği için 6 donanım testi `optional:` gerekçesiyle
atlandı. `python -m ruff check .` ve `git diff --check` temiz. Kısıtlı çalışma
ortamında Zig cache dizinleri yazılabilir `.pytest_cache` altına yönlendirildi.
Hiçbir port gerçek donanımda doğrulanmadı; kanıt tablosuna donanım başarısı eklenmedi.

Commit oluşturulamadı: worktree'nin gerçek Git index dizini izin verilen yazma
kökünün dışında kaldığı için `git add` ve commit işlemleri `index.lock: Permission
denied` ile reddedildi. Dosyalar çalışma ağacında, stage edilmeden bırakıldı.
Yazma izni olan oturumda bu kapsamı stage edip tek commit oluşturun; mesaj:
`embedded-ai-tool: ports and optional hardware acceptance tests`.
