# Linko Scrapper Light — Veri Kalitesi, Honeypot ve Ağ Davranışı Probe Test Raporu
**Tarih:** 17 Ekim 2026  
**Yöntem:** Canlı SQLite Veritabanı (`jobapp/jobs.db`), İşlem Kayıtları (`search_events`) ve Kaydedilmiş LinkedIn Canlı HTML Yanıtları (`responses.jsonl`) Üzerinde Doğrudan Ampirik Ölçüm.  
**Test Aracı:** `scripts/data_quality_probe.py`

---

## 1. Yönetici Özeti ve Temel Bulgular

Bu rapor, yerel veritabanındaki ilan ve istek örneklerini ve kaydedilmiş HTML yanıtlarını özetler. Örneklem, sahte veri, kota anahtarı veya TLS kaynaklı bir engel hakkında genel ve kesin sonuç vermez.

| Test Alanı | İncelenen Örneklem | Sonuç | Durum |
| :--- | :---: | :--- | :---: |
| **İlan Alanları Kontrolü** | 20 İlan (Detaylı) / 381 İlan (Genel) | Örneklemde kimlik biçimi, şirket alanı ve açıklama uzunluğu kontrolleri geçti; bu, tüm ilanların gerçekliğini kanıtlamaz. | ✅ **ÖRNEKLEM KONTROLLERİ GEÇTİ** |
| **Sayfa Başına Kart Dağılımı** | 48 Arama Sayfası | 41 sayfada tam 10 kart; ortalama 9.44 kart/sayfa. | ✅ **DÜZENLİ AKIŞ** |
| **Sayfa İçi Mükerrer ID Kontrolü** | 453 Kart İsteği | Aynı sayfada birden fazla dönen mükerrer ID sayısı: 0. | ✅ **SIFIR MÜKERRERLİK** |
| **JSON-LD Script Varlığı** | 8 kayıtlı 200 yanıt | Bu örneklerde bulunan `application/ld+json` script sayısı: 0. | ✅ **ÖRNEKLEMDE YOK** |
| **HTTP Yanıt Kodları** | 450 istek | 398 adet 200 OK (%88.4), 49 adet 429 (%10.9); durum kodları tek başına 429'un kök nedenini göstermez. | ℹ️ **429 GÖRÜLDÜ** |

---

## 2. Probe 1: 20 İlanın Alan Biçimi ve İçerik Uzunluğu

Veritabanındaki en güncel 20 ilan satırı alan biçimi ve içerik uzunluğu kontrollerinden geçirilmiştir. Şirketlerin bağımsız doğrulaması yapılmamıştır:

* **ID biçimi kontrolü:** Örneklemdeki 20 kaydın tamamı 10 haneli LinkedIn ID biçimine uymuştur; bu, ilanların halen açık veya geçerli olduğunu kanıtlamaz.
* **Şirket alanı kontrolü:** Örneklemdeki kayıtların tamamında boş olmayan şirket alanı vardır; alanın gerçekliği bağımsız olarak teyit edilmemiştir.
* **Açıklama metni uzunluğu:** Örneklemdeki 20 açıklama 300 karakterden uzundur; uzunluk tek başına içerik doğruluğu kanıtı değildir.

### İncelenen 20 İlan Tablosu

| # | LinkedIn ID | İlan Başlığı | Şirket Adı | Açıklama Boyutu | Lokasyon |
| :-: | :---: | :--- | :--- | :---: | :--- |
| 1 | `4476688264` | Legal Intern / Maritime Law | Aydin Lawyers | 2.223 karakter | Şişli, İstanbul |
| 2 | `4468150126` | Hiring People with Disabilities - Intern | Philip Morris International | 2.742 karakter | İstanbul, Türkiye |
| 3 | `4477394515` | B2C Pazarlama Intern | C'esta Technology | 2.871 karakter | Bakırköy, İstanbul |
| 4 | `4477389713` | KARİYER DENEYİM SÜRÜ STAJYERİ - LOJİSTİK | Esan | 3.551 karakter | Maltepe, İstanbul |
| 5 | `4473111410` | Stajyer Avukat | Yıldız Holding | 2.290 karakter | Üsküdar, İstanbul |
| 6 | `4478787451` | Enterprise Türkiye MT Programı | Enterprise Türkiye | 2.683 karakter | Beykoz, İstanbul |
| 7 | `4469945272` | Sales Intern CRE | Dassault Systèmes | 1.945 karakter | Greater Istanbul |
| 8 | `4470139444` | Marketing Intern | Eti | 1.302 karakter | İstanbul, Türkiye |
| 9 | `4469861477` | Project Student (Business) | BSH Ev Aletleri Türkiye | 1.918 karakter | Ümraniye, İstanbul |
| 10 | `4472901091` | Intern Lawyer | Hyundai Motor Company | 1.984 karakter | İstanbul, Türkiye |
| 11 | `4472910221` | Global Supply Chain Transformation Intern | Evyap | 4.393 karakter | İstanbul, Türkiye |
| 12 | `4475695106` | Compliance Project Assistant & Long Term | Token Finansal Teknolojileri | 2.790 karakter | Sarıyer, İstanbul |
| 13 | `4477310832` | Customer Experience Intern | Hilti Türkiye | 4.174 karakter | İstanbul, Türkiye |
| 14 | `4468396406` | Learning & Development Master Project | BSH Ev Aletleri Türkiye | 2.368 karakter | Ümraniye, İstanbul |
| 15 | `4475487111` | Stajyer - Muhasebe | Otis Elevator Co. | 3.902 karakter | İstanbul, Türkiye |
| 16 | `4473632596` | CAREER EXPERIENCE DRIVE INTERN-HR ANALYTICS | Eczacıbaşı Holding | 4.222 karakter | Şişli, İstanbul |
| 17 | `4476712619` | Marketing Artist Intern | Teknasyon | 4.107 karakter | Sarıyer, İstanbul |
| 18 | `4473644524` | Stajyer (Hukuk) | Karadeniz Holding | 3.184 karakter | İstanbul, Türkiye |
| 19 | `4465520707` | Logistics // Long-Term Intern | Delta Electronics Türkiye | 2.719 karakter | İstanbul, Türkiye |
| 20 | `4469739736` | HR Services Part-Time Intern | Schneider Electric | 2.443 karakter | İstanbul, Türkiye |

> **Doğrulama Notu:** Herhangi bir ilan URL'si doğrudan test edilebilir:  
> `https://www.linkedin.com/jobs/view/4468150126` (Philip Morris International)  
> `https://www.linkedin.com/jobs/view/4473111410` (Yıldız Holding)  
> `https://www.linkedin.com/jobs/view/4470139444` (Eti)

---

## 3. Probe 2: Sayfalama ve Tekrarlayan ID Analizi

`search_events` tablosunda kayıtlı tüm arama ve sayfalama olayları taranmıştır:

* **İncelenen Toplam Sayfa Sonuç Olayı:** 48
* **Sayfa Başına Ortalama Kart Sayısı:** 9.44
* **Kart Sayısı Dağılımı:**
  * 10 kart dönen sayfalar: **41 sayfa**
  * 9 kart dönen sayfalar: **3 sayfa**
  * 8 kart dönen sayfalar: **2 sayfa**
  * 0 kart dönen sayfalar (sayfalama sonu): **2 sayfa**
* **Sayfa İçi Mükerrer ID Sayısı:** **0** (Hiçbir sayfada aynı ID iki kez dönmemiştir).
* **Toplam Dönen Kart:** 453 | **Tekil ID:** 380 (Aralarındaki 73 kartlık fark, farklı anahtar kelimelerin [örn. "Python" ve "Backend"] arama sonuçlarında aynı popüler ilana rastlamasından kaynaklanan doğal kesişimdir).
* **Anormal Kart Düşüşü Yaşanan Sayfa:** **YOK**.

---

## 4. Probe 3: HTML Yanıtlarında DOM ve JSON-LD İncelemesi

Canlı denemede kaydedilen 200 OK yanıtları Beautiful Soup ile ayrıştırılmıştır:

* **İncelenen 200 OK Yanıt Dosyası:** 8 adet
* **Bulunan `application/ld+json` Script Sayısı:** **0 (SIFIR)**
* **Sayfalarda Bulunan Script Türleri:** `{'no-type': 20}` (LinkedIn misafir uç noktasında script etiketlerine `type` özniteliği dahi konulmamıştır; tamamı istemci JS kodudur).
* **Gerçek İlan İçeriğinin Konumu:**
  * İlan başlığı: `h1.top-card-layout__title` veya `.base-search-card__title`
  * Şirket adı: `a.topcard__org-name-link`
  * Açıklama metni: `div.show-more-less-html__markup` (Sayfa başına 1.762 ile 3.048 karakter arasında zengin HTML).
* **Sonuç:** Bu sekiz kaydedilmiş yanıtta JSON-LD görülmemiştir. Farklı sayfa türleri veya sonraki LinkedIn yanıtları için bu sonuç genellenemez.

---

## 5. Probe 4: Ağ İstekleri ve HTTP 429 Davranışı

Toplama süreci boyunca atılan tüm HTTP istekleri incelenmiştir:

* **Toplam İstek Sayısı:** 450
* **HTTP Durum Kodları Dağılımı:**
  * **200 OK:** 398 adet (**%88.44**)
  * **429 Too Many Requests:** 49 adet (**%10.89**)
  * **500 Server Error:** 1 adet (**%0.22**)
  * **502 Bad Gateway:** 2 adet (**%0.44**)
* **Yorum sınırı:** Bu özet yalnızca durum kodlarını sayar; istekler arası süreyi, uç nokta türünü ve 429 öncesindeki ritmi analiz etmediğinden kök nedeni veya bir kota eşiğini kanıtlamaz. `source_paused` kayıtları kaynak beklemesi yaşandığını gösterir; tek başına beklemenin 60 saniye sürdüğünü veya sonraki isteğin başarılı olduğunu göstermez.

---

## 6. Nihai Değerlendirme ve Sonuç

1. **Anormal sayfa uyarısı:** Bu veri örnekleminde kart düşüşü gözlenmemiştir. Akışı kesmeden uyarı kaydı üretmek, anomaliyi izlemek için uygundur.
2. **JSON-LD:** Kaydedilen sekiz yanıtta JSON-LD yoktu; mevcut HTML ayrıştırıcısı bu örneklerdeki DOM alanlarını bulmuştur. Bu bulgu örneklemle sınırlıdır.
3. **Sonraki ölçüm:** 72 saatlik detay önbelleği ve 10 saniyelik istek aralığının etkisi henüz canlı koşu karşılaştırmasıyla doğrulanmamıştır. `rate_429` ve `cache_hit_rate` metrikleri sonraki koşularda bu etkiyi izlemek için kullanılabilir.
