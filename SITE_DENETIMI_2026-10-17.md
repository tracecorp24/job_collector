**Linko site ve veri toplama denetimi — 17 Ekim 2026**

Canlı site tarayıcıdan, veri akışı kaynak koddan, yerel SQLite ve JSON havuzları salt okunur olarak incelendi. Hatalar ayrı geçici veritabanlarında ve yerel test sunucusunda yeniden üretildi. Canlı sitede gözlem sırasında 419, yerel veritabanında 381 ilan vardı; aşağıdaki yerel sayılar canlı veritabanının sayıları değildir. Çalışma dizininde başka değişiklikler devam ettiği için bulgular, yeniden üretme dosyalarının çalıştırıldığı durum ve belirtilen canlı gözlemler için geçerlidir.

**Konum sorununun kök nedeni**

Birbirinden ayrı üç sorun var:

1. **Eski ayrıştırıcı doğru ham konumu bozmuş.** Hesapsız LinkedIn kartı zaten `[unvan, şirket, konum]` şeklinde çıkarılıyor. `parse_card()` konumu satır sırasından almak yerine ülke kelimeleri, virgül ve çalışma biçimi üzerinden tahmin ediyor. `Ümraniye`, `Sarıyer`, `Greater Istanbul` gibi değerleri tanımıyor. `AXA Türkiye`, `Honda Türkiye A.Ş.` veya virgüllü şirket adını ise konum sanıyor; bu durumda şirket alanı da boş kalıyor. Sorun bu örneklerde HTML'den çekme aşamasında değil, sonraki ayrıştırma aşamasında.
2. **Doğru ayrıştırılan kaynak kartı da doğrulanmış iş konumu anlamına gelmiyor.** Canlı sitedeki `4468009911` kaynak kimlikli National Laboratory of the Rockies ilanında konum `Ümraniye`; aynı ilanın açıklamasındaki konum alanı `CO - Golden`. Yerel ham veri de aynı uyuşmazlığı içeriyor. Kazıyıcı karttaki konumu aynen alıyor; detaydan yalnızca açıklamayı çekiyor. Kart, detay ve varsa yapılandırılmış iş konumu arasında kontrol yapılmıyor. Bunun işveren dağıtım ayarından mı, kaynaktaki kart bilgisinden mi geldiği bu kayıtla kesinleştirilemez. İlan uzaktan çalışma içerdiği için açıklamadaki yeri körlemesine kartın üzerine yazmak da doğru çözüm olmaz.
3. **Şehir/ilçe normalleştirmesi yok.** Canlı konum filtresi aynı bölgeyi `İstanbul, Türkiye` 165, `İstanbul` 82 ve `Greater Istanbul` 69 olarak ayırıyor; ilçeler ayrıca listeleniyor. Filtre SQL'de tam metin eşitliği kullanıyor. Dolayısıyla İstanbul seçimi tüm İstanbul ilanları anlamına gelmiyor. Aranan konum ile ilan konumu ayrı tutulmuş, fakat ilan konumunun şehir/ilçe/ülke bileşenleri yok.

| Yerel veri kontrolü | Sonuç |
| --- | ---: |
| Toplam ilan | 381 |
| Ham karta göre şirket veya konumu yanlış ilan | 249 (%65,4) |
| Konumu boş ilan | 219 |
| Şirketi boş, şirket adı konuma kaymış ilan | 30 |
| İncelenen JSON ilan kopyası | 542 |
| JSON ile SQLite konumu farklı kopya | 364 |
| Mevcut onarım geçici DB kopyasına uygulandıktan sonra kalan alan hatası | 0 |
| Onarımdan sonra JSON/DB konum farkı | 0 |

Kodda `parse_guest_card()` ve `_repair_guest_card_fields()` düzeltmeleri zaten bulunuyor. Yerel DB'de `repair_guest_card_fields_v1` işareti yok; onarım bu dosyaya henüz uygulanmamış. Canlı konum filtresindeki 419 ilanın tamamında konum mevcut, eski şirket/konum kayması o görünümde yok. Dolayısıyla yerel dosyadaki eski bozuk kayıtlar ile canlıdaki kaynak uyuşmazlığını karıştırmamak gerekiyor.

Ek kalıcılık problemi: artımlı tarama, kart ve açıklama aynıysa `process_raw()` çağrısını atlıyor. Ayrıştırıcı sürümü ve türetilmiş alanların doğruluğu karşılaştırılmıyor. Geçici deneyde ham konumu `Maltepe`, DB konumu boş olan ilan tekrar tarandığında `unchanged=1` döndü ve konum boş kaldı. Sadece tekrar taramak her veri düzeltmesini uygulamaz.

Dayanak: [parse.py](jobapp/parse.py), [accountless.py](jobapp/scraper/accountless.py), [db.py](jobapp/db.py), [pipeline.py](jobapp/pipeline.py), [filters.py](jobapp/filters.py).

**Öncelikli diğer hatalar**

| Öncelik | Bulgu ve kanıt | Etki ve düzeltme yönü |
| --- | --- | --- |
| Yüksek | **Canlı olay bağlantıları HTTP kapasitesini tüketiyor.** `/events` sonsuz SSE döngüsü; üretimde Waitress `threads=12`. İzole sunucuda 2 iş parçacığına 2 SSE bağlantısı açıldı; önce HTTP 200 dönen ilan API'si sonrasında zaman aşımına girdi. | Yeterli sekme/kullanıcı siteyi yanıtsız bırakabilir. Tek collector sürecini koruyarak SSE'yi uygun asenkron katmanda yönetmek veya mevcut kısa durum sorgularını geçici çözüm olarak kullanmak gerekir. Sadece daha fazla iş parçacığı eklemek sınırı erteler. |
| Yüksek | **Detayı alınamayan ilan tamamlanmış sayfada kaybolabiliyor.** Detay HTML'sinde açıklama seçicisi bulunmayınca ilan `seen` listesine ekleniyor. Deneyde 1 kart, 1 detay hatası, 0 kayıt olmasına rağmen görev `finished` oldu. | Seçici değişikliği veya geçici detay problemi eksik sonuç üretir. Geçici başarısızlıkları ayrı bekleyen listede tutmak; 404/410 ile ayrıştırma/ağ hatalarını ayırmak gerekir. Logda hata var, fakat görevin tamamlanma durumu eksikliği gidermiyor. |
| Yüksek | **Deneyim şirket yaşından çıkarılıyor.** Canlı Monster Notebook ilanı 26 yıl gösteriyor; şirket tanıtımı 26 yıllık faaliyetini, nitelikler ise 5 yıllık deneyim şartını anlatıyor. Regex ilk Türkçe yıl sayısını alıyor. `3 years of experience` için sonuç boş; `3–5` aralığının düz tireli örneğinde sonuç 5. | Deneyim filtresi uygun adayları/ilanları yanlış eler. Nitelik ve deneyim bağlamını önceliklendirmek, İngilizceyi ve alt/üst sınırları desteklemek gerekir. |
| Orta | **Kıdem alt kelimeyle eşleşiyor.** Canlı `Machine Learning Engineer at International Startup` ilanı stajyer. `Internal Auditor` da aynı sonuç veriyor; sebep `intern` alt dizisi. | Tam kelime/sınırlı kalıp eşleşmesi ve unvan öncelikleri gerekli. |
| Orta | **Maaş kaynaktan çıkarılmıyor.** Yerel 381 ilanın maaşı boş. National Laboratory açıklamasında 44.500–71.200 USD yıllık aralık var. Kural sınıflandırıcısı maaşı sürekli boş döndürüyor; `salary.parse_salary()` yalnızca bu boş alanı işliyor. | Maaş filtresi/sıralaması kaynakta mevcut veriyi kullanamıyor. Açıklamanın maaş bölümünü önce deterministik olarak çıkarmak gerekir. Her ilanda maaş bulunduğu iddia edilmiyor. |
| Orta | **DB ve JSON farklı çıkarım kuralları kullanıyor.** Aynı “not a remote … onsite” metni DB tarafında Onsite, JSON tarafında Remote. Belirsiz çalışma tipi JSON'da Office varsayılıyor. `PLC SCADA MATLAB AutoCAD` metni JSON'da dört yetenek, DB'de sıfır etiket üretiyor. | Sitedeki filtreler ile dışa aktarılan havuz aynı şeyi temsil etmiyor. Tek ortak alan çıkarımı, olumsuzluk kontrolü ve bilinmeyen değeri koruma gerekli. |
| Orta | **İstek türleri yeterince doğrulanmıyor.** `/api/queue` ve `/api/scrape` uçlarına JSON listesi gönderildiğinde HTTP 500. `task_data({keywords: "AI", locations: "Berlin"})` 12 harf kombinasyonu oluşturuyor. | Entegrasyon hatası anlamsız taramaları tetikleyebilir. Gövdenin nesne, unvan/konumların liste ve öğelerin uygun tür olduğunu görev oluşturmadan doğrulamak gerekir. `/api/watches` nesne olmayan gövdeyi doğru biçimde 400 ile reddediyor. |
| Orta | **Listeleme büyüdükçe pahalılaşıyor.** Sayfalama öncesinde tüm eşleşen ilan kimlikleri belleğe alınıyor. Her `Job.to_dict()` ayrıca arama ilişkisi sorguluyor. İzole 31 kayıtta 24 ilanlık sayfa 26 SQL sorgusu yaptı. | Normal sıralamada SQL LIMIT/OFFSET veya cursor; ilişkilerde toplu yükleme gerekir. 419 ilandaki hız, büyük havuzdaki performansı garanti etmez. |
| Orta | **Geçmişi kalıcı silme, değişiklik akışını güncellemiyor.** Testte ilan korunup arama ilişkisi kaldırıldı; ilanın `search_ids=[]` oldu, fakat `job_changes` tablosuna yeni olay yazılmadı. İlişki için yalnızca INSERT tetikleyicisi var. | API tüketicilerinin geçmiş/arama ilişkileri eski kalır. İlişki DELETE/UPDATE değişikliklerinin de aynı işlemde olaya dönüşmesi gerekir. Bu deneme yalnızca geçici veride yapıldı. |
| Düşük | **Konum sonundaki her parantez siliniyor.** `Frankfurt (Oder)` girdisi `Frankfurt` oluyor; temizleyici sadece çalışma biçimi parantezleriyle sınırlı değil. Ayrıca şirketi boş guest kart `quality_ok=True` kabul edilirken JSON dışa aktarma bunu reddediyor. | Bilinen çalışma biçimi eklerini temizlemek ve minimum kalite sözleşmesini ortaklaştırmak gerekir. |
| Düşük | **Groq anahtarının serbest metinde gizlenmesi eksik.** Sahte anahtarla `audit.clean()` denemesinde `msg` içindeki değer gizlenmedi; serbest metin yalnızca Anthropic anahtarını temizliyor. | Gerçek anahtar sızıntısı gözlemlenmedi. Tüm yapılandırılmış gizli değerler ve başlık biçimleri ortak temizlemeden geçirilmeli. |

**Düzeltme sırası**

1. SSE kaynaklı servis tıkanmasını ve başarısız detayların tamamlanmış sayılmasını düzeltmek.
2. Doğru DB dosyasını yedekleyip eski konum onarımını uygulamak; kaynak konum uyuşmazlığını ayrıca işaretlemek. Mevcut onarımın kopyada 249 kaydı düzeltmesi, yeniden LinkedIn taraması gerekmeyen bir çözüm olduğunu gösteriyor.
3. Ham konumu koruyup şehir/ilçe/ülke, kaynak ve güven/uyuşmazlık alanlarını eklemek. Aranan şehri ilanın gerçek konumu olarak doldurmamak.
4. Deneyim, kıdem, maaş, çalışma tipi ve yetenek çıkarımını ortaklaştırıp mevcut kayıtları ağ isteği olmadan yeniden işlemek. Artımlı karşılaştırmaya ayrıştırma/işleme sürümü eklemek.
5. İstek doğrulama, ilişki değişiklik akışı ve listeleme sorgularını düzeltmek; her bulguyu davranış testiyle sabitlemek.

**Doğrulama ve yeniden üretme**

İlk test çalışmasında 79, inceleme sonundaki çalışmada 87 test geçti. Bu, yukarıdaki yeni örneklerin doğru işlendiği anlamına gelmiyor. SQLite bütünlük kontrolü `ok`; yerel veride yinelenen ilan, yetim ilan/görev ilişkisi ve geçersiz ham JSON bulunmadı. Canlı tarayıcıda incelenen görünümde JavaScript hata/uyarı kaydı yoktu. Kaynağın HTTP 429 bekleme durumu görünürdü; bu tek başına uygulama hatası değil ve denetim sırasında bekleme politikası değiştirilmedi.

- [Veri ve davranış denetimi](.qa/root_cause_audit_20261017.py) — salt okunur özgün DB, onarım için geçici kopya, sahte HTTP yanıtları.
- [Makinece okunabilir bulgular](.qa/root_cause_audit_20261017.json).
- [SSE kapasite deneyi](.qa/sse_capacity_probe_20261017.py) ve [sonucu](.qa/sse_capacity_probe_20261017.json) — geçici DB, yalnızca yerel HTTP, 2 iş parçacığı.
- [Test çalışması kaydı](.qa/unit_tests_audit_20261017.log).

Canlı DB'ye doğrudan erişilmedi; canlı arka uçtaki tüm kayıtlar, kimlik doğrulamasız dış erişim ve dağıtım yapılandırmasının sunucudaki gerçek hali doğrulanmış sayılmamalı. Bulguların hiçbiri canlıda veri silme veya yeni tarama başlatma yoluyla test edilmedi.
