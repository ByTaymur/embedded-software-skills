# Embedded AI Tool açık kaynak yayın incelemesi

Tarih: 2026-10-20

> Bu not o tarihteki durumu anlatır. Güncel kanıt düzeyleri:
> [live-control.md kanıt tablosu](../../skills/embedded-ai-tool/references/live-control.md#durum-kanıt-tablosu).

## Sonuç

`skills/embedded-ai-tool`, açıkça belirtilen sınırlarıyla **alpha sürüm olarak
paylaşılabilecek** duruma getirildi. Bu değerlendirme tüm kartlarda çalıştığı,
kusursuz olduğu veya üretim ortamında doğrulandığı anlamına gelmez. İnceleme yeni
aracın kodu, taşınabilirliği, dağıtım paketi ve depo yayın hijyeni üzerindedir;
depodaki diğer bütün skill'lerin davranışları kapsamlı biçimde test edilmedi.

GitHub'a gönderim, herkese açık yayın veya sürüm etiketi bu çalışma kapsamında
yapılmadı. Gerçek donanıma bağlanılmadı.

## ST-Link ve OpenOCD desteği

Bağlantı zinciri şöyledir:

```text
eat / AI ajanı -> OpenOCD Tcl RPC -> ST-Link veya desteklenen prob -> MCU
```

| Özellik | Durum |
| --- | --- |
| OpenOCD Tcl RPC üzerinden UID, bellek okuma ve izleme | Uygulandı; bilgisayar üzerinde ve donanımsız Tcl testleriyle doğrulandı |
| ST-Link ile bağlantı | OpenOCD üzerinden; gerçek prob/kart doğrulaması bekliyor |
| Doğrudan ST-Link USB, STM32CubeProgrammer veya ST-LINK GDB sunucusu | Uygulanmadı |
| Yazma, halt/resume/reset ve flash | Açık `--execute` gerektirir; gerçek kart doğrulaması bekliyor |
| Uzak sunucuya flash dosyası aktarma | Uygulanmadı; flash yerel/paylaşılan dosya sistemi gerektirir |
| DWARF yapı/dizi çözümleme, breakpoint ve RTOS görünümü | Uygulanmadı |

ST-Link ve OpenOCD iki bağımsız backend değildir. Prob, MCU, prob firmware'i,
OpenOCD sürümü ve seçilen yapılandırmanın birlikte uyumlu olması gerekir.
Profilin UID alanı 8 bit erişimle okunabilir olmalıdır.
Resmî kaynaklar: [OpenOCD adaptör yapılandırması](https://openocd.org/doc/html/Debug-Adapter-Configuration.html)
ve [Tcl RPC API](https://openocd.org/doc/html/Tcl-Scripting-API.html).

## Bu incelemede kapatılan eksikler

- Bağımsız kopyalanan skill ve Python dağıtımına MIT lisansı eklendi.
  Paket README'si, alpha sınıflandırması ve kaynak dağıtım manifesti eklendi.
- Windows/Linux ve Python 3.11/3.14 için GitHub Actions iş akışı eklendi.
- Özel karakterli dosya yollarının Tcl hata yakalama sarmalayıcısını bozması
  giderildi; gerçek OpenOCD yorumlayıcısıyla donanımsız regresyon testi eklendi.
- Hash'i uyuşmayan ELF dosyasının önbellekte geçerli kalması engellendi.
- Build, kaynak arama ve yerel OpenOCD başlatma için gereksiz cihaz UID şartı
  kaldırıldı. Başarısız OpenOCD süreci artık başarı sonucu üretmiyor;
  yapılandırılmış Tcl portu kullanılıyor.
- Sembole dayalı okuma/izleme öncesinde cihazdaki flash içeriği ELF'nin dosyada
  bulunan PT_LOAD bölümleriyle doğrulanıyor. Yalnızca ham adresle okuma bunun
  yerine geçmez.
- Flash için doğrulanmış ELF baytlarının oturuma özel kopyası kullanılıyor;
  eşzamanlı derlemenin yüklenen dosyayı değiştirmesi önleniyor.
- JSON'a sığmayan NaN/Inf değerleri açıklayıcı hata ve ham bayt bilgisiyle
  raporlanıyor. Oturum kayıtlarına profil hash'i ve hedef bağlamı eklendi.
- Yerel profiller, oturumlar, ortam dosyaları ve derleme çıktıları için ignore
  kuralları eklendi; destek sınırları kullanım belgelerine işlendi.

Kod: `skills/embedded-ai-tool/scripts/embedded_ai_tool/core.py` ve `cli.py`.
Kullanım: `skills/embedded-ai-tool/references/usage.md`.

## Doğrulama kanıtı

Yerel ortam Windows, Python 3.14.2 ve xPack OpenOCD 0.12.0 geliştirme sürümüdür.

| Kontrol | Sonuç |
| --- | --- |
| `python -m unittest discover -s skills/embedded-ai-tool/tests -v` | 22 test geçti; yerelde atlanan test yok |
| Ruff, `scripts` ve `tests` | Geçti |
| Skill yapısı doğrulayıcısı | Geçti |
| `git diff --check` | Geçti |
| `python -m build --no-isolation` | Wheel ve kaynak dağıtımı oluşturuldu |
| Paket içerikleri ve metadata | Wheel içinde MIT lisansı; kaynak dağıtımında skill, launcher, referanslar ve testler doğrulandı |
| Geçici dizine wheel kurulumu ve izole Python ile `doctor` | Geçti; donanım doğrulanmış olarak işaretlenmiyor |
| Farklı çalışma dizininden taşınmış skill kullanımı | Otomatik testlerde geçti |
| GitHub Actions YAML yapısı | Kontrol edildi; GitHub üzerinde çalıştırılmadı |
| Gerçek ST-Link/MCU üzerinde çalışma | Yapılmadı |

OpenOCD yorumlayıcı testleri `noinit` ve sahte bellek komutları kullanır; prob
bağlantısını doğrulamaz. Linux ve Python 3.11 matrisinin tanımlanmış olması bu
ortamlarda başarılı çalıştırma kanıtı değildir.

Çalışma ağacında 52 dosya ve mevcut 4 commit üzerinde özel anahtar işaretleri ve
bazı yaygın erişim anahtarı biçimleri tarandı; eşleşme bulunmadı. Bu sınırlı
sezgisel tarama bütün özel bilgilerin yokluğunu garanti etmez. Yerel cihaz
kimlikleri, firmware dosyaları ve oturum kayıtları yayına eklenmemelidir.
Üçüncü taraf skill'lerin mevcut lisans ve kaynak bildirimleri korundu;
bu çalışma kapsamlı bir hukuki lisans denetimi değildir.

## Kararlı sürüm öncesinde kalanlar

1. GitHub CI matrisini çalıştırıp sonuçlarını doğrulamak.
2. Desteklenecek her gerçek prob/MCU birleşimi için model, prob firmware'i,
   OpenOCD sürümü ve yapılandırmasını kaydetmek.
3. UID, sembol adresleri, bilinen bellek değerleri, izleme ve yanlış cihaz/ELF
   reddini gerçek kartta ölçmek.
4. Kullanıcının açıkça yetkilendirdiği test kapsamında RAM yazma/geri okuma,
   halt/resume/reset ve flash/doğrulama işlemlerini denemek; sonrasında uygulamanın
   fiziksel davranışını kontrol etmek.
5. Destek tablosunu yalnızca bu ölçümlerle genişletmek; test edilmemiş kartları
   desteklenmiş veya üretime hazır olarak sunmamak.

Bu nedenle uygun yayın tanımı: **profil tabanlı, OpenOCD üzerinden ST-Link
kullanabilen, donanım kabul testleri bekleyen alpha geliştirme aracı**.
