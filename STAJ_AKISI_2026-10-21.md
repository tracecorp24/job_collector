# Staj fırsatları: Collector → Next Step

## Havuz incelemesi

21 Ekim 2026 tarihinde yerel veritabanı yalnızca okunarak 3.011 geçerli, aktif ilan incelendi.
İlan içeriğine dayalı ayrım: 56 staj, 3 yeni mezun programı, 2 türü belirsiz, 2.950 iş.
Eski `Intern` etiketli 58 ilanın ikisi staj olarak doğrulanamadığı için belirsiz kaldı.

56 stajın 55'inde ücretli/ücretsiz durumu, 55'inde hafta olarak süre, 55'inde
zorunlu/gönüllü ayrımı açıkça çıkarılamadı. Eksik bilgi olumsuz koşul veya sıfır sayı değildir.
Bu sayılar yerel havuza ve mevcut muhafazakâr ayrıştırıcıya aittir; canlı havuz farklı olabilir.

## Collector

- Yeni tarama ekranının başında kuyruk için `Tüm fırsatlar / Staj ilanları` seçilir.
  Staj seçimi kaynak isteğine `f_JT=I` ekler. Kuyruk kaydı, yeniden başlatma ve
  kontrol noktaları bu seçimi korur. Seçim bir ilanı kendiliğinden staj olarak etiketlemez.
- İlk kart kaydedilirken `opportunity_type` belirlenir: `internship`, `graduate`, `job`, `unknown`.
  Bu alan kıdemden ve aramada kullanılan anahtar kelimeden ayrıdır.
- Detay geldikçe dönem, zorunlu/gönüllü durumu, hafta olarak süre ve süre aralığı,
  haftalık gün, ücret durumu, başvuru tarihi, sınıf ve açıkça belirtilmiş bölüm koşulları
  `internship_details` içine kanıt parçalarıyla kaydedilir. Desteklenmeyen veya çelişkili ifadeler
  bilinmiyor olarak korunur; her dil ve tarih biçimi otomatik olarak çözümlenmez.
- International/Internal, stajyerlere mentorluk ve staj programı koordinatörlüğü staj değildir.
  Belirsiz trainee/bursiyer ilanları otomatik olarak staj sayılmaz.
- Alan düzeltme ve yeniden analiz fırsat bilgisini yeniden üretir. Yeni JSON çıktıları,
  `/api/jobs`, `/api/v1/jobs` ve değişiklik akışı bu bilgileri taşır.
- Collector filtre panelinde bağımsız `Fırsat türü` faseti bulunur.

## Next Step

- Dashboard'da `Staj fırsatlarını keşfet` girişi ilgili filtreleri açar; mobilde fırsat çekmecesini de açar.
- Staj, yeni mezun programı, iş ve belirsiz türleri ayrılır. Alan/meslek grubu, konum,
  çalışma biçimi, yetenek eşleşmesi ve staj koşulları birlikte kullanılabilir.
- Dönem, zorunlu/gönüllü, ücret, en fazla süre, haftalık gün ve sınıf koşulları filtrelenir.
  Koşul seçildiğinde o bilgisi eksik ilanlar dahil edilmez. `Konum veya uzaktan` ayrı seçenektir;
  uzaktan çalışma ülke dışından başvuru hakkını garanti etmez.
- Kart ve detay paneli staj koşullarını, son tarihi ve eksik alanları gösterir.
  Ücretli olduğu bilinen fakat tutarı belirtilmeyen ilanlar ayrı anlaşılır.
- `Staj tercihlerim` bölümünde bölüm, sınıf, dönem, staj türü ve haftalık müsait gün kaydedilir.
  Koşul uyuşmazlıkları ve eksik bilgiler yetenek eşleşme yüzdesinden ayrı gösterilir.
- Kayıtlı aramalar staj koşullarını saklar; uygulama açıkken yeni eşleşmeler için tekil
  uygulama içi bildirim üretir. Kayıtlı aramalar mevcut sistemde bu tarayıcıdaki hesaba aittir.
  Arka planda e-posta servisi veya cihazlar arası kayıtlı arama eşitlemesi eklenmedi.
- Aktif koşullar kaldırılabilir etiketlerle gösterilir; boş sonuçta sonuç getirecek
  gevşetmeler önerilir. Kartlar klavyeyle açılır, mobil yerleşim taşma açısından kontrol edilir.

## Geçiş ve çalıştırma

Önce Collector kodu güncellenip normal başlatıcıyla yeniden başlatılır. Mevcut SQLite
şemasına iki alan ve tür indeksi eklenir. İlanlar silinmeden 500'lük partilerde bir kez
yeniden sınıflandırılır; tamamlanma işareti işlemin tekrarlanmasını önler. Kaynak yeniden
taranmaz. Daha sonra Next Step sunucusu ve statik dosyaları güncellenir.

Eski Collector API'sinden tür alanı gelmezse Next Step bunu `Türü belirsiz` olarak gösterir.
Tarihsel JSON dosyaları topluca yeniden yazılmaz; Next Step güncel kaynağı API'den okur.
Bu çalışma kapsamında canlıya dağıtım veya çalışan üretim süreçlerinin yeniden başlatılması yapılmadı.

## Doğrulama

- `tests/test_opportunities.py`: sınıflandırma, yanlış eşleşmeler, eksik/çelişkili koşullar,
  kanıt, ekleme/güncelleme, filtreler ve tekrar çalıştırılabilir eski kayıt geçişi.
- `tests/test_internship_collection.py`: sahte kaynak yanıtı → kaynak filtresi → veritabanı
  → JSON → filtre faseti → servis API'si → değişiklik akışı; kuyruk seçiminin kalıcılığı.
- `next_step_v2/tests/internships.test.mjs`: birleşik koşullar, konum veya uzaktan mantığı,
  öğrenci uygunluğu ve kayıtlı staj aramalarının tekil bildirimi.
- `next_step_v2/tests/backend/test_internships.py`: kaynak verisinin aktarımı ve öğrenci
  tercihleri için profil API'si doğrulaması.
- `next_step_v2/tests/internships.browser.mjs`: gerçek statik dosyalar ve izole sahte API'lerle
  Chrome'da masaüstü/mobil keşif, filtreler, kart, detay, tercih formu ve taşma kontrolü.
  Görüntüler: `next_step_v2/test-results/internships/`.

Mevcut arama, kaynak ve eşleşme testleri de çalıştırıldı. Sandbox içinde zaman aşımına uğrayan
iki mevcut worker senaryosu sandbox dışında tekrar çalıştırılıp geçti.

Sonuçlar: 38 Node ilan/arama testi, 22 mevcut birim testi, 34 Next Step backend testi,
7 Collector sınıflandırma/geçiş testi ve 2 Collector kaynak/API bütünleşme testi geçti.
Chrome masaüstü/mobil senaryosu geçti; sayfa hatası veya yatay taşma görülmedi.

Ek arama regresyonu: `mekanik tasarım` ve `mechanical design` aynı sonuçları üretir.
Mechanical Designer ve ilgili mühendis unvanları aynı meslek kavramına dönüştürülür.
Özgün sorgudaki bilinen meslek kavramı, ek dil çevirilerinde de zorunlu kalır;
genel `design` çevirisi elektrik veya arayüz tasarımı ilanlarını ekleyemez.
