# Canlı RAM kontrolü: flash'a yazmadan pin ve çevre birimi yönetimi

Bu bölüm, kartta yalnızca bir kez yüklenen sabit bir **stub** ile yapay zekanın pinleri,
çevre birimlerini ve küçük RAM parçalarını anlık yönetmesini anlatır. Hiçbir komut
bu modda flash'a yazmaz. Reset veya güç kesilince RAM silinir, kart stub'a döner.

```text
Ajan --JSON--> eat (ana makine) --Tcl RPC--> OpenOCD --SWD--> MCU
                                                              RAM: [mailbox][scratch kod][...]
                                                              Flash: yalnız stub (bir kez yüklenir)
```

## Durum: kanıt tablosu

Üç ayrı kanıt düzeyi: **host testi** (sahte RPC, gerçek OpenOCD yorumlayıcısı `noinit` ile, host'ta
derlenen gerçek C kodu), **kart denemesi** (gerçek prob ve MCU'da komut + register/RAM geri okuması),
**fiziksel ölçüm** (pinde gözle, ölçü aletiyle veya osiloskopla görülen sonuç). Kart ve ölçüm
sütunlarına yalnız işlemci, prob ve araç sürümüyle kaydedilen sonuçlar yazılır; makine/ürün adı ve
firmware dosyaları kaydedilmez. "1 kart": 2026-10-24, STM32F732 (Cortex-M7), ST-Link V3, xPack OpenOCD
0.12.0+dev; kartta bir uygulama firmware'i çalışırken, CPU durdurulmadan. Başka prob, MCU veya mimari denenmedi.

| Parça | Host testi | Kart denemesi | Fiziksel ölçüm |
|---|---|---|---|
| OpenOCD Tcl RPC, UID koruması, `identity`, `peek` | Var | 1 kart | Gerekmez |
| SVD ile adla register/bit alanı okuma ve çevrimdışı listeleme | Var | Yok | Gerekmez |
| SVD adlarıyla pin tarifleri ve `mcu-db scaffold` | Var | Yok | Yok |
| `poke`: tam, maskeli oku-değiştir-yaz, 16 bit, `--no-verify` kör yazma; politika retleri | Var | 1 kart (RAM'de) | Gerekmez |
| `pin apply` / `pin release` (GPIO çıkış tarifi) | Var | 1 kart, tek LED pini | Var: LED gözle; aynı porttaki diğer çıkışların değişmediği register okumasıyla |
| `pin restore`, `safe`, kaynak çakışması, `partial` kaydı | Var | Yok | Yok |
| PWM, UART ve diğer çevre birimi tarifleri | Var (kurgusal veriyle) | Yok | Yok |
| `serve`, `mcp` (16 araç), OpenOCD'yi otomatik başlatma | Var | 1 kart (okuma ve LED tarifi) | Gerekmez |
| Magic korumalı heartbeat (stub yokken mailbox'a yazmama) | Var | 1 kart | Gerekmez |
| Stub çekirdeği: mailbox, dead-man, RAM çağrısı, fault | Var (C kodu host'ta, Python istemcisiyle) | **Yok**: hiçbir hedefte stub çalıştırılmadı | **Yok**: bağlantı kopunca çıkışın güvenli duruma geçtiği ölçülmedi |
| `ram build` / `load` / `run` | Var | Yok | Yok |
| MCP `watch_variables`: tablo, min/max, süre sınırı, heartbeat | Var | Yok | Yok |
| `fault`: SCB bayrakları, adres geçerliliği, exception frame, politika retleri | Var | Yok | Yok |
| Seri bağlantı (`eat_link`, `link.py`), `eat_embed` entegrasyonu | Var (gerçek C koduna karşı, simüle bellek); ARM Cortex-M0, RISC-V 32, MIPS32, 64 bit host için `-Werror -pedantic` derleme | **Yok**: gerçek UART üzerinde denenmedi | Yok |
| MCU veri dosyaları | `references/examples/` **kurgusaldır** | Kart denemesindeki dosya o karta özeldir ve dağıtılmaz | — |

Host testleri protokol, politika ve mantık hatalarını yakalar; donanım davranışını kanıtlamaz. Bir
mimaride derlenmesi o mimarinin kartlarında çalıştığını göstermez. Uyumluluk iddiası yalnız kart ve
fiziksel ölçüm sütunlarına dayanır.

## Profil (schema_version 2)

Kartla bağlantı `connection.transport` ile seçilir:

| `transport` | Alanlar | Kullanım |
|---|---|---|
| `openocd` (varsayılan) | `host`, `port` (Tcl, 6666), `timeout_s` | Debug probu (SWD/JTAG) üzerinden; `control`/`flash` yalnız burada |
| `serial` | `port` (`COM5`, `/dev/ttyACM0`), `baud`, `timeout_s` | Stub'ın seri bağlantısı (`pip install pyserial`); probsuz veya OpenOCD'nin desteklemediği hedefler |

İki yol da aynı komutları, `serve` ve `mcp`'yi destekler; her istekte kart kimliği denetlenir.

`live` ve `pins` alanları yalnız `schema_version: 2` profilinde bulunabilir. Tam örnek:
[examples/example-board.json](examples/example-board.json) (kurgusal adresler).

| Alan | Anlamı |
|---|---|
| `live.write_ranges` | `poke` ve tariflerin yazabileceği register/RAM alanları. `mailbox` ve `scratch` okunabilir ama `write_ranges` kapsasa bile `poke`/tarifle **yazılamaz**; onlara yalnız stub protokolü ve `ram load` yazar |
| `live.protected_ranges` | Her izin listesinden güçlü; bu alanlara yazı reddedilir (flash, option bytes, debug/clock kontrolü) |
| `live.side_effect_ranges` | Okuması durum değiştiren registerlar. `peek` reddeder; yazma körlemesine yapılır, geri okuma ve maskeli yazma yapılmaz |
| `live.mailbox` | Stub mailbox RAM'i (hizalı, en az 88 bayt): `{"address", "size"}` veya `{"symbol": "eat_mailbox"}` (adres/boyut profildeki `artifact` ELF'inden). Tanımlıysa pin komutları çalışan stub ister |
| `live.scratch` | RAM'e yüklenecek kod bölgesi, aynı biçimde (`{"symbol": "eat_scratch"}`); `mailbox` ile çakışamaz |
| `live.heartbeat_timeout_ms` | Dead-man süresi, 100..60000, varsayılan 1000 |
| `live.deadman` | Varsayılan `true`; `false` ise stub güvenli durumu otomatik uygulamaz |
| `live.entry_or` | `ram run` giriş adresine OR'lanan mimari bitleri; varsayılan 0. Cortex-M (Thumb) için 1 |
| `live.verify_build` | Yazmadan önce flash'taki (stub) imajı doğrula. Varsayılan: profilde `artifact` ve `flash_ranges` varsa `true`; oturum başına bir kez |
| `live.mcu_db` | MCU veri dosyası yolu (profile göre) |
| `live.ram_build` | `{"argv": [...], "output": "snippet.bin", "timeout_s": 60}` |
| `pins.<ad>` | `mcu_pin`, `functions` (izinli işlevler), `safe_function`, `limits`, `protected` + `reason` |

Pin kuralları: profilde olmayan pin, `functions` dışındaki işlev veya `protected: true`
pin reddedilir. SWDIO/SWCLK gibi debug pinlerini **her zaman** `protected` yap.
`limits` girdi başına `min`/`max` koyar ve tarifin kendi sınırıyla kesişir
(`{"duty_permille": {"max": 500}}`). Güvenli durum tarifi (`safe_function`) zorunludur.

## MCU veri dosyası

MCU'ya özgü bilgi kodda değil veridedir. Adresler ve bitler referans kılavuzdan veya SVD'den alınır;
**tahmin edilmez.** Şema: [examples/example-mcu.json](examples/example-mcu.json).

- `pins.<MCU pini>.functions.<işlev>` → `recipe` adı, `params` (tam sayı ifadeleri), isteğe bağlı `resources`.
- `recipes.<ad>`: `inputs` (kullanıcı girdileri: `default`, `min`, `max`, `required`), `derive`
  (sıralı türetilmiş değerler), `steps`, isteğe bağlı `resources`.
- Adım türleri: `write`, `modify` (`mask` + `value`), `read` (`name` ile çıktı üretir), `poll`
  (bit bekler, `timeout_ms` ≤ 2000), `delay_ms` (≤ 1000). `width` 8/16/32; `verify: false`
  yazma-only veya yazarak-temizlenen (W1C) registerlar içindir: adım **kör, tam genişlikte** yazılır,
  register hiç okunmaz; bu yüzden maske verilemez ve geri alma kaydı tutulamaz.
- İfadeler yalnız **tam sayı** aritmetiğidir: `+ - * // % << >> & | ^ ~`, parantez, `min`, `max`
  ve parametre adları. Ek çağrılar yalnız aşağıdaki iki alan yardımcısıdır; nitelik erişimi,
  kayan nokta ve `/` yoktur; uzunluk ≤ 256.
- `resources` yalnız **paylaşılamayan** kaynakları listeler (örn. `UART0`, `TIM0_CH1`). İki pin
  aynı kaynağı talep edemez. Paylaşılabilir kaynakları (ortak timer clock'u) yazma.
- Dead-man açıkken `safe_function` tarifi yalnız `write`/`modify` içerebilir; stub bunları tekrar oynatır.

`live.svd` varsa `address` register adı olabilir; yoksa adlandırılmış adım reddedilir:

```json
{"op": "modify", "address": "GPIO{port}.MODER",
 "mask": "field_mask(\"MODER{pin}\")", "value": "field_value(\"MODER{pin}\", 1)"}
```

Ad/alan içindeki `{param}` düz parametre adıdır; biçimlendirme ve nitelik erişimi yoktur.
Alan yardımcıları yalnız bu registerın alanlarını kabul eder; taşan alan değeri reddedilir.
Genişlik varsayılanı SVD'den gelir, verilirse aynı olmalıdır. Sayısal adresler geçerlidir.
SVD izin vermez: somut adımlar yine `Live.prepare`, `write_ranges`, korumalı alan,
yan etki ve SVD `readAction` denetimlerinden geçer.

```text
eat mcu-db scaffold --svd device.svd --map pin-map.json --out new-mcu.json
```

Komut çevrimdışıdır ve mevcut dosyanın üzerine yazmaz. Kurgusal eşleme:
[example-pin-map.json](examples/example-pin-map.json), testlerdeki `fictional.svd` içindir.
`pins.<pin>` altında `level` (`register`, `field`, `low`, `high`), `direction` listesi
(her öğede `register`, `field`, `input`, `output`) ve `input` (`register`, `field`) zorunludur.
Yön listesi ayrı pin-mux bloklarını da açıkça eşleyebilir. İsteğe bağlı `atomic` içinde
`set` ve `clear`, aynı registerdaki `register`, `field`, `value` eşlemeleridir;
seçilen seviye kör tam-register yazması üretir. Register adından işlev çıkarılmaz.
Kullanıcı anlamları doğrular; araç SVD adlarını ve alan değerlerini doğrulayıp her pin için
`gpio_out`, `gpio_in`, `gpio_read` tariflerini üretir. Bu başlangıç dosyası clock/açılış
adımlarını tahmin etmez; donanımda kullanmadan önce incelenmelidir.

## Komutlar

Değiştiren komutlar `--execute` olmadan **plan** döndürür ve hiç bağlanmaz.

| Komut | İşlev |
|---|---|
| `peek ADRES [--count N] [--width 8\|16\|32]` | İzinli alandan oku |
| `poke ADRES DEĞER [--width] [--mask] [--no-verify] [--execute]` | Yaz; maske verilirse tek Tcl isteğinde oku-değiştir-yaz; sonra geri oku |
| `pin list` | Profildeki pinler, izinli işlevler, ana makine kayıtlı talepleri (ölçülmemiş) |
| `pin apply PIN İŞLEV [--param ad=değer ...] [--execute]` | Tarifi uygula |
| `pin release PIN [--execute]` | `safe_function` tarifiyle güvenli duruma al, talebi bırak |
| `pin restore PIN [--execute]` | Uygulamadan önceki register bitlerini geri yaz |
| `safe [--all] [--execute]` | Talep edilen (veya profildeki bütün korumasız) pinleri güvenli duruma al; biri başarısız olsa devam eder |
| `ram build\|load\|run` | Bölüm "RAM parçası" |
| `stub status` | Mailbox, heartbeat ve dead-man sayacı |
| `serve` | Satır tabanlı JSON oturumu |

Bir pin uygulaması şu sırayla ilerler: UID/build doğrulama → politika ve sınırlar →
kaynak çakışması → stub canlı mı → **dead-man tablosunu önce kur** → adımlar (her adım
UID korumalı, geri okumalı) → talep ve geri alma kaydı. Adım yarıda kalırsa talep
`partial` işaretlenir, otomatik tekrar veya otomatik düzeltme yapılmaz; sonucu ölç,
sonra `pin release`/`restore`/`safe` kararını ver.

### `serve` oturumu

```text
eat --profile debug/my-board/board.json serve
{"argv": ["pin", "apply", "LED", "pwm", "--param", "freq=1000", "--execute"]}
{"argv": ["pin", "list"]}
```

İlk çıktı satırı `{"event": "ready", ...}`; her istek bir yanıt satırı üretir. `--execute` yazılmayan
değiştirici istekler yine yalnız plan döndürür.

Her satır `{"argv": [...]}`; yanıt, normal komut çıktısı ve denetim kaydıdır. Tek RPC
bağlantısı açık kalır; profil, MCU verisi, pin kaydı ve flash doğrulaması oturum başında bir kez
yüklenir (oturum sürerken profili değiştirmek için `serve` yeniden başlatılır). Stub heartbeat'i
`heartbeat_timeout_ms / 3` aralığıyla ve uzun flash doğrulaması sırasında da yazılır. Heartbeat
yalnız aynı Tcl isteğinde mailbox `magic` görülürse yazılır; stub yoksa `ready` olayı `stub: false`
der ve o RAM'e hiç dokunulmaz. Bir RPC çağrısı yarıda kalırsa (zaman aşımı) bağlantı kapatılır ve
oturum biter: geç gelen yanıt sonraki isteğe karışmaz. İstek sırasında Ctrl+C oturumu bitirir.
argparse yardım/hata metni stdout'a değil yanıtın `output` alanına yazılır.
İzinli komutlar: `peek poke pin safe ram stub reg identity verify read`. Oturum biterse
heartbeat durur ve stub süre sonunda pinleri güvenli duruma alır. **Tek seferlik CLI
çağrısı da bu süreyi başlatır**: `pin apply` sonrası çıkış, `serve` çalışmıyorsa
yaklaşık `heartbeat_timeout_ms` sonra geri alınır. Kalıcı bırakmak için `serve` kullan.

### `mcp` köprüsü (yapay zekâ → işlemcinin RAM'i)

```text
Yapay zekâ istemcisi --MCP (stdio)--> eat mcp --Tcl RPC--> OpenOCD --SWD/ST-Link--> MCU register/RAM/stub
```

`eat --profile <board.json> mcp`, `serve` ile aynı oturumu MCP aracı olarak sunar. Ek paket
gerekmez. Claude Code'a proje kapsamında kaydetmek için proje kökünde `.mcp.json`:

```json
{
  "mcpServers": {
    "embedded-ai-tool": {
      "command": "python",
      "args": ["<skill>/scripts/eat.py", "--profile", "debug/my-board/board.json",
               "--session-dir", "sessions", "mcp"]
    }
  }
}
```

veya `claude mcp add embedded-ai-tool -- python <skill>/scripts/eat.py --profile debug/my-board/board.json mcp`.

| Araç | CLI karşılığı | Karta dokunur mu |
|---|---|---|
| `target_identity`, `verify_build`, `read_variables`, `peek`, `stub_status` | `identity`, `verify`, `read`, `peek`, `stub status` | Okur |
| `pin_list` | `pin list` | Hayır |
| `poke`, `pin_apply`, `pin_release`, `pin_restore`, `safe_state`, `ram_load`, `ram_run` | aynı adlar | Yalnız `execute: true` ile yazar; aksi hâlde plan |
| `ram_build` | `ram build` | Hayır (ana makinede derler) |

- Bağlantı tembeldir: istemci başlarken OpenOCD kapalı olabilir; ilk donanım çağrısında açılır,
  koparsa sonraki çağrıda yeniden açılır (flash doğrulaması yeniden yapılır). OpenOCD yoksa çağrı
  araç hatası döner, sunucu çökmez.
- Profilde `"openocd": {"autostart": true, "executable": ..., "config_files": [...]}` varsa bağlantı
  reddedildiğinde köprü `eat openocd` ile aynı argv'yi başlatır (en çok 10 sn bekler) ve çıkarken
  yalnız kendi başlattığı OpenOCD'yi kapatır; hedef resetlenmez/durdurulmaz. Böylece yapay zekâ
  istemcisi açıldığında ST-Link'ten RAM'e kadar zincir tek kayıtla kurulur.
- Her çağrı CLI ile aynı yoldan geçer: ayrıştırıcı, `sessions/` denetim kaydı, bellek/pin politikası,
  her Tcl isteğinde UID koruması, dead-man. stdout yalnız JSON-RPC taşır; günlük stderr'e gider.
- İnsan onayı: değiştiren araçlar `destructiveHint` ile işaretlidir. Okuyan araçları
  (`mcp__embedded-ai-tool__peek` vb.) izin listesine eklemek güvenlidir; değiştirenleri onaya bırakın.
- İstemci kapanınca heartbeat durur ve stub, `heartbeat_timeout_ms` sonra pinleri güvenli duruma alır.
- Desteklenmeyenler: `write`, `flash`, `control` (halt/reset) ve MCP kaynakları/istemleri.

### `watch_variables`

MCP `watch_variables`, profil değişkenlerini CPU'yu durdurmadan örnekler: `names` listesi,
`samples` 1..200 (varsayılan 20), `interval_ms` 10..5000 (varsayılan 200).
Planlanan `(samples - 1) * interval_ms` 60000'i aşarsa reddedilir; çalışma bütçesi de
60 saniyedir (build doğrulaması ve taşıma beklemeleri dahil); döngü süre dolunca yeni
okuma başlatmaz. Sürmekte olan tek bir istek bağlantı zaman aşımı kadar ek süre alabilir.
Sonuç `columns`, `rows`
(ilk örneğe göre `t_ms`), `min_max`, `samples`, `complete` ve `atomic: false` içerir.
Ardışık okumalar atomik değildir; gecikmeler gerçek zaman garantisi vermez. Süre dolunca
kısmi tablo (`complete: false`) veya taşıma zaman aşımı hatası döner. Oturum heartbeat'i
örnekler ve beklemeler arasında beslenir; stdout yalnız JSON-RPC taşır. SVD adıyla register
örnekleme bu araçta yoktur. Aynı tablo CLI'da `watch-variables` ile alınabilir.

### Fault kanıtı

`eat fault` ve salt okuyan MCP `fault_evidence`, yalnız `live.arch: "cortex-m"` seçilince
SCB CFSR/HFSR/MMFAR/BFAR/SHCSR/ICSR/CPUID/AFSR okur. Bilinmeyen veya eksik mimari
`desteklenmiyor` döndürür. Profil `read_ranges` alanına
`{"address": "0xE000ED00", "size": "0x100"}` gerekir; okuma yan etkisi politikası da
uygulanır. Bayraklar ve MMARVALID/BFARVALID raporlanır; geçersiz adresler yorumlanmaz.
AFSR uygulamaya özgü olduğundan yalnız ham değer raporlanır. Register yerleşimi Armv7-M
ARM DDI 0403E.b §B3.2 ve Armv8-M ARM DDI 0553B.y §B3.12'ye dayanır; SCB fault registerları
olmayan çekirdeklerde bu seçim kullanılmamalıdır.

Exception frame yalnız OpenOCD'de çekirdek zaten halt edilmişse okunur; araç halt/reset
yapmaz. SP/LR/PC/xPSR ve MSP/PSP okunur, LR'deki standart EXC_RETURN ile MSP/PSP ve
basic/extended frame seçilir (iki biçimde de temel frame SP adresinde; FP alanı ardından gelir).
İzinli yığından 8 kelime ve stacked PC/LR alınır. Handler prologue yığını değiştirmiş olabilir; güvenlik durumları arasında
geçiş yapan EXC_RETURN değerleri yorumlanmaz. Çalışan çekirdekte veya seri bağlantıda
halt edilmiş çekirdek gerektiği belirtilir. `ram run`, fault durumunda `ValueError` verir;
`live.arch` tanımlıysa hata mesajının sonuna `; fault_evidence=` ve kompakt JSON kanıtı eklenir.
Kanıt okuma hatası `{"error": ...}` olarak eklenir; RAM çağrısı hata olarak kalır.

## SVD

İsteğe bağlı `live.svd`, profil dosyasına göre çözülen yerel CMSIS-SVD yoludur:
`"live": {"svd": "device.svd"}`. SVD byte order belirtirse profilin `byte_order`
değeriyle uyuşmalıdır. Dosya en fazla 64 MB olabilir; DOCTYPE/ENTITY reddedilir.

`eat reg list [ÇEVRE_BİRİMİ] [--filter METİN]` bağlantı açmadan registerları listeler.
`eat reg read PORT.MODE PORT.MODE.STATE` registerı bir kez okuyup adres, genişlik,
ham değer ve adlandırılmış bit alanlarını (varsa enum adlarıyla) döndürür. Profil
`--profile` ile seçilir. Adlar büyük/küçük harfe duyarsızdır; dizilerde `DATA0`
ve `DATA[0]` kullanılabilir. MCP karşılıkları `read_register {names: [...]}` ve
çevrimdışı `list_registers {peripheral?, filter?}` araçlarıdır; `serve` içinde `reg` desteklenir.

SVD hiçbir izin vermez. Okumalar mevcut bellek politikasından ve her istekte kimlik
korumasından geçer; korumalı alanlar reddedilir. Register veya herhangi bir alanı
`readAction` olarak `clear`, `set`, `modify` veya `modifyExternal` belirtiyorsa,
profil ayrıca listelemese bile okuma reddedilir. `poke` adla yazmaz; pin tarifleri adlandırılmış
biçimi kullanabilir. OpenOCD ve seri
bağlantı aynı okuma yolunu kullanır. Host testleri gerçek kart kanıtı değildir.

## RAM parçası

`ram build` (profil `ram_build.argv`, shell yok) → `ram load` (yalnız `scratch` içine, proje
kökü altından, geri okuyup doğrulayarak; SHA-256 ana makinede kaydedilir) → `ram run`
(yalnız yüklenen parçanın içindeki giriş, en çok 4 argüman, `--timeout`). `ram load` yazmaya
başlamadan önceki kaydı siler; `ram run` çağırmadan önce scratch'i yeniden okuyup SHA-256'yı kayıtla
karşılaştırır, reset veya yarım yükleme sonrası çalıştırmaz. Çağrı
mailbox üzerinden yapılır; CPU halt edilmez. Zaman aşımında kod hâlâ çalışıyor olabilir,
**tekrar denenmez**; durdurmak için `control halt`/`reset-halt`. Parça, stub'ın yığınını
kullanır; scratch'e göre konumdan bağımsız olmalı veya scratch adresine bağlanmalıdır.

## Güvenlik katmanları

1. **Pin politikası** (ana makine): izin listesi, korumalı pin, girdi sınırları.
2. **Bellek politikası** (ana makine): `write_ranges`, `protected_ranges`, `side_effect_ranges`, hizalama.
3. **UID koruması**: her okuma/yazma aynı Tcl isteğinde kimliği yeniden doğrular.
4. **Dead-man** (stub): heartbeat susarsa güvenli durum tablosu oynatılır (tek sefer, sayaçla kayıtlı).
5. **Fault yakalayıcı** (stub portu): HardFault `eat_stub_fault` ile güvenli durumu uygular; yalnız
   tablo kuruluyken (`armed=1`). Boş tablo kurulurken ana makine `safe_count=0` yazar.
6. **Fiziksel**: sigorta, akım sınırı, yük tarafı korumalar sizin sorumluluğunuzdadır; yazılım bunların yerini tutmaz.

Dead-man veya stub reset sonrası: sonraki `pin apply` uyarı döndürür ve mevcut talepleri
`stale_after_deadman` işaretler. Dead-man, stub sayacının ana makine kaydından farklı
olmasıyla; reset ise kurulu talepler varken mailbox'ta `armed=0` görülmesiyle anlaşılır
(stub açılışta mailbox'ı sıfırlar). Dead-man kapalıysa (`deadman: false`) reset bu yolla
anlaşılamaz. Tarifteki `delay_ms`/`poll` adımlarından önce ve sonra heartbeat yazılır.
Bir `ram run` çağrısı sürerken stub döngüsü durduğu için dead-man **çalışmaz**; RAM
parçasının kendisi güvenilir olmalıdır (watchdog ve fault yakalayıcı bunu sınırlar).

## Bilinen sınırlar

- Yol haritası: [hedefte canlı program yorumlayıcısı tasarımı (F4.1)](interpreter-design.md) — öneri; henüz uygulanmadı.
- SWD erişimi erişim başına yaklaşık 0,1–1 ms'dir; gerçek zamanlı kontrol döngüsü değildir.
  Çevre birimini kurup bırakmak veya küçük RAM parçası kullanmak gerekir.
- Oku-değiştir-yaz tek Tcl isteğindedir ama çalışan çekirdek aynı register'ı değiştiriyorsa
  yarışabilir. Hedefte atomik set/clear register'ı varsa tarif onu `verify: false` tam genişlik
  yazmayla kullanmalıdır (bkz. [lessons.md](lessons.md)). Stub boştayken bu risk yoktur.
- Pin durumu `pin list` ile **donanımdan okunmaz**, ana makine kaydıdır.
- Seri bağlantı ana döngüden işlendiği için uygulama döngüsü uzun bloklarsa yanıt gecikir; ana makine
  zaman aşımında bağlantıyı kapatır.
- Çok çekirdekli hedeflerde hangi çekirdeğin hedeflendiği OpenOCD config'ine bağlıdır.
- `*.pins.local.json` talep kaydı profilin yanında tutulur ve git dışıdır; başka karta ait ise yüklenmez.
