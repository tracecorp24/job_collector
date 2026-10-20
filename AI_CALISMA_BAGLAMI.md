# Ajanlar için kısa çalışma bağlamı

Güncelleme: 20 Ekim 2026. İlk inceleme üretim `f3d6819` sürümünü kapsıyordu.
Planın yerel uygulaması şimdi `improve/reliable-collection-plan` dalında; henüz
canlıya alınmadı. Yeni ajan önce aşağıdaki uygulama durumunu, sonra tarihsel
kanıtları okusun.

## Önce oku

1. `CALISMA_YONTEMI.md`: canlı log protokolü, anahtar kapsamı, incident yaşam döngüsü.
2. `TOPLAMA_HIZI_ANALIZI_2026-10-20.md`: kanıtlar, nedenler, öncelikli düzeltmeler.
3. `CLAUDE.md`: çalışma ve üretim kuralları.
4. `429_ARTISI_ANALIZI_VE_PLAN_2026-10-20.md`: son kullanıcı yönlendirmesiyle
   güncellenen neden analizi ve yeni uygulama sırası; oturum düzeltmesi ilk sırada.
5. **Güncel uygulama planı:** `DENEY_SONUCLARI_VE_AYRINTILI_PLAN_2026-10-20.md`.
   Önceki deneyler, uygulama kararları ve canlıya geçiş kabul koşulları burada.

## Bu dalda uygulananlar

- `jobapp/transport.py`: süreç ömrü boyunca paylaşılan seri HTTP istemcisi,
  oturum/istek sıra kimlikleri, lease yenileme ve güvenli kapatma.
- `jobapp/scraper/accountless.py`, `runs.py`, `repair.py`: her iş kendi callback ve
  kimliğini taşırken aynı HTTP sahibini kullanır. 429/403/challenge sonrasında yeni
  oturum açıp tekrar deneme yapılmaz. İstek kayıtları HTTP sonucu, içerik sonucu,
  bekleme/HTTP/parse süreleri ve `Retry-After` kökenini ayırır.
- `repair.py`: aynı kart için geçerli cache kullanılır; değişmiş kartın eski
  açıklaması tamamlandı sayılmaz; `done + detail_pending` tutarsızlığı aynı kartın
  açıklaması varsa yerelde temizlenir, değişmiş kart varsa görev yeni revizyon için
  tekrar açılır. İstek/ret sayaçları görev üzerinde birikir.
- `service.py`: manuel öncelik ve rutinlere 60 saniye sessizlik korunur; tamamlama
  isteği sayısı ve en eski detay yaşı arttıkça rutinlere adil dönüş bütçesi verilir.
- `problems.py` ve `audit.py`: backlog alarmı gerçek başarılı ilerlemeye bağlı;
  aynı kuyruk sayısında bile tamamlanan ilanı tanır. Anlamsal başarı, 200 içeriksiz
  yanıt, oturum sayısı ve zaman ölçümleri rapora eklendi.
- Kart keşfi zaten detaydan ayrıdır: `DEFER_DETAILS` varsayılanı açık; bu dal bu
  mimariyi yeniden kurmadı, onun oturum/cache/kuyruk sahipliğini düzeltti.
- Kaynak bağımsız 72 istekli loopback deneyi: `.qa/collection-transport-implementation-2026-10-20.json`.
  Yalnız `127.0.0.1`; canlı siteye istek atmaz. Çerez gerektiren yapay koşulda
  yeni oturum 8/8, kalıcı oturum 1/8 ret aldı. IP bütçesi ve `Retry-After`
  kollarında fark yok; bu nedenle canlı 429 oranının düştüğünü kanıtlamaz.
- Son hedefli paketler: transport 15/15, repair 16/16, service 12/12, scheduling
  22/22, details 13/13, problems 17/17, audit 9/9 geçti. `test_light.py` 9/11
  geçti; kalan iki
  UI beklentisi (`Linko Scrapper Light`, `quick-filters`) çalışma başında mevcut
  kullanıcı arayüzü değişiklikleriyle uyuşmuyor. Bu arayüz dosyalarına dokunma.
- Canlı üretimde gözlem, merge veya deploy yapılmadı. Aşama 2 için doğal iş yükünde
  24–72 saatlik, aynı endpoint ve başlangıç koşullarıyla ölçüm hâlâ gerekli.

## Son deneylerin kısa sonucu

- `scripts/collection_transport_experiment.py --offline`: dokuz ayrı loopback
  kolu, 72 gerçek yerel HTTP isteği, 11/11 kabul kontrolü. Sürekli session tek
  TCP, yeni session sekiz TCP. Çerezli yapay modelde hata düşüyor; bağımsız IP
  bütçesi ve Retry-After modellerinde hata oranı aynı. Bu LinkedIn mekanizması değil.
- `.qa/experiment_policy_invariants.py`: gerçek Coordinator ve scraper ile
  18/18 hata/koruma senaryosu geçti; ağ yok. Session/restart blokajı kaldırmıyor.
- `.qa/experiment_lease_expiry.py`: 3/3. Interval10/lease60/aktifHTTP80 ve ikinci
  istemcide 61. saniyede çakışma mümkün; interval120 kontrolünde çakışma yok.
  Üretimde böyle bir çakışma yaşandığı kanıtlanmadı.
- Yeni sürüm ilk60 detay429=%5, son60=%18,33; session stratejisi aynı. Kaynak
  geçmişi ve toparlanması ayrıca izlenmeli. Tarihsel ortak URL sayısı sadece1.
- HTTP 200 güvenlik sayfasının başarı sayılması, iş başına session ve callback
  sızıntısı bu daldaki kodla düzeltildi; yerel testlerde doğrulandı.
- Ayrı canlı pilot branch'i `audit/bounded-session-pilot-20261020`; iş:
  https://github.com/tracecorp24/job_collector/actions/runs/39387160852 .
  Ortak yerel gate, güncel üretim blokaj guard'ı, en fazla8 kaynak gönderimi,
  min120sn, ilk rette tümkollar durur. Üretimlease/IP'siyle aynı ortam değil.
  Script `scripts/collection_live_pilot.py`; otomatik CI kendiliğinden çalıştırmaz.
  Sonuç: 10:32:32–10:56:31 İstanbul, 76 durum gözlemi, kayıtlı blokaj beklendi;
  tek gerçek kaynak isteği 429 aldı (Retry-After yok, 24.633 bayt), tüm pilot durdu.
  Fresh kolu denenmedi; canlı A/B veya kazanan yok. Workflow success yalnız
  betik/artifact başarısıdır. `.local/.../live-pilot/result.json` kanıttır.
  Offline: transport11/11, policy18/18, lease3/3, cache7/7. Mevcut239 testin ilk
  koşusunda bir portable alt süreç timeout'u; tekil tekrar geçti. Temiz239/239 deme.

## Kanıtlanmış durum

- Üretim sürümü `f3d6819`; deploy başarılı. Tek collector/supervisor var.
- 20 Ekim 09:45 İstanbul canlı sorgusunda beş uç HTTP 200: health, incidents,
  app/events export, status. 36.024 olay; kaynak 429, aralık 120 saniye,
  6 ihlal. Kuyrukta 223 done / 3 retry; 43 şehir zamanı gelmiş.
- 18 Ekim 600, 19 Ekim 159 yeni ilan. Eski hızlı koşu 69 dakikada 293 yeni **kart**;
  açıklamalar sonradan tamamlanıyor. Kayan bir saatte görülen en yüksek yeni ilan: 254.
- 19 Ekim 03:38–14:44 İstanbul arasında 11 saat kaynak isteği yok.
- Yeni İstanbul rutini 15,42 saatte 209 yeni ilan; bu sürede kayıtlı kaynak blokajı
  9,42 saat. İstek aralığı 10 yerine kalıcı olarak 120 saniyeye çıkmış.
- `34bca7d`: manuel > tamamlama > rutin. `f3d6819`: rutin için 60 saniye sessizlik.
  Yeni kartlar tamamlama işi çıkarınca rutin `priority_yield` ile kesiliyor.
- `DEFER_DETAILS` zaten varsayılan açık. Özelliği yeniden eklemeye çalışma.
- Kaynak 429 ve 403 dönüşleri gerçek; bekleme politikasını sırf hız için sıfırlama.
- Aynı detay ucunda eski tamamlayıcı 30/631=%4,75; son sürüm 28/210=%13,33
  429 almış. Yeni akışın toplamı 31/257=%12,06. Eski dönemde 429 yoktu deneme;
  fakat son kararlı akışla karşılaştırmada gerçek artış var.
- Eski detaylarda request_number=1 yalnız 4/631; yeni detaylarda 257/257,
  yeni liste isteklerinde 49/49. Her işte/session devamında oturum parçalanıyor.
  Öncelik: telemetri + sürekli ve seri sahipli HTTP session; sonra kuyruk adaleti.
- Yeni sürüm daha hızlı istek patlatmıyor: son dönemde medyan başlangıç aralığı
  124,29 saniye. Tek neden diye WAF/çerez puanlaması iddiası üretme.
- `37aa6b5` öncesi arka plan 429'ları kayda girmiyordu. Eski/yeni kayıt kapsamını
  eşleştirmeden UI uyarı sayısı veya toplam günlük hata sayısı karşılaştırma.

## Tarihsel bulgular ve bu daldaki karşılıkları

- Güncel cache deneyi: 5 izole akış, 7/7 kontrol. Aynı kartın geçerli cache'i
  hem eski `fill_one` hem yeni otomatik repair yolunda 0 HTTP ile kullanılıyor;
  değişmiş kart 1 HTTP ile güncel açıklamayı alıyor; açık manuel yenileme geçerli
  cache'i bilinçli olarak atlayıp 1 HTTP yapıyor. `detail_pending` artık otomatik
  cache bypass sebebi değil; eski açıklamanın korunması kart fingerprint'iyle
  engelleniyor.
  Son yedekte 10 pending'in dokuzunda cache yok; kalan #1212 zaten done. Aktif
  detail pending/retry işlerinde geçerli cache atlatma adayı 0. Bu koşulu mevcut
  429 artışının ölçülmüş ana nedeni diye sunma; tarihsel sıklığı bilinmiyor.
- `jobapp/problems.py`: backlog minimumu 0'a düşünce daha sonraki kuyruklar eski
  başlangıca göre “25/57 saattir azalmadı” alarmı veriyor. `min=0` üretimde doğrulandı;
  alarm sırasında başarılı detay tamamlama var. Alarm artık başarı olayını da takip ediyor.
- `repair.discover` mevcut `RepairTask` satırlarını atlıyor; `enqueue` conflict'te
  yeniden açmıyor. İlan `#1212`, external ID `4479822205`: açıklama var,
  `detail_pending=1`, tamamlama görevi `done`. Aynı kartta bekleme bayrağı temizlenir;
  değişmiş kart için görev yeniden açılır.
- `repair.worker` içindeki `process_raw` çağrılarında `emit` yok: detay sonrası
  işlem aşamalarının süre ve sonuç olayları artık kaydediliyor. Sağlayıcı token
  sayımları henüz eklenmedi.
- `Details.known()` yalnızca açıklaması olan ilanı bilinen sayıyor. Keşif ile
  detay hazır olma kavramlarını ayır.
- `/healthz=ok`, verimlilik sağlıklı demek değil. `frozen_ratio` tüm sistem beklemesi değil.

## Veri ve yeniden kullanım

- Ham üretim verisi: `.local/performance-audit-20261020/`, gitignore altında.
- Yedekler `jobs-20261016.db` … `jobs-20261020.db`; son olay 20 Ekim 03:10 UTC.
- Özetler: `diagnosis.json`, `snapshot-analysis.json`, `drilldown.json`.
- 429 sürüm/uç/oturum karşılaştırması: `429-comparison.json`; hesaplayan yerel
  yardımcı `.qa/compare_429_versions.py`. Yeni plan yalnız doğal kuyruk gözlemi
  kullanır; kaynak politikasını sıfırlama veya ek canlı yük testi içermez.
- Güncel canlı yanıtlar `live/` altında; `manifest.json` sorgu zamanını ve HTTP
  durumlarını, `analysis.json` kısa ölçümleri tutar. Olaylar 09:18'e kadar.
- Üretim DB'sini uygulama modülleriyle açma: import/init_db göçleri çalıştırabilir.
  `sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)` kullan.
- Tekrar kullanılabilir araç:
  `python scripts/collection_diagnosis.py --db <yedek.db> --output <ozet.json>`.
- `.venv` bu kopyada bozuk (`pyvenv.cfg` yok); sistem `python` çalışıyor.
- Python ağ araçları sandbox'ta `127.0.0.1:9` proxy hatası verebilir. Ağ erişimi
  gerekiyorsa izin mekanizmasını kullan; anahtarları ve proxy ayarlarını yazdırma.

## Canlı haberleşme

Normal yol: gitignore'daki `.local/linko_cli.env` içinde `LINKO_URL` ve
`LINKO_LOG_KEY`; `python scripts/linko_logs.py incidents` ve
`python scripts/linko_logs.py download --source events --since 1d`.

Bu kopyada dosya yoktu. Kullanıcı bağlantının ajan tarafından kurulmasını açıkça
yetkilendirdi. Mevcut GitHub `LINKO_LOG_KEY` secret'ını kullanarak ayrı dalda salt
okuma tanılaması çalıştırıldı; secret çıkarılmadı/değiştirilmedi.

- Dal: `audit/live-collection-diagnosis-20261020`, commit `d5025eb`.
- Bu daldaki `.github/workflows/incidents.yml` yalnız `workflow_dispatch` ile
  tanılama yapar. **Main'e birleştirme:** ana daldaki incident eşitlemesini değiştirir.
- İş: https://github.com/tracecorp24/job_collector/actions/runs/39382262116
- Artifact: `live-collection-diagnosis`, 3 gün saklama.
- Aynı mevcut workflow'u bu dal referansıyla yeniden dispatch ederek güncel
  health, incidents ve app/events JSONL alınabilir. Kodda LOG_KEY yalnız log ve
  incident uçları içindir; bu çalışmada mevcut secret/fallback ile status da
  HTTP 200 verdi. Kullanılan gizli değerin kapsamını yalnız secret adından çıkarma.
- Dispatch: `POST /repos/tracecorp24/job_collector/actions/workflows/incidents.yml/dispatches`,
  JSON: `{"ref":"audit/live-collection-diagnosis-20261020"}`. Sonra aynı branch'in
  Actions run'larını ve run'ın `/artifacts` uçlarını sorgula. GitHub kimliği gerekir;
  anahtarı yazdırma. Yanıtlar salt okuma; POST yalnız tanılama işini başlatır.
- Yerel yardımcılar `.qa/prepare_live_collection_audit.py` ve
  `.qa/download_live_collection_audit.py`; prepare dal oluşturduğu için körlemesine
  tekrar çalıştırma. Güncel run/artifact kimliğini sorgula.

## Ölçüm kuralları

Kart keşfi, ilk detayın tamamlanması ve AI analizi hazır olması ayrı kilometre
taşlarıdır. `collected`, `new` ve `unchanged` birbirinin yerine kullanılamaz.
Snapshot zamanı ile canlı sorgu zamanını belirt. Kaynak bekleme aralıklarını
birleştir, çift sayma. Son deneme sayıları ile kümülatif koşu sayılarını karıştırma.
Eski hız raporlarındaki sıfır 429/WAF algoritması/garantili kapasite iddiaları
küçük örneklerden çıkarılmış; üretim kaydı yerine geçmez.

Canlı ret oranının nedeni kesinleşmiş değildir. Yerel değişiklik canlı doğrulama
yerine geçmez; üretim loglarında aynı ölçümler toplanmadan 429 iyileşti denmemeli.
