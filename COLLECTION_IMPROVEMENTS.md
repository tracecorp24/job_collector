# Toplama verimliliği ve güvenli devreye alma

Kaynak beklemeleri, tek toplayıcı, güncel detay önbelleği ayarı, zorunlu yenileme,
ilan analizi, dışa aktarım ve arama ilişkileri korunur. Birleştirilen GitHub sürümünün
72 saatlik varsayılan önbelleği korunur; arayüz gerçek yapılandırmayı gösterir. Resmi kaynak API'si gerekmez.

## Davranış

- Devam kaydı v2, sayfanın kartlarını ve işlenmiş kimlikleri saklar. Kaynak beklemesi
  bittikten sonra kalan detaydan devam edilir. Sayfa tamamen işlenince sonraki sayfa
  kaydedilir. Eski devam kayıtları mevcut liste isteği yoluyla çalışır.
  Güncel GitHub sürümündeki değişken sayfa boyutu ve `offset` alanı korunur. Varsayılan
  önce-kart/sonra-detay akışı ve hafif detay uç noktası devam eder; saklanan sayfa hem
  ertelenen detay hem eşzamanlı detay modunda kullanılabilir.
- İlan, arama ilişkisi ve ilerleme aynı veritabanı işleminde kaydedilir. Ani kapanma
  sonrası kaydedilmiş ilan tekrar hedef sayısına eklenmez. Kalan kartlar sessizce atılmaz.
- Arayüz gerçek ortak istek aralığını, benzersiz ilanları ve kaynaktan gelen kartları
  gösterir. Saklanan kartların yeniden işlenmesi yeni liste isteği olarak sayılmaz.
- Önbellek nedenleri: ilk istek, süre dolması, kart değişmesi, zorunlu yenileme.
  Önbellek süresi uzatılmaz. Tam analiz modu mevcut detay önbelleğini kullanabilir.
- Kuyruk düzenleyici aynı unvan, konum ve hedefin yanlışlıkla tekrar eklenmesini önler.
  Farklı hedefli veya farklı aramalar korunur. Duraklayan işi aynı çalışma üzerinden
  devam ettirmek geçmişi ve ilerlemeyi korur.
- Düzenli taramalar yeni ilan takibi içindir; kapsamlı geçmiş taramasının yerine geçmez.
- Bakım / analiz bölümündeki isteğe bağlı “Kaynak beklerken” seçeneği kayıtlı ilanları
  en fazla beş başarılı kayıttan oluşan gruplarla işler. Kaynak beklemesinin bitimine
  yaklaşınca yeni kayıt başlatılmaz. Başlamış tek analiz tamamlanır; bekleme dolduğunda
  yeni grup başlatılmaz. Kullanıcı duraklatması ve durdurması otomatik çalışmayı keser.
  Açıklaması henüz gelmemiş ilanlara yapay zekâ isteği gönderilmez. Analiz sağlayıcısının
  uzun kota beklemesi bu modda kapalıdır; mevcut normal analiz davranışı korunur.

## Ölçüm, yedek ve devreye alma

Canlı veriler repoya alınmaz. Dağıtımdan önce sunucuda:

```sh
python scripts/collection_baseline.py --db /var/lib/linko/jobs.db --backup-dir /var/lib/linko/backups --output /var/lib/linko/collection-before.json
```

Bu komut kaynak DB'yi salt okunur açar; SQLite online backup oluşturur ve bütünlüğünü
kontrol eder. Aynı ölçüm dağıtım sonrasında farklı bir çıktı dosyasına alınabilir.
Deploy betiğinin mevcut dağıtım öncesi yedeği de korunur.

Önce küçük, tek görevli bir taramada mevcut bekleme politikası altında devam davranışı
doğrulanır. Ardından normal kuyruklar açılır. Temel karşılaştırma: aynı kapsam için
benzersiz tamamlanan ilan başına istek, liste isteği sayısı, gerçek istek sırası beklemesi,
kaynak beklemesi ve HTTP/analiz süreleri. Kart görünümü benzersiz ilan sayısı değildir.

`python -m unittest discover -s tests` ve arayüz smoke testi uygulanır. Sahte yanıtlarla
429, yinelenen 429, yeniden başlatma, eski checkpoint, hedef değişimi, içerik değişimi,
zorunlu yenileme, kullanıcı durdurması ve analiz sırasında kaynak beklemesinin dolması
kontrol edilir. Canlı kaynağa yük testi yapılmaz.

Sorun halinde önceki uygulama sürümüne dönülür. V2 kaydı eski `page`, `seen`, `collected`
alanlarını koruduğundan eski sürüm aynı sayfayı tekrar isteyerek devam edebilir. Veri
silen şema değişikliği yoktur; uygulamayı geri almak için canlı DB'yi eski yedeğe
döndürmek gerekmez. Böylece dağıtım sonrası toplanan ilanlar da korunur.
