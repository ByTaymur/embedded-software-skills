# Ölçerek geliştirme dersleri

Bu ilkeler saha operatörü ve canlı firmware inceleme deneyiminden genelleştirildi.
Belirli bir makinenin prosedürleri, özel yetkileri, firmware adresleri ve fiziksel
limitleri skill'e taşınmaz. Her hedef için proje belgesi ve ölçüm esas alınır.

| Gözlem | Uygulama |
|---|---|
| Aynı firmware birden fazla kartta bulunabilir | Her canlı istekte UID denetimi; UID ile yazma aynı Tcl değerlendirmesinde |
| Örneklemeli flash eşleşmesi tam build kanıtı değildir | Dosya destekli PT_LOAD baytlarının tamamını karşılaştır |
| Build değişince RAM adresleri kayabilir | Adresi hash'i sabitlenmiş ELF'ten çöz; sembol tekilliği ve boyutunu denetle |
| Yazma zaman aşımında komut uygulanmış olabilir | Otomatik tekrar yok; önce yeniden kimlik ve durum ölçümü |
| Firmware aynı çıkışı tekrar değiştirebilir | Readback'i fiziksel başarı sayma; uygulama sonucunu izleyerek doğrula |
| Anlık iki okuma aradaki hareketi kaçırabilir | Zaman serisi, gerçek örnek başlangıç/bitişi ve yeterli örnekleme |
| Ham pinin aktif seviyesi ters yorumlanabilir | MCU belgesi ve firmware okuma ifadesiyle doğrula |
| Sensör doygunluğu eşik denetimini etkiler | Eşiği gerçek ölçüm aralığıyla ilişkilendir; başka karttan taşıma |
| Rutin adı bütün davranışı açıklamaz | Tetikleme, yan etkiler, timeout ve çıkış yolunu kaynakta incele |
| Eski belge/ölçüm bugünkü durumu kanıtlamaz | Kaynakta dosya/satır/hash; canlı kayıtta profil, UID ve zaman kullan |

## Sonuç bildirirken

Beklenen ve ölçülen değeri, kayıt yolunu, hangi kaynağın kullanıldığını ve denenmeyen
yolları birlikte belirt. Bilinmeyen değeri sıfır doldurma. Eski kaydın zamanını
yenilemek yeni ölçüm oluşturmaz. Profil limitleri yalnız o donanım/build için geçerlidir.

Birden fazla değişken sırayla okunur; hepsi aynı CPU anına ait değildir. İzleme
gerçek zamanlı motor/ısıtıcı güvenlik denetimi değildir. Kimlik/build eşleşmesi de
donanımın güvenli çalıştığını kanıtlamaz. Uygulama kabul ölçütleri hedef projeden gelir.

Host birim testleri, sahte TCP sunucusu ve adaptör açılmadan çalıştırılan Tcl testleri
kart testi sayılmaz. Gerçek probe, MCU bağlantısı, firmware derlemesi, flash ve fiziksel
davranış ayrı kanıtlanır. Test/derleme yapılmadıysa yapılmış gibi raporlanmaz.
