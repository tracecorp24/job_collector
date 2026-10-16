"""Production entry point: one process, threaded HTTP and one collector."""
from jobapp import config, server, service


def main():
    config.ensure_local_keys()
    if config.HOST not in ('127.0.0.1', '::1', 'localhost') and not (config.API_KEY and config.ADMIN_KEY):
        raise SystemExit('Dış ağ için JOBAPP_API_KEY ve JOBAPP_ADMIN_KEY ayarlayın.')
    from waitress import create_server
    application = server.create_app()
    http = create_server(application, host=config.HOST, port=config.PORT, threads=12,
        channel_timeout=120, max_request_body_size=1024*1024)
    service.start(server)
    http.run()


if __name__ == '__main__':
    main()
