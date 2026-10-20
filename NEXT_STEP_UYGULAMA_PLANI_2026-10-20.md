# NextStep — tüm bulguları kapatma ve gerçek kullanıcıya açılma planı

Bu belge bir **uygulama planıdır**; aşağıdaki kutular tamamlanmış iş olarak işaretlenmemiştir. Temel rapor: [26 bulguluk denetim](NEXT_STEP_GERCEK_URUN_DENETIMI_2026-10-20.md).

Hedef akış: **kayıt ve doğrulama → aday profilini anlama → güncel ve başvurulabilir uygun işler → CV/başvuru hazırlığı → gerçek ilan sayfasına yönlendirme → kullanıcının teyit ettiği başvuruyu takip**.

Teknik uygulama, migrasyon, test, dağıtım hazırlığı ve işletim kontrolü benim yapabileceğim işlerdir. Sizden gereken bilgiler en sondaki kısa listededir. Önceki oturumlarda verilmiş erişim ve yetkiler tekrar istenmez.

## Uygulama sırası

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

## 0. Güncel çalışma tabanını sabitle

- [ ] Başka oturumların son commit ve yerel değişikliklerini belirleyip tek uygulama tabanında birleştir.
- [ ] Sonradan yapılan Job AI ve kayıt/giriş değişikliklerini koru; eski dosya havuzunu geri getirme.
- [ ] Mevcut prod sürümü, yapılandırma adları, veritabanı sürümü ve geri dönüş yolu kaydedilsin; sır değerleri rapora yazılmasın.
- [ ] Üretimde yalnızca okunur sayım al: gerçek/fake adayları, ilan kaynakları, başvuru ve CV ilişkileri.

**Bitti sayılması:** hangi commit'in düzeltildiği ve hangi veri üzerinde işlem yapılacağı nettir. Başka çalışma ezilmemiştir.

## 1. Yalnızca yayımlanacak dosyaları webden erişilebilir yap

- [ ] Statik dosyalar için ayrı bir public kök veya açık izinli klasörler kullan.
- [ ] `app/`, `tools/`, `tests/`, `.git/`, sır, log, veritabanı ve yedek yollarını HTTP üzerinden kapat.
- [ ] Docker/dağıtım paketine yalnızca gereken dosyaları al; `.gitignore` korumasını web erişim kontrolü olarak kullanma.
- [ ] Mevcut kaynak erişiminin canlıdaki durumunu içerik/sır göstermeden kontrol et. Gerçekten açığa çıkmış bir sır bulunursa ilgili anahtarın rotasyonunu gerçekleştir.

**Bitti sayılması:** CSS/JS/gerekli belgeler çalışır; kaynak ve dahili dosya yolları 404/403 döner. Bu kontrol gerçek dağıtım üzerinden de yapılır.

## 2. Gerçek hesapların birbirinden ayrılmasını güvenceye al

- [ ] Bootstrap admin atamasını kontrollü sahiplik doğrulamasına bağla; herkese açık kayıt akışı tek başına admin oluşturamasın.
- [ ] Auth yanıtında sabit kullanıcı kimliğini kullan; cihaz verilerini bu kimlikle ayır.
- [ ] Oturum süresi dolması, kullanıcı değişmesi ve başarısız oturum kontrolünde eski hesabın state'ini yeni hesaba yükleme.
- [ ] Misafir/eski cihaz verisinin içe aktarımını ayrı ve açık bir işlem yap; daha önce misafir kullanım kaldırıldıysa onu tekrar açma.
- [ ] Kullanıcı kendi profil/CV/başvuru/mülakat verilerine erişebilsin; diğer kullanıcı verisi hiçbir cihaz/sunucu birleşimiyle görünmesin.

**Bitti sayılması:** A→oturum süresi dolması→B girişi, iki tarayıcı/iki cihaz, admin e-postasıyla izinsiz kayıt ve olağan giriş/çıkış senaryoları geçer. A'nın hiçbir kişisel verisi B'ye taşınmaz.

## 3. Sahte veriyi kalıcı olarak geliştirme ortamına ayır

- [ ] 22 mockup ilan ve 20 fake hesap üreticisini üretim paketinden çıkar; testlerde gerekiyorsa izole fixture olarak tut.
- [ ] Bütün `*.json`/`@example.com`/başvuru tablolarını hedefleyen eski purge komutlarını prod kullanımından kaldır.
- [ ] Gerekliyse test verisine `is_test`/`seed_batch`/köken etiketi ekle; sıradan kullanıcı ve ilan akışından dışla.
- [ ] Denetim eklerindeki tam kimlikleri üretim kayıtlarıyla **yalnızca okuyarak** eşleştir; gerçek şirket adına göre silme yapma.
- [ ] Eski sayısal job kimliklerinde başlık/şirket/kaynak kanıtıyla çakışma kontrolü yap.
- [ ] Bulunan hedef kayıtlar için ilişki sayımı ve geri yüklenebilir yedek hazırla. Gerçek CV/not/başvuru korunması gerekenleri listede göster.
- [ ] Hedefli temizliği uygula; tarayıcıdaki eski örnek kayıtlar için yalnızca bilinen kimlikleri kapsayan migrasyon oluştur.
- [ ] Seed rehberlerini ve eski veri kaynağı açıklamalarını güncelle.

**Bitti sayılması:** prod paketinde fake üretici yoktur; kesin örnek kayıtlar normal kullanıcı listesi/analitik/ilan akışına girmez; gerçek kayıt sayımları beklenen biçimde korunur. Mevcut yerel ilan temizliği tekrar yapılacak iş sayılmaz; sonucu doğrulanır.

## 4. Job AI'dan gerçek ve başvurulabilir ilan akışını tamamla

- [ ] Mevcut erişimle sunucu tarafı Job AI bağlantısını doğrula; anahtarı tarayıcıya gönderme.
- [ ] Kaynak kimliği, başvuru URL'si, unvan, şirket, ülke/şehir, çalışma tipi, deneyim, gereksinimler ve kaynak tarihlerini tek sözleşmede tanımla.
- [ ] Yayın tarihi, ilk görülme, son görülme ve son kontrol tarihlerini ayır. Eksik veriyi “şimdi/ofiste” gibi uydurulmuş değere dönüştürme.
- [ ] Detayı eksik/kalitesi yetersiz/URL'siz ilanların vitrindeki görünürlük ve başvuru durumlarını açıkça belirle.
- [ ] Kaynakta kapanan/silinen ilanları önerilerden çıkar; kullanıcının geçmişini açıklamalı koru.
- [ ] Eski yerel ingest ve yönetim sayacı yollarını yeni gerçek kaynağa bağla veya devreden çıkar.
- [ ] Servis kesintisi, timeout, kaynakta geçersiz kayıt ve çok sayfalı liste davranışlarını test et; örnek veriye fallback ekleme.

**Bitti sayılması:** kontrollü kaynak ekle/güncelle/kaldır akışı sitede doğru görünür; gerçek kaynağın sayısıyla yönetim sayacı tutarlıdır; kesintide sahte ilan çıkmaz.

## 5. Kişisel profil ve açıklanabilir eşleşme

- [ ] Kayıt/giriş sonrası eksik profil için kısa ve anlaşılır kurulum sun.
- [ ] Hedef meslek/rol, mevcut beceriler, deneyim, çalışma tipi, konum/uzaktan çalışma ve temel zorunlu şartları topla.
- [ ] CV ayrıştırmasını kullanıcıya onaylat; çıkarım ile kişinin onayladığı bilgi ayrı tutulabilsin.
- [ ] Boş aday veya yetersiz ilan verisinde yüksek yüzde üretme; eksik bilgi/güven durumu göster.
- [ ] Konum, rol, kıdem ve zorunlu koşulları eşleşmede gerçek girdiler haline getir.
- [ ] Frontend, haftalık e-posta, yol haritası ve analitik için aynı sürümlü eşleşme sözleşmesini kullan.
- [ ] “Uygun”, “eksik”, “zorunlu şart karşılanmıyor” gerekçelerini açıkla; yüzdeyi işe alınma ihtimali gibi sunma.

**Bitti sayılması:** boş profil yüksek eşleşme almaz; bilinen zorunlu koşul eksikliği bütün kanallarda aynı sonucu verir; konum tercihi sonuçları değiştirir; uygun iş yoksa açıkça belirtilir.

## 6. Gerçek ilan eylemleri ve doğru başvuru takibi

- [ ] “Doğrulanmış” rozetini gerçek bir doğrulama kaydıyla koşullandır; böyle bir süreç yoksa kaynak/son kontrol bilgisini göster.
- [ ] “İlana git” ve “Başvurdum” eylemlerini ayır.
- [ ] URL'siz/uygunsuz URL'li ilanda yönlendirme veya applied kaydı üretme.
- [ ] Kullanıcının açık teyidini, kaynak sayfasına gitme olayından ayrı sakla.
- [ ] Elle girilen görüşme/teklif durumlarını işveren teyidi olarak etiketleme.

**Bitti sayılması:** kaynak sayfasını açmak başvuruldu sayılmaz; kullanıcı teyidi gerçek hesabına kaydolur; geçerli URL'ye doğru yönlendirilir.

## 7. Öğrenme ve mevcut yetkinlikleri ayır

- [ ] Öğrenilecek beceri listesi oluştur; “Harekete geç” bu listeye/çalışma planına götürsün.
- [ ] Mevcut beceri ve CV'ye ekleme ancak kullanıcının ayrı, anlamı açık beyanıyla yapılsın.
- [ ] Yol haritasında kazanılmış beceri ile hedef beceriyi farklı göster.
- [ ] Kurs kataloglarını doğrulanmış kurs ve eğitim arama önerisi olarak ayır; süreleri tahmin diye belirt.

**Bitti sayılması:** “Python öğren”e tıklamak CV'ye Python yazmaz; eğitim hedefi olarak görünür. Skor yalnızca mevcut yetkinlik değişince güncellenir.

## 8. CV, başvuru paketi ve mülakatı gerçekte çalışır hale getir

- [ ] Başvuru paketini CSRF başlıklı ortak API yardımcısına geçir.
- [ ] `experienceEntries`/`experience` uyumsuzluğunu ve eğitim/sertifika şema farklarını düzelt.
- [ ] Uyarlanmış CV'yi önizlemeli ayrı sürüm üretimiyle koru; temel CV sessizce ezilmesin.
- [ ] Docling bağımlılığını gerçek dağıtımda doğrula; bozuk dosya, taranmış PDF ve servis yokluğu doğru hataya dönüşsün.
- [ ] CV doluluk puanını ATS uygunluk garantisi gibi sunma.
- [ ] Gerçek AI değerlendirmesi, kurallı değerlendirme ve hesaplanan yardımcı metrikleri yöntemleriyle göster.
- [ ] Video kaydının kapsamını doğru anlat; görüntü/telaffuz analizi yapılmıyorsa böyle bir iddia kullanma.

**Bitti sayılması:** gerçek kullanıcının güncel CV deneyimleri pakete gider; istek 403 olmaz; hata sırasında uydurma AI sonucu verilmez; eski CV korunur.

## 9. Kayıt, çok cihazlı kullanım ve e-posta

- [ ] Profil/başvuru/CV için kaydediliyor, sunucuda kaydedildi, hata/yeniden deneme durumlarını göster.
- [ ] HTTP başarısızlıklarını kontrol et; yerel başarı ile sunucu başarısını ayır.
- [ ] Eşitlemede güncelleme/silme çatışmalarını çöz; silinen kayıt tekrar gelmesin.
- [ ] Profil çekilince kimlik, skorlar, öneriler ve diğer ilgili ekranları birlikte yenile.
- [ ] Gerçek gönderici alanı, Resend erişimi, link taban adresi ve teslim hatası takibini doğrula.
- [ ] Mail yoksa doğrulama/şifre sıfırlama akışının tamamlanmış sayılmasını engelle; işletim tarafında yeniden deneme kur.
- [ ] Gerçek tokenlı e-posta içeriğini loglama davranışını kaldır.

**Bitti sayılması:** iki cihazda veri kalıcı ve tutarlı; sunucu kayıt hatası görünür; gerçek doğrulama ve sıfırlama e-postaları doğru HTTPS bağlantısıyla teslim edilir.

## 10. Görsel ve vaat temizliği

- [ ] Sabit Yetenek Ağı'nı veri temelli çiz veya dekoratif görsel olarak sadeleştir.
- [ ] Hızlı asistanı mevcut kısayol işleviyle doğru adlandır; gerçek konuşma yokken AI danışman vaadi verme.
- [ ] Maaş tahminindeki sabit %10 artışı kaldır; doğrulanmış veri varsa dönem/para birimi/konum/örneklemle göster.
- [ ] Sunumdaki potansiyel değerleri ölçülmüş başarıya dönüştürme; gerçek sonuçlar oluşana kadar hedef olarak açık tut.
- [ ] İlk yayında işlevi olmayan ücretli/işveren rol seçeneklerini kullanıcı akışından kaldır veya erişime kapat.
- [ ] Mevcut gerçek eğitim içeriklerini, testleri ve demo temizleyen migrasyonu koru.

**Bitti sayılması:** görünen her sayı/rozet/özellik gerçek veri, açıklanan hesap veya açıkça adlandırılmış hedef/örnek içerikle eşleşir.

## 11. Kullanıcıya gösterilen metinleri gerçek ürüne uydur

- [ ] Gerçek işletmeci unvanı/adresi ve destek/başvuru e-postasını yerleştir.
- [ ] Mülakat transcript'inin gerçekten saklandığını ve erişim/silme davranışını doğru açıkla; aksi yönde ürün kararı varsa kodu o karara göre değiştir.
- [ ] CV, başvuru paketi ve mülakatın hangi veriyi hangi AI işlemine gönderdiği kullanıcıya açık olsun.
- [ ] Kullanıcının verdiği onayı kullanılan metin sürümü/zamanıyla kaydet.
- [ ] Hesap silme/dışa aktarma ve saklama temizliklerini güncel veri modeline karşı kontrol et.

**Bitti sayılması:** yayımlanan metinde şirket/iletişim yer tutucusu yoktur; belgeler ile test edilmiş saklama davranışı çelişmez.

## 12. Yayın ve pilot kabulü

- [ ] Son kaynak sürümünde JS ve backend testlerini çalıştır; yeni davranışların anlamlı regresyon testlerini ekle.
- [ ] Postgres migrasyonlarını mevcut veri kopyasında doğrula; gerçek veri üzerinde deney yapma.
- [ ] Uçtan uca tarayıcı testi: kayıt→doğrulama→profil/CV→kişisel ilan→başvuru hazırlığı→gerçek URL→teyit→başka cihazda görüntüleme.
- [ ] Güvenlik kabulü: doğrulanmamış admin, hesap değiştirme, kaynak dosyası erişimi ve kullanıcılar arası yetki kontrolleri.
- [ ] Kesinti kabulü: Job AI/mail/AI/DB hatalarında doğru ekran; sahte başarı/fake içerik yok.
- [ ] Yedekten geri dönüş ve son sürüme ait sağlık/teslim izleme hazır olsun.
- [ ] Dağıtımın yalnızca yetki verilmiş adımlarını uygula; gerekiyorsa yayın onayı için tamamlanmış sürüm ve sonuçları sun.
- [ ] Küçük bir gerçek kullanıcı pilotunda uygun iş, yanlış eşleşme ve kullanılamayan bağlantı geri bildirimlerini topla.

**Bitti sayılması:** bir kişi kendi hesabı ve gerçek bilgileriyle baştan sona akışı tamamlar; kendi verisini başka cihazda bulur; gerçekten başvurulabilir uygun işlere ulaşır. Görüşme/teklif sonucu kullanıcı beyanı veya doğrulanmış kaynak olarak ayrı ölçülür; işe girme garantisi verilmez.

## Sizin adım adım yapmanız gerekenler

**Bu liste yalnızca sizin kararınızı veya size ait bir hesaba erişimi gerektirebilecek işleri içerir. Kod düzenleme, test, SQL yazma, dosya taşıma ve sunucu komutlarını çalıştırma işi size bırakılmıyor.** Mevcut bağlantı/anahtar/hesap hazırsa ilgili maddeyi yeniden yapmanız gerekmiyor.

1. **Hesap sahibi ve işletmeci bilgisini netleştirin.** Yetkili admin e-postası, ürünün gerçek işleticisinin adı/unvanı, gerekiyorsa adresi ve kullanıcının ulaşacağı destek e-postası gerekli. Bunlar sizin adınıza uydurulamaz.
2. **İlk kapsamı teyit edin veya değiştirin.** Önerilen başlangıç: bireysel iş arayan aday; mevcut gerçek ilan kapsamı; ücretsiz kayıt; gerçek ilana yönlendirme ve manuel başvuru teyidi. Ücretli Pro, işveren işe alım paneli ve otomatik başvuru gönderimini ilk sürüm vaadine eklemiyoruz. Farklı bir ticari kapsam istiyorsanız bu karar sizden gelmeli.
3. **Yalnızca mevcut değilse servis hesabı/alan adı erişimini sağlayın.** Job AI API erişimi, OpenRouter hizmeti ve gerçek e-posta gönderimi için kullanılacak hesap sizin kontrolünüzde olmalı. Alan adı doğrulaması veya hesap açma/ödeme işlemi gerekiyorsa kendi servis panelinizde tamamlayın; bağlantı ve teknik doğrulamayı ben yaparım. Anahtarları sohbet metnine yazmak yerine güvenli ayar alanına girin. Çalışan mevcut erişimler yeniden istenmez.
4. **Yayımlanacak işletmeci ve veri davranışını onaylayın.** Transcript saklanacak mı gibi ürün kararlarında son gerçek davranış size açıkça sunulur; kullanıcı metinlerinde yer alacak gerçek bilgileri teyit edin. Hukuki inceleme gerektiren işletmeci kararlarını sizin adınıza alamam.
5. **Hedefli canlı temizlik gerekirse somut listeyi inceleyin.** Size “bütün test verilerini silelim” gibi belirsiz bir onay sunulmaz. Önce kesin kayıtlar, sayılar, ilişkiler ve korunacak veriler hazırlanır. Gerçek kayıt kaybı riski olan kalıcı işlem için yalnızca bu hazır liste üzerinden karar verirsiniz.
6. **Teknik kabul tamamlanınca kendi e-posta kutunuzla bir gerçek deneme yapın.** Gelen doğrulama/sıfırlama e-postasının alındığını, kendi profilinizin doğru anlaşıldığını ve önerilen ilanların size uygunluğunu kontrol edin. Kendi CV'nizi yüklemek sizin tercihinizdir; teknik testler bunun öncesinde izole verilerle tamamlanır.

Bu aşamada sizden teknik kurulum yapmanız veya sır/şifre göndermeniz istenmiyor. Uygulama başlamadan önce eksik olduğu gerçekten görülen bilgi/erişimler, ilgili aşamada tek bir kısa listede toplanabilir.
