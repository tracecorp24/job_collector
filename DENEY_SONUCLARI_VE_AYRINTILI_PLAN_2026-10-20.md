# Toplama hatalarını azaltma: deneyler ve ayrıntılı uygulama planı

Tarih: 20 Ekim 2026. İncelenen üretim sürümü: `f3d6819`.
Saatler ayrıca belirtilmedikçe UTC+3. Bu belge, önceki analizlerin uygulama sırasını
deney sonuçlarıyla günceller. Planın yerel kod değişiklikleri improve/reliable-collection-plan
dalında uygulanıyor. Canlı uygulama birleştirilmedi ve deploy edilmedi; üretim
24–72 saat doğal iş yükü ölçümü henüz yapılmadı.

## Amaç ve başarı tanımı

Amaç, hem liste keşfinde hem detay tamamlamada erişim reddini ve tekrar maliyetini
azaltırken daha fazla **benzersiz, açıklaması gerçekten hazır ilan** üretmek.
Karşılaştırılan iki teknik durum eski akıştaki sürekli oturum ve yeni akıştaki
iş başına oturumdur. Manuel ve rutin işlerin ikisi de aynı korumaları kullanmalı.

Başarı yalnız 429 sayısının düşmesi değildir. İstekler durdurulunca da hata sayısı
düşer. Birlikte izlenecek sonuçlar:

- HTTP 429 ve diğer erişim reddi oranı: 401/403/999 ve HTTP 200 güvenlik sayfası.
- Başarılı, benzersiz detay/saat ve yeni benzersiz kart/saat.
- Karttan ilk açıklamaya, açıklamadan analize p50/p95 gecikme.
- Benzersiz tamamlanmış ilan başına kaynak isteği ve tekrar isteği.
- En eski hazır işin yaşı, kuyruk giriş/çıkışı, kaynak açıkken bekleme süresi.
- Aynı anda aktif kaynak isteği sayısı, kaynak beklemesine uyum, log kaybı.

Sıfır kaynak hatası garanti edilemez. Hedef, aynı kapsam ve kaynak koşullarında
ölçülmüş azalma; başarısızlıkların kontrol altında kalması ve ilanların kaybolmaması.

## Yapılan deneylerin özeti

| Deney | Ortam | İşlem | Sonuç |
|---|---|---|---|
| Tarihsel koşulları eşleme | Kaydedilmiş üretim JSONL; salt okuma | Eski/yeni uç, ilk URL, önceki istek aralığı, zaman ve oturum konumu ayrımı | Gerçek bozulma var; tek başına oturum nedenselliği çıkmıyor. |
| Gerçek HTTP oturumu/bağlantısı | 9 ayrı yerel süreç/DB; yalnız loopback HTTP/1.1 | 72 yerel HTTP isteği, 11 kabul kontrolü | **11/11 geçti**; dış kaynak isteği yok. |
| Üretim kaynak kapısı | Ayrı SQLite + sanal saat; gerçek Coordinator ve scraper | İki modda 18 hata/koruma senaryosu | **18/18 geçti**; ağ isteği yok. |
| Lease süresi | Gerçek Coordinator ve scraper; taklit uzun HTTP | Kısa/uzun aktif istek, ikinci istemci ve 120 saniye aralık kontrolü | **3/3 kontrol geçti**; belirli koşulda lease aşımı riski doğrulandı. |
| Önbellek ve kart revizyonu | 5 ayrı DB; gerçek eski/yeni tamamlama ve manuel force, taklit HTTP | Geçerli cache, değişmiş kart ve açık kullanıcı yenilemesi | **7/7 kontrol geçti**; otomatik yol geçerli cache'i kullanıyor, değişmiş kartı yeniliyor, açık force cache'i atlıyor. |
| Sınırlı canlı pilot | Ayrı GitHub runner; iki kola ortak yerel kaynak kapısı | 23 dakika 59 saniye toplam; kaynak deadline'ı beklendi; yalnız 1 gerçek kaynak isteği | İlk istek **429**; tüm deney durdu. Canlı mod karşılaştırması oluşmadı. |

### 1. Üretim kayıtlarıyla yapılan ek karşılaştırma

Ham kaynak: önceki çalışmada siteden alınan 36.024 olay. Ortak kayıt ufku 20 Ekim
09:18:25 İstanbul'a kadar. Yeni bir kaynak isteği yapılmadan hesaplandı.

| Kontrol | Eski sürekli detay akışı | Son sürüm |
|---|---:|---:|
| Aynı misafir detay uç noktasında 429 | 30/631 = %4,75 | 28/210 = %13,33 |
| Önceki kaynak isteğine 115–180 saniye uzaklıktaki detaylarda 429 | 17/306 = %5,56 | 19/110 = %17,27 |
| Kendi döneminde ilk kez görülen URL'lerde 429 | 30/601 = %4,99 | 24/182 = %13,19 |
| En az 900 saniye kaynak boşluğundan sonraki detaylarda 429 | 0/20 | 3/23 |

İstek aralığı burada **gerçek gözlenen başlangıç farkıdır**; her istekte kaydedilmiş
bir `interval_floor=120` etiketi değildir. Bekleme hatalar sonrası arttığından bu
dilimler de bağımsız deney grupları sayılmaz.

Yeni sürümün ilk 60 detayında 3 adet 429 (**%5**), son 60 detayında 11 adet 429
(**%18,33**) ve 2 adet 403 var. Aynı anda medyan istek aralığı 38,58 saniyeden
124,25 saniyeye çıkıyor. Oturum stratejisi aynı kalırken zamanla bozulma büyümüş.
Oturum kaybının düzeltilmesi gerekli bir aday; kaynağın yük/erişim geçmişi ve
toparlanması ayrıca izlenmeli.

Eski ve yeni dönemler arasında yalnızca **bir ortak detay URL'si** var; ikisi de
başarılı. Bu nedenle “aynı uç” karşılaştırması “aynı ilanla kontrollü A/B” değildir.
Eski ilk oturum isteği sayısı yalnız dört; yeni isteklerin hepsi ilk istek. Eski
ilk dört isteğin de başarılı olması, ilk isteğin kendi başına hata nedeni olduğunu
göstermiyor. Mevcut analizde eski IP geçmişi, saat, ilan seçimi ve seri bağımlılık
tam kontrol edilemiyor.

Araç: `scripts/experiments/observational_experiment.py`.
Sonuç: `.local/performance-audit-20261020/observational-experiment.json`.

### 2. Gerçek yerel HTTP/1.1 ile iki oturum biçimi

Her kolun kendi sahte kaynağı ve DB'si var. Dış ağa çıkış program içinde engelli;
yalnız `127.0.0.1`. Gerçek `requests.Session`, gerçek TCP bağlantıları ve üretimdeki
`Coordinator` kullanıldı. Zaman sanal olarak ilerledi; bekleme silinmedi.

| Yapay kaynak davranışı | Her işte yeni oturum | Sürekli oturum | Çıkarım |
|---|---|---|---|
| Kaynak çerez devamlılığı gerektiriyor | 8/8 ret, 8 TCP bağlantısı | 1/8 ret, 1 TCP bağlantısı | Çerez/bağlantı sürekliliği gerçekten kayboluyor; bu modele özgü hata azalması var. |
| Kaynak oturumdan bağımsız IP zaman penceresi kotası uyguluyor | 2/8 ret | 2/8 ret | Sürekli oturum bu sınırlamayı çözmüyor. |
| Sayısal/tarihli Retry-After | 2/8 ret | 2/8 ret | Her iki mod kaynak beklemesine aynı şekilde uyuyor. |
| Boş 200, kaldırılmış 404/410 | Aynı içerik sonucu | Aynı içerik sonucu | Oturum kullanımı eksik/kaldırılmış ilanı düzeltmiyor. |

Çerezli model bilinçli olarak böyle programlandı; LinkedIn'in aynı algoritmayı
kullandığı sonucu çıkmaz. Başarılı teknik sonuç TCP bağlantı sayımının gerçekten
8'den 1'e düşmesi ve çerezin sonraki isteğe taşınmasıdır.

Ek yaşam döngüsü deneyinde aynı `Session` nesnesine ortada `close()` uygulandı:
çerez devam etti, TCP bağlantısı ikiye çıktı. **`close()` çerez temizlemek değildir**;
nesne kimliğinin aynı olması da bağlantı havuzunun açık kaldığını göstermez.

Araç: `scripts/collection_transport_experiment.py --offline`.
Sonuç: `.qa/collection-transport-experiment.json` ve kol başına ayrı DB/JSON.

### 3. Gerçek koruma kodunun hata senaryoları

18 senaryoda yalnız HTTP yanıtları taklit edildi; `Coordinator` ve `_fetch_url`
üretim kodundan çalıştı. İki oturum biçiminde aşağıdakiler doğrulandı:

- Sayısal ve HTTP-date Retry-After süresi bitmeden sonraki HTTP çağrısı yok.
- 403, 999, HTTP 200 güvenlik sayfası ve giriş yönlendirmesi durduruluyor.
- Oturumu değiştirmek veya yeni engine/Coordinator oluşturmak kalıcı blokajı
  kaldırmıyor; erken `acknowledge` ile bekleme kısalmıyor.
- İstek başı/sonu kayıt callback'i hata verdiğinde lease temizleniyor; kaynak
  duraklatması yanıt sonrası kaydedilmişse bu durum kalıcı kalıyor.
- Oturumdan bağımsız ortak kaynak bütçesi modelinde modlar aynı sonucu veriyor.

Araç: `scripts/experiments/experiment_policy_invariants.py`.
Sonuç: `.local/performance-audit-20261020/policy-experiment.json`.

### 4. Uzun istek sırasında lease aşımı

Gerçek kaynak kapısı, 60 saniye dolduğunda başka istemcinin yeniden edinmesine
izin verebiliyor. Temiz DB ve 10 saniye kaynak aralığıyla yapılan sanal deneyde:

- 20 saniyelik aktif HTTP bitmeden ikinci edinim gerçekleşmedi.
- HTTP taklidi 80 saniye sürdüğünde ikinci istemci 61. saniyede yeni lease aldı.
- İlk istemcinin 80. saniyedeki eski token'la `release` çağrısı ikinci istemcinin
  lease'ini silmedi; token kontrolü doğru çalıştı.
- 120 saniye kaynak aralığıyla aynı 80 saniyelik aktif HTTP deneyinde ikinci
  istemci ancak 120. saniyede izin aldı; çakışma oluşmadı.

Koşullar birlikte önemli: **ikinci istemci + süresi dolan lease + geçmiş
`next_request_at` + hâlâ aktif ilk HTTP**. Bugünkü 120 saniye kaynak tabanında
80 saniyelik HTTP tek başına bu çakışmayı oluşturmaz. Üretimde böyle bir çakışma
olduğu kanıtlanmadı. Bu, kalıcı taşıma tasarımında kapatılacak koşullu bir risk.
`requests` içindeki 20 saniye timeout toplam duvar saati sınırı olarak okunmamalı.

Araç: `scripts/experiments/experiment_lease_expiry.py`.
Sonuç: `.local/performance-audit-20261020/lease-experiment.json`.

### 5. Gerçek tamamlama akışında önbellek ve revizyon deneyi

Eski `Details.fill_one` ile güncel `repair.discover` + iki worker aşaması ve
manuel force akışı, beş ayrı veritabanında karşılaştırıldı. Gerçek işleme kodu
kullanıldı; HTTP yanıtı taklit edildi ve dış ağ soketleri engellendi. **7/7 kontrol
geçti.**

| Durum | Eski `fill_one` | Güncel otomatik repair | Açık manuel yenileme |
|---|---|---|---|
| Aynı karta ait, süresi dolmamış cache; iş açıklaması boş ve pending | 0 HTTP; cache kullanıldı | 0 HTTP; cache kullanıldı | — |
| Kart değişmiş, eski açıklama tutulmuş; cache önceki karta ait | 1 HTTP; güncel açıklama | 1 HTTP; güncel açıklama | — |
| Aynı kartta kayıtlı açıklama ve kullanıcı açıkça yeniden çekmek istedi | — | — | 1 HTTP; güncel açıklama |

Önceki uygulama planındaki otomatik force, geçerli cache'i gereksiz atlatabiliyordu.
Bu davranış uygulama dalında düzeltildi: `detail_pending` tek başına cache bypass
etmez; kullanıcı isteği `_repair_force_requested` ile ayrı tutulur. Kart
fingerprint'i değişikliği algılar ve eski açıklamayı tamamlanmış saymaz. Böylece
force'u tümden kaldırmak yerine otomatik pending, değişmiş kart ve açık kullanıcı
yenilemesi ayrıştırıldı.

Bu deney güncel yerel akışın beklenen davranışını doğruluyor; eski davranışın
canlıdaki sıklığını veya 429 artışındaki payını ölçmüyor. Her pending ilanın
gereksiz istek olduğu söylenemez.

**Canlı yedek kontrolü:** `jobs-20261020.db` salt okunur incelendi. TTL için
arşivin 20 Ekim 06:33:58 İstanbul zamanı referans alındı; bugünün saati kullanılmadı.
1.322 görünür LinkedIn ilanında 10 pending vardı: dokuzunda cache yok; kalan
#1212'de discover normalizasyonuyla geçerli cache var ama görev zaten `enrich/done`.
Aktif `detail/pending` veya `detail/retry` işlerinde gereksiz cache atlatma adayı
**0**. Bu snapshot, cache koşulunun mevcut yavaşlamanın ana nedeni olduğu iddiasını
desteklemiyor. Sayım bir anlık fotoğraf; tarihsel tüm istekleri kapsamaz.

Sayım: `.local/performance-audit-20261020/pending-valid-cache-snapshot-count.json`.

Araç: `scripts/experiments/experiment_repair_cache.py`.
Sonuç: `.local/performance-audit-20261020/repair-cache-experiment.json`.

### 6. Sınırlı canlı pilotun tasarımı

[Pilot çalışması](https://github.com/tracecorp24/job_collector/actions/runs/39387160852)
ayrı `audit/bounded-session-pilot-20261020` dalında çalıştırıldı. Bu dal main'e
birleştirilmez; dalda yalnız deney betiği ve elle başlatılan iş akışı var.
Uygulama deploy edilmedi, üretim DB'sine yazılmadı.

- Mod sırası: sürekli / yeni / yeni / sürekli / yeni / sürekli / sürekli / yeni.
- Tek uç nokta: misafir detay API'si. Uygulama API'sinden seçilen, açıklaması
  bulunan sekiz farklı ilan; sıra önceden sabit tohumla karıştırıldı.
- Kollar tek yerel SQLite kapısını paylaşır. En az 120 saniye, varsa daha uzun
  kaynak aralığı; gerçek gönderimler arasında ayrıca monotonic kontrol var.
- Her gönderimden önce sitenin güncel `source` durumu okunur. Üretim blokajı
  yerel kapıya yalnız `max` ile aktarılır; yerel deadline/taban sıfırlanmaz.
- İlk 429/403/999/güvenlik sayfası/başarısız içerikte tüm kaynak deneyi durur.
  Engel sonrası diğer moda geçip yeni oturumla tekrar denenmez.
- En fazla sekiz gerçek HTTP gönderimi ve 25 dakika çalışma bütçesi var.
- Deney ayrı runner'da; üretimin çıkış IP'si ve DB lease'iyle aynı ortam değildir.
  Bu nedenle üretim 429 nedenini veya kazanan modu belirleyecek A/B sayılmaz.

Sekiz başarı görülse bile genel hata oranının tek taraflı %95 üst sınırı yaklaşık
%31; mod başına dört başarıyla bu sınır yaklaşık %53. Küçük pilot, güvenilir
kapasite/hata oranı veya sıfır 429 iddiası için yeterli değildir.

### 7. Canlı pilotun gerçekleşen sonucu

20 Ekim **10:32:32–10:56:31 İstanbul**; toplam **1.438,762 saniye**.
76 durum gözlemi alındı. Başlangıçta üretim `f3d6819`, 120 saniye taban, 7 ihlal
ve yaklaşık 1.437 saniye kalan blokaj bildirdi. Bekleme son tarihi değişmedi.

Kaynak son tarihi **10:56:29,916**, gerçek ilk gönderim **10:56:30,855**: kayıtlı
blokaj bitmeden kaynak isteği yapılmadı. Sürekli istemci kolunun **ilk** misafir
detay isteği 446 ms'de **HTTP 429**, 24.633 bayt HTML döndürdü; Retry-After yoktu.
Açıklama elde edilmedi. Yerel kaynak kapısı yeniden durakladı ve tüm pilot durdu.
Yeni oturum koluna geçilmedi; tekrar istek gönderilmedi. Toplam gerçek kaynak
gönderimi **1**, tamamlanan açıklama **0**.

Bu, uzun bekleme sonrasında da kaynak reddinin sürebildiğini gösterir; farklı
runner/IP ortamı nedeniyle üretim ortamının nedeni hakkında doğrudan hüküm
vermez. Kalıcı istemcinin ilk isteği henüz sıcak oturum değildir. İki mod için
canlı hata oranı karşılaştırması veya kazanan **yok**. 429 sonrasında diğer kola
geçerek örnek tamamlama yapılmadı. Yerel deneylerde iki mod karşılaştırıldı;
üretim etkisi için Aşama 2'deki doğal iş yükü gözlemi hâlâ gereklidir.

GitHub işinin `success` olması, deney betiğinin düzgün sonlanması ve kaydı
yüklemesi demektir; ilan çekiminin başarılı olduğu anlamına gelmez.
Üretime kod kurulmadı, üretim kuyruğu/DB'si değiştirilmedi. Son durum sorgusunda
224 done / 2 retry, 43 zamanı gelmiş şehir; log dropped/spooled **0** idi.

Kanıt: `.local/performance-audit-20261020/live-pilot/result.json`,
`live-pilot-summary.json`, GitHub run `39387160852` / commit `8dd89c5`.

## Deneylerden sonra değişen kararlar

1. Sürekli HTTP istemcisi birinci aday olarak kalıyor. Yeniden kullanılan şey
   bütün scraper değil, ayrı sahibi olan HTTP istemcisi olmalı.
2. Yalnız oturum düzeltmesiyle tüm 429'ların kaybolacağı beklenmemeli. Kaynak
   toparlanması, anlamsal yanıt sonucu ve ilan başına tekrarlar aynı ölçümde yer almalı.
3. Ham HTTP 200 başarı sayılmamalı. `_fetch_url` HTTP olayını güvenlik kontrolünden
   önce yazıyor; açıklama elde edilmesi ayrı ve zorunlu başarı ölçütü olmalı.
4. Her işin yeni scraper'ı olabilir; HTTP Session kimliği ve istek sırası scraper
   sayacından ayrı tutulmalı. Callback/görev bağlamı iş başına yenilenmeli.
5. Kaynak kapısı ve beklemelerin korunması iki modda da testlerle doğrulandı.
   Hız için bunları sıfırlamak planın parçası değil.
6. Gereksiz arama kesintilerini azaltma ikinci bağımsız değişiklik olmalı;
   oturum etkisiyle scheduler etkisi aynı anda karıştırılmamalı.

## Ayrıntılı uygulama aşamaları

### Aşama 0 — karşılaştırılabilir ve doğru kayıt

**Dosyalar:** `scraper/accountless.py`, `transport.py`, `details.py`, `repair.py`,
`audit.py`, `logstore.py`, gerekirse yalnız alan ekleyen `models.py` / `db.py`.

Her gerçek HTTP gönderimi için:

| Alan | Anlam |
|---|---|
| `process_id`, `transport_session_id`, `session_request_number` | İşler arasında gerçekten aynı istemci mi kullanılıyor? |
| `version`, `run_id`, `task_id`, `attempt_id`, `request_id`, `external_id` | Sürüm, iş ve kaynak isteği bağlantısı. |
| `queue_layer`, `endpoint_kind`, `request_reason` | Manuel/rutin/tamamlama; liste/detay; ilk detay, eksik alan, gerçek kart değişimi, kullanıcı yenilemesi. |
| `policy_before`, `policy_after` | Gerçek taban, etkili aralık, sonraki izin, bloke son tarihi, ihlal serisi. |
| `http_status`, `retry_after_raw`, `retry_after_seconds`, `cooldown_origin` | Kaynağın talebi ile yerel fallback ayrımı. |
| `semantic_outcome`, `description_chars`, `response_bytes` | Kamuya açık içerik, boş yanıt, kaldırılmış ilan, güvenlik sayfası, yönlendirme, ağ hatası. |
| `gate_wait_ms`, `http_ms`, `parse_ms`, `analysis_ms`, `queue_wait_ms` | Beklemeleri birbirine karıştırmayan süreler. |

Çerez, token, Authorization, Set-Cookie değeri kaydedilmez. Çerez sayısı gibi
duyarlı olmayan teknik özetler kullanılabilir. HTTP sonucu ve anlamsal sonuç
aynı `request_id` ile bağlanır. Artık tek başına `request_finished(status=200)`
başarı payına eklenmez. 429 uyarı olarak kalır; her biri yeni incident üretmez.

**Kabul:** HTTP 200 challenge senaryosu ham 200 ve anlamsal challenge olarak
görülür; başarı sayılmaz. Her repair aşaması sonlanır veya açıkça ertelenir;
sessizce SSE'ye yazılıp kaybolmaz. Bekleme aralıkları birleşimle sayılır.

### Aşama 1 — HTTP istemcisinin açık sahipliği

**Dosyalar:** `transport.py`, `scraper/accountless.py`, `repair.py`, `pipeline.py`,
`service.py`, `serve_service.py`, CLI uyumluluğu için `run_accountless.py`.

1. Süreç içinde seri kullanılacak bir HTTP istemcisi sahibi ekle. Oturum, header,
   cookie jar, adapter havuzu ve Session'a ait istek sırası bu nesnede yaşasın.
2. Her iş kendi `emit`, `should_stop`, run/task bağlamını ve scraper istatistiğini
   oluştursun; bunlar kalıcı HTTP sahibinin içine kapanıp sonraki işe taşınmasın.
3. Scraper'ın dışarıdan istemci alması desteklensin. Varsayılan CLI yolunda kendi
   oluşturduğu istemciyi kapatma hakkı açıkça tanımlansın.
4. `scrape()` finally ve `repair.worker` finally ödünç alınan istemciyi kapatmasın.
   Sahip olduğu bağımsız istemciyi kapatma davranışı geriye uyumlu kalsın.
5. İstemci aynı anda bir işte ödünç alınabilsin. Worker thread'leri işler arasında
   değişse de cookie/header/close/reset işlemleri çakışmasın. DB yazma kilidi HTTP
   boyunca tutulmasın. Kaynak kapısı mevcut ortak DB/source anahtarında kalsın.
6. Normal 429, 403, captcha veya kullanıcı duraklatması session yenileme nedeni
   olmasın. Kaynak deadline'ı korunarak iş ertelensin. Süreç kapanışında sahibi
   tüm yanıtları ve adapter'ları kontrollü kapatsın.

**Anlamlı testler:** ardışık iki detay ve rutin devamında aynı session ID ve artan
sıra; gerçek TCP reuse; borrower sonrası kapanmamış pool; farklı job_id'ye doğru
event atfı; eski stop callback'inin yeni işi kesmemesi; iptalde gate edinilmemesi;
iki thread'in aynı HTTP sahibini eşzamanlı kullanamaması; shutdown temizliği.

**Kabul:** yerel transport deneyindeki 11 kontrol yeni mimaride korunur;
ek gerçek kaynak isteği oluşmaz; kalıcı blokaj, önbellek ve checkpoint korunur.

### Aşama 1B — uzun istek ve lease sahipliği

**Dosyalar:** `transport.py`, `scraper/accountless.py`, yaşam döngüsü testleri.

Aktif HTTP'nin bitmediği durumda lease'in zaman aşımıyla ikinci istemciye
verilmesini önlemek için owner token'ına bağlı süre yenileme veya bütün isteğin
güvenilir üst sınırını aşan lease tasarımı seçilsin. Yalnız `timeout=20` yeterli
gerekçe sayılmasın. Seçim kontrollü uzun yanıt deneyinde doğrulansın.

Owner kaybında yeni istek/redirect gönderilmesin. Eski owner yeni owner'ın kaydını
silemesin. Çöken süreç sonsuz kilit bırakmasın; yenileme durunca kurtarma mümkün
olsun. Bu, bugünkü 429 artışının kanıtlanmış nedeni değil, ek güvenilirlik işi.

### Aşama 2 — yalnız istemci değişikliğini üretimde ölç

Üretim DB yedeği ve metrik başlangıcı alındıktan sonra yalnız Aşama 0/1 değişikliği
kurulsun. Aynı anda endpoint, UA, minimum aralık, cooldown veya scheduler değişmesin.
Mevcut kaynak beklemesi varsa süresi aynen beklensin; rollout sayaçları temizlemesin.

En az 24 saat ve mümkünse en az 200 detay isteği gözlensin. Tarihsel %13,33 ile
%4,75 farkını ayırmak, bağımsız denemeler varsayımında yaklaşık 175 istek/mod
gerektirir; zaman/IP bağımlılığı bu sayıyı artırabilir. Hacim yoksa ölçüm 48–72
saate uzatılır; eksik örnekle “çözüldü” denmez. Örnek için ek kaynak yükü üretilmez.

**Karşılaştırma:** endpoint, arama kapsamı, yeniden deneme/ilk URL, günün saati ve
başlangıç kaynak durumu ayrı raporlanır. Zaman veya koşu bazında kümelenme dikkate
alınır. Kaynak tabanı hataya tepki olduğu için ham aralık dilimleri nedensellik
kanıtı diye kullanılmaz.

**Kabul:** karşılaştırılabilir dilimlerde erişim reddi düşerken benzersiz detay/saat
artar veya korunur; 403/999/challenge artışıyla gizlenmiş 429 düşüşü olmaz. p95
detay gecikmesi ve eski görevlerin yaşı kötüleşmez. Yeterli iyileşme yoksa diğer
değişiklikler tek başına ilaç ilan edilmeden kaynak/toparlanma incelemesi sürer.

**Geri dönüş:** yalnız uygulama sürümünü geri al; üretim DB'sini eski yedeğe döndürme.
Kaynak durumu, son toplanan ilanlar ve incident geçmişi korunur. Oturum kaynaklı
sayaçlar süreç yeniden başladığını açıkça işaretler.

### Aşama 3 — ilan başına tekrarları ve revizyonları yönet

**Dosyalar:** `repair.py`, `models.py`, `db.py`, `transport.py`, `pipeline.py`.

- `attempts` alanının mevcut anlamını bozma. Bunun yanına toplam ağ gönderimi,
  erişim reddi sayısı, ilk/son ağ denemesi, son anlamlı ilerleme ve retry nedeni ekle.
- Genel kaynak deadline'ı her zaman alt sınırdır. Tek bir sorunlu ilanın bunun
  üzerine daha geç denemesi olabilir; global beklemeyi kısa devre eden istisna yok.
- Geçici erişim reddi, kalıcı kaldırılma ve parse hatası ayrı durumlar olsun.
  403/429'u ilanın kesin kaldırıldığı şeklinde işaretleme; 404/410 mevcut kısa
  negatif cache politikasıyla ele alınsın.
- Tekrar eşiğine ulaşan iş bekletilebilir ve görünür inceleme durumuna alınabilir;
  veri silinmez, otomatik ilk sıraya sonsuz geri dönmez. Tekrar açma kaynak
  deadline'ını kaldırmaz. Eşik üretim verisiyle belirlenir; rastgele üç retle
  kalıcı veri kaybı yaratılmaz.
- Kaynak kart revizyonu ve açıklama hash'i; run/task/analiz metadata'sından ayrı
  tutulsun. Yalnız provenance değişikliği yeniden indirmeye neden olmasın.
- `done` tamamlama işi olan ilanda yeni gerçek kart revizyonu eksikse aynı benzersiz
  kaynak/ilan işi atomik olarak yeni revizyon için açılabilsin; aynı revizyonda
  retry zamanı/başarısızlık sayısı tekrar keşifte sıfırlanmasın.
- `detail_pending` tek başına `force=True` anlamına gelmesin. Aynı revizyona ait
  kullanılabilir açıklama varsa gereksiz kaynak isteği yerine yerel aşama kullanılsın.
- Açıklamanın mevcut olması yeterli sayılmasın: hangi kart revizyonundan geldiği
  doğrulansın. Değişmiş kartta tutulan eski açıklama, güncel detayın yerine geçmesin.
  Cache isabeti, cache atlama nedeni ve açık kullanıcı yenilemesi ayrı kaydedilsin.

**Zorunlu karşı örnekler:** geçerli cache + boş açıklama + pending → sıfır HTTP;
değişmiş kart + eski açıklama → güncel açıklama alınmadan `done` yok; süresi dolmuş
cache → kaynak kapısından geçen tek yenileme; aynı revizyonun yeniden keşfi → yeni
iş/istek yok; açık kullanıcı force → cache atlanır ama kaynak deadline'ı korunur.

**Kabul:** #1212 benzeri `done` + pending tutarsızlığı uzlaştırılır; başarılı
detay gereksiz yere yeniden indirilmez; eski içerik yeni revizyona aitmiş gibi
etiketlenmez; işlem yarıda kesilse bile kaynak/ilan başına tek kalıcı iş kalır.

### Aşama 4 — önce kart ve detay işlerini dengeli yürüt

**Dosyalar:** `service.py`, `scheduling.py`, `routine_cities.py`, `watches.py`,
`runs.py`, `repair.py` ve kuyruk görünümü.

1. Manuel iş önceliği kalsın. Rutin kartların oluşturduğu normal detay işleri,
   bütün rutini her sayfada kesen sınırsız üst öncelik olarak ele alınmasın.
2. Bir keşif dilimi bir sorgu/sayfa gibi güvenli checkpoint sınırında bitsin;
   sonraki dilimde yaşa ve bütçeye göre detaylar işlensin. Bir şehrin tüm 15
   sorgusunun bütün sayfaları bitmeden diğer şehirler sonsuz beklemesin.
3. Sabit “1 liste : 3 detay” kuralı otomatik varsayılmasın. Sayfa 10 yeni kart
   getiriyorsa böyle bir oran kuyruğu sürekli büyütür. Ölçülen yeni kart verimi,
   hazır detay sayısı ve en eski bekleme yaşına göre bütçe ayarlansın.
4. Başlangıç önerisi: şehir/meslekler arasında ilk sayfa dolaşımı ve biriken
   detayları karşılayacak iş bütçesi; detay yaşı/hedef backlog aşılınca keşif
   azaltılsın. Kaynak açıkken hem keşfe hem hazır detaylara ilerleme garantisi
   sağlansın. Yoğun manuel kullanım bu garantinin koşullarında ayrıca belirtilsin.
5. 60 saniye sessizlik kullanıcı etkileşiminden rutine geçişi korusun. Rutinin
   kendi detaylarından sonra her seferinde bu süre baştan başlamasın.
6. Kaynağın tümü bilinen sayfa/yenilik eşiği korumaları devam etsin. “Keşfedilmiş
   kimlik” ile “açıklaması hazır kimlik” ayrı kontrol edilsin; pending kimlik
   tekrar yeni kart sayılmasın.

**Kabul:** aynı kayıtlı yanıtlarla eski/yeni scheduler karşılaştırmasında benzersiz
sonuçlar aynı; checkpoint kaybı yok; manuel iş bir güvenli sınırda öncelik alır;
sessiz saatler azalır; kaynak istek tabanı veya Retry-After değişmez. Kaynak kapalı
süre hedef bekleme ihlali diye sayılmaz; kullanılabilir kaynak süresi ayrıca ölçülür.

**Bütçe hesabı:** kaynak açıkken istek kapasitesinin iyimser üst sınırı
`R = 3600 / etkili_aralık` olsun. Listeye ayrılan pay `p`, liste başına benzersiz
yeni kart `y`, başarılı yeni detay başına gereken kaynak isteği `d` ise kart girişi
`R*p*y`, detay çıkışı en fazla `R*(1-p)/d` olur. Kuyruğun sürekli büyümemesi için
`p <= 1/(1+y*d)` gerekir. Bu, uygulanacak sabit oran değil, ölçülen verimle
zamanlayıcının kontrol edeceği yük koşuludur.

Örneğin 120 saniye, sayfa başına 10 yeni kart ve detay başına bir istek varsayımıyla
en iyimser toplam 30 istek/saat; dengeli keşif+detay çıkışı yaklaşık 27 ilan/saat.
Jitter, yanıt süresi, tekrar ve kaynak blokajları bunu düşürür. Yaklaşık 300 kart/saat
keşif ile 300 yeni açıklamayı/saat indirmek farklı kapasitelerdir. Bu kaynak tabanı
korunurken yeni açıklamalar için ikincisi vaat edilemez; yerel cache tamamlamaları
ayrı sayılır. Yükü azaltan değişikliklerin gerçek katkısı ölçülerek raporlanır.

### Aşama 5 — detay ve AI aşamalarını ayır

Kaynak açıklaması indirildiğinde, açıklama hazır olma anı AI çağrısının arkasında
gizlenmesin. Kaynak verisi ve ilerleme işlemsel saklansın; analiz ayrı kalıcı
aşamada devam etsin. Boş açıklamaya LLM çağrısı yapılmasın.

Başlık + açıklama hash'i + model/prompt/kurallar sürümüyle analiz yeniden kullanımı
tanımlansın. Değişmeyen içerik aynı modelle yeniden işlenmesin; içerik değiştiğinde
eski embedding geçersiz kalsın. Model kotası, sağlayıcı hatası ve kurallara dönüş
ayrı sonuçlar olarak kaydedilsin. Kaynak beklemesi sırasında kaynak gerektirmeyen
analiz ilerleyebilir; kaynak izni gelince ikinci ağ collector'ı oluşmasın.

**Kabul:** aynı açıklamada bir AI çağrısı; içerik/sürüm değişiminde yeniden analiz;
AI hatası açıklamayı ve ilk keşif zamanını kaybettirmez. Detay hazır ve analiz
hazır sayaçları kullanıcıya anlaşılır ayrı durumlarla sunulur.

### Aşama 6 — alarm ve paneli gerçek ilerlemeye bağla

**Dosyalar:** `problems.py`, `dashboard.py`, `audit.py`, `service_api.py`, UI.

Tarihsel minimum `min=0` hatası kaldırılıp son başarılı ilerleme zamanı, en eski
**hazır** iş ve kuyruk giriş/çıkışı izlenir. Boş kuyruktan yeni kuyruğa geçiş yeni
izleme dönemi başlatır. Kullanıcı pause'u ve kaynak blokajı, kaynağın açık olduğu
halde ilerlememe durumundan ayrılır.

Panel: son 1/6/24 saatte benzersiz kart ve detay hızı; uç başına erişim reddi;
gerçek etkili aralık; birleşik kaynak beklemesi; kuyruk katmanı süreleri; en eski
hazır detay; retry nedenleri ve log kayıp sayaçları. Son deneme ve kümülatif koşu
sayıları ayrı etiketlenir. `/healthz` ile verimlilik sağlığı birbirinin yerine geçmez.

**Kabul:** başarılı tamamlama sürerken “60 saattir azalmadı” çıkmaz; gerçek ilerleme
yoksa alarm çıkar. Incident'in otomatik kapanması, kontrollü performans kabulünün
yerine geçmez. Düzeltilen incident için mevcut 24 saat izleme sürer.

### Aşama 7 — kaynak toparlanmasını ölçümle ayarla

Bu aşama oturum, tekrar ve scheduler sonuçları görülmeden uygulanmaz. Kaynak
başlığındaki Retry-After ve güvenlik doğrulaması korunur. Yerel fallback kökeni
açık kayıtlı olur. Kalıcı minimumun ne kadar süre yüksek kaldığı, son kaynak
reddinden beri geçen süre ve başarılı içerik serisi birlikte değerlendirilir.

Kararlı başarıda daha sağlıklı toparlanma modeli gerekiyorsa önce sanal saat ve
aynı tarihsel durum izleriyle karşılaştırılır. Yeni hata → yeniden deneme → yeni
hata döngüsü azalmadan salt aralığı düşürmek hız çözümü sayılmaz. Tek kaynak kapısı
ve tek collector korunur; IP/çerez/oturum döndürerek engel aşma eklenmez.

## Yayına alma ve durdurma koşulları

Her aşama ayrı gözden geçirilebilir değişiklik olmalı. Geriye uyumlu alan ekleme,
mevcut veride veri silmeyen göç, uygulama DB yedeği ve kaynak durumunu koruma
zorunlu. Yalnız deney branch'leri uygulama branch'ine birleştirilmez.

Anında durdurma/geri değerlendirme: kaynak beklemesi sürerken HTTP gönderimi,
aynı anda iki kaynak isteği, yanlış ilanda callback/DB güncellemesi, veri kaybı,
auth/cookie bilgisinin loga girmesi, unhandled worker hatası. 429 tek başına yeni
session açma sebebi olamaz. Düşük hacim başarı olarak raporlanmaz.

Yeni bir davranışta anlamlı regresyon testleri ve mevcut test paketi çalıştırılır.
Canlıda her aşama için açık ölçüm başlangıcı/bitişi ve gerçek SHA saklanır.

## Yeniden çalıştırılabilir araçlar

### Mevcut test paketinin sonucu

Mevcut paket 239 test çalıştırdı: 238'i geçti, yalnız
`test_portable_without_main_project` alt sürecinin `--help` çağrısı 15 saniyelik
zaman aşımına uğradı. Aynı test tek başına yeniden çalıştırılınca geçti. Bu yüzden
sonuç “ilk koşuda temiz 239/239” değildir; ilk koşuda bir timeout ve başarılı
tekil tekrar olarak kaydedildi. İlk sandbox koşusundaki geçici klasör izin
hataları da ortam kaynaklıydı; paket gerekli izinle yeniden çalıştırıldı.

Kayıtlar: `.qa/experiment-regression.log`, `.qa/portable-recheck.log`.
Deney girdileri ve sonuçları için SHA-256 kayıt dosyası:
`.local/performance-audit-20261020/experiment-manifest.json`.

### Offline deney komutları

```powershell
.\.qa\collection-venv\Scripts\python.exe -B scripts/collection_transport_experiment.py --offline
.\.qa\collection-venv\Scripts\python.exe -B scripts/experiments/experiment_policy_invariants.py
.\.qa\collection-venv\Scripts\python.exe -B scripts/experiments/experiment_lease_expiry.py
.\.qa\collection-venv\Scripts\python.exe -B scripts/experiments/experiment_repair_cache.py
python scripts/experiments/observational_experiment.py
```

`scripts/experiments/` altındaki kopyalar gelecek ajanların deneyleri yeniden
kurabilmesi için kalıcı tutuldu. İlk koşuların `.qa/` asılları korunuyor; taşınan
kopyalarda yalnız proje kökü hesabı değişti ve sözdizimi kontrol edildi.
Python ortamının bu kopyadaki yolu örnektir; temiz kurulumda proje bağımlılıkları
kurulu bir Python ortamı kullanılır. Ham canlı veriler ve `.qa/` kayıtları gitignore
altında kalır; depodaki bu rapor toplu sonuçları ve sınırlarını saklar.

İlk araç ayrı loopback sunucuları kullanır; diğer deneylerde kaynak ağı taklit
edilir/engellenir. `scripts/collection_live_pilot.py` bunlardan farklıdır: açıkça
anahtarlı kontrol erişimi ister, sınırlı gerçek kaynak isteği yapabilir; rutin
test paketinin veya otomatik CI'ın kendiliğinden çalışan parçası değildir.

`scripts/experiment_burst_pacing.py`, `experiment_session_reset.py` gibi eski
deneyler ortak üretim kaynak kapısını kullanmıyor. Bu yeni incelemede canlı
çalıştırılmadılar; eski küçük örneklerin WAF/IP algoritması iddiaları kabul kriteri
olarak kullanılmıyor.

## Planı uygulama durumu (20 Ekim 2026)

| Aşama | Yerel değişiklik | Durum ve kalan iş |
|---|---|---|
| 0 — doğru kayıt | Her HTTP isteğine run/task/attempt/request/session kimliği; kuyruk katmanı ve istek nedeni; kaynak politikası öncesi/sonrası; HTTP, parse ve gate süreleri; ham HTTP ile anlamsal sonuç; Retry-After kökeni eklendi. Audit raporu 200 içeriksiz yanıtı ve eşleşmeyen başlangıç olaylarını sayıyor. | Kod tamam; canlı log hacmi ve kayıp oranı üretimde ölçülmeli. |
| 1 — HTTP sahibi | İş başına scraper aynı süreç sahibindeki seri HTTPTransport nesnesini ödünç alıyor; iş callback’leri taşınmıyor; 429 sonrası session değiştirme yok; kapanışta güvenli kapatma eklendi. | Kod ve hedefli testler tamam; gerçek kaynak etkisi gözlenmedi. |
| 1B — lease | Owner-token ile lease yenileme, istek başı heartbeat, servis kapanırken iptal ve worker bitmeden session kapatmama eklendi. | Kod/test tamam; çok süreçli canlı çakışma ölçülmedi. |
| 2 — üretim ölçümü | — | Bekliyor: deploy/yedek ve başlangıç ölçümü onaylandıktan sonra 24–72 saat doğal iş yükü. Bu dalda deploy yapılmadı. |
| 3 — cache/revizyon | Eşleşen geçerli cache’in detail_pending nedeniyle zorla atlanması kaldırıldı; kart fingerprint’i ayrı tutuluyor; değişmiş kartın eski açıklaması tamamlanmış sayılmıyor; aynı karttaki done + detail_pending yerelde uzlaştırılıyor, değişmiş kart için görev yeniden açılıyor; ağ denemesi/ret sayaçları kalıcı. | Hedefli cache ve görev testleri var. Üretimde #1212 benzeri kayıtlar için yedek üzerinde salt-okunur doğrulama yapılmalı. |
| 4 — kuyruk adaleti | Detay kuyruğu ve rutin iş arasında kaynak isteği sayısı, backlog yaşı ve hacme göre sınırlı dönüş bütçesi eklendi; scheduler her turda tüm backlog zamanlarını ORM’ye çekmiyor; mevcut kart-önce/detay-sonra akışı korundu. | Hedefli service testi geçti. Şehirler arasında ilk sayfa round-robin’i ve gerçek kapasiteye göre bütçe ayarı sonraki aşama. |
| 5 — kaynak/AI aşamaları | Repair’den process_raw çağrısına olay callback’i veriliyor; işlem aşaması ve sonuç zamanları kaydediliyor. | Kısmi: model token/kota metrikleri, içerik hash’i ile analiz tekrar kullanımı ve ayrı AI kuyruğu henüz yok. |
| 6 — alarm/ölçüm | Backlog alarmı boş/pause/kaynak blokajını stall saymıyor; kuyruk sayısı sabit kalsa da başarılı detail event’i ilerleme kabul ediliyor. Audit raporunda anlamsal sonuç, session sayısı ve detay başarı sayısı var. | Uygulama alarm/audit tarafında tamam; dashboard/API görünümü ve 1/6/24 saat hız göstergeleri eklenmedi. |
| 7 — toparlanma politikası | Mevcut Retry-After, ortak gate ve source cooldown korunuyor. | Bilerek ertelendi. Yeni interval/backoff veya 429 sonrası oturum stratejisi eklenmeyecek; doğal üretim kanıtı bekleniyor. |

### Uygulama dalındaki doğrulama

- scripts/collection_transport_experiment.py --offline: dokuz loopback kolunda
  72 yerel HTTP isteği ve 11/11 kontrol geçti. Yapay çerez gereksiniminde fresh
  oturum 8/8, kalıcı oturum 1/8 kez 429 aldı; yapay IP bütçesi ve Retry-After
  kolları iki modda aynı sonucu verdi. Bu LinkedIn ölçümü değildir. Sonuç:
  .qa/collection-transport-implementation-2026-10-20.json.
- Hedefli testler: test_transport 15, test_repair 16, test_service 12,
  test_scheduling 22, test_details 13, test_problems 17 ve test_audit 9 test geçti.
- test_light 11 testten 9’unu geçti; kalan iki UI assertion mevcut kullanıcı
  arayüzü dosyalarının “Linko Scrapper Light” ve quick-filters beklentileriyle
  uyuşmamasından başarısız. İlgili arayüz değişiklikleri çalışma başlamadan vardı
  ve bu uygulamada değiştirilmedi.
- Tam 239 testlik paket yeni uygulama dalında yeniden temiz sonuçla çalıştırılmadı.
  Eski baseline’daki bir portable alt süreç timeout’u ve bu dalın UI assertion
  farkları yüzünden 239/239 geçti iddiası yok.
