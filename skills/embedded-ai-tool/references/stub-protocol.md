# Stub mailbox protokolü (sürüm 1)

Normatif kaynaklar: [../stub/eat_stub_core.h](../stub/eat_stub_core.h) (stub) ve
`scripts/embedded_ai_tool/live.py` (`WORD` tablosu). `tests/test_stub.py`, ikisinin aynı
olduğunu her çalıştırmada denetler.

Mailbox, hedef RAM'inde hizalı 32 bit kelimelerden oluşur. Her kelimeyi **tek taraf yazar**.

| Kelime | Ad | Yazan | Anlam |
|---|---|---|---|
| 0 | `magic` | stub | `0x53544145`; başlatmanın son adımı |
| 1 | `version` | stub | Protokol sürümü (1) |
| 2 | `stub_hb` | stub | Her `poll` çağrısında artar; canlılık kanıtı |
| 3 | `host_hb` | ana makine | Her heartbeat'te artar |
| 4 | `call_seq` | ana makine | Yeni çağrı numarası; **en son** yazılır |
| 5 | `done_seq` | stub | Biten çağrı numarası; **en son** yazılır |
| 6 | `status` | stub | 0 idle, 1 busy, 2 ok, 3 fault, 4 deadman |
| 7 | `entry` | ana makine | Çağrılacak adres (profildeki `live.entry_or` mimari bitleri uygulanmış) |
| 8–11 | `args[4]` | ana makine | Argümanlar |
| 12 | `result` | stub | Çağrının 32 bit dönüş değeri |
| 13 | `error` | stub | Fault kodu |
| 14 | `armed` | ana makine | 1 ise dead-man etkin |
| 15 | `timeout_ms` | ana makine | Dead-man süresi |
| 16 | `safe_count` | ana makine | Güvenli durum satır sayısı |
| 17 | `deadman_count` | stub | Dead-man tetiklenme sayısı (reset'te sıfırlanır) |
| 18… | güvenli durum satırları | ana makine | Satır başına 4 kelime: `adres, genişlik_bit, maske, değer` |

Satır kapasitesi `(mailbox_kelime - 18) / 4`. Stub `safe_count` değerini kapasiteye kırpar.

## Kurallar

- **Canlılık:** Ana makine `magic`, `version` ve `stub_hb` ilerlemesini görmeden pin veya RAM çağrısı yapmaz.
- **Çağrı:** Ana makine `entry` + `args` yazar, sonra `call_seq = önceki + 1` yazar. Stub farkı görünce
  `status=busy`, çağrıyı yapar, `result`, `error=0`, `status=ok` yazar ve **en son** `done_seq = call_seq` yazar.
  Ana makine yalnız `done_seq == call_seq` iken sonuca bakar. Tek çağrı yürür; yenisi bitmeden başlatılmaz.
- **Dead-man:** `armed=1` iken `host_hb` `timeout_ms` boyunca değişmezse stub satırları sırayla
  `reg = (reg & ~maske) | (değer & maske)` ile uygular, `deadman_count++`, `status=deadman` yapar ve
  tekrar tetiklenmez. `host_hb` değişince `status` idle olur ve sayaç yeniden işler. Arm edildiği an
  geri sayım yeniden başlar.
- **Yeniden kurma:** Ana makine tabloyu değiştirirken önce `armed=0`, sonra satırlar + `timeout_ms` +
  `safe_count`, bir heartbeat, en son `armed=1` yazar. Ana makine pin yazmadan **önce** tabloyu kurar.
- **Boş tablo:** Ana makine tabloyu boşaltırken `armed=0` ardından `safe_count=0` yazar.
- **Fault:** Fault yakalayıcı `eat_stub_fault(kod)` çağırır: güvenli durum **yalnız `armed=1` iken** uygulanır
  (kapalı tablo bayat veya yarım yazılmış olabilir), `error=kod`,
  `status=fault`, `done_seq=call_seq`. Normal akışa dönmez (reset veya sonsuz döngü).
- **Bayat talep:** Ana makine, kaydettiği `deadman_count` ile okuduğunu karşılaştırır; fark varsa
  talepler `stale_after_deadman` olur.

## Seri bağlantı (sürüm 1)

Debug probu olmayan veya OpenOCD'nin desteklemediği hedefler için aynı bellek işlemleri bir bayt
akışı (UART, USB CDC…) üzerinden yapılır. Normatif kaynaklar:
[../stub/eat_link.h](../stub/eat_link.h) ve `scripts/embedded_ai_tool/link.py`; `tests/test_link.py`
ikisinin aynı olduğunu denetler ve Python istemcisini gerçek C koduna karşı çalıştırır.

Çerçeve (iki yön; çok baytlı alanlar hedefin bayt sırasından bağımsız olarak **little-endian**):

```text
0xEA 0x7E | uzunluk u16 | veri[uzunluk] | crc16 u16     (CRC-16/CCITT-FALSE, uzunluk+veri üzerinden)
İstek verisi : sıra u8 | komut u8 | koruma_adresi u32 | koruma_uzunluğu u8 | koruma baytları | argümanlar
Yanıt verisi : sıra u8 | durum u8 | veri
```

| Komut | Argümanlar | Yanıt |
|---|---|---|
| `0x01 INFO` | — | protokol u8, azami veri u16, mailbox adresi u32, mailbox kelime sayısı u32 |
| `0x02 READ` | adres u32, genişlik u8 (8/16/32), adet u16 | değerler (genişlik/8 bayt) |
| `0x03 WRITE` | adres u32, genişlik u8, adet u16, değerler | — |
| `0x04 MODIFY` | adres u32, genişlik u8, maske u32, değer u32 | önceki değer u32 |
| `0x05 INCREMENT_IF` | kontrol adresi u32, beklenen u32, adres u32 | yapıldı u8 |

Durum: 0 ok, 1 hatalı istek, 2 kimlik uyuşmuyor, 3 bilinmeyen komut, 4 hizasız/geçersiz genişlik.

- **Kimlik:** Stub, koruma baytlarını koruma adresindeki baytlarla karşılaştırmadan hiçbir komutu
  çalıştırmaz (OpenOCD yolundaki her Tcl isteğindeki UID korumasının karşılığı). Ana makine profildeki
  `identity` alanını her isteğe koyar.
- **Bozuk çerçeve:** CRC'si tutmayan çerçeve yanıtsız kalır; `EAT_LINK_BYTE_TIMEOUT_MS` (100 ms)
  boyunca yarım kalan çerçeve atılır. Ana makine zaman aşımında veya bozuk yanıtta bağlantıyı kapatır ve
  **tekrar denemez** (yazma sonucu belirsiz).
- **Boyut:** Stub `EAT_LINK_MAX_PAYLOAD` (varsayılan 1024) değerini INFO ile bildirir; ana makine büyük
  okuma/yazmayı buna göre böler.
- **Bağlam:** `eat_link_rx()` ana döngüden (veya `eat_stub_poll()` ile aynı görevden) çağrılır; böylece
  MODIFY ve INCREMENT_IF stub'a göre atomiktir.

## Port gereksinimleri

Bkz. [stub/README.md](../stub/README.md): `eat_embed` ile mevcut firmware'e ekleme veya kendi
`eat_hal` / `eat_link_port` yapın, fault/trap bağlantısı, mailbox'ın ELF sembolüyle bulunması.

## Örnekleyici

`eat_sampler.{h,c}` mailbox'tan bağımsız sürüm 1 kullanır; mailbox düzeni değişmez.
`eat_embed` için `EAT_SAMPLER_SLOTS=0` kapalıdır; etkinleştirmek için 1..65536 arasında
ikinin kuvveti seçilir ve `eat_sampler.c` derlemeye eklenir. ELF'teki `eat_samples`
32 bit kelime dizisi `59 + 10 * EAT_SAMPLER_SLOTS` kelimedir (örneğin 64 yuva: 2796 bayt).
Profilde `live.samples` zorunludur: `{"symbol": "eat_samples"}` adresi ve boyutu
`live.mailbox` gibi profildeki `artifact` ELF'inden çözer; alternatif olarak
`{"address": "0x20001000", "size": 2796}` verilebilir (kurgusal adres, 64 yuva).
Örnekleyici yalnız çözülmüş `live.samples` alanını kullanır; ayrı ELF araması yapmaz.
Bu RAM okunabilir fakat `write_ranges` kapsasa bile `poke` ve pin tarifleriyle
yazılamaz; yalnız örnekleyici protokolü kendi host alanlarına yazar.

| Kelime | Alan | Yazan |
|---|---|---|
| 0 | magic `0x504D5345`, başlatmada en son | hedef |
| 1..3 | sürüm 1, yuva sayısı, azami kanal sayısı 8 | hedef |
| 4..5 | kanal sayısı, istenen dönem (ms) | host |
| 6 | write: yayımlanan kayıt sayacı | hedef |
| 7 | read: serbest bırakılan kayıt sayacı | host |
| 8 | overrun: dolu halkaya düşen örnek sayısı | hedef |
| 9..10 | hedef zamanı (ms; örnek veya durma anı), son örnek girişiminin sıra numarası | hedef |
| 11 | enable: 0 durdur, 1 başlat | host |
| 12 | state: 0 durdu, 1 çalışıyor, 2 yapılandırma reddedildi | hedef |
| 13 | izin tablosu satır sayısı (0..8) | host |
| 14 | epoch: tutarlı başlık sayacı | hedef |
| 15 | error: 0 başarılı, 1 geçersiz yapılandırma | hedef |
| 16..18 | başlangıç hedef zamanı, sıra, overrun (çalışma boyunca sabit) | hedef |
| 19..34 | 8 izin satırı: adres, genişlik (8/16/32 bit) | host |
| 35..58 | 8 kanal: tür, adres/kanal kimliği, genişlik | host |
| 59.. | yuva başına 10 kelime: sıra, hedef zamanı, 8 kanal değeri | hedef |

Bütün kelimeler hedefin bayt sırasındadır; her kelimeyi çalışma sırasında yalnız tabloda
belirtilen taraf yazar. Başlangıçta diziyi sıfırlayan hedef henüz host'a açılmamıştır.
Kanal türü 0 bellek kelimesidir: hizalama, genişlik ve izin tablosundaki **adres/genişlik
eşleşmesi** kontrol edilir. Tür 1 portun `read_channel(channel_id)` kancasını çağırır.
Port kimliklerini yalnız güvenilir firmware belirler; CLI/MCP yalnız bellek kanalı açar.
Host her kanalın tüm baytlarını `read_ranges` içinde arar ve `side_effect_ranges` ile
örtüşmeyi reddeder. İzin tablosu kötü niyetli bir host'a karşı donanım koruması değildir.

Host önce `enable=0` yazar, `state=0` onayını bekler; ancak sonra tabloları, sayıları ve
dönemi yazar. Son işlem `enable=1` olur. Hedef yapılandırmayı özel belleğine kopyalar ve
tamamını doğrulamadan hiçbir kanal okumaz. Çalışırken yapılandırma değiştirilemez.
Başlatma zamanını hedef kaydeder; ilk örnek en erken bir dönem sonra gelir.
Durdurma onayı yoksa host tabloyu değiştirmez. Tek host tüketici ve yeniden girişsiz tek
üretici vardır; birden fazla istemcinin erişimi uygulamada dışarıdan sıraya konmalıdır.

Hedef önce yuva verisini, en son `write` sayacını yayımlar. Host yayımlanmış yuvaları
en fazla iki toplu okumayla alır; tüm okuma başarılı olduktan sonra `read` yayımlar.
Sayaçlar 32 bit modülerdir; yuva `sayaç & (yuva_sayısı-1)` ile seçilir. Halka dolunca
**yeni örnek düşer**; üretici `read` yazmaz ve tüketicinin okuduğu kayıt değişmez.
Her örnek girişiminde sıra ve hedef zamanı, dolulukta ayrıca overrun ilerler. Geciken
tick için geçmiş örnekler üretilmez. Kanallar art arda okunur, eşzamanlı ADC ölçümü değildir.
Durdurma onayında hedef zamanı son kez güncellenir ve durduğu sürece sabit kalır;
son örnekten sonra geçen bekleme süresi de hız hesabına katılır.

Üretici başlık değişimini `epoch` tek sayı, bariyer, alanlar, bariyer, çift sayı sırasıyla
yapar. Host önce epoch, sonra başlık, sonra yeniden epoch okur; üç değer aynı ve çift
olmalıdır. `eat_sampler_port.barrier` RAM yayınlama/edinme sırasını ve gerekiyorsa cache
bakımını sağlar. NULL yalnız güçlü sıralı, prob/seri erişimiyle tutarlı RAM için geçerlidir.
Port hizalı 32 bit erişimlerin atomik olduğunu sağlamalıdır; C99 `volatile` tek başına
cache veya zayıf bellek sıralamasını çözmez. Dizi gerekirse cache dışı RAM'e yerleştirilir.
Boşaltma yalnız atomik `write` sayacına ihtiyaç duyar; hareketli sıra/zaman çiftini
okumaz. Başlangıç değerleri `state=1` görülünce sabit 16..18 alanlarından, bitiş değerleri
`state=0` onayından sonra alınır. Böylece prob okumalarından hızlı örnekleme, tutarlı
başlık okumayı sürekli yeniden denemeye zorlamaz.

Port `eat_sampler_tick(now_ms)` fonksiyonunu **ya** periyodik timer kesmesinden **ya da**
sabit tick ile ana döngüden çağırır; iki bağlam birlikte kullanılmaz. Timer kesmesi daha
az jitter sağlar; kanal kancaları kısa, bloklamayan ve kesme güvenli olmalıdır. Ana döngü
kesme yükünü azaltır fakat uzun uygulama/seri işleri örneklemeyi geciktirir. Dönem ms
cinsindedir; alt milisaniye örnekleme bu sürümde yoktur. `eat_embed_init` yalnız başlatır,
tick zamanlamasını uygulama sağlar. Özel port için `eat_sampler_init` kullanılabilir.
Gelecekteki üretici aynı bağlamdan `eat_sampler_push(now_ms, values, count)` çağırır;
tick ile yapılandırma onayı sürer, ancak aynı anda tick örnekleri üretilmemelidir.

`eat measure --channel 0x20000800:32 --period-ms 2 --duration 1 --threshold 100`
örneğinde adres kurgusaldır. Komut ve MCP `measure` yalnız örnekleyici yapılandırma alanına
yazar; `readOnlyHint=false` bu nedenle kullanılır, ayrıca `--execute` gerekmez.
ELF SHA256 kontrolü ve taşımanın her istekteki kimlik koruması geçerlidir.
`channels` MCP dizisi aynı `adres[:genişlik]` metinlerini alır; eşikler kanal sırasındadır.
MCP `duration` üst sınırı **60 saniyedir**; 61 saniye gibi değerler MCP argüman
denetiminde, bağlantı kurulmadan reddedilir. CLI'nin 24 saat sınırı değişmez.

Host başlangıç ve bitişte hedef sıra/zamanını tutarlı okur:
`rate_hz = sıra_farkı * 1000 / hedef_ms_farkı`. İstenen dönemden hız hesaplanmaz;
hedef zaman farkı sıfırsa hız `null` olur. Bu hız saklanan kayıtları değil örnek girişimlerini
ölçer. `count` alınan kayıt sayısıdır; `loss` overrun, sıra boşlukları ve kuyruk kayıplarını
çift saymadan içerir. Min/max/ortalama yalnız alınan kayıtlara aittir. Eşik geçişleri
ardışık sıra numaraları arasında sayılır; kayıp aralığı boyunca geçiş tahmin edilmez.
Host süresi yalnız toplama penceresini sınırlar. Ölçüm 24 saatle sınırlıdır; bu aralıkta
sıra ve ms sayaçları en fazla bir kez sarar. Hedef reseti veya başka üreticiyle eşzamanlı
yapılandırma desteklenmez; yeni oturum başlatılmalıdır. Kart üzerinde doğrulama yapılmadı.
