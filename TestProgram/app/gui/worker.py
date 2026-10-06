"""QThread wrapper around run_sweep."""

import threading
import traceback

from PyQt5.QtCore import QThread, pyqtSignal

from ..config import TestConfig
from ..sweep import run_sweep


class MeasureWorker(QThread):
    # baudrate, done, total, new latencies (us, OK only), new error count
    progress = pyqtSignal(int, int, int, list, int)
    stats_ready = pyqtSignal(object)   # Stats
    log = pyqtSignal(str)
    done = pyqtSignal(object)          # SweepResult
    failed = pyqtSignal(str)

    def __init__(self, cfg: TestConfig, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            result = run_sweep(
                self.cfg,
                self._stop,
                progress=self._on_progress,
                on_stats=self.stats_ready.emit,
                log=self.log.emit,
            )
            self.done.emit(result)
        except Exception:
            self.failed.emit(traceback.format_exc())

    def _on_progress(self, baud, done, total, new_records):
        lat = [r.latency_us for r in new_records if r.status == "OK"]
        errors = sum(1 for r in new_records if r.status != "OK")
        self.progress.emit(baud, done, total, lat, errors)
