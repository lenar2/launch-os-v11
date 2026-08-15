from __future__ import annotations

import signal
from threading import Event

from launch_os_v11.persistence.session import create_engine_from_settings, create_session_factory
from launch_os_v11.platform.config import get_settings
from launch_os_v11.runtime.scheduler import RuntimeScheduler
from launch_os_v11.runtime.transport import create_redis_job_queue


def main() -> None:
    settings = get_settings()
    engine = create_engine_from_settings(settings)
    factory = create_session_factory(engine)
    queue = create_redis_job_queue(settings.redis_url)
    stop_event = Event()

    def stop(signum: int, frame: object | None) -> None:
        del signum, frame
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    scheduler = RuntimeScheduler(session_factory=factory, queue=queue)
    try:
        while not stop_event.is_set():
            scheduler.run_once()
            stop_event.wait(5)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
