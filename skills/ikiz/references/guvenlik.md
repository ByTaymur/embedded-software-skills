# Güvenlik, izolasyon ve maliyet

## 1. İzin matrisi — aşamaya göre araç kümesi

| Aşama | `--tools` | `--allowedTools` | `--permission-mode` |
|---|---|---|---|
| Plan (Aşama 1) | `Read,Grep,Glob` | gerekmez | `default` |
| Keşif / analiz | `Read,Grep,Glob` | gerekmez | `default` |
| Build/test çalıştırma | `Read,Grep,Glob,Bash` | `"Bash(<tam komut>:*)"` | `default` |
| Uygulama (Aşama 2) | `Read,Grep,Glob,Edit,Write,Bash` | ihtiyaç kadar | `acceptEdits` |
| Çapraz kontrol (Aşama 3) | `Read,Grep,Glob` | gerekmez | `default` |

Kural: **en dar küme**. Salt-okunur araçlar izin istemez ve hiçbir şeyi bozamaz;
aşamaların çoğu salt-okunurdur. Yazma yalnızca Aşama 2'de açılır.

## 2. Yazma izolasyonu — git worktree

Aynı worktree'de iki yazıcı ajan birbirinin düzenlemesini bozar: A bir dosyayı
okur, B yazar, A eski içeriğin üstüne yazar. Sessiz veri kaybıdır.

```bash
git worktree add ../<repo>-ikiz-B -b ikiz/<is-slug>
# B bu dizinde çalışır
git -C ../<repo>-ikiz-B diff > .ikiz/<is-slug>/diff-B.patch
```

- Worktree **silinmez** — kullanıcı inceleyebilsin diye durur.
  Temizlik: `git worktree remove ../<repo>-ikiz-B` (kullanıcı istediğinde).
- B'nin dalı ana dala **merge edilmez**; kararı A verir, değişikliği A uygular.
- `scripts/ikiz.ps1 -Worktree` bunu otomatik yapar.

## 3. Git yasağı

Çocuk ajan **commit, push, merge, rebase, tag, remote** işlemi yapmaz. Git
disiplini ebeveyndedir. Uygulama:

```
--disallowedTools "Bash(git commit:*) Bash(git push:*) Bash(git merge:*)"
```

ve görev dosyasının **Sınırlar** bölümünde açık cümleyle.

## 4. Özyineleme (süreç bombası)

Çocuk ortamı miras alır; hiçbir kilit yoksa çocuk da bu skill'i tetikleyip
torun doğurur — üstel büyüme.

Üç katmanlı kilit, üçü birden kullanılır:

1. `CLAUDE_IKIZ_DERINLIK=1` ortam değişkeni (script otomatik verir),
2. `--append-system-prompt "... Delege etme, alt ajan başlatma."`,
3. gerekiyorsa `--disable-slash-commands` (çocukta skill'ler tamamen kapanır).

Skill'in ilk kuralı: **derinlik ≥ 1 iken delegasyon yok.**

## 5. Yasak: izin atlatma

`--dangerously-skip-permissions` ve `--allow-dangerously-skip-permissions`
gerçek repoda **kullanılmaz**. Bu bayraklarla çalışan çocuk `rm`, `git push`,
ağ erişimi dahil her şeyi kapısız yapar. Yalnız internet erişimi olmayan, atılabilir
bir sandbox için düşünülebilir — bu skill kapsamında değildir.

## 6. Sır sızıntısı

Prompt'lar **diske yazılır** (oturum dosyaları, `.ikiz/` görev dosyaları,
script çıktıları). Token, parola, API anahtarı, `.env` içeriği prompt'a konmaz.
Gerekiyorsa çocuğa dosya **yolunu** ver, içeriğini değil; okumayı o yapsın.

`.gitignore`'a ekle:

```
.ikiz/
```

`IKIZ-DEFTERI.md` **izlenir** (kalıcı kayıt), yardımcı dosyalar izlenmez.

## 7. Maliyet kontrolü

- Her çocuk ~20k token soğuk başlangıç ödetir (ölçüldü). Küçük iş delege edilmez.
- **Varsayılan model opus'tur** — ikinci görüşün değeri modele bağlıdır, ucuz
  modelden gelen onay protokolün amacını boşa çıkarır. Bedeli: soğuk başlangıç
  opus fiyatından ödenir (ölçülen tek çağrı ≈ $0.13). Ucuz modele düşürmek
  bilinçli bir karardır ve deftere yazılır.
- Eşzamanlılık **2–4** ile sınırlı. Fazlası hız kazandırmaz; maliyet, rate-limit
  ve doğrulanamayan çıktı üretir.
- API-key kullanımında `--max-budget-usd` ile tavan koy.
- Toplu iş başlatmadan önce **tek çağrıyla** maliyeti ölç
  (`references/komut-sozlugu.md` §Tuzak 1).
- Maliyeti deftere yaz — hangi işin ne tuttuğu zamanla görünür olsun.

## 8. Zaman aşımı ve asılma

Çocuk ajan takılabilir (izin bekleyemez ama sonsuz döngüye girebilir).
`scripts/ikiz.ps1 -Zaman <saniye>` tavan koyar; aşınca süreç sonlandırılır ve
sonuç **başarısız** sayılır. Zaman aşımına uğrayan iş defterde "tek taraflı"
etiketiyle kalır — yarım çıktı sonuç yerine geçmez.

## 9. Kullanıcıya sorma eşiği

| Durum | Sor |
|---|---|
| Salt-okunur plan/analiz/çapraz kontrol | Hayır |
| Oturumdaki **ilk yazan** çocuk | **Evet** |
| Worktree açma | Hayır (izole ve geri alınabilir) |
| Ana worktree'de çocuğa yazdırma | **Evet** — ve tercihen yapma |
| Çocuk sayısı > 4 | **Evet** (maliyet) |
