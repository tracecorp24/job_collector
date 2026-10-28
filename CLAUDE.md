# Linko & NextStep Ekosistemi — Geliştirici ve Ajan Rehberi

Bu çalışma alanı birbirine entegre çalışan **iki bağımsız Git projesini** barındırır:
1. **Job Collector (Linko Scrapper Light)**: Kök dizin (`.`) — Git: `tracecorp24/job_collector`
2. **NextStep AI**: Alt dizin (`./next_step`) — Git: `tracecorp24/next_step_v2`

---

## 1. Projeler ve Sistem Mimarisi

### A. Job Collector (Kök Dizin — Linko Scrapper Light)
- **Görevi:** Hesapsız LinkedIn iş ilanlarını otonom olarak kazır, temizler, şehir/ülke ve etiketlerle zenginleştirir; yerel/canlı SQLite veritabanında saklar ve REST API sunar.
- **Teknoloji:** Python 3.12, Flask, SQLAlchemy, Waitress (`serve_service.py`).
- **Arayüz:** `jobapp/templates/index.html`, `jobapp/static/`.
- **Canlı Adres:** `https://job.ai-org.online` (VPS `38.45.81.29`, Caddy arkasında `127.0.0.1:8016`).
- **Yerel Çalıştırma:** `python run.py` veya `launch.bat` (Port: 8016).
- **Testler:** `python -m unittest discover -s tests`

### B. NextStep AI (`./next_step`)
- **Görevi:** İlan havuzunu tüketerek kullanıcılara AI destekli CV hazırlama, ATS uyumluluk analizi, gerçekçi video/metin mülakat simülasyonu, Kanban başvuru takibi ve kariyer önerileri sunan modern web platformu.
- **Teknoloji:** Statik frontend (Vanilla JS/CSS, `index.html`), Flask backend (`app/`, `server.py`), DeepSeek/Docling/Gemini servisleri, SQLite/PostgreSQL.
- **İlan Entegrasyonu:** İlanlar doğrudan Job Collector'ın canlı API'sinden (`https://job.ai-org.online/api/v1/jobs`) `next_step/app/job_ai.py` adaptörüyle dinamik çekilir. Yerel dummy/kopya ilan tutulmaz.
- **Canlı Adres:** `https://nextstep.ai-org.online` (veya `https://ai-org.online`).
- **Yerel Çalıştırma:** `cd next_step` ardından `python server.py` veya `start.bat` (Port: 5500, tarayıcıda `http://localhost:5500` otomatik açılır).
- **Testler:** `cd next_step && pytest`

---

## 2. GitHub Actions ve CI/CD Otomasyonları

Sistem canlı web sitesiyle ve VPS ile GitHub Actions üzerinden sürekli haberleşir:

### Kök Depo (`tracecorp24/job_collector`)
- **`.github/workflows/deploy.yml`**: `main` dalına push/merge edildiğinde unit testleri çalıştırır. Testler geçerse VPS'e (`DEPLOY_HOST: 38.45.81.29`) SSH ile bağlanıp `deploy` komutunu çalıştırarak Linko'yu günceller.
- **`.github/workflows/incidents.yml`**: Canlı web sitesindeki (`https://job.ai-org.online`) hata kayıtlarını `scripts/incident_sync.py` ile GitHub Issues ile iki yönlü senkronize eder. Sitede hata oluşursa issue açılır; issue çözülüp deploy edildiğinde sitede "çözüldü" olarak işaretlenir.
- **`.github/workflows/uptime.yml`**: 15 dakikada bir `https://job.ai-org.online/healthz` adresini kontrol eder. 3 denemede yanıt alınamazsa GitHub'da `hata-kaydı` issue'su açar; site geri geldiğinde otomatik kapatıp sitenin loglarına kaydeder.
- **`.github/workflows/claude.yml`**: Issue veya PR yorumunda `@claude` etiketlendiğinde Claude Code botu tetiklenir, ilgili düzeltmeyi kodlayıp PR açar.

### NextStep Deposu (`tracecorp24/next_step_v2`)
- **`next_step/.github/workflows/ci.yml`**: Backend testleri (pytest), JS testleri ve güvenlik/lint kontrollerini yürütür.
- **`next_step/.github/workflows/deploy.yml`**: `main` dalına push yapıldığında CI kontrolleri başarılıysa VPS'e `deploy/nextstep-deploy.sh` üzerinden otomatik dağıtır.

---

## 3. Çalışma Kuralları

- **Dil:** Kullanıcı Türkçe konuşur; issue yanıtları, PR açıklamaları, arayüz metinleri ve kod yorumları **Türkçe** olmalıdır.
- **Test Zorunluluğu:** Değişiklik sonrası ilgili testleri mutlaka çalıştır (`python -m unittest discover -s tests` / `pytest`). Testleri kırık PR açma.
- **Canlı Veritabanı:** Canlıda aktif veri vardır; SQLite/Postgres şema değişiklikleri geriye dönük uyumlu olmalı, veri silen göçler yazılmamalıdır.
- **Kaynak Koruma Politikası (`SERVICE_PLAN.md`):** Güvenlik doğrulaması ve Retry-After beklemesi aşılmaz, tek collector süreci korunur. Tek collector süreci varsayımını bozacak çok worker'lı eklemeler yapma.
- **Güvenlik & Gizlilik:** `.env`, API anahtarları, şifreler veya `SIFRELER.txt` içeriği kesinlikle GitHub'a commit edilmez.
- **Canlı Loglar (`CALISMA_YONTEMI.md`):** Geliştirme öncesinde `python scripts/linko_logs.py incidents` ile canlı duruma bakılabilir.

---

## 4. Canlı Sunucu (VPS) ve Altyapı

- **VPS:** IP: `38.45.81.29` (Euronodes).
- **Yollar:** Kod `/opt/linko`, veri `/var/lib/linko`, ortam `/etc/linko.env`, servis `linko.service`.
- **Ters Vekil (Reverse Proxy):** Caddy (HTTPS + basic auth). Job Collector `127.0.0.1:8016` dinler; loopback isteklerine anahtarsız güvendiğinden dışarıya doğrudan açılmaz.
- **Yedekleme:** Her deploy öncesi yerel yedek (`/var/lib/linko/backups`); günlük otomatik GitHub yedeği (`tracecorp24/job_collector-backups`).
- **İzleme & Loglar:** `journalctl -u linko`, `/var/log/caddy/access.log`, `scripts/linko_logs.py`.

---

## 5. İlgili Belgeler
- Mimari ve metodoloji: [`CALISMA_YONTEMI.md`](file:///c:/Users/eminf/Desktop/job_collector/linko%20scrapper%20light/CALISMA_YONTEMI.md)
- Domain ve Caddy kurulumu: [`website_kurulum.md`](file:///c:/Users/eminf/Desktop/job_collector/linko%20scrapper%20light/website_kurulum.md)
- NextStep detaylı teknik spesifikasyonları: [`next_step/CLAUDE.md`](file:///c:/Users/eminf/Desktop/job_collector/linko%20scrapper%20light/next_step/CLAUDE.md)
- Devir bağlamı ve deneyler: [`AI_CALISMA_BAGLAMI.md`](file:///c:/Users/eminf/Desktop/job_collector/linko%20scrapper%20light/AI_CALISMA_BAGLAMI.md)

