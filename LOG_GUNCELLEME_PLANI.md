# Log ve haberleşme mimarisi — güncelleme planı (yüksek + orta öncelik)

Kaynak: 17 Ekim 2026 mimari analizi. Hedef: **hiçbir hata ve sorun kaybolmasın**, süreç ölse bile.
Kurallar (CLAUDE.md): şema yalnızca ekleyerek değişir (ALTER ADD COLUMN, veri silen göç yok), tek
collector süreci korunur, kaynak bekleme politikasına dokunulmaz, anahtarlar koda/commit'e/issue'ya girmez.

Dört faz; her faz ayrı commit + deploy, kendi testleriyle. Sunucu tarafı elle kurulum gerektiren adımlar ⚙ ile işaretli
(`/usr/local/bin/linko-*` betikleri repo'dan **kopya** olarak kurulu; deploy onları güncellemez).

## Hedef mimari

```
 uygulama logları ─┐
 problem kuralları ┼─► logstore (redakte → toplu yazım) ─► app_logs / incidents ◄─ spool ingest
 excepthook/kapanış┘          │ DB yazılamazsa                    ▲                  ▲
                              └──────────► spool/*.jsonl ─────────┘                  │
 deploy geri alma, yedek hatası, systemd OnFailure ──────────────► spool/*.jsonl ────┘
 uptime.yml (site ölü) ──► doğrudan issue ── site dönünce ──► /api/v1/incidents/report
 incidents.yml ◄──► GitHub issue: aç / yeniden aç / fix yayında / doğrulandı / otomatik kapat
```

Hata kaydı durumları: `open` → (issue kapandı) → `fix_deployed` (düzeltme commit'i canlıda) →
24 saat temiz → `resolved`. Herhangi bir aşamada tekrar görülürse → `open` (+`reopened` geçmişi).
Kayıt türü (`kind`): `error` (ERROR logu), `problem` (eşik kuralı), `external` (spool/uptime).

---

## Faz 1 — Kayıt sağlamlığı (madde 3, 4, 8, 9, 10)

**4. Gizli bilgi maskeleme** — `jobapp/logstore.py`
- `redact(text)`: bilinen değerler (`ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `JOBAPP_API_KEY`, `JOBAPP_ADMIN_KEY`,
  `JOBAPP_LOG_KEY`) + desenler (`Bearer \S+`, `gsk_\w+`, `sk-ant-\S+`, `(api[_-]?key|token|password|secret)=\S+`).
- Mesaj ve traceback'e yazmadan önce uygulanır. `scripts/incident_sync.py` issue gövdesine yazmadan önce aynı
  desenleri ikinci kez uygular (savunma katmanı).

**3. Parmak izi ve issue taşkını**
- `audit.record` log satırına `extra={"fingerprint_key": f"{kind}|{reason or msg}"}` ekler; `DatabaseHandler`
  varsa bunu kullanır → unvan/konum parmak izine girmez.
- `incident_sync.py`: tur başına en fazla **5** yeni issue; fazlası tek "Hata taşkını" issue'sunda liste olarak
  (işaret `<!-- linko-flood -->`, varsa yorum eklenir). Kalanlar sonraki turlarda normal issue olur.

**8. Başlangıç / kapanış / çökme kaybı** — `serve_service.py`, `jobapp/logstore.py`
- `logstore.install()` `create_app()`'ten **önce** çağrılır; tablolar hazır olana kadar kayıtlar bellekte bekler,
  `logstore.ready()` (init_db sonrası) ile akıtılır.
- `sys.excepthook` ve `threading.excepthook` → CRITICAL log (hata kaydı açar).
- SIGTERM/atexit → `listener.stop()` (kuyruk boşaltılır; systemd `TimeoutStopSec=30` yeterli).

**9. Toplu yazım, sınırlı kuyruk, yedek dosya**
- Yazıcı 1 sn veya 200 kayıtta bir **tek işlemde** yazar.
- Kuyruk 10 000 kayıtla sınırlı; taşarsa düşen kayıt sayılır.
- DB yazımı başarısızsa kayıtlar `/var/lib/linko/spool/applog-*.jsonl`'a eklenir, sonra ingest edilir (Faz 3).
- Sayaçlar (`written`, `spooled`, `dropped`, `last_error`) `/api/v1/status`'ta; `dropped>0` bir problem kuralı (Faz 3).

**10. Sürüm bilgisi**
- ⚙ `deploy/linko-deploy.sh` başarılı deploy sonunda `/var/lib/linko/version.json` yazar
  (`sha`, `subject`, `deployed_at`) ve `/var/lib/linko/deploy_history.jsonl`'a ekler (linko kullanıcısı git'i
  okuyamıyor; bu yüzden dosya). Yerelde dosya yoksa `bilinmiyor`.
- `config.VERSION` başlangıçta okunur; `app_logs.version`, `incidents.first_version` / `last_version` sütunları;
  `/healthz` ve `/api/v1/status` sürümü döner; "Servis başladı" satırı sürümü içerir.

**Testler** (`tests/test_logs.py`): maskeleme (değer + desen), audit parmak izi unvandan bağımsız, taşkın sınırı
(7 kayıt → 5 issue + 1 taşkın issue'su), hazır olmadan gelen kayıtların kaybolmaması, toplu yazım, DB hatasında
spool'a düşme, kuyruk taşma sayacı, excepthook'un hata kaydı açması, sürümün kayda yazılması.

## Faz 2 — Ayrı log anahtarı (madde 5)

- `JOBAPP_LOG_KEY`: yalnızca `/api/v1/logs*` ve `/api/v1/incidents*` (GET + POST). `service_api.authorize`
  bu yollar için LOG_KEY'i de kabul eder; diğer yönetim uçları LOG_KEY'i **reddeder**. ADMIN_KEY her yerde geçerli kalır.
- ⚙ Sunucuda anahtar üret, `/etc/linko.env`'e ekle, servisi yeniden başlat; GitHub secret `LINKO_LOG_KEY` olarak
  aktar (ekrana basmadan), `incidents.yml` ve `.local/linko_cli.env` LOG_KEY'e geçer, `LINKO_ADMIN_KEY` secret'ı silinir.
- **Testler:** LOG_KEY ile log/incident 200, `/api/v1/collections` POST ve `/api/runs/...` 401; API_KEY ile log 403.

## Faz 3 — Süreç dışı olaylar ve sorun kuralları (madde 1, 2)

**1a. Spool ingest** — yeni `jobapp/spool.py`
- `/var/lib/linko/spool/*.jsonl` satırları (`source`, `level`, `title`, `message`, `at`) başlangıçta ve supervisor
  her turunda okunur → `kind=external` hata kaydı; işlenen dosya `spool/done/`'a taşınır (silinmez, bakım 90 günde budar).
- ⚙ `linko-deploy.sh`: geri alma yapınca spool'a "Deploy geri alındı: <sha>" + son 30 journal satırı.
- ⚙ `linko-backup.sh`: hata trap'i spool'a da yazar.
- ⚙ Yeni `deploy/linko-alert.service` + `linko.service`'e `OnFailure=linko-alert.service`: systemd servisi
  vazgeçtiğinde (restart döngüsü) son 50 journal satırını spool'a yazar.

**1b. Site tamamen ölüyse** — `.github/workflows/uptime.yml`
- 3 deneme başarısızsa `<!-- linko-uptime -->` işaretli açık issue var mı bak; yoksa `hata-kaydı` etiketli
  "Site erişilemiyor" issue'su aç, varsa yorum ekle.
- Başarılı kontrolde açık uptime issue'su varsa: kesinti süresini yorumla, issue'yu kapat ("✅ Çözüldü: site
  yeniden ayakta") ve `POST /api/v1/incidents/report` ile kaydı DB'ye de yaz (`kind=external`, çözülmüş, issue bağlı).
- Yeni uç: `POST /api/v1/incidents/report` (LOG_KEY) — dış kaynaklı kayıt oluşturur/günceller.

**2. Sorun kuralları** — yeni `jobapp/problems.py`, supervisor her 5 dk'da bir değerlendirir
| Anahtar | Koşul | Mesaj |
|---|---|---|
| `source_blocked_long` | Kaynak kilidi kalan süresi ≥ 3 sa veya ihlal sayacı ≥ 5 | Kaynak uzun süredir kilitli |
| `queue_stalled` | Kullanıcı duraklatmamış, bitmemiş koşu 24 sa'tir ilerlemiyor ve kaynak açık | Kuyruk ilerlemiyor |
| `supervisor_error` | `service.last_error` 10 dk'dan uzun dolu | Toplayıcı hata veriyor |
| `detail_backlog` | Bekleyen detay sayısı 24 sa'tir azalmıyor (`details.pending_count`) | Detay tamamlama tıkandı |
| `backup_stale` | `backup_status.json` ok=false veya 36 sa'ten eski | Sunucu dışı yedek alınamıyor |
| `log_drops` | Yazıcı `dropped` / `spooled` > 0 | Log kaydı kaybı riski |
- Koşul başlayınca `kind=problem` kaydı açılır (parmak izi `problem:<anahtar>`); koşul 30 dk boyunca ortadan
  kalkınca kayıt **otomatik çözülür** (geçmişe "koşul kalktı" düşer). Kural eşikleri `config`'te.
- **Testler:** her kural için tetiklenme + otomatik çözülme; spool ingest (bozuk satır atlanır, dosya done'a taşınır);
  report ucu; uptime adımları için `incident_sync` ile aynı sahte HTTP kalıbıyla betik testi.

## Faz 4 — Issue yaşam döngüsü ve bağlam (madde 6, 7, 11)

**6. Doğrulanmış çözüm** — `scripts/incident_sync.py`, `jobapp/logs_api.py`
- Issue kapanınca kapanış olayındaki commit (`/issues/{n}/events` → `closed.commit_id`) alınır.
  - Commit yoksa (elle kapatma): `resolved` (not: "elle kapatıldı, doğrulama yok").
  - Commit varsa: `/compare/{commit}...{canlı sha}` "ahead/identical" olana kadar `open` kalır; olunca
    `fix_deployed` (yorum: "🚀 Düzeltme yayında, 24 saat izleniyor").
- `fix_deployed` + 24 saat tekrar yok → `resolved` (yorum: "✅ Çözüldü — 24 saat tekrar görülmedi").
- `fix_deployed` iken tekrar görülürse → `open`, issue yeniden açılır ("düzeltme yetmedi").
- Yeni sütunlar: `fix_commit`, `fix_deployed_at`, `verified_at`; API'ye `action: fix_deployed | reopen` eklenir.

**7. Elle yeniden açma** — `issues: reopened` olayında iş akışı `ISSUE_NUMBER` geçirir; sync bu issue'nun kaydını
`open` yapar (geçmiş: "issue elle yeniden açıldı"). Zamanlanmış turda son 30 günde çözülen kayıtların issue durumları da
karşılaştırılır (kaçan olaylar için).

**Otomatik çözülen sorunlar** (Faz 3): sunucu `resolved`, issue açıksa sync issue'yu yorumla kapatır.

**11. Hata bağlamı** — `GET /api/v1/incidents/<id>/context?window=10m[&at=]`: kaydın son görülme anının
± penceresindeki `app_logs` + `search_events` (zaman sıralı, en fazla 500). CLI: `incident 3 --context 10m`;
issue gövdesine bu komut eklenir.

**Testler:** kapanış commit'i yayında değil → open kalır; yayında → fix_deployed; 24 sa → resolved; arada tekrar →
reopen; elle kapanış; elle yeniden açma; otomatik çözülen problemin issue'sunun kapanması; bağlam penceresi.

---

## Yayın sırası ve doğrulama

| Faz | Commit | ⚙ Sunucu adımı | Canlı doğrulama |
|---|---|---|---|
| 1 | Kayıt sağlamlığı | `linko-deploy.sh` kopyala (version.json) | `/healthz` sürüm döner; `logs --since 10m` başlangıç satırları dahil; sahte anahtarlı log satırı `[gizlendi]` |
| 2 | Log anahtarı | LOG_KEY üret, env + secret, ADMIN secret'ı sil | CLI LOG_KEY ile çalışır; LOG_KEY ile `/api/v1/collections` POST 401 |
| 3 | Dış olaylar + kurallar | `linko-backup.sh`, `linko-alert.service`, `OnFailure` kur, `daemon-reload` | spool'a deneme satırı → hata kaydı + issue; `incidents --status all` problem kayıtları |
| 4 | Issue döngüsü | — | deneme hata kaydı → issue → `Fixes #N` → fix_deployed → (24 sa) resolved; issue yorumları |

Her fazda: `python -m unittest discover -s tests` yeşil, yalnızca kendi değişiklikler commit'lenir (eşzamanlı oturum
varsa ayrı worktree), deploy sonrası `/healthz` ve `incidents.yml` tetiklenip sonucu kontrol edilir.
Belgeler: her faz sonunda `CALISMA_YONTEMI.md` (durumlar, komutlar, kurallar) güncellenir.

---

## Uygulama notları (plandan sapmalar)

Dört faz da uygulandı (commit'ler: `db8a012`, `c1aa2c8`, `12f9e9f` ve yaşam döngüsü commit'i). Plandan farklar:

- **`OnFailure=linko-alert.service` yerine `ExecStopPost`:** varsayılan başlatma sınırı (10 sn'de 5) `RestartSec=10`
  ile hiç aşılmaz, `OnFailure` çökme döngüsünde tetiklenmezdi; sınır koymak ise geçici bir sorunda servisi kalıcı
  kapatırdı. `linko.service` içindeki `ExecStopPost=+/usr/local/bin/linko-spool-stop` her beklenmedik duruşu kaydeder.
- **Elle yeniden açma:** olaya `ISSUE_NUMBER` geçirmek yerine her senkron turu (30 dk, issue kapanış/yeniden açılış
  olayı ve deploy sonu tetikler) çözüldü kayıtların issue durumunu tarar (son 30 gün, en fazla 50 issue).
- **Yeni sütunlar** (hepsi `ALTER ADD COLUMN`, veri silen göç yok): `app_logs.version`, `incidents.first_version`,
  `last_version`, `kind`, `fix_commit`, `fix_deployed_at`.
- **Kurulum:** sunucudaki kopya betikler için tek komut: `deploy/install-ops.sh` (bkz. `CALISMA_YONTEMI.md`).
- **Test altyapısı:** issue senkronu, gerçek sunucu API'si ile bellek içi sahte GitHub arasında uçtan uca test edilir
  (`tests/test_incident_lifecycle.py`).
