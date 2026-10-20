# Linko Scrapper Light

Hesapsız LinkedIn ilan toplayıcı: Flask + SQLAlchemy (SQLite), tek süreçte Waitress HTTP
sunucusu ve otonom toplayıcı (`serve_service.py`). Arayüz `jobapp/templates/index.html`,
`jobapp/static/`. Ayrıntı: `README.md`, `SERVICE.md`.

Toplama hızı ve canlı iletişim incelemesinin kısa devir notu: `AI_CALISMA_BAGLAMI.md`.
Kanıtlar ve düzeltme sırası: `deney_sonuclari/TOPLAMA_HIZI_ANALIZI_2026-10-20.md`.
429 artışı için güncel öncelikler: `429_ARTISI_ANALIZI_VE_PLAN_2026-10-20.md`.
Yapılan deneyler ve ayrıntılı uygulama planı: `deney_sonuclari/DENEY_SONUCLARI_VE_AYRINTILI_PLAN_2026-10-20.md`.

## Çalışma kuralları
- Kullanıcı Türkçe konuşur; issue yanıtları, PR açıklamaları ve arayüz metinleri Türkçe olsun.
- Her değişiklikten sonra testleri çalıştır: `python -m unittest discover -s tests`. Yeni davranış için test ekle.
- `main`'e merge edilen her şey otomatik olarak canlı sunucuya kurulur (`.github/workflows/deploy.yml`). Testleri kırık PR açma.
- Canlı veritabanı var: şema değişiklikleri mevcut verilerle geriye uyumlu olmalı, veri silen göç yazma.
- Kaynak bekleme ve hız politikasını (`SERVICE_PLAN.md`) koru: güvenlik doğrulaması ve Retry-After beklemesi aşılmaz, tek collector süreci korunur. Varsayılan 10 saniyelik istek aralığı bir deneme ayarıdır; 429'u sıfırladığı veya verimi artırdığı varsayılmaz. Etkiyi benzer koşullardaki gerçek koşuların `rate_429` ve `frozen_ratio` değerleriyle doğrula.
- Tek collector süreci varsayımını bozma (çok worker'lı sunucu ekleme).
- Anahtar, şifre veya `.env` içeriğini koda/commit'e koyma.
- Geliştirme canlı loglara dayanır (`CALISMA_YONTEMI.md`): işe başlarken
  `python scripts/linko_logs.py incidents` ve `logs --since 1d --level warning` ile bak; sorun bildirilince ilgili
  aralığı `download` ile indir. Hata kaydını düzelten commit'e `Fixes #<issue>` yaz; hata kayıtlarını ve issue'ları silme.

## Canlı ortam
- VPS: kod `/opt/linko`, veri `/var/lib/linko`, ayarlar `/etc/linko.env`, servis `linko.service`.
- Uygulama `127.0.0.1:8016` dinler; önünde Caddy (HTTPS + basic auth, `job.ai-org.online`) vardır. Uygulama loopback
  isteklerine anahtarsız güvenir, bu yüzden `JOBAPP_HOST`'u dış arayüze açma.
- Ollama sunucuda yok; yerel yapay zekâ ve eşleştirme seçenekleri arayüzde kapalı görünür.
- Yedek: her deploy öncesi `/var/lib/linko/backups` (son 10); günlük `linko-backup.timer` →
  private `tracecorp24/job_collector-backups` (son 7 gün, `deploy/linko-backup.sh`).
- İzleme: `.github/workflows/uptime.yml` 15 dakikada bir `/healthz` kontrol eder.
- Loglar: `journalctl -u linko` (önemli olaylar, `audit.LOGGED`), Caddy erişim logu `/var/log/caddy/access.log`.
  Günlük bakım (`jobapp/maintenance.py`) kayıt tablolarını budar; yedek durumu `/var/lib/linko/backup_status.json`.
- Düzenli taramalar (`jobapp/watches.py`) kaynağı korur: yakın tarihli ilanlar, en yeniden sıralama, bilinen
  ilanın detayı yeniden indirilmez, tamamı bilinen sayfada durulur. Bu korumaları gevşetme.
