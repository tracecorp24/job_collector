# Uzun mola: canlı bulgular

Ölçüm: 20 Ekim 2026 16:38 İstanbul / 13:38 UTC. Canlı sürüm `294c81d`.
Salt okunur tanılama: GitHub Actions run `39432157695`.
Ham kanıtlar ana çalışma alanının gitignore altındaki
`.local/pause-audit-20261020/39432157695/` klasöründe.
`refresh_live_diagnosis.py` mevcut tanılama dalını yeniden dispatch eder;
üretim ayarı, kaynak politikası veya uygulama verisi değiştirilmedi.

## Doğrulanan neden

Son üç kaynak isteği aynı liste URL'sine: `seeMoreJobPostings/search`,
Endüstri Mühendisliği / Istanbul, offset 50. Üçü de HTTP 429, sıfır kart.

| İstanbul zamanı | HTTP | Yerel ihlal sayacı | Uygulanan mola |
|---|---|---|---|
| 15:34:58 | 429 | 5 | 960 sn / 16 dk |
| 15:51:02 | 429 | 6 | 1920 sn / 32 dk |
| 16:23:04 | 429 | 7 | 3840 sn / 64 dk |

Son iki yanıtın açık telemetrisi: `retry_after=null`,
`cooldown_origin=local_fallback`, `semantic_outcome=access_denied`.
Dolayısıyla 64 dakika kaynak tarafından bildirilen bir süre değildir;
`Coordinator.pause()` içindeki yerel artan bekleme hesabıdır.
Bu mekanizma önceki sürümden korunmuştur; arayüz yayını molayı sıfırlamaz.
Kaynak 429'unun hangi karşı taraf kuralından kaynaklandığı bu kayıtlarla kesinleşmez.

16:38 ölçümünde kalan 2901 sn, blokaj bitişi 17:27:04 İstanbul.
Süre bitiminde başarı garantisi yok: yeni 429 yeni bekleme doğurabilir.
Normal istek aralığı ayrıca 120–138 sn; blokajdan farklı bir kısıttır.
Sayaç, son ihlalden bir saat geçmeden alınan başarılarla sıfırlanmaz;
bu yüzden arada başarılı detaylar bulunması 7 sayacını çürütmez.

## Önce kart, sonra detay beklentisi

`DEFER_DETAILS` varsayılan açık. Kartın başlık/şirket/konumu açıklamadan önce
kaydedilir. Bu, tüm rutin keşiflerin detaylardan önce bitirildiği anlamına gelmez:
çalışan rutin hazır repair işi görünce öncelik bırakabilir. Eski akışta
14:38:57 İstanbul `priority_yield: routine -> repair` olayı bunu gösterir.
Bu olay yeni adalet düzeltmesinden önceye aittir; yeni düzeltmenin başarısızlığı
diye kullanılamaz. Kod incelemesinde aktif rutin dalındaki koşulsuz repair
preemption ile yeni rutin dönüş bütçesinin ilişkisi ayrıca incelenmelidir;
yeni sürümde bunun canlı tekrarı henüz görülmedi.

Liste ve detay uçları aynı kaynak gate'ini paylaşır; detay 429'u keşfi de bekletir.
Fakat güncel son üç 429 doğrudan liste ucundadır. Şu an yalnız detay
işlerini ertelemek bu liste reddini ortadan kaldırdığını kanıtlamaz.

## Hataların ayrımı

- Supervisor canlı, `last_error` boş; gözlem anında uygulama çökmesi yok.
- Detay kuyruğu `done=264`, pending/retry yok. Eski `detail_backlog`
  alarmı 16:32 İstanbul'da resolved olmuş.
- Aktif sorun `source_blocked_long`: gerçek kaynak beklemesi.
- `/api/jobs/679/fetch-detail` hatası 17 Ekim eski sürüm kaydı;
  yeni sürümde tekrarlandığına ilişkin bu indirmede kanıt yok.
- `Client disconnected while serving /events` bilgi seviyesinde bağlantı
  kapanmasıdır; kaynak 429'unun nedeni olarak gösterilemez.
- Log yazımı aktif, dropped/spooled=0. Yeni isteklerde HTTP/yerel mola ayrımı
  yeterli; UI bu ayrımı ve bitiş zamanını daha açık göstermelidir.

## Sonraki uygulama sırası

1. Kaynak molasını atlamadan, yeni kodda rutin dönüşünün gerçekten en az bir
   liste isteğine ulaşmasını incele; çalışan rutin tekrar repair tarafından
   hemen durdurulabiliyorsa sınırlı ve kalıcı keşif bütçesiyle düzelt.
2. Kart kaydı ile açıklama eksikliğini kullanıcıya ayrı durumlar olarak göster;
   açıklaması beklenen kart yanlış veri veya başarısız ilan sayılmamalı.
3. UI'da kaynak HTTP sonucu, Retry-After var/yok, yerel bekleme kuralı,
   kesin yeniden deneme zamanı, normal istek aralığı ayrı gösterilsin.
4. Kaynak politikasını sıfırlama/gevşetme. Sadece isim toplamak da liste
   reddini aşmaz. Doğal başarılı liste isteği geldikten sonra kart/saat ve
   tamamlanan detay/saat ayrı ölçülsün; 429 iyileşti iddiası henüz kurulamaz.

İlk incelemede uygulama kodu veya üretim ayarı değiştirilmedi.

## Kullanıcı onayıyla uygulanan düzeltme

- `runs.start`: rutin başlangıcında son olay kimliği kalıcı run options'a yazılır;
  `routine_page_turn_started` olayı bir sayfalık keşif sırasını açıklar.
- `scheduling.routine_page_pending`: aynı koşunun bu başlangıçtan sonraki
  tamamlanmış sayfasını bekler. Yarıda kesilmiş veya başka koşuya ait sayfa sayılmaz.
- `service.tick`: otomatik repair ilk sayfadan önce rutini kesemez; manuel öncelik
  ve kaynak beklemesi korunur. Zamanı gelen şehir/alarm taraması detay kuyruğu
  doluyken de sıraya girer; mevcut adalet bütçesi artık bu adayı görebilir.
- Mola süre hesabı değiştirilmedi. Süre kanıtı mevcut `settings` tablosunda
  deadline'a bağlı saklanır; kaynağın bildirdiği saniye ile yerel süre ayrılır.
  Eski kayıtların kökeni tahmin edilmez. Veri silme/şema göçü yok.
- Arayüz kesin yeniden deneme zamanını, olası yeni beklemeyi, HTTP durumunu ve
  süre kökenini gösterir. Geçmiş log ekranı eski hatanın güncel tekrar olmadığını
  açıklar; kart açıklamasının ertelenmesi ayrıca anlaşılır metinle gösterilir.

Yeni regresyonlar: ilk tamamlanmış sayfa, yarım sayfa, başka run'ın sayfası,
manuel preemption, yeni başlangıçta marker yenileme, backlog varken due şehir,
mola kanıtının kalıcılığı, Retry-After ve yerel escalation ayrımı.
Tarayıcıda yerel 64 dk / kaynak süresi / karma / eski kayıt durumları kontrol edilir.
İlk paralel paket koşusunda iki eski işçi testi 10/15 sn zaman aşımı aldı;
bu ilk koşu temiz paket başarısı olarak gösterilmemeli. Yeni dört kuyruk testi
ve üç kaynak bekleme testi ayrı tekrarında geçti. Son paket/yayın sonuçları
GitHub Actions ve yerel `.qa/ui-collection-test_*.log` kanıtından okunmalı.
Doğal kaynak 429 oranında iyileşme henüz doğrulanmış değildir.

Son yerel doğrulama: scheduling **26/26** (254,194 sn), transport **17/17**
(423,665 sn); son kaynak/yerel süre ayrımı testi **2/2** (119,389 sn).
Tam tarayıcı kontrolü başarılı, JavaScript hatası yok (14:07:46 UTC).
İlk zaman aşımı alan iki test de temiz paket tekrarları içinde geçti.
CI tüm Python paketini yeniden çalıştırmadan üretim deploy'u yapmaz.
