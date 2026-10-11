"""`python -m localagent serve`: start every installed connection, run the tools' background jobs, wait."""
import logging
import threading

log = logging.getLogger(__name__)
BACKGROUND_EVERY_SECONDS = 60


def run_background_jobs(tools: dict) -> None:
    for name, tool in tools.items():
        try:
            tool.background()
        except Exception:
            log.exception("Background job of tool %s failed", name)


def serve(connections: dict, tools: dict, stop_event: threading.Event | None = None) -> int:
    stop_event = stop_event or threading.Event()
    started = []
    try:
        for name, connection in connections.items():
            connection.start()
            started.append(connection)
            print(f"Connection '{name}' started.")
        print("Serving. Press Ctrl+C to stop.")
        seconds = 0
        while not stop_event.is_set():
            if seconds % BACKGROUND_EVERY_SECONDS == 0:
                run_background_jobs(tools)
            stop_event.wait(1)  # short waits: on Windows a long wait ignores Ctrl+C
            seconds += 1
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        for connection in reversed(started):
            try:
                connection.stop()
            except Exception:
                log.exception("Could not stop connection %s", connection.name)
    return 0
