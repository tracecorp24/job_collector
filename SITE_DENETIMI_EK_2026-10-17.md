**Linko ayrıntılı denetim — ilk rapora ek bulgular, 17 Ekim 2026**

İlk rapordaki konum, deneyim, kıdem, SSE kapasitesi ve temel listeleme hataları tekrar listelenmedi. Bu turda kalıcı iş durumları, Groq profil puanlaması, ilan yaşam döngüsü, yedekten dönüş, API senkronizasyonu, izleme ve arayüzde hata sonrası davranış incelendi.

13 hata/risk senaryosu geçici veritabanlarında yeniden üretildi; ayrıca yetki sınırları için kontroller yapıldı. Mevcut test takımındaki **91 test geçti**. Bu sayı yeni bulguların düzeltilmiş olduğu anlamına gelmez: denetim betiğindeki kontroller, hatalı davranışın gerçekleştiğini doğruluyor.

İnceleme sırasında başka çalışmalar da dosyaları değiştiriyordu. Kaynak incelemesindeki son görülen commit `9ddaf26`; canlı arayüz ve kaydedilmemiş yerel arayüz değişiklikleri birebir aynı sürüm olarak kabul edilmedi. Canlıda gözlem anında 420 ilan vardı. Özgün yerel DB salt okunur açıldı; veri değiştiren deneyler ayrı geçici DB'lerde, HTTP ve model yanıtları taklit edilerek yapıldı.

**1. Puan kaydedilmeden ilan tamamlanmış sayılıyor — yüksek öncelik**

`fit.run_fit_backfill()` puanı önce oturumdaki nesneye yazar, `processing_result: saved` olayını gönderir, bütün partiyi daha sonra commit eder. `runs.maintenance_worker()` ise bu olay gelir gelmez ilan kimliğini kendi ayrı DB işleminde `processed_ids` listesine kalıcı kaydeder.

Deneyde puan işleminin commit aşaması bilinçli olarak başarısız yapıldı. Puan DB'de boş kaldı, fakat devam noktasında `processed_ids=[1]` vardı. Kullanıcı devam ettiğinde ilan atlandı, modele yeniden sorulmadı ve çalışma `finished` oldu; puan hâlâ boştu.

Bu bir hata mesajı eksikliğinden daha ciddi: devam mekanizması kalıcı verinin önüne geçiyor. Puan ile tamamlanma işareti aynı işlemde yazılmalı veya başarı olayı commit'ten sonra üretilmeli. Parti commit'i başarısız olduğunda tüm parti yeniden işlenebilir kalmalı.

Dayanak: [fit.py](jobapp/fit.py) `run_fit_backfill`, [runs.py](jobapp/runs.py) `maintenance_worker`.

**2. İlan değişse de eski uygunluk puanı güncel sayılıyor — yüksek öncelik**

Puan yalnızca profil metninin hash'ine bağlı. İlanın açıklama, unvan ve şartlarının sürümü puana bağlanmıyor. `pipeline.process_raw()` değişen içerikte embedding'i geçersiz kılıyor; `fit_score`, `fit_reason` ve `fit_profile` için aynı davranış yok.

Deneyde Python ilanına verilmiş 93 puan, ilan “Senior C++ Engineer / 10 yıl deneyim” olarak güncellendikten sonra da kaldı. Profil hash'i aynı olduğu için yeniden puanlama hedef sayısı 0 döndü. Kullanıcı eski gerekçeyi ve puanı güncel ilan için görür.

Puanın geçerlilik anahtarı profil sürümü, ilan içerik sürümü ve değerlendirme model/prompt sürümünü kapsamalı. İlanın ilgili alanları değiştiğinde puan bekleyen duruma alınmalı.

Dayanak: [fit.py](jobapp/fit.py) `profile_hash`, [pipeline.py](jobapp/pipeline.py) `process_raw`, [app.js](jobapp/static/js/app.js) `fitCurrent`.

**3. Boş tekrarlı tur bütün zamanlayıcıyı bekletebiliyor — yüksek öncelik**

`service.tick()` bitmiş tekrarlı çalışmadan yalnızca `finished` görevleri kopyalıyor. Önceki turdaki tüm görevler kullanıcı tarafından durdurulmuşsa yeni tur sıfır görevle oluşabiliyor. Sonraki tick, bu en eski kuyruğu başlatırken “Devam ettirilecek sorgu kalmadı” hatası alıyor; aynı kayıt sonraki tick'te yeniden seçiliyor.

Deneyde sıfır görevli tur oluşturuldu; iki ardışık tick aynı hatayı verdi. Daha sonra eklenen geçerli çalışma `queued` kaldı. Gerçek supervisor istisnayı yakalayıp tekrar dener, fakat bozuk adayın durumunu değiştirmediği için tıkanma sürer.

Boş tur oluşturulmamalı. Başlatılamayan bir aday neden bilgisiyle karantinaya alınmalı/sonlandırılmalı ve diğer geçerli işler değerlendirilmelidir. Bu düzeltme tek collector varsayımını koruyabilir.

Dayanak: [service.py](jobapp/service.py) `tick`, [runs.py](jobapp/runs.py) `start`.

**4. API kayıt saklama politikası sessiz senkronizasyon kaybına yol açabiliyor — yüksek öncelik**

Yeni bakım işlemi eski `job_changes` satırlarını siliyor; değişiklik API'si istemcinin cursor'unun artık saklama aralığının dışında olduğunu bildirmiyor. Bakım açıklamasındaki `after=0` ile baştan senkronize olma önerisi de tek başına yeterli değil: eski olayları silinmiş, hâlâ aktif ilanlar bu akışta bulunmayabilir.

Deneyde 1 aktif ilanın tek eski değişiklik olayı budandı. `/api/v1/jobs` hâlâ 1 ilan döndürürken `/api/v1/jobs/changes?after=0` boş döndü. Eski cursor ile istek de HTTP 200, boş liste ve `has_more=false` aldı; yeniden başlangıç gerektiğine dair işaret yoktu.

API bir saklama sınırı/high-watermark tutmalı; geçersiz cursor için açık `reset_required` veya uygun hata vermeli. Tam yeniden eşitleme, aktif ilan snapshot'ı ve bu snapshot ile uyumlu değişiklik cursor'u üzerinden tanımlanmalı. Silinen kayıtların istemcide kalmaması için tam eşitlemenin eski yerel kayıtları da uzlaştırması gerekir.

Dayanak: [maintenance.py](jobapp/maintenance.py) `run`, [service_api.py](jobapp/service_api.py) `changes`, `jobs`.

**5. SQLite ve JSON işlemleri birlikte atomik değil — yüksek öncelik**

İlanı çöp kutusuna taşırken JSON kopyaları güncelleniyor, DB daha sonra commit ediliyor. İkinci dosyada okuma/yazma hatası olduğunda ilk dosya geri alınmıyor. Kalıcı geçmiş silmede de dosya silme işlemi DB commit'inden önce gerçekleşiyor; bu ikinci yol kodda görülüyor, ayrıca canlıda denenmedi.

Yeniden üretmede aynı ilanın iki JSON kopyasından ikincisi bozuk yapıldı. Silme isteği HTTP 400 döndü. DB'deki ilan aktif kaldı; ilk JSON kopyası silinmiş olarak işaretlenmişti. İki veri kanalı artık farklı görünürlük bilgisi taşıyor.

DB değişikliğiyle birlikte bir dışa aktarım işi/outbox kaydı oluşturmak, dosya yazımını tekrar denenebilir ve idempotent yapmak daha sağlam çözüm. Hataları yalnızca istemciye döndürmek mevcut dosya değişikliklerini geri almaz.

Dayanak: [enhanced.py](jobapp/enhanced.py) `trash_jobs`, `sync_exports`, `run_action`.

**6. Yedek veriyi kurtarıyor, bütün çalışma durumunu kurtarmıyor — yüksek öncelik**

Sunucu dışı yedek betiği yalnızca `jobs.db` kopyasını sıkıştırıyor. DB'de arama klasörünün adı ve devam noktası var; devam kodu ayrıca `accountless_searches/<klasör>/search.json` dosyasını zorunlu tutuyor.

DB-only geri yükleme benzetiminde ilanlar okunabiliyordu, ancak devam çağrısı “Devam edilecek arama havuzu bulunamadı” ile reddedildi. Bu nedenle SQLite `integrity_check=ok` uygulamanın tam geri dönebildiğini kanıtlamaz.

Yedek sözleşmesi DB ile arama çıktıları/metadata'yı birlikte kapsamalı veya eksik klasörler DB'den güvenli biçimde yeniden kurulabilmeli. Ortam ayarları ve erişim anahtarlarının ayrı kurtarma yöntemi de tanımlanmalı. Boş bir ortamda ilan okuma, arama geçmişi, yarım işi devam ettirme ve API tüketicisini eşitleme adımlarını içeren geri dönüş tatbikatı gerekli.

Dayanak: [linko-backup.sh](deploy/linko-backup.sh), [search_export.py](jobapp/search_export.py) `resume`.

**7. Eski DB'nin değişiklik tetikleyicileri yeni alanları taşımıyor — orta/yüksek öncelik**

Şemaya `fit_score`, `fit_reason`, `fit_profile` eklenmiş, ancak günlük tetikleyicileri `CREATE TRIGGER IF NOT EXISTS` ile kuruluyor. Mevcut tetikleyicinin payload'ı model genişlediğinde yenilenmiyor.

Özgün yerel DB salt okunur kontrol edildi: üç `jobs_journal_*` tetikleyicisinde de bu üç alan eksik. Geçici deneyde eski payload'lı tetikleyici bırakılıp `init_db()` çalıştırıldı; puan 88'e güncellenmesine rağmen değişiklik payload'ında puan yoktu. Yeni kurulum ile yükseltilmiş kurulum aynı API sözleşmesini sunmayabilir.

Tetikleyici şeması sürümlenmeli ve gerekli yükseltmede işlem içinde yeniden oluşturulmalı. API payload'ı için açık sürüm ve eski DB yükseltme testi gerekli.

Dayanak: [service_api.py](jobapp/service_api.py) `init_journal`, [db.py](jobapp/db.py) `init_db`.

**8. Kaynakta kapanan ilan sitede aktif kalıyor — orta öncelik**

Bir ilan daha önce kaydedilip detay yenilemede HTTP 404 alınırsa hata önbelleğe yazılıyor; mevcut `Job` kaydı için kaynak durumu güncellenmiyor. Deneyde kaynak 404 verdikten sonra ilan aktif listede kaldı.

Kullanıcının çöp kutusuyla kaynağın ilanı kapatması ayrı kavramlar olmalı. `source_status`, son doğrulama zamanı, detayın alındığı zaman ve kapanma nedeni gibi alanlar gerekli. 404/410 ile geçici 429/ağ hatası birbirine dönüştürülmemeli; her başarısızlık ilanı kapatmak için yeterli değildir.

Dayanak: [accountless.py](jobapp/scraper/accountless.py), [transport.py](jobapp/transport.py) `Details`, [models.py](jobapp/models.py) `Job`.

**9. “Şimdi tara”, duraklatılmış düzenli taramayı kalıcı olarak açıyor — orta öncelik**

Duraklatılmış watch üzerinde `run-now` çağrısı `enabled=True` yapıyor. Arayüzdeki işlem adı tek seferlik bir tur izlenimi veriyor; işlem sonrasında düzenli turlar da yeniden açılıyor. Ayrıca watch silinince önceden oluşturulmuş `service_managed` kuyruk kaydı silinmiyor veya iptal edilmiyor.

Deneyde kapalı watch “Şimdi tara” sonrasında açık kaldı. Ardından watch silindi; daha önce sıraya alınmış tur zamanlayıcı tarafından hâlâ başlatılmak istendi.

Tek seferlik tur ile düzenli taramayı etkinleştirme ayrı eylemler olmalı. Silme/duraklatmanın mevcut turu ve henüz başlamamış turu nasıl etkilediği açıkça tanımlanmalı. Süren bir turu korumak tercih ediliyorsa kullanıcıya kalan turun devam edeceği söylenmeli.

Dayanak: [watches.py](jobapp/watches.py) `run_watch_now`, `delete_watch`, [app.js](jobapp/static/js/app.js) `watchAction`.

**10. İki sekme kuyruk düzenlemesini sessizce geri alabiliyor — orta öncelik**

Kuyruk kayıtlarında revision/ETag karşılaştırması yok. Aynı kuyruk iki sekmede açıkken A'nın güncel değişikliği, B'nin eski otomatik kaydıyla üzerine yazılabiliyor. Deneyde A'nın unvan değişikliği HTTP 200 ile kaydedildi; eski içerikli ikinci istek de HTTP 200 aldı ve unvan eski haline döndü.

Tarayıcıdaki kayıt zinciri yalnızca o sekmedeki istekleri sıralar. Sunucuda beklenen revision ile atomik güncelleme ve uyuşmazlıkta 409 yanıtı gerekli; arayüz diğer sekmedeki değişikliği göstermeli.

Dayanak: [enhanced.py](jobapp/enhanced.py) `save_queue`, [app.js](jobapp/static/js/app.js) taslak kayıt akışı.

**11. Sağlık kontrolü iş ilerlemediği halde sağlıklı diyebiliyor — orta öncelik**

`/healthz` DB erişimini, supervisor thread'ini ve heartbeat'ini kontrol ediyor. `service.tick()` aktif iş varken heartbeat'i yenileyip çıkıyor. İşçi thread'in ölmüş/takılmış olması veya uzun süredir ilerleme üretmemesi ayrıca denetlenmiyor.

Deneyde `state.running=True`, gerçek worker thread'i yok, supervisor canlı ve heartbeat güncel iken HTTP 200 / `status=ok` alındı. Mevcut dış izleyici sadece bu sağlık sonucunu izlediği için işlerin durmuş olmasını kaçırabilir.

HTTP liveness ile collector readiness/progress ayrılmalı. Aktif işçi varlığı, son kalıcı ilerleme zamanı, en eski bekleyen görev, kaynak bekleme son tarihi ve tekrar hata sayısı izlenmeli. Beklenen kaynak beklemesi alarm üretirken gerçek takılmayı gizlememeli.

Dayanak: [service_api.py](jobapp/service_api.py) `health`, [service.py](jobapp/service.py) `tick`, [uptime.yml](.github/workflows/uptime.yml).

**12. Kısmi puanlama tam başarı gibi tamamlanıyor — orta öncelik**

Model bir partideki ilanların yalnızca bir kısmını döndürürse `scores` boş olmadığı için toplu hata sayacı sıfırlanıyor. Eksik ilanlar `skipped` olarak sayılıyor, fakat toplam iş `completed/finished` olabiliyor. Deneyde 2 ilandan yalnızca 1'i puanlandı; biri boş kaldığı halde çalışma tamamlandı.

Eksik yanıt veren ilanlar için ayrı yeniden deneme listesi ve “kısmen tamamlandı” durumu gerekli. Geçerli çıktı sayısı/istenen çıktı sayısı doğrulanmalı. Model yanıtının JSON olması yeterli değil: alakasız bir JSON nesnesi `apply_fields()` tarafından `classified_by=groq` diye başarı sayılabiliyor; sonraki yeniden analiz bu kaydı işlenmiş sanabilir.

Dayanak: [fit.py](jobapp/fit.py) `score_batch`, `run_fit_backfill`, [classify/_shared.py](jobapp/classify/_shared.py) `apply_fields`.

**13. AI girdisi ve durdurma sınırları ürünün anlattığından dar — orta öncelik**

Profilin ilk 3.000 karakteri, özet bulunmayan ilanın açıklamasının ilk 600 karakteri değerlendirmeye gidiyor. Uzun şirket tanıtımından sonra gelen zorunlu şartlar modele hiç ulaşmayabilir. Sentetik deneyde açıklamanın sonraki kısmındaki zorunlu C++ şartı `_brief()` çıktısına girmedi. Profil hash'i ise tüm profil üzerinden üretildiği için sonradan eklenmiş, modele gitmeyen bir bilgi bile puanı “yeni profil için” gösterebilir.

Metni baştan kesmek yerine nitelikler, deneyim, zorunlu beceri, çalışma hakkı ve çalışma biçimi gibi alanları bütçeye göre derlemek; kullanıcıya değerlendirmenin kapsadığı metni göstermek gerekir. Model/prompt sürümü, puanlama zamanı ve dayanak alanları da saklanmalı.

Groq `max_wait=8` toplam süre sınırı değil. İki 429 yeniden denemesinde taklit beklemeler 14 saniyeye ulaştı; HTTP timeout ayrıca her çağrıda 60 saniye. Bekleme `sleep` üzerinden ve iptal callback'i olmadan yapılıyor. Durdurma isteği mevcut model çağrısını/beklemeyi anında kesmeyebilir. Toplam işlem deadline'ı ve iptal edilebilir kota beklemesi gerekli; harici gerçek API üzerinde uzun bekleme testi yapılmadı.

Dayanak: [fit.py](jobapp/fit.py) `MAX_PROFILE`, `_brief`, [groq_client.py](jobapp/groq_client.py) `chat`, `_wait_for_quota`.

**Canlı arayüzde ek gözlemler**

- Para birimi/dönem seçmeden “Maaş: yüksekten düşüğe” seçimi hem ilan isteğini hem filtre sayıları isteğini hataya düşürüyor. Gerekli seçimler önceden istenmiyor; mobilde ilgili alanlar kapalı filtre panelinde. “Tekrar dene” aynı eksik parametrelerle yeniden hata veriyor. Bu bir sunucu çökmesi değil, düzeltilmesi gereken kullanıcı akışı.
- Normal sıralamaya dönüp 420 ilan tekrar yüklendiğinde üst durum metni “Filtre sayıları güncellenemedi” olarak kaldı. Canlı bağlantı durumu ile filtre hatası aynı metin alanını kullanıyor; başarı sonrasında eski hata temizlenmiyor.
- 390×844 görünümünde yatay sayfa taşması gözlenmedi. Canlıdaki üst menü birçok satır kaplıyor; yerelde sürmekte olan alt menü değişikliklerinin canlıda çalıştığı varsayılmadı.
- Arama anahtar kelimesi kesin rol/kıdem koşulu değil. Yerel “elektrik staj” aramasında teknisyen, saha servis ve teknik destek unvanları da var. Bu LinkedIn'in geniş eşleştirmesiyle uyumlu olabilir; uygulama uygunluk kontrolü yapmadığı için “aramada döndü” ile “tam olarak kriterlere uyuyor” ayrımını kullanıcıya göstermeli.

**Eksik ürün sözleşmeleri ve güvenlik sınırları**

Başarısız/kısmi iş, güncelliği şüpheli ilan, kapalı kaynak ilanı, kaynak konumu uyuşmazlığı ve eski AI puanı için ayrı durumlar eksik. Bunları tek “geçerli/aktif/tamamlandı” işaretinde toplamak, teknik hata olmadan da yanlış karar yaratıyor. Veri modelindeki durumların arayüzde ve API'de aynı anlamı taşıması öncelikli.

Profil `settings` tablosunda tek ortak kayıt; kullanıcı/sahip alanı yok. Birden fazla kişiye açılacaksa kişiye özel profil, puan, favori ve erişim modeli ayrıca tasarlanmalı. Mevcut tek kullanıcılı kullanım için bu başlı başına yetki açığı diye sınıflandırılmadı.

Yetki deneylerinde salt okuma anahtarı ilanları okuyabildi (200), toplama oluşturamadı (401), dış IP'den yönetim profil API'sini okuyamadı (401); farklı Origin'den yazma isteği reddedildi (403). Loopback isteği keyfi Host ile anahtarsız kabul ediliyor; bu uygulamanın yerel güven sınırının bir parçası. Host allowlist/proxy güven sözleşmesi yokluğu DNS rebinding gibi yerel saldırı senaryoları için sertleştirme alanı; canlı sitede sömürülmüş veya genel erişime açık bir güvenlik açığı kanıtlanmadı. Gerçek VPS Caddy/firewall yapılandırması bu denetimde okunmadı.

Dağıtımın release/şema/payload sürümünü sağlık veya servis yanıtında açıkça sunmaması, canlı ile yereldeki davranışı karşılaştırmayı zorlaştırıyor. Yükseltilmiş DB için API sözleşme testi, yedekten dönüş tatbikatı, kısmi model yanıtı, commit hatası, eski cursor ve iki sekme testi kalıcı test takımına eklenmeli.

**Önerilen uygulama sırası**

| Sıra | Çalışma | Tamamlanma ölçütü |
| --- | --- | --- |
| 1 | Puan/ilerleme işlemi, bozuk zamanlayıcı adayı, dosya/DB tutarlılığı | Hata enjeksiyonundan sonra kayıpsız devam; bozuk bir iş sonraki işi engellemiyor |
| 2 | Cursor saklama sözleşmesi, tetikleyici yükseltmesi, yedekten dönüş | Eski DB ile yeni DB aynı payload; eski istemci açık yeniden eşitleme alıyor; boş ortamda yarım iş devam ediyor |
| 3 | İlan içerik sürümü, AI puanı geçerliliği, kapalı/kısmi durumlar | İlan değişince puan eskimiş; kaynak 404'ü ayrı; eksik model yanıtı tam başarı değil |
| 4 | Watch kontrol anlamları ve kuyruk revision'ı | Tek seferlik tur otomatik taramayı açmıyor; silinen watch'ın bekleyen turu tanımlı; eski sekme güncel düzenlemeyi ezmiyor |
| 5 | İlerleme izleme ve arayüz hata toparlama | Canlı HTTP ile durmuş collector ayrılıyor; düzelen filtre hatası ekrandan kalkıyor |

Yeniden üretme: [denetim betiği](.qa/extended_audit_20261017.py), [JSON sonuçlar](.qa/extended_audit_20261017.json), [91 testin kaydı](.qa/extended_unit_tests_20261017.log). İlk denetim: [konum ve temel veri akışı raporu](SITE_DENETIMI_2026-10-17.md).
