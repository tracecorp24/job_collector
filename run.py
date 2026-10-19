"""Entry point: start the jobapp web UI.

    python run.py

Opens the browser to the job board. Scraping is triggered from the UI's
"Scrape new jobs" button.
"""

import sys
import threading
import time
import webbrowser
import socket
import json
import urllib.request

# Force UTF-8 on Windows consoles (job text is often Turkish).
if sys.platform == "win32" and __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from jobapp import config
from jobapp.server import create_app


def main():
    url = f"http://{config.HOST}:{config.PORT}"
    probe_host = "127.0.0.1" if config.HOST == "0.0.0.0" else "::1" if config.HOST == "::" else config.HOST
    try:
        with socket.create_connection((probe_host, config.PORT), timeout=1):
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(url + "/api/scrape/status", timeout=3) as response:
                    status = json.load(response)
                if not isinstance(status, dict) or "running" not in status or "kind" not in status:
                    raise ValueError("Başka uygulama")
            except (OSError, ValueError):
                print(f"\n[HATA] {config.PORT} portu başka bir uygulama tarafından kullanılıyor.")
                return 1
            print(f"\nUygulama zaten çalışıyor: {url}")
            print("Mevcut taramalar korunuyor. Bu başlatıcı penceresi kapanabilir.")
            if config.OPEN_BROWSER:
                try:
                    webbrowser.open(url)
                except OSError:
                    print("Tarayıcı açılamadı. Yukarıdaki adresi tarayıcınızda açabilirsiniz.")
            return
    except OSError:
        pass
    app = create_app()
    config.ensure_local_keys()
    if config.HOST not in ('127.0.0.1', '::1', 'localhost') and not (config.API_KEY and config.ADMIN_KEY):
        raise SystemExit('Dış ağ için JOBAPP_API_KEY ve JOBAPP_ADMIN_KEY ayarlayın.')
    from waitress import create_server
    http = create_server(app, host=config.HOST, port=config.PORT, threads=12,
        channel_timeout=120, max_request_body_size=1024*1024)
    from jobapp import service, server
    service.start(server)

    print("\n" + "=" * 56)
    print("  Linko Scrapper Light")
    print(f"  Open: {url}")
    print("=" * 56 + "\n")
    print("Sunucu bu pencerede çalışıyor. Durdurmak için Ctrl+C kullanın.\n")

    if config.OPEN_BROWSER:
        def _open():
            time.sleep(1.2)
            try:
                webbrowser.open(url)
            except Exception:
                pass
        threading.Thread(target=_open, daemon=True).start()

    http.run()


if __name__ == "__main__":
    sys.exit(main() or 0)
