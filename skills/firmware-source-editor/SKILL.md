---
name: firmware-source-editor
description: Edit embedded firmware source files (C/H) in a project. Use when asked to modify, update, or change firmware code. Only edits source — does NOT build or flash. Maintains a per-session Knowledge/QA log. Project-specific pins/parameters live in the project CLAUDE.md, not here.
---

# firmware-source-editor

Embedded firmware kaynak kodu (`.c` / `.h`) düzenleyicisi. Proje `CLAUDE.md`'de tanımlı kaynak klasörlerindeki dosyaları değiştirir. **Build veya flash yapmaz** — yalnızca kaynağı düzenler.

> Bu skill proje-bağımsızdır. Hangi dosya nerede, hangi motor/pin/parametre — hepsi **proje `CLAUDE.md`'sinden** okunur. Buraya sabit değer (pin, parametre, motor) yazılmaz.

## Çalışma dosyaları (projeye özel)

Proje `CLAUDE.md`'deki dosya yapısından öğren. Tipik embedded proje düzeni:

| Rol | Tipik konum |
|-----|-------------|
| Ana kontrol döngüsü | `firmware/Src/main.c` |
| Parametre tek kaynağı | `firmware/Inc/*_config.h` |
| Global include/define | `firmware/Inc/main.h` |
| Kesme vektörleri | `firmware/Src/*_it.c` |
| HAL MSP (peripheral init) | `firmware/Src/*_hal_msp.c` |

## Knowledge Log (Bilgi Deposu)

Her geliştirme oturumunda sorulan teknik sorular ve verilen cevaplar bir QA log dosyasına kaydedilir. Dosya yolu proje `CLAUDE.md`'de tanımlıdır (tipik: `docs/knowledge/QA_LOG.md`).

### Kayıt kuralları

1. **Her soru-cevap çifti** aynı oturumda, konuşma biterken QA log dosyasına eklenir.
2. **Format** (tarih projenin yerel saatiyle, en yeni giriş en üstte):

```markdown
---

## YYYY-MM-DD

### S: <sorulan sorunun kısa başlığı>

**Soru:** <kullanıcının tam sorusu>

**Cevap:** <verilen cevap — teknik detay, karar, öğrenilen bilgi>

**İlgili dosya:** `<dosya yolu>` (varsa)
```

3. **Kayıt ne zaman açılır:**
   - Kullanıcı teknik bir soru sorarsa (neden, nasıl, ne zaman)
   - Bir parametre veya pin hakkında karar verilirse
   - Bir hata analiz edilip çözülürse
   - Bir tasarım kararı tartışılırsa

4. **Kayıt ne zaman açılmaz:**
   - "şunu yaz", "şunu değiştir" gibi doğrudan kod komutları
   - Basit syntax soruları

5. **Dosya yoksa oluştur**, üst kısımda şu başlık:

```markdown
# <PROJE> — Geliştirme Bilgi Deposu

Oturum soru-cevap geçmişi. Her giriş tarihli ve dosya referanslıdır.
En yeni giriş en üstte.

---
```

## Gotchas (genel embedded kuralları)

Projeye özel pin/parametre değerleri **proje `CLAUDE.md`'de**; aşağıdakiler her projede geçerli disiplinlerdir:

- **Parametreler tek yerde** — tüm motor/donanım sabitleri tek config header'da; `main.c` içine sabit gömme.
- **Sadece USER CODE BEGIN/END blokları** — CubeMX üretimi bölümlerin dışına çıkma.
- **Register/AF'yi doğrula** — pin alternate-function ve remap'i datasheet'e göre onayla (tahmin etme).
- **HAL_Delay yasak** — `HAL_GetTick()` ile non-blocking zamanlama veya state machine kullan.
- **ISR kısa kalır** — zaman kritik iş ISR'de, gerisi ana döngüde; ISR'de blocking/heavy iş yok.

> Bu skill kod düzenler; derleme/flash için ayrı toolchain akışı (bkz. `stm32-firmware-workflow`) kullanılır.
