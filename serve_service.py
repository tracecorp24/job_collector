"""Production entry point: one process, threaded HTTP and one collector."""
import logging
import sys
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
    http = create_server(application, host=config.HOST, port=config.PORT, threads=12,
        channel_timeout=120, max_request_body_size=1024*1024)
    service.start(server)
    from jobapp import problems
    problems.start(server)
    logging.getLogger("linko").info("Servis başladı: http://%s:%s, veritabanı %s, sürüm %s", config.HOST, config.PORT, config.DB_PATH,
                                    config.version_info().get("sha"))
    try:
        http.run()
    finally:
        service.stop(server, timeout=30.0)
        logstore.shutdown()


if __name__ == '__main__':
    main()
