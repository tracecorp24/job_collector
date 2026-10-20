# Tarama verimliliği — 17 Ekim 2026

**Sonuç:** Önce kartları toplamak listeyi erken hazırlar. Detay önbelleğini korumak
ise tekrar aramalardaki dış istekleri azaltır. Bütün ilanlar yeniyse detayları
ertelemek toplam indirme sayısını azaltmaz.

## Canlı küçük örnek

Arama: **Python Developer / Istanbul, Turkey**, en yeniden sıralama, **5 ilan hedefi**.
İstekler bu bilgisayardan yapıldı; üretim VPS'sinin hız ölçümü değildir. Ayrı test
veritabanı ve ortak kaynak bekleme kaydı kullanıldı. Üretim ilanları değiştirilmedi.
Yapay zekâ API'si kullanılmadı; kurallı analiz açıktı.

| Deneme | Liste isteği | Detay isteği | Toplam | Süre | Sonuç |
| --- | ---: | ---: | ---: | ---: | --- |
| İlk tarama, detaylar hemen | 1 | 5 | 6 | 34,27 sn | 4 tam ilan; 5. detayda HTTP 429 |
| Silme sonrası ilk tekrar | 1 | 0 | 1 | 0,53 sn | Liste isteği HTTP 429; sonuç alınamadı |
| Bekleme sonrası, önce kartlar | 1 | 1 | 2 | 14,83 sn | 4 detay önbellekten; eksik 1 detay indirildi |
| Beşi de silindikten sonra aynı arama | 1 | 0 | 1 | **0,99 sn** | **5 detay önbellekten; yeni detay isteği yok** |

Son iki denemede beş kartın işlenmesi sırasıyla **1,08 sn** ve **0,99 sn** sürdü.
İlk kart ilk taramada 8,51 sn; önce kartlar yönteminde 0,81 sn sonra işlendi.
Kaynak 10 kart döndürdü; test hedefi beş olduğu için ilk beş kullanıldı.

Kaynak kısıtlamaları sırasında normal 60/120 saniyelik bekleme ve artan istek
aralığı korundu. İlk tarama eksik tamamlandı ve önbellek durumu farklıydı: bu
tablodan saf bir "34 kat hızlandı" sonucu çıkarılamaz. Doğrudan doğrulanan bulgu,
son tekrarda aynı beş ilan için yalnızca bir liste isteğinin yeterli olmasıdır.

Her başarılı deneme sonrası sadece testte işlenen ilanlar uygulamanın çöp kutusu
API'siyle gizlendi. Yeniden arama gizlenmiş ilanları kendiliğinden geri getirmedi.
Son durumda test havuzunda **5 gizli ilan, 5 detay önbelleği, 4 arama kaydı,
193 arama olayı ve 14 arama–ilan bağlantısı** kaldı; görünür ilan sayısı sıfır.

## Aynı yanıtlarla kontrollü karşılaştırma

İlk canlı denemede başarıyla alınan dört ilanın HTML yanıtları kaydedildi.
Her yöntem ayrı boş test havuzunda başlatıldı; ardından sonuçlar silinip arama
tekrarlandı. Bu bölümde ağ erişimi yapılmadı. Süreler yalnızca yerel işleme
süresidir; LinkedIn ağ gecikmesini ve zorunlu istek aralıklarını içermez.

| Yöntem | Liste hazır | Tüm detaylar hazır | Dış istek eşdeğeri |
| --- | ---: | ---: | ---: |
| Detayları hemen, ilk toplama | 0,82 sn | 0,82 sn | 1 liste + 4 detay |
| Önce kartlar, ilk toplama | 0,33 sn | 0,82 sn | 1 liste + 4 detay |
| Detayları hemen, silme sonrası tekrar | 0,32 sn | 0,32 sn | 1 liste + 0 detay |
| Önce kartlar, silme sonrası tekrar | 0,30 sn | 0,30 sn | 1 liste + 0 detay |

Her iki yöntemde de tekrar aramada dört önbellek eşleşmesi görüldü. Tekrar aramanın
5 yerine 1 istek kullanması **%80 daha az istek** demektir. Bu avantaj mevcut
önbelleğin korunmasından gelir; tamamını yeni kodun kazancı olarak değerlendirmemek
gerekir. Küçük CPU süreleri tek örnektir ve genellenebilir hız katsayısı değildir.

## Uygulanan iyileştirmeler

- Bir sayfadaki kartlar bir kez ayrıştırılıyor; detay önbelleği topluca okunuyor.
- Kartı değişen bilinen ilanların detay yenilemesi de erteleniyor. Önceki açıklama,
  yenisi gelene kadar korunuyor; eski açıklama yeni ve güncel veri diye önbelleğe alınmıyor.
- Detay tamamlayıcı, ağ isteğinden hemen önce önbelleği kontrol ediyor. Başka bir
  aramanın getirdiği açıklama varsa tekrar indirmiyor.
- Bekleyen işler mevcut benzersiz kaynak–ilan kaydı üzerinden tamamlanıyor.
  Aynı ilan farklı aramalarda bulunsa da tek kayıt ve tek bekleyen detay kalıyor.
- Sayfalama dönen kart sayısı kadar ilerliyor. Devam noktasında gerçek offset
  saklanıyor; eski devam noktaları da destekleniyor. Bu canlı örnekte sayfa boyutu
  10 olduğundan buradan ek bir hız kazancı ölçülmedi. Değişken boyut, tekrarlı ve
  hatalı kart içeren sayfalar otomatik testlerle doğrulandı.
- Geçici 404/410 önbelleği süresi dolunca yeniden değerlendiriliyor.
- Çalışma klasöründeki yeni meslek alanlarının liste değerleri için JSON saklama
  uyumluluğu düzeltildi; mevcut ilan güncellemelerinde bu alanlar da korunuyor.

## Doğrulama ve tekrar çalıştırma

Sekiz yeni davranış testi; sil–yeniden ara, geçmiş ve önbellek korunması, örtüşen
aramaların tekilleştirilmesi, değişen kartın ertelenmesi, son anda önbellek kullanımı,
eski açıklamanın yanlış önbelleğe alınmaması, geçici olumsuz önbellek ve değişken
sayfalama/devam noktalarını kapsıyor.

Görev başında çalışma klasöründe başka değişiklikler de devam ediyordu. Karşılaştırma
için başlangıç Git sürümü saklandı; yalnızca tarama değişiklikleri eklenmiş izole
kopyada **119 test geçti**. Ardından güncel çalışma klasörünün **115 testinin
tamamı da 42,27 saniyede geçti**; sekiz yeni verimlilik testi bu sayıya dahildir.
İki test kümesinin kapsamları farklıdır; sayıları birbirine eklenmemelidir.
Güncel çıktı `.qa/efficiency-20261017/workspace-tests-final.log` dosyasında tutuluyor.

Tekrar kullanılabilir araç: `scripts/benchmark_scrape.py`. Canlı mod normal
kaynak sınırlarına uyar; kayıtlı yanıt modu ağa asla geri dönmez. Çıktılar yalnızca
deponun `.qa/` dizinine yazılabilir. Aynı rapor etiketi üzerine yazılmaz.

Örnek kayıtlı yanıt testi (yeni çıktı klasörü/etiketi seçilmeli):

```powershell
.\.venv\Scripts\python.exe -B scripts/benchmark_scrape.py --output .qa/tekrar-deneme --label ilk --mode deferred --limit 4 --delete-after --replay .qa/efficiency-20261017/live-immediate/responses.jsonl
.\.venv\Scripts\python.exe -B scripts/benchmark_scrape.py --output .qa/tekrar-deneme --label silme-sonrasi --mode deferred --limit 4 --delete-after --replay .qa/efficiency-20261017/live-immediate/responses.jsonl
```

Ham canlı ölçümler: `.qa/efficiency-20261017/live-immediate/*.json`.
İstek/işlem olayları: aynı dizindeki `*-events.jsonl` dosyaları.
Saklanan test sistemi: aynı dizindeki `jobs.db` ve `searches/`.
Kontrollü ölçümler: `replay-immediate/` ve `replay-deferred/`.

Değişiklikler yerel çalışma klasöründe uygulanmıştır; bu çalışma kapsamında canlı
siteye dağıtım yapılmamıştır.
