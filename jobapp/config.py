"""Portable configuration for Linko Scrapper Light (accountless only)."""
import os
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(PACKAGE_DIR)

def _env(name, default):
    return os.environ.get(name) or default

DB_PATH = _env("JOBAPP_DB_PATH", os.path.join(PACKAGE_DIR, "jobs.db"))
DB_URL = f"sqlite:///{DB_PATH}"
HOST = _env("JOBAPP_HOST", "127.0.0.1")
PORT = int(_env("JOBAPP_PORT", "8016"))
OPEN_BROWSER = _env("JOBAPP_OPEN_BROWSER", "1") not in ("0", "false", "False")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_MODEL = _env("JOBAPP_LLM_MODEL", "claude-haiku-4-5")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = _env("JOBAPP_GROQ_MODEL", "openai/gpt-oss-120b")
# Toplu ilan analizi için küçük/hızlı model; ücretsiz kotayı (8k token/dk) daha çok ilana yayar.
GROQ_CLASSIFY_MODEL = _env("JOBAPP_GROQ_CLASSIFY_MODEL", "openai/gpt-oss-20b")
OLLAMA_HOST = _env("JOBAPP_OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = _env("JOBAPP_OLLAMA_MODEL", "qwen3.5:9b")
OLLAMA_EMBED_MODEL = _env("JOBAPP_OLLAMA_EMBED_MODEL", "qwen3-embedding:8b")
OLLAMA_TIMEOUT_SECONDS = int(_env("JOBAPP_OLLAMA_TIMEOUT_SECONDS", "180"))
SOURCE_LINKEDIN = "linkedin"
ACCOUNTLESS_OUTPUT_DIR = _env("JOBAPP_ACCOUNTLESS_OUTPUT_DIR", os.path.join(ROOT_DIR, "accountless_searches"))
LEGACY_JOB_LIST_DIR = _env("JOBAPP_LEGACY_JOB_LIST_DIR", os.path.join(ROOT_DIR, "imports"))
REQUEST_INTERVAL = float(_env("JOBAPP_REQUEST_INTERVAL", "10.0"))
MAX_RETRIES = int(_env("JOBAPP_MAX_RETRIES", "10"))
RETRY_BASE_COOLDOWN = float(_env("JOBAPP_RETRY_BASE_COOLDOWN", "60.0"))
DEFAULT_LOCATION = _env("JOBAPP_DEFAULT_LOCATION", "Istanbul, Turkey")
MIN_REQUEST_INTERVAL = max(1.0, float(_env("JOBAPP_MIN_REQUEST_INTERVAL", "10.0")))
# Önce kart: taramada yeni ilanın detayı istenmez, arka planda tamamlanır (jobapp/details.py).
DEFER_DETAILS = _env("JOBAPP_DEFER_DETAILS", "1") not in ("0", "false", "False")
# İstek aralığına eklenen rastgele pay (0.15 = %0–15); düzenli ritim bot gibi görünür.
REQUEST_JITTER = max(0.0, float(_env("JOBAPP_REQUEST_JITTER", "0.15")))
# Eşik tabanlı erken durma: sayfadaki yeni ilan oranı bu oranın altına inerse arama tamamlanır.
LOW_YIELD_THRESHOLD = max(0.0, min(1.0, float(_env("JOBAPP_LOW_YIELD_THRESHOLD", "0.20"))))
DETAIL_CACHE_TTL_SECONDS = max(0.0, float(_env("JOBAPP_DETAIL_CACHE_TTL_SECONDS", "259200")))
DETAIL_MISSING_TTL_SECONDS = max(0.0, float(_env("JOBAPP_DETAIL_MISSING_TTL_SECONDS", "300")))
ACCESS_PAUSE_SECONDS = max(1.0, float(_env("JOBAPP_ACCESS_PAUSE_SECONDS", "900")))
ACCESS_FAILURE_THRESHOLD = max(1, int(_env("JOBAPP_ACCESS_FAILURE_THRESHOLD", "3")))
ACCESS_FAILURE_WINDOW_SECONDS = max(1.0, float(_env("JOBAPP_ACCESS_FAILURE_WINDOW_SECONDS", "3600")))
NETWORK_LEASE_SECONDS = 60.0
INLINE_RETRY_WAIT_SECONDS = 30.0
MAX_ACCESS_PAUSE_SECONDS = max(ACCESS_PAUSE_SECONDS, float(_env("JOBAPP_MAX_ACCESS_PAUSE_SECONDS", "21600")))
SERVICE_POLL_SECONDS = max(1.0, float(_env("JOBAPP_SERVICE_POLL_SECONDS", "5")))
# Kayıt tablolarının saklama süreleri (gün); günlük bakım daha eskilerini siler.
EVENT_RETENTION_DAYS = max(1, int(_env("JOBAPP_EVENT_RETENTION_DAYS", "90")))
CHANGES_RETENTION_DAYS = max(1, int(_env("JOBAPP_CHANGES_RETENTION_DAYS", "60")))
APP_LOG_RETENTION_DAYS = max(1, int(_env("JOBAPP_APP_LOG_RETENTION_DAYS", "90")))
# Deploy betiğinin yazdığı sürüm bilgisi ve veritabanı yazılamazken logların düştüğü yedek klasör.
VERSION_PATH = _env("JOBAPP_VERSION_PATH", os.path.join(os.path.dirname(DB_PATH), "version.json"))
SPOOL_DIR = _env("JOBAPP_SPOOL_DIR", os.path.join(os.path.dirname(DB_PATH), "spool"))
_version_cache = {}


def version_info():
    """Canlıda `/var/lib/linko/version.json` (deploy yazar); yoksa sha "bilinmiyor". Dosya değişince yeniden okunur."""
    import json
    try:
        stamp = (VERSION_PATH, os.stat(VERSION_PATH).st_mtime_ns)
    except OSError:
        return {"sha": "bilinmiyor"}
    if _version_cache.get("stamp") != stamp:
        try:
            with open(VERSION_PATH, encoding="utf-8") as file:
                info = json.load(file)
            _version_cache.update(stamp=stamp, info=info if isinstance(info, dict) and info.get("sha") else {"sha": "bilinmiyor"})
        except (OSError, ValueError):
            return {"sha": "bilinmiyor"}
    return _version_cache["info"]
# linko-backup betiğinin yazdığı sunucu dışı yedek durumu.
BACKUP_STATUS_PATH = _env("JOBAPP_BACKUP_STATUS_PATH", os.path.join(os.path.dirname(DB_PATH), "backup_status.json"))
API_KEY = os.environ.get("JOBAPP_API_KEY", "")
ADMIN_KEY = os.environ.get("JOBAPP_ADMIN_KEY", "")
# Yalnızca /api/v1/logs* ve /api/v1/incidents* uçlarını açar; yönetim işlemlerine yetkisi yoktur.
LOG_KEY = os.environ.get("JOBAPP_LOG_KEY", "")


def ensure_local_keys():
    """Persist local-only credentials without printing them or changing remote config."""
    global API_KEY, ADMIN_KEY
    if HOST not in ('127.0.0.1', '::1', 'localhost') or API_KEY and ADMIN_KEY:
        return
    import json
    import secrets
    from pathlib import Path
    path = Path(ROOT_DIR) / '.local' / 'service_keys.json'
    path.parent.mkdir(exist_ok=True)
    if not path.exists():
        from .search_export import _write_json
        _write_json(path, {'api_key':secrets.token_urlsafe(32), 'admin_key':secrets.token_urlsafe(32)})
        if os.name != 'nt':
            path.chmod(0o600)
    keys = json.loads(path.read_text(encoding='utf-8'))
    API_KEY = API_KEY or keys['api_key']
    ADMIN_KEY = ADMIN_KEY or keys['admin_key']
