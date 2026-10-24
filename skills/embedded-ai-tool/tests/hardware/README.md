# İsteğe bağlı donanım kabul testleri

`EAT_HW_PROFILE` yoksa testler `optional:` gerekçesiyle atlanır ve donanıma erişmez.
Profil verilmesi bu testlerin LED registerlarına, mailbox'a ve isteğe bağlı scratch'e
yazmasını açıkça etkinleştirir. Bu repoda gerçek donanım kabul testi çalıştırılmadı.

## Bağlantı ve profil

- Ortak GND, uygun lojik gerilim, akım sınırlı besleme ve dirençli boş bir LED kullanın.
  Tehlikeli yük bağlamayın. Probe ve UART hatlarının pinlerini profilde koruyun.
- Yerel schema_version 2 profili; doğrulanmış UID, read/write izinleri, `live.mailbox`,
  `heartbeat_timeout_ms` ve etkin dead-man gereklidir. ELF sembolü kullanılıyorsa
  artifact bilgileri gerçek yerel derlemeyle eşleşmelidir. UID/profili repoya koymayın.
- `pins` ve `live.mcu_db` içindeki LED, `gpio_out` + `level=1` tarifini desteklemeli;
  `safe_function` tüm gerekli registerları güvenli duruma almalıdır. Aktif ve güvenli
  durum en az bir maskeli register alanında farklı olmalıdır. Aktif-low LED'de level=1
  ışık yakmayabilir; mantıksal geçişi ölçün. Release eski durumu değil güvenli tarifi uygular.
- Güvenli tarifin her registerı yan etkisiz okunabilir olmalı; write-only/W1C register
  bu testte kullanılamaz. Yazılım geri okuması çıkış seviyesinin fiziksel kanıtı değildir.
- Başka `serve`/MCP oturumlarını, heartbeat süreçlerini kapatın; önceki pin taleplerini
  release edin ve stub'ı disarm edin. Testler mevcut talepleri devralmaz. Paralel pytest
  çalıştırmayın. Çalışan uygulama test registerlarını değiştirmemelidir.

## Çalıştırma (PowerShell)

`skills/embedded-ai-tool/` dizininde:

```powershell
$env:EAT_HW_PROFILE = 'C:/local/acceptance.json'
$env:EAT_HW_PROBE = '<işlemci mimarisi> / <prob ve araç sürümü veya UART adaptörü>'
$env:EAT_HW_LED_PIN = 'LED'
python -m pytest -q -s -rs tests/hardware
```

Prob/transport tanımı için `EAT_HW_PROBE` zorunludur. Profil adı yalnız işlemci/mimari
seviyesinde anonim olmalıdır. LED adı verilmezse LED ve dead-man testleri atlanır;
transport serial değilse seri round-trip atlanır. Atlanan test kabul kanıtı değildir.
OpenOCD kullanılıyorsa yerel sunucuyu önceden başlatın; serial yolunda pyserial gerekir.

RAM testi için `EAT_HW_SNIPPET`, profilin `project_root` altındaki kullanıcı tarafından
hazırlanan küçük raw binary'nin göreli yoludur. `live.scratch`, yürütülebilir RAM,
doğru ISA/ABI, entry_or, gerekli cache/barrier ve linker koşulları önceden sağlanmalıdır.
Giriş byte 0'dadır; argümansız çağrı kısa sürede `uint32_t` 42 döndürmelidir.
Snippet verilmezse test `optional:` ile atlanır; bu repo snippet dağıtmaz. Yükleme
geri okunup doğrulanır ve CLI kaydındaki hash çalıştırmadan önce tekrar denetlenir.
Zaman aşımında parça hâlâ çalışıyor olabilir; otomatik tekrar yapılmaz.

## Dead-man ve fiziksel kanıt

Test LED'i uygular, güvenli tablonun kurulduğunu ve aktif register farkını doğrular,
son heartbeat'i yollar; sonra `heartbeat_timeout_ms` + en az 250 ms (%50) marj boyunca
heartbeat göndermez. Stub'ın dead-man durumu, sayacın bir artışı ve güvenli tarifteki
tüm registerların maskeli değerleri okunur. **Ayrıca pini logic analyzer ile ölçün**:
heartbeat kesilmesinden güvenli seviyeye geçişe kadar süreyi, güvenli seviyeyi ve
varsa pull-up/pull-down davranışını kaydedin. Özellikle safe_function giriş moduna
geçiyorsa latch geri okuması gerçek pin voltajını göstermez. Test sonunda LED release
edilir; bağlantı hatasında kör yazma tekrarı yapılmaz. Hatalı/yarım talepleri yerelde
inceleyin; otomatik tekrar başlatmayın.

Her test `EAT_HW` JSON satırında UTC tarih, profil adı, prob/transport, test ve sonucu
yazar (`-s` ile görünür). Konsol kayıtları yerelde kalmalıdır; UID veya artifact yolu
içerebilen tam hata çıktısını yayımlamadan inceleyin.
[live-control.md kanıt tablosuna](../../references/live-control.md#durum-kanıt-tablosu)
yalnız başarılı testin tarihini, işlemci/mimari, prob/transport ve araç sürümünü,
komut/register sonucunu aktarın. Fiziksel ölçümü ayrı sütunda süre/seviye ve ölçüm
aracıyla kaydedin; yalnız yazılım testi varsa fiziksel sütununu boş bırakın.
Ürün/şirket/kart isimleri, UID, profil dosyası veya firmware dosyası yayımlamayın.
