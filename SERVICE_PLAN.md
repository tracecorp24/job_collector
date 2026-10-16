# Servis güncelleme planı

1. İptal edilen görevi eski taslak kaydının yeniden etkinleştirmesini engelle.
2. Başarısız ilan işlemede checkpoint'i ilerletme; hatayı görünür ve devam edilebilir tut.
3. İçerik değişince eski embedding'i temizle.
4. Dosya dışa aktarımlarını durdurma/duraklatma/hedef değişikliklerinde DB ile eşleştir.
5. Retry-After süresini koruyan, artan beklemeli otonom kaynak politikası uygula.
6. Kalıcı otomatik devam, yeniden başlatma kurtarma ve tekrarlı toplama ekle.
7. Sürümlü, anahtar korumalı API ve işlemsel değişiklik günlüğü ekle.
8. Servis sağlık bilgisi, kullanım belgeleri ve dağıtım örneği hazırla.
9. İzole regresyon testleri; canlı DB yedeği; kontrollü yerel güncelleme.

Kaynak beklemesi hiçbir zaman kısaltılmayacak. Kullanıcının duraklattığı veya
durdurduğu iş otomatik açılmayacak. Güvenlik doğrulaması aşılmayacak; uzun
aralıklı normal erişim denemeleri yapılacak. Tek collector süreci kullanılacak.
