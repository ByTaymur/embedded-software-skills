# ASCII Akış Şeması Kılavuzu

State machine fonksiyonları için ASCII akış şeması çizme standardı.
Proje bağımsız — her STM32 / gömülü yazılım projesinde geçerlidir.

---

## Zorunlu uygulama — ne zaman tetiklenir

Bu kılavuz aşağıdaki durumlarda **otomatik olarak devreye girer**; kullanıcının hatırlatması gerekmez:

| Durum | Şema zorunlu mu? |
|-------|-----------------|
| Bu oturumda sıfırdan yazılan yeni state machine fonksiyonu | **EVET** |
| Mevcut fonksiyon kullanıcı onayıyla tamamen yeniden yazılıyor | **EVET** |
| Mevcut fonksiyona küçük ekleme/düzeltme | HAYIR |
| Tek koşullu basit yardımcı fonksiyon | HAYIR |

**Uygulanacak sıra:**
1. Şemayı çiz — önce diyagram, sonra kod.
2. Fonksiyon gövdesinin **en üstüne** `/* ... */` bloğu içinde yerleştir.
3. Tüm 7 kuralı kontrol et (aşağıya bak).
4. Ancak ondan sonra `switch`/`if` bloğunu yaz.

---

## Neden zorunlu

State machine kodu okunduğunda case numaraları anlam taşımaz. Şema olmadan "Case 3'ten Case 4'e geçiyor" ifadesi okuyucuya hiçbir şey söylemez. Şema şunu gösterir:

- Fonksiyon ilk çağrıldığında sistem hangi koşullarda olabilir?
- Her case ne yapmak için var?
- Hangi sensör/flag değişimi state geçişini tetikliyor?
- Donanıma o anda ne söyleniyor?
- Nerede sonsuz döngü var, nerede hata koşulu var?

---

## Şemanın Yapısı — 7 Kural

### Kural 1: BAŞLANGIÇ kutusu en üstte, çift etiketli

Her şema tek bir giriş noktasıyla başlar. Kutu içinde iki bilgi birlikte:
- Okunabilir bir isim
- Parantez içinde kodun gerçek case/state numarası

```
   ┌─────────────────┐
   │   BAŞLANGIÇ     │
   │    (Case 0)     │
   └───────┬─────────┘
           │
```

Okuyucu şemadan koda geçtiğinde `case 0:` bloğunu direkt bulur.

---

### Kural 2: Başlangıçtan çıkan TÜM senaryolar şemada

Fonksiyon çağrıldığında sistem kaç farklı durumda olabilir? Bu sayıyı bul ve hepsini ayrı dal olarak çiz. Hiçbir senaryo atlanmaz — "oraya düşülemez" diye geçiştirilen senaryo da şemaya girer, `(HATA!)` etiketiyle.

İki sensör varsa 4 kombinasyon çıkar:

```
                  ┌─────────────────┐
                  │   BAŞLANGIÇ     │
                  │    (Case 0)     │
                  └───────┬─────────┘
                          │
       ┌──────────────────┼──────────────────┬──────────────────┐
       │                  │                  │                  │
   ┌───▼───┐          ┌───▼───┐          ┌───▼───┐          ┌───▼───┐
   │ A=0   │          │ A=0   │          │ A=1   │          │ A=1   │
   │ B=0   │          │ B=1   │          │ B=0   │          │ B=1   │
   │(HATA!)│          │(DurumX)│          │(DurumY)│          │(Bilin.)│
   └───┬───┘          └───┬───┘          └───┬───┘          └───┬───┘
```

---

### Kural 3: Her case kutusu — 3 satır

```
   ┌─────────────────────┐
   │     Case 2          │   ← case numarası
   │  (İnce Ayar)        │   ← bu case ne amaçla var (Türkçe, kısa)
   │  Aşağı Hareket      │   ← o anda donanıma verilen komut
   └──────────┬──────────┘
```

Sadece numara yasaktır. Kutunun içine bakan okuyucu o state'in ne yaptığını anlamalıdır.

---

### Kural 4: Geçiş koşulu — okun yanında, kutunun içinde değil

Bir case'den diğerine hangi koşulda geçildiği, geçiş okuna yazılır.

```
              │
   SensorA: 0→1 geçiş         ← hangi değişken, hangi yön
              │
              ▼
```

Kabul edilen formatlar:

| Format | Kullanım |
|--------|----------|
| `SensorAdi: 0→1 geçiş` | Kenar geçişi (rising/falling edge) |
| `FlagAdi=0 (açıklama)` | Seviye kontrolü, anlamıyla birlikte |
| `Koşul mu? EVET / HAYIR` | Dal sorusu |

"Koşul sağlandı", "flag değişti" gibi soyut ifadeler yasaktır.

---

### Kural 5: Donanım komutu — geçiş okunda, case'e girmeden önce

Donanıma verilen komut (motor yönü, duty, GPIO, vb.) case kutusunun içine değil, o case'e GIRERKEN verilen geçiş okuna yazılır.

```
              │ Aşağı Git
              │ Duty=30
              ▼
   ┌─────────────────────┐
   │     Case 1          │
```

Bu, koddaki gerçek davranışı yansıtır: `CezveAsagiDuty = 30` case'e girerken set edilir, case içinde değil.

Gerçek değişken adı veya sayısal değer yazılır — "bir şeyler yap" gibi muğlak ifade yasaktır.

---

### Kural 6: Birleşen yollar — `◄───` oku ile

Birden fazla farklı dalın aynı case'e gittiği yerlerde birleşme açıkça gösterilir:

```
   ┌─────────────────────┐
   │     Case 4          │◄───────────┬────────────────────┐
   └──────────┬──────────┘            │                    │
              │                  (dal 1)               (dal 2)
```

Bu gösterim olmadan okuyucu "şemada iki ayrı Case 4 var mı?" diye yanılır.

---

### Kural 7: Tehlikeli durumlar — açıkça etiketlenir

Üç durum her zaman şemada işaretlenir:

| Durum | Etiket |
|-------|--------|
| İmkansız / geçersiz giriş kombinasyonu | `(HATA!)` — kutunun içinde |
| Kasıtlı sonsuz döngü | `SONSUZ DÖNGÜ! (CaseX→Y→Z→X...)` — döngü okun altında |
| Belirsiz / bilinmeyen fiziksel konum | `(Bilinmeyen)` — kutunun içinde |

Sonsuz döngü örneği:

```
              └────────────────────────────────┐
                       SONSUZ DÖNGÜ!           │
                    (Case 3→4→5→3...)          │ (bu ok Case 3'e döner)
```

---

## Adım Adım Yeni Şema Çizme

### Adım 1: Giriş koşullarını listele

Fonksiyon çağrıldığında sistem hangi durumda olabilir?

```
SensörA: 0 veya 1
SensörB: 0 veya 1
→ 4 kombinasyon
→ Hangisi geçerli senaryo?
→ Hangisi HATA?
→ Hangisi Bilinmeyen?
```

### Adım 2: Her case'i 3 satırla tanımla

```
Case N  |  Ne amaçla var?  |  Donanıma o an ne söylüyor?
```

### Adım 3: Geçiş koşullarını belirle

Her case'den çıkış için:
- Hangi değişken değişiyor?
- Hangi yönde? (`0→1` mı, `1→0` mu, seviye mi, kenar mı?)
- Bu geçişte donanıma yeni komut veriliyor mu?

### Adım 4: Tehlikeli durumları işaretle

- İki sensör aynı anda tetiklenebilir mi? → `(HATA!)`
- Bilinmeyen konumdan başlanabilir mi? → `(Bilinmeyen)`
- Kasıtlı sonsuz döngü var mı? → `SONSUZ DÖNGÜ!`

### Adım 5: Birleşen yolları bul

Birden fazla dalın aynı case'e gittiği yerleri bul, `◄───` ile işaretle.

---

## ASCII Karakter Seti

| Eleman | Karakter |
|--------|----------|
| Kutu köşesi sol üst | `┌` |
| Kutu köşesi sağ üst | `┐` |
| Kutu köşesi sol alt | `└` |
| Kutu köşesi sağ alt | `┘` |
| Kutu yatay kenar | `─` |
| Kutu dikey kenar | `│` |
| Aşağı T birleşim | `┬` |
| Yukarı T birleşim | `┴` |
| Artı birleşim | `┼` |
| Aşağı yönlü köşe | `▼` |
| Sol yönlü ok | `◄` |

**ASCII-only alternatif** (Unicode yoksa):

```
+------------------+
|     Case 2       |
|  (Ince Ayar)     |
|  Asagi Hareket   |
+----------+-------+
           |
SensorA: 0->1 gecis
           |
           v
```

---

## Şema Nereye Yazılır

```c
void YeniFonksiyon(void) {
  /*

   ┌─────────────────┐
   │   BAŞLANGIÇ     │
   │    (Case 0)     │
   └───────┬─────────┘
           │
   [ ... şema ... ]

  */

  switch (durum) {
  case 0:
    ...
```

- Açılış `{` dan hemen sonra `/* ... */` bloğu.
- `*/` kapandıktan sonra doğrudan `switch` / ilk kod satırı — araya açıklama eklenmez.
- Şema Türkçe yazılır (bu projenin genel dili).

---

## Tam Örnek Şema

Aşağıdaki şema tüm 7 kuralı bir arada gösterir. Soyut bir pozisyon bulma fonksiyonudur — herhangi bir projede bu yapıyı örnek alabilirsin.

```
void KonumBul(void) {
  /*

                              ┌─────────────────┐
                              │   BAŞLANGIÇ     │    <- Kural 1: çift etiket
                              │    (Case 0)     │
                              └───────┬─────────┘
                                      │
              ┌───────────────────────┼───────────────────────┐
              │                       │                       │
   ┌──────────▼──────────┐  ┌─────────▼──────────┐  ┌────────▼────────────┐
   │  SnsrA=0            │  │  SnsrA=1           │  │  SnsrA=1            │
   │  SnsrB=0            │  │  SnsrB=0           │  │  SnsrB=1            │
   │  (HATA!)            │  │  (Konum A'da)      │  │  (Bilinmeyen)       │
   └──────────┬──────────┘  └─────────┬──────────┘  └────────┬────────────┘
              │                       │                       │
              │ Geri Git              │ İleri Git             │ İleri Git   <- Kural 5: donanım komutu
              │ Duty=40               │ Duty=40               │ Duty=40       okun üstünde
              ▼                       │                       │
   ┌─────────────────────┐            │                       │
   │     Case 1          │            │                       │
   │  (Hata Düzeltme)    │            │                       │    <- Kural 3: 3 satır
   │  Geri Hareket       │            │                       │
   └──────────┬──────────┘            │                       │
              │                       │                       │
   SnsrA: 0→1 geçiş                   │                       │    <- Kural 4: geçiş koşulu
              │                       │                       │       okun üstünde
              ▼                       │                       │
   ┌─────────────────────┐            │                       │
   │     Case 3          │◄───────────┴───────────────────────┘    <- Kural 6: birleşen yollar
   │  (Referans Bekleme) │
   │  Dur                │
   └──────────┬──────────┘
              │
   SnsrB=1 (Referans kayboldu)
              │
              │ İleri Git
              │ Duty=40
              ▼
   ┌─────────────────────┐
   │     Case 2          │
   │  (İleri Hareket)    │
   │  Hedefe Git         │
   └──────────┬──────────┘
              │
   SnsrA=0 (Hedefe ulaştı)
              │
              │ DUR!
              │ Duty=0
              ▼
   ┌─────────────────────┐
   │     Case 4          │◄──────────────────────────────────────┐
   │  (Konumda DUR)      │                                       │
   │  Bekle              │                                       │
   └──────────┬──────────┘                                       │
              │                                                  │
   SnsrA=1 (Konum kaybı)                                        │
              │                                                  │
              │ İleri Git                                        │
              │ Duty=40                                          │
              ▼                                                  │
   ┌─────────────────────┐                                       │
   │     Case 5          │                                       │
   │  (Yeniden Bul)      │                                       │
   │  İleri Hareket      │                                       │
   └──────────┬──────────┘                                       │
              │                                                  │
   SnsrA: 1→0 geçiş                                             │
              │                                                  │
              └──────────────────────────────────────────────────┘
                         SONSUZ DÖNGÜ!                              <- Kural 7: tehlikeli durum
                      (Case 4→5→4→5...)

  */
```

**Şemada 7 kural nerede görünüyor:**

| Kural | Şemadaki yer |
|-------|-------------|
| 1 — Çift etiketli BAŞLANGIÇ | En üst kutu: `BAŞLANGIÇ / (Case 0)` |
| 2 — Tüm giriş senaryoları | Case 0'dan 3 dal: HATA, Konum A'da, Bilinmeyen |
| 3 — Her case 3 satır | Tüm case kutularında: numara + amaç + komut |
| 4 — Geçiş koşulu okun üstünde | `SnsrA: 0→1 geçiş`, `SnsrA=0 (Hedefe ulaştı)` vb. |
| 5 — Donanım komutu okun üstünde | `İleri Git / Duty=40`, `DUR! / Duty=0` |
| 6 — Birleşen yollar `◄───` ile | Case 3 ve Case 4'e birden fazla dal birleşiyor |
| 7 — Tehlikeli durumlar etiketli | `(HATA!)`, `(Bilinmeyen)`, `SONSUZ DÖNGÜ!` |

---

## Sık Yapılan Hatalar

| Hata | Doğrusu |
|------|---------|
| Kutuda sadece case numarası | 3 satır: numara + amaç + komut |
| Geçiş koşulu kutunun içinde | Geçiş okuna yaz |
| Donanım komutunu şemada göstermemek | Her geçiş okuna ekle |
| Hata senaryosunu atlamak | `(HATA!)` ile işaretle |
| Sonsuz döngüyü gizlemek | `SONSUZ DÖNGÜ!` notu yaz |
| Birleşen yolları ayrı kutu gibi göstermek | `◄───` oku ile tek noktada topla |
| Soyut geçiş koşulu ("flag değişti") | Değişken adı + yön yaz |
