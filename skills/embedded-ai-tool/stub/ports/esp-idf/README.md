# ESP-IDF bileşen örneği

**derlenmedi / not compiled in this repo**: IDF SDK, FreeRTOS başlıkları ve Xtensa
toolchain bu repoda yoktur. RISC-V ESP hedefleri de burada IDF ile derlenmedi.
Donanımda çalıştığı iddia edilmez.

Bu dizini bileşen olarak `EXTRA_COMPONENT_DIRS` içine ekleyin; `../../eat_*.c`
göreli yollarını koruyun veya kaynakları birlikte taşıyın. `idf_component.yml`
IDF bağımlılığını bildirir; IDF ortamını integratör sağlar.
`eat_port_esp_idf_start(uart, stack_bytes, priority)` öncesinde public IDF API'leriyle
UART driver, baud, pin mux ve clock ayarlarını yapın (`TODO(port)`). Yalnız bir kez
başlatın ve dönen `esp_err_t` hatasını işleyin. Debug/seri bağlantı pinlerini koruyun.
Stack boyutunu RAM parçasının kullanımı dahil ölçün; görev önceliği ve tick süresi
heartbeat zaman aşımından çok küçük bir poll aralığı sağlamalıdır.

Millis `esp_timer_get_time()/1000` kullanır. Tek FreeRTOS görevi UART'tan en çok 64
bayt alıp `eat_link_rx()` ve `eat_stub_poll()` çağırır; diğer görev/IRQ bunları
çağırmamalıdır. TX hatası IDF hata yoluna gider. Panic handler burada değiştirilmez:
IDF'nin public ve sürüme uygun panic entegrasyon noktasını integratör belirlemeli;
geçerli bağlamda `eat_stub_fault(cause)` ve donanımsal güvenli durumu sağlamalıdır.
Cache kapalı panic bağlamından normal C stub'ını çağırmanın güvenli olduğunu varsaymayın.

`eat_port_config.h`, `EAT_SCRATCH_ATTR` için `IRAM_ATTR` tarzı yerleşim verir ve
CMake bunu **eat_embed.c dahil tüm bileşene** uygular. Scratch varsayılan olarak
kapalıdır; boyutu `EAT_SCRATCH_BYTES` ile seçin. Xtensa'da komut RAM'inin veri erişim
genişliği/alias kısıtları ve cache kuralları olabilir; IRAM adresini sıradan byte RAM
gibi kullanmayın. RISC-V ESP hedeflerinde de gerçek executable RAM/izin ve komut
senkronizasyonu doğrulanmalıdır. Attribute tek başına yeterli değildir: linker
haritasını ve RAM yazma/çalıştırma yolunu doğrulayın; gerekiyorsa özel
`eat_hal`/`eat_link_port` kullanın. RAM çağrısını bunlar tamamlanmadan etkinleştirmeyin.

Mailbox ELF'teki `eat_mailbox` sembolünden bulunur; bunun için linker değişikliği
gerekmez. Profilde `live.mailbox: {"symbol": "eat_mailbox"}` kullanın; Xtensa ve
RISC-V için `live.entry_or` değeri 0'dır.
