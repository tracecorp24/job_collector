# Çalışma yöntemi: canlı loglara dayalı geliştirme

20 Ekim hız incelemesi: `TOPLAMA_HIZI_ANALIZI_2026-10-20.md`; sonraki ajanlar için
kısa başlangıç ve yerel anahtar yokken kullanılan GitHub tanılama yolu:
`AI_CALISMA_BAGLAMI.md`. Salt okunur yedek özeti: `scripts/collection_diagnosis.py`.
Eski/yeni 429 oranı ve oturum ömrü karşılaştırması; güncellenen uygulama sırası:
`429_ARTISI_ANALIZI_VE_PLAN_2026-10-20.md`.
Deney sonuçları ve uygulanacak ayrıntılı aşamalar:
`DENEY_SONUCLARI_VE_AYRINTILI_PLAN_2026-10-20.md`.
Planın yerel kod uygulaması, test sonuçları ve canlı rollout'ta bekleyen işler için
önce `AI_CALISMA_BAGLAMI.md` içindeki “Bu dalda uygulananlar” bölümünü oku.

Geliştirme, canlı sitenin kendi kayıtlarına bakarak yapılır. Site loglarını kalıcı saklar, yerelden
anahtarla sorgulanır; hatalar ve sorunlar kaybolmayan **hata kayıtlarına** dönüşür, GitHub issue'su olarak
takip edilir ve ancak düzeltme canlıda 24 saat temiz geçince **çözüldü** sayılır.

```
 uygulama logları ─┐
 sorun kuralları ──┼─► logstore (maskele → toplu yaz) ─► app_logs / incidents ◄─ olay klasörü (spool)
 çökme/kapanış ────┘          │ DB yazılamazsa                 ▲                    ▲
                              └────────► spool/applog-*.jsonl ─┘                    │
 deploy geri alma, yedek hatası, servis çökmesi ──► linko-spool ──► spool/external-*.jsonl
 uptime.yml: site ölü ──► issue ── site dönünce ──► POST /api/v1/incidents/report (çözülmüş)
 incidents.yml ◄──► GitHub issue (hata-kaydı): aç / yeniden aç / düzeltme yayında / çözüldü
```

## Hata kaydı (incident)

Aynı hata tek kayıtta toplanır: parmak izi `logger + olay türü/sebep` (sayılar, kimlikler, unvan/konum atılır).
Kayıt: ilk/son görülme ve sürüm, tekrar sayısı, örnek mesaj, iz kaydı (traceback), issue numarası, geçmiş.
Hiçbir kayıt budanmaz; ham loglar (`app_logs`) 90 gün tutulur.

| `kind` | Kaynak |
|---|---|
| `error` | ERROR/CRITICAL log satırı, yakalanmamış istisna |
| `problem` | Sorun kuralı (`jobapp/problems.py`) |
| `external` | Süreç dışı olay: deploy geri alma, yedek hatası, servis çökmesi, site kesintisi |

**Durumlar:** `open` → (issue `Fixes #N` ile kapandı **ve** commit canlıda) `fix_deployed` →
(24 saat tekrar yok) `resolved`. Herhangi bir aşamada tekrar görülürse `open` + `reopened` geçmişi + issue yeniden açılır.
Elle kapatılan issue (commit yok): tekrar görülmediyse `resolved` ("doğrulama yok"), görüldüyse issue yeniden açılır.
Issue GitHub'da elle yeniden açılırsa kayıt da açılır (`issue_reopened`). Sorun kuralları koşul 30 dk kalkınca
kendiliğinden `resolved` olur ve açık issue'su yorumla kapatılır.

## Sorun kuralları (5 dakikada bir)

`source_blocked_long` (kilit ≥ 3 sa veya ardışık ihlal ≥ 5) · `queue_stalled` (kullanıcı duraklatmamış koşu 24 sa ilerlemiyor,
kaynak açık) · `supervisor_error` (toplayıcı hatası ≥ 10 dk) · `detail_backlog` (bekleyen detay 24 sa azalmıyor) ·
`backup_stale` (yedek başarısız / 36 sa'ten eski) · `log_drops` (log yazılamıyor/dosyaya düşüyor).
Aktif sorunlar `/api/v1/status` içinde `problems` olarak görünür.

## Yerel kurulum (bir kez)

`.local/linko_cli.env` (gitignore'da):

```
LINKO_URL=https://job.ai-org.online
LINKO_LOG_KEY=<sunucudaki /etc/linko.env içindeki JOBAPP_LOG_KEY>
```

`JOBAPP_LOG_KEY` yalnızca `/api/v1/logs*` ve `/api/v1/incidents*` uçlarını açar; yönetim ve veri uçlarında geçmez.
Geçişte `LINKO_ADMIN_KEY` de kabul edilir. `/api/v1/*` Caddy basic auth'undan muaftır, Bearer anahtarı yeterlidir.

## Komutlar

```bash
python scripts/linko_logs.py logs --since 2h                     # son 2 saatin sunucu logu
python scripts/linko_logs.py logs --since 1d --level warning      # uyarı ve üstü
python scripts/linko_logs.py logs --source events --since 30m --kind request_finished --q 429
python scripts/linko_logs.py follow --level warning               # canlı takip
python scripts/linko_logs.py download --since 2026-10-17T00:00:00Z --until 2026-10-18T00:00:00Z
python scripts/linko_logs.py download --source events --since 7d  # .local/logs/ altına JSONL
python scripts/linko_logs.py incidents --status all               # open | fix_deployed | resolved | all
python scripts/linko_logs.py incident 3                           # ayrıntı, geçmiş, son 20 log
python scripts/linko_logs.py incident 3 --context 10m             # hata anının ±10 dakikası (log + arama olayları)
```

Zamanlar UTC; ISO 8601 ya da göreli (`30m`, `2h`, `7d`). Tek indirme en fazla 31 gündür. Her satırda
`version` (commit) vardır: hatanın hangi sürümde başladığı `incident` çıktısında `first_version` / `last_version`.

## Geliştirme döngüsü

1. **Başlarken:** `incidents` ile açık hata kayıtlarına, `logs --since 1d --level warning` ile son uyarılara bak.
   Bildirilen sorunda önce ilgili aralığı indir, nedeni loga dayandır; hata kaydında `--context` ile öncesine bak.
2. **Düzeltirken:** hatayı yeniden üreten test yaz (`python -m unittest discover -s tests`).
3. **Commit:** ilgili issue'yu kapatmak için mesaja `Fixes #<issue>` yaz. `main`'e merge → otomatik deploy.
4. **Yayın:** deploy bitince `incidents.yml` çalışır; kapatan commit canlıdaysa kayıt `fix_deployed` olur.
5. **Doğrulama:** 24 saat tekrar görülmezse kayıt `resolved` olur, issue'ya "✅ Çözüldü" yorumu düşer.
   Tekrar görülürse issue yeniden açılır ("düzeltme yetmedi"). Hiçbir kayıt ve issue silinmez.

## Sunucu işletimi

Aşağıdaki dosyalar sunucuda **kopya** olarak durur; deploy bunları güncellemez. Değişince bir kez, root olarak:

```bash
ssh root@38.45.81.29 'bash /opt/linko/deploy/install-ops.sh'
```

Kurar: `linko-deploy` (sürüm dosyası + geri alma kaydı), `linko-backup` (başarısızlıkta kayıt), `linko-spool`
(olay klasörüne yazar), `linko-spool-stop` (servis `ExecStopPost`: beklenmedik duruşu kaydeder) ve `linko.service`.
`JOBAPP_LOG_KEY` `/etc/linko.env`'e eklenir; aynı değer GitHub secret'ı `LINKO_LOG_KEY` ve `.local/linko_cli.env` olur.
Servis yeniden başlatma sınırı bilerek konmadı (çökme döngüsünde servis kalıcı kapanırdı); duruşlar `ExecStopPost` ile kaydedilir.

Sürüm bilgisi `/var/lib/linko/version.json` (deploy yazar, `/healthz` ve `/api/v1/status` gösterir); geçmişi
`deploy_history.jsonl`. Olay klasörü `/var/lib/linko/spool` (işlenenler `done/` altına taşınır).

## Kurallar

- Log API'si yalnızca log/yönetici anahtarıyla çalışır; anahtar koda, commit'e, issue'ya yazılmaz. Loglar kaydedilmeden
  önce anahtar/şifre desenlerinden arındırılır; yine de yeni log satırlarına anahtar, şifre, çerez yazma.
- Hata kayıtlarını ve issue'ları silme; yanlış alarmı "not planned" olarak kapat (kayıt "çözüldü" geçmişiyle kalır).
- Bir turda en fazla 5 yeni issue açılır; fazlası tek "Hata taşkını" issue'sunda listelenir.
- Kaynak (LinkedIn) 429 beklemeleri uyarıdır, hata kaydı açmaz; yalnızca uzun süren kilit `source_blocked_long`
  sorunu olur. Bekleme politikası loga bakılarak gevşetilmez.
