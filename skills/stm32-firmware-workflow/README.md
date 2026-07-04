# stm32-firmware-workflow

STM32 / ARM Cortex-M firmware projelerinde kıdemli gömülü mühendis çalışma çerçevesini Claude Code'a uygulatan, **proje-agnostik ve modüler** bir skill. Bir kez kur, tüm projelerinde kullan; özellikleri tek tek aç/kapat.

> **Dil:** Skill'in tüm iç içeriği İngilizce; ama AI seninle **Türkçe** konuşur.

## En önemli iki davranış

- **Scope guard:** İstediğin işin dışına çıkacak her durumda (başka dosya/fonksiyona dokunma, refactor, istenmeyen parametre/özellik) önce **tek satır uyarır ve onayını bekler.** Varsayımla genişletmez.
- **Minimum iş yükü:** Her zaman en az satır/dosyaya dokunan, append-öncelikli, ekstra üretmeyen değişiklik. İki çözüm varsa az değiştireni seçer.

## Kurulum — VS Code (projeye at, "kullan" de)

Claude Code'un VS Code eklentisi, workspace içindeki `.claude/skills/` klasörünü okur. Yani skill'i projenin içine atman yeterli:

```bash
# proje kökünde:
mkdir -p .claude/skills
unzip stm32-firmware-workflow.zip -d .claude/skills/
# (veya klasörü elle .claude/skills/ içine sürükle-bırak)
```
Klasör yapısı şöyle olmalı (çift iç içe OLMAMALI):
```
<proje>/.claude/skills/stm32-firmware-workflow/SKILL.md
```
Sonra VS Code'da Claude Code oturumunu **yeniden başlat**. Tetikleyiciler (STM32, .ioc, TIM/ADC/DMA, register...) eşleşince otomatik devreye girer. Garanti istersen:

> Bu projede `stm32-firmware-workflow` skill'ini kullan.

Tüm projelerde geçerli olsun istersen `.claude/skills/` yerine `~/.claude/skills/` içine koy.

Doğrulama: oturumda `/skills` → listede `stm32-firmware-workflow` görünmeli.

## Özellikleri aç/kapat (toggle)

Skill modüler. Her özellik açılıp kapanabilir. Toggle'lar **projenin kök `CLAUDE.md`'sindeki "0. Feature Toggles" bloğunda** durur; `[x]` açık, `[ ]` kapalı.

```
## 0. Feature Toggles
- [x] scope_guard          # konu dışına çıkmadan uyar + onay al
- [x] min_workload         # en az değişiklik
- [x] cubemx_first         # .ioc otoritesi (CubeMX yoksa: [ ])
- [x] non_blocking         # HAL_Delay yasak
- [x] task_placement       # ISR vs background
- [x] register_verify      # register/AF'yi datasheet'e doğrula
- [x] single_source_params # sabitler tek header'da
- [x] deep_engineering     # derin gömülü referans
- [x] doc_sync             # CLAUDE.md'yi aynı commit'te güncelle
- [ ] git_protocol         # branch-per-session + commit + günlük
- [x] onboarding           # yeni projede tam soru akışı
- [x] terse_output         # kısa cevap
```

`CLAUDE.md`'de bu blok yoksa varsayılanlar geçerli (bkz. `references/feature-toggles.md`). Ayrıca konuşma içinde "git_protocol'ü aç" / "cubemx_first'ü kapat" dersen Claude bu bloğu düzenler.

## İki katman

- **ANA KURALLAR = skill** (her projede): scope guard, min iş yükü, CubeMX-first, non-blocking, ISR/background, register/AF doğruluğu, parametre tek-kaynağı, mühendislik akışı, build/flash, git.
- **ALT KURALLAR = her repo `CLAUDE.md`'si** (projeye özel): MCU, detaylı pinout, clock tree, peripheral/DMA/IRQ, parametreler, mimari, bilinen sorunlar, build/flash + **bu projenin toggle'ları.**

## Yeni proje davranışı

Repo'da `CLAUDE.md` yoksa ve `onboarding` açıksa skill tahmin etmez: senden (Türkçe) detaylı bilgi ister — özellikle pinlerin yön/AF/pull/hız/aktif-seviye ve PCB tuzakları — şablondan `CLAUDE.md` üretir, onaylatır, sonra çalışır.

## İçerik

```
stm32-firmware-workflow/
├── SKILL.md                       # orkestratör: dil + toggle + scope guard + min workload + akış
├── README.md
├── references/
│   ├── feature-toggles.md         # toggle listesi + varsayılanlar
│   ├── new-project-bootstrap.md   # yeni proje: detaylı kural/pin/PCB toplama
│   ├── CLAUDE.md.template          # alt-kural şablonu (toggle bloğu dahil)
│   ├── coding-rules.md             # çalışma disiplini detay
│   ├── embedded-engineering.md     # MUST/MUST NOT, ISR, DMA/cache, doğrulama
│   ├── toolchain-build-flash.md    # build/flash + sorun-giderme
│   └── git-workflow.md             # dosya dizilimi, branch, commit, günlük
└── commands/
    ├── new-project.md
    ├── session-start.md
    └── session-end.md
```
