# Yapay zekâ hız önerileri — değerlendirme ve güncelleme planı (17 Ekim 2026)

**Sonuç:** Önerilerin **büyük çoğunluğu uygulanmayacak**. Üç şey yüzünden:
(1) önerilerin ana hedefi bekleme süresini kısaltıp kaynağa saatte 5–8 kat fazla istek atmak —
bu `CLAUDE.md` ve `SERVICE_PLAN.md` kurallarına doğrudan aykırı; (2) birçoğu LinkedIn'in
bot tespitini atlatmaya yönelik (TLS taklidi, IP döndürme, kova değiştirme, Google
yedek kanalı); (3) iyi görünen kalan kısmın çoğu **kodda zaten var**. Gerçekten işe yarayan
yalnızca iki küçük, düşük riskli değişiklik çıktı (bkz. "Güncelleme planı").

Bu belge yalnızca değerlendirme ve plan içerir; **kodda hiçbir değişiklik yapılmadı**.

## 1. Değerlendirme ölçütleri

1. Proje kuralları: bekleme/hız politikası gevşetilmez, güvenlik doğrulaması aşılmaz, tek
   collector süreci korunur, canlı veritabanıyla geriye uyumluluk.
2. Önerinin dayandığı iddia bu depoda **doğrulanabiliyor mu**? (Kod, kayıtlı gerçek yanıtlar, canlı log.)
3. Kod zaten bunu yapıyor mu?
4. Kazanç / risk / bakım maliyeti.

## 2. Önerinin dayandığı iddiaların doğrulanması

| İddia | Doğrulama | Sonuç |
| --- | --- | --- |
| "5–6 sn aralıkta 429 oranı düşer / `min_interval` 3,5–4 sn'ye çekilebilir" | Bugün canlı logda yine HTTP 429 var (`source_paused … remaining_seconds=960`). `TARAMA_VERIMLILIK_RAPORU` deneyinde 6 sn aralıkla 34 sn içinde 5. detayda 429 ve ardından liste isteğinde 429 görüldü. | **Yanlış.** 429, şimdiki aralıkta bile geliyor; sorun TLS değil, istek hızı. Aralığı kısaltmak sıklığı artırır. |
| "Saatte ~600 istek → 3.000–5.000" | Aralık 6 sn × (1 + 0–%30 pay) ≈ ortalama 6,9 sn ≈ **~520 istek/saat**. 3.000–5.000, 5–10 kat demek. | Hedef kural dışı; ayrıca dayanağı yok (hiçbir ölçüm yok). |
| "LinkedIn detay sayfalarına JSON-LD gömüyor" | `.qa/efficiency-20261017/live-immediate/responses.jsonl` içindeki gerçek detay yanıtlarında (200–276 KB) `application/ld+json` betiği **yok**. | **Yanlış** (en azından bu uç noktada). Önerilen kod hiçbir şey ayrıştırmaz. |
| "`requests` TLS parmak izi yüzünden geçemiyor" | Aynı belgede önerinin kendisi `seeMoreJobPostings`'in 13 sayfa üst üste 200 döndürdüğünü söylüyor; bizim canlı sistem de `requests` ile veri topluyor. | Kendi içinde çelişkili; kanıt yok. |
| "Tek kova var, hepsi aynı limite takılıyor" | Doğru: `source_policy` tek `linkedin` satırı. Ama bu **bilinçli** tasarım (web+CLI+detay doldurucu ortak sıra). | Gerçek tespit, ama sonuç yanlış (aşağıda). |
| "Honeypot veri servis ediliyor" | Kaynak gösterilmemiş "arama sonucu" alıntısı; bu depoda bunu destekleyen hiçbir gözlem yok. | Doğrulanamadı. |
| Kod adları (`source_key`, `min_interval`, `lease_owner`) | Gerçek şema: `source`, `interval_floor`, `lease_owner`. `search_events`, `SearchRun`, `DetailCache` gerçekten var. | Kısmen yanlış; kod örnekleri kopyalanamaz. |
| "Paralel worker olmalı" (§5, §20) ve "paralel istek ölü yöntem" (§13) | Aynı metin hem paralel işçi öneriyor hem paraleli bot sinyali sayıyor. | Çelişki. |
| "Residential proxy zorunlu" (§10) ve "proxy'siz 5–8 kat hız" (§14) | Aynı metin iki zıt şey söylüyor. | Çelişki. |

## 3. Madde madde karar

Başlıklardaki § numaraları önerinin kendi numaralarıdır.

### 3.1 Onaylananlar (2)

| # | Öneri | Karar | Sebep |
| --- | --- | --- | --- |
| § 5, § 22 | Detay önbelleği süresini uzat (24 sa → 72 sa) | **Onay — yalnızca detay açıklaması için, ayar olarak** | Kaynağa giden isteği **azaltır**, hız politikasına dokunmaz. Sürenin kendisi zaten `JOBAPP_DETAIL_CACHE_TTL_SECONDS` ile ayarlanıyor; kod değişmez. Parmak izi (kart satırları + yayın tarihi) değişirse önbellek zaten geçersiz sayılıyor. Kazanç küçük: bilinen ilanlar için bayat açıklama zaten kullanılıyor (`allow_stale_ids=known`); fark, silinip 24 saatten sonra yeniden aranan ilanlarda görünür. İlan metni 2–3 günde nadiren değişir. |
| § 16, § 24 (+ § 11'in ölçüm kısmı) | Ölçüm metrikleri: 429 oranı, istek başına yeni ilan, önbellek isabeti, bekleme toplamı, sayfa başına kart sayısı | **Onay — yalnızca ölçüm/raporlama** | Hız ayarlarını "hissederek" değil sayıyla değerlendirmek doğru; bu belgenin kendisi de ölçüm eksikliği yüzünden kanıt gösteremiyor. Veri zaten `search_events`'te (`request_finished.status`, `cache_hit/miss`, `source_paused`, `page_result`); `audit.report` ham sayıları veriyor ama oran ve bekleme toplamı yok. Yeni tablo/sütun gerekmez, geriye uyumlu. Önerideki "honeypot olursa kovayı değiştir" **eylemi alınmıyor**; yalnızca anormal sayfa (çok az kart, tekrar eden ID) uyarı olarak raporlanır. |

### 3.2 Zaten uygulanmış olanlar (kod karşılığıyla)

| Öneri | Mevcut kod |
| --- | --- |
| § 3 Hata sonrası aralığı artır, başarıda yavaşça düşür (AIMD) | `transport.py` `Coordinator.pause`: ihlalde `interval_floor × 1,5` (üst sınır 120 sn); `success`: kararlı dönemde `× 0,95`. **Taban 6 sn'dir ve altına inmez** — önerinin "taban 3,5 sn" kısmı reddedildi. |
| § 3, § 7 `Retry-After` kadar dur; 999/authwall'da 15 dk blok | `retry_after_seconds`, `pause(hard=True)`, `ACCESS_PAUSE_SECONDS=900`, artan bekleme, üst sınır 6 sa. |
| § 7 Kart→detay geçişinde de aralık; "navigasyon hızı" | Kart ve detay istekleri **aynı** kapıdan (`Coordinator.acquire`) geçiyor; her istek arası ≥ aralık + pay. (Önerinin atıfta bulunduğu "navigasyon hızı" oturum açmış profil gezintisiyle ilgili, hesapsız uca uygulanmaz.) |
| § 7 Oturumda parmak izini sabit tut | `_reset_session` yalnızca oluşturmada çalışır; yorumda "engelden kaçmak için oturum döndürme" açıkça yasak. |
| § 6, § 9 `Accept-Language`, keep-alive, oturum/çerez yeniden kullanımı | `Accept-Language: tr-TR…` ve `Sec-*` başlıkları var; `requests.Session` bağlantıyı ve çerezleri otomatik yeniden kullanır; tarama boyunca tek oturum. |
| § 5 Önce kart, detay sonra (defer) | `DEFER_DETAILS`, `details.py` arka plan doldurucu; `TARAMA_VERIMLILIK_RAPORU` içinde ölçüldü. |
| § 12 Yeni ilanları öne al | Düzenli taramalar `sort_recent` (`sortBy=DD`), `posted_within`, `stop_when_known` ile çalışıyor. |
| § 12 "3–5 sayfada kes mantığı yanlış" | Böyle bir kesme yok; tarama sonuç bitene, limite veya "tamamı bilinen sayfaya" kadar sürüyor. |
| § 14 Önbellek isabeti | `DetailCache` + kalıcı önbellek mevcut; silinen ilanın detayı bile korunuyor. |

### 3.3 Onaylanmayanlar ve sebepleri

| # | Öneri | Sebep |
| --- | --- | --- |
| § 1, § 8, § 19-A | `requests` → `curl_cffi(impersonate="chrome")`, HTTP/2, başlık sırası taklidi | Amaç, bot tespitini atlatıp aralığı kısaltmak; doğrulanabilir tek kazanç yok (429 şimdiki hızda sürüyor). Ayrıca üretimde otomatik deploy edilen sisteme yerel (native) bir ikili bağımlılık ekler; kırılırsa tüm hizmet düşer. Bakım yükü ve kırılganlık kazançtan büyük. Mevcut istemci zaten tutarlı tarayıcı başlıkları gönderiyor. |
| § 2, § 17 | Kart / detay / HTML için ayrı hız kovaları, "3× throughput" | Aynı sunucu ve aynı IP'ye giden toplam istek hızını **katlamak** demek; "hız sınırını gevşetme" kuralının tam karşıtı. Kovalardan biri kısıtlanınca diğerlerinin devam etmesi, kaynağın verdiği bekleme sinyalini atlamaktır. Tek kapı bilinçli: web, CLI ve detay doldurucu aynı sırayı paylaşır. |
| § 3, § 14, § 15, § 21 | Taban aralığını 3–3,5 sn'ye indirmek; gece 3 sn, 8 saatte ~9.000 istek | `MIN_REQUEST_INTERVAL=6` ve "bekleme süreleri kısaltılmaz" kuralları. Zaten 6 sn'de 429 alıyoruz. |
| § 4, § 10 | IPv6 adres döndürme, Cloudflare WARP / wgcf, modem IP yenileme, IP havuzu bazlı koordinatör | Engel/hız sınırından kaçmak için kimlik değiştirme; kodda "engelden kaçmak için oturum döndürme" yasağıyla aynı ilke. Tek VPS ve tek IP varsayımı üzerine kurulu bekleme politikasını anlamsızlaştırır. Hesapsız, kaynağa saygılı toplama yaklaşımımızın dışında. |
| § 11 (eylem kısmı) | "Az kart gelirse kovayı değiştir / IP değiştir / 10 dk soğut ve yeniden dene" | Dayanak doğrulanamadı; sayfa boyutu zaten değişken kabul ediliyor (offset gerçek kart sayısıyla ilerliyor), yani `%30` eşiği meşru sayfaları "sahte" sayabilir. Değiştirme eylemi reddedildi; yalnızca ölçüm alındı (bkz. 3.1). |
| § 8, § 19-D | JSON-LD ayrıştırma | Gerçek yanıtlarda JSON-LD yok (bkz. §2). "Honeypot'a dirençli" iddiasının da dayanağı yok. |
| § 12, § 23 | Google/Bing "X-Ray" yedek kanalı | Arama motoru sonuçlarını otomatik kazımak o hizmetlerin kullanım şartlarına aykırıdır ve hızla CAPTCHA/engele girer. Asıl amaç LinkedIn'in bekleme sinyalini dolanmak; üstelik toplanan ilan kimlikleri yine aynı LinkedIn detay uç noktasına gidecek. Güvenlik doğrulaması/bekleme aşılmaz kuralı. |
| § 5, § 15, § 20 | Detay doldurucuda 2–3 işçi, aralarında 1,5–2 sn kayma | Tek kapı olduğu için ya hiçbir hız kazancı sağlamaz ya da kapıyı delerek hızı artırır. "Tek collector süreci" kuralıyla da çelişir; önerinin kendi § 13'üyle de çelişir. |
| § 22 | Katmanlı önbellek (kart 48 sa, firma 7 gün, maaş 48 sa) | Bizde yalnızca detay açıklaması önbelleğe alınıyor; kart, firma ve maaş ayrı önbellek değil. Uygulanacak bir hedef yok (detay süresi ayarı 3.1'de). |
| § 6 | `Referer` başlığı eklemek | Kazancı kanıtsız tarayıcı taklidi; yapılmayacak. Diğer başlıklar zaten var. |
| § 9 | Guest `Set-Cookie` değerlerini elle sakla | `requests.Session` bunu zaten yapıyor. |
| § 15 | 4 haftalık "kademeli açma planı" | Planın tamamı yukarıdaki reddedilen adımlara dayanıyor. Kabul edilen iki parçası aşağıda. |
| § 13 | "Ne yapma" listesi | Bilgilendirme; zaten doğru taraftayız (hesapsız, çerezsiz, sıralı). Ancak listede paralel/proxy/raw-requests iddiaları kendi içinde çelişkili ve kaynaksız. |
| § 0 | "Mimarin avantajlı" | Doğru ve `CLAUDE.md` ile uyumlu: hesapsız, yalnızca kamuya açık sayfalar. Eylem gerektirmez. |

## 4. Gerçek darboğaz nedir?

Önerinin teşhisi (TLS parmak izi) bu depoda desteklenmiyor. Kanıtlar, darboğazın **kaynağın verdiği
bekleme** olduğunu gösteriyor: 429 → 60/120 sn bekleme → artan aralık → bazen 15 dk–6 sa duraklatma.
Bu yüzden gerçek kazanç "daha hızlı istemek" değil, **daha az istek atmaktır**; bunlar zaten
uygulandı (önce kart, detay önbelleği, `stop_when_known`, `posted_within`). Hız artışı isteniyorsa
yöntem: gereksiz isteği azaltmak ve kaynağın sinyallerini ölçerek izlemek.

## 5. Güncelleme planı (yalnızca onaylananlar)

Kurallar: şema yalnızca ekleyerek değişir (burada hiç değişmiyor), veri silinmez, hız/bekleme politikasına
dokunulmaz, tek collector korunur.

### Faz 1 — Detay önbelleği ayarı (kod yok)
- `.env.example` içinde `JOBAPP_DETAIL_CACHE_TTL_SECONDS=259200` (72 sa) ve açıklaması.
- Canlıda `/etc/linko.env` ayrıca elle güncellenir (deploy bu dosyayı değiştirmez) ve `linko.service` yeniden başlatılır.
- Kabul: `JOBAPP_DETAIL_CACHE_TTL_SECONDS` testleri geçer; fingerprint değişince önbellek hâlâ geçersiz sayılır.
- Geri alma: değeri `86400`'e çek.

### Faz 2 — Ölçüm oranları (yalnızca raporlama)
- `jobapp/audit.py` `report()`: mevcut sayaçlardan türetilmiş alanlar ekle — `rate_429` (statuses'tan
  429 / toplam), `useful_per_request` (`new_jobs / requests`), `cache_hit_rate`
  (`hits / (hits + misses)`), `avg_cards_per_page`, `pause_seconds` (`source_paused.remaining_seconds` toplamı).
  Yeni tablo veya sütun yok.
- Anormal sayfa (ilk sayfa dışı, kart sayısı bir önceki sayfanın yarısından az, sıfır değil) için **yalnızca**
  `warning` log satırı; tarama akışı, bekleme ve yeniden deneme davranışı değişmez.
- `tests/`: oran hesapları ve sıfıra bölme durumları için birim testi; mevcut `python -m unittest discover -s tests` geçmeli.
- Kabul: aynı tarama için iki ölçüm tekrarlanabilir; 429 oranı arayüzde/raporda görünür.

### Değerlendirmeden sonra
Faz 1 ve 2 canlıya girdikten sonra 1 hafta veri toplanır. Aralığı değiştirmek için yeni karar,
**yeni kanıt ve açık kullanıcı onayı** gerekir; bu belge o kararı vermez.

## 6. Özet

| Durum | Başlıklar |
| --- | --- |
| Onaylandı (küçük, riski düşük) | Detay önbelleği 72 sa (ayar), ölçüm oranları + uyarı logu |
| Zaten var | AIMD ve `Retry-After`/authwall beklemesi, kart→detay geçiş aralığı, sabit oturum, başlık/keep-alive/çerez, önce kart, `sort_recent`/`stop_when_known`, detay önbelleği |
| Reddedildi | `curl_cffi`, ayrı kovalar, taban aralığı kısaltma ve gece profili, IPv6/WARP, honeypot'ta kova/IP değiştirme, JSON-LD, Google X-Ray, çoklu detay işçisi, katmanlı önbellek, `Referer`, 4 haftalık plan |
