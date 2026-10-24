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
