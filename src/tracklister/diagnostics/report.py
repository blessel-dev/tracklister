"""The REDACTED Diagnostico report the user pastes back in the chat ("Copiar informe").

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

No own username/password/IP, peers as peer-1, peer-2... Checked with assert_no_secrets before
it is returned.

1.0.1 (R7): the pseudonym goes in the peer column only; the rest of the text is redacted without the
peer names (a peer called "50" left «título distinto (peer-6%)» in his report). A candidate line seen
several times (the same peer, folder, file, size...) is printed once with «(×N)».
"""
from __future__ import annotations

from datetime import datetime

from tracklister.diagnostics.redact import Redactor, assert_no_secrets
from tracklister.diagnostics.run import DiagRow, mb_text as _mb, mmss_text as _mmss
from tracklister.engine.spec import DEFAULT_ENGINE_ID, ENGINE_PINS
from tracklister.pipeline.report import row_label

SELF_CHECK = ("Comprobación: este informe no contiene tu usuario, tu contraseña ni direcciones IP; "
              "los usuarios de Soulseek aparecen como peer-1, peer-2...")


def engine_exe(engine_id: str) -> str:
    """The program that listens on the port, so the one the Windows Firewall asks about: the engine
    (sockseek.exe, or sldl.exe for the fallback), not Tracklister.exe."""
    pin = ENGINE_PINS.get(engine_id.removeprefix("fake:")) or ENGINE_PINS[DEFAULT_ENGINE_ID]
    return pin.exe_name


def build_report(diag: list[DiagRow], *, app_version: str, engine_id: str, windows_version: str,
                 listen_port: int, redactor: Redactor) -> str:
    lines = ["Diagnóstico de Tracklister", "",
             f"Fecha: {datetime.now():%Y-%m-%d %H:%M}",
             f"Tracklister {app_version}  |  Motor {engine_id}  |  {windows_version}",
             f"Puerto de escucha: {listen_port}", ""]
    searched = len(diag)
    with_cands = sum(1 for d in diag if d.candidates)
    accepted = sum(1 for d in diag if any(c.accepted for c in d.candidates))
    errors = sum(1 for d in diag if d.error_es and not d.candidates)
    lines.append(f"Filas buscadas: {searched}; con resultados: {with_cands}; con un candidato válido: {accepted}; "
                 f"sin resultados o con error: {errors}.")
    lines.append("")
    for d in diag:
        r = d.row
        exp = f"  (duración esperada {_mmss(r.expected_duration_s)})" if r.expected_duration_s else ""
        lines.append(f"{r.pos:02d}. {row_label(r)}{exp}")
        if d.error_es:
            lines.append(f"    ! {d.error_es}")
        for c in d.candidates:
            peer = redactor.peer(c.peer)
            br = f"{c.bitrate} kbps" if c.bitrate else "? kbps"
            times = f" (\u00d7{c.repeats})" if c.repeats > 1 else ""
            lines.append(f"    - {peer} | {c.path_tail} | {_mb(c.size)} | {br} | {_mmss(c.duration_s)} | "
                         f"{c.score:.0f}/100 | {c.why_es}{times}")
        if d.result_es:
            lines.append(f"    Descarga: {d.result_es}")
        lines.append("")
    if searched and with_cands == 0:
        lines += ["No ha llegado ningún resultado. Qué puedes probar:",
                  f"  1. Abre el puerto TCP {listen_port} en el router hacia la IP local de este PC.",
                  f"  2. Permite «{engine_exe(engine_id)}» (el motor de descarga de Tracklister) en el Firewall "
                  "de Windows, en redes privadas. Está en %LOCALAPPDATA%\\Tracklister\\tools\\engines.",
                  "  3. Si tu operador usa CGNAT no podrás abrir el puerto: pide una IP pública.",
                  "  4. Si otro amigo usa Tracklister en tu misma red, usad puertos distintos (Ajustes).",
                  "  5. Comprueba tu usuario y contraseña de Soulseek en Ajustes.", ""]
    lines.append(SELF_CHECK)
    # the peer column already holds the pseudonyms: never search the free text for peer names (R7)
    text = redactor.redact("\n".join(lines) + "\n", peers=False)
    assert_no_secrets(text, redactor.secrets)
    return text
