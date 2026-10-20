# Job Collector — NextStep entegrasyon analizi

## Kullanıcı düzeltmesi sonrası uygulama

Kullanıcı tüm ilanların Job AI sitesinden gelmesini istedi. Yerel NextStep
havuzunun **tamamı** (11 örnek + 163 eski kayıt ve `ilanlar.js`) kaldırıldı.
Liste, eşleştirme ve ilan bağlamı artık `app/job_ai.py` aracılığıyla yalnızca
Job AI `/api/v1/jobs` API'sinden okunuyor. Yerel DB satırları ve Remotive
listeye katılmıyor; kaynak hatasında yerel/örnek veriye dönüş yapılmıyor.
Ülke/şehir ve yayın tarihi yeni API adaptöründe taşınıyor. Sunucuya dağıtım
bu kod değişikliğiyle yapılmış değildir. Aşağıdaki inceleme, değişiklik öncesi
durumun kaydıdır; “163 kayıt korundu” sonucu kullanıcı düzeltmesiyle geçersizdir.

Yeni NextStep API'si canlı Job AI kaynağıyla yerelde çalıştırıldı: HTTP 200,
**2.140 ilan**, tamamında `_source=job_ai`, yerel havuz dosyası 0. Ülke bilgisi
olan 1.616 kayıt yeni adaptörden geçti; API anahtarı yanıtta bulunmadı.
Kanıt: `.qa/nextstep-job-ai-only-live-check.json`.

Kaynak/ingest backend testleri 20/20; JavaScript testleri 22/22 ve yeni kaynak
testleri 4/4 geçti. Geniş backend takımı 157 geçti, 1 hata verdi: Docling bu
ortamda kurulmadığından `test_cv_parse_rejects_fake_pdf_via_magic_bytes` testi
beklediği 400 yerine bağımlılık hatası 503 aldı. Bu çalışma CV kodunu değiştirmedi.

20 Ekim 2026. Canlı ilan sayımı: 18:36 UTC / 21:36 Türkiye saati.

## Sonuç

Aktarım kodu mevcut, fakat iki uygulamanın canlıda düzenli haberleştiği ve yeni
ilanların NextStep'te göründüğü doğrulanamadı. Dokümanda NextStep'e ayrılan
`https://ai-org.online` adresi şu anda Linko'yu sunuyor. Veritabanları ayrı
şemalardır; mevcut köprü temel ilan alanlarını dönüştürüyor, bütün alanları ve
silinme/güncelleme davranışını taşımıyor.

## Canlı gözlemler

- Collector'ın `/api/v1/jobs` adresinden 5 sayfada **2.098 görünür ilan** okundu.
  Bu, API'nin aktif ve kaliteli ilan filtresinden geçen kayıtların sayısıdır;
  veritabanındaki tüm satırların sayısı değildir.
- Bu kayıtlarda 1.594 ülke bilgisi, 2.096 şehir bilgisi vardı; 301 ilan detay
  bekliyordu. En son taranma zamanı `2026-10-20T18:36:34.412250` idi.
- `job.ai-org.online/healthz` ve `ai-org.online/healthz`, aynı kontrol sırasında
  aynı Linko sağlık yapısını ve `a09e64d` sürümünü döndürdü.
- `ai-org.online/` sayfasının başlığı:
  `ilanlar. — Profesyonel İş İlanları Keşif Platformu · Linko Scrapper Light`.
- NextStep'in beklediği `/api/ilanlar` ve `/api/ilanlar/degisiklik` uçları,
  sitenin mevcut Basic Auth bilgileriyle **HTTP 404** döndürdü. Kimlik
  doğrulamasız çağrılar 401 dönüyordu; bulgu kimlik doğrulamasından sonra alındı.
- Bu bilgisayarda varsayılan NextStep portu `127.0.0.1:5500` erişilebilir değildi;
  NextStep klasöründe yerel bir `.db` dosyası da bulunmadı.
- Sunucudaki `nextstep.service`, cron ve gerçek NextStep DB kayıtları bu erişimle
  okunamadı. NextStep'in başka bir adreste veya yalnızca sunucu içinde çalışması
  dışlanamaz. Mevcut dış adreste NextStep görünürlüğü doğrulanmış değildir.

## Kodda bulunan veri akışı

`Collector SQLite jobs → next_step/tools/push_jobs.py → POST /api/jobs/ingest
→ NextStep jobs → GET /api/ilanlar → js/data/jobs.js`

- Köprü SQLite'ı salt okunur açar. HTTP aktarımı 100 kayıtlık partiler kullanır.
- NextStep, `(source, external_id)` üzerinden ekleme/güncelleme yapar; bu yol aynı
  kaynak kimliğinin tekrar aktarılmasını destekler.
- Collector'ın sayısal `id` alanı ile NextStep'in metin `id` alanı farklıdır.
  Ortak veritabanı dosyasına işaret etmek uygun değildir; köprü gereklidir.
- NextStep DB ilanları, dosya havuzu ve Remotive ilanları okuma sırasında birleşir.
  DB ile dosya havuzunun mükerrer kontrolü yalnız görünen `id` üzerinden yapılır.
- UI, değişiklik kontrolünü 30 saniyede bir yapacak şekilde yazılmıştır. Mevcut
  bir ilanın içeriği değiştiğinde, yeni/silinen ID yoksa `applyFullJobLoad`
  görünür kartları yeniden çizmez. Veri bellekte güncellense de karttaki detay
  bilgisi yenilenene kadar eski kalabilir.

## Şema ve davranış uyumu

| Collector alanı/durumu | NextStep karşılığı | Mevcut durum |
| --- | --- | --- |
| `source`, `external_id` | `source`, `external_id` | Upsert kimliği eşleniyor. |
| Başlık, şirket, açıklama | Başlık, şirket, açıklama | Temel aktarım mevcut. |
| `workplace_type` | `work_type` / API `type` | Remote/Hybrid/Office dönüşümü mevcut. |
| `tags` listesi | `skills` | Temel yetenek listesi taşınıyor. |
| `url` | `apply_url` / API `applyUrl` | Taşınıyor. |
| `location` | `location` | Serbest konum metni taşınıyor. |
| `location_country`, `location_city` | Ayrı ülke/şehir alanı yok | Köprü, DB, API ve UI normalizasyonunda kayboluyor. |
| `posted_at` | `posted` | Köprü gerçek yayın tarihi yerine `scraped_at` kullanıyor. |
| `deleted_at` | `active` | Silinme filtresi yok; köprü her zaman `active=True` üretiyor. |
| Sonradan kalitesiz/scam/ghost olan ilan | `active=False` gerekir | Kaynak satırı atlanıyor; hedefteki eski ilanı kaldıran işlem yok. |
| `experience_years` | Sayısal karşılık yok | Yerine kıdemden türetilen metin gönderiliyor. |
| `category`, `seniority` | DB alanları mevcut | Ingest saklıyor, `to_pool_dict()` çıktıya eklemiyor. |
| Meslek grupları, özet, yan haklar, sayısal maaş | Tam karşılık yok | Mevcut köprü tam zenginleştirmeyi taşımıyor. |

Bu nedenle Collector'da AI ile doldurulan **ülke bilgisi mevcut köprü üzerinden
NextStep'e ulaşmaz**. `--since` yalnız `scraped_at` filtresi olduğundan eski bir
ilandaki ülke/detay güncellemesini eksiksiz takip eden bir değişiklik imleci de
değildir. Collector'ın `/api/v1/jobs/changes` akışı var, fakat NextStep köprüsü
bu akışı kullanmıyor; `scripts/consume_jobs.py` ayrı, örnek bir tüketicidir.

## Yerel yol ve veri durumu

- `push_jobs.py` varsayılanı komşu `LinkoScraper/jobapp/jobs.db` yoludur. Bu
  yerleşimde o dosya yok; `--sqlite` veya `JOBAPP_DB_PATH` açıkça verilmelidir.
- Yerel `jobapp/jobs.db` 381 kayıt içeriyor ve son taranma zamanı 16 Ekim.
  Mevcut köprü filtresinden 379'u geçiyor. Bu dosya canlı 2.098 kayıtlık havuzun
  güncel kopyası değildir.
- Eski `havuza_aktar.py` aracı `data_scrapper/job_list` ve eski ham JSON
  şemasını okuyor; mevcut Collector'ın otomatik entegrasyonunun kanıtı değildir.
- İncelenen repolarda NextStep aktarımını kuran cron/systemd tanımı bulunmadı.
  Dokümanda cron'dan söz edilmesi, sunucuda çalıştığını kanıtlamaz.

## Kullanıcının istediği mockup temizliği

- NextStep'in `ilan_havuzu/ilan_1.json` … `ilan_11.json` dosyaları örnek ilanlardı.
  101–105 ve 1–6 sayısal kimlikleri, örnek başlık/şirketler ve yer tutucu başvuru
  bağlantılarıyla çevrimdışı dosyadaki aynı 11 örneğe karşılık geliyordu.
- **11 örnek JSON kaldırıldı.** `ilanlar.js` içindeki 11 örnek kopyası da kaldırılıp
  dosya havuzunda kalan **163 toplanmış ilanla** yeniden oluşturuldu.
- 163 `sc-*.json` dosyasının önceki/sonraki SHA-256 değerleri aynı; içerikleri
  değiştirilmedi. Çevrimdışı listedeki ID kümesi kalan JSON dosyalarıyla eşleşiyor.
- JSON doğrulaması, JavaScript sözdizimi kontrolü ve `git diff --check` geçti.
- Değişiklik yerel NextStep reposundadır; canlı dağıtım veya erişilemeyen bir
  NextStep veritabanında temizlik yapıldığı iddia edilmemektedir.

## Öncelikli tamamlanacak işler

1. NextStep'in gerçek servis/adresini ve reverse proxy yönlendirmesini doğrula;
   `/api/ilanlar` ve `meta.dbCount` erişilebilir olsun.
2. Gerçek Collector DB yoluyla aktarımı kur; kalıcı zamanlayıcı ve son başarılı
   aktarım kaydı üzerinden çalıştığını gözle.
3. Ülke/şehir ile yayın tarihi eşlemesini tamamla; silinen/elenen ilanlar için
   hedefte pasifleştirme uygula. Eski kayıt güncellemelerini değişiklik akışıyla izle.
4. Aynı ID'deki içerik değişikliklerinde UI'ı yeniden çiz; mockup temizliğini yeni
   NextStep sürümüyle dağıt ve canlı DB'de ek örnek kayıt olup olmadığını kontrol et.

Kanıt özeti: `.qa/collector-nextstep-audit-20261020.json`.
Temizlik yedeği ve dosya hash'leri: `.qa/nextstep-mock-cleanup-20261020/`.
Uygulama anahtarları ve kullanıcı bilgileri bu rapora yazılmadı.
