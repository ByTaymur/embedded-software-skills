# embedded-software-skills

## İçerik

### skills/
| Skill | Ne yapar |
|-------|----------|
| `stm32-firmware-workflow` | STM32/Cortex-M firmware yaşam döngüsü çalışma çerçevesi (toggle'lı; scope guard, CubeMX-first, non-blocking, register doğrulama, build/flash, git). **Kendi `references/` (8) + `commands/` (3) klasörleriyle gelir** — deponun en olgun örneği. |
| `firmware-source-editor` | Embedded firmware kaynak (`.c`/`.h`) düzenleyici + oturum QA log deseni. Build/flash yapmaz — hafif giriş noktası. |
| [`embedded-ai-tool`](skills/embedded-ai-tool/SKILL.md) | ST-Link/uyumlu prob + OpenOCD ile profil tabanlı canlı okuma, ELF/AXF sembolleri, iz kaydı, UID/build doğrulama ve istenen derleme/yazma/flash; ayrıca flash'a yazmadan RAM'den pin/çevre birimi kontrolü, yapay zekâ için MCP köprüsü (`eat mcp`) ve probsuz hedefler için seri bağlantılı stub (alpha; kart kanıtı `references/live-control.md` tablosunda). Kendi Python aracı, testleri ve kullanım referanslarıyla taşınabilir. |
| `multi-model-pipeline` | 3-aşamalı çok-modelli akıl yürütme zinciri (parse → reason → write). Script kendi klasöründe (`multi_model_pipeline.py`). |
| `ikiz` | İki AI ajanın **aynı işi aynı anda bağımsız** yapıp çapraz kontrol etmesi protokolü. Terminalden `claude -p` ile ikinci ajan başlatılır; iki plan ve iki uygulama karşılaştırılır, her karşılaştırma kalıcı `IKIZ-DEFTERI.md`'ye işlenir. Kendi `references/` (4) + `scripts/` (ps1/sh) klasörleriyle gelir. |
| `obsidian-agent` | Obsidian vault'a QA / günlük / karar notu yazma-okuma (MCP). Vault yolu projenin bellek dosyasından. |
| `third-party/dashboarding` | Grafana dashboard oluşturma/düzenleme. *Dış kaynak* (Grafana), gözlemlenebilirlik alanı. |
| `third-party/dd-logs` | Datadog log yönetimi. *Dış kaynak* (Datadog), gözlemlenebilirlik alanı. |

> `third-party/` = başka repo'lardan vendor edilmiş, farklı alan skill'leri. Kaynakları her SKILL.md'nin `metadata.source` alanında izlenir.

### commands/
| Komut | Ne yapar |
|-------|----------|
| `firmware-status` | Firmware/kontrol sisteminin konfigürasyon durum raporu (proje-agnostik). |

> Oturum komutları (`session-start`, `session-end`, `new-project`) **tek kaynak ilkesi** gereği ait oldukları skill'in içinde yaşar: `skills/stm32-firmware-workflow/commands/`. Kök `commands/` yalnızca tek bir skill'e bağlı olmayan komutlar içindir.

### agents/
| Agent | Ne yapar |
|-------|----------|
| `code-reviewer` | Kapsamlı kod incelemesi (kalite/güvenlik/performans). Salt-okunur. |
| `code-simplifier` | Davranışı bozmadan sadeleştirme/refactor. |
| `code-skeptic` | Şüpheci/adversaryal doğrulama — "logları göster yoksa olmadı". Kuralları projenin kendi bellek dosyasından okur. |

## Kurulum

Bir skill'i **global** (tüm projeler) kullanmak için, aracın skill dizinine kopyala. Claude Code örneği:
```bash
cp -r skills/<skill-adı> ~/.claude/skills/
```

Sadece **bir projede** kullanmak için, projenin köküne (aracın beklediği dizine):
```bash
cp -r skills/<skill-adı> <proje>/.claude/skills/
```

Komutlar için `commands/`, agent'lar için `agents/` klasörünü aynı şekilde hedefe kopyala. Değişmezlerin senkron kalması için kopya yerine **symlink** de kullanılabilir. Farklı araçlar farklı dizin/uzantı bekleyebilir; içerik nötr olduğu için tanımlar taşınabilir kalır.

`embedded-ai-tool` için `python -m pip install "<skill-klasörü>"` Python bağımlılıklarını
ve `eat` komutunu kurar. Skill'in tamamı kopyalanır; doğrudan giriş dosyası
`scripts/eat.py` her çalışma dizininden kullanılabilir. Kart profili ve kayıtları
hedef projede tutulur. [Kurulum ve kullanım](skills/embedded-ai-tool/references/usage.md).

Araç şu anda **alpha** aşamasındadır. ST-Link erişimi OpenOCD üzerinden sağlanır;
doğrudan ST-Link backend'i yoktur ve gerçek kart uyumluluğu henüz doğrulanmamıştır.
[Destek matrisi](skills/embedded-ai-tool/README.md) ve
[açık kaynak yayın incelemesi](docs/notes/open-source-readiness.md).

## İlkeler (bakım kuralı)

- **Nötrlük denetimi:** depoya girecek her dosya için `kilo`, `cline`, proje adları, mutlak yollar, pin/parametre sabitleri aranır — sonuç boş olmalı.
- **Her skill kendi kendine yeter:** kendi `commands/` ve `references/`'ını taşır. Skill'e bağlı komut o skill'in içindedir.
- **Progressive disclosure:** SKILL.md kısa; ağır detay `references/`'ta ve talep üzerine yüklenir (bkz. `stm32-firmware-workflow`). Bu desen standarttır — daha az bağlam, daha az token.
- **Ham çıktı girmez:** build log'u, workspace dosyası, dev artefaktı depoya konmaz (bkz. `.gitignore`).

## Lisans

Bu depo [MIT lisansı](LICENSE) ile lisanslanmıştır.

**İstisna:** `skills/third-party/` altındaki skill'ler dış kaynaklardan vendor edilmiştir ve **kendi lisanslarını taşır** — `dashboarding` (Grafana, Apache-2.0) ve `dd-logs` (Datadog, MIT). Her birinin `LICENSE` dosyası kendi klasöründedir ve korunmalıdır.

