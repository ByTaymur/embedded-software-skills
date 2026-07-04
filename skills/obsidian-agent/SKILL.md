---
name: obsidian-agent
description: Obsidian vault okuma/yazma ajanı. Proje notlarını, QA kayıtlarını ve oturum günlüklerini bir Obsidian vault'una yazar ve oradan okur. MCP üzerinden çalışır. Vault yolu ve klasör yapısı proje CLAUDE.md'de tanımlanır.
---

# obsidian-agent

Bir Obsidian vault'unu MCP aracılığıyla yöneten skill. Proje notlarını, teknik QA kayıtlarını, oturum günlüklerini ve tasarım kararlarını vault'a yazar / vault'tan okur.

## Yapılandırma (projeye özel)

Bu skill proje-bağımsızdır. Şu iki değer **proje `CLAUDE.md`'sinden** okunur; skill içine gömülmez:

| Ayar | Nereden | Örnek |
|------|---------|-------|
| Vault yolu | proje `CLAUDE.md` | `<vault-kök-yolu>` |
| Kök klasör | proje `CLAUDE.md` | `<PROJE-ADI>/` (örn. proje kısaltması) |

Proje `CLAUDE.md`'de bu değerler yoksa kullanıcıya (Türkçe) sor; tahmin etme.

## Vault yapısı (önerilen)

```
<VAULT>/
└── <PROJE-ADI>/
    ├── QA/            ← Teknik soru-cevaplar
    │   └── YYYY-MM-DD-konu.md
    ├── Gunluk/        ← Oturum günlükleri (session-end'den gelir)
    │   └── YYYY-MM-DD.md
    └── Kararlar/      ← Önemli tasarım kararları
        └── YYYY-MM-DD-karar.md
```

## MCP araçları

Bu skill `obsidian` MCP sunucusunun araçlarını kullanır:

| Araç | Kullanım |
|------|----------|
| `mcp__obsidian__read_note` | Vault'tan not oku |
| `mcp__obsidian__create_note` | Yeni not oluştur |
| `mcp__obsidian__search_notes` | Vault'ta ara |
| `mcp__obsidian__list_notes` | Notları listele |

## Tetikleyiciler

- `/obsidian-agent` komutu
- "vault'a yaz", "obsidian'a kaydet", "not al" ifadeleri
- `session-end` komutu çalışırken (günlük kaydı)

## QA notu şablonu

```markdown
---
tags: [<proje>, qa]
date: YYYY-MM-DD
file: <ilgili dosya>
---

# S: <sorunun kısa başlığı>

**Soru:** <tam soru>

**Cevap:** <teknik cevap, karar, öğrenilen bilgi>

**İlgili dosya:** `<dosya yolu>`
```

## Oturum günlüğü şablonu

```markdown
---
tags: [<proje>, session-log]
date: YYYY-MM-DD
branch: <branch adı>
---

## YYYY-MM-DD

**Branch:** <branch>
**Yapılan:** <kısa özet>
**Değiştirilen dosyalar:** <liste>
**Sonuç:** <ne elde edildi>
**Sonraki adım:** <ne yapılacak>
```

## Karar notu şablonu

```markdown
---
tags: [<proje>, karar]
date: YYYY-MM-DD
---

# Karar: <başlık>

**Neden:** <gerekçe>
**Seçilen:** <seçilen yol>
**Alternatifler:** <diğer seçenekler>
**Etki:** <hangi dosyalar/sistemler etkilendi>
```

## Önemli

- MCP sunucusu: `obsidian` (`.mcp.json`'da tanımlı, `claude mcp list`'te ✓ Connected olmalı).
- Not yoksa oluştur, varsa üstüne ekle (üzerine yazma).
- Vault yolu ve proje kök klasörü proje `CLAUDE.md`'den gelir — buraya sabit değer yazma.
