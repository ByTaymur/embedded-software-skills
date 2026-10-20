---
name: ikiz
description: İki AI ajanın aynı işi aynı anda, birbirinden bağımsız yapması ve sonuçların çapraz kontrol edilmesi protokolü. Terminalden `claude -p` ile ikinci bir Claude Code ajanı başlatılır; önce iki plan, sonra iki uygulama karşılaştırılır, her karşılaştırma kalıcı bir defter .md dosyasına işlenir. Şu durumlarda kullan: "ikiz çalıştır", "çapraz kontrol", "iki ajan aynı işi yapsın", "planımı ikinci bir ajana doğrulat", "delege et", "paralel çalıştır", "headless claude", "second opinion", "cross-check", ya da hatası pahalı olan bir değişikliğe girmeden önce.
---

# ikiz — iki ajan, aynı iş, çapraz kontrol

İkinci bir Claude Code ajanı (**B**) terminalden başlatılır. Sen (**A**) ve B
**aynı işi aynı anda, birbirinizden habersiz** yaparsınız. Sonra iki plan ve iki
uygulama karşılaştırılır; **fark çıkan her yer risk işaretidir**. Bütün
karşılaştırmalar tek bir kalıcı deftere yazılır.

Kullanıcıyla Türkçe konuş.

## Temel ilke: bağımsızlık

B'ye kendi planını **plan üretmeden önce gösterme**. Gösterirsen B onu onaylar
(anchoring) ve ikiz çalışmanın tek değeri olan bağımsız fark kaybolur. Paylaşım
**karşılaştırma aşamasında** yapılır — protokolün tamamı bunun üzerine kurulu.

İstisna: kullanıcı açıkça "planımı ver, eleştirsin" derse `-Mod paylasimli`
kullanılır; o zaman B ikiz değil **denetçi**dir ve defterde öyle etiketlenir.

## Dört aşama

```
   A (sen)                          B (claude -p)
      │                                   │
 1 ── plan-A.md ────┐         ┌──── plan-B.md          ← bağımsız, aynı anda
                    └► KARŞILAŞTIR ◄┘
                          │
                    plan-ORTAK.md                      ← birleşik plan, deftere işlenir
                          │
 2 ── uygula ───────┐     │     ┌──── uygula (ayrı worktree)
      diff-A        └► KARŞILAŞTIR ◄┘   diff-B
                          │
 3 ──   B, A'nın diff'ini denetler ─┐
        A, B'nin diff'ini denetler ─┴► ÇAPRAZ BULGULAR
                          │
 4 ──               KARAR + DEFTER  (IKIZ-DEFTERI.md, append-only)
```

## Ne zaman kullanma

Ucuz değildir: B soğuk başlar, `CLAUDE.md`'yi ve ağacı yeniden okur, kendi
token'ını harcar. Kullanma:

- iş küçük veya tek yönlüyse (tek dosya, tek satır, mekanik düzeltme),
- doğrulama zaten ucuzsa (test var, derleyici yakalıyor),
- sadece "uzun" bir işse — **geniş** veya **hatası pahalı** değilse.

Kullan: donanıma/sahaya giden değişiklik, güvenlik/kilitlenme mantığı, geri
alınması zor refactor, mimari karar, kullanıcının açıkça istediği her durum.

## Ön kontrol (ilk delegasyondan önce, oturumda bir kez)

1. **Derinlik kilidi** — `CLAUDE_IKIZ_DERINLIK` ortam değişkenini oku.
   `1` veya üstüyse **sen zaten B'sin: delege etme, işi kendin yap.** Çocuk
   süreç ortamı miras alır; kilit olmazsa süreç bombası olur.
2. **Binary** — `claude` PATH'te olmayabilir; `scripts/ikiz.ps1` çözer.
3. **Yazma izolasyonu** — B yazacaksa **ayrı git worktree** şart. Aynı worktree'de
   iki yazıcı birbirinin düzenlemesini bozar (`references/guvenlik.md`).
4. **İlk yazma delegasyonunda kullanıcıya sor.** Salt-okunur aşamalar için sorma.

## Aşama 1 — PLAN

1. Kendi planını `.ikiz/<is-slug>/plan-A.md` dosyasına yaz. Aşama listesi,
   dokunulacak dosyalar, riskler, doğrulama yöntemi.
2. Görev dosyasını hazırla (`references/protokol.md` §Görev dosyası) ve B'yi
   **salt-okunur** başlat:
   ```powershell
   & <skill>/scripts/ikiz.ps1 -Gorev .ikiz\<is-slug>\gorev.md `
       -Cikti .ikiz\<is-slug>\plan-B.json
   ```
   Varsayılan model **`claude-opus-5`**. B'nin ucuz modelden gelmesi ikinci
   görüşün değerini düşürür — model düşürmek istersen bilinçli karar ver ve
   deftere yaz. Kısa alias (`opus`, `sonnet`) sessizce yok sayılır: tam kimlik
   kullan (`references/komut-sozlugu.md` §Tuzak 1).
3. İki planı karşılaştır → deftere `## 1. Plan karşılaştırması` tablosu:
   ortak adımlar / yalnız A'da / yalnız B'de / çelişki.
4. **Yalnız birinde olan her adım açıklanır**: ya birleşik plana girer ya da
   defterde neden elendiği yazılır. Sessizce düşürülmez.
5. `plan-ORTAK.md` yaz — uygulama bundan yürür.

## Aşama 2 — UYGULAMA (ikiz)

İkisi de `plan-ORTAK.md`'yi uygular, **aynı anda**:

- **A:** ana worktree'de normal şekilde.
- **B:** `-Worktree` ile açılan izole kopyada, yazma araçları açık.

```powershell
& <skill>/scripts/ikiz.ps1 -Gorev .ikiz\<is-slug>\uygula.md `
    -Cikti .ikiz\<is-slug>\uygula-B.json -Yaz -Worktree
```

Script B'nin worktree'sini açar, işi çalıştırır, `diff-B.patch` üretir ve
worktree'yi **silmez** — inceleyebilesin diye durur.

⚠️ Aynı işin iki uygulaması **birleştirilmez**. Biri seçilir; diğerinden alınan
her fikir defterde tek tek gerekçelendirilir.

## Aşama 3 — ÇAPRAZ KONTROL

Şimdi paylaşım serbest — bağımsızlık aşaması bitti.

1. B'ye A'nın diff'ini ver, denetlet (`references/protokol.md` §Çapraz görev).
2. Sen B'nin diff'ini denetle.
3. Her bulgu için **kanıt** iste ve **doğrula**: iddia edilen dosya/satır var mı,
   gerçekten öyle mi diyor. Çocuk ajanlar satır numarasını kendinden emin uydurur.
4. İki tarafın çelişen bulguları **bastırılmaz**, deftere çelişki olarak yazılır.

Görev bölünmüşse çapraz kontrol zorunludur: kimse kendi yazdığını denetlemez.

## Aşama 4 — KARAR + DEFTER

Defter proje kökünde tek dosyadır: **`IKIZ-DEFTERI.md`**, append-only, en yeni
en üstte. Şablon ve doldurma kuralı: `references/defter-sablonu.md`.

Her iş için deftere şu girer: iş kimliği · iki plan farkı · iki uygulama farkı ·
çapraz bulgular · **hangi çözüm alındı ve neden** · doğrulanmamış kalanlar.

> Projenin kendi kayıt sistemi varsa (değişiklik defteri, günlük vb.) defter
> oraya **link verir**, içerik kopyalanmaz.

## Kırmızı çizgiler

- ❌ `--dangerously-skip-permissions` / `--allow-dangerously-skip-permissions`
  gerçek repoda **kullanılmaz**.
- ❌ B commit/push/merge yapmaz, remote'a dokunmaz. Git A'dadır.
- ❌ Derinlik ≥ 1 iken delegasyon yok.
- ❌ Prompt'a token, parola, `.env` içeriği konmaz — prompt'lar diske yazılır.
- ⚠️ B'nin çıktısı **iddiadır, kanıt değildir**. `is_error`, boş `result` veya
  sıfırdan farklı çıkış kodu = iş başarısız; kendi tahminini onun yerine koyma.
- ⚠️ Kullanıcı B'nin çıktısını görmez. Ona sonucu ve **neyi doğruladığını** anlat,
  ham döküm verme.

## Referanslar

- `references/protokol.md` — görev dosyası şablonları, çapraz görev metinleri,
  paylaşımlı mod, fan-out (aynı iş değil, farklı işler) varyantı.
- `references/defter-sablonu.md` — `IKIZ-DEFTERI.md` yapısı ve doldurma kuralı.
- `references/komut-sozlugu.md` — doğrulanmış `claude` CLI bayrakları, JSON
  sonuç alanları, stdin/exit-code davranışı.
- `references/guvenlik.md` — izin matrisi, worktree izolasyonu, bütçe, özyineleme.
- `scripts/ikiz.ps1` (Windows) · `scripts/ikiz.sh` (bash/Linux) — çocuk ajan
  çalıştırıcı: derinlik kilidi, worktree, paralel, JSON toplama.
