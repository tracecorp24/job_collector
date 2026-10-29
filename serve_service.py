"""Production entry point: one process, threaded HTTP and one collector."""
import logging
import sys
import os
import signal
import threading
from jobapp import config, server, service


def main():
    # journald zaman damgasını kendisi ekler; seviye ve kaynak yeterli.
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("waitress.queue").setLevel(logging.ERROR)
    # Kayıt yazıcısı uygulamadan ÖNCE kurulur: göç/kurtarma ve çökme satırları da app_logs'a düşer.
    from jobapp import logstore
    logstore.install()
    config.ensure_local_keys()
    if config.HOST not in ('127.0.0.1', '::1', 'localhost') and not (config.API_KEY and config.ADMIN_KEY):
        raise SystemExit('Dış ağ için JOBAPP_API_KEY ve JOBAPP_ADMIN_KEY ayarlayın.')
    from waitress import create_server
    application = server.create_app()
    logstore.ready()  # tablolar hazır; bekleyen kayıtlar app_logs'a akar
    server.state.shutdown_event.clear()
    http = create_server(application, host=config.HOST, port=config.PORT, threads=32, map={},
        channel_timeout=120, max_request_body_size=1024*1024)
    def only_events(environ, start_response):
        if environ.get('PATH_INFO') != '/events':
            start_response('404 Not Found', [('Content-Type', 'text/plain')])
            return [b'Not found']
        return application(environ, start_response)
    events = create_server(only_events, host='127.0.0.1',
        port=int(os.environ.get('JOBAPP_SSE_PORT', config.PORT + 2)), threads=32,
        map={}, channel_timeout=120, max_request_body_size=1024*1024)
    events_thread = threading.Thread(target=events.run, name='sse-http', daemon=True)
    events_thread.start()
    def shutdown(signum, frame):
        server.state.shutdown_event.set()
        with server.state.condition:
            server.state.condition.notify_all()
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, shutdown)
    split_worker = os.environ.get('JOBAPP_SPLIT_WORKER', '0') == '1'
    if not split_worker:
        service.start(server)
        from jobapp import problems
        problems.start(server)
    logging.getLogger("linko").info("Servis başladı: http://%s:%s, veritabanı %s, sürüm %s (split_worker=%s)",
                                    config.HOST, config.PORT, config.DB_PATH,
                                    config.version_info().get("sha"), split_worker)
    try:
        http.run()
    finally:
        server.state.shutdown_event.set()
        with server.state.condition:
            server.state.condition.notify_all()
        events.close()
        events_thread.join(timeout=2)
        if not split_worker:
            service.stop(server, timeout=30.0)
        logstore.shutdown()


if __name__ == '__main__':
    main()
