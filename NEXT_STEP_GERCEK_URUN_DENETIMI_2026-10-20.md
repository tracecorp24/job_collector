# NextStep — örnek veri ve gerçek ürüne geçiş denetimi

Tarih: **20 Ekim 2026**. Amaç: kullanıcı kayıt olduğunda kendi bilgileriyle, güncel ve başvurulabilir gerçek işlere ulaşması.

## 1. Sonuç ve incelemenin sınırı

Projede gerçek hesap, oturum, profil, CV, başvuru takibi ve AI servis kodu var. Buna rağmen örnek veri temizliği tek başına gerçek kullanıma geçiş için yeterli değil. **Hesap güvenliği, kullanıcı verisinin hesaplar arasında ayrılması, ilanların doğruluk iddiası ve başvuru durumunun dürüst kaydedilmesi öncelikli açıklar.**

Bu denetim kaynak kodu ve yerel veri dosyaları üzerinde yapıldı. Üretim veritabanına girilmedi; gerçek hesap oluşturulmadı, gerçek e-posta/AI isteği gönderilmedi ve canlı kayıt silinmedi. Üretimde kaç sahte kullanıcı olduğu veya yeni ilan bağlantısının gerçekten çalıştığı bu incelemeyle kanıtlanmış değildir. Şifre dosyalarının içeriği okunmadı.

### Eşzamanlı değişiklikler ve esas alınan kopya

İnceleme sırasında başka bir işlem aynı `next_step` deposunda değişiklik ve commit yaptı. Bu nedenle ilk okunan mimari ile son dosyalar aynı değil:

| Durum | Kanıt / zaman |
|---|---|
| Başlangıçtaki depo | `a23df35`; eski dosya havuzu + DB + Remotive birleşimi |
| 11 eski örnek ilanın temizlenmesi | İnceleme sırasında oluşan `9e2b6f4` commit'i |
| Yeni Job AI istemcisi | İnceleme sırasında oluşan `35dd8fd` commit'i |
| Raporun sabit kaynak kopyası | **20 Ekim 2026, 21:46:42 Türkiye saati**; `.qa/nextstep-audit-snapshot-20261020T184642Z/` |
| Kopyanın Git tabanı | `35dd8fd10446f5ecf7dffe7d8cee6effe5871a5e` **ve o anda diskteki commit edilmemiş değişiklikler** |
| Kopyalama sonrasında | Kaynak depoda ilan bağlantısı ve arayüz değişiklikleri sürüyordu; burada bildirilenler sabit kopyanın bulgularıdır |

Kaynakların SHA-256 listesi: [snapshot manifesti](.qa/nextstep_audit_snapshot_manifest.json). Yeni bağlantı değişikliklerinin canlıya çıktığı varsayılmadı. Buradaki temizlikler bu denetim tarafından yapılmadı; raporda gözlenen durumları kaydedildi. Bu çalışma yalnızca rapor ve `.qa` inceleme araçları üretti.

Son ek kontrolde depo `cffddc1` sürümüne ilerlemişti; Job AI entegrasyonu ve misafir düğmesinin kaldırılması gibi değişiklikler vardı. Kritik statik dosya servisi, doğrulanmış ilan rozeti ve başvuru paketi/şema bulguları ilgili dosyalarda hâlâ görülüyordu. Eşzamanlı çalışmanın tamamlandığı veya bu sürümün canlıya çıktığı bu raporla onaylanmıyor. Uygulama öncesinde planın 0. adımıyla güncel taban tekrar sabitlenmelidir.

## 2. İlan ve sahte kullanıcı envanteri

### 2.1. Yerel dosyalardaki durum

| Veri | İlk gözlem / ölçüm | Sabit son kopya | Değerlendirme |
|---|---:|---:|---|
| Eski `ilan_1.json`–`ilan_11.json` örnek seti | 11 dosya başlangıçta vardı; Git tabanından içerikleri alındı | 0 | İnceleme sırasında kaldırıldı; Ek A'da tam liste |
| Eski `sc-*.json` kazıma seti | 163 dosya, 163 kayıt | 0 | İnceleme sırasında kaldırıldı; Ek D'deki CSV bütün kayıtları içerir |
| `ilanlar.js` çevrimdışı paketi | Ara ölçümde 163 kayıt | Dosya yok | Son frontend kopyası bunu yüklemiyor |
| `seed_fake_jobs.py` içindeki `MOCK_JOBS` | 22 tanım | **22 tanım hâlâ var** | Kodda açıkça mockup olarak tanımlı; Ek B |
| `seed_fake_users.py` içindeki `FAKE_DEVELOPERS` | 20 hesap tanımı | **20 tanım hâlâ var** | Üretim DB'sinde bulunup bulunmadıkları bilinmiyor; Ek C |
| Eski demo profil `Emre Demir` | Migrasyon kodunda | Migrasyon kodunda | Yeni varsayılan kullanıcı değil; eski demoyu temizleme amacıyla tutuluyor |

22 tanımlı mockup ilanın hiçbirini ölçülen 163 `sc-*.json` kaydıyla aynı sanmamak gerekir: kimlik/başlık/şirket eşleştirmesinde **0 eşleşme** bulundu. 163 kayıt, gerçek kazımadan gelmiş olabilecek fakat ciddi veri kalitesi sorunları taşıyan ayrı bir setti. İlanların hâlâ açık olduğu doğrulanmadı.

### 2.2. Kaldırılan 163 kaydın kalite özeti

| Kontrol | Sonuç |
|---|---:|
| Başvuru URL'si olmayan | **163 / 163** |
| Şirket adı ilan başlığıyla birebir aynı olan | **144 / 163** |
| Açıklaması 200 karakterden kısa olan | **78 / 163** |
| Kaynak JSON'da `skills` boş olan | **141 / 163** |
| `_tags` ile çok eksenli gereksinim analizi bulunan | **0 / 163** |
| Kaynak JSON'da `_fetchedAt` bulunan | **0 / 163** |
| Maaş verisi bulunan | **0 / 163** |
| `posted` alanı `2026-03-15` olan | **163 / 163** |
| Aynı `id` tekrarları / okunamayan JSON | **0 / 0** |

Bu ölçümler dosyalara aittir. Eski backend, boş `skills` alanlarını bazı kayıtlarda bellekte kural tabanlı çıkarımla doldurabiliyordu; 141 sayısı API çıktısının değil kaynak dosyaların ölçümüdür. `posted` tarihleri gerçek yayın tarihi olarak doğrulanamaz: eski `tools/havuza_aktar.py`, `kayit_zamani` alanını `posted` olarak yazıyor ve `applyUrl` alanını doğrudan `None` yapıyordu.

Örnek: `sc-07743efc9a71.json` içinde `title` ve `company`, `Control Systems Simulation and Calibration Engineer`; açıklama ise özet kart metninden oluşuyordu. Bu kayıt başvurulabilir gerçek bir ilan sunumu için yeterli değildi.

### 2.3. Yeni ilan kaynağında doğrulanan ve doğrulanmayanlar

Sabit kopyada `app/blueprints/jobs.py`, listeleme/eşleştirmeyi `app/job_ai.py` üzerinden Job AI servisine bağlamış durumda. Eski yerel dosya, yerel `jobs` tablosu ve Remotive birleşimi listeleme yolundan çıkarılmış. `js/data/jobs.js`, API başarısızsa boş liste ve `source: 'unavailable'` döndürüyor. **İzole kontrolde HTTP hatasında 0 ilan döndüğü doğrulandı.** Bu, eski örnek veriye dönüş sorununu son kopya için gideriyor.

Bağlantı için `JOBAPP_URL` ve `JOBAPP_API_KEY` gerekiyor. Anahtar boşken `/api/ilanlar`, izole kontrolde **503 / available:false / count:0** döndü. Üretim anahtarı, servis erişimi, gerçek ilan sayısı, URL geçerliliği ve aktarım gecikmesi bu raporda doğrulanmış değildir. Çalışan kod, çalışan üretim bağlantısının kanıtı değildir.

## 3. Öncelik sırası

**P0:** gerçek kullanıcı kabulünden önce kapatılması gereken güvenlik/veri ayrımı sorunları. **P1:** iş bulma akışını veya sonuçların güvenilirliğini bozan sorunlar. **P2:** açıklık, içerik ve ürün kapsamı düzeltmeleri.

| Kimlik | Öncelik | Bulgu | Durum |
|---|---|---|---|
| G01 | P0 | Proje kökü statik dosya olarak servis ediliyor | İzole istekte kaynak dosyalarına 200 |
| G02 | P0 | Doğrulanmamış e-postayla bootstrap admin olunabiliyor | İzole akışta admin API'sine 200 |
| G03 | P0 | Tek localStorage alanı eski hesabın verisini yeni hesaba taşıyabiliyor | Kontrollü JS akışında yeniden üretildi |
| G04 | P0 | Mevcut seed temizleme betikleri gerçek kayıtları da silebilir | Koddan kesin |
| G05 | P0 | Görünen gizlilik metni, ham mülakat cevabının tutulmadığını söylüyor; DB transcript tutuyor | Kod/metin çelişkisi |
| U01 | P1 | Koşulsuz “Doğrulanmış İlan” rozeti | Açık |
| U02 | P1 | URL olmadan bile başvuruldu kaydı | Kontrollü JS akışında yeniden üretildi |
| U03 | P1 | Yeni kullanıcı için profil toplama otomatik değil; boş profille kişiselleştirme gösteriliyor | Açık |
| U04 | P1 | Kanıt yokken %50–%70 eşleşme | Kontrollü hesaplamada yeniden üretildi |
| U05 | P1 | Lokasyon ve çok eksenli koşullar eksik; frontend/mail motorları farklı | Aynı örnekte %30 / %100 |
| U06 | P1 | “Öğren” eylemi doğrudan gerçek profil/CV yeteneğine dönüşüyor | Kontrollü JS akışında yeniden üretildi |
| U07 | P1 | Başvuru paketi isteği CSRF yüzünden 403 | İzole backend isteğinde yeniden üretildi |
| U08 | P1 | Başvuru paketi eski CV şemasını kullanıyor | Açık |
| U09 | P1 | Bazı sunucu kayıt hataları kullanıcıya başarı gibi görünebilir | Koddan doğrulandı |
| U10 | P1 | E-posta gönderilmediğinde kayıt başarılı ve “e-postanızı kontrol edin” yanıtı | İzole akışta yeniden üretildi |
| U11 | P1 | Job AI veri sözleşmesi / eski ingest ve yönetim sayaçları uyumsuz | Yeni entegrasyon sonrası kontrol gerekiyor |
| S01 | P1 | 22 mockup ilan ve 20 fake kullanıcı üreten araçlar üretim ağacında | Açık; otomatik çalıştıkları görülmedi |
| S02 | P2 | Sahte veriyi ayıran kalıcı etiket yok | Model ve seed kodunda yok |
| V01 | P2 | Yetenek ağı sabit dekoratif grafik | Açık |
| V02 | P2 | Hızlı asistan bir kısayol menüsü | Arayüz açıklaması bunu söylüyor; AI sohbet değil |
| V03 | P2 | ATS skoru bölüm doluluk kontrolü | Açık; iddia düzeltilmeli |
| V04 | P2 | Maaş tahmininde sabit %10 artış | Açık |
| V05 | P2 | Kurs/süre/yol haritası verileri editoryal tahminler | Açık; gerçek kurs doğrulaması yok |
| V06 | P2 | Mülakat alt puanları ve “AI” etiketleri değerlendirme yöntemini tam yansıtmıyor | Açık |
| V07 | P2 | Sunumda ölçülmüş ürün sonucu olmayan performans potansiyelleri | Gerçek başarı olarak kullanılmamalı |
| V08 | P2 | Pro/HR/company rolleri var; tam ticari/işveren akışı yok | Kullanıcıya vaat edilirken kapsam netleşmeli |

## 4. Gerçek kullanıcılar açısından kritik açıklar

### G01 — Kaynak kodu ve dahili dosyalar statik web kökünde

Kanıt: `app/__init__.py:25`, `Flask(..., static_folder=BASE_DIR, static_url_path='')`. `Caddyfile` tüm yolları backend'e geçiriyor; dahili dosyalar için bir izin listesi yok.

Gerçek uygulamanın izole test istemcisinde `/app/config.py`, `/tools/seed_fake_jobs.py` ve `/tests/backend/test_auth.py` **200** döndü. İçerikleri rapora taşınmadı. Bu, API yetkilerinden bağımsız bir dosya servis yoludur.

Yerel dizinde `SIFRELER.txt` ve `server.log` da var. Bunlar denetimde açılmadı. `.gitignore` dosyayı Git'ten uzak tutar; Flask'ın dosyayı servis etmesini engellemez. `.dockerignore`, `.git` ve `.env` gibi bazı öğeleri dışlıyor fakat `SIFRELER.txt` ve `server.log` için açık bir dışlama içermiyor; Dockerfile `COPY . .` kullanıyor. Git'ten üretilen build ile doğrudan yerel build'in içerikleri aynı olmayabilir.

Gereken değişiklik: yalnızca `css/`, `js/`, `vendor/`, gerekli görseller ve açıkça yayımlanan belgeler web kökünde kalmalı. Backend, araçlar, veritabanı, yedek, log, Git ve sır dosyaları hiçbir statik URL'den servis edilmemeli. Canlıda böyle bir dosyanın açılıp açılmadığı ayrıca erişim loglarıyla kontrol edilmeli; burada canlı sızıntı yaşandığı iddia edilmiyor.

### G02 — Yönetici e-postasını doğrulamadan yönetici olma

Kanıt: `app/blueprints/auth.py` kayıt/giriş akışı ile `app/authz.py:is_user_admin`. `ADMIN_EMAILS` içindeki e-posta, sahipliği doğrulanmadan admin kabul ediliyor. Giriş, `email_verified_at` şartı aramıyor.

İzole senaryo: boş test DB'sinde admin listesine bir test adresi verildi; o adresle kayıt ve giriş yapıldı. Sonuç: `emailVerified:false`, `isAdmin:true`, `/api/admin/stats` **200**. Üretimde gerçek admin adresiyle deneme yapılmadı.

Koşul: ilgili bootstrap adresinin önceden güvenli biçimde kaydedilmemiş olması veya bu güven politikasının yanlış kullanılması. Çözüm: admin yetkisi için doğrulanmış sahiplik ve kontrollü bootstrap; yeni bir açık kayıt, yalnızca e-posta metni eşleşmesiyle admin yetkisi almamalı.

### G03 — Hesaplara göre ayrılmayan cihaz verisi

Kanıt: `js/state.js:213`, `:264`, `:309`; `js/data/constants.js` tek `STORAGE_KEY`; `js/views/auth.js:submitAuthForm`. Hesap girişinde cihazdaki eski veriler temiz bir kullanıcı alanına taşınmıyor; `pullStateFromServer` mevcut state ile birleşim yapıyor.

Kontrollü JS senaryosu: cihazda A hesabının tamamlanmış profili ve henüz senkronize edilmemiş başvurusu varken B hesabıyla giriş yapılmış kabul edildi; B'nin sunucu profili boş döndü. Kod, **A'nın profilini B oturumu altında yükleme** ve **A'nın yerel başvurusunu B oturumu altında kaydetme** çağrılarını başlattı. Bu, gerçek sunucuda veri karıştığının kanıtı değil; kaynak kodunun bu koşulda yaptığının yeniden üretimidir.

Normal çıkış akışı localStorage'ı temizliyor; sorun özellikle oturum süresi dolması, hesap değişimi ve eski yerel verinin kaldığı akışta ortaya çıkıyor. CV listeleri de hesap kimliğine göre ayrılmıyor.

Çözüm: sunucunun sabit kullanıcı kimliğine bağlı depolama alanı, kimlik değişiminde temiz state, misafir verisini kullanıcıya aktarmak için açık ve kontrollü içe aktarma. Başka hesaba ait yerel veri otomatik yüklenmemeli.

### G04 — Hazır “temizlik” komutları hedefli değil

`tools/seed_fake_jobs.py:purge_pool_files`, bütün `ilan_havuzu/*.json` dosyalarını siler; ardından 22 mockup ilanı yeniden yazar. **Bu betik örnek veriyi kaldırma aracı olarak çalıştırılmamalı.**

`--purge-db` yolu bütün `SavedJob`, `JobInterviewQuestion` ve `JobEvent` kayıtlarını siliyor, tüm ilgili başvuruların `job_id` alanını boşaltıyor. İşlem mockup kimlikleriyle sınırlandırılmamış. `jobs` tablosunu da temizlemiyor; kullanıcının gerçek kayıtlarına zarar verip ilan kaynağındaki örneği bırakabilir.

`tools/seed_fake_users.py:purge`, 20 belirli adres yerine bütün `@example.com` kullanıcılarını hedefliyor. Gerçek bir kişinin başka bir QA hesabı veya saklanması gereken test senaryosu da bu kapsama girebilir.

Çözüm: üretim ağacından bu araçları çıkarma/erişime kapatma; ayrı geliştirme fixture'ları; yalnızca kesin kimlik listesi ve veri kökeniyle sınırlı, önce sayım yapan temizlik. Bu denetimde bu betiklerin hiçbiri çalıştırılmadı.

### G05 — Görünen belgeler ve saklanan veri farklı

`docs/gizlilik.html:55`, ham mülakat cevabının sunucuda saklanmadığını söylüyor. `app/models.py:InterviewSession.transcript` ve `js/views/interviewShared.js:persistInterviewProgress`, cevap metnini transcript ile sunucuya kaydediyor. Sadece skor kaydedilmiyor.

Gizlilik ve aydınlatma HTML/Markdown dosyalarında `[ŞİRKET BİLGİLERİ]`, `[ŞİRKET UNVANI, ADRES]`, `[İLETİŞİM E-POSTASI]` gibi yer tutucular da var. Bunlar gerçek kullanıcıya sunulan metinlerin içinde.

Gereken iş: gerçek saklama davranışı ile kullanıcıya açıklanan davranışı eşitlemek, işletmeci/iletişim alanlarını tamamlamak ve kullanılan metnin sürümünü onay kaydına bağlamak. Bu tespit kod/metin karşılaştırmasıdır; hukuki uygunluk kararı değildir.

## 5. İş bulma akışındaki eksikler ve yanıltıcı göstergeler

### U01–U02 — Doğrulanmış ilan ve başvuru durumları

`js/views/jobList.js` her kartta, `js/views/slidePanel.js:25` her detayda koşulsuz **“Doğrulanmış İlan”** üretiyor. Modelde bu rozeti destekleyen bir doğrulama kaydı yok. Kaynağın gerçek bir servis olması her ilanın işveren tarafından doğrulandığı veya hâlâ açık olduğu anlamına gelmez. Rozet yalnızca kanıtlı doğrulama durumuna bağlı olmalı; kaynak ve son kontrol tarihi ayrı gösterilmeli.

`slidePanel.js:109` içindeki `applyToJobFromPanel`: URL varsa yeni pencere açıyor, **URL olsun olmasın** `saveJobToKanban(..., 'applied')` çağırıyor. İzole JS kontrolünde URL'siz ilan için tek sonuç `status:'applied'` oldu. İşverene başvuru gönderen bir endpoint veya teslim teyidi yok.

Gerçek ürün davranışı: “İlana git” geçerli başvuru sayfasını açmalı; “Başvurdum” kullanıcının ayrı teyidi olmalı. URL yoksa başvuru eylemi kullanılamamalı. Popup açmak ya da hazırlık paketi üretmek başvurunun teslim edildiği anlamına gelmemeli. Kanban, açıkça kullanıcının kendi süreç takibi olarak korunabilir.

### U03–U05 — Kişiselleştirme şu anda yeterli kanıta dayanmıyor

`js/main.js:initializeApp` ve `js/views/auth.js:submitAuthForm`, yeni kullanıcının profil kurulumunu otomatik başlatmıyor. Kurulum Ayarlar'a bırakılmış. Kayıt sonrası uygulama kişinin adı, becerileri, hedef rolü ve çalışma tercihleri olmadan açılabiliyor.

`js/engine/matcher.js:computeMatchScore` kontrol sonuçları:

| Kontrollü girdi | Çıktı | Sorun |
|---|---:|---|
| Boş profil + beceri/deneyim gereksinimi bilinmeyen ilan | **%50** | Henüz aday hakkında bilgi yok |
| Yalnızca aynı unvan ve aynı çalışma tipi; beceri/deneyim kanıtı yok | **%70** | “Yüksek eşleşme” eşiğine erişiliyor |
| Aynı aday için biri Berlin, biri İstanbul olan iki aynı nitelikli ofis ilanı | **%100 / %100** | Lokasyon skorda kullanılmıyor |
| Ruhsatı olmayan aday, ruhsatı zorunlu örnek ilan; frontend | **%30**, uygun değil | Frontend eleyici koşulu uyguluyor |
| Aynı örnek; `app/matching.py` | **%100** | Haftalık e-posta motoru eleyici koşulu yok sayıyor |

Eksik beceri listesine 30, belirsiz deneyim ihtiyacına 15 puan veriliyor. Eşleşme yüzdesi işe alınma olasılığı değil, bu ağırlıkların toplamı. Kullanıcı arayüzü bunu belirtmeli; veri eksikken “hesaplamak için bilgi eksik” veya düşük güven durumu kullanılmalı.

Mevcut çok eksenli verilerde `roleFamily`, kıdem, meslek, ülke, şehir, yetenek seviyesi/yıl gibi alanların hepsi puanlamada gerçek bir kısıta dönüşmüyor. Profildeki beceri etiketinin bulunması birçok koşulu karşılanmış saymaya yetiyor. Özellikle dil seviyesi, çalışma izni, mesleki ruhsat ve yer değiştirme koşulları serbest metin unvan benzerliğiyle doğrulanamaz.

İlk gerçek kapsam için: hedef rol/meslek, konum veya uzaktan çalışma, deneyim, mevcut beceriler ve zorunlu koşullar toplanmalı. Sonra eksik verinin güveni düşürdüğü ve frontend/e-posta tarafında aynı sonucu veren tek bir eşleştirme sözleşmesi kurulmalı. Uygun iş bulunamadığında bunu açıkça söyleyen boş sonuç ekranı olmalı.

### U06 — Öğrenme önerisi gerçek beceri beyanına dönüşüyor

`js/views/recommendations.js:54` içindeki “Harekete Geç”, `addSkillToProfile(rec.skill)` çağırıyor. `js/views/cvBuilder.js:33`, beceriyi **hem profil becerilerine hem CV becerilerine** ekliyor. İzole akışta “Python öğren” önerisine tıklamak profil becerisine doğrudan `Python` ekledi. Kullanıcı eğitim tamamlamadı.

Bu, skorun artmasını ve CV'nin kullanıcının henüz sahip olmadığı beceriyi iddia etmesini sağlayabilir. “Öğrenilecekler” ayrı veri olmalı; beceri kazanımı kullanıcı tarafından ayrıca teyit edilmeli. Yol haritasının ayrı butonunda “öğrendin mi?” teyidi var; öneri eyleminde de aynı anlam ayrımı kurulmalı.

### U07–U08 — AI başvuru paketi görünür ama çalışması engelleniyor

`js/views/applicationPack.js:24`, doğrudan `fetch` kullanıyor; yalnızca `Content-Type` başlığı var. `app/__init__.py:_csrf_guard`, durum değiştiren API isteklerinde `X-Requested-With: XMLHttpRequest` istiyor. Aynı başlıklarla izole POST **403 / csrf_check_failed** döndü. `apiFetch` bu başlığı otomatik ekliyor; paket bu ortak yardımcıyı kullanmıyor.

İkinci sorun: `applicationPack.js:37` ve `:144`, `cvContent.experienceEntries` alanını bekliyor. Gerçek güncel şema `js/state.js:defaultCvContent` içinde `experience` dizisi. Sonuçta gerçek deneyim kayıtları pakete eksik gider, öneriler doğru kayıtları bulamaz. Bu hata CSRF düzeltildikten sonra da kalacak.

Paketin CV'ye uygulama yolu aktif özeti doğrudan değiştiriyor. İlana özel yeni CV üretme akışı (`cvAiGenerate.js`) yeni versiyon açarken bu akış aynı korumayı kullanmıyor. Kullanıcının temel CV'sini koruyan önizleme/ayrı sürüm davranışı belirlenmeli.

### U09 — Kayıt ve senkronizasyonun başarı anlamı

`state.js:syncApplicationToServer`, başarısız HTTP yanıtlarında kullanıcıya hata göstermiyor; yerel işlem daha önce “başvuru kaydedildi” bildirimi verebiliyor. Silme eşitlemesinde de sonuç kontrolü eksik. Aynı kayıt hem cihazda hem sunucuda varmış gibi algılanabilir.

CV kaydı için açık “sunucuya kaydedilmedi / kaydedilmemiş değişiklikler var” durumları zaten var; bu iyi bir temel. Başvuru/profil için de kaydediliyor, sunucuda kaydedildi, tekrar denenecek durumları gerekli. Kullanıcı verisi kaybı ve yeniden beliren silinmiş kayıtlar için çatışma/silme sözleşmesi kurulmalı.

`pullStateFromServer` profil geldikten sonra dashboard, Kanban ve CV editörünü çiziyor; ilan listesinin skorları, öneriler ve kimlik başlığının hepsi aynı anda yeniden çizilmiyor. Başlangıçta boş/önceki profil için üretilmiş skorlar ekranda kalabilir.

### U10 — E-posta katmanı geliştirme davranışını sürdürebiliyor

`app/email_service.py:17`: Resend anahtarı yoksa e-posta gönderilmiyor, bağlantılı HTML loga yazılıyor, `False` dönüyor. Kayıt/doğrulama ve parola sıfırlama çağıranları bu sonucu kullanıcı akışına yansıtmıyor. İzole kontrolde gönderim `False` iken kayıt yanıtı **200 / “E-postanızı kontrol edin”** oldu.

Üretimde mail anahtarı, gerçek gönderici alanı ve `PUBLIC_BASE_URL` çalışması doğrulanmalı. Kullanıcı açısından genel ve güvenli yanıtlar korunurken işletim tarafında gönderim hatası görünür ve yeniden denenebilir olmalı. Doğrulama/sıfırlama bağlantılarının loglara dökülmesi gerçek hesaplarda kaldırılmalı.

### U11 — Yeni kaynağa geçişin kalan sözleşmeleri

`app/job_ai.py:to_job`, gerçek kaynaktan gelen beceri listesini `skills` yapıyor; önceki çok eksenli `_tags.requirements/core/signal` yapısını üretmiyor. `normalizeJob` bu yapıyı bulamazsa basit beceri eşleştirmesine dönüyor. Yeni bağlantı, mevcut altı eksenli analiz iddiasının otomatik tamamlandığını göstermiyor.

Bilinmeyen çalışma tipi `Office` yapılıyor; eksik `_fetchedAt`, frontend'de “şimdi”ye çevriliyor. Bunlar gerçek gözlem yerine yeni değer üretir. İlanın yayın tarihi, ilk görülme, son görülme, son kontrol ve detay bekleme durumları ayrılmalı. İlanın güncel ve başvurulabilir olduğu kanıtı olmadan yeni/doğrulanmış sayılmamalı.

Eski `/api/jobs/ingest` hâlâ yerel `jobs` tablosuna yazıyor; yeni liste bu tabloyu okumuyor. Yönetim ayarlarındaki `jobCount` da yerel `Job.query` sayısını kullanıyor. Bu nedenle başarılı aktarım veya yönetim panelindeki ilan sayısı, gerçek vitrindeki Job AI ilan sayısı anlamına gelmeyebilir. Eski araçlar/devreler açıkça kapatılmalı veya yeni sözleşmeye bağlanmalı.

Yeni kaynak için doğrulanması gereken sonuç: kontrollü gerçek ilan eklenmesi, sitede görünmesi, değişikliğin yansıması, kaynaktan kaldırılınca vitrinden kalkması, başvuru URL'sinin doğru olması, kaynak kesilince örnek veriye dönülmemesi. Canlıya yazma yapılmadan bu raporda yalnızca son madde ve eksik yapılandırma davranışı izole doğrulandı.

## 6. Mockup veya olduğundan fazla anlam yüklenmiş görseller/içerikler

| Alan | Kanıt | Gerçek durum | Önerilen karar |
|---|---|---|---|
| Yetenek Ağı | `index.html:640`; `sidebarWidgets.js:renderSkillNetworkCaption` | Beş sabit düğüm/dört sabit çizgi; sadece başlık ilk iki beceriden üretiliyor | Gerçek ilişki verisine bağla veya dekoratif görsel olarak adlandır |
| Hızlı Asistan | `js/views/assistant.js` ve `index.html:1352` | Beş ön tanımlı kısayol; serbest metin AI konuşması yok; açıklama bunu söylüyor | Kullanışlı kısayolları koru, kişisel AI danışman gibi sunma |
| CV / ATS Skoru | `dashboard.js:computeCvScore` | Yedi bölümün doluluk kontrolü; ATS sistemiyle test veya işverene özgü eleme simülasyonu yok | “CV tamamlanma kontrolü” olarak sun; ATS iddiasını gerçek doğrulamaya bağla |
| Maaş tahmini | `slidePanel.js:renderSalaryComparisonInPanel` | Deneyim fazlaysa ilan üst maaşı × 1.1; piyasa tahmin modeli yok | Sabit artışı kaldır veya açık formül tahmini yap; veri yoksa boş göster |
| Piyasa maaş ortalaması | `engine/salary.js` | Eldeki ilan aralıklarının orta noktası; baskın para birimi; ödeme dönemi/ülke/kıdem tam ayrılmıyor | Örneklem kapsamını belirt; ücret dönemi ve para birimini ayır |
| Kurs önerileri | `js/data/courses.js` | 50 editoryal kayıt, süre/seviye sabit; bağlantılar çoğunlukla platform arama sayfası | “Eğitim arama önerisi” de; belirli kurs/süreyi doğrulanmış katalog gibi sunma |
| Öğrenme süresi | `engine/roadmap.js:SKILL_HOURS_ESTIMATE` | Sabit saat tablosu; bilinmeyen beceri 30 saat | Kullanıcı seviyesine göre belirsizlik aralığı ve plan olarak sun |
| Mülakat alt puanları | `interviewShared.js:935` | Cevap derinliği karakter sayısı; anlatım yeteneği teknik puan ve uzunluğun karışımı | Ölçülen şeyi adlandır; bağımsız uzman/AI değerlendirmesi izlenimi verme |
| Mülakat “AI değerlendirmesi” başlığı | `interviewShared.js:1083` | Kural tabanlı sonuçlarda da aynı başlık kullanılabiliyor; dışa aktarma yöntemi daha doğru ayırıyor | Her soruda `method` ve gerçek değerlendirme kaynağını göster |
| Video mülakat | `videoInterview.js` | Gerçek kamera/MediaRecorder kaydı; video yerelde indiriliyor; puanlama yazılı/dikte edilmiş cevap metnine dayanıyor | Video, yüz ifadesi, beden dili veya telaffuzun modelce analiz edildiğini iddia etme |
| Sunumdaki etki rakamları | `presentation.html:700` civarı | 4.3x davet, %15→%65, 3x teklif ve 8→2.5 ay **potansiyel/hedef** olarak yazılmış; ürün deneyinden kanıt bulunmadı | Bunları gerçekleşmiş başarı/ölçülmüş kullanıcı sonucu olarak yayımlama |
| Pro/HR/company | `authz.py`, admin rol seçimi | Gerçek yetki etiketleri; tam ödeme/abonelik/işveren işe alım iş akışı bulunmadı | İlk yayında aday hesabı ve yönetim kapsamını netleştir |

Mülakat, soru bankası ve öğrenme yol haritası kullanıcıya gerçek bir hazırlık hizmeti sağlayabilir. “Simülasyon” adı tek başına sahte veri sorunu değildir; işverenle yapılmış gerçek görüşme veya gerçekten ölçülmüş beceri olarak kaydedilmemelidir.

## 7. Ne kaldırılmalı, ne korunmalı?

| Öğe | Karar | Gerekçe |
|---|---|---|
| Eski 11 örnek ilan, 163 bozuk/eski kazıma kaydı, `ilanlar.js` | Son kopyada kaldırılmış; canlı paket ve cache'te kalmadığını kontrol et | Başvuru ve güncellik kanıtı yoktu |
| `tools/seed_fake_jobs.py`, `tools/seed_fake_users.py` | Üretim paketinden çıkar; gerekiyorsa ayrı geliştirme fixture'ına taşı | Yeniden örnek veri üretme ve tehlikeli purge riski |
| Üretim DB'sindeki kesin seed hesapları ve ilişkileri | Önce kesin kimlik listesiyle say; sonra hedefli temizlik | Bu raporda gerçekten mevcut oldukları bilinmiyor |
| `docs/VERI_SEED_REHBERI.md`, `tools/README.md` seed komutları | Üretim yönergelerinden kaldır/güncelle; geliştirme için açıkça işaretle | Rehber prod'a fake kullanıcı/ilan eklemeyi tarif ediyor; veri mimarisi de eskimiş |
| Backend/model açıklamalarındaki “dosya havuzu korunur” ifadeleri | Job AI mimarisine göre düzelt | Yeni davranışla çelişiyor |
| `js/state.js` eski demo temizleme migrasyonu | Şimdilik koru | Yeni demo üretmiyor; eski cihaz verisini temizliyor |
| Boş varsayılan profil/CV ve boş başvuru listeleri | Koru | `defaultState` yeni sahte kullanıcı doldurmuyor |
| `soru_havuzu/*.json`, `app/seed.py`, hazır teknik soru bankası | Koru, içerik kalitesini düzenle | Ürünün gerçek eğitim içeriği; fake kullanıcı veya ilan değildir |
| `cvHints.js`, form placeholder'ları | Koru, örnek oldukları açık kalsın | Kullanıcının verisi olarak kaydedilmedikçe normal arayüz yardımı |
| `tests/` ve izole test verileri | Koru, webden servis edilmesini engelle | Gerçek davranışı denetlemek için gerekli |
| Dashboard ve bildirim kodu | Koru, kaynak/güven anlamlarını düzelt | Sayılar ve olaylar büyük ölçüde mevcut kullanıcı verilerinden hesaplanıyor; rastgele fake bildirim üretilmiyor |
| `ai_service.py` eski Gemini katmanı | Kullanım analizi sonrası üretim dışına taşıma adayı | Aktif AI blueprint'i DeepSeek kullanıyor; artık çalışmayan ikinci katman bakım yükü |
| `server.log`, şifre/dahili dokümanlar, test/seed araçları | Webden erişimi kaldır | Statik yayımlanması gerekmiyor |

### Güvenli veri temizliğinin kapsamı

1. Önce DB/paket yedeği ve sadece okunur sayım: Ek C'deki **20 tam e-posta**, Ek A'daki **11 tam job kimliği**, Ek B'deki **22 tam job kimliği** ve Ek D'deki **163 `sc-...` kimliği** ayrı değerlendirilir.
2. İlan kayıtlarında yalnızca ID'ye güvenilmez: eski küçük sayısal kimlikler başka kayıtlarda çakışabilir. Şirket, başlık, kaynak, oluşturulma zamanı ve bilinen seed içeriğiyle köken doğrulanır. Gerçek şirket adı tek başına temizlik ölçütü değildir.
3. Silmeden önce ilgili `applications`, `saved_jobs`, `job_events`, `job_interview_questions`, `interview_sessions` ve kullanıcı tarafında profil/CV/oturum ilişkilerinin sayımı alınır. Kullanıcının gerçek not ve CV'si korunur; örnek ilana ait kayıt gerekiyorsa açıklamalı arşive taşınır.
4. Kesin fake hesaplar hedefli silinir/devre dışı bırakılır; gerçek kullanıcıların hesabı, oturumu ve başvuruları için toplu wildcard temizlik yapılmaz. Admin analitiği bu hesaplardan arındırılır.
5. Tarayıcıdaki eski örnek kayıtlara sürümlü, belirli kimliklerle sınırlı migrasyon uygulanır. Tüm localStorage'ı topluca silmek gerçek CV ve başvuruları da yok edebilir.
6. Son kontrolde yeni hesap boş başlar; hiçbir seed otomatik çalışmaz; örnek veri kaynağa erişim hatasında geri gelmez.

Bu adımlar burada uygulanmadı. Özellikle eski `--purge-db` komutu bu planın yerine kullanılmamalı.

## 8. Gerçek iş bulma ürünü için uygulanabilir sıra

1. **Hesap ve veri sınırı:** G01/G02/G03 kapatılır; profil ve kayıtlar kullanıcı kimliğiyle ayrılır. Gizlilik metni gerçek saklama davranışına göre tamamlanır.
2. **Tek gerçek ilan kaynağı:** Job AI bağlantısı üretimde doğrulanır; sadece kalite eşiğini geçen, kaynak kimliği ve kullanılabilir URL'si bulunan ilanlar yayımlanır. Kaynak kesintisi ayrı durumdur; örnek liste açılmaz.
3. **Adayı tanıma:** kayıt/giriş sonrası hedef meslek, lokasyon, deneyim, beceriler ve zorunlu koşullar kısa kurulumda alınır. CV ayrıştırma sonucu kullanıcıya onaylatılır. Profil olmadan kişisel eşleşme iddiası yapılmaz.
4. **Açıklanabilir sıralama:** gerçek mevcut beceri, zorunlu koşullar ve tercihler kullanılır. Aynı aday/ilan için ekran ve e-posta aynı skoru verir. Eksik veri ve uygun olmayan sonuç gizlenmez.
5. **Başvuruya hazırlık ve yönlendirme:** başvuru paketi ve CV şeması düzeltilir; temel CV korunur; doğru kaynak ilanına gidilir; “başvurdum” ayrı teyittir.
6. **Kalıcı takip:** sunucu kaydı başarı/hata durumu gösterilir; çok cihazlı güncelleme ve silme tutarlı çalışır. Gerçek e-posta ve hatırlatma teslimi kontrol edilir.
7. **Sonuç ölçümü:** gerçek ilan görüntüleme → kaydetme → kaynak sayfasına gitme → kullanıcının başvuru teyidi → görüşme → teklif sonuçları ayrı olaylar olarak ölçülür. Test hesapları dışlanır; kullanıcı beyanı ve dışarıdan doğrulanmış sonuç ayrı tutulur.

İlk gerçek ürün için yeterli kapsam: **güncel ve başvurulabilir ilan + kullanıcıya uygun açıklanabilir sıralama + CV/mülakat hazırlığı + güvenilir süreç takibi**. İşveren sistemine otomatik başvuru gönderimi, ayrıca kapsamlandırılabilecek bir ürün kararıdır. Kodun bugün böyle bir gönderim yaptığı varsayılmamalı.

### Yayın kabul senaryoları

| Senaryo | Beklenen sonuç |
|---|---|
| Yeni kullanıcı kayıt olur | E-posta gerçekten teslim edilir; kullanıcı kendi boş profiliyle başlar |
| Bootstrap admin e-postasını başka biri yazar | Sahipliği doğrulanmadan yönetici yetkisi alamaz |
| A'nın oturumu sona erer, B aynı tarayıcıda giriş yapar | A'nın profili/CV'si/başvurusu B'de görünmez ve B'ye yüklenmez |
| Backend kaynak/şifre/log URL'si istenir | 404/403; statik içerik sunulmaz |
| Aday profili veya ilan gereksinimleri eksiktir | Kanıtsız yüksek eşleşme gösterilmez |
| İlan bağlantısı yoktur | “İlana git/başvuru” kapalıdır; otomatik applied kaydı yoktur |
| Kullanıcı “Python öğren”e basar | Öğrenme planına eklenir; CV'sine kazanılmış beceri yazılmaz |
| Aday zorunlu ruhsatı taşımıyordur | Ekran ve e-postada aynı uygunluk kararı görülür |
| Job AI kesilir | Kaynak hatası görünür; eski/fake ilanla doldurulmaz |
| CV paketi hazırlanır | CSRF hatası olmadan gerçek güncel deneyim alanlarıyla çalışır |
| Kaynak ilan kapanır | Vitrinden kalkar; kullanıcının gerçek geçmişi açıklamalı korunur |
| Sunucu kayıt isteği başarısızdır | Kullanıcıya “sunucuda kaydedildi” sonucu gösterilmez |

## 9. Doğrulama ve kanıt dosyaları

| Kontrol | Sonuç | Sınır |
|---|---|---|
| Mevcut JS birim testleri | **22 geçti, 0 kaldı** | Sabit kopyada çalıştırıldı; bu testler bütün ürün akışını kapsamıyor |
| Auth/CSRF/session/me/matching backend testleri | **46 geçti** | Sabit kopya, in-memory SQLite, dış servis anahtarları boş |
| İlk backend tam koşusu | **154 geçti, 1 kaldı** | Job AI değişikliği tamamlanmadan önceki dosyalar; son kopyanın tam test sonucu olarak kullanılamaz |
| Başarısız ilk test | `test_cv_parse_rejects_fake_pdf_via_magic_bytes`: 400 beklerken 503 | Bu ortamda Docling paketi yok; bozuk PDF denemesi belge işleyiciye ulaşınca 503 aldı. Üretimde de bozuk olduğu iddia edilmiyor |
| Ek izole backend kontrolleri | Kaynak servis 200; admin doğrulamasız 200; başvuru paketi 403; mail gönderilmeden kayıt 200; kaynaksız ilan API'si 503 | Dış ağa çıkılmadı, test DB'si kullanıldı |
| Ek JS kontrolleri | %50/%70 kanıtsız skor, lokasyonun etkisizliği, URL'siz applied, öğrenme eyleminin beceri eklemesi, hesap karışımı; yeni API hatasında 0 ilan | Kontrollü VM senaryoları; tam tarayıcı/üretim kullanıcı testi değil |
| Canlı servis/Postgres/mail/AI/video/PDF görsel testleri | **Yapılmadı** | Kaynak ve izole davranış raporu; canlı hizmet hazır onayı değil |

Kanıtlar:

- [Sabit kaynak manifesti](.qa/nextstep_audit_snapshot_manifest.json)
- [Son kopyanın veri envanteri](.qa/nextstep_audit_inventory.json)
- [Eski 163 kayıtlı ara ölçüm](.qa/nextstep_audit_inventory_earlier.json)
- [İzole backend kontrol sonuçları](.qa/nextstep_audit_backend_probes.json)
- [İzole frontend kontrol sonuçları](.qa/nextstep_audit_frontend_probes.json)
- [163 eski ilanın tamamı ve kayıt bazında kalite işaretleri](.qa/nextstep_eski_ilan_envanteri_2026-10-20.csv)

<!-- GENERATED_APPENDICES -->

## Ek A — Kaldırılan 11 eski örnek ilanın tam listesi

İçerikler başlangıç Git tabanı `a23df35` üzerinden okunmuştur. Sabit son kopyada bu dosyalar yoktur. Kayıtların şirket adları gerçek şirketlere aittir; tablodaki ilanların o şirketler tarafından gerçekten yayımlandığı doğrulanmış değildir. Kaynak bağlantıları yalnızca dosyadaki değerlerdir.

| Dosya | Kimlik | Şirket | Pozisyon | Dosyadaki URL |
|---|---|---|---|---|
| ilan_havuzu/ilan_1.json | 101 | Getir | Senior Go Developer | https://www.linkedin.com/jobs/view/101 |
| ilan_havuzu/ilan_10.json | 5 | Insider | Data Scientist | https://www.kariyer.net/ilan/654321 |
| ilan_havuzu/ilan_11.json | 6 | Microsoft | Backend Team Lead | https://www.linkedin.com/jobs/view/1122334455 |
| ilan_havuzu/ilan_2.json | 102 | Hepsiburada | Frontend Developer (Vue.js) | https://www.kariyer.net/ilan/102 |
| ilan_havuzu/ilan_3.json | 103 | Dream Games | Mobile Software Engineer (Flutter) | https://www.glassdoor.com/job/103 |
| ilan_havuzu/ilan_4.json | 104 | Insider | AI / Machine Learning Engineer | https://www.linkedin.com/jobs/view/104 |
| ilan_havuzu/ilan_5.json | 105 | Trendyol | DevOps Specialist | https://www.kariyer.net/ilan/105 |
| ilan_havuzu/ilan_6.json | 1 | Spotify | Senior Backend Engineer | https://www.linkedin.com/jobs/view/123456789 |
| ilan_havuzu/ilan_7.json | 2 | Hepsiburada | Frontend Developer | https://www.kariyer.net/ilan/123456 |
| ilan_havuzu/ilan_8.json | 3 | Trendyol | DevOps Engineer | https://www.indeed.com/job/devops-engineer-123 |
| ilan_havuzu/ilan_9.json | 4 | Getir | Full Stack Developer | https://www.linkedin.com/jobs/view/987654321 |

## Ek B — Seed betiğindeki 22 kesin mockup ilan tanımı

Kaynak: `tools/seed_fake_jobs.py:MOCK_JOBS`. Bunlar mevcut canlı ilanlar olarak doğrulanmamıştır; betik tarafından yazılmış örnek tanımlardır. Sabit kopyada ilan dosyaları kaldırılmış olsa da bu üretici betik duruyor. URL'ler betikte bulunan üretilmiş adreslerdir.

| Kimlik | Şirket | Pozisyon | Betikteki URL |
|---|---|---|---|
| job-101 | Trendyol | Senior Go & Distributed Systems Engineer | https://trendyol.com/kariyer/job-101 |
| job-102 | Insider | Senior Frontend Developer (React & TypeScript) | https://useinsider.com/careers/job-102 |
| job-103 | Getir | Lead Backend Architect (Python & Django) | https://getir.com/kariyer/job-103 |
| job-104 | Papara | Node.js High-Load Backend Developer | https://papara.com/kariyer/job-104 |
| job-105 | Midas | Senior Flutter Mobile Application Engineer | https://getmidas.com/careers/job-105 |
| job-106 | Peak Games | Senior iOS Engineer (Swift & SwiftUI) | https://peak.com/careers/job-106 |
| job-107 | Hepsiburada | Senior Android Engineer (Kotlin & Jetpack) | https://hepsiburada.com/kariyer/job-107 |
| job-108 | Jotform | Staff DevOps & Platform Infrastructure Engineer | https://jotform.com/careers/job-108 |
| job-109 | Baykar Technologies | Senior Data & Pipeline Engineer | https://baykartech.com/kariyer/job-109 |
| job-110 | Dream Games | Machine Learning & AI Systems Engineer | https://dreamgames.com/careers/job-110 |
| job-111 | Garanti BBVA Teknoloji | Senior Java Spring Boot Engineer | https://garantibbvateknoloji.com.tr/job-111 |
| job-112 | Siemens Türkiye | Senior .NET Core Developer (C# & Cloud) | https://jobs.siemens.com/job-112 |
| job-113 | Commencis | Full-Stack Engineer (Next.js & Node.js) | https://commencis.com/careers/job-113 |
| job-114 | Akbank Teknoloji | Senior Vue.js / Nuxt Frontend Developer | https://akbank.com/kariyer/job-114 |
| job-115 | Armut.com | Full-Stack PHP Developer (Laravel & Vue) | https://armut.com/kariyer/job-115 |
| job-116 | Aselsan | Embedded Systems Specialist (C/C++ & RTOS) | https://aselsan.com.tr/kariyer/job-116 |
| job-117 | Trendyol Express | QA Automation Engineer (Python & Playwright) | https://trendyol.com/kariyer/job-117 |
| job-118 | Picus Security | Cloud Security & Infrastructure Architect (AWS) | https://picussecurity.com/careers/job-118 |
| job-119 | Protocol Labs / Remote | Senior Systems Developer (Rust & Distributed) | https://protocol.ai/careers/job-119 |
| job-120 | TaleWorlds Entertainment | 3D Game Developer (Unity & C#) | https://taleworlds.com/careers/job-120 |
| job-121 | Turkcell | Cybersecurity & SecOps Analyst | https://turkcell.com.tr/kariyer/job-121 |
| job-122 | Craftgate | Technical Product Manager / Tech Lead | https://craftgate.io/careers/job-122 |

## Ek C — Seed betiğinin ürettiği 20 sahte hesap adresi

Kaynak: `tools/seed_fake_users.py:FAKE_DEVELOPERS`. Bu liste, üretim DB'sinde 20 hesabın gerçekten var olduğuna dair bir sonuç değildir. Önce yalnızca bu tam adreslerle sayım yapılmalı. Betik ortak bilinen geliştirme parolası kullanıyor, e-postaları doğrulanmış işaretliyor ve kayıt zamanlarını geçmişe yayıyor; kullanıcı büyüme grafikleri bu kayıtlarla şişebilir. Parola bu rapora kopyalanmadı.

| Sıra | Tam e-posta |
|---|---|
| 1 | `ada.yilmaz@example.com` |
| 2 | `emir.kaya@example.com` |
| 3 | `zeynep.demir@example.com` |
| 4 | `mert.aydin@example.com` |
| 5 | `elif.sahin@example.com` |
| 6 | `can.ozturk@example.com` |
| 7 | `deniz.arslan@example.com` |
| 8 | `burak.celik@example.com` |
| 9 | `selin.koc@example.com` |
| 10 | `kaan.dogan@example.com` |
| 11 | `ece.yildiz@example.com` |
| 12 | `ozan.aksoy@example.com` |
| 13 | `merve.polat@example.com` |
| 14 | `yusuf.erdogan@example.com` |
| 15 | `nil.cinar@example.com` |
| 16 | `baris.kurt@example.com` |
| 17 | `irem.gunes@example.com` |
| 18 | `tolga.sen@example.com` |
| 19 | `gizem.acar@example.com` |
| 20 | `alp.yalcin@example.com` |

## Ek D — Eski 163 kazıma kaydının tamamı

[CSV dosyası](.qa/nextstep_eski_ilan_envanteri_2026-10-20.csv), her kaydın dosya adını, tam kimliğini, şirket/başlık/konumunu, tarihini, bağlantısını, açıklama uzunluğunu, beceri sayısını ve kalite işaretlerini içerir. Dosya UTF-8 BOM ve noktalı virgül ayracıyla Excel'de açılabilecek şekilde yazılmıştır.

Bu kayıtlar ilk ara ölçümde diskteydi; raporun sabit son kopyasında yoklar. Başvuru bağlantısı olmayan veya şirketi yanlış ayrıştırılmış bir kayıt, tek başına yapay olarak uydurulduğunun kanıtı değildir. Bu CSV'nin amacı hangi kaydın düzeltilmesi/yeniden toplanması gerektiğini kaybetmemektir.

## Ek E — Raporu tekrar kontrol etme

Denetim yardımcıları `.qa/nextstep_audit_inventory.py`, `.qa/nextstep_audit_probes.py`, `.qa/nextstep_audit_probes.mjs` ve `.qa/nextstep_audit_snapshot.py` altındadır. Seed betikleri import edilmedi/çalıştırılmadı; tanımlar Python AST ile okundu. Backend kontrolleri test ortamı ve yalnızca bellekte SQLite kullandı. Kaynak kopyası sır/log/DB/Git dosyalarını bilerek içermiyor.

Bu dosya bir inceleme raporudur. Kaynak ağacında sonradan yapılan düzeltmeler için bulguların kapanma kanıtı eklenmeli; burada belirtilen sabit kopya ile sonraki canlı sürüm birbirinin yerine kullanılmamalıdır.


## 10. Bütün bulguları kapatma planı ve sizin yapmanız gerekenler

Bu belge bir **uygulama planıdır**; aşağıdaki kutular tamamlanmış iş olarak işaretlenmemiştir. Temel rapor: [26 bulguluk denetim](NEXT_STEP_GERCEK_URUN_DENETIMI_2026-10-20.md).

Hedef akış: **kayıt ve doğrulama → aday profilini anlama → güncel ve başvurulabilir uygun işler → CV/başvuru hazırlığı → gerçek ilan sayfasına yönlendirme → kullanıcının teyit ettiği başvuruyu takip**.

Teknik uygulama, migrasyon, test, dağıtım hazırlığı ve işletim kontrolü benim yapabileceğim işlerdir. Sizden gereken bilgiler en sondaki kısa listededir. Önceki oturumlarda verilmiş erişim ve yetkiler tekrar istenmez.

### Uygulama sırası

| Sıra | İş | Kapanacak bulgular | Bağımlılık / teslim |
|---|---|---|---|
| 0 | Güncel sürümü sabitle, değişiklikleri birleştir | İnceleme sırasında değişen taban | Net dal/commit, mevcut verinin korunması |
| 1 | Web kökünü ve dağıtım paketini daralt | G01 | Gerçek hesap kabulünden önce |
| 2 | Admin ve kullanıcı veri ayrımını düzelt | G02, G03 | 1; hesap karışımı testleri |
| 3 | Örnek veri üreticilerini ayır, hedefli veri temizliği hazırla | G04, S01, S02 | 0–2; önce sayım, yedek ve hedef liste |
| 4 | Job AI bağlantısını ve ilan veri sözleşmesini tamamla | U11 | Tek gerçek kaynak, doğru yaşam döngüsü |
| 5 | Yeni kullanıcı profilini ve tek eşleşme motorunu tamamla | U03, U04, U05 | 2 ve 4; açıklanabilir eşleşme |
| 6 | İlan doğrulama ve başvuru eylemlerini düzelt | U01, U02 | 4; gerçek yönlendirme ve ayrı teyit |
| 7 | Öğrenme planını gerçek beceriden ayır | U06, V05 | 5; CV'ye yanlış beceri eklenmemesi |
| 8 | CV/başvuru paketi ve mülakat değerlendirmesini düzelt | U07, U08, V03, V06 | 2 ve 5; çalışan AI ve doğru etiketler |
| 9 | Kayıt/senkronizasyon ve e-posta teslimini tamamla | U09, U10 | 2; gerçek sunucu kaydı ve teslim durumu |
| 10 | Mockup göstergeleri ve ürün vaatlerini düzelt | V01, V02, V04, V07, V08 | Gerçek veri ve işlevlerle uyumlu ekranlar |
| 11 | Gizlilik açıklamalarını gerçek davranışa eşitle | G05 | 2, 8, 9 ve işletmeci bilgileri |
| 12 | Tam kabul testleri, kontrollü yayın ve pilot | Bütün bulguların kapanış kontrolü | 1–11; yeni sürüme ait kanıt |

1–3 önceliklidir. Diğer aşamalar küçük ve gözden geçirilebilir değişiklikler halinde tamamlanır. Her aşamanın kabul sonucu kaydedilir; önceki sürümde geçen test yeni sürümün kanıtı sayılmaz.

### 0. Güncel çalışma tabanını sabitle

- [ ] Başka oturumların son commit ve yerel değişikliklerini belirleyip tek uygulama tabanında birleştir.
- [ ] Sonradan yapılan Job AI ve kayıt/giriş değişikliklerini koru; eski dosya havuzunu geri getirme.
- [ ] Mevcut prod sürümü, yapılandırma adları, veritabanı sürümü ve geri dönüş yolu kaydedilsin; sır değerleri rapora yazılmasın.
- [ ] Üretimde yalnızca okunur sayım al: gerçek/fake adayları, ilan kaynakları, başvuru ve CV ilişkileri.

**Bitti sayılması:** hangi commit'in düzeltildiği ve hangi veri üzerinde işlem yapılacağı nettir. Başka çalışma ezilmemiştir.

### 1. Yalnızca yayımlanacak dosyaları webden erişilebilir yap

- [ ] Statik dosyalar için ayrı bir public kök veya açık izinli klasörler kullan.
- [ ] `app/`, `tools/`, `tests/`, `.git/`, sır, log, veritabanı ve yedek yollarını HTTP üzerinden kapat.
- [ ] Docker/dağıtım paketine yalnızca gereken dosyaları al; `.gitignore` korumasını web erişim kontrolü olarak kullanma.
- [ ] Mevcut kaynak erişiminin canlıdaki durumunu içerik/sır göstermeden kontrol et. Gerçekten açığa çıkmış bir sır bulunursa ilgili anahtarın rotasyonunu gerçekleştir.

**Bitti sayılması:** CSS/JS/gerekli belgeler çalışır; kaynak ve dahili dosya yolları 404/403 döner. Bu kontrol gerçek dağıtım üzerinden de yapılır.

### 2. Gerçek hesapların birbirinden ayrılmasını güvenceye al

- [ ] Bootstrap admin atamasını kontrollü sahiplik doğrulamasına bağla; herkese açık kayıt akışı tek başına admin oluşturamasın.
- [ ] Auth yanıtında sabit kullanıcı kimliğini kullan; cihaz verilerini bu kimlikle ayır.
- [ ] Oturum süresi dolması, kullanıcı değişmesi ve başarısız oturum kontrolünde eski hesabın state'ini yeni hesaba yükleme.
- [ ] Misafir/eski cihaz verisinin içe aktarımını ayrı ve açık bir işlem yap; daha önce misafir kullanım kaldırıldıysa onu tekrar açma.
- [ ] Kullanıcı kendi profil/CV/başvuru/mülakat verilerine erişebilsin; diğer kullanıcı verisi hiçbir cihaz/sunucu birleşimiyle görünmesin.

**Bitti sayılması:** A→oturum süresi dolması→B girişi, iki tarayıcı/iki cihaz, admin e-postasıyla izinsiz kayıt ve olağan giriş/çıkış senaryoları geçer. A'nın hiçbir kişisel verisi B'ye taşınmaz.

### 3. Sahte veriyi kalıcı olarak geliştirme ortamına ayır

- [ ] 22 mockup ilan ve 20 fake hesap üreticisini üretim paketinden çıkar; testlerde gerekiyorsa izole fixture olarak tut.
- [ ] Bütün `*.json`/`@example.com`/başvuru tablolarını hedefleyen eski purge komutlarını prod kullanımından kaldır.
- [ ] Gerekliyse test verisine `is_test`/`seed_batch`/köken etiketi ekle; sıradan kullanıcı ve ilan akışından dışla.
- [ ] Denetim eklerindeki tam kimlikleri üretim kayıtlarıyla **yalnızca okuyarak** eşleştir; gerçek şirket adına göre silme yapma.
- [ ] Eski sayısal job kimliklerinde başlık/şirket/kaynak kanıtıyla çakışma kontrolü yap.
- [ ] Bulunan hedef kayıtlar için ilişki sayımı ve geri yüklenebilir yedek hazırla. Gerçek CV/not/başvuru korunması gerekenleri listede göster.
- [ ] Hedefli temizliği uygula; tarayıcıdaki eski örnek kayıtlar için yalnızca bilinen kimlikleri kapsayan migrasyon oluştur.
- [ ] Seed rehberlerini ve eski veri kaynağı açıklamalarını güncelle.

**Bitti sayılması:** prod paketinde fake üretici yoktur; kesin örnek kayıtlar normal kullanıcı listesi/analitik/ilan akışına girmez; gerçek kayıt sayımları beklenen biçimde korunur. Mevcut yerel ilan temizliği tekrar yapılacak iş sayılmaz; sonucu doğrulanır.

### 4. Job AI'dan gerçek ve başvurulabilir ilan akışını tamamla

- [ ] Mevcut erişimle sunucu tarafı Job AI bağlantısını doğrula; anahtarı tarayıcıya gönderme.
- [ ] Kaynak kimliği, başvuru URL'si, unvan, şirket, ülke/şehir, çalışma tipi, deneyim, gereksinimler ve kaynak tarihlerini tek sözleşmede tanımla.
- [ ] Yayın tarihi, ilk görülme, son görülme ve son kontrol tarihlerini ayır. Eksik veriyi “şimdi/ofiste” gibi uydurulmuş değere dönüştürme.
- [ ] Detayı eksik/kalitesi yetersiz/URL'siz ilanların vitrindeki görünürlük ve başvuru durumlarını açıkça belirle.
- [ ] Kaynakta kapanan/silinen ilanları önerilerden çıkar; kullanıcının geçmişini açıklamalı koru.
- [ ] Eski yerel ingest ve yönetim sayacı yollarını yeni gerçek kaynağa bağla veya devreden çıkar.
- [ ] Servis kesintisi, timeout, kaynakta geçersiz kayıt ve çok sayfalı liste davranışlarını test et; örnek veriye fallback ekleme.

**Bitti sayılması:** kontrollü kaynak ekle/güncelle/kaldır akışı sitede doğru görünür; gerçek kaynağın sayısıyla yönetim sayacı tutarlıdır; kesintide sahte ilan çıkmaz.

### 5. Kişisel profil ve açıklanabilir eşleşme

- [ ] Kayıt/giriş sonrası eksik profil için kısa ve anlaşılır kurulum sun.
- [ ] Hedef meslek/rol, mevcut beceriler, deneyim, çalışma tipi, konum/uzaktan çalışma ve temel zorunlu şartları topla.
- [ ] CV ayrıştırmasını kullanıcıya onaylat; çıkarım ile kişinin onayladığı bilgi ayrı tutulabilsin.
- [ ] Boş aday veya yetersiz ilan verisinde yüksek yüzde üretme; eksik bilgi/güven durumu göster.
- [ ] Konum, rol, kıdem ve zorunlu koşulları eşleşmede gerçek girdiler haline getir.
- [ ] Frontend, haftalık e-posta, yol haritası ve analitik için aynı sürümlü eşleşme sözleşmesini kullan.
- [ ] “Uygun”, “eksik”, “zorunlu şart karşılanmıyor” gerekçelerini açıkla; yüzdeyi işe alınma ihtimali gibi sunma.

**Bitti sayılması:** boş profil yüksek eşleşme almaz; bilinen zorunlu koşul eksikliği bütün kanallarda aynı sonucu verir; konum tercihi sonuçları değiştirir; uygun iş yoksa açıkça belirtilir.

### 6. Gerçek ilan eylemleri ve doğru başvuru takibi

- [ ] “Doğrulanmış” rozetini gerçek bir doğrulama kaydıyla koşullandır; böyle bir süreç yoksa kaynak/son kontrol bilgisini göster.
- [ ] “İlana git” ve “Başvurdum” eylemlerini ayır.
- [ ] URL'siz/uygunsuz URL'li ilanda yönlendirme veya applied kaydı üretme.
- [ ] Kullanıcının açık teyidini, kaynak sayfasına gitme olayından ayrı sakla.
- [ ] Elle girilen görüşme/teklif durumlarını işveren teyidi olarak etiketleme.

**Bitti sayılması:** kaynak sayfasını açmak başvuruldu sayılmaz; kullanıcı teyidi gerçek hesabına kaydolur; geçerli URL'ye doğru yönlendirilir.

### 7. Öğrenme ve mevcut yetkinlikleri ayır

- [ ] Öğrenilecek beceri listesi oluştur; “Harekete geç” bu listeye/çalışma planına götürsün.
- [ ] Mevcut beceri ve CV'ye ekleme ancak kullanıcının ayrı, anlamı açık beyanıyla yapılsın.
- [ ] Yol haritasında kazanılmış beceri ile hedef beceriyi farklı göster.
- [ ] Kurs kataloglarını doğrulanmış kurs ve eğitim arama önerisi olarak ayır; süreleri tahmin diye belirt.

**Bitti sayılması:** “Python öğren”e tıklamak CV'ye Python yazmaz; eğitim hedefi olarak görünür. Skor yalnızca mevcut yetkinlik değişince güncellenir.

### 8. CV, başvuru paketi ve mülakatı gerçekte çalışır hale getir

- [ ] Başvuru paketini CSRF başlıklı ortak API yardımcısına geçir.
- [ ] `experienceEntries`/`experience` uyumsuzluğunu ve eğitim/sertifika şema farklarını düzelt.
- [ ] Uyarlanmış CV'yi önizlemeli ayrı sürüm üretimiyle koru; temel CV sessizce ezilmesin.
- [ ] Docling bağımlılığını gerçek dağıtımda doğrula; bozuk dosya, taranmış PDF ve servis yokluğu doğru hataya dönüşsün.
- [ ] CV doluluk puanını ATS uygunluk garantisi gibi sunma.
- [ ] Gerçek AI değerlendirmesi, kurallı değerlendirme ve hesaplanan yardımcı metrikleri yöntemleriyle göster.
- [ ] Video kaydının kapsamını doğru anlat; görüntü/telaffuz analizi yapılmıyorsa böyle bir iddia kullanma.

**Bitti sayılması:** gerçek kullanıcının güncel CV deneyimleri pakete gider; istek 403 olmaz; hata sırasında uydurma AI sonucu verilmez; eski CV korunur.

### 9. Kayıt, çok cihazlı kullanım ve e-posta

- [ ] Profil/başvuru/CV için kaydediliyor, sunucuda kaydedildi, hata/yeniden deneme durumlarını göster.
- [ ] HTTP başarısızlıklarını kontrol et; yerel başarı ile sunucu başarısını ayır.
- [ ] Eşitlemede güncelleme/silme çatışmalarını çöz; silinen kayıt tekrar gelmesin.
- [ ] Profil çekilince kimlik, skorlar, öneriler ve diğer ilgili ekranları birlikte yenile.
- [ ] Gerçek gönderici alanı, Resend erişimi, link taban adresi ve teslim hatası takibini doğrula.
- [ ] Mail yoksa doğrulama/şifre sıfırlama akışının tamamlanmış sayılmasını engelle; işletim tarafında yeniden deneme kur.
- [ ] Gerçek tokenlı e-posta içeriğini loglama davranışını kaldır.

**Bitti sayılması:** iki cihazda veri kalıcı ve tutarlı; sunucu kayıt hatası görünür; gerçek doğrulama ve sıfırlama e-postaları doğru HTTPS bağlantısıyla teslim edilir.

### 10. Görsel ve vaat temizliği

- [ ] Sabit Yetenek Ağı'nı veri temelli çiz veya dekoratif görsel olarak sadeleştir.
- [ ] Hızlı asistanı mevcut kısayol işleviyle doğru adlandır; gerçek konuşma yokken AI danışman vaadi verme.
- [ ] Maaş tahminindeki sabit %10 artışı kaldır; doğrulanmış veri varsa dönem/para birimi/konum/örneklemle göster.
- [ ] Sunumdaki potansiyel değerleri ölçülmüş başarıya dönüştürme; gerçek sonuçlar oluşana kadar hedef olarak açık tut.
- [ ] İlk yayında işlevi olmayan ücretli/işveren rol seçeneklerini kullanıcı akışından kaldır veya erişime kapat.
- [ ] Mevcut gerçek eğitim içeriklerini, testleri ve demo temizleyen migrasyonu koru.

**Bitti sayılması:** görünen her sayı/rozet/özellik gerçek veri, açıklanan hesap veya açıkça adlandırılmış hedef/örnek içerikle eşleşir.

### 11. Kullanıcıya gösterilen metinleri gerçek ürüne uydur

- [ ] Gerçek işletmeci unvanı/adresi ve destek/başvuru e-postasını yerleştir.
- [ ] Mülakat transcript'inin gerçekten saklandığını ve erişim/silme davranışını doğru açıkla; aksi yönde ürün kararı varsa kodu o karara göre değiştir.
- [ ] CV, başvuru paketi ve mülakatın hangi veriyi hangi AI işlemine gönderdiği kullanıcıya açık olsun.
- [ ] Kullanıcının verdiği onayı kullanılan metin sürümü/zamanıyla kaydet.
- [ ] Hesap silme/dışa aktarma ve saklama temizliklerini güncel veri modeline karşı kontrol et.

**Bitti sayılması:** yayımlanan metinde şirket/iletişim yer tutucusu yoktur; belgeler ile test edilmiş saklama davranışı çelişmez.

### 12. Yayın ve pilot kabulü

- [ ] Son kaynak sürümünde JS ve backend testlerini çalıştır; yeni davranışların anlamlı regresyon testlerini ekle.
- [ ] Postgres migrasyonlarını mevcut veri kopyasında doğrula; gerçek veri üzerinde deney yapma.
- [ ] Uçtan uca tarayıcı testi: kayıt→doğrulama→profil/CV→kişisel ilan→başvuru hazırlığı→gerçek URL→teyit→başka cihazda görüntüleme.
- [ ] Güvenlik kabulü: doğrulanmamış admin, hesap değiştirme, kaynak dosyası erişimi ve kullanıcılar arası yetki kontrolleri.
- [ ] Kesinti kabulü: Job AI/mail/AI/DB hatalarında doğru ekran; sahte başarı/fake içerik yok.
- [ ] Yedekten geri dönüş ve son sürüme ait sağlık/teslim izleme hazır olsun.
- [ ] Dağıtımın yalnızca yetki verilmiş adımlarını uygula; gerekiyorsa yayın onayı için tamamlanmış sürüm ve sonuçları sun.
- [ ] Küçük bir gerçek kullanıcı pilotunda uygun iş, yanlış eşleşme ve kullanılamayan bağlantı geri bildirimlerini topla.

**Bitti sayılması:** bir kişi kendi hesabı ve gerçek bilgileriyle baştan sona akışı tamamlar; kendi verisini başka cihazda bulur; gerçekten başvurulabilir uygun işlere ulaşır. Görüşme/teklif sonucu kullanıcı beyanı veya doğrulanmış kaynak olarak ayrı ölçülür; işe girme garantisi verilmez.

### Sizin adım adım yapmanız gerekenler

**Bu liste yalnızca sizin kararınızı veya size ait bir hesaba erişimi gerektirebilecek işleri içerir. Kod düzenleme, test, SQL yazma, dosya taşıma ve sunucu komutlarını çalıştırma işi size bırakılmıyor.** Mevcut bağlantı/anahtar/hesap hazırsa ilgili maddeyi yeniden yapmanız gerekmiyor.

1. **Hesap sahibi ve işletmeci bilgisini netleştirin.** Yetkili admin e-postası, ürünün gerçek işleticisinin adı/unvanı, gerekiyorsa adresi ve kullanıcının ulaşacağı destek e-postası gerekli. Bunlar sizin adınıza uydurulamaz.
2. **İlk kapsamı teyit edin veya değiştirin.** Önerilen başlangıç: bireysel iş arayan aday; mevcut gerçek ilan kapsamı; ücretsiz kayıt; gerçek ilana yönlendirme ve manuel başvuru teyidi. Ücretli Pro, işveren işe alım paneli ve otomatik başvuru gönderimini ilk sürüm vaadine eklemiyoruz. Farklı bir ticari kapsam istiyorsanız bu karar sizden gelmeli.
3. **Yalnızca mevcut değilse servis hesabı/alan adı erişimini sağlayın.** Job AI API erişimi, OpenRouter hizmeti ve gerçek e-posta gönderimi için kullanılacak hesap sizin kontrolünüzde olmalı. Alan adı doğrulaması veya hesap açma/ödeme işlemi gerekiyorsa kendi servis panelinizde tamamlayın; bağlantı ve teknik doğrulamayı ben yaparım. Anahtarları sohbet metnine yazmak yerine güvenli ayar alanına girin. Çalışan mevcut erişimler yeniden istenmez.
4. **Yayımlanacak işletmeci ve veri davranışını onaylayın.** Transcript saklanacak mı gibi ürün kararlarında son gerçek davranış size açıkça sunulur; kullanıcı metinlerinde yer alacak gerçek bilgileri teyit edin. Hukuki inceleme gerektiren işletmeci kararlarını sizin adınıza alamam.
5. **Hedefli canlı temizlik gerekirse somut listeyi inceleyin.** Size “bütün test verilerini silelim” gibi belirsiz bir onay sunulmaz. Önce kesin kayıtlar, sayılar, ilişkiler ve korunacak veriler hazırlanır. Gerçek kayıt kaybı riski olan kalıcı işlem için yalnızca bu hazır liste üzerinden karar verirsiniz.
6. **Teknik kabul tamamlanınca kendi e-posta kutunuzla bir gerçek deneme yapın.** Gelen doğrulama/sıfırlama e-postasının alındığını, kendi profilinizin doğru anlaşıldığını ve önerilen ilanların size uygunluğunu kontrol edin. Kendi CV'nizi yüklemek sizin tercihinizdir; teknik testler bunun öncesinde izole verilerle tamamlanır.

Bu aşamada sizden teknik kurulum yapmanız veya sır/şifre göndermeniz istenmiyor. Uygulama başlamadan önce eksik olduğu gerçekten görülen bilgi/erişimler, ilgili aşamada tek bir kısa listede toplanabilir.
