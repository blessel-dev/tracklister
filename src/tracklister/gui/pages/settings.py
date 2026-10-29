"""'Ajustes': theme, account, format preset, folders, network, engine, yt-dlp and updates.

Owner: GUI step.
SPDX-License-Identifier: GPL-3.0-or-later

Every change is saved at once to settings.json (per user). The account is the exception: it is
written to Windows Credential Manager (the macOS Keychain on a Mac) only when 'Guardar cuenta' is
pressed, and never shown back except for the user name.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFormLayout, QGridLayout, QHBoxLayout, QLineEdit,
                               QRadioButton, QVBoxLayout, QWidget)

from tracklister import config
from tracklister.engine.credentials import CredentialError, store_name_es
from tracklister.engine.spec import engine_pins
from tracklister.gui.pages.common import PresetChooser, default_library_root
from tracklister.gui.pages.first_run import SHARE_NOTICE, port_help
from tracklister.gui.theme import THEME_LABELS_ES, theme_ids
from tracklister.gui.widgets import Banner, IntField, button, card, label, scroll_page

ENGINE_LABELS = {"sockseek-3.0.5": "Sockseek 3.0.5 (recomendado)", "sldl-2.6.0": "sldl 2.6.0 (alternativa)"}
SAMPLERATES = ((None, "Sin límite"), (44100, "44,1 kHz"), (48000, "48 kHz"), (96000, "96 kHz"))
BITDEPTHS = ((None, "Sin límite"), (16, "16 bit"), (24, "24 bit"))
MP3_KBPS = (320, 256, 192)


class SettingsPage(QWidget):
    def __init__(self, window, parent: QWidget | None = None):
        super().__init__(parent)
        self.window = window
        self.services = window.services
        self.themes = window.themes
        self._loading = True
        s = self.services.settings
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        body = QWidget()
        outer.addWidget(scroll_page(body))
        lay = QVBoxLayout(body)
        lay.setContentsMargins(28, 22, 28, 22)
        lay.setSpacing(14)
        lay.addWidget(label("Ajustes", "title"))
        self.banner = Banner(self.themes)
        lay.addWidget(self.banner)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        lay.addLayout(grid)

        # Theme
        c, cl = card("Tema")
        self.theme_group = QButtonGroup(self)
        self.theme_buttons: dict[str, QRadioButton] = {}
        current = self.themes.theme.id
        for tid in theme_ids():
            rb = QRadioButton(THEME_LABELS_ES.get(tid, tid))
            rb.setChecked(tid == current)
            rb.toggled.connect(lambda on, tid=tid: on and self.set_theme(tid))
            self.theme_group.addButton(rb)
            self.theme_buttons[tid] = rb
            cl.addWidget(rb)
        cl.addStretch(1)
        grid.addWidget(c, 0, 0)

        # Account
        c, cl = card("Cuenta de Soulseek", f"En el {store_name_es()}, nunca en un archivo.")
        self.account = label("", wrap=True)
        cl.addWidget(self.account)
        form = QFormLayout()
        self.user = QLineEdit()
        self.user.setAccessibleName("Usuario de Soulseek")
        self.user.setPlaceholderText("usuario")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setAccessibleName("Contraseña de Soulseek")
        self.password.setPlaceholderText("contraseña")
        form.addRow("Usuario", self.user)
        form.addRow("Contraseña", self.password)
        cl.addLayout(form)
        arow = QHBoxLayout()
        self.save_account_btn = button("Guardar cuenta")
        self.save_account_btn.clicked.connect(self.save_account)
        self.clear_account_btn = button("Borrar cuenta")
        self.clear_account_btn.clicked.connect(self.clear_account)
        arow.addWidget(self.save_account_btn)
        arow.addWidget(self.clear_account_btn)
        arow.addStretch(1)
        cl.addLayout(arow)
        cl.addStretch(1)
        grid.addWidget(c, 0, 1)

        # Preset
        c, cl = card("Formato")
        self.preset = PresetChooser(s.preset_id)
        self.preset.changed.connect(self.set_preset)
        cl.addWidget(self.preset)
        self.custom = QWidget()
        cg = QVBoxLayout(self.custom)
        cg.setContentsMargins(24, 0, 0, 0)
        frow = QHBoxLayout()
        self.fmt_boxes: dict[str, QCheckBox] = {}
        for f in ("flac", "wav", "aiff", "mp3"):
            cb = QCheckBox(f.upper())
            cb.setChecked(f in [x.lower() for x in s.custom_preset.formats])
            cb.toggled.connect(self._custom_changed)
            self.fmt_boxes[f] = cb
            frow.addWidget(cb)
        frow.addStretch(1)
        cg.addLayout(frow)
        cform = QFormLayout()
        self.kbps = QComboBox()
        for k in MP3_KBPS:
            self.kbps.addItem(f"{k} kbps", k)
        self.kbps.setCurrentIndex(max(0, self.kbps.findData(int(s.custom_preset.min_mp3_kbps or 320))))
        self.kbps.currentIndexChanged.connect(self._custom_changed)
        self.max_sr = QComboBox()
        for v, t in SAMPLERATES:
            self.max_sr.addItem(t, v)
        self.max_sr.setCurrentIndex(max(0, self.max_sr.findData(s.custom_preset.max_samplerate)))
        self.max_sr.currentIndexChanged.connect(self._custom_changed)
        self.max_bits = QComboBox()
        for v, t in BITDEPTHS:
            self.max_bits.addItem(t, v)
        self.max_bits.setCurrentIndex(max(0, self.max_bits.findData(s.custom_preset.max_bitdepth)))
        self.max_bits.currentIndexChanged.connect(self._custom_changed)
        cform.addRow("MP3 mínimo", self.kbps)
        cform.addRow("Sample rate máximo", self.max_sr)
        cform.addRow("Bits máximos", self.max_bits)
        cg.addLayout(cform)
        self.lossy_fallback = QCheckBox("Si no hay lossless, preguntar si la busco en MP3")
        self.lossy_fallback.setChecked(bool(s.custom_preset.allow_lossy_fallback))
        self.lossy_fallback.toggled.connect(self._custom_changed)
        cg.addWidget(self.lossy_fallback)
        cl.addWidget(self.custom)
        cl.addStretch(1)
        grid.addWidget(c, 1, 0)

        # Folders and library
        c, cl = card("Biblioteca", "Una carpeta por set, con el informe y la tracklist de cada uno.")
        rrow = QHBoxLayout()
        self.root = QLineEdit(s.library_root or "")
        self.root.setReadOnly(True)
        self.root.setAccessibleName("Carpeta de la biblioteca")
        rrow.addWidget(self.root, 1)
        change = button("Cambiar…")
        change.clicked.connect(self.change_root)
        openb = button("Abrir")
        self.themes.bind_icon(openb, "carpeta")
        openb.clicked.connect(lambda: self.root.text() and self.services.open_path(Path(self.root.text())))
        rrow.addWidget(change)
        rrow.addWidget(openb)
        cl.addLayout(rrow)
        lrow = QHBoxLayout()
        self.rebuild_btn = button("Reconstruir índice de la biblioteca",
                                  tooltip="Vuelve a leer los sets de la carpeta para detectar pistas repetidas.")
        self.rebuild_btn.clicked.connect(self.rebuild_library)
        lrow.addWidget(self.rebuild_btn)
        lrow.addStretch(1)
        cl.addLayout(lrow)
        self.library_info = label("", "small", wrap=True)
        cl.addWidget(self.library_info)
        cl.addStretch(1)
        grid.addWidget(c, 1, 1)

        # Network and engine
        c, cl = card("Red y motor")
        nform = QFormLayout()
        self.port = IntField(int(s.listen_port or config.DEFAULT_LISTEN_PORT), 1024, 65535)
        self.port.setFixedWidth(110)
        self.port.setAccessibleName("Puerto de escucha (1024 a 65535)")
        self.port.textChanged.connect(self._save_port)
        nform.addRow("Puerto de escucha", self.port)
        self.engine = QComboBox()
        for eid in engine_pins():                    # macOS ships only Sockseek (DECISIONES Y)
            self.engine.addItem(ENGINE_LABELS.get(eid, eid), eid)
        self.engine.setCurrentIndex(max(0, self.engine.findData(self.services.engine_id())))
        self.engine.currentIndexChanged.connect(self._save_engine)
        self.engine.setAccessibleName("Motor de descarga")
        nform.addRow("Motor", self.engine)
        cl.addLayout(nform)
        cl.addWidget(label(port_help(), "small", wrap=True))
        cl.addWidget(label(SHARE_NOTICE, "small", wrap=True))
        cl.addStretch(1)
        grid.addWidget(c, 2, 0)

        # Checks and sources
        c, cl = card("Comprobaciones y fuentes")
        self.enrich_box = QCheckBox("Completar datos al importar (iTunes, Deezer y MusicBrainz; solo envía "
                                    "artista y título)")
        self.enrich_box.setChecked(bool(s.enrichment_enabled))
        self.spectral_box = QCheckBox("Análisis de espectro: marcar los probables MP3 convertidos")
        self.spectral_box.setChecked(bool(s.spectral_check_enabled))
        self.watch_box = QCheckBox("Vigilar la carpeta Descargas por si llega un CSV de trackid.net")
        self.watch_box.setChecked(bool(s.watch_downloads_folder))
        for cb in (self.enrich_box, self.spectral_box, self.watch_box):
            cb.toggled.connect(self._save_checks)
            cl.addWidget(cb)
        yrow = QHBoxLayout()
        self.ytdlp_label = label("yt-dlp: …", "small", mono=True)
        yrow.addWidget(self.ytdlp_label, 1)
        self.ytdlp_btn = button("Actualizar yt-dlp",
                                tooltip="Si YouTube cambia y no se leen los comentarios, actualízalo aquí.")
        self.ytdlp_btn.clicked.connect(self.update_ytdlp)
        yrow.addWidget(self.ytdlp_btn)
        cl.addLayout(yrow)
        cl.addStretch(1)
        grid.addWidget(c, 2, 1)

        # Updates and about
        c, cl = card("Tracklister")
        cl.addWidget(label(f"Versión {config.APP_VERSION}. Software libre (GPL-3.0-or-later). Tipografías Inter y "
                           "JetBrains Mono (licencia OFL). Motor Sockseek/sldl (AGPL/GPL), sin modificar.",
                           "small", wrap=True))
        urow = QHBoxLayout()
        self.update_btn = button("Buscar actualizaciones")
        self.update_btn.clicked.connect(self.check_updates)
        urow.addWidget(self.update_btn)
        self.update_label = label("", "small", wrap=True)
        urow.addWidget(self.update_label, 1)
        cl.addLayout(urow)
        grid.addWidget(c, 3, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        lay.addStretch(1)

        self._loading = False
        self.refresh()

    # ---- refresh -------------------------------------------------------------------------------
    def refresh(self) -> None:
        self._loading = True
        s = self.services.settings
        # the page is built before the first run: show what it chose (barrido CL-13)
        self.preset.set_value(s.preset_id)
        self.port.setValue(int(s.listen_port or config.DEFAULT_LISTEN_PORT))
        self.custom.setVisible(self.preset.value() == "personalizado")
        self.root.setText(s.library_root or "")
        try:
            creds = self.services.get_credentials()
            self.account.setText(f"Cuenta guardada: {creds.username}" if creds else
                                 "No hay ninguna cuenta guardada.")
        except CredentialError as e:
            self.account.setText(e.msg_es)
        self._loading = False

    def showEvent(self, e) -> None:  # noqa: N802
        self.refresh()
        if self.ytdlp_label.text() == "yt-dlp: …":
            self.refresh_ytdlp()
        super().showEvent(e)

    def refresh_ytdlp(self) -> None:
        self.window.pool.start(lambda t: self.services.ytdlp_version(),
                               on_ok=lambda v: self.ytdlp_label.setText(f"yt-dlp: {v}" if v else
                                                                        "yt-dlp: no encontrado"),
                               on_error=lambda m: self.ytdlp_label.setText("yt-dlp: no encontrado"))

    # ---- handlers -----------------------------------------------------------------------------
    def _save(self) -> None:
        if not self._loading:
            self.services.save_settings()
            self.window.status("Ajustes guardados.")

    def set_theme(self, tid: str) -> None:
        if self._loading:
            return
        self.themes.apply(tid)
        self.services.settings.theme = tid
        self._save()

    def set_preset(self, pid: str) -> None:
        self.custom.setVisible(pid == "personalizado")
        if self._loading:
            return
        self.services.settings.preset_id = pid
        self._save()

    def _custom_changed(self, *_args) -> None:
        if self._loading:
            return
        cp = self.services.settings.custom_preset
        cp.formats = [f for f, cb in self.fmt_boxes.items() if cb.isChecked()]
        cp.min_mp3_kbps = int(self.kbps.currentData() or 320)
        cp.max_samplerate = self.max_sr.currentData()
        cp.max_bitdepth = self.max_bits.currentData()
        cp.allow_lossy_fallback = self.lossy_fallback.isChecked()
        self._save()

    def _save_port(self, *_args) -> None:
        """Saved as soon as the field holds a valid port (1024-65535); anything else is not saved."""
        if self._loading or not self.port.hasAcceptableInput():
            return
        if int(self.port.value()) != int(self.services.settings.listen_port):
            self.services.settings.listen_port = int(self.port.value())
            self._save()

    def hideEvent(self, e) -> None:  # noqa: N802
        if not self.port.hasAcceptableInput():          # half-typed port: show the saved one again
            self.port.setValue(int(self.services.settings.listen_port))
        super().hideEvent(e)

    def _save_engine(self) -> None:
        self.services.settings.engine_id = str(self.engine.currentData())
        self._save()

    def _save_checks(self) -> None:
        s = self.services.settings
        s.enrichment_enabled = self.enrich_box.isChecked()
        s.spectral_check_enabled = self.spectral_box.isChecked()
        was = s.watch_downloads_folder
        s.watch_downloads_folder = self.watch_box.isChecked()
        self._save()
        if was != s.watch_downloads_folder:
            if s.watch_downloads_folder:
                self.window.new_set.start_watching()
            else:
                self.window.new_set.stop_watching()

    def change_root(self) -> None:
        d = self.window.prompter.pick_folder("Carpeta de tu biblioteca",
                                             self.root.text() or str(default_library_root()))
        if not d:
            return
        try:
            Path(d).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.banner.show_message(f"No se puede usar esa carpeta ({e.strerror or e}).", "error")
            return
        self.services.settings.library_root = str(Path(d))
        self._save()
        self.root.setText(str(Path(d)))

    def save_account(self) -> None:
        user, pw = self.user.text().strip(), self.password.text()
        if not user or not pw:
            self.banner.show_message("Escribe el usuario y la contraseña de Soulseek.", "warn")
            return
        try:
            self.services.save_credentials(user, pw)
        except CredentialError as e:
            self.banner.show_message(e.msg_es, "error")
            return
        self.password.clear()
        self.user.clear()
        self.banner.show_message(f"Cuenta guardada en el {store_name_es()}.", "ok")
        self.refresh()

    def clear_account(self) -> None:
        if not self.window.prompter.confirm("Borrar cuenta", "¿Borro tu cuenta de Soulseek de este PC?",
                                            ok="Borrar"):
            return
        try:
            self.services.clear_credentials()
        except CredentialError as e:
            self.banner.show_message(e.msg_es, "error")
            return
        self.banner.show_message("Cuenta borrada de este PC.", "ok")
        self.refresh()

    def rebuild_library(self) -> None:
        self.rebuild_btn.setEnabled(False)
        self.library_info.setText("Leyendo los sets…")

        def done(n):
            self.rebuild_btn.setEnabled(True)
            self.library_info.setText(f"Índice reconstruido: {n} pistas en la biblioteca.")

        def fail(msg):
            self.rebuild_btn.setEnabled(True)
            self.library_info.setText(msg)
        self.window.pool.start(lambda t: self.services.rebuild_library(), on_ok=done, on_error=fail)

    def update_ytdlp(self) -> None:
        self.ytdlp_btn.setEnabled(False)
        self.ytdlp_label.setText("yt-dlp: actualizando…")

        def done(res):
            ok, msg = res
            self.ytdlp_btn.setEnabled(True)
            self.banner.show_message(msg, "ok" if ok else "warn")
            self.refresh_ytdlp()

        def fail(msg):
            self.ytdlp_btn.setEnabled(True)
            self.banner.show_message(msg, "error")
            self.refresh_ytdlp()
        self.window.pool.start(lambda t: self.services.update_ytdlp(), on_ok=done, on_error=fail)

    def check_updates(self) -> None:
        self.update_btn.setEnabled(False)
        self.update_label.setText("Buscando…")

        def done(info):
            self.update_btn.setEnabled(True)
            if info:
                self.update_label.setText(f"Hay una versión nueva: {getattr(info, 'latest', '?')}.")
                self.window.show_update(info)
            else:
                self.update_label.setText("No hay ninguna versión nueva (o no se pudo comprobar).")

        def fail(msg):
            self.update_btn.setEnabled(True)
            self.update_label.setText("No se pudo comprobar ahora.")
        self.window.pool.start(lambda t: self.services.check_for_update(force=True), on_ok=done, on_error=fail)

    def select_theme_button(self, tid: str) -> None:
        rb = self.theme_buttons.get(tid)
        if rb is not None and not rb.isChecked():
            rb.setChecked(True)
