# `claude` CLI sözlüğü — çocuk ajan çalıştırma

Bu dosyadaki bayraklar **`claude --version` = 2.1.25** çıktısından doğrulanmıştır.
Farklı sürümde `claude --help` ile yeniden doğrula; uydurma bayrak kullanma.

## Zorunlu çekirdek

| Bayrak | Anlamı |
|---|---|
| `-p`, `--print` | Etkileşimsiz çalış, cevabı yazdır ve çık. Çocuk ajanın temeli. |
| `--output-format text\|json\|stream-json` | Yalnız `-p` ile. Ayrıştırılacaksa **`json`**. |
| `--model <id>` | Model. **Aşağıdaki tuzağa bak.** |
| `--tools "<liste>"` | Kullanılabilir araç kümesi. `""` = araç yok, `default` = hepsi. |
| `--allowedTools "<liste>"` | İzin sorulmadan kullanılabilecekler (ör. `"Bash(git diff:*) Read"`). |
| `--disallowedTools "<liste>"` | Yasaklananlar. |
| `--permission-mode <mod>` | `default`, `acceptEdits`, `plan`, `dontAsk`, `delegate`, `bypassPermissions`. |
| `--add-dir <dizinler...>` | Çalışma dizini dışında erişilecek ağaçlar. |
| `--append-system-prompt <metin>` | Varsayılan sistem promptuna ekler — çıktı sözleşmesi ve "delege etme" kilidi buraya. |
| `--system-prompt <metin>` | Sistem promptunu **değiştirir**. Dikkat: proje disiplinini de siler. |
| `--json-schema <şema>` | Yapılandırılmış çıktıyı şemaya karşı doğrular. Prompt'la rica etmekten sağlam. |
| `--session-id <uuid>` | Sabit oturum kimliği — çok turlu çocuk için. |
| `-r`, `--resume <id>` | Oturumu sürdür. `--fork-session` ile yeni kimlikle dallandır. |
| `--max-budget-usd <tutar>` | Yalnız `-p` ile. API-key kullanımında harcama tavanı. |
| `--setting-sources <user,project,local>` | Hangi ayar kaynakları yüklensin. |
| `--strict-mcp-config` | Yalnız `--mcp-config` ile verilenler; ortamdaki MCP'leri yok sayar. |
| `--disable-slash-commands` | Çocukta skill'leri kapatır — özyineleme riskini kökten keser. |

## Prompt verme: stdin en güvenlisi

Argüman olarak verilen çok satırlı prompt Windows'ta tırnak/`$`/backtick
yüzünden bozulur. **Doğrulandı:** stdin çalışıyor.

```powershell
Get-Content .\gorev.md -Raw | & $claude -p --output-format json --tools "Read,Grep,Glob"
```

```bash
claude -p --output-format json --tools "Read,Grep,Glob" < gorev.md
```

## JSON sonuç alanları (doğrulandı, v2.1.25)

```json
{
  "type": "result",
  "subtype": "success",
  "is_error": false,
  "duration_ms": 1995,
  "duration_api_ms": 1843,
  "num_turns": 1,
  "result": "<ajanın son cevabı, düz metin>",
  "session_id": "…",
  "total_cost_usd": 0.126,
  "usage": { "input_tokens": 2, "cache_creation_input_tokens": 20167,
             "cache_read_input_tokens": 0, "output_tokens": 6, "…": "…" },
  "modelUsage": { "<model-id>": { "…": "…" } },
  "permission_denials": [],
  "uuid": "…"
}
```

Okuma sırası:

1. `is_error` **ve** süreç çıkış kodu — ikisi de temiz değilse iş başarısızdır.
2. `permission_denials` **boş olmalı**. Dolu ise çocuk bir aracı kullanamamış,
   yani işi eksik yapmıştır — sonucu "tamam" sayma.
3. `result` — asıl cevap. JSON istediysen `result` içinde JSON metni gelir,
   yani **iki kez** ayrıştırırsın.
4. `total_cost_usd`, `duration_ms` — deftere maliyet satırı.

## ⚠️ Tuzak 1: model alias'ı sessizce yok sayılabilir

Bu makinede ölçüldü (kullanıcı ayarlarında model zorlaması **yokken**):

| Verilen | Fiilen ne oldu |
|---|---|
| `--model haiku` | opus fiyatıyla çalıştı ($0.126) — **alias etkisiz** |
| `--model sonnet` | opus fiyatıyla çalıştı ($0.126) — **alias etkisiz** |
| `--model claude-haiku-4-5-20251001` | ucuz çalıştı ($0.0102) — uygulandı |
| `--model claude-sonnet-5` | ucuz çalıştı ($0.0102) — uygulandı |
| `--model claude-opus-5` | kabul edildi, opus fiyatıyla çalıştı ($0.128); `modelUsage` `claude-opus-4-5-20251101` raporladı |

Sonuç: **tam model kimliği kullan**, kısa alias'a güvenme.

`modelUsage` alanı **tutarsız** gözlendi: bir çağrıda verilen modelle uyuşmadı
(haiku kimliği verildiği hâlde opus anahtarı göründü), sonraki çağrıda doğru
gösterdi. Tek başına kanıt sayma; kesin doğrulama **`total_cost_usd`** üzerinden.

> ⚠️ Bu davranış sürüme/hesaba bağlı olabilir. Ucuz model varsayarak toplu iş
> başlatmadan önce **tek bir çağrıyla maliyeti ölç**.

## ⚠️ Tuzak 2: her çocuk ~20k token soğuk başlar

Ölçülen: boş bir görevde bile `cache_creation_input_tokens ≈ 20167`. Çocuk
ajan sistem promptunu ve proje bağlamını sıfırdan yükler. Küçük işi delege etmek
**kendin yapmaktan pahalıdır** — ikiz protokolü hatası pahalı işler içindir.

## ⚠️ Tuzak 3: etkileşimsiz oturumda izin sorulamaz

`-p` modunda izin diyaloğu yoktur; izin gerektiren çağrı **reddedilir** ve
`permission_denials` dolar. Çocuğun gerçekten kullanacağı araçları önceden
`--allowedTools` ile ver, yoksa iş yarım kalır ve bunu ancak alanı okuyarak
fark edersin.

## Çıkış kodu

Başarıda `0`. PowerShell'de `$LASTEXITCODE`, bash'te `$?` ile kontrol et;
`is_error` alanıyla **birlikte** değerlendir.

## Ortam değişkeni kilidi (bu skill'in kuralı)

`CLAUDE_IKIZ_DERINLIK` — ebeveyn `1` yazar, çocuk miras alır. Skill'in ilk
kuralı: değer `1` veya üstüyse **delege etme**. Çocuğa ayrıca
`--append-system-prompt "... Delege etme."` ve gerekirse
`--disable-slash-commands` verilir.
