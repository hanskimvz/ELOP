"""Main window: settings, run/stop, live progress, statistics, comparison."""

import math
import os
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..cli import config_from_args
from ..compare import compare_files, format_report
from ..config import PATTERNS, READ_MODES, SETUPS, STANDARD_BAUDRATES, TestConfig
from ..error_analysis import analyze_records
from ..error_analysis import format_report as format_error_report
from ..serial_port import list_ports_info
from ..storage import RESULTS_DIR, load_csv, save_results
from .histogram import HistogramWidget
from .worker import MeasureWorker


def _spin(lo, hi, value, suffix=""):
    w = QSpinBox()
    w.setRange(lo, hi)
    w.setValue(value)
    if suffix:
        w.setSuffix(" " + suffix)
    return w


def _dspin(lo, hi, value, decimals=1, suffix=""):
    w = QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setDecimals(decimals)
    w.setValue(value)
    if suffix:
        w.setSuffix(" " + suffix)
    return w


class MainWindow(QMainWindow):
    def __init__(self, cfg: TestConfig):
        super().__init__()
        self.setWindowTitle("UART Echo Latency Test v{}".format(__version__))
        self.resize(1200, 800)
        self.worker = None
        self.last_result = None
        self.last_cfg = None
        self._live = []
        self._live_errors = 0

        tabs = QTabWidget()
        tabs.addTab(self._build_measure_tab(), "측정")
        tabs.addTab(self._build_compare_tab(), "비교 (C − B)")
        self.setCentralWidget(tabs)

        self.refresh_ports()
        self.set_config(cfg)

    # ------------------------------------------------------------------ UI
    def _build_measure_tab(self) -> QWidget:
        # --- settings (left)
        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        refresh_btn = QPushButton("새로고침")
        refresh_btn.clicked.connect(self.refresh_ports)
        port_row = QHBoxLayout()
        port_row.addWidget(self.port_combo, 1)
        port_row.addWidget(refresh_btn)

        self.channel_spin = _spin(1, 8, 1)
        self.setup_combo = QComboBox()
        for key, desc in SETUPS.items():
            self.setup_combo.addItem("{} - {}".format(key, desc), key)
        self.fiber_spin = _dspin(0, 100000, 1000, 1, "m")

        g_target = QGroupBox("대상")
        f = QFormLayout(g_target)
        f.addRow("포트", port_row)
        f.addRow("장비 채널", self.channel_spin)
        f.addRow("측정 구성", self.setup_combo)
        f.addRow("fiber 길이", self.fiber_spin)

        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        for b in STANDARD_BAUDRATES:
            self.baud_combo.addItem(str(b))
        self.parity_combo = QComboBox()
        self.parity_combo.addItems(["N", "E", "O", "M", "S"])
        self.stop_combo = QComboBox()
        self.stop_combo.addItems(["1", "1.5", "2"])
        self.rtscts_check = QCheckBox("RTS/CTS")
        self.sweep_edit = QLineEdit()
        self.sweep_edit.setPlaceholderText("예: 115200, 921600, 2000000 (비우면 위 baudrate만)")

        g_uart = QGroupBox("UART")
        f = QFormLayout(g_uart)
        f.addRow("baudrate", self.baud_combo)
        f.addRow("baud 스윕", self.sweep_edit)
        f.addRow("parity", self.parity_combo)
        f.addRow("stop bits", self.stop_combo)
        f.addRow("흐름 제어", self.rtscts_check)

        self.size_spin = _spin(1, 4096, 16, "byte")
        self.pattern_combo = QComboBox()
        self.pattern_combo.addItems(PATTERNS)
        self.fixed_edit = QLineEdit()
        self.fixed_edit.setPlaceholderText("예: 0x0A")
        self.pattern_combo.currentTextChanged.connect(
            lambda t: self.fixed_edit.setEnabled(t == "fixed"))
        self.seq_check = QCheckBox("앞 4 byte에 시퀀스 번호")

        g_msg = QGroupBox("메시지")
        f = QFormLayout(g_msg)
        f.addRow("크기", self.size_spin)
        f.addRow("패턴", self.pattern_combo)
        f.addRow("fixed 값", self.fixed_edit)
        f.addRow("", self.seq_check)

        self.iter_spin = _spin(1, 10000000, 1000, "회")
        self.warmup_spin = _spin(0, 10000, 10, "회")
        self.interval_spin = _dspin(0, 60000, 10, 1, "ms")
        self.timeout_spin = _dspin(1, 60000, 1000, 0, "ms")
        self.readmode_combo = QComboBox()
        self.readmode_combo.addItems(READ_MODES)
        self.priority_check = QCheckBox("프로세스 우선순위 높임")
        self.note_edit = QLineEdit()

        g_run = QGroupBox("반복")
        f = QFormLayout(g_run)
        f.addRow("측정 횟수", self.iter_spin)
        f.addRow("warmup", self.warmup_spin)
        f.addRow("간격", self.interval_spin)
        f.addRow("타임아웃", self.timeout_spin)
        f.addRow("읽기 방식", self.readmode_combo)
        f.addRow("", self.priority_check)
        f.addRow("메모", self.note_edit)

        self.autosave_check = QCheckBox("완료 시 자동 저장 (CSV)")
        self.autosave_check.setChecked(True)
        self.xlsx_check = QCheckBox("Excel(.xlsx)도 저장")
        self.xlsx_check.setChecked(True)

        self.start_btn = QPushButton("시작")
        self.start_btn.clicked.connect(self.start)
        self.stop_btn = QPushButton("중지")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        self.save_btn = QPushButton("결과 저장")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self.save)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addWidget(self.save_btn)

        left = QWidget()
        lv = QVBoxLayout(left)
        for g in (g_target, g_uart, g_msg, g_run):
            lv.addWidget(g)
        lv.addWidget(self.autosave_check)
        lv.addWidget(self.xlsx_check)
        lv.addLayout(btn_row)
        lv.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(left)
        scroll.setMinimumWidth(440)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # --- results (right)
        self.progress_bar = QProgressBar()
        self.live_label = QLabel("대기 중")
        self.live_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.stats_table = QTableWidget()
        self.stats_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.stats_table.verticalHeader().setDefaultSectionSize(20)

        self.hist = HistogramWidget()

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)

        right_split = QSplitter(Qt.Vertical)
        top = QWidget()
        tv = QVBoxLayout(top)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.addWidget(self.progress_bar)
        tv.addWidget(self.live_label)
        tv.addWidget(self.hist, 1)
        self.error_view = QPlainTextEdit()
        self.error_view.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        self.error_view.setFont(mono)
        self.error_view.setPlaceholderText("측정이 끝나면 에러 분석 결과가 표시됩니다.")
        open_btn = QPushButton("저장된 CSV 분석...")
        open_btn.clicked.connect(self.analyze_file)
        err_tab = QWidget()
        ev = QVBoxLayout(err_tab)
        ev.setContentsMargins(0, 0, 0, 0)
        ev.addWidget(self.error_view, 1)
        ev.addWidget(open_btn, 0, Qt.AlignRight)

        self.result_tabs = QTabWidget()
        self.result_tabs.addTab(self.stats_table, "통계")
        self.result_tabs.addTab(err_tab, "에러 분석")

        right_split.addWidget(top)
        right_split.addWidget(self.result_tabs)
        right_split.addWidget(self.log_view)
        right_split.setSizes([300, 360, 120])

        split = QSplitter(Qt.Horizontal)
        split.addWidget(scroll)
        split.addWidget(right_split)
        split.setSizes([460, 740])
        return split

    def _build_compare_tab(self) -> QWidget:
        self.ref_edit = QLineEdit()
        self.tgt_edit = QLineEdit()
        ref_btn = QPushButton("찾기")
        ref_btn.clicked.connect(lambda: self._browse_csv(self.ref_edit))
        tgt_btn = QPushButton("찾기")
        tgt_btn.clicked.connect(lambda: self._browse_csv(self.tgt_edit))

        form = QFormLayout()
        row = QHBoxLayout()
        row.addWidget(self.ref_edit, 1)
        row.addWidget(ref_btn)
        form.addRow("기준 (B 또는 C0) CSV", row)
        row = QHBoxLayout()
        row.addWidget(self.tgt_edit, 1)
        row.addWidget(tgt_btn)
        form.addRow("대상 (C) CSV", row)

        run_btn = QPushButton("비교")
        run_btn.clicked.connect(self.run_compare)

        self.compare_view = QPlainTextEdit()
        self.compare_view.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        self.compare_view.setFont(mono)

        help_label = QLabel(
            "링크 왕복 지연 ≈ mean(C) − mean(B),  fiber 왕복 지연 ≈ mean(C) − mean(C0).\n"
            "USB 지연이 회차마다 흔들리므로 평균끼리만 뺄 수 있습니다. "
            "같은 어댑터·같은 USB 포트·같은 설정으로 측정한 파일을 비교하세요.")
        help_label.setWordWrap(True)

        w = QWidget()
        v = QVBoxLayout(w)
        v.addLayout(form)
        v.addWidget(run_btn)
        v.addWidget(help_label)
        v.addWidget(self.compare_view, 1)
        return w

    # ------------------------------------------------------------- config
    def refresh_ports(self):
        current = self.port_combo.currentText()
        self.port_combo.clear()
        for p in list_ports_info():
            self.port_combo.addItem(p.label(), p.device)
        if current:
            self._select_port(current)

    def _select_port(self, device: str):
        for i in range(self.port_combo.count()):
            if (self.port_combo.itemData(i) or "").upper() == device.upper():
                self.port_combo.setCurrentIndex(i)
                return
        self.port_combo.setEditText(device)

    def _port_device(self) -> str:
        idx = self.port_combo.currentIndex()
        text = self.port_combo.currentText().strip()
        if idx >= 0 and self.port_combo.itemText(idx) == text:
            return self.port_combo.itemData(idx)
        return text.split(" ")[0]

    def set_config(self, cfg: TestConfig):
        self._select_port(cfg.port)
        self.channel_spin.setValue(cfg.channel_no)
        self.setup_combo.setCurrentIndex(max(0, self.setup_combo.findData(cfg.setup)))
        self.fiber_spin.setValue(cfg.fiber_length_m)
        self.baud_combo.setEditText(str(cfg.baudrate))
        self.sweep_edit.setText(", ".join(str(b) for b in cfg.baud_sweep))
        self.parity_combo.setCurrentText(cfg.parity)
        self.stop_combo.setCurrentText("{:g}".format(cfg.stopbits))
        self.rtscts_check.setChecked(cfg.rtscts)
        self.size_spin.setValue(cfg.payload_size)
        self.pattern_combo.setCurrentText(cfg.pattern)
        self.fixed_edit.setText("0x{:02X}".format(cfg.fixed_byte))
        self.fixed_edit.setEnabled(cfg.pattern == "fixed")
        self.seq_check.setChecked(cfg.use_seq)
        self.iter_spin.setValue(cfg.iterations)
        self.warmup_spin.setValue(cfg.warmup)
        self.interval_spin.setValue(cfg.interval_ms)
        self.timeout_spin.setValue(cfg.timeout_ms)
        self.readmode_combo.setCurrentText(cfg.read_mode)
        self.priority_check.setChecked(cfg.high_priority)
        self.note_edit.setText(cfg.note)

    def get_config(self) -> TestConfig:
        sweep_text = self.sweep_edit.text().replace(" ", "")
        cfg = TestConfig(
            port=self._port_device(),
            channel_no=self.channel_spin.value(),
            setup=self.setup_combo.currentData(),
            fiber_length_m=self.fiber_spin.value(),
            baudrate=int(self.baud_combo.currentText()),
            parity=self.parity_combo.currentText(),
            stopbits=float(self.stop_combo.currentText()),
            rtscts=self.rtscts_check.isChecked(),
            payload_size=self.size_spin.value(),
            pattern=self.pattern_combo.currentText(),
            fixed_byte=int(self.fixed_edit.text().strip() or "0x5A", 0),
            use_seq=self.seq_check.isChecked(),
            iterations=self.iter_spin.value(),
            warmup=self.warmup_spin.value(),
            interval_ms=self.interval_spin.value(),
            timeout_ms=self.timeout_spin.value(),
            read_mode=self.readmode_combo.currentText(),
            baud_sweep=[int(x) for x in sweep_text.split(",") if x],
            high_priority=self.priority_check.isChecked(),
            note=self.note_edit.text(),
        )
        if cfg.stopbits == 1.0:
            cfg.stopbits = 1
        elif cfg.stopbits == 2.0:
            cfg.stopbits = 2
        cfg.validate()
        return cfg

    # ---------------------------------------------------------------- run
    def start(self):
        try:
            cfg = self.get_config()
        except ValueError as e:
            QMessageBox.warning(self, "설정 오류", str(e))
            return

        self.last_cfg = cfg
        self.last_result = None
        self.stats_table.clear()
        self.stats_table.setRowCount(0)
        self.stats_table.setColumnCount(0)
        self.error_view.clear()
        self._log("=== 측정 시작: {} / 구성 {} / ch{} ===".format(cfg.port, cfg.setup, cfg.channel_no))

        self.worker = MeasureWorker(cfg, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.stats_ready.connect(self._on_stats)
        self.worker.log.connect(self._log)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._on_thread_finished)
        self._current_baud = None
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.save_btn.setEnabled(False)
        self.worker.start()

    def stop(self):
        if self.worker:
            self.worker.stop()
            self._log("중지 요청 - 현재 회차가 끝나면 멈춥니다")

    def _on_progress(self, baud, done, total, latencies, errors):
        if baud != self._current_baud:
            self._current_baud = baud
            self._live = []
            self._live_errors = 0
            self.hist.clear("{} bps".format(baud))
        self._live.extend(latencies)
        self._live_errors += errors
        self.hist.add(latencies)
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(done)

        if self._live:
            n = len(self._live)
            mean = sum(self._live) / n
            self.live_label.setText(
                "{} bps   {}/{}   ok {}   오류 {}   last {:.1f} us   mean {:.1f} us   min {:.1f}   max {:.1f}"
                .format(baud, done, total, n, self._live_errors, self._live[-1], mean,
                        min(self._live), max(self._live)))
        else:
            self.live_label.setText("{} bps   {}/{}   ok 0   오류 {}".format(
                baud, done, total, self._live_errors))

    def _on_stats(self, st):
        rows = st.as_rows()[1:]
        table = self.stats_table
        if table.columnCount() == 0:
            table.setRowCount(len(rows))
            table.setVerticalHeaderLabels(["{} ({})".format(l, u) if u else l for l, _, u in rows])
        col = table.columnCount()
        table.setColumnCount(col + 1)
        table.setHorizontalHeaderItem(col, QTableWidgetItem("{} bps".format(st.baudrate)))
        for i, (_, value, _) in enumerate(rows):
            if isinstance(value, float):
                text = "-" if math.isnan(value) else (
                    "{:.3e}".format(value) if 0 < abs(value) < 0.001 else "{:.2f}".format(value))
            else:
                text = str(value)
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(i, col, item)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

    def _on_done(self, result):
        self.last_result = result
        state = "중지됨" if result.stopped else "완료"
        self._log("=== {}: {} 회 기록, 건너뛴 baud {} ===".format(
            state, len(result.records), result.skipped or "없음"))
        if result.records:
            self.error_view.setPlainText(format_error_report(result.records, result.errors))
            if any(r.status != "OK" for r in result.records):
                self.result_tabs.setCurrentIndex(1)
                self._log("오류가 있습니다 - '에러 분석' 탭을 확인하세요")
            self.save_btn.setEnabled(True)
            if self.autosave_check.isChecked():
                self.save()

    def _on_failed(self, tb):
        self._log("오류:\n" + tb)
        QMessageBox.critical(self, "측정 오류", tb.strip().splitlines()[-1])

    def _on_thread_finished(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.worker = None

    def save(self):
        if not self.last_result or not self.last_result.records:
            return
        try:
            paths = save_results(self.last_cfg, self.last_result.started,
                                 self.last_result.records, self.last_result.stats,
                                 xlsx=self.xlsx_check.isChecked())
        except OSError as e:
            QMessageBox.critical(self, "저장 오류", str(e))
            return
        for p in paths:
            self._log("저장: {}".format(p))
        # 비교 탭에 바로 쓸 수 있도록
        csv_path = paths[0]
        if self.last_cfg.setup in ("B", "C0"):
            self.ref_edit.setText(csv_path)
        elif self.last_cfg.setup == "C":
            self.tgt_edit.setText(csv_path)

    def analyze_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "결과 CSV 선택", RESULTS_DIR, "CSV (*.csv)")
        if not path:
            return
        try:
            _, rows = load_csv(path)
            text = format_error_report(rows, analyze_records(rows))
        except (OSError, ValueError, KeyError) as e:
            QMessageBox.critical(self, "분석 오류", str(e))
            return
        self.error_view.setPlainText("# {}\n\n{}".format(path, text))
        self.result_tabs.setCurrentIndex(1)

    # ------------------------------------------------------------ compare
    def _browse_csv(self, edit: QLineEdit):
        start = os.path.dirname(edit.text()) if edit.text() else RESULTS_DIR
        path, _ = QFileDialog.getOpenFileName(self, "결과 CSV 선택", start, "CSV (*.csv)")
        if path:
            edit.setText(path)

    def run_compare(self):
        ref, tgt = self.ref_edit.text().strip(), self.tgt_edit.text().strip()
        if not (os.path.isfile(ref) and os.path.isfile(tgt)):
            QMessageBox.warning(self, "비교", "두 CSV 파일을 선택하세요.")
            return
        try:
            rows, ref_meta, tgt_meta = compare_files(ref, tgt)
        except (OSError, ValueError, KeyError) as e:
            QMessageBox.critical(self, "비교 오류", str(e))
            return
        self.compare_view.setPlainText(format_report(rows, ref_meta, tgt_meta))

    # --------------------------------------------------------------- misc
    def _log(self, msg: str):
        self.log_view.appendPlainText(msg)

    def closeEvent(self, event):
        if self.worker:
            self.worker.stop()
            self.worker.wait(3000)
        event.accept()


def run_gui(args) -> int:
    app = QApplication(sys.argv)
    win = MainWindow(config_from_args(args))
    win.show()
    return app.exec_()
