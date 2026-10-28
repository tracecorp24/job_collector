# Otonom ilan toplama servisi

`SERVICE_PLAN.md` uygulama planını içerir. Tek toplayıcı süreç, SQLite içinde
kalıcı kuyruk ve aynı süreçte çalışan HTTP sunucusu kullanılır. Arayüz kapalıyken
toplama devam eder. Sunucu yeniden başlayınca çalışmakta olan işler kurtarılır;
kullanıcı tarafından duraklatılan işler kendiliğinden açılmaz.

## Çalıştırma

Yerelde `python run.py` otonom yöneticiyi de açar. Sunucuda:

Yerel başlatmada anahtar verilmemişse `.local/service_keys.json` içinde iki
kalıcı anahtar oluşturulur: `api_key` okuma, `admin_key` yönetim içindir. Bu dosya
git dışında tutulur; diğer programınıza okuma anahtarını ortam değişkeniyle
verin. Anahtarlar ekranlarda ve loglarda gösterilmez. Dış ağa açılan kurulumda
ortam değişkenleriyle anahtar vermek zorunludur.

```bash
python -m pip install -r requirements.txt
export JOBAPP_HOST=0.0.0.0
export JOBAPP_OPEN_BROWSER=0
export JOBAPP_API_KEY='<uzun-rastgele-okuma-anahtari>'
export JOBAPP_ADMIN_KEY='<farkli-uzun-rastgele-yonetim-anahtari>'
export JOBAPP_DB_PATH=/var/lib/linko/jobs.db
export JOBAPP_ACCOUNTLESS_OUTPUT_DIR=/var/lib/linko/searches
python serve_service.py
```

DB ve çıktı dizinlerini önceden oluşturun; servis kullanıcısına yazma izni verin.
Windows PowerShell'de ortam değişkenleri `$env:JOBAPP_API_KEY='...'` biçimindedir.
Anahtarları kaynak koduna koymayın. Dış ağda TLS reverse proxy kullanın.
Okuma anahtarı sadece `/api/v1/` GET isteklerini açar; yazma ve eski yönetim
API'leri yönetim anahtarı ister. Yerel arayüz loopback üzerinden anahtarsız
çalışır. Uzaktaki arayüz için kimlik doğrulayan proxy'nin yönetim anahtarını
sunucu tarafında iletmesi gerekir. X-Forwarded-For güvenilir istemci kimliği
olarak kabul edilmez; proxy arkasında eski yönetim yollarını dış erişime açmayın.

`serve_service.py` Waitress kullanır. Bir DB için yalnızca **bir servis süreci**
çalıştırın; çok worker'lı Gunicorn kullanmayın. SSE uzun bağlantı tutar; veri
tüketicileri HTTP polling kullanmalıdır. Bu sürüm dağıtık collector değildir.

Linux systemd örneği: `deploy/linko.service`. Örnekteki kullanıcı/dizinleri
kurulumunuza uyarlayın; `/etc/linko.env` dosyasına anahtarları ve DB yolunu yazın.
Windows'ta aynı komutu Görev Zamanlayıcı veya servis yöneticisiyle başlatın;
başarısızlıkta yeniden başlatma ve açılışta çalıştırmayı etkinleştirin.

## Otonom bekleme ve kurtarma

429 yanıtındaki `Retry-After` (saniye veya HTTP tarihi) korunur. Başlık yoksa
60, 120, üçüncü ihlalde en az 900 saniye; sonraki ihlallerde artan bekleme
uygulanır. Yerel artış 6 saatte sınırlanır; kaynağın daha uzun süresi kısaltılmaz.
403/güvenlik doğrulaması en az 900 saniye bekletir, sonrasında normal erişim
tekrar denenir; doğrulama veya erişim engeli aşılmaz. İhlaller istek aralığını da
artırır. Bir saat boyunca yeni ihlal görülmezse sonraki başarılı erişimlerde
istek aralığı kademeli azalır. Bir başarılı yanıt tüm bekleme geçmişini sıfırlamaz.

Bekleme DB'de tutulur, uygulama kapanıp açıldığında korunur. Süre dolunca yönetici
aynı görev ve checkpoint ile devam eder; onay gerekmez. Genel işleme hataları
5 dakikadan başlayarak artan aralıklarla tekrar denenir; kalıcı hatalar logda
görünür. Kullanıcı duraklatması/durdurması otomatik devamı kapatır.

Arayüzde kaynak beklemesi, hata sonrası yeniden deneme ve istekler arasındaki
beklemeler geri sayımla gösterilir. `/healthz` DB ve otonom yönetici sağlığını
ölçer (200/503); kaynak 429 beklemesi servis arızası sayılmaz.

## Arama sorgusu çevirisi

Arayüz araması Google çevirisini varsayılan olarak kullanmaz; statik çok dilli
meslek/yetenek eşanlamlıları çalışmaya devam eder. İsteğe bağlı açmak için servis
ortamına `JOBAPP_TRANSLATE=1` ekleyip yeniden başlatın. Açıkken ilk çeviri HTTP
isteğini bekletebilir. Üç karakterden kısa sorgular gönderilmez; başarısız çeviri
10 dakika önbelleklenir ve hata sonrası yeni sorgular için 60 saniye dış çağrı
yapılmaz. Aynı sorgu/dil için eşzamanlı ikinci çağrı beklemeden özgün sorguya
döner. Bu ayar ilan detayının kullanıcı tarafından istenen çevirisini ve toplama
sorgularının Groq ile yerelleştirilmesini değiştirmez.

## API v1

Tüm isteklerde `Authorization: Bearer ANAHTAR` gerekir. JSON kullanılır.
Sayfa limiti varsayılan 100, en fazla 500. Zamanlar UTC'dir.

| İstek | İşlev |
| --- | --- |
| GET `/api/v1/status` | Toplayıcı, heartbeat, kaynak bekleme durumu |
| GET `/api/v1/jobs?after_id=0&limit=100` | ID sıralı aktif/geçerli ilanlar |
| GET `/api/v1/jobs/changes?after=0&limit=100` | Kalıcı değişiklik akışı |
| POST `/api/v1/collections` | Kalıcı toplama işi oluştur |
| GET `/api/v1/collections/{run_id}` | Görevler, sayaçlar ve zamanlama |
| POST `/api/v1/collections/{run_id}/pause` | Otomatik devamı da duraklat |
| POST `/api/v1/collections/{run_id}/resume` | Aynı çalışmayı devam ettir |
| POST `/api/v1/collections/{run_id}/stop` | Başlamış işi sonlandır |
| POST `/api/v1/collections/{run_id}/cancel` | Başlamamış işi iptal et |
| POST `/api/v1/collections/{run_id}/disable-schedule` | Bu işin ve devam zincirinin tekrarını kapat |

`jobs` listesi `items`, `next_after_id`, `has_more` döndürür; eşitlik filtreleri:
`source`, `category`, `company`, `location`. Eşzamanlı güncellemelerde tam
senkronizasyon için değişiklik akışını kullanın.

Değişiklik akışı `items`, `next_cursor`, `has_more` döndürür. Her öğede
`sequence`, `operation` (`upsert`/`delete`), `job_id`, `changed_at`, `job` bulunur.
`delete` öğesinde `job=null`; tüketici kendi kopyasını silmeli. İlk `after=0`
çağrısı başlangıç verilerini de sağlar. İlan gövdesi açıklama, etiketler,
`search_ids` ve `run_ids` içerir. Ayrıntılı arama geçmişi eski log/report
uçlarında yönetim anahtarıyla erişilebilir. Bir ilanın kaydı ve arama ilişkisi
aynı işlemde ayrı olaylar üretebilir; `job_id` üzerinden upsert yapın.

Olaylar DB trigger'ıyla kayıtla aynı transaction'da yazılır; rollback olay
oluşturmaz. Silme/çöp kutusu/geri yükleme de akışta görünür. İşlenen sayfanın
verileriyle cursor'u kendi DB'nizde **aynı transaction'da** saklayın. Böylece
çökme sonrası sayfa tekrar gelse de idempotent upsert ile kayıp yaşanmaz.
Örnek tüketici: `scripts/consume_jobs.py`. Günlük otomatik silinmez; uzun süreli
kurulumlarda DB boyutunu ve yedeklemeyi izleyin. SQLite online backup kullanın.

Toplama örneği (yönetim anahtarı ve benzersiz `Idempotency-Key` başlığı):

```json
{
  "tasks": [{"keyword": "Python Developer", "location": "Istanbul, Turkey", "limit": 100}],
  "mode": "incremental",
  "classify_backend": "rules",
  "repeat_seconds": 3600
}
```

Yanıt 202 ve `run_id`. Aynı anahtar/istek 200 ile önceki kimliği döndürür;
aynı anahtar farklı istek 409. `repeat_seconds=0` tek sefer; tekrar en az 900.
Tekrar önceki iş bittikten sonra sayılır, yeni run/task kimlikleriyle geçmiş
korunur. Kuyruk taslağı oluşturmak işin otomatik başlaması anlamına gelmez;
API collection oluşturma servise teslim eder. Tekrarlı işi kapatma yeni
tekrarları engeller, çalışan son taramanın toplanan verilerini korur.

Hatalar: 400 geçersiz parametre, 401 yetkisiz, 404 bulunamadı, 409 kaynak
beklemesi veya idempotency çakışması. Anahtarları URL'ye eklemeyin.

## Kayıt saklama ve loglar

Servis boştayken günde bir bakım çalışır: `search_events` (arama işlem kayıtları) 90 günden,
`job_changes` (değişiklik akışı) 60 günden eski kayıtları siler (`JOBAPP_EVENT_RETENTION_DAYS`,
`JOBAPP_CHANGES_RETENTION_DAYS`). Değişiklik akışı tüketicisi bu süreden uzun ara verirse
`after=0` ile yeniden senkronize olmalıdır. Uyarılar, hatalar, çalışma başlangıç/bitişleri ve
düzenli tur kararları süreç loguna da yazılır (`journalctl -u linko`); istek başı ayrıntılar
yalnızca veritabanında ve arayüzdeki işlem kayıtlarında tutulur. Servis / API paneli veritabanı
boyutunu, kayıt sayılarını, son bakımı ve sunucu dışı yedeğin durumunu gösterir.
