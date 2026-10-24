# Cortex-M mimari örneği

Bu bir kart portu değildir; donanımda doğrulanmadı. `eat_port_cortex_m.c`, SysTick'i
çekirdek saatinden 1 ms kesmeye ayırır. Başlatma gerçek çekirdek Hz değerini alır;
1000'e bölünmeyen veya 24 bit reload sınırını aşan saatleri reddeder. Başarısızlığı
işleyin; başlatmadan önce millis çağırmayın. Saat değişince yeniden yapılandırın.
SysTick zaten RTOS'a aitse bu handler'ı eklemeyin; mevcut 1 ms tick kancasını kullanın.
Firmware'in kendi `HardFault_Handler`'ı varsa bu dosyadakini derlemeyin; mevcut handler'ın başında `eat_stub_fault(3u)` çağırın.
Kesme maskelenmesi bir tick'i aşarsa zaman kaybolabilir; dead-man ölçümünü buna göre yapın.

`main_example.c` içindeki `TODO(port)` kancaları saat ağacı, pin mux, UART sürücüsü
ve uygulama adımı içindir. IRQ yalnız RX kuyruğunu doldurur; `eat_link_rx()` ve
`eat_stub_poll()` aynı ana döngüde çalışır. Poll aralığı heartbeat süresinden küçük olmalı.
Başlangıç vektörü `SysTick_Handler` ve `HardFault_Handler` işlevlerine bağlanmalı.
HardFault önce `eat_stub_fault(3)` çağırır, sonra dönmez; geçerli stack gerekir.
Stack bozulması/lockup gibi durumlar için bağımsız watchdog ve fiziksel koruma gerekir.

Mailbox için linker değişikliği gerekmez: adres ve boyut ELF sembolünden bulunur.
Profilin `live` alanına şu parçayı ekleyin:

```json
{"entry_or": 1, "mailbox": {"symbol": "eat_mailbox"}}
```

VTOR yalnız destekleyen çekirdeklerde ve vektör tablosunu taşımak gerekiyorsa kullanılır;
M0'da bulunduğunu varsaymayın. Hizalama ve bariyerleri mimari/startup kurallarına göre
integratör düzenler. RAM çağrıları için yürütülebilir scratch, MPU izinleri ve gerekiyorsa
veri/komut cache eşlemesi ayrıca sağlanmalıdır.
