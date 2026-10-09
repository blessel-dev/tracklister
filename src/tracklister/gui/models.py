"""Qt table models: the editable review table, the results table and the reorder preview.

Owner: GUI step.
SPDX-License-Identifier: GPL-3.0-or-later

TrackRow.pos is the row index and the ONLY source of the NN prefix, so the review model
renumbers pos 1..n after every structural change (move, insert, delete) and on load.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import replace
from typing import Iterable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor

from tracklister.core.model import DoubtKind, ResultState, RowResult, RowStatus, TrackRow
from tracklister.core.textnorm import nfc, norm_key, split_artists, split_title_version
from tracklister.gui.theme import Theme, mono_font, state_icon, state_label_es

R = Qt.ItemDataRole

DOUBT_SHORT_ES = {
    DoubtKind.IDENTIDAD: "otra canción",
    DoubtKind.VERSION: "otra versión",
    DoubtKind.DURACION: "duración",
    DoubtKind.ESPECTRO: "posible lossless falso",
    DoubtKind.REVISAR: "revisar",
}
DOUBT_LONG_ES = {
    DoubtKind.IDENTIDAD: "Parece otra canción. Está en la carpeta _dudosos.",
    DoubtKind.VERSION: "Parece otra versión (remix, radio edit...). Está en la carpeta _dudosos.",
    DoubtKind.DURACION: "La duración no cuadra (o el archivo está cortado). Está en la carpeta _dudosos.",
    DoubtKind.ESPECTRO: "Posible lossless falso (sacado de un MP3). Se queda en el set, marcado: escúchalo.",
    DoubtKind.REVISAR: "Coincide a medias. Se queda en el set, marcado: revísalo.",
}
ROW_STATUS_ES = {
    RowStatus.OK: "Lista", RowStatus.REVISAR: "Revisar", RowStatus.ID: "ID",
    RowStatus.YA_EN_BIBLIOTECA: "Ya en biblioteca", RowStatus.DESCARGADA: "Descargada", RowStatus.FALLIDA: "Fallida",
}
ROW_STATUS_ICON = {RowStatus.REVISAR: ResultState.DUDOSO, RowStatus.ID: ResultState.OMITIDA,
                   RowStatus.YA_EN_BIBLIOTECA: ResultState.YA_EN_BIBLIOTECA,
                   RowStatus.DESCARGADA: ResultState.VERIFICADO, RowStatus.FALLIDA: ResultState.FALLIDA}
ENRICH_ES = {"itunes": "iTunes", "deezer": "Deezer", "musicbrainz": "MusicBrainz"}
RETRYABLE = (ResultState.NO_ENCONTRADO, ResultState.FALLIDA, ResultState.NO_CUMPLE_FORMATO)
QUARANTINED = (DoubtKind.IDENTIDAD, DoubtKind.VERSION, DoubtKind.DURACION)


def fmt_clock(s: int | float | None) -> str:
    if s is None:
        return ""
    s = int(round(float(s)))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def parse_clock(text: str) -> int | None:
    """'' -> None; '5:09', '01:02:03', '309' -> seconds. Raises ValueError otherwise."""
    t = (text or "").strip()
    if not t:
        return None
    if not re.fullmatch(r"\d{1,3}(:\d{1,2}){0,2}", t):
        raise ValueError(t)
    parts = [int(p) for p in t.split(":")]
    if any(p >= 60 for p in parts[1:]):
        raise ValueError(t)
    total = 0
    for p in parts:
        total = total * 60 + p
    return total


def is_id_text(s: str | None) -> bool:
    return norm_key(s) in ("", "id", "id hueco", "unknown", "desconocido")


def track_label(row: TrackRow) -> str:
    who = row.artist_display or row.search_artist
    title = row.title_with_version or ("ID" if row.is_id else "")
    return f"{who} - {title}" if who else title


def fmt_audio(res: RowResult | None) -> str:
    if res is None or not res.format:
        return ""
    fmt = res.format.upper()
    if res.format == "mp3":
        return f"{fmt} · {res.bitrate_kbps} kbps" if res.bitrate_kbps else fmt
    bits = []
    if res.samplerate:
        bits.append(f"{res.samplerate / 1000:g}".replace(".", ",") + " kHz")
    if res.bitdepth:
        bits.append(f"{res.bitdepth} bit")
    return " · ".join([fmt] + bits)


class TrackTableModel(QAbstractTableModel):
    """The editable review table of the 'Nuevo set' screen."""

    COLUMNS = (("download", ""), ("pos", "Nº"), ("start", "Inicio"), ("artist", "Artista"), ("title", "Título"),
               ("version", "Versión"), ("label", "Sello"), ("duration", "Duración"), ("status", "Estado"),
               ("notes", "Notas"))
    EDITABLE = {"start", "artist", "title", "version", "label", "duration"}
    edited = Signal()

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self._rows: list[TrackRow] = []
        self._theme = theme
        self.editable = True

    # ---- data access --------------------------------------------------------------------------
    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        if self._rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._rows) - 1, len(self.COLUMNS) - 1))
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(self.COLUMNS) - 1)

    def set_editable(self, on: bool) -> None:
        self.layoutAboutToBeChanged.emit()
        self.editable = on
        self.layoutChanged.emit()

    def set_rows(self, rows: Iterable[TrackRow]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self._renumber()
        self.endResetModel()
        self.edited.emit()

    def rows(self) -> list[TrackRow]:
        self._renumber()
        return list(self._rows)

    def row_at(self, i: int) -> TrackRow:
        return self._rows[i]

    def key(self, col: int) -> str:
        return self.COLUMNS[col][0]

    def column_of(self, key: str) -> int:
        return [k for k, _ in self.COLUMNS].index(key)

    def downloadable(self) -> list[TrackRow]:
        return [r for r in self._rows if r.download and (r.title or "").strip()]

    def _renumber(self) -> None:
        for i, r in enumerate(self._rows, start=1):
            r.pos = i

    # ---- Qt model API ----------------------------------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, section, orientation, role=R.DisplayRole):  # noqa: N802
        if orientation != Qt.Orientation.Horizontal:
            return None
        key, title = self.COLUMNS[section]
        if role == R.DisplayRole:
            return title
        if role == R.ToolTipRole:
            return {"download": "Marcada = se descarga", "start": "Minuto del set",
                    "duration": "Duración esperada (de iTunes, Deezer o MusicBrainz)"}.get(key)
        if role == R.AccessibleTextRole:
            return title or "Descargar"
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        key = self.key(index.column())
        if self.editable and key == "download":
            f |= Qt.ItemFlag.ItemIsUserCheckable
        elif self.editable and key in self.EDITABLE:
            f |= Qt.ItemFlag.ItemIsEditable
        return f

    def _text(self, r: TrackRow, key: str) -> str:
        if key == "pos":
            return f"{r.pos:0{3 if len(self._rows) > 99 else 2}d}"
        if key == "start":
            return fmt_clock(r.ts_start)
        if key == "artist":
            return r.artist_display or ", ".join(r.artists)
        if key == "title":
            return r.title or ""
        if key == "version":
            return r.version or ""
        if key == "label":
            return r.label or ""
        if key == "duration":
            return fmt_clock(r.expected_duration_s)
        if key == "status":
            return ROW_STATUS_ES.get(r.status, str(r.status))
        if key == "notes":
            return "; ".join(r.notes)
        return ""

    def data(self, index, role=R.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        r = self._rows[index.row()]
        key = self.key(index.column())
        t = self._theme
        if role in (R.DisplayRole, R.EditRole):
            return None if key == "download" else self._text(r, key)
        if role == R.CheckStateRole and key == "download":
            return Qt.CheckState.Checked if r.download else Qt.CheckState.Unchecked
        if role == R.ForegroundRole:
            if key == "status" and r.status == RowStatus.REVISAR:
                return QColor(t.state_color(ResultState.DUDOSO))
            if r.is_id or not r.download:
                return QColor(t.color("ink_muted"))
            return None
        if role == R.FontRole and key in ("pos", "start", "duration"):
            return mono_font(t, "sm")
        if role == R.DecorationRole and key == "status" and r.status in ROW_STATUS_ICON:
            return state_icon(t, ROW_STATUS_ICON[r.status])
        if role == R.TextAlignmentRole and key in ("pos", "start", "duration"):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == R.ToolTipRole:
            return self._tooltip(r, key)
        if role == R.AccessibleTextRole and key == "download":
            return "Se descarga" if r.download else "No se descarga"
        return None

    def _tooltip(self, r: TrackRow, key: str) -> str | None:
        if key == "download":
            if not (r.title or "").strip():
                return "Falta el título: escríbelo para poder descargarla."
            return "Desmarca para no descargarla." if r.download else "Marca para descargarla."
        if key == "duration" and r.enrich_source:
            return f"Duración de {ENRICH_ES.get(r.enrich_source, r.enrich_source)}"
        if key == "status":
            src = f"\nDatos completados con {ENRICH_ES.get(r.enrich_source, r.enrich_source)}." if r.enrich_source else ""
            if r.status == RowStatus.REVISAR:
                return "Línea leída a medias: revisa artista y título y márcala si está bien." + src
            if r.status == RowStatus.ID:
                return "Pista sin identificar: no se descarga." + src
            return (ROW_STATUS_ES.get(r.status, "") + src) or None
        lines = []
        if r.raw:
            lines.append(f"Original: {r.raw}")
        lines += r.notes
        return "\n".join(lines) or None

    def setData(self, index, value, role=R.EditRole):  # noqa: N802
        if not index.isValid() or not self.editable:
            return False
        r = self._rows[index.row()]
        key = self.key(index.column())
        if key == "download" and role == R.CheckStateRole:
            want = Qt.CheckState(value) == Qt.CheckState.Checked
            if want and not (r.title or "").strip():
                return False
            r.download = want
            self._changed(index.row())
            return True
        if role != R.EditRole or key not in self.EDITABLE:
            return False
        text = nfc(str(value or ""))
        if key == "start" or key == "duration":
            try:
                secs = parse_clock(text)
            except ValueError:
                return False
            if key == "start":
                r.ts_start = secs
            else:
                r.expected_duration_s = secs
        elif key == "artist":
            r.artist_display = text
            r.artists = split_artists(text)
        elif key == "title":
            had_title = bool((r.title or "").strip())
            base, version = split_title_version(text)
            r.title = base or text
            if version:
                r.version = version
            if not had_title and r.title:
                r.download = True
            if not r.title:
                r.download = False
        elif key == "version":
            r.version = text or None
        elif key == "label":
            r.label = text or None
        if r.is_id and key in ("artist", "title") and not is_id_text(r.title) and not is_id_text(r.artist_display):
            r.is_id = False
            r.status = RowStatus.OK
            r.download = True
        self._changed(index.row())
        return True

    def _changed(self, row: int) -> None:
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(self.COLUMNS) - 1))
        self.edited.emit()

    # ---- structure ----------------------------------------------------------------------------
    def move_row(self, i: int, delta: int) -> int:
        j = i + delta
        if not (0 <= i < len(self._rows)) or not (0 <= j < len(self._rows)) or delta == 0:
            return i
        dest = j + 1 if delta > 0 else j
        self.beginMoveRows(QModelIndex(), i, i, QModelIndex(), dest)
        self._rows.insert(j, self._rows.pop(i))
        self._renumber()
        self.endMoveRows()
        lo, hi = min(i, j), max(i, j)
        self.dataChanged.emit(self.index(lo, 0), self.index(hi, len(self.COLUMNS) - 1))
        self.edited.emit()
        return j

    def remove_rows(self, indices: Iterable[int]) -> None:
        for i in sorted(set(indices), reverse=True):
            if 0 <= i < len(self._rows):
                self.beginRemoveRows(QModelIndex(), i, i)
                self._rows.pop(i)
                self.endRemoveRows()
        self._renumber()
        if self._rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._rows) - 1, len(self.COLUMNS) - 1))
        self.edited.emit()

    def insert_row(self, at: int) -> int:
        at = max(0, min(at, len(self._rows)))
        self.beginInsertRows(QModelIndex(), at, at)
        self._rows.insert(at, TrackRow(pos=at + 1, source="manual", download=False, confidence=0.7))
        self._renumber()
        self.endInsertRows()
        self.dataChanged.emit(self.index(0, 0), self.index(len(self._rows) - 1, len(self.COLUMNS) - 1))
        self.edited.emit()
        return at

    def replace_rows_by_uid(self, rows: Iterable[TrackRow]) -> None:
        by_uid = {r.uid: r for r in rows}
        self.beginResetModel()
        self._rows = [by_uid.get(r.uid, r) for r in self._rows]
        self._renumber()
        self.endResetModel()
        self.edited.emit()


class ResultsTableModel(QAbstractTableModel):
    """Per-track states of a set ('Descargando' / 'Resultados')."""

    COLUMNS = ("Nº", "Pista", "Estado", "Detalle", "Formato", "Confianza")

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._rows: list[TrackRow] = []
        self._res: dict[str, RowResult] = {}
        self._live: dict[str, str] = {}
        self._index: dict[str, int] = {}

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        if self._rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._rows) - 1, len(self.COLUMNS) - 1))

    def load(self, rows: Iterable[TrackRow], results: dict[str, RowResult]) -> None:
        self.beginResetModel()
        self._rows = sorted((TrackRow.from_dict(r.to_dict()) for r in rows), key=lambda x: x.pos)
        self._res = {u: RowResult.from_dict(v.to_dict()) for u, v in results.items()}
        self._live = {}
        self._index = {r.uid: i for i, r in enumerate(self._rows)}
        self.endResetModel()

    def apply_event(self, uid: str | None, state: ResultState | None, message: str = "",
                    snap: RowResult | None = None) -> None:
        if not uid or uid not in self._index:
            return
        i = self._index[uid]
        if snap is not None:
            self._res[uid] = snap
            self._live.pop(uid, None)
        else:
            res = self._res.setdefault(uid, RowResult(uid=uid, pos=self._rows[i].pos))
            if state is not None:
                self._res[uid] = replace(res, state=ResultState(state))
            if message:
                self._live[uid] = message
        self.dataChanged.emit(self.index(i, 0), self.index(i, len(self.COLUMNS) - 1))

    def state_of(self, uid: str) -> ResultState:
        res = self._res.get(uid)
        return res.state if res else ResultState.PENDIENTE

    def result_of(self, uid: str) -> RowResult | None:
        return self._res.get(uid)

    def rows(self) -> list[TrackRow]:
        return list(self._rows)

    def counts(self) -> Counter:
        return Counter(self.state_of(r.uid) for r in self._rows)

    def retryable(self) -> int:
        n = 0
        for r in self._rows:
            res = self._res.get(r.uid)
            if res is None or not r.download:
                continue
            if res.state in RETRYABLE or (res.state == ResultState.DUDOSO and res.doubt in QUARANTINED):
                n += 1
        return n

    def pending(self) -> int:
        return sum(1 for r in self._rows if r.download and (r.title or "").strip()
                   and self.state_of(r.uid) in (ResultState.PENDIENTE, ResultState.EN_CURSO))

    # ---- Qt model API --------------------------------------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, section, orientation, role=R.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == R.DisplayRole:
            return self.COLUMNS[section]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def state_text(self, res: RowResult | None) -> str:
        state = res.state if res else ResultState.PENDIENTE
        label = state_label_es(state)
        if res is not None and state == ResultState.DUDOSO and res.doubt:
            label += f" · {DOUBT_SHORT_ES.get(res.doubt, str(res.doubt))}"
        elif res is not None and state == ResultState.YA_EN_BIBLIOTECA and "posible_falso_lossless" in res.flags:
            # a reused file keeps the mark it had in its set (never accepted silently)
            label += f" · {DOUBT_SHORT_ES[DoubtKind.ESPECTRO]}"
        return label

    def data(self, index, role=R.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        r = self._rows[index.row()]
        res = self._res.get(r.uid)
        state = res.state if res else ResultState.PENDIENTE
        col = index.column()
        t = self._theme
        if role == R.DisplayRole:
            if col == 0:
                return f"{r.pos:0{3 if len(self._rows) > 99 else 2}d}"
            if col == 1:
                return track_label(r)
            if col == 2:
                return self.state_text(res)
            if col == 3:
                live = self._live.get(r.uid)
                if live and state == ResultState.EN_CURSO:
                    return live
                if res and res.reasons:
                    return res.reasons[0]
                return live or ""
            if col == 4:
                return fmt_audio(res)
            if col == 5:
                return f"{res.score}/100" if res and res.score is not None else ""
            return None
        if role == R.DecorationRole and col == 2:
            return state_icon(t, state)
        if role == R.ForegroundRole:
            if col == 2:
                return QColor(t.state_color(state))
            if state == ResultState.OMITIDA:
                return QColor(t.color("ink_muted"))
            return None
        if role == R.FontRole and col in (0, 4, 5):
            return mono_font(t, "sm")
        if role == R.TextAlignmentRole and col in (0, 5):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == R.ToolTipRole:
            return self._tooltip(r, res)
        if role == R.AccessibleTextRole and col == 2:
            return self.state_text(res)
        return None

    def detail_text(self, i: int) -> str:
        """Full explanation of row i (shown under the table for the selected row)."""
        if not (0 <= i < len(self._rows)):
            return ""
        r = self._rows[i]
        return self._tooltip(r, self._res.get(r.uid)) or f"{r.pos:02d}. {track_label(r)}"

    def _tooltip(self, r: TrackRow, res: RowResult | None) -> str | None:
        if res is None:
            return None
        lines = [f"{r.pos:02d}. {track_label(r)}", self.state_text(res)]
        if res.doubt:
            lines.append(DOUBT_LONG_ES.get(res.doubt, ""))
        lines += [f"- {x}" for x in res.reasons]
        if res.file:
            lines.append(f"Archivo: {res.file}")
        if res.original_file:
            lines.append(f"Original: {res.original_file}")
        if res.source_path_tail:
            lines.append(f"Origen: {res.source_path_tail}")
        return "\n".join(x for x in lines if x)


REORDER_STATUS_ES = {"match": "Coincide", "ambiguous": "Dudoso: confírmalo", "missing": "Sin archivo",
                     "extra": "No encaja"}
REORDER_STATUS_ICON = {"match": ResultState.VERIFICADO, "ambiguous": ResultState.DUDOSO,
                       "missing": ResultState.NO_ENCONTRADO, "extra": ResultState.OMITIDA}


class ReorderPreviewModel(QAbstractTableModel):
    """Mandatory preview of 'Reordenar carpeta existente'. Ambiguous rows start unchecked."""

    COLUMNS = ("", "Nº", "Archivo actual", "Nombre nuevo", "Coincidencia", "Estado")
    edited = Signal()

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._props: list = []
        self._checked: list[bool] = []

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        if self._props:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._props) - 1, len(self.COLUMNS) - 1))

    def set_proposals(self, proposals: Iterable) -> None:
        self.beginResetModel()
        self._props = list(proposals)
        self._checked = [p.status == "match" and p.src is not None and p.dst is not None and p.src != p.dst
                         for p in self._props]
        self.endResetModel()
        self.edited.emit()

    def proposals(self) -> list:
        return list(self._props)

    def checkable(self, i: int) -> bool:
        p = self._props[i]
        return p.status in ("match", "ambiguous") and p.src is not None and p.dst is not None and p.src != p.dst

    def chosen(self) -> list:
        """Copies ready for apply_reorder: checked rows become 'match', the rest 'omitida'."""
        out = []
        for p, on in zip(self._props, self._checked):
            out.append(replace(p, status="match" if on else ("omitida" if p.status in ("match", "ambiguous")
                                                             else p.status)))
        return out

    def checked_count(self) -> int:
        return sum(self._checked)

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._props)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, section, orientation, role=R.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == R.DisplayRole:
            return self.COLUMNS[section]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 0 and self.checkable(index.row()):
            f |= Qt.ItemFlag.ItemIsUserCheckable
        return f

    def data(self, index, role=R.DisplayRole):
        if not index.isValid() or index.row() >= len(self._props):
            return None
        p = self._props[index.row()]
        col = index.column()
        t = self._theme
        if role == R.CheckStateRole and col == 0 and self.checkable(index.row()):
            return Qt.CheckState.Checked if self._checked[index.row()] else Qt.CheckState.Unchecked
        if role == R.DisplayRole:
            if col == 1:
                return f"{p.pos:02d}" if p.pos else ""
            if col == 2:
                return p.src.name if p.src is not None else ""
            if col == 3:
                if p.dst is None:
                    return ""
                return "(sin cambios)" if p.src == p.dst else p.dst.name
            if col == 4:
                return f"{p.score:.0f}%" if p.score else ""
            if col == 5:
                return REORDER_STATUS_ES.get(p.status, p.status)
            return None
        if role == R.DecorationRole and col == 5 and p.status in REORDER_STATUS_ICON:
            return state_icon(t, REORDER_STATUS_ICON[p.status])
        if role == R.ForegroundRole and col == 5 and p.status in REORDER_STATUS_ICON:
            return QColor(t.state_color(REORDER_STATUS_ICON[p.status]))
        if role == R.FontRole and col in (1, 4):
            return mono_font(t, "sm")
        if role == R.ToolTipRole:
            return p.reason_es
        return None

    def setData(self, index, value, role=R.EditRole):  # noqa: N802
        if role == R.CheckStateRole and index.column() == 0 and self.checkable(index.row()):
            self._checked[index.row()] = Qt.CheckState(value) == Qt.CheckState.Checked
            self.dataChanged.emit(self.index(index.row(), 0), self.index(index.row(), len(self.COLUMNS) - 1))
            self.edited.emit()
            return True
        return False
