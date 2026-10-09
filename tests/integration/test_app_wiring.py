"""The window wired to the REAL inputs, enrichment, update check, library and pipeline.

SPDX-License-Identifier: GPL-3.0-or-later

Offline: HTTP from recorded fixtures, the FAKE engine for every download (never Soulseek).
"""
from __future__ import annotations

import json

import pytest

from tests.integration.conftest import SAMPLE_CSV, make_services, replay
from tracklister import config
from tracklister.core.model import ResultState
from tracklister.gui.models import fmt_clock

pytestmark = [pytest.mark.gui, pytest.mark.slow]
S = ResultState


def _wait_import(qtbot, page, until=None, timeout=60000):
    qtbot.waitUntil(lambda: not page._busy and page.model.rowCount() > 0 and (until is None or until()),
                    timeout=timeout)


def _wait_done(qtbot, window, timeout=120000):
    qtbot.waitUntil(lambda: not window.worker_running() and window.results.phase.text() == "Terminado.",
                    timeout=timeout)


# ---- import + 'Completar datos' -----------------------------------------------------------------------
def test_trackid_csv_then_enrichment_through_the_window(qtbot, open_window, tmp_path):
    http, rt = replay()
    services = make_services(tmp_path, http=http, enrichment=True)
    w = open_window(services)
    page = w.new_set
    page.import_source(SAMPLE_CSV)
    _wait_import(qtbot, page, lambda: "Datos completados" in page.banner.message())
    rows = page.model.rows()
    tracks = [r for r in rows if not r.is_id]
    assert len(rows) == 21 and len(tracks) == 17                       # 4 gaps > 90 s became "ID (hueco)"
    assert [r.pos for r in rows] == list(range(1, 22))
    assert page.banner.message() == ("Datos completados: 17 de 21 pistas (iTunes 17). "
                                     "17 con duración esperada.")
    liebing = next(r for r in tracks if r.title == "Higher Things")
    assert liebing.version == "FJAAK Remix" and liebing.expected_duration_s == 289    # the remix, not 4:58
    roll = next(r for r in tracks if r.title == "The Red House")
    assert roll.artist_display == "Roll Dann" and roll.expected_duration_s == 340
    i = rows.index(liebing)
    assert page.model.data(page.model.index(i, page.model.column_of("duration"))) == fmt_clock(289) == "04:49"
    # what was sent: only artist + title, with the app User-Agent; the store answered first every time
    assert {c.host for c in rt.calls} == {"itunes.apple.com"} and len(rt.calls) == 17
    assert all(dict(c.headers)["User-Agent"] == config.user_agent() for c in rt.calls)
    sent = " ".join(v for c in rt.calls for _, v in c.params)
    assert "usuario-prueba" not in sent and "clave-prueba" not in sent
    cache = json.loads(services.paths.enrich_cache_file.read_text(encoding="utf-8"))
    assert cache["schema"] == "tracklister.enrichcache/1" and len(cache["entries"]) == 17
    # The same tracklist imported again ("Reemplazar la tabla"): enriched from the cache, no request.
    w.prompter.choose_answers = [0]
    page.banner.hide()
    page.import_source(SAMPLE_CSV)
    _wait_import(qtbot, page, lambda: "Datos completados" in page.banner.message())
    assert len(rt.calls) == 17
    assert next(r for r in page.model.rows() if r.title == "Higher Things").expected_duration_s == 289


# ---- the user's own Excel-style CSV -> download -> folder in tracklist order ---------------------------
def _own_csv(path):
    """What Excel saves as 'CSV (delimitado por punto y coma)': cp1252, ';', CRLF, Spanish headers."""
    text = ("Nº;Artista;Título;Duración\r\n"
            "1;Fjaak;Spirit;0:30\r\n"
            "2;Chris Liebing;Higher Things (FJAAK Remix);0:32\r\n"
            "3;ID;ID;\r\n"
            "4;Sigur Rós;Glaður;0:26\r\n")
    path.write_bytes(text.encode("cp1252"))
    return path


def _network(tmp_path):
    """The fake Soulseek: the right files for rows 1, 2 and 4 (row 4 without tags), served in
    the opposite order to the table, so the NN prefix can only come from the row index."""
    def f(peer, path, artist, title, dur, tags=True):
        return {"peer": peer, "path": path, "artist": artist, "title": title, "duration_s": dur, "format": "flac",
                "samplerate": 44100, "bitdepth": 16, "bitrate_kbps": None, "vbr": False,
                "audio": {"lowpass_hz": None, "truncate_to_s": None, "tags": tags, "tag_title": None,
                          "tag_artist": None}}
    net = {"schema": "tracklister.fakenet/1", "search_delay_ms": 0, "ban_after_searches": None, "peers": {},
           "files": [f("peerC", "@@x\\Sigur Rós\\Sigur Rós - Glaður.flac", "Sigur Rós", "Glaður", 26, tags=False),
                     f("peerB", "@@techno\\Chris Liebing\\Chris Liebing - Higher Things (FJAAK Remix).flac",
                       "Chris Liebing", "Higher Things (FJAAK Remix)", 32),
                     f("peerA", "@@musica\\Fjaak\\Fjaak - Spirit.flac", "Fjaak", "Spirit", 30)]}
    p = tmp_path / "fakenet-own-csv.json"
    p.write_text(json.dumps(net, ensure_ascii=False), encoding="utf-8")
    return p


def test_own_csv_download_names_by_row_index_and_rerun_is_idempotent(qtbot, open_window, prompter, tmp_path):
    services = make_services(tmp_path, network=_network(tmp_path))
    w = open_window(services)
    page = w.new_set
    csv_path = _own_csv(tmp_path / "Mi set de prueba.csv")
    page.import_source(csv_path)
    _wait_import(qtbot, page)
    rows = page.model.rows()
    assert [(r.pos, r.artist_display, r.title, r.version, r.expected_duration_s, r.download) for r in rows] == [
        (1, "Fjaak", "Spirit", None, 30, True),
        (2, "Chris Liebing", "Higher Things", "FJAAK Remix", 32, True),
        (3, "ID", "ID", None, None, False),
        (4, "Sigur Rós", "Glaður", None, 26, True)]
    assert page.name.text() == "Mi set de prueba"
    assert page.download_btn.text() == "Descargar 3 pistas"
    page.request_download()
    assert w.current_page() == "results"
    _wait_done(qtbot, w)
    m = w.results.model
    assert {r.pos: m.state_of(r.uid) for r in m.rows()} == {1: S.VERIFICADO, 2: S.VERIFICADO, 3: S.OMITIDA,
                                                           4: S.VERIFICADO}
    set_dir = w.session.set_dir
    assert set_dir == tmp_path / "biblioteca" / "Mi set de prueba"
    audio = sorted(p.name for p in set_dir.glob("*.flac"))
    assert audio == ["01 - Fjaak - Spirit.flac", "02 - Chris Liebing - Higher Things (FJAAK Remix).flac",
                     "04 - Sigur Rós - Glaður.flac"]
    res4 = w.session.doc.results[rows[3].uid]
    assert "sin_tags" in res4.flags and res4.peer == "peerC"
    assert (set_dir / "Informe - Mi set de prueba.txt").is_file()
    w.results.copy_btn.click()
    assert services.copied[-1].splitlines()[:2] == ["01. Fjaak - Spirit",
                                                    "02. Chris Liebing - Higher Things (FJAAK Remix)"]
    assert [c[0] for c in prompter.calls if c[0] in ("ask_duplicate", "ask_lossy")] == []
    passes = len(w.session.doc.passes)
    sizes = {p.name: p.stat().st_size for p in set_dir.glob("*.flac")}
    lib = services.library()
    assert len(lib.entries) == 3

    # The same CSV again ("Reemplazar la tabla"): the existing set is completed, nothing is
    # downloaded or asked again.
    w.go("new_set")
    prompter.choose_answers = [0]
    n_calls = len(prompter.calls)
    page.import_source(csv_path)
    qtbot.waitUntil(lambda: not page._busy and any(c[0] == "choose" for c in prompter.calls[n_calls:]),
                    timeout=30000)
    assert [c[1] for c in prompter.calls[n_calls:] if c[0] == "choose"] == ["Ya hay una tracklist en la tabla"]
    assert page.model.rowCount() == 4 and "Ya existe este set" in page.dest.text()
    page.request_download()
    _wait_done(qtbot, w)
    assert len(w.session.doc.passes) == passes
    assert {p.name: p.stat().st_size for p in set_dir.glob("*.flac")} == sizes
    assert {r.pos: w.results.model.state_of(r.uid) for r in w.results.model.rows()}[4] == S.VERIFICADO
    assert [c[0] for c in prompter.calls if c[0] == "ask_duplicate"] == []


# ---- update notice (mocked GitHub) ----------------------------------------------------------------------
def test_update_notice_with_link_once_a_day(qtbot, open_window, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "GITHUB_OWNER", "tracklister-test")
    http, rt = replay("github", "newer")
    services = make_services(tmp_path, http=http)
    w = open_window(services)
    w.check_updates()
    qtbot.waitUntil(lambda: w.update_holder.isVisible(), timeout=15000)
    msg = w.update_banner.message()
    assert msg.startswith("Tracklister 1.0.1 ya está disponible") and "no se instala nada solo" in msg
    action = w.update_banner.actions.itemAt(0).widget()
    assert action.text() == "Ver la novedad"
    action.click()
    assert services.opened_urls == ["https://github.com/tracklister-test/tracklister/releases/tag/v1.0.1"]
    assert len(rt.calls) == 1 and rt.calls[0].url == config.releases_latest_api_url()
    assert dict(rt.calls[0].headers)["User-Agent"] == config.user_agent()
    state = json.loads(services.paths.update_state_file.read_text(encoding="utf-8"))
    assert state["latest_seen"] == "1.0.1"
    # later the same day (a new launch reads update.json): the notice again, without a request
    again = make_services(tmp_path, http=http).check_for_update()
    assert again is not None and again.latest == "1.0.1" and len(rt.calls) == 1


def test_no_update_request_while_the_owner_is_a_placeholder(qtbot, open_window, tmp_path):
    assert config.GITHUB_OWNER == "OWNER_PLACEHOLDER"
    http, rt = replay("github", "newer")
    w = open_window(make_services(tmp_path, http=http))
    w.check_updates()
    qtbot.waitUntil(lambda: not w.pool.busy(), timeout=15000)
    qtbot.wait(200)
    assert rt.calls == [] and not w.update_holder.isVisible()
