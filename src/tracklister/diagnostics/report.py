"""The REDACTED Diagnostico report the user pastes back in the chat ("Copiar informe").

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

No own username/password/IP, peers as peer-1, peer-2... Checked with assert_no_secrets before
it is returned.
"""
from __future__ import annotations

from datetime import datetime

from tracklister.diagnostics.redact import Redactor, assert_no_secrets
from tracklister.diagnostics.run import DiagRow
from tracklister.pipeline.report import row_label

SELF_CHECK = ("Comprobacion: este informe no contiene tu usuario, tu contrasena ni direcciones IP; "
              "los usuarios de Soulseek aparecen como peer-1, peer-2...")


def _mmss(s: float | None) -> str:
    if not s:
        return "?"
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"


def _mb(n: int | None) -> str:
    return f"{n / (1024 * 1024):.1f} MB" if n else "? MB"


def build_report(diag: list[DiagRow], *, app_version: str, engine_id: str, windows_version: str,
                 listen_port: int, redactor: Redactor) -> str:
    lines = ["Diagnostico de Tracklister", "",
             f"Fecha: {datetime.now():%Y-%m-%d %H:%M}",
             f"Tracklister {app_version}  |  Motor {engine_id}  |  {windows_version}",
             f"Puerto de escucha: {listen_port}", ""]
    searched = len(diag)
    with_cands = sum(1 for d in diag if d.candidates)
    accepted = sum(1 for d in diag if any(c.accepted for c in d.candidates))
    errors = sum(1 for d in diag if d.error_es and not d.candidates)
    lines.append(f"Filas buscadas: {searched}; con resultados: {with_cands}; con un candidato valido: {accepted}; "
                 f"sin resultados o con error: {errors}.")
    lines.append("")
    for d in diag:
        r = d.row
        exp = f"  (duracion esperada {_mmss(r.expected_duration_s)})" if r.expected_duration_s else ""
        lines.append(f"{r.pos:02d}. {row_label(r)}{exp}")
        if d.error_es:
            lines.append(f"    ! {d.error_es}")
        for c in d.candidates:
            peer = redactor.peer(c.peer)
            br = f"{c.bitrate} kbps" if c.bitrate else "? kbps"
            lines.append(f"    - {peer} | {c.path_tail} | {_mb(c.size)} | {br} | {_mmss(c.duration_s)} | "
                         f"{c.score:.0f}/100 | {c.why_es}")
        if d.result_es:
            lines.append(f"    Descarga: {d.result_es}")
        lines.append("")
    if searched and with_cands == 0:
        lines += ["No ha llegado ningun resultado. Que puedes probar:",
                  f"  1. Abre el puerto TCP {listen_port} en el router hacia la IP local de este PC.",
                  "  2. Permite Tracklister en el Firewall de Windows (redes privadas).",
                  "  3. Si tu operador usa CGNAT no podras abrir el puerto: pide una IP publica.",
                  "  4. Si otro amigo usa Tracklister en tu misma red, usad puertos distintos (Ajustes).",
                  "  5. Comprueba tu usuario y contrasena de Soulseek en Ajustes.", ""]
    lines.append(SELF_CHECK)
    text = redactor.redact("\n".join(lines) + "\n")
    assert_no_secrets(text, redactor.secrets)
    return text
