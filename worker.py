"""Standalone worker process consuming collector tasks and problem supervisor."""
import logging
import signal
import sys
import time

from jobapp import config, logstore, problems, server, service


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(levelname)s %(name)s: %(message)s")
    logstore.install()
    config.ensure_local_keys()
    logstore.ready()
    server.state.shutdown_event.clear()

    def shutdown(signum, frame):
        server.state.shutdown_event.set()
        with server.state.condition:
            server.state.condition.notify_all()
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, shutdown)
    service.start(server)
    problems.start(server)
    logging.getLogger("linko-worker").info("Worker başladı: veritabanı %s", config.DB_PATH)
    try:
        while not server.state.shutdown_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.state.shutdown_event.set()
        with server.state.condition:
            server.state.condition.notify_all()
        service.stop(server, timeout=30.0)
        logstore.shutdown()


if __name__ == "__main__":
    main()
