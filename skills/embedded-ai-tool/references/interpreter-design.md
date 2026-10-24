# Hedefte canlı program yorumlayıcısı — F4.1 tasarımı

Durum: öneri; çalışan özellik veya donanım uyumluluğu iddiası değildir.
Kapsam: stub içine eklenecek C99 bytecode yorumlayıcısı ve host sözleşmesi.
Mevcut davranış: [live-control.md](live-control.md), kelime sahipliği:
[stub-protocol.md](stub-protocol.md), port: [stub/README.md](../stub/README.md).
Buradaki önerilen sürümler mevcut sürüm 1 kaynaklarının yerine geçmez.

## 1. Problem ve sınırlar

Bugün host register tariflerini çalıştırabilir veya RAM'de yerel kod çağırabilir.
Sohbetten örnek alıp eşik kararı vermek bağlantı gecikmesine bağlıdır; uzun yerel
çağrı `eat_stub_poll()` ve dolayısıyla dead-man denetimini durdurabilir.
Amaç: örnekleme, eşik, süre ve olay kararını hedefte tutup programı RAM'de değiştirmek.
Her değişiklikte C derleme ve flash yazma yoktur; yorumlayıcının ilk kurulumu gerekir.

| Dahil | Kapsam dışı |
|---|---|
| Küçük görevler, GPIO/ADC/PWM, olay, süre, parametre | Genel amaçlı dil, dosya sistemi, ağ yığını |
| Atomik görev kümesi değişikliği, sürüm geri okuma | Debugger, breakpoint, adımlama |
| Hedefte izin denetimi ve güvenli duruma geçiş | Düşmanca host'a karşı donanımsal izolasyon |
| Ölçülebilir gecikme sınırı, donanım timerı | Her MCU'da sabit çevrim veya sert gerçek zaman garantisi |
| İki taşımada aynı program | Çalışan uygulama firmware'inin otomatik taşınması |

## 2. Çekirdek, kapasite ve bellek bütçesi

Çekirdek yalnız `stdint.h` kullanan, sabit kapasiteli C99 olacaktır; heap, recursion,
VLA, kayan nokta, işletim sistemi, register işaretçisi veya mimari assembly içermez.
Bellek entegrasyonda ayrılır; donanım işleri yalnız port kancalarına gider.
Serileştirme C struct yerleşimine dayanmaz; alanlar açık bayt işlemleriyle çözülür.
Aralık denetimi taşmasızdır: `offset <= size && length <= size-offset`.

Aşağıdakiler **ölçülmemiş üst bütçe hedefleridir**; uygulamada linker map ve stack
ölçümü gerekir. KiB=1024 B; kapasite aşımı kırpılmaz, reddedilir.

| Parça | Standart yapılandırma | Küçük yapılandırma |
|---|---|---|
| Yorumlayıcı + doğrulayıcı flash | ≤12 KiB | ≤8 KiB |
| Mevcut stub dahil toplam çekirdek flash | ≤16 KiB | ≤12 KiB |
| Sabit özel RAM (aktif tablolar dahil) | ≤1536 B | ≤768 B |
| Görev başına çalışma RAM'i | 160 B | 112 B |
| Görev sayısı T | 4 | 2 |
| Banka başına program kapasitesi P | 2048 B | 768 B |
| İki program bankası | 4096 B | 1536 B |
| Mailbox kontrol başlığı | 256 B | 256 B |
| Ölçüm halkası: 32 B başlık + N*32 | N=32: 1056 B | N=8: 288 B |
| Giriş olay kuyruğu Q*16 | Q=16: 256 B | Q=4: 64 B |
| Yetkinlik raporu sabit alanı | 256 B | 256 B |
| Ortak C stack için ayrılan üst sınır | 512 B | 384 B |
| Toplam ayrılan RAM hedefi | 8608 B | 3776 B |

Toplam: `sabit + T*görev + 2P + 256 + 32 + 32N + 16Q + 256 + stack`.
Bankalar kod, sabit, görev şeması, izin ve safe tablolarını içerir.
Standart özel RAM'in 1024 B'ı aktif allow (16*48 B) ve safe (16*16 B)
tablolarına; küçük bütçenin 512 B'ı sekizer satıra ayrılır. Kalanı yönetim durumudur.
Görev RAM'i standartta 16 değişken, 8 geçici register, 2 timer ve yürütme durumudur;
küçükte 8 değişken vardır. Şema metinleri hedefte tutulmaz; sayısal kimlik kullanılır.
Özel yönetim RAM'ine en fazla 8 u32 aktif parametre ve küçük göç çalışma alanı dahildir;
PARAM_SET mühürlü bankayı değiştirmez, bu parametre gölgesini günceller.
Seri çerçeve tamponları, sürücüler, port kodu/stack'i, DMA ve yerel RAM kodu bu
toplamlara dahil değildir; hedef raporunda ayrıca eklenir.
Mevcut `EAT_MAILBOX_WORDS=64` yalnız yeni kontrol başlığına yeter; büyütülmelidir.

| Derleme seçeneği (öneri) | Kapatıldığında / küçültüldüğünde |
|---|---|
| `EAT_INTERP_ENABLE=0` | Mevcut sürüm 1 stub, yorumlayıcı yok |
| `EAT_INTERP_ADC/PWM/IRQ/NATIVE=0` | İlgili opcode/kanca/yetkinlik kaldırılır |
| `EAT_INTERP_DIV=0` | Bölme/mod ve yazılımsal yardımcıları kaldırılır |
| `EAT_INTERP_TASKS/VARS/TIMERS` | Görev/değişken/timer kapasitesi küçülür |
| `EAT_INTERP_IMAGE_BYTES/ALLOW_ROWS/SAFE_ROWS` | Banka ve özel tablolar küçülür |
| `EAT_INTERP_RING_RECORDS/EVENTS` | Ölçüm ve giriş kuyruğu küçülür |

Küçük yapılandırmada PWM, IRQ, native ve bölme kapalı; ADC, timer, eşik açıktır.
Halka sıfırlanarak ölçüm kaldırılabilir; yetkinlik raporu bunu bildirir.

## 3. Yürütme modeli ve zamanlama

| Nesne | Sözleşme |
|---|---|
| Program | Kimlikli görevler, parametreler, kaynak sahipleri, allow/safe |
| Görev | Tek PC, özel değişken/timer; READY/WAITING/STOPPED/FAULT |
| Başlatma | Giriş PC'sinden; görevler arası çağrı/paylaşılan değişken yok |
| Olay | `pin_change`, `timer`, `threshold`, `message`: kaynak/değer/zaman |
| Giriş kuyruğu | Sonlu FIFO; ISR yalnız yakalar, yorumlayıcı görev bağlamındadır |
| Zaman | Monotonik u32 ms; süre 1..2^31-1, fark unsigned; poll arası <2^31 ms |
| Eşik | Periyodik ADC okuma, iki eşikli histerezis; yükseliş başına tek olay |
| Mesaj | İzinli kimlik ve u32 veri; komut en fazla bir olay ekler |
| Periyodik görev | Mutlak timer takvimi; gecikmiş çevrimler birleştirilir |

Her `eat_stub_poll()` için önerilen sıra:

1. `stub_hb` ilerlet; heartbeat/dead-man ve fault mandalını denetle.
2. Sınırlı link/komut ve olay aktar; doğrulama işinden sınırlı parça işle.
3. Commit varsa güvenli noktada değerlendir; geçiş bitmediyse görev yürütme.
4. Tick geldiyse round-robin görevleri çalıştır; poll başına en fazla bir tick.
5. Durumu yayımla, uygulamaya dön; watchdog'u uygulama kendi politikasında besler.

Varsayılan tick 1 ms, toplam B=64 komut maliyet birimi, görev dilimi b=16;
round-robin başlangıcı sonraki tick'e taşınır. Sınırsız tick telafisi yoktur.
Her opcode en az bir birim; donanım/native çağrısı bildirilen WCET maliyeti kadar
önceden ücretlenir. Kalan bütçeye sığmayan işlem başlamaz; tek maliyet >b ise ret.
Geri dallanma mümkündür; `WAIT`, `DELAY`, `YIELD` veya `END` olmadan dilimini bitiren
görev `BUDGET_EXCEEDED` üretir. İlk ihlalde bütün program durur, safe uygulanır;
sonsuz döngü sonraki tick'te otomatik sürdürülmez. Açık `YIELD` PC'yi korur.
Yalnız toplam B bittiği için ertelenen görev ihlal sayılmaz; görev diliminin
tükenmesi ile toplam tick bütçesinin tükenmesi ayrı sayaçlarla izlenir.

Poll sınırı: yönetim + B*Cmax + sınırlı olay aktarımı; port her terime WCET verir.
CRC/doğrulama poll başına en fazla 64 bayt/8 tanım işler. Aktivasyonda kopyalama ve
kaynak geçişi sabit kapasiteyle sınırlıdır. Seri RX dış döngüsü de bayt bütçeli olmalı;
sınırsız `while (uart_has_byte())` poll'u aç bırakmamalıdır.
Kancalar busy-wait yapamaz; ADC dönüşümü ve periferal hazırlığı bölünür.

ISR yalnız zaman/olay kaydeder; pin yazmaz, bytecode çalıştırmaz.
Olay, kaynak eşleşen bekleyen görevleri bir kez uyandırır; görev olay yükünü alır.
Bir görev uyandıktan sonraki olaylarda bekleyen sayılmaz. Beklemiyorken abonelik
yoktur; kaçmaması gereken kenar için port sayacı/F3 yakalaması gerekir.
IRQ fırtınasında giriş kuyruğu taşarsa `EVENT_OVERFLOW` ile program safe olur.
Ölçüm halkasının dolması ayrı, kayıplı bir durumdur.

Deadline doğruluğu: tick çözünürlüğü + azami poll boşluğu + görev kuyruğu + kanca WCET'i.
PWM kenarları donanım timerında; hızlı örnekleme F3/DMA portunda olur.
Güvenlik açısından bu gecikmeye sığmayan iş host doğrulamasında reddedilir.

## 4. Bytecode biçimi ve komut kümesi

Sabit 8 B komut: `op:u8, a:u8, b:u8, c:u8, k:u32 little-endian`.
Değişken uzunluğa göre daha çok RAM kullanır; doğrulama, PC sınırı ve maliyet hesabı
basittir. Dallar bayt adresine değil komut indeksine gider. Kullanılmayan alanlar
sıfırdır; bilinmeyen opcode ve ayrılmış bitler reddedilir.
`r` geçici u32 register, `v` görev değişkeni, `p` salt okunur parametre, `h` allow
satırı, `t` timer, `k` sabit/indeks. Adres aritmetiği ve keyfi yükle/sakla yoktur.

| Opcode | Operantlar (alanlar) | Etki | Güvenlik kontrolü |
|---|---|---|---|
| `00 NOP` | — | İlerle | PC/bütçe |
| `01 CONST` | a=r,k=değer | r[a]=k | Register indeksi |
| `02 MOV` | a=dst,b=src | Kopyala | İki indeks |
| `03 LOAD_VAR` | a=r,k=v | Değişken oku | Göreve ait slot |
| `04 STORE_VAR` | a=r,k=v | Değişken yaz | Slot, tip/sınır |
| `05 LOAD_PARAM` | a=r,k=p | Parametre oku | Parametre indeksi |
| `06 ADD` | a=dst,b=x,c=y | u32 mod 2^32 toplam | İndeksler |
| `07 SUB` | a=dst,b=x,c=y | u32 mod 2^32 fark | İndeksler |
| `08 MUL` | a=dst,b=x,c=y | Alt 32 bit çarpım | İndeksler |
| `09 DIV` | a=dst,b=x,c=y | Unsigned bölüm | Özellik, sıfır bölen |
| `0A MOD` | a=dst,b=x,c=y | Unsigned kalan | Özellik, sıfır bölen |
| `0B BIT` | a=dst,b=x,c=y,k=işlem | AND/OR/XOR/SHL/SHR | İşlem 0..4; kaydırma <32 |
| `10 CMP` | a=dst,b=x,c=y,k=koşul | EQ/NE/LT/LE/GT/GE, u32 0/1 | Koşul 0..5, indeksler |
| `11 BR_TRUE` | a=r,k=PC | r[a]!=0 ise dallan | Aynı görev kod sınırı |
| `12 JUMP` | k=PC | Koşulsuz dallan | Aynı görev, bütçe |
| `20 GPIO_READ` | a=dst,k=h | Seviyeyi oku | Allow pin/GPIO giriş |
| `21 GPIO_WRITE` | a=değer,k=h | Çıkış ayarla | Allow pin/çıkış, 0/1, sahip |
| `22 GPIO_MODE` | k=h | Önceden tanımlı modu seç | Allow işlev, kaynak, safe |
| `23 ADC_START` | k=h | Dönüşüm başlat | Allow kanal/hız/sahip |
| `24 ADC_READ` | a=dst,b=hazır,k=h | Sonuç/hazır bitini oku | Allow ADC; bloklama yok |
| `25 PWM_SET` | a=duty,b=freq,k=h | PWM güncelle | Allow pin/kanal, iki değer sınırı |
| `26 IRQ_BIND` | k=h | Manifestteki kenar aboneliğini aç | Allow pin/kenar, sahip |
| `30 TIMER_SET` | a=süre,k=t | now+süre, tek atım | Slot, süre sınırı |
| `31 WAIT_TIMER` | k=t | Dolana kadar WAITING | Kurulu timer, bloklama yok |
| `32 DELAY` | a=süre,k=t | Kur ve bekle | Süre/slot; PC sonraki komut |
| `33 WAIT_EVENT` | a=değer,b=zaman,k=abonelik | Eşleşen olayı bekle | Manifest/allow kaynak eşleşmesi |
| `34 YIELD` | — | Sonraki tick'e bırak | Bütçe tüketir |
| `40 EMIT` | a=değer,b=aux,k=kanal | Ortak halkaya kayıt | İzinli kanal/hız |
| `41 NATIVE_CALL` | a=dst,b=ilk_arg,c=adet,k=h | İzinli yerel RAM işlevi | Allow giriş/hash/ABI, argüman, WCET |
| `7F END` | — | Görevi durdur | Sahip çıktıları safe yap |

Opcode sütunu onaltılıktır. Belirtilmeyen alan sıfırdır; her indekse çalışma
zamanında bakılır. Signed taşma kullanılmaz; ilk sürüm sayıları u32 yorumlar.
Negatif fiziksel birimler için host ofset/ölçek seçer; ölçek şemada yer alır.
Aritmetik sarma serbest olsa da donanım yazısında son değer yeniden denetlenir.
Sıfıra bölme, geçersiz timer/PC/indeks bütün programı safe yapar.
EMIT kanal manifesti kayıt türünü belirler; threshold türünde aynı kayıt sonlu
giriş kuyruğuna da gönderilir. Böylece CMP ile algılanan eşik başka görevin
WAIT_EVENT aboneliğini hedefte uyandırabilir; kuyruk taşması kontrol hatasıdır.

`GPIO_MODE`/`IRQ_BIND` yalnız manifestte rezerve edilmiş uyumlu modlar arasında
geçer; kaynak/pin değişimi yeni aktivasyon ister. Önce çıkış safe, sonra eski
abonelik kapalı, sonra port yapılandırmasıdır. Kanca `PENDING` dönerse görev bekler;
hazır olmadan sonraki donanım komutu çalışmaz. Deadline aşımında iptal/safe uygulanır.

`NATIVE_CALL` en çok dört ardışık register argümanı alır; pointer argümanı yoktur.
Yerel kod genel sandbox değildir: yalnız incelenmiş, sabit süreli, adres/hash'i
kilitli ve donanım işlerini aynı izin denetimli porttan yapan işlev kabul edilir.
ABI/mimari çağrı bitleri portta kalır; bytecode ham giriş adresi içermez.
Native görüntü host'ta SHA-256, hedefte manifest CRC32 ile doğrulanır; kayıtlı bölge
program boyunca kilitlenir. Her çağrıda izin/ABI/sahip ve argüman sınırı denetlenir.
Süre sınırını yazılımla kesmek mümkün değildir; ihlalde watchdog gerekir.
WCET kanıtı olmayan işlev ret; native varsayılan kapalıdır. Program aktifken ham
`ram run` ve aktif yerel kod bölgesine `ram load` reddedilir.

## 5. Çift izin denetimi ve dead-man

| Katman | Zorunlu kontrol |
|---|---|
| Host derleyici | Profil pin/işlev/limits, protected, read/write/side-effect ranges |
| Kaynak planı | Debug/taşıma pinleri, timer/kanal/IRQ ve uygulama sahipleri |
| Yükleme doğrulayıcısı | Kod, allow, safe, kaynaklar, yetkinlik tutarlılığı |
| Yorumlayıcı | Her donanım işleminden hemen önce aktif allow ve sahiplik |
| Port | Sabit koruma zarfı: pin/işlev/adres/maske ve kanca süreleri |

Host allow tablosunu mailbox içindeki aday bankaya yazar; doğrulamadan sonra stub
aktif tabloyu özel RAM'e kopyalar. Satır 12 u32/48 B:
`id, kind, resource, function, start, length, width, mask, min0, max0, min1, max1`.
Kind GPIO/ADC/PWM/IRQ/native/sample'dır; birimler kind ile sabittir. Kaynak kimliği
port kataloğuna gider; kod register adresi üretmez. Portun bilinen tarifindeki her
erişime genişlik/maske/alan sonu/yan etki kontrolü uygulanır; farklı registerlar için
birden çok satır gerekir. Native bölgesi ve manifest hash/ABI/argüman şeması birlikte
doğrulanır. Allow olmayan okuma da ret; protected zarf satırla genişletilemez.

Safe satırı mevcut dört kelimedir: `adres, genişlik, maske, değer`.
Port zarfına göre doğrulanır; yan etkili/yalnız yazma registerda maskeli okuma yerine
portun kör tam yazma tarifi gerekir. Safe bounded/idempotenttir; önce IRQ/DMA/PWM
üreticilerini durduran kanca çalışır. Fault/trap son doğrulanmış özel kopyayı kullanır.

Yorumlayıcıda dead-man zorunludur; `deadman:false` ile program kabul edilmez.
Aktif safe kopyası upload sırasında disarm edilmez. Mevcut v1 `arm()` yolu çalışan
programa uygulanamaz; v2 host ayrı komut yolunu kullanır. İlk donanım yazısından
önce safe kopyası ve süre sayacı kurulmuş olmalıdır.

Heartbeat dolunca: görevleri durdur → IRQ/ADC/PWM üreticilerini iptal et → aktif
safe tablosunu uygula → deadman_count artır → `STOPPED_DEADMAN` mandalla.
Heartbeat geri gelişi programı başlatmaz. Host kimlik/durumu yeniden okuyup açık
aktivasyon yapar. Fault/bütçe/izin/port hatası aynı yolu ayrı nedenle kullanır.
Safe gecikme sınırı: timeout + azami poll boşluğu + port safe WCET'i.
CPU kilitlenmesinde bağımsız watchdog/reset güvenli başlangıç politikasını uygular.
Bu, mevcut güvenilir host modeline ek kontroldür; debug/genel seri WRITE ile
saldıran host'a karşı izolasyon veya CRC ile kimlik doğrulama iddiası yoktur.

## 6. Canlı değişiklik ve durum göçü

Her düzenleme yeni program görüntüsüdür; görev ekle/sil aynı transaction'ı kullanır.
İki bankayla eski program upload/doğrulama boyunca çalışır. Commit karşılaştırmalı
değişimdir: `expected_generation` gerekir; tek yazıcı oturumu vardır.

| Durum | Sonraki adım / görünürlük |
|---|---|
| EMPTY/ACTIVE | BEGIN boş bankayı kiralar; aktif bankaya yazılamaz |
| RECEIVING | Sıralı chunk; eski program çalışır |
| VERIFYING | CRC/biçim/kaynak/allow/safe denetimi; eski program çalışır |
| READY | Banka mühürlü, commit beklenir |
| TRANSITION | Görevler donmuş; safe ve kaynak geçişi bounded adımlarla |
| ACTIVE | Yeni kod/tablo/durum görünür; generation bir artar |
| REJECTED | Aktivasyon öncesi hata: eski program sürer |
| STOPPED | Geçişte hata/dead-man: safe, otomatik yeniden başlatma yok |

Güvenli nokta: opcode/port adımı tamamlanmış, native çağrı/ADC isteği askıda değil,
ISR aktarımı kısa kritik bölgeyle kapatılmış poll sınırı. Bekleyen dönüşümün iptali
bounded olmalıdır. Geçiş birden çok poll sürebilir; heartbeat/watchdog sürer ama
hiçbir görev donanım komutu çalıştırmaz. Atomiklik yürütülen görev kümesidir;
fiziksel pinlerin aynı anda değiştiği iddia edilmez.

Önce kaynaklar kuru kontrolden geçer; değişen/silinen kaynaklar safe yapılır,
abonelikleri sökülür, yeni pin/periferaller başlatılır. Başarılı son adımda aktif
banka/allow/safe/durum/generation birlikte yayımlanır. Geçiş boyunca eski ve yeni
kaynakları kapsayan geçici safe birleşimi kullanılır; çelişen güvenli maskeler veya
kapasite aşımı commit öncesi reddedilir. Birleşim, eski özel ve aday safe tabloların
sınırlı dolaşımıyla uygulanır; üçüncü tam tablo tahsisi gerekmez.

| Durum öğesi | Koruma kuralı |
|---|---|
| Değişmeyen görev (aynı kod/şema/kaynak hash'i) | PC/register/değişken/bekleme/timer korunur |
| Değiştirilen görev | PC girişe; geçiciler sıfır; bekleyen olaylar iptal |
| Kalıcı değişken | Aynı task_id + var_id + tip/ölçek, yeni sınır içindeyse kopyala |
| Yeni/uyumsuz değişken | JSON başlangıç değeri; sessiz dönüşüm yok |
| Timer | Değişen görevde yalnız açık preserve + aynı timer_id/süre/olay bağı |
| Süresi geçmiş korunmuş timer | Aktivasyon sonrası tek olay; telafi yağmuru yok |
| Taşınan pin/işlev/kaynak | Periferal, bağlı timer/eşik geçmişi sıfırlanır; register göçmez |
| Silinen görev | Timer/abonelik/olaylarını sil; sahip çıkışları safe yap |
| Parametre | Yeni görüntüdeki açık değer; yalnız ad eşleşmesiyle eski değer taşınmaz |

Exclusive çıkışın iki sahibi olamaz; ADC paylaşımı ancak port izin verirse mümkündür.
Mevcut `pin apply` talepleriyle de çakışma aranır. Aktif kaynaklarda `poke/pin apply/
restore/ram run` engellenir; `safe --all` önce programı durdurur. İki taşıma aynı
oturum kilidini kullanır; dış debug istemcilerinin kilide uyduğu varsayılır.

Kimlik: schema_version, bytecode_version, capability_hash, host SHA-256, hedef CRC32,
generation, task_revision, boot_id. Reset generation'ı sıfırlar. Boot_id portun her
açılışta değişen sayacı/nonce'udur; bunu sağlayamayan portta her bağlantıda host
önbelleği bayat kabul edilir. Generation/istek sayacı sarmadan oturum yenilenir.

## 7. Mailbox ve seri bağlantı uzantısı

Öneri: mailbox sürüm 2, magic `0x32544145`; v1 magic'iyle karıştırılmaz.
Böylece yalnız magic kontrol eden eski heartbeat istemcisi de v2'ye yazamaz.
V1 yerleşimi değişmez; v2 bilinçli yeni host gerektirir. Seri çerçeve sürümü 1 ve
INFO biçimi kalır; ek seri opcode gerekmez. INFO ile bulunan mailbox'tan keşfedilir.

| Kelime | Alan | Tek yazan | Kural |
|---|---|---|---|
| 0..17 | Eski başlık adları | Eski sahipleri | V2 magic/version; armed yalnız denetimli istek |
| 18 | extension_words | Stub | 46; toplam kontrol başlığı 64 kelime |
| 19..20 | caps_offset, caps_bytes | Stub | Mailbox tabanına göre salt okunur rapor |
| 21..23 | bank0_offset, bank1_offset, bank_bytes | Stub | Başlık/rapor/halka ile çakışmaz |
| 24..25 | ring_offset, ring_bytes | Stub | Ortak ölçüm alanı |
| 26..27 | request_seq, command | Host | request_seq en son |
| 28..35 | request_args[8] | Host | Ack gelmeden değişmez |
| 36..39 | ack_seq, command_status, error, result | Stub | ack_seq en son |
| 40..45 | generation, active_bank, run_state, active_crc, boot_id, state_seq | Stub | state_seq çift/tek snapshot sayacı |
| 46..49 | upload_id, received_bytes, candidate_state, task_fault_id | Stub | Aday ilerlemesi |
| 50 | ring_read_seq | Host | Tüketim cursor isteği |
| 51..53 | ring_ack_seq, ring_ack_status, reserved | Stub | Sonuncu sıfır |
| 54..63 | Ayrılmış | Stub | Sıfır; host yazmaz |
| 64.. | Rapor, bankalar, halka | Alanına göre | Banka baytları host; rapor/halka stub |

V2 safe satırları kelime 18'de değildir, bankadadır. Eski safe_count/armed host
alanları yalnız tanılama/istektir; etkin güvenlik özel safe kopyasındadır.
Çalışırken armed=0 görülmesi güvenliği kapatmaz, programı durdurur.
Ham çağrı alanları aktif programda `BUSY_PROGRAM` ile tamamlanır, çağrı yapılmaz.

| Komut (öneri) | request_args | Sonuç |
|---|---|---|
| `10 BEGIN` | expected_generation, toplam_bayt, CRC32, format | upload_id, boş banka; önce boyut denetimi |
| `11 CHUNK` | upload_id, offset, length, chunk_crc | Yazılmış parçayı kontrol et; received_bytes ilerlet |
| `12 VERIFY` | upload_id | Sınırlı doğrulamayı başlat; READY ayrıca okunur |
| `13 COMMIT` | upload_id, expected_generation | Güvenli noktadan sonra nihai ack |
| `14 ABORT` | upload_id | Adayı bırak; aktif program etkilenmez |
| `15 STOP_SAFE` | expected_generation | Programı durdur, safe uygula |
| `16 PARAM_SET` | expected_generation, param_id, değer | Sınır kontrolü; tick sınırında atomik, generation++ |
| `17 MESSAGE` | expected_generation, message_id, değer | İzinli olay kuyruğuna ekle |

Komut kodları onaltılıktır. Tek istek yürür; taşıma sıra numarası istek kimliği
değildir. `ack_seq==request_seq` olunca sonuç okunur. VERIFY kabul ack'i verir,
READY ayrı durumdur; COMMIT ack'i geçişin nihai sonucudur. Generation commit anında
tekrar kontrol edilir. Stub state_seq'i tek yapıp alanları yazar, sonra çift yapar;
host iki eşit çift state_seq arasında snapshot okur.

Görüntü başlığı: magic EATI, format u16, header_bytes u16, total_bytes u32,
bytecode_version u32, capability_hash u32, bölüm_sayısı u32; ardından her bölüm
için `type, offset, length, count` u32 tanımı. Bölümler görev, kod, değişken şeması,
parametre, olay, allow, safe, native manifestidir. Bütün tamsayılar little-endian;
çakışan bölüm, hizasız kod, bilinmeyen zorunlu bölüm ve kapasite aşımı ret.

Upload: BEGIN ack → boş bankaya en fazla 128 B sıralı bayt yaz → CHUNK → ack →
sonraki parça → VERIFY → READY → COMMIT → generation/CRC geri oku.
Son parça dışında uzunluk 4'ün katı; dolgu toplam CRC'ye dahil değildir.
CRC32/ISO-HDLC: reflected poly `0xEDB88320`, init/xorout `0xFFFFFFFF`.
Chunk CRC yalnız parça verisine, toplam CRC görüntünün tam baytlarına uygulanır.
Mevcut seri CRC16 bunların yerine geçmez.

READ/WRITE/INCREMENT_IF iki taşımada aynı mailbox işlemlerini taşır.
OpenOCD yolunda UID korumalı mailbox bellek erişimi, seri yolda mevcut eat_link
READ/WRITE komutları kullanılır. İki yol aynı komut sahipliği/ack düzenine uyar;
program baytları 8 bit, kontrol kelimeleri hedef byte order'ına çevrilerek yazılır.
Chunk boyutu seri azami
payload eksi UID/istek giderine de sığmalıdır. Host mühürlü/aktif bankaya yazmaz;
VERIFY boyunca aday da değişmez. Stub yalnız tahsisli banka offsetlerini kabul eder,
serbest RAM adresi almaz. Her istek UID korumasından geçer; build/stub_hb önkoşulları
korunur. Kritik yayımda port publish/acquire sözleşmesi uygulanır.

Timeout'ta değiştirici istek otomatik tekrarlanmaz. Yeniden bağlanınca boot_id,
request/ack, upload_id, generation, CRC okunur; belirsizlik açık raporlanır.
Yarım aday 5 s ilerlemesizlikte bırakılır; aktif program etkilenmez. Heartbeat kaybı
ayrıca dead-man tetikler. Yeniden upload yeni kimlikle başlar.

## 8. Host temsili, derleyici ve araçlar

AI önce JSON düzenler; hedef JSON/metin çözümlemez. Sonraki küçük metin DSL'si aynı
doğrulanmış ara temsile çevrilebilir, ayrı güvenlik yolu oluşturmaz.
Aşağıdaki önerilen biçimdir; mevcut CLI girdisi değildir.

```json
{
  "schema_version": 1,
  "expected_generation": 7,
  "params": {"threshold": {"type": "u32", "value": 1800, "min": 0, "max": 4095}},
  "tasks": [{
    "id": "threshold_output", "revision": 2,
    "resources": ["sense", "load"],
    "trigger": {"kind": "periodic", "period_ms": 10},
    "vars": [{"id": "above", "type": "u32", "initial": 0, "preserve": true}],
    "steps": [
      {"op": "analog_read", "pin": "sense", "dst": "value"},
      {"op": "emit", "channel": "sense", "value": "value"},
      {"op": "on_rising_threshold", "value": "value", "param": "threshold", "hysteresis": 50,
       "actions": [{"op": "pulse", "pin": "load", "duration_ms": 3000}]}
    ]
  }]
}
```

Pulse, ADC hazır bekleme ve eşik host'ta durum makinesine indirilir; 3 s bekleme
ADC örneklemeyi durdurmaz. Sembolik geçiciler register/slotlara atanır.
Yeni yükseliş aktif pulse'u varsayılan uzatmaz; restart/ignore politikası şemada
açıktır ve hedefte uygulanır. Eşik histerezisinde alt sınır taşması host'ta ret.

| Derleme geçişi | Ret / çıktı |
|---|---|
| Şema/sürüm | Tekil kimlik, tam sayı, boyut sınırı; bilinmeyen alan ret |
| Profil + MCU verisi | Pin/işlev/parametre/aralık, yan etki, protected, safe tarifleri |
| Yetkinlik eşleştirme | Hook/IRQ/ADC/PWM/native, kaynak, hedef birimleri ve ölçek |
| Kaynak/zaman planı | Pin taşıma, exclusive sahip, örnek hızı, WCET/deadline |
| İndirme | Durum makineleri, slot/timer/etiket; recursive yapı ret |
| Kod doğrulama | PC, register/tip, bekleme yolları, komut/dilim sınırları |
| Paketleme | Kod, allow/safe, göç şeması, CRC32/SHA-256, kaynak eşlemesi |
| Plan/yürütme | Fark, çıkış etkisi, sıfırlanacak durum; execute ile upload/commit |

Dinamik dallarda statik bütçe kanıtı yoksa hedef bütçe denetimi zorunlu kalır.
Mevcut Policy, MCU tarifi ve oturum heartbeat yolu genişletilir; v1 sınıflarına
sessizce v2 indeksleri sokulmaz. Banka/halka/rapor da reserved alan olur.

| MCP aracı | Girdi / davranış |
|---|---|
| program_get | Hedeften durum, generation/boot_id, CRC, görev revizyonları |
| program_set | JSON + expected_generation + execute; derle, planla, etkinleştir |
| task_add | Görev JSON + expected_generation; ekle/değiştir, aynı transaction |
| task_remove | task_id + expected_generation; safe/geçiş ile sil |
| param_set | param_id/değer/expected_generation; plan veya atomik PARAM_SET |
| events_read | En çok N kayıt/cursor; kayıp sayacıyla oku, açık tüketim onayı |

Değiştiriciler varsayılan plan, mevcut execute:true kuralını kullanır; denetim kaydı
kaynak/hash, plan, sonuç ve belirsizliği içerir. Program_get manifest/bytecode okur;
JSON kaynağı host hash kaydından gelir. Kaynak yoksa kimlik/çözülmüş komut döner.
Events_read cursor ilerletiyorsa mailbox'a yazar, execute:true ister; consume:false
yalnız okur. Donanım geri okumasından fiziksel başarı çıkarılmaz.

## 9. Port kancaları ve yetkinlik raporu

Mevcut eat_hal bozulmaz; sürümlü ayrı eat_interp_port/kayıt çağrısı önerilir.
Eat_embed kapalı özellikte aynı API/akışı korur; açıkken port ayrıca kaydedilir.

| Kanca | Sözleşme |
|---|---|
| gpio_read/write/configure | Kaynak kimliği; set/clear ve pin modu portta |
| analog_start/read/cancel | START/READY/PENDING/ERROR; dönüşüm beklemek yok |
| pwm_set/stop | Duty/frekans sınırı, kanal paylaşımı, safe stop |
| pin_irq_bind/unbind | Kenar maskesi; bounded sökme; ISR yalnız olay iter |
| resource_check/prepare/release | Uygulama kaynaklarıyla çakışma, safe pin taşıma |
| native_call | Onaylı kimlik → ABI/giriş; bounded, denetimli donanım sarmalayıcısı |
| safe_stop/write | Üreticileri kes; doğrulanmış safe register satırını uygula |
| critical_enter/leave, publish/acquire | ISR ve debug/seri bellek görünürlüğü |
| millis, isteğe bağlı micros | Taşmalı monotonik zaman; tick/ölçüm saati |

C99 volatile tek başına bariyer değildir. Port hizalı u32 yayımını atomik sağlar;
cache/DMA/debug tutarlılığı ve bariyer/cache bakımı porttadır. Çok çekirdekte tek
sahip çekirdek seçilir; desteklenmeyen tutarlılıkta ret. PENDING/hatalı kancanın
ne kadar sürede iptal edileceği açık sözleşmedir.
Salt okunur rapor: sürüm, özellik bitleri, bytecode sürümü, kapasiteler, tick/poll/
WCET limitleri, timer çözünürlüğü, ADC birim/çözünürlük, PWM sınırları, IRQ kenarları,
native ABI, halka sürümü, katalog hash'i. 256 B alan sabit özet/hash taşır; büyük
pin kataloğu host MCU dosyasındadır. Hash/sürüm uyuşmadan kimlik kullanılamaz.
Desteklenmeyen özellik erken ret; host gecikmeli komutlarla taklit etmez.

## 10. F3 ile ortak örnek/olay halkası

Bu F3 için önerilen sözleşmedir; mevcut F3 uygulaması iddiası değildir.
Yorumlayıcı EMIT, port örnekleyici ve F3 aynı kayıt biçimini kullanmalıdır.
Tek fiziksel üretici poll bağlamıdır; ISR/DMA sonlu staging kuyruğuna yazar.
Yüksek hızlı F3 ayrı halka kullanabilir, format/sayaç kuralları aynıdır.

32 B başlık, sekiz u32: format=1, record_bytes=32, capacity, write_seq,
read_seq_ack, dropped, time_unit_ns, clock_id. Hepsini stub yazar;
host cursor isteğini mailbox ring_read_seq'e yazar, başlığa doğrudan yazmaz.
Kapasite ikinin kuvveti ve <2^31; sıra u32, doluluk unsigned farktır.

| Kayıt alanı | Ofset/tip | Anlam |
|---|---|---|
| seq | 0/u32 | Yayım sıra numarası, en son yazılır |
| timestamp | 4/u32 | Yakalama zamanı; tick veya örnekleme saati |
| generation | 8/u32 | Üretim anındaki program sürümü |
| source | 12/u16 | Görev/F3 kaynağı; 0 sistem |
| kind | 14/u8 | 1 sample, 2 pin, 3 timer, 4 threshold, 5 message, 6 fault, 7 commit |
| flags | 15/u8 | Bit0 veri geçerli, bit1 gecikmiş, bit2 staging kaybı |
| channel | 16/u32 | Profil/manifest kanalı |
| value | 20/u32 | Ham/sabit noktalı değer |
| aux | 24/u32 | IRQ kenarı, ADC indeksi veya hata kodu |
| reserved | 28/u32 | Sıfır |

Halka little-endian; slot indeksi `seq & (capacity-1)`. Başlangıç write/read seq=0;
üretici slotta seq=write_seq yayımlar, sonra write_seq++ yapar. Host yalnız modüler
read_seq_ack..write_seq penceresini okur; seq/write_seq'i yeniden okuyarak doğrular.
Okunmamış slot ezilmez; dolu halkada yeni kayıt atılır, dropped artar, kontrol
bloklanmaz. Fault ayrıca mailbox'ta kalır; dolu halkada hata durumu kaybolmaz.

Host ring_read_seq'e sonraki cursor'u yazar; stub pencereyi kontrol eder,
read_seq_ack/ring_ack_status yazar, ring_ack_seq'i son yayımlar. Geri/geçersiz cursor
ret; boot_id değişince eski cursor bırakılır. Zaman sarması host'ta genişletilir;
birim/clock_id ve azami okuma aralığı raporlanır. Kanal ölçeği host manifestindedir.

## 11. Kabul senaryoları ve kanıt

Adlar mantıksal profil takma adlarıdır; gerçek pin/adres önermez. Önkoşul: port
WCET'i, safe tablo, bağımsız watchdog ve fiziksel ölçüm düzeneği doğrulanmıştır.

| Adım | İşlem | Beklenen gözlem |
|---|---|---|
| 1 | Kimlik/build, yetkinlik/safe doğrula | Destekli işlevler; generation=0, çıkış safe |
| 2 | Sense ADC'yi 10 ms aralıkla örnekleyen görev yükle | Flash değişmez; hedef timestamp'leri 10 ms planını gösterir |
| 3 | Events_read verisinden eşik seç; param_set | Sınır kontrolü, generation++; örnekleme kesilmez |
| 4 | Eşikte load çıkışını 3 s açan görev ekle | Karar hedefte; sohbet yanıtı beklenmeden çıkış açılır |
| 5 | Araç çağrılarına 2 s ara ver; heartbeat sürsün | ADC ve 3 s kapanış sürer; retrigger politikası ölçülür |
| 6 | Load pinini kesme girişi yapan görüntüyü commit et | Önce safe, sonra IRQ; eski pulse/timer iptal |
| 7 | Girişte kenar üret | Hedef zamanlı olay; çift abonelik/eski görev yazısı yok |
| 8 | Yeni modülü izinli direction/PWM pinlerine bağla; görev ekle | 2 s ileri; önce stop, sonra yön değişimi |
| 9 | Profilin zorunlu nötr süresini uygula | PWM=0 aralığı fiziksel ölçülür; sonra ters sürüş |
| 10 | Görevi sil | Kaynaklar bırakılır, çıkış safe; diğer görev durumu korunur |

3 s/2 s toleransı deadline formülünden türetilir; örnek kaydı pin ölçümünün yerine
geçmez. Modül sürüş tarifi genel motor sürücüsü değildir; zorunlu beklemeler ve
pin işlevleri incelenmiş profil/port verisidir.

| Hata enjeksiyonu | Beklenen sonuç |
|---|---|
| Host/heartbeat tamamen ölür | Timeout+poll/safe sınırında safe; heartbeat otomatik başlatmaz |
| Upload ortasında host kapanır | Aktif banka sağlam; aday atılır; heartbeat kaybında dead-man |
| Chunk/görüntü CRC bozuk | READY/COMMIT yok; eski generation/program korunur |
| Yasak pin veya sınır dışı PWM | Host ret; elle bozuk görüntüyle hedefte de ret; kanca çağrılmaz |
| Protected adresli allow/safe | Port zarfı ret; eski program sürer |
| Sonsuz geri dal | ≤b birimde BUDGET_EXCEEDED; poll/link ilerler, safe uygulanır |
| ADC hazır olmuyor | Deadline/cancel hatası; bloklama yok, safe |
| IRQ kuyruğu taşar | EVENT_OVERFLOW, safe; ölçüm kaybından farklı |
| Ölçüm halkası dolar | Yeni kayıt düşer, dropped artar; kontrol sürer |
| İki host aynı generation ile düzenler | İlk commit başarılı; ikinci STALE_GENERATION |
| Commit sırasında bağlantı kopar | Boot/generation/CRC ile sonucu bul; kör tekrar yok |
| Pin taşıma kancası hata verir | Eski+yeni safe; STOPPED; başarı generation'ı yayımlanmaz |
| Reset/sayaç sarması | Bayat program/cursor/istek ret; yeni oturum |
| Native hash yanlış / işlev süresiz | Hash upload'da ret; süre ihlalinde watchdog/reset-safe ölçümü |

Uygulama kabulü: iki taşıma ile aynı görüntü/sonuç; bozuk görüntü testleri,
C99 taşınabilir derleme, bütçe/bellek, göç/commit yarışları için host C testleri;
ardından hedefte jitter, watchdog, kesinti ve safe ölçümü. F3 ile üretici/kayıp/
cursor format testi ortak kabul kapısıdır. F4.1 yalnız tasarımdır; bu testler yapılmış
sayılmaz ve mevcut host testleri donanım kanıtına dönüştürülmez.

## 12. Alternatifler ve açık kararlar

Boyut karşılaştırması mühendislik değerlendirmesidir; eşdeğer hedef derlemeleri
ölçülmeden kesin KiB sıralaması iddia edilmez.

| Seçenek | Boyut | Güvenlik / determinizm | Karar |
|---|---|---|---|
| Yalnız yerel RAM kodu | Küçük dispatcher; kod/stack ve araç zinciri eklenir | Keyfi erişim, kesilemeyen çağrı; WCET geliştiricide | İncelenmiş bounded hızlandırıcı opsiyonu |
| Yalnız komut dispatch | En küçük çekirdek adayı | Host zamanlaması; eşik/süre için ek durum makinesi gerekir | Hedef zamanlama amacını tek başına karşılamaz |
| Küçük Forth | Küçük olabilir; sözlük/veri/return stack maliyeti | Bellek kelimeleri kısıtlanmalı, bütçe/allow yine eklenir | Dil esnekliği gerekirse tekrar değerlendir |
| Lua | Dinamik nesne/stack ve GC RAM'i | GC/C çağrıları deadline için ayrıca sınırlandırılmalı | İlk statik bellek hedefinde seçilmedi |
| WASM yorumlayıcısı | Doğrulayıcı, linear memory ve stack maliyeti | Bellek izolasyonu yararlı; donanım importları/süre yine denetlenmeli | Daha büyük hedeflerde alternatif |
| Bu komut kümesi | Hedef ≤16 KiB çekirdek flash; statik RAM | Dar yüzey, her I/O'da allow, bounded tick | İlk uygulama tercihi |

Birincil kaynaklar: [küçük Forth örneği](https://github.com/zevv/zForth)
gömülebilir yapı ve yapılandırılabilir stack/sözlük gösterir;
[Lua bellek yönetimi](https://www.lua.org/manual/5.5/manual.html#2.5)
GC tanımlar; [WASM çalışma zamanı kaynağı](https://github.com/wasm-micro-runtime/wasm-micro-runtime)
yorumlayıcı/modül yükleme/yapılandırma seçeneklerini sunar. Bu kaynaklar kendi
bütçe hedeflerimizin kanıtı değildir.

| Açık soru | İlk karar / kapanış ölçütü |
|---|---|
| F3 formatı ve saat | Bu 32 B formatı ortaklaştır; F3 sahibiyle sürüm/cursor testi kesinleştir |
| Gerçek flash/RAM/tick | Küçük 32 bit hedefte map/stack/WCET ölç; aşılırsa özellik düşür |
| Safe birleşimi kapasitesi | İlk sürüm 16 satır; sığmayan geçişe açık ret |
| Periferal yeniden başlatma gecikmesi | Port deadline raporu; çok poll geçişinde görev atomikliği |
| Timer/değişken göçü arayüzü | Açık preserve; parametreye PARAM_SET, kod değişince giriş PC |
| Çok hızlı eşik tepkisi | F3/donanım karşılaştırıcı; tick altında garanti verme |
| Native güven sözleşmesi | Varsayılan kapalı; incelenmiş hash/ABI/WCET varsa aç |
| Genel seri WRITE sınırlaması | Güvenilir host modeli; düşmanca istemci izolasyonu ayrı iş |
| Bağımsız güvenli durdurma | Her portta watchdog/reset-safe testi |
| DSL ve signed/sabit nokta | JSON/u32 ile başla; aynı ara temsil, sürümlü tipler |

Uygulama sırası: biçim/doğrulayıcı C testleri → zamanlayıcı → iki bankalı protokol/
host derleyici → port/F3 → iki taşıma/fiziksel kabul. Her aşama capability ile
ilan edilir; tasarımda bulunması destek iddiası değildir.
