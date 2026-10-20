# Protokol ayrıntısı — görev dosyaları ve modlar

Çocuk ajan bu konuşmadan **hiçbir şey görmez**. Her görev dosyası kendi başına
yeterli olmalıdır: bağlam, iş, sınırlar, çıktı sözleşmesi.

---

## Görev dosyası — dört bölüm (zorunlu)

```markdown
# Bağlam
<Depo ne yapar, hangi dil/platform, hangi dosyalar önemli. Proje gerçeği bir
dosyada yazılıysa yolunu ver: "proje gerçeği kökteki CLAUDE.md'dedir".>

# İş
<Tek, kapalı uçlu görev veya tek teslimat. İki iş varsa iki dosya yap.>

# Sınırlar
- <Salt-okunur mu, hangi dosyalara dokunulmaz>
- <Ölü/arşiv klasörler — aramada yanıltır>
- Commit/push/merge yapma. Delege etme, alt ajan başlatma.

# Çıktı
<Ayrıştıracağın tam şekil. JSON istiyorsan örneğini yaz.>
```

Kural: **"iyi bir şey yap" diye görev verilmez.** Çıktı sözleşmesi yoksa
karşılaştırma yapılamaz ve ikiz protokolünün tamamı boşa gider.

---

## Aşama 1 — plan görevi (B'ye)

```markdown
# Bağlam
<...>

# İş
Şu işin uygulama planını çıkar: <iş tanımı>.
Kodu OKU, gerçekte nasıl olduğunu doğrula, sonra planla. Varsayımla plan yapma.

# Sınırlar
- Salt-okunur: hiçbir dosyayı değiştirme, komut çalıştırma.
- Commit/push yok. Delege etme.

# Çıktı
Yalnız JSON, düz metin yazma:
{
  "adimlar": [{"no":1,"ne":"","dosyalar":[""],"neden":"","risk":""}],
  "dokunulan_dosyalar": [""],
  "riskler": [{"risk":"","etki":"","onlem":""}],
  "dogrulama": "bu iş bittiğinde doğru olduğunu nasıl anlarız",
  "belirsizlikler": ["cevabı bilinmeyen, sormak gereken şeyler"]
}
```

`belirsizlikler` alanı önemlidir: iki ajan aynı yerde belirsizlik gördüyse orada
gerçekten eksik bir gereksinim vardır — kullanıcıya sorulacak liste odur.

---

## Aşama 2 — uygulama görevi (B'ye)

```markdown
# Bağlam
<...> Ortak plan aşağıdadır ve aynen uygulanacaktır.

# Ortak plan
<plan-ORTAK.md içeriği buraya gömülür — B dosya yollarını göremeyebilir>

# İş
Planı uygula. Her adımı bitir; yarım bırakma. Emin olmadığın yeri uydurma,
"belirsizlikler" listesine yaz ve o adımı atla.

# Sınırlar
- Yalnız şu dosyalara dokun: <liste>
- Commit/push/merge yok. Delege etme.
- Derleme/test komutu: <varsa tam komut, yoksa "çalıştırma">

# Çıktı
Yalnız JSON:
{
  "yapilanlar": [{"adim":1,"dosya":"","ozet":"","durum":"tamam|atlandi"}],
  "atlananlar": [{"adim":0,"neden":""}],
  "belirsizlikler": [""],
  "dogrulama": "ne çalıştırdın, çıktısı ne oldu"
}
```

---

## Aşama 3 — çapraz kontrol görevi (B'ye, A'nın işi üzerine)

```markdown
# Bağlam
<...> Aşağıdaki diff bu iş için yapılan bir değişikliktir.

# Diff
<diff-A.patch içeriği>

# İş
Bu değişikliği denetle. Aradığın: doğruluk hatası, atlanmış durum, sınır
koşulu, yarış durumu, güvenlik/kilitlenme etkisi, plana uymayan yer.

Üslup, isimlendirme ve biçim tercihleri BULGU DEĞİLDİR — yazma.

Her bulgu için dosya ve satır göster. Emin değilsen "kesinlik":"dusuk" yaz;
uydurma satır numarası verme.

# Sınırlar
- Salt-okunur. Düzeltme yapma, sadece bildir.
- Delege etme.

# Çıktı
Yalnız JSON:
{
  "bulgular": [{"dosya":"","satir":0,"sinif":"dogruluk|guvenlik|eksik|plan-sapmasi",
                "aciklama":"","kanit":"<o satırda ne yazıyor>",
                "nasil_patlar":"<somut senaryo>","kesinlik":"yuksek|orta|dusuk"}],
  "iyi_yapilmis": [""],
  "sonuc": "guvenli|riskli|belirsiz"
}
```

`nasil_patlar` alanı zorunludur: somut bir bozulma senaryosu yazamayan bulgu
genelde bulgu değildir.

**A tarafında da aynısı yapılır**: sen B'nin `diff-B.patch`'ini aynı ölçütlerle
denetlersin. Kimse kendi yazdığını denetlemez.

---

## Modlar

### İkiz (varsayılan)
A ve B aynı işi **bağımsız** yapar, sonra karşılaştırılır. B'ye A'nın planı
plan üretmeden önce **gösterilmez**. En pahalı, en çok bilgi veren mod.

### Paylaşımlı (B = denetçi)
Kullanıcı "planımı ver, eleştirsin" dediğinde. A'nın planı görev dosyasına
gömülür, B kendi planını yapmaz — denetler. Daha ucuz, ama **anchoring** vardır:
B büyük ihtimalle A'nın çerçevesini kabul eder ve yalnız içeride hata arar.
Defterde mod `paylasimli` olarak etiketlenir ki sonradan güven derecesi bilinsin.

### Fan-out (aynı iş değil, farklı işler)
Bağımsız N alt iş, N çocuk, karşılaştırma yok — birleştirme var. Geniş keşif
için: "şu 4 modülü ayrı ayrı incele". Her çocuk kendi görev dosyasını alır,
`scripts/ikiz.ps1 -GorevKlasoru` ile toplu çalıştırılır. Defterde tek girdi
açılır; karşılaştırma tabloları yerine bulgu birleşimi yazılır.

### Çok turlu çocuk
Çocuğa devam sorusu sorulacaksa `--session-id <uuid>` ile başlat, sonra
`-r <uuid>` ile sürdür. Bağlamı korur, soğuk başlangıcı ikinci kez ödemezsin.

---

## Karşılaştırmayı yaparken

1. **Adım eşleştir**, cümle karşılaştırma. Aynı şeyi farklı kelimeyle söyleyen
   iki adım aynıdır; farklı sırayla yapılan aynı iki adım **farklıdır**.
2. **Yalnız birinde olan adım = incelenecek fark.** İki sonuç: ya diğeri
   atlamıştır (bulgu), ya gereksizdir (gerekçe yaz).
3. **Aynı yeri farklı çözdülerse** gereksinim belirsizdir → kullanıcıya sor.
4. **B'nin bulgusunu kanıtıyla doğrula.** Dosya:satır oku. Doğrulanmamış bulgu
   uygulanmaz.
5. **Örtüşme de sonuçtur.** İki bağımsız ajan aynı çözüme vardıysa bu, o
   değişikliğe duyulan güveni artırır; deftere öyle yaz.
