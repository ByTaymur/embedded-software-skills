---
name: multi-model-pipeline
description: 3-aşamalı çok modelli akıl yürütme pipeline'ı. Karmaşık teknik sorular için Haiku (parse) → Opus (reasoning) → Sonnet (write) zinciri çalıştırır. Script bu skill klasöründeki multi_model_pipeline.py.
---

# multi-model-pipeline

Karmaşık bir soru veya analiz görevi geldiğinde bu skill devreye girer.

## Ne yapar

```
Kullanıcı sorusu
  → Stage 1 (Haiku)   : soruyu parse et, sıkıştır
  → Stage 2 (Opus)    : derin akıl yürüt, plan oluştur
  → Stage 3 (Sonnet)  : temiz, net cevap yaz
```

## Tetikleyiciler

Bu skill şu durumlarda çağrılır:
- Kullanıcı `/multi-pipeline` yazar
- "derin analiz", "detaylı araştır", "3 aşamalı" gibi ifadeler

## Çalıştırma adımları

1. Kullanıcının sorusunu al.
2. Bu skill klasöründeki script'i çalıştır:
   ```bash
   python "<bu skill klasörü>/multi_model_pipeline.py" "<kullanicinin_sorusu>"
   ```
   Script argümansız çağrılırsa soruyu stdin'den okur.
3. Çıktıyı kullanıcıya göster.

## Gereksinimler

- `ANTHROPIC_API_KEY` ortam değişkeni ayarlı olmalı.
- `anthropic` Python paketi kurulu olmalı (`pip install anthropic`).
- Script: `multi_model_pipeline.py` (bu skill klasörünün içinde, kendine yeterli).

## Model kimlikleri

Aşamaların modelleri script'in başındaki fonksiyonlarda tanımlıdır (`stage1_read`, `stage2_reason`, `stage3_write`). Yeni model sürümü çıkınca yalnızca oradaki `model="..."` satırlarını güncelle.

## Hata durumu

Eğer "credit balance is too low" hatası gelirse:
- console.anthropic.com → Plans & Billing → kredi ekle.
- API key ayarlıysa kredi ekleyince direkt çalışır.

## Örnek kullanım

```
/multi-pipeline PID akım kontrolörü nasıl tune edilir?
/multi-pipeline Bu mimaride hangi tasarım riskleri var, sırala?
```
