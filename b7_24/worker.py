import signal
from threading import Event

from app import create_app
from app.services.video_processing import run_video_worker


app = create_app()
stop_event = Event()


def request_shutdown(_signal_number, _frame) -> None:
    stop_event.set()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)
    run_video_worker(app, stop_event)
