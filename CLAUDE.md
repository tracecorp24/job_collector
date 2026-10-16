# Linko Scrapper Light

Hesapsız LinkedIn ilan toplayıcı: Flask + SQLAlchemy (SQLite), tek süreçte Waitress HTTP
sunucusu ve otonom toplayıcı (`serve_service.py`). Arayüz `jobapp/templates/index.html`,
`jobapp/static/`. Ayrıntı: `README.md`, `SERVICE.md`.

## Çalışma kuralları
- Kullanıcı Türkçe konuşur; issue yanıtları, PR açıklamaları ve arayüz metinleri Türkçe olsun.
- Her değişiklikten sonra testleri çalıştır: `python -m unittest discover -s tests`. Yeni davranış için test ekle.
- `main`'e merge edilen her şey otomatik olarak canlı sunucuya kurulur (`.github/workflows/deploy.yml`). Testleri kırık PR açma.
- Canlı veritabanı var: şema değişiklikleri mevcut verilerle geriye uyumlu olmalı, veri silen göç yazma.
- Kaynak bekleme/hız sınırı politikasını (`SERVICE_PLAN.md`) gevşetme; bekleme süreleri kısaltılmaz, güvenlik doğrulaması aşılmaz.
- Tek collector süreci varsayımını bozma (çok worker'lı sunucu ekleme).
- Anahtar, şifre veya `.env` içeriğini koda/commit'e koyma.

## Canlı ortam
- VPS: kod `/opt/linko`, veri `/var/lib/linko`, ayarlar `/etc/linko.env`, servis `linko.service`.
- Uygulama `127.0.0.1:8016` dinler; önünde Caddy (HTTPS + basic auth) vardır. Uygulama loopback isteklerine
  anahtarsız güvenir, bu yüzden `JOBAPP_HOST`'u dış arayüze açma.
