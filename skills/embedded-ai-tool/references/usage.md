# Kurulum, proje profili ve komutlar

Skill klasörü tek başına kopyalanabilir. Runtime `scripts/embedded_ai_tool/`, giriş
`scripts/eat.py` dosyasıdır. Python 3.11+ ve pyelftools gerekir. Seçtiğin Python
ortamında `python -m pip install "<skill-klasörü>"` paket/dependency kurulumunu yapar.
Sonrasında `eat` komutu veya `python "<skill-klasörü>/scripts/eat.py"` kullanılabilir.

Komutları hedef firmware projesinin klasöründe çalıştır. Bundan sonraki örneklerde
`eat` yerine gerekirse tam Python/giriş dosyası komutunu yaz. Profil, log ve gerçek
firmware dosyalarını skill klasörüne kaydetme. Tüm komutlar JSON döndürür; `watch`
ara örnekler için de JSON satırı üretir. Hata durumunda çıkış kodu 1 olur.

## Yeni kart

1. MCU modeli, debug pinleri, besleme ve probu doğrula. UID alanının adres/boyutunu
   ve bellek haritasını MCU belgesinden al; örneklerden tahmin etme.
2. `eat init debug/my-board --name my-board` ile `board.json` şablonunu üret.
   Aynı dosyanın üzerine yazmaz. Canlı erişim için donanım alanları doldurulmalıdır;
   çevrimdışı build/search ve yerel OpenOCD başlatma hedef UID'si istemez.
3. OpenOCD'yi kart/probe için incelenmiş config dosyalarıyla başlat. Birden fazla
   prob varsa seri numarasını config içinde seç. Yeni sunucu başlatmak için profil
   tamamlandığında `openocd` planını incele; `openocd --execute` ön planda çalışır.
4. API, Tcl RPC portudur: varsayılan 6666. Telnet/GDB portunu kullanma. Uzak erişimde
   Tcl portuna uygun hazırlanmış tüneli kullan; tüneli değiştirmek ayrı bir iştir.
   `openocd` komutu yerel sunucuyu profilin Tcl portuyla başlatır. Kullandığın config
   dosyaları port ayarından önce `init` çalıştırmamalıdır.
5. `eat probe-uid <adres> <bayt-sayısı> --host <host> --port <port>` ile doğruladığın,
   8 bit erişimi destekleyen UID alanını oku. Fiziksel kartı teyit et; `uid_hex`
   çıktısını aynı bayt sırasıyla `identity.expected_hex` alanına yaz.
6. `eat symbols path/to/firmware.elf --filter counter` ile sembol adresi/boyutu,
   byte order ve ELF SHA256 bilgisini al. `artifact.path` ve `artifact.sha256`
   alanlarını bu build'e bağla. ELF ve AXF desteklenir; stripped build'de sembol yoktur.
7. `read_ranges` alanına UID, kullanılacak RAM/register/flash alanlarını ekle.
   `flash_ranges`, dosya verisi taşıyan bütün PT_LOAD segmentlerini kapsamalı.
   RAM başlangıç verilerinin flash adresi ELF `p_paddr` yükleme adresidir.
8. İzlenecek değişkenleri `variables` içinde açık tipleriyle tanımla.

## Profil alanları

| Alan | Anlamı |
|---|---|
| `schema_version` | `1` |
| `name` | Proje/kart profil adı |
| `project_root` | Profil dosyasının klasörüne göre proje kökü |
| `byte_order` | Hedef/ELF ile aynı `little` veya `big` |
| `connection` | `host`, Tcl `port`, `timeout_s` (0'dan büyük, en fazla 300) |
| `identity` | `address`, `size` (bayt), `expected_hex` (ham bayt sırası) |
| `read_ranges` | `address`/`size` nesnelerinin listesi |
| `flash_ranges` | Aynı biçimde flash yükleme alanları |
| `artifact` | `project_root` göreli `path` ve dosyanın `sha256` değeri |
| `variables` | İsim → sembol veya ham adres, tip ve isteğe bağlı yazma/erişim bilgisi |
| `build` | Shell kullanmayan `argv` listesi, isteğe bağlı `timeout_s` |
| `openocd` | `executable`, `config_files`, isteğe bağlı `shared_filesystem` |

Adres/boyutlar JSON tam sayısı veya `0x...` biçiminde metin olabilir. Sayısal
aralıklar MCU belgesinden alınır. `config_files` ve build komutu `project_root`
klasöründe çalışır; OpenOCD'nin kendi config arama yolları da geçerlidir.

Örnek değişken tanımları (`variables` nesnesinin içi):

```json
{
  "counter": {"symbol": "counter", "type": "u32", "writable": true, "min": 0, "max": 100},
  "temperature": {"symbol": "temperature", "type": "f32", "writable": false}
}
```

İsim ve sınırlar yalnız örnektir. `symbol` yerine MCU belgesinden doğrulanmış ham
`address` kullanılabilir; ikisi birlikte verilemez. Tipler: `u8/i8/u16/i16/u32/i32/
u64/i64/f32/f64`. ELF sembolü tekil ve belirtilen tiple aynı boyutta olmalı. Tipin
işaret/float anlamı DWARF'tan çıkarılmaz; doğru tip proje sorumluluğundadır.
Struct/dizi ifadeleri desteklenmez.

`access_bits` ile 8/16/32/64 bit okuma seçilebilir. Varsayılan erişim genişliği
tip boyutu, en fazla 32 bittir. Register genişliği MCU belgesiyle eşleşmeli;
okununca temizlenen bayraklar izlemeye eklenmez. Yazma ancak `writable=true` ve
sayısal `min`/`max` ile mümkündür; doğal tip genişliğinde hizalı yazma/readback yapılır.

## Komut akışı

```text
eat --profile debug/my-board/board.json identity
eat --profile debug/my-board/board.json verify
eat --profile debug/my-board/board.json read counter temperature
eat --profile debug/my-board/board.json watch counter temperature --duration 20 --interval 0.1
eat --profile debug/my-board/board.json search counter --limit 30
eat --profile debug/my-board/board.json write counter 42
eat --profile debug/my-board/board.json write counter 42 --execute
eat --profile debug/my-board/board.json build
eat --profile debug/my-board/board.json build --execute
eat --profile debug/my-board/board.json flash
eat --profile debug/my-board/board.json flash --execute
eat --profile debug/my-board/board.json control halt --execute
eat --profile debug/my-board/board.json control resume --execute
```

`write`, `build`, `flash`, `openocd`, `control`: varsayılan çevrimdışı plan;
`--execute` kullanıcının yetkilendirdiği kapsamı uygular. Etkileşimli onay döngüsü yoktur.
Kontrol seçenekleri `halt`, `resume`, `reset-run`, `reset-halt`.
Olay niyeti bağlantıdan önce, sonuç işlemden sonra `sessions/` altına yazılır.
İstenen kayıt dizini `--session-dir <dizin>` ile alt komuttan önce seçilir.
Sonuç kaydı profil hash'ini, beklenen UID/build'i ve bağlantıyı içerir; bunlar profil
bağlamıdır. `read` ve `watch`, sembol kullanılıyorsa ölçümden önce canlı build'i
karşılaştırır. NaN/sonsuz float ölçümü ham baytları içeren tanısal hatayla bildirilir.

`build.argv` CMake/make/Keil/CubeIDE komutu olabilir. Profil yerel güvenilir
çalıştırma yapılandırmasıdır; komut shell ile yorumlanmaz. Yeni build sonrası ELF
hash'i ve değişken arayüzü gözden geçirilir; araç hash'i kendiliğinden güncellemez.

`verify`, tüm dosya destekli PT_LOAD baytlarını karşılaştırır; boş flash, EEPROM,
option bytes veya fiziksel uygulama sonucunu doğrulamaz. `write` bunu tekrar yapıp
UID kontrolüyle aynı Tcl isteğinde yazmayı gönderir. Belirsiz yazma tekrarlanmaz.

`flash`: UID → halt → flash erase/write → verify_image → reset run. Yeni ELF ile
eski flash'ın önceden eşleşmesi gerekmez; hedef UID ve yüklenecek ELF hash'i denetlenir.
Hash'i doğrulanan ELF baytları kayıt klasöründe sabit bir imaja kopyalanır; eşzamanlı
derleme yüklenen dosyayı değiştiremez. Bu imaj yerel firmware verisidir, yayımlanmaz.
`openocd.shared_filesystem=true` yalnız sunucu gerçekten aynı ELF dosyasını görüyorsa
açılır. Uzak dosya aktarımı yoktur. Uzun yüklemeler için `connection.timeout_s` değerini
hedefe göre seç. Hata sonrası kart durmuş/yarım yazılmış olabilir; durumu yeniden oku.

Kendi başına LLM/MCP/web sunucusu başlatılmaz. AI ajanı kaynak düzenleme araçlarıyla
geliştirir; bu skill komutlarıyla derler ve ölçer. Her hedefte canlı kabul testi gerekir.

Teknik kaynaklar: [OpenOCD Tcl RPC](https://openocd.org/doc/html/Tcl-Scripting-API.html),
[bellek komutları](https://openocd.org/doc/html/General-Commands.html),
[flash komutları](https://openocd.org/doc/html/Flash-Commands.html).

## ST-Link ve OpenOCD kapsamı

ST-Link prob, OpenOCD bağlantı sunucusudur. Bu araç ikisini birlikte kullanır;
OpenOCD'siz doğrudan ST-Link USB/CubeProgrammer/GDB erişimi sağlamaz.
OpenOCD'nin güncel `st-link` sürücüsü desteklediği V2/V3 modellerini kendi
adaptör yapılandırmasıyla seçer; eski HLA sürücüsünün config adı ve transport'u
OpenOCD sürümüne göre farklıdır. Kurulu OpenOCD dağıtımının `interface/` dosyalarını
esas al. [Resmî adaptör dokümanı](https://openocd.org/doc/html/Debug-Adapter-Configuration.html).

Örneğin `interface/stlink.cfg` ve hedef MCU için incelenmiş `target/<aile>.cfg`
dosyaları `openocd.config_files` listesinde kullanılabilir. Bu bir bağlantı şablonudur;
MCU ailesi, seri numarası, transport ve hız hedefe göre belirlenir. STM32 haricindeki
hedeflerde probun o hedefi desteklediğini ayrıca doğrula. Varsayılan seçili target
kullanılır; çok çekirdekli hedef seçimi ayrı profil/config gerektirir.

Yayın durumu **alpha**: yerel yazılım ve adaptör açılmadan Tcl testleri vardır.
Gerçek ST-Link V2/V3 + kart bağlantısı/yazma/flash uyumluluğu henüz ölçülmedi.
Mevcut destek sınırları ve katkı komutları [paket README'sindedir](../README.md).

## Entegrasyon doğrulaması — 2026-10-20

Araç bu skill'in içine paketlendi; başka bir kaynak deposuna veya sabit kullanıcı
yoluna ihtiyaç duymaz. Mevcut kaynak düzenleme ve STM32 iş akışlarında isteğe bağlı
araç olarak yönlendirilir. Eski projelerin makineye özel kayıtları bu skill'e alınmadı.

- 15 test geçti: çekirdek protokol/kimlik/yazma testleri, klasör taşıma sonrası
  giriş dosyası ve yerel paket importu, başka çalışma dizininde profil oluşturma.
- Skill doğrulayıcısı, Ruff ve Python derlenebilirlik kontrolü başarılı.
- Wheel üretimi ve geçici hedefe kurulan wheel'in izole Python ile çalışması başarılı.
  İlk izole build bağımlılık aşamasında bekledi; mevcut build araçlarıyla
  `--no-build-isolation` kullanılarak paket üretimi tamamlandı.
- Gerçek OpenOCD yorumlayıcı testi `noinit` ile, adaptör/target açılmadan geçti.
  Gerçek kart bağlantısı, firmware derlemesi, yazma veya flash testi yapılmadı.

Bakım için skill klasöründe `python -m unittest discover -s tests -v`,
`python -m ruff check scripts tests` ve `python -m compileall -q scripts` kullanılır.
Testin atlanması veya hedef kartta yapılmayan işlemler ayrıca belirtilir; ham test
ve build çıktıları skill kaynaklarına eklenmez.
