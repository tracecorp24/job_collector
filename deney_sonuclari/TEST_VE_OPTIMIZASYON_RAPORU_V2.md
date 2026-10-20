# Linko Scrapper Light — Test, Doğrulama ve İleri Hızlandırma Analizi Raporu
**Belge:** `v2 - kanıt ve ölçüm sınırları`
**Tarih:** 17 Ekim 2026  
**Kapsam:** Yerel veri örneklemi, birim testleri ve varsayımlı pacing simülasyonunun özeti. İleri optimizasyon başlıkları ölçüm gerektiren hipotezlerdir.

> **Yorum sınırı:** Veritabanı ve HTML sayıları yalnızca bu yerel örneklemi anlatır; ilanların veya şirketlerin dışarıdan doğrulandığını göstermez. HTTP 429 sayımı tek başına kota anahtarını ya da kök nedeni kanıtlamaz. Pacing simülasyonu 10 saniyelik senaryoda 429 eşiğini kapatır; çıktısı canlı performans tahmini değildir. Canlı UA betiği çalıştırıldığında dış ağa istek gönderir ve bu commit doğrulamasında çalıştırılmamıştır.

---

## BÖLÜM 1: Gerçekleştirilen Testlerin Tasnifli Kataloğu

Rapor, yerel SQLite veritabanı (`jobs.db`), işlem kayıtları (`search_events`), kaydedilmiş yanıt örnekleri (`responses.jsonl`) ve birim testlerinden derlenmiştir. Canlı UA isteği bu doğrulama turunda tekrarlanmadı; pacing karşılaştırması simülasyondur.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       TEST VE DOĞRULAMA ÖZETİ (v2.4.0)                      │
├─────────────────────────┬──────────────────────┬─────────────┬──────────────┤
│ Test Adı                │ İnceleme Kapsamı     │ Sonuç       │ Durum        │
├─────────────────────────┼──────────────────────┼─────────────┼──────────────┤
│ 1. İlan alanı kontrolleri│ 20 örnek / DB sayısı │ Alan biçimi │ ✅ ÖRNEKLEM  │
│ 2. Sayfalama örneği      │ 48 sayfa / 453 slot  │ Ort: 9.44   │ ✅ ÖRNEKLEM  │
│ 3. 0-kart kayıtları      │ Event #3655 / #3717  │ İncelenenler│ ℹ️ SINIRLI   │
│ 4. UA / HTML kaydı       │ Tek ilan yanıtı       │ JSON-LD: 0  │ ℹ️ ÖRNEKLEM  │
│ 5. İstek olay sırası     │ run/task gruplu       │ Kota bilinmiyor│ ℹ️ KANIT DEĞİL│
│ 6. Pacing modeli         │ 1 saat varsayımı      │ Tahmin değil│ ℹ️ SİMÜLASYON│
│ 7. Birim testleri        │ 154 test              │ 154/154 OK  │ ✅ GEÇTİ     │
└─────────────────────────┴──────────────────────┴─────────────┴──────────────┘
```

---

### [TEST 1] Gerçek İlan ve Honeypot Doğrulama Testi
* **Araç / Betik:** [`scripts/data_quality_probe.py`](../scripts/data_quality_probe.py)
* **Amaç:** Yerel ilan örnekleminde ID biçimini, şirket alanının doluluğunu ve açıklama uzunluğunu kontrol etmek.
* **Girdi / Örneklem:** Veritabanındaki en güncel 20 ilan; toplam kayıt sayısı bu kontrollerle doğrulanmaz.
* **Bulgular:**
  1. 10 haneli ID biçimi: bu örneklemdeki kayıtlar biçim kontrolünü geçmiştir; ilan geçerliliği teyit edilmemiştir.
  2. Şirket alanı: dolu ve test adıyla başlamayan değerler bulunmuştur; şirketlerin gerçekliği bağımsız doğrulanmamıştır.
  3. Açıklama uzunluğu: bu örneklemde açıklamalar 300 karakterden uzundur; içerik doğruluğu ölçülmemiştir.
* **Karar:** Bu kontroller honeypot bulunmadığını kanıtlamaz; yalnızca alan biçimini ve uzunluğunu özetler.

---

### [TEST 2] Sayfalama, Kart Dağılımı ve ID Tekrarlama Testi
* **Araç / Betik:** [`scripts/data_quality_probe.py`](../scripts/data_quality_probe.py)
* **Amaç:** Sayfa başına kart düşüşü veya ID döngüsü olup olmadığını ölçmek.
* **Girdi:** 48 arama sayfası olayı ve 453 dönen kart slotu (bu yerel kayıt anlık görüntüsü).
* **Bulgular:**
  - Sayfa başı ortalama kart: **9.44**.
  - Dağılım: 41 sayfada tam 10 kart, 3 sayfada 9 kart, 2 sayfada 8 kart, 2 sayfada 0 kart.
  - Sayfa içi mükerrer ID sayısı: **0 (Sıfır)**.
  - Toplam dönen kart: 453 | Tekil ID: 380 (73 fark, anahtar kelime kesişimlerinden gelen doğal örtüşmedir).
* **Karar:** Bu kayıt örnekleminde sayfalar çoğunlukla 10 kart döndürmüştür; diğer arama ve zamanlar için garanti vermez.

---

### [TEST 3] 0-Kart Dönen Sayfaların Geriye Dönük İncelenmesi
* **Amaç:** Veritabanında 0 kart dönen 2 sayfanın sessiz bir engel mi yoksa arama sonu mu olduğunu doğrulamak.
* **Girdi:** Event #3655 ve Event #3717.
* **Bulgular:**
  - Olay 1 (ID: 3655): `elektrik staj` | Sayfa 6 (start=50). İlk 5 sayfada 50 ilan çekilmiş, 6. sayfada ilan bittiği için 0 dönmüştür.
  - Olay 2 (ID: 3717): `elektrik mühendisliği` | Sayfa 35 (start=340). İlk 34 sayfada 340 ilan çekilmiş, 35. sayfada arama sonuna ulaşıldığı için 0 dönmüştür.
* **Karar:** Sessiz bozulma yoktur; arama kriterinin doğal olarak tükenmesidir (`exhausted_results`).

---

### [TEST 4] Chrome 131 UA ile Kaydedilmiş DOM ve JSON-LD Probe'u
* **Araç / Betik:** [`scripts/test_live_chrome_ua.py`](../scripts/test_live_chrome_ua.py)
* **Amaç:** Kaydedilen tek yanıttaki DOM ve JSON-LD alanlarını incelemek.
* **Girdi:** Raporda kaydedildiği belirtilen LinkedIn ilanı (`/jobs/view/4468150126`) ve Chrome 131 başlıkları.
* **Bulgular:**
  - Yanıt: `200 OK` (269.186 bayt).
  - `application/ld+json` script sayısı: **0 (SIFIR)**.
  - Başlık ve Açıklama: `h1` ve `div.show-more-less-html__markup` içinde 2.697 karakter olarak DOM'da mevcuttur.
* **Karar:** Kaydedilen tek yanıtta JSON-LD görülmemiştir. Bu bulgu başka ilan veya sonraki yanıtlar için genellenemez.

---

### [TEST 5] Endpoint İzolasyonu ve Çapraz Uç Nokta Etkilenme Testi
* **Araç / Betik:** [`scripts/test_endpoint_isolation.py`](../scripts/test_endpoint_isolation.py)
* **Amaç:** Arama uç noktası ile Detay uç noktasının bağımsız kotalara sahip olup olmadığını denetlemek.
* **Girdi:** `run_id` ve `task_id` ile gruplanmış istek olayları.
* **Bulgular:**
  - Aynı çalışma içindeki sonraki isteklerin durumları ve arada kaynak beklemesi olup olmadığı listelenir.
* **Karar:** Bu kayıtlar uç nokta kotasının mı, IP'nin mi, oturumun mu etkili olduğunu tek başına ayırt etmez. Kontrollü ve güvenli bir deney olmadan "IP bazlı" sonucu çıkarılmamalıdır.

---

### [TEST 6] Pacing (İstek Ritmi) 1 Saatlik Verim Simülasyon Testi
* **Araç / Betik:** [`scripts/test_endpoint_isolation.py`](../scripts/test_endpoint_isolation.py)
* **Amaç:** 6s aralık + 429 beklemesi ile 10s sabit ritim arasındaki net saatlik verimi kıyaslamak.
* **Bulgular:**
  - **Mevcut 6s Ritim:** Saatte 182 başarılı istek, 36 kez 429 hatası, **39 dakika donma (%65 boş bekleme)**.
  - **10s deneme senaryosu:** Saatte 334 istek ve 0 bekleme; simülatörde 429 eşiği devre dışıdır.
* **Karar:** 182 ve 334 değerleri yalnızca girilen sabit kabuller altındaki model çıktılarıdır. 10 saniyelik ayarın canlı 429 oranını veya verimi nasıl etkilediği sonraki benzer koşularla ölçülmelidir.

---

### [TEST 7] Tam Regresyon ve Birim Test Paketi
* **Komut:** `python -m unittest discover -s tests`
* **Kapsam:** 154 birim testi (tüm modüller, şema uyumluluğu, oran hesaplamaları, anormal kart logları).
* **Sonuç:** Bu doğrulama turunda `Ran 154 tests in 42.577s - OK`.

---

## BÖLÜM 2: Sistemi Daha da Hızlandırmak İçin Neler Yapılabilir? (İleri Düzey Analiz)

Bu yerel kayıt örneklemi LinkedIn'in sabit bir istek kotasını veya kota anahtarını belirlemeye yetmez. Aşağıdaki maddeler uygulanmış çözümler değil, ölçülmesi gereken fikirlerdir. Hiçbiri `Retry-After`, kaynak duraklatması veya genel ilan toplama davranışını aşmamalıdır.

---

### 1. Ön Eleme ile Tembel Detay Doldurma (Pre-filtering & Lazy Detail Enrichment)
* **Kapsam notu:** Sistem genel bir ilan toplayıcısıdır; kullanıcının anlık filtrelerine göre ilan toplamayı durdurmak genel veri kümesini eksiltir ve uygulanmamalıdır.
* **Çözüm:** 
  - İlanın unvanı ve şirketi zaten arama kartından gelmektedir.
  - Meslek grubu etiketleri kart verisinden çıkarılabilir; kullanıcı filtreleri toplama aşamasından sonra uygulanır.
  - Detay isteği azaltımı ancak genel veri kapsamını koruduğu, kalite kaybı yaratmadığı ve gerçek istek kayıtlarında ölçüldüğü durumda değerlendirilebilir.
* **Beklenen kazanç:** Ölçülmemiştir; yüzde veya hız artışı varsayılmamalıdır.

---

### 2. Eşik Tabanlı Erken Durma (Threshold Early Stopping)
* **Darboğaz:** `stop_when_known` şu an sayfadaki kartların %100'ü biliniyorsa durmaktadır. Ancak düzenli aramalarda bir sayfadaki 10 ilanın 8 veya 9 tanesi zaten veritabanında varsa, o arama için 2. ve 3. sayfalara gitmek çoğu zaman eski ilanları tekrar tekrar taramaktır.
* **Çözüm:** Eşik tabanlı durma, yalnızca `sort_recent` kullanan tekrarlı izlemelerde ve sonuç kapsamı/kaçırma oranı test edildikten sonra ayrı bir seçenek olarak değerlendirilebilir.
* **Beklenen kazanç:** Ölçülmemiştir. Yalnızca düşük yeni ilan oranı, sonraki sayfalarda yeni ilan olmayacağını kanıtlamaz.

---

### 3. Arama Terimlerinin Çapraz Tekilleştirilmesi (Orthogonal Keyword Targeting)
* **Darboğaz:** Kuyrukta hem `"Python Developer"` hem `"Python Yazılımcı"` hem de `"Backend Developer"` olduğunda, bu üç sorgu LinkedIn'de %60–80 oranında **birebir aynı ilanları** döndürür. İkinci ve üçüncü arama aynı ilanları tekrar gördüğü için kota boşa harcanır.
* **Çözüm:**
  - Arama kuyruğundaki eşanlamlı kelimeleri aynı tarama döngüsünde peş peşe çalıştırmak yerine rotasyona sokmak veya daha geniş filtrelerle tekilleştirmek.
* **Beklenen kazanç:** Ölçülmemiştir. Arama terimlerini otomatik atlamak yerine örtüşme raporlanmalı ve kullanıcının sorguları korunmalıdır.

---

### 4. SQLite WAL ve Yüksek Başarımlı PRAGMA Ayarları
* **Darboğaz:** Flask SSE arayüzü, arka plan detay doldurucusu (`details.py`) ve ana toplayıcı aynı SQLite veritabanına erişmektedir. Varsayılan SQLite ayarlarında yazma kilitleri küçük de olsa CPU ve I/O gecikmesi yaratabilir.
* **Çözüm:**
  - Veritabanı bağlantı anında şu pragma'lar zorunlu kılınabilir:
    ```sql
    PRAGMA journal_mode = WAL;
    PRAGMA synchronous = NORMAL;
    PRAGMA busy_timeout = 5000;
    PRAGMA cache_size = -64000; -- 64MB bellek önbelleği
    ```
* **Beklenen etki:** WAL eşzamanlı okuyuculara yardımcı olabilir; yazma kilitlerini sıfırlamaz ve gerçek iş yükünde ölçülmelidir. Herhangi bir değişiklikten önce yedek ve geri dönüş testi gerekir.

---

### 5. Çoklu egress / IP rotasyonu (uygulanmayacak)
Tek collector ve kaynak koruma politikası korunur. Kota veya engel aşmak için çıkış IP'si çoğaltmak ya da rotasyon eklemek bu planın parçası değildir.

---

## 3. Öncelikli Tavsiye ve Yol Haritası

Bir sonraki adım, 10 saniyelik pacing ayarını benzer aramalardaki `rate_429`, `frozen_ratio` ve yeni ilan/istek oranlarıyla ölçmektir. WAL veya erken durma gibi ek değişiklikler için önce izole kıyaslama, veri kapsamı kontrolü ve geri dönüş planı gerekir.
