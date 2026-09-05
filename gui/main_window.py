"""Main window (PySide6): drag-drop jars, per-version catalog + editors, and Generate.

The **MC version** selector at the top drives everything: the item catalog, the tier/keys
data and the output path are all per-version, because mods change their materials/items
between versions (e.g. Blue Skies renamed cherry -> comet). Sword patterns are shared.

Generation reuses the existing CLI unchanged — it runs ``python main.py --mc <v> [path]``
as a subprocess (QProcess) and streams the output into a log pane. The output root shows the
path saved in ``.env`` for the selected version; editing it writes back to ``.env``.
"""

import os
import sys

from PySide6.QtCore import Qt, QProcess
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QTabWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QPushButton, QLabel, QComboBox, QLineEdit, QGroupBox,
    QPlainTextEdit, QFileDialog, QMessageBox,
)

import main as generator  # CLI module, stdlib-only, no import side effects
from catalog.cache import Catalog
from core.tiers_model import TiersModel, REPO_ROOT
from core.patterns_model import PatternsModel
from core import env_file
from gui.catalog_view import CatalogView
from gui.tier_editor import TierEditor
from gui.pattern_editor import PatternEditor

ENV_PATH = os.path.join(REPO_ROOT, ".env")
DEFAULT_VERSION = "1.21.1"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.resize(1100, 760)

        self._version = (DEFAULT_VERSION if DEFAULT_VERSION in generator.VERSION_PROFILES
                         else next(iter(generator.VERSION_PROFILES)))
        self._catalog = Catalog(self._version)
        self._catalog.load()
        self._model = TiersModel(self._version)
        self._model.load()
        self._patterns = PatternsModel(self._version)
        self._patterns.load()
        self._proc: QProcess | None = None

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet("font-family: monospace; font-size: 11px;")

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_tiers_tab(), "Tiers && Items")
        self._tabs.addTab(self._build_patterns_tab(), "Sword Patterns")
        # Keep the pattern editor's tier list in sync with tier add/deletes.
        self._tabs.currentChanged.connect(self._on_tab_changed)

        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self._build_generate_box())
        bl.addWidget(QLabel("<b>Output log</b>"))
        bl.addWidget(self._log, 1)

        vsplit = QSplitter(Qt.Vertical)
        vsplit.addWidget(self._tabs)
        vsplit.addWidget(bottom)
        vsplit.setStretchFactor(0, 3)
        vsplit.setStretchFactor(1, 2)

        central = QWidget()
        cl = QVBoxLayout(central)
        cl.addLayout(self._build_top_bar())
        cl.addWidget(vsplit, 1)
        self.setCentralWidget(central)

        self._tier_editor.statusMessage.connect(self.statusBar().showMessage)
        self._pattern_editor.statusMessage.connect(self.statusBar().showMessage)
        self._load_output_from_env()
        self._update_title()
        self.statusBar().showMessage("Drop .jar files to build the item catalog for this version.")

    # --- layout ---------------------------------------------------------------

    def _build_top_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.addWidget(QLabel("<b>MC version:</b>"))
        self._version_combo = QComboBox()
        self._version_combo.addItems(list(generator.VERSION_PROFILES))
        self._version_combo.setCurrentText(self._version)
        self._version_combo.currentTextChanged.connect(self._on_version_changed)
        bar.addWidget(self._version_combo)
        bar.addWidget(QLabel("— catalog, tiers &amp; output are saved per version"))
        bar.addStretch(1)
        return bar

    def _build_tiers_tab(self) -> QWidget:
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._build_left())

        tier_panel = QWidget()
        tv = QVBoxLayout(tier_panel)
        tv.addWidget(QLabel("<b>Tier editor</b>"))
        self._tier_editor = TierEditor(self._model, self._catalog_view.current_item)
        tv.addWidget(self._tier_editor)
        tv.addStretch(1)
        split.addWidget(tier_panel)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        return split

    def _build_patterns_tab(self) -> QWidget:
        self._pattern_editor = PatternEditor(self._patterns, self._model.tier_names)
        return self._pattern_editor

    def _on_tab_changed(self, index: int) -> None:
        # Refresh the pattern editor's Template-set list when it becomes visible, so tiers
        # added/removed on the other tab show up as override targets.
        if self._tabs.widget(index) is self._pattern_editor:
            self._pattern_editor.reload()

    def _build_left(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        header = QHBoxLayout()
        header.addWidget(QLabel("<b>Item catalog</b>"))
        header.addStretch(1)
        add_btn = QPushButton("Add jars…")
        add_btn.clicked.connect(self._pick_jars)
        header.addWidget(add_btn)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_catalog)
        header.addWidget(clear_btn)
        layout.addLayout(header)

        self._catalog_view = CatalogView(self._catalog)
        layout.addWidget(self._catalog_view, 1)
        return panel

    def _build_generate_box(self) -> QGroupBox:
        box = QGroupBox("Generate")
        outer = QVBoxLayout(box)

        form = QFormLayout()
        path_row = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("mod-repo root for this version (empty = local ./<loader>)")
        self._path_edit.textChanged.connect(self._update_target_warning)
        self._path_edit.editingFinished.connect(self._commit_output_path)
        path_row.addWidget(self._path_edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_output_dir)
        path_row.addWidget(browse)
        form.addRow("Output root (.env):", path_row)
        outer.addLayout(form)

        self._target_label = QLabel()
        self._target_label.setWordWrap(True)
        outer.addWidget(self._target_label)

        self._generate_btn = QPushButton("Generate")
        self._generate_btn.clicked.connect(self._on_generate)
        outer.addWidget(self._generate_btn)
        return box

    # --- version switching ----------------------------------------------------

    def _update_title(self) -> None:
        self.setWindowTitle(f"Knaves' Needs — Recipe Manager  ·  MC {self._version}")

    def _on_version_changed(self, new_version: str) -> None:
        if not new_version or new_version == self._version:
            return
        # Tiers/keys AND patterns are per-version, so both may have unsaved edits.
        if self._model.dirty or self._patterns.dirty:
            choice = QMessageBox.question(
                self, "Unsaved changes",
                f"Save changes to {self._version} data before switching to {new_version}?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
            if choice == QMessageBox.Cancel:
                self._version_combo.blockSignals(True)
                self._version_combo.setCurrentText(self._version)
                self._version_combo.blockSignals(False)
                return
            if choice == QMessageBox.Save:
                if self._model.dirty:
                    self._model.save()
                if self._patterns.dirty:
                    self._patterns.save()

        self._version = new_version
        self._model.set_version(new_version)       # loads that version's tiers/keys/mods
        self._tier_editor.reload()
        self._patterns.set_version(new_version)    # loads that version's patterns + overrides
        self._pattern_editor.reload()
        self._catalog.set_version(new_version)     # loads that version's cached catalog
        self._catalog_view.refresh()
        self._load_output_from_env()
        self._update_title()
        self.statusBar().showMessage(
            f"Switched to MC {new_version}: {len(self._catalog.items)} catalog items, "
            f"{len(self._model.tiers)} tiers.")

    # --- drag & drop ----------------------------------------------------------

    def dragEnterEvent(self, event) -> None:
        if self._urls_with_jars(event):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        jars = self._urls_with_jars(event)
        if jars:
            self._add_jars(jars)
            event.acceptProposedAction()

    @staticmethod
    def _urls_with_jars(event) -> list[str]:
        md = event.mimeData()
        if not md.hasUrls():
            return []
        return [u.toLocalFile() for u in md.urls()
                if u.isLocalFile() and u.toLocalFile().lower().endswith(".jar")]

    # --- catalog actions ------------------------------------------------------

    def _pick_jars(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add mod / Minecraft jars", "", "Jar files (*.jar)")
        if paths:
            self._add_jars(paths)

    def _add_jars(self, paths: list[str]) -> None:
        total = 0
        for path in paths:
            try:
                total += self._catalog.add_jar(path)
            except (ValueError, FileNotFoundError, OSError) as e:
                QMessageBox.warning(self, "Add jar", f"Could not read {os.path.basename(path)}:\n{e}")
        self._catalog.save()
        self._catalog_view.refresh()
        self.statusBar().showMessage(
            f"[{self._version}] Loaded {len(paths)} jar(s): +{total} items. "
            f"Cache: {self._catalog.cache_dir}")

    def _clear_catalog(self) -> None:
        if not self._catalog.items and not self._catalog.jars:
            return
        if QMessageBox.question(
                self, "Clear catalog",
                f"Forget all loaded items for MC {self._version}? (jars can be re-added)"
                ) != QMessageBox.Yes:
            return
        self._catalog.items.clear()
        self._catalog.jars.clear()
        self._catalog.save()
        self._catalog_view.refresh()

    # --- output path / .env ---------------------------------------------------

    def _env_key(self) -> str:
        return env_file.env_key_for_version(self._version)

    def _load_output_from_env(self) -> None:
        val = env_file.read_env(ENV_PATH).get(self._env_key(), "")
        self._path_edit.blockSignals(True)
        self._path_edit.setText(val)
        self._path_edit.blockSignals(False)
        self._update_target_warning()

    def _commit_output_path(self) -> None:
        """Persist the output-root edit back to .env for the current version."""
        val = self._path_edit.text().strip()
        env_file.set_env_value(self._env_key(), val, ENV_PATH)
        self._update_target_warning()
        self.statusBar().showMessage(f"Saved output path for MC {self._version} to .env.")

    def _pick_output_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select multiloader project root")
        if d:
            self._path_edit.setText(d)
            self._commit_output_path()

    def _update_target_warning(self) -> None:
        path = self._path_edit.text().strip()
        if not path:
            self._target_label.setText(
                "<span style='color:green'>No path set — writes to local ./fabric and "
                "./neoforge (or ./forge), not the mod repo.</span>")
        else:
            self._target_label.setText(
                f"<span style='color:#c0392b'>⚠ Writes generated files into: {path}</span>")

    # --- generate -------------------------------------------------------------

    def _on_generate(self) -> None:
        if self._proc is not None:
            return
        path = self._path_edit.text().strip()
        if path:
            if QMessageBox.warning(
                    self, "Write into project?",
                    f"This will write generated files into:\n\n{path}\n\nProceed?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return

        if self._model.dirty:
            self._model.save()
            self._log.appendPlainText(f"• Saved {self._version} tiers.json / keys.json.")
            self._tier_editor._emit_dirty()
        if self._patterns.dirty:
            self._patterns.save()
            self._log.appendPlainText("• Saved sword_patterns.json before generating.")
            self._pattern_editor._emit_dirty()

        args = ["main.py", "--mc", self._version]
        if path:
            args.append(path)

        self._log.appendPlainText(f"\n$ python {' '.join(args)}  (cwd={REPO_ROOT})")
        self._generate_btn.setEnabled(False)
        self._proc = QProcess(self)
        self._proc.setWorkingDirectory(REPO_ROOT)
        self._proc.setProcessChannelMode(QProcess.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._on_proc_output)
        self._proc.finished.connect(self._on_proc_finished)
        self._proc.start(sys.executable, args)

    def _on_proc_output(self) -> None:
        data = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        self._log.moveCursor(QTextCursor.End)
        self._log.insertPlainText(data)
        self._log.moveCursor(QTextCursor.End)
        self._log.ensureCursorVisible()

    def _on_proc_finished(self, code, _status) -> None:
        self._log.appendPlainText(f"— generator exited with code {code} —")
        self._generate_btn.setEnabled(True)
        self._proc = None
