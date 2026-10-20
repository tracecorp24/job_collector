# Eski ve yeni sürümlerde HTTP 429 karşılaştırması ve güncel plan

20 Ekim 2026. Ana raporun eki: `deney_sonuclari/TOPLAMA_HIZI_ANALIZI_2026-10-20.md`.
Kullanıcının istediği deneylerden sonraki güncel ve daha ayrıntılı uygulama planı:
`deney_sonuclari/DENEY_SONUCLARI_VE_AYRINTILI_PLAN_2026-10-20.md`. Aşağıdaki başlangıç planının
üzerine oturum sahipliği, anlamsal başarı, lease ve zamanla bozulan kaynak
toparlanması deneyleri eklendi.
Dayanak: 09:45 İstanbul'da indirilen üretim logları; son olay 09:18:25 İstanbul.
Bu ek için kaynağa yeni ilan isteği gönderilmedi; kayıtlar ve Git geçmişi incelendi.

## Sonuç

**Son kararlı eski tamamlayıcıyla karşılaştırınca yeni sürümde 429 oranı gerçekten
artmış.** Aynı misafir detay uç noktasında eski akış **%4,75**, son sürüm **%13,33**:
yaklaşık **2,8 kat**. Bütün eski sürümlerin sıfır 429 aldığı söylenemez; ancak yeni
akıştaki artış, yalnızca günlük ilan sayısının azalmasından veya alarm hatasından
ibaret değil.

En güçlü kod kaynaklı aday **HTTP oturumunun her işte yeniden oluşturulması**.
İstek başlangıcı olayları bunu doğruluyor: eski tamamlayıcıda 631 detay isteğinin
yalnızca 4'ü `request_number=1`; yeni tamamlayıcıda **257 isteğin tamamı 1**.
Yeni arama/listeme isteklerinin de **49/49'u** yeni scraper'ın ilk isteği.

Bu, oturum sürekliliğinin kaybolduğunu kanıtlar. LinkedIn'in bu yüzden hangi
isteği neden reddettiğini kanıtlamaz. Çerez/bağlantı devamlılığını kaybetmek güçlü
bir neden adayıdır; kaynağın IP değerlendirmesi, saat, sorgu, ilan ve geçmiş yük
farkları ayrıştırılmadan tek neden ilan edilmemeli.

## Karşılaştırma

Sınıflandırma HTTP URL yolundan yapıldı; liste ve detay istekleri ayrı sayıldı.
`request_finished` satırları kullanıldı; `source_paused`, uyarı ve retry olayları
yeniden HTTP isteği sayılmadı.

| Akış | Uç nokta | İstek | 429 | 403 | 429 oranı |
|---|---|---:|---:|---:|---:|
| Eski kalıcı detay tamamlayıcı | `/jobs-guest/jobs/api/jobPosting/…` | 631 | 30 | 0 | **%4,75** |
| Yeni katmanlı kuyruk, 60 saniye kuralından önce | Aynı detay ucu | 47 | 3 | 0 | %6,38 |
| Son sürüm `f3d6819`, 60 saniye kuralından sonra | Aynı detay ucu | 210 | 28 | 3 | **%13,33** |
| Yeni tamamlayıcının bütün dönemi | Aynı detay ucu | 257 | 31 | 3 | %12,06 |

Son sürümde 429 ve 403 birlikte ele alındığında detay erişim reddi **31/210 =
%14,76**. Bu, eski dönemde aynı uçta %4,75 olan erişim reddinden daha yüksek.

Eski tamamlayıcının son penceresinde 203 detay isteği, 197 başarı, 6 adet 429
var: **%2,96**. Bu daha kısa ve farklı saatlerde bir pencere olduğundan bütün eski
dönemin yerine kullanılmadı. Kaynak olayı kapsamı ve uç nokta eşleşmesi daha iyi
olan 631 isteklik örnek ana karşılaştırma olarak tutuldu.

Sürüm zamanları başarılı Actions işlerinin bitiş zamanıyla yaklaşık eşleştirildi;
kesin sürüm alt tablosunda deploy'a ±120 saniye yakın istekler dışarıda bırakıldı.
Eski `e618e16` için bu yöntemle 629 detay / 30 adet 429, **%4,77** bulunuyor.
Her istek satırında SHA bulunmadığı için bu eşleştirme yaklaşık; akış gruplarının
kesim noktaları ve tam sayılar `.local/performance-audit-20261020/429-comparison.json`
dosyasında saklı.

## Artışı açıklayan değişiklikler

### 1. Kalıcı oturum yerine her detayda yeni oturum — birinci inceleme önceliği

`34bca7d` öncesinde `details.start()` döngüsü scraper'ı bir kez oluşturuyor,
`scraper = scraper or AccountlessScraper(...)` ile aynı nesneyi tekrar kullanıyordu.
İstek sayacı bir oturumda 628'e kadar yükselmiş.

Yeni `repair.worker`, her detay için `AccountlessScraper(...)` oluşturuyor,
`finally` içinde `scraper.session.close()` çağırıyor. Oturumun kendisi ve içindeki
çerez/bağlantı havuzu bir sonraki detay işine taşınmıyor. HTTPAdapter ekli olması
bu yaşam süresi sorununu çözmüyor.

`Session` nesnesinin çerezleri ve bağlantı havuzunu istekler arasında koruması,
[Requests'in resmi belgesindeki](https://requests.readthedocs.io/en/latest/user/advanced/#session-objects)
davranış. Bağlantı/çerez devamlılığının kaybolması kesin; bunun 429'a etkisinin
büyüklüğü henüz ölçülmedi. Çerez veya oturum döndürme ile engel aşma önerilmiyor;
eski sürümdeki normal, sürekli istemci yaşam döngüsünün geri kazanılması öneriliyor.

### 2. Öncelik devri liste oturumlarını da sık kapatıyor — doğrulandı

Yeni rutin, kart sayfasından sonra detay kuyruğuna sıra bırakıyor. Tarama çıkışında
oturumu kapanıyor; devam edince yeni scraper kuruluyor. Yeni dönemde 49 liste
isteğinin tamamının `request_number=1` olması bu parçalanmayla uyumlu.

Eski hızlı koşuda 33 kaynak isteğiyle 293 yeni kart bulunmuş; bunların 2'si 429.
Bu örnek 300/saat civarındaki kart keşfini destekliyor, sıfır hata iddiasını
desteklemiyor. Kartların liste halinde gelmesi çok sayıda detay isteğiyle aynı
yük profili değildir.

### 3. Artış daha sık istek atılmasına bağlanamıyor

Yeni katmanlı akışın ilk döneminde kaydedilen istek başlangıçları arası en kısa
süre **10,04 saniye**; son sürüm döneminde **33,76 saniye**, medyan **124,29 saniye**.
Bu iki yeni dönemde 9 saniyeden kısa aralık yok. Eksik istek kaydı veya başka bir
istemcinin aynı IP'yi kullanması bu kayıtlardan dışlanamaz; fakat uygulamanın
görünen yeni akışında hızlanmış istek patlaması kanıtı yok.

429 sayısı artarken sistem kendi korumasıyla daha da yavaşlıyor: hata → aralığı
1,5 kat büyütme → uzun bekleme → az sayıda başarı → yeni hata. Bu geri besleme
ilk hatanın nedenini açıklamıyor, **hız düşüşünü büyütüyor**.

### 4. Bazı ilanlar tekrar tekrar reddediliyor; bütün kaynağı bekletiyor

Örnek `4475690215`: 20 Ekim UTC **03:10 429 → 04:59 403 → 05:16 429 → 05:18 200**.
Bir başka ilanda iki 429 sonrası başarı, bir başkasında son kayda kadar iki 429 var.
Bu yüzden `RepairTask.attempts=0`, işin ilk ağ denemesinde olduğu anlamına gelmiyor.
`SourcePaused` sayacı artırmıyor ve bu durum için ilan başına terminal deneme sınırı yok.

Bir ilanın reddi ortak `source_policy` üzerinden tüm liste/detay akışını bekletiyor.
Kaynağın gerçekten IP, oturum veya ilan bazında karar verdiği eldeki yanıtlardan
kesinleşmiyor. Sonuç çıkarmadan kaynak genelindeki bekleme korunmalı; sorunlu iş
için bunun üzerine daha geç bir deneme zamanı ve ayrı izleme uygulanabilir.

### 5. Eski hataların bir kısmı görünmüyordu — doğrulandı

`37aa6b5` commit'i açıkça, eski arka plan tamamlayıcısının scraper'ı `emit` olmadan
kurduğunu ve 429/kilitlerinin ölçüm kayıtlarına girmediğini düzeltiyor. Bu commit'ten
önce “logda 429 yok” sonucu “kaynak 429 vermedi” anlamına gelmiyor.

Daha sonraki eski tamamlayıcı olayları DB'ye yazarken yeni `repair.worker` ayrıca
`server.state.emit` ile arayüze aktarabiliyor. Kullanıcının gördüğü uyarılar da
artmış olabilir. Buna rağmen aynı detay uç noktasındaki %4,75 → %13,33 artışı
ölçülen gerçek bir bozulma; görünürlük farkıyla geçiştirilemez.

### 6. Henüz ana neden olarak gösterilemeyecekler

- Hafif detay API'si, düşük 429'lu eski `e618e16` döneminde de kullanılıyor.
  19 Ekim sonrası artışı tek başına bu uç noktaya geçiş açıklamıyor.
- Kullanıcı aracısı ve temel HTTP başlıkları kuyruk değişikliğinde değişmemiş.
  Yeni sürüme özgü başlık bozulması bulunmadı.
- 60 saniyelik bekleme ve uzun ortak aralıklar çıktı hızını azaltır; doğrudan
  daha sık istek oluşturan değişiklikler değildir.
- Düşük yenilik oranı, aynı ilanlara rastlanması ve şehir kapsamı yeni ilan
  sayısını etkiler; bir HTTP isteğinin 429 olmasının tek başına açıklaması değildir.
- Kaynak IP'sinin önceki yükü, başka programlar ve sunucu tarafı karar değişimleri
  için yeterli telemetri yok. Bot yönetiminin algoritması veya çerez puanlaması
  hakkında kesin hüküm verilemez.

## Retry-After ve yerel bekleme ayrımı

İndirilen kayıtta **167 adet 429 ve 3 adet HTTP 403'ün hiçbirinde `Retry-After`
değeri kayıtlı değil**. İlgili log alanı boş olduğundan bu yanıtlarda 15/32/64
dakikalık süreleri kaynağın başlıkla istediği söylenemez; süreler mevcut yerel
üstel bekleme politikasından geliyor. Ham yanıtlar saklanmadığı için eski başlık
kaydının doğruluğu bağımsız olarak yeniden doğrulanamaz.

Bu ayrım beklemeyi atlama gerekçesi değildir. Plan, kaynak başlığıyla gelen süre
ile yerel fallback'i ayrı kaydetmeyi ve politikanın gerçek sonucu ölçüldükten sonra
değerlendirilmesini gerektiriyor. 120 saniyelik kalıcı taban ve üstel bekleme
mantığı 19 Ekim kuyruk değişikliğinden önce de kodda var; yeni eklenmiş bir
cezalandırma kuralı olarak sunulmamalı.

## Güncellenmiş uygulama planı

İlk plandaki “oturum kullanımını sonradan değerlendir” sırası değiştirildi.
**Önce kaynak istemcisindeki gerileme, sonra scheduler ve bekleme ayarı** ele alınmalı.

| Sıra | İş | Doğrulama / kabul koşulu |
|---|---|---|
| 0 | Her ağ isteğine süreç/oturum kimliği, oturumun kaçıncı isteği, uç türü, aktif kuyruk katmanı, sürüm ve gerçek kaynak aralığı ekle | Yeniden başlatma ile iş başına oturum yenilenmesi ayırt edilebilir. Çerez/anahtar içeriği yazılmaz. |
| 1 | Supervisor'ın sahip olduğu, seri kullanılan HTTP istemcisini detay işleri ve rutin devamları arasında yaşat | İki ardışık normal işte aynı session kimliği ve artan sıra numarası; iş bitti diye kapatma yok; süreç kapanışında kapatma var. Tek collector ve ortak kaynak kapısı korunur. |
| 2 | Yalnız oturum yaşam süresi değişikliğini, mevcut gerçek kuyrukta gözlemle | Aynı kaynak aralığı/bekleme politikası altında uç başına 429, 403, başarılı detay/saat, yeni kart/saat ve p95 gecikme önce/sonra karşılaştırılır. |
| 3 | Tekrarlanan erişim reddine ilan bazlı kalıcı sayaç, ilk/son deneme ve ek bekleme ekle | Genel kaynak beklemesi kalkmadan istek yok; aynı sorunlu iş en erken hazır iş olarak sürekli geri gelmez; 429 ile eksik alan/parsing hatası ayrılır. |
| 4 | Rutin keşfe sınırlı ve garanti edilen sayfa bütçesi ver; kendi detaylarından sonra 60 saniyeyi yeniden başlatma | Manuel öncelik ve kaynak politikası korunarak yeni şehir/meslek keşfi ilerler; detaylar da sınırsız ertelenmez. |
| 5 | Backlog alarmı ve `done`/`detail_pending` revizyon tutarsızlığını düzelt | Gerçek ilerleme varken eski minimumdan tıkanma mesajı çıkmaz; sahipsiz bekleyen detay kalmaz. |
| 6 | Ölçüm sonrası aralık toparlanmasını ve yerel fallback'i gözden geçir | Kaynak `Retry-After` değerlerine uyulur; blokaj ve hız yalnız UI sayaçlarıyla değerlendirilmez. |

0 ve 1 aynı küçük değişiklikte yapılabilir. 3–5'in bağımsız, ağ davranışını
değiştirmeyen kısımları ayrı hazırlanabilir; üretim karşılaştırmasında hangi
değişikliğin hangi etkiyi yaptığı kaybolmamalı.

### Kontrollü gözlem tasarımı

- Eski-yeni toplayıcı aynı IP'de eşzamanlı çalıştırılmaz; mevcut işlere ilave yük
  oluşturan canlı benchmark yapılmaz. Doğal kuyruk trafiği değerlendirilir.
- İlk değişiklikte endpoint, kaynak aralığı, cooldown, başlıklar, görev kapsamı ve
  sınıflandırıcı birlikte değiştirilmez. Kalıcı `blocked_until` ve `interval_floor`
  sıfırlanmaz. Oturumu her 429 sonrası yenileme/çerez temizleme yapılmaz.
- En az 24 saat ve mümkünse en az 200 detay isteği gözlenir. Hacim oluşmazsa
  “kanıt yetersiz” denir; süre dolması tek başına başarı sayılmaz.
- Eski %4,75 oranı bir referans; bütün koşullar eşit olmadığından garanti veya
  evrensel limit değildir. Hedef, karşılaştırılabilir trafik dilimlerinde kalıcı
  düşüş ve daha fazla başarılı detay/saat. 403/999 artarken 429 düşmesi başarı değil.
- Session kimliği ve sayaçları, gerçekten yeniden kullanım olduğunu göstermeli.
  Rutin beklemesi azalırken detayların p95 yaşı büyüyorsa plan yeniden dengelenir.
- Yeterli düşüş yoksa bir sonraki adım uç nokta/ilan/saat/IP geçmişi ayrımını
  incelemektir; oturum değişikliğinin bütün 429'ları çözdüğü varsayılmaz.

## Kayıtlar ve yeniden üretme

Yerel ayrıntı: `.local/performance-audit-20261020/429-comparison.json`.
Hesaplayan yardımcı: `.qa/compare_429_versions.py` (salt okunur JSONL analizi).
Git kaynakları: `34bca7d` eski/yeni worker ve oturum ömrü, `37aa6b5` kayıt kapsamı,
`ccb3409` uç noktası geçişi, `9f84b42` 6→10 saniye varsayılan ayarı.

Bu çalışma analiz ve plan güncellemesidir; uygulama ve üretim ayarları değiştirilmedi.
