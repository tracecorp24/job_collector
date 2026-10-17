# Çalışma yöntemi: canlı loglara dayalı geliştirme

Geliştirme, canlı sitenin kendi kayıtlarına bakarak yapılır. Site loglarını kalıcı olarak saklar,
yerelden yönetici anahtarıyla sorgulanır; hatalar kaybolmayan **hata kayıtlarına** dönüşür ve
GitHub issue'su olarak takip edilir.

```
 canlı site (VPS)                              GitHub                         yerel
 ───────────────                               ──────                         ─────
 Python logları ──► app_logs (90 gün)                                         scripts/linko_logs.py
 arama olayları ──► search_events (90 gün)  ◄── /api/v1/logs[/export] ◄────── logs / follow / download
 ERROR ──► incidents (hiç silinmez) ◄──────── incidents.yml (30 dk'da bir) ── incidents / incident
                     │                          ├─ yeni kayıt → issue (hata-kaydı)
                     │                          ├─ issue kapandı → kayıt "çözüldü" + yorum
                     └── tekrar görülürse ────► └─ kapalı issue yeniden açılır
```

## Parçalar

| Parça | Yer | Görev |
|---|---|---|
| Log deposu | `jobapp/logstore.py` | Kök loga kuyruklu yazıcı; her INFO+ satırı `app_logs`'a, ERROR+ satırları parmak iziyle `incidents`'a |
| Log/hata API'si | `jobapp/logs_api.py` | `/api/v1/logs`, `/api/v1/logs/export`, `/api/v1/incidents[/<id>]` — yalnızca `JOBAPP_ADMIN_KEY` |
| Yerel istemci | `scripts/linko_logs.py` | Sorgu, canlı takip, aralık indirme, hata kaydı listesi |
| Issue senkronu | `scripts/incident_sync.py`, `.github/workflows/incidents.yml` | Hata kaydı ↔ issue eşlemesi; repo secret'ı `LINKO_ADMIN_KEY` |
| Budama | `jobapp/maintenance.py` | `app_logs` `JOBAPP_APP_LOG_RETENTION_DAYS` (90) gün; **incidents asla budanmaz** |

Hata kaydı; ilk/son görülme, tekrar sayısı, örnek mesaj, son iz kaydı (traceback), issue numarası ve
durum geçmişini (`opened`, `issue_linked`, `resolved`, `reopened`) tutar. Ham loglar budansa bile kayıt kalır.
Aynı hata, mesajdaki sayı ve kimlikler atılarak tek kayıtta toplanır.

## Yerel kurulum (bir kez)

`.local/linko_cli.env` (gitignore'da):

```
LINKO_URL=https://ai-org.online
LINKO_ADMIN_KEY=<sunucudaki /etc/linko.env içindeki JOBAPP_ADMIN_KEY>
```

`/api/v1/*` Caddy basic auth'undan muaftır, Bearer anahtarı yeterlidir.

## Komutlar

```bash
python scripts/linko_logs.py logs --since 2h                     # son 2 saatin sunucu logu
python scripts/linko_logs.py logs --since 1d --level warning      # uyarı ve üstü
python scripts/linko_logs.py logs --source events --since 30m --kind request_finished --q 429
python scripts/linko_logs.py follow --level warning               # canlı takip
python scripts/linko_logs.py download --since 2026-10-17T00:00:00Z --until 2026-10-18T00:00:00Z
python scripts/linko_logs.py download --source events --since 7d  # .local/logs/ altına JSONL
python scripts/linko_logs.py incidents --status all               # açık + çözülmüş hata kayıtları
python scripts/linko_logs.py incident 3                           # ayrıntı, geçmiş, son 20 log
```

Zamanlar UTC'dir; ISO 8601 ya da göreli (`30m`, `2h`, `7d`) verilebilir. Tek indirme en fazla 31 gündür.

## Geliştirme döngüsü

1. **Başlarken:** `incidents` ile açık hata kayıtlarına, `logs --since 1d --level warning` ile son uyarılara bak.
   Kullanıcının bildirdiği sorunda önce ilgili aralığın loglarını indir, nedeni loga dayandır.
2. **Düzeltirken:** hatayı yeniden üreten test yaz (`python -m unittest discover -s tests`).
3. **Commit:** ilgili issue'yu kapatmak için mesaja `Fixes #<issue>` yaz. `main`'e merge → otomatik deploy.
4. **Kapanış:** issue kapanınca `incidents.yml` (en geç 30 dk; issue kapanışı da tetikler) kaydı
   **çözüldü** yapar ve issue'ya "✅ Çözüldü" yorumu düşer. Kapanıştan sonra hata yine görülürse issue
   yeniden açılır, kayıt `reopened` geçmişiyle tekrar açık olur. Hiçbir kayıt ve issue silinmez.
5. **Doğrulama:** deploy sonrası `follow --level error` veya `incidents` ile hatanın kesildiğini gör.

## Kurallar

- Log API'si yalnızca yönetici anahtarıyla çalışır; anahtar koda, commit'e, issue'ya yazılmaz.
- `audit.clean` hassas alanları gizler; yeni log satırlarına anahtar, şifre, çerez yazma.
- Hata kayıtlarını ve issue'ları silme; yanlış alarmı "not planned" olarak kapat (kayıt yine "çözüldü" geçmişiyle kalır).
- Kaynak (LinkedIn) 429 beklemeleri uyarıdır, hata kaydı açmaz; bekleme politikası loga bakılarak gevşetilmez.
