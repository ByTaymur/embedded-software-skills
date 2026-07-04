---
description: Firmware/kontrol sisteminin mevcut konfigürasyon özetini çıkarır (proje-bağımsız).
---

Projenin firmware konfigürasyonundan bir durum raporu çıkar. Hangi dosyaların okunacağını **proje `CLAUDE.md`'sinden** öğren; tipik olarak:

- parametre config header'ı (motor/donanım sabitleri, tek kaynak)
- global include/define header'ı (pin tanımları)
- `.ioc` (peripheral konfigürasyonu)
- ana kontrol döngüsü kaynağı (kontrol sabitleri, offset kalibrasyonu)

Rapor formatı (yalnızca projede geçerli olan bölümleri doldur):

## <PROJE> Durum Raporu

### Aktif Konfigürasyon
- Ana parametreler (ör. motor modeli, kutup sayısı, nominal hız/akım) — proje neyse

### Donanım Pinleri (doğrulanmış)
- PWM / güç çıkışları
- Sensörler (akım, gerilim, sıcaklık…)
- Encoder / geri besleme
- Haberleşme (UART/CAN/…)

### Kontrol / FOC Parametreleri
- PWM frekansı, dead-time, loop frekansı
- PID başlangıç değerleri (Kp, Ki)
- Offset / kalibrasyon değerleri

### Periferik Durum
- Timer'lar (PWM, encoder, kontrol IRQ)
- ADC/DMA
- Diğer aktif periferikler

### Bilinen Açık Sorunlar
Proje `CLAUDE.md`'deki "Bilinen Sorunlar" bölümünden listele.

### Son Değişiklikler
`git log --oneline -5` çıktısı.

Kullanıcıya raporu Türkçe sun. Projeye ait olmayan bölümleri atla; değer yoksa "TBD" yaz, uydurma.
