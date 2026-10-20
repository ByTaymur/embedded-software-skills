# IKIZ-DEFTERI.md — yapı ve doldurma kuralı

Defter **proje kökünde tek dosyadır**, `IKIZ-DEFTERI.md`. Append-only: yeni iş
en üste eklenir, eski girdiler **düzenlenmez** (yanlış çıktıysa altına düzeltme
girdisi yazılır). Yardımcı dosyalar (`plan-A.md`, `plan-B.md`, `diff-*.patch`)
`.ikiz/<is-slug>/` altında durur; deftere **link** verilir, içerik kopyalanmaz.

## Dosya başlığı (bir kez, dosyanın en üstünde)

```markdown
# İkiz Çalışma Defteri

İki ajanın aynı işi bağımsız yapıp karşılaştırdığı kayıtlar.
Yeni girdi en üste eklenir. Eski girdi düzenlenmez.
Ayrıntı dosyaları: `.ikiz/<is-slug>/`
```

## Girdi şablonu

```markdown
---

## IK-YYYYMMDD-NN · <iş başlığı>

| | |
|---|---|
| Tarih | YYYY-MM-DD |
| Mod | ikiz (bağımsız) \| paylaşımlı (B denetçi) \| fan-out |
| B ajanı | model=<tam-kimlik, vars. claude-opus-5> · araçlar=<...> · worktree=<yol\|yok> |
| Kapsam | <hangi dosyalar / hangi soru> |
| Dosyalar | [plan-A](.ikiz/<slug>/plan-A.md) · [plan-B](.ikiz/<slug>/plan-B.md) · [diff-B](.ikiz/<slug>/diff-B.patch) |

### 1. Plan karşılaştırması

| Adım | A | B | Karar |
|---|---|---|---|
| <adım> | ✅ | ✅ | ortak — alındı |
| <adım> | ✅ | — | alındı · gerekçe: … |
| <adım> | — | ✅ | **alındı** · A'nın atladığı: … |
| <adım> | ✅ | ✅ | **çelişki**: A … / B … → seçilen: … çünkü … |

**Yalnız bir tarafta çıkan her adım bu tabloda açıklanır.** Sessizce düşürülmez.

### 2. Uygulama karşılaştırması

| Konu | A'nın çözümü | B'nin çözümü | Fark önemli mi |
|---|---|---|---|
| <dosya/fonksiyon> | … | … | hayır (üslup) \| **evet** — … |

Seçilen uygulama: **A \| B**
Diğerinden alınanlar: <madde madde, her biri gerekçeli>

### 3. Çapraz kontrol bulguları

| # | Bulan | Hedef | Bulgu | Kanıt (dosya:satır) | Doğrulandı mı | Sonuç |
|---|---|---|---|---|---|---|
| 1 | B | A'nın diff'i | … | `src/x.c:120` | ✅ okundu, doğru | düzeltildi |
| 2 | A | B'nin diff'i | … | `src/y.c:44` | ❌ satır öyle demiyor | reddedildi |

Kanıtı doğrulanmayan bulgu **uygulanmaz**; tabloda kalır, "doğrulanmadı" yazılır.

### 4. Karar

<Ne yapıldı, neden. Tek paragraf.>

### 5. Açık kalanlar

- ⚠️ <doğrulanmamış varsayım / sahada test edilecek / ertelenen fark>

### 6. Maliyet

B: <n> çağrı · <süre> · <$maliyet varsa>
```

## Doldurma kuralları

1. **Fark = risk.** İki ajan aynı yeri farklı çözdüyse orada ya belirsiz bir
   gereksinim ya da gerçek bir hata vardır. "Aynısı, önemsiz" demeden önce
   farkın **neden** oluştuğunu yaz.
2. **Çelişki bastırılmaz.** İki taraf zıt şey diyorsa ikisi de tabloya girer,
   seçim gerekçesiyle yazılır.
3. **Kanıt zorunlu.** Dosya:satır olmayan bulgu bulgu değildir.
4. **Hiç fark çıkmadıysa da girdi açılır** — "iki bağımsız uygulama örtüştü"
   bilgisi, o değişikliğe duyulan güveni artıran gerçek bir kayıttır.
5. **B başarısız olduysa** (`is_error`, boş sonuç, timeout) bu da yazılır.
   Karşılaştırma yapılmadıysa defterde "tek taraflı" etiketi kalır.
6. Projenin kendi kayıt sistemi varsa (değişiklik defteri, günlük, karar notu)
   defter girdisi oraya link verir; aynı bilgi iki yere kopyalanmaz.

## Slug kuralı

`IK-YYYYMMDD-NN` · `<is-slug>` = kısa, kebab-case, Türkçe karaktersiz.
Örnek: `IK-20260808-01` · `.ikiz/kazan-pid-guvenlik/`
