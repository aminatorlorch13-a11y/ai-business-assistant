from __future__ import annotations

import logging
import math
import threading

from app.forge.worker import ForgeWorker

logger = logging.getLogger(__name__)


class ForgeWorkerRunner:
    """Run Forge job processing independently of foreground conversations."""

    def __init__(
        self,
        worker: ForgeWorker,
        *,
        poll_interval: float = 1.0,
    ) -> None:
        if not isinstance(worker, ForgeWorker):
            raise TypeError("worker must be a ForgeWorker.")
        if isinstance(poll_interval, bool) or not isinstance(
            poll_interval, (int, float)
        ):
            raise TypeError("poll_interval must be a positive number.")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be greater than zero.")

        self._worker = worker
        self._poll_interval = float(poll_interval)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self) -> ForgeWorkerRunner:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self

            self._stop_event = threading.Event()
            self._thread = threading.Thread(
                target=self._run,
                name="amination-forge-worker",
                daemon=True,
            )
            self._thread.start()

        return self

    def stop(self, timeout: float | None = 10.0) -> bool:
        if timeout is not None:
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
                raise TypeError("timeout must be a number or None.")
            try:
                finite_timeout = math.isfinite(timeout)
            except OverflowError:
                finite_timeout = False
            if not finite_timeout or timeout < 0:
                raise ValueError("timeout must be finite and non-negative or None.")

        # Coordinate shutdown with start() so the stop event cannot be replaced.
        with self._lock:
            thread = self._thread
            if thread is None:
                return True
            self._stop_event.set()
            if thread is threading.current_thread():
                return False
            thread.join(timeout)
            return not thread.is_alive()


    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._worker.run_once()
            except (Exception, SystemExit):
                logger.exception("Forge worker iteration failed; runner will continue.")

            self._stop_event.wait(self._poll_interval)
