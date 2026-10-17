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

Kaynak beklemesi ve güvenlik kontrolleri (Retry-After, HTTP 429/999/403 duraklatmaları)
hiçbir zaman hileyle aşılmayacak veya kısaltılmayacak. Kullanıcının duraklattığı veya
durdurduğu iş otomatik açılmayacak.

Bununla birlikte, 76 dakikalık bir koşuda görülen yüksek duraklama oranını azaltmayı denemek
için varsayılan istek aralığı 10 saniye olarak ayarlanmıştır (`JOBAPP_REQUEST_INTERVAL=10.0`,
`JOBAPP_MIN_REQUEST_INTERVAL=10.0`, `%0–15` jitter). Bu ayar yaklaşık 10,75 saniyelik ortalama
aralığa karşılık gelir; 429 hatalarını sıfırladığı veya toplam verimi artırdığı henüz kanıtlanmış
değildir. Etkisi, benzer arama koşullarındaki sonraki koşuların `rate_429` ve `frozen_ratio`
ölçümleriyle doğrulanmalıdır. Tek collector süreci kullanılacak.
