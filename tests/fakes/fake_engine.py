"""FAKE Soulseek engine: an offline stand-in for Sockseek 3.0.5 / sldl 2.6.0.

Owner: ENGINE branch.
SPDX-License-Identifier: GPL-3.0-or-later

It never opens a socket. Imports: stdlib, numpy/soundfile/mutagen through tests/fakes/synth.py.
It parses the SAME argv as tracklister.engine.cli.build_command (`-p` -> sldl 2.x mimic,
`--output-dir` -> Sockseek 3.x mimic), reads a fake network from the JSON file named by the
environment variable TRACKLISTER_FAKE_NETWORK (schema tracklister.fakenet/1) and reproduces the
real engines' outputs as captured in tests/fixtures/engine/mock-run/: files in in/<snum>/, the
index CSV, the m3u playlist, the log file, --no-progress lines and exit codes.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
import time
import unicodedata
import uuid
import zlib
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import synth  # noqa: E402

V3, V2 = "sockseek3", "sldl2"
VALUE_FLAGS = {"--input-type", "--user", "--pass", "--output-dir", "-p", "--name-format", "--index-path",
               "--log-file", "--listen-port", "--artist-col", "--title-col", "--length-col",
               "--time-format", "--format", "--min-bitrate", "--max-samplerate", "--length-tol",
               "--playlist-path", "--concurrent-jobs", "--concurrent-downloads", "--searches-per-time",
               "--searches-renew-time", "--print", "--mock-files-dir", "--banned-users"}
BOOL_FLAGS = {"--no-config", "--no-progress", "--no-modify-share-count", "--strict-title",
              "--strict-artist", "--no-skip-existing", "--write-playlist", "--no-listen"}
V3_ONLY = {"--output-dir", "--concurrent-jobs", "--no-listen"}
V2_ONLY = {"-p", "--concurrent-downloads"}
KICKED = ("Soulseek server kicked this client, probably because the same account logged in "
          "elsewhere. Stopping this run.")


def lp(p) -> str:
    """Long-path form on Windows (the real engines are .NET and long-path aware)."""
    s = os.path.abspath(str(p))
    if os.name == "nt" and len(s) >= 240 and not s.startswith("\\\\?\\"):
        return "\\\\?\\" + s
    return s


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def phrase_in(needle: str, hay: str) -> bool:
    n, h = norm(needle), norm(hay)
    return bool(n) and re.search(r"(^| )" + re.escape(n) + r"( |$)", h) is not None


class Out:
    def __init__(self, log_path: Path | None, dialect: str):
        self.log_path, self.dialect = log_path, dialect
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)

    def line(self, text: str, level: str = "info", console: bool = True) -> None:
        if console:
            sys.stdout.write(text + "\n")
            sys.stdout.flush()
        if self.log_path:
            lvl = level if self.dialect == V3 else level.capitalize()
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} [{lvl}] {text.strip()}\n")


def parse_argv(argv: list[str]) -> tuple[dict, str | None]:
    opts: dict = {"positional": None}
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok.startswith("--") and "=" in tok:
            flag, val = tok.split("=", 1)
            if flag not in VALUE_FLAGS:
                return opts, f"Unknown argument: {flag}"
            opts[flag] = val
        elif tok in VALUE_FLAGS:
            if i + 1 >= len(argv):
                return opts, f"Option '{tok}' requires a parameter"
            opts[tok] = argv[i + 1]
            i += 1
        elif tok in BOOL_FLAGS:
            opts[tok] = True
        elif tok.startswith("-") and len(tok) > 1:
            return opts, f"Unknown argument: {tok}"
        elif opts["positional"] is None:
            opts["positional"] = tok
        else:
            return opts, f"Invalid argument '{tok}'. Input is already set"
        i += 1
    return opts, None


def read_items(opts: dict) -> list[dict]:
    if opts.get("--input-type") == "string":
        d = {"artist": "", "title": "", "length": None}
        for part in re.split(r",\s*(?=(?:artist|title|length)=)", opts["positional"] or ""):
            k, _, v = part.partition("=")
            k = k.strip()
            if k == "length":
                d["length"] = int(v) if v.strip() else None
            elif k in ("artist", "title"):
                d[k] = v.strip()
        return [dict(d, snum=1, line=1)]
    text = Path(opts["positional"]).read_text(encoding="utf-8")
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0]
    ai, ti, li = (header.index(opts.get(k, d)) for k, d in
                  (("--artist-col", "Artist"), ("--title-col", "Title"), ("--length-col", "Length")))
    items = []
    for n, r in enumerate(rows[1:], start=1):
        if not r:
            continue
        length = r[li].strip()
        items.append({"snum": n, "line": n + 1, "artist": r[ai], "title": r[ti],
                      "length": int(length) if length else None})
    return items


def file_ext(path: str) -> str:
    base = path.replace("\\", "/").rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[-1].lower() if "." in base else ""


def file_base(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def is_result(f: dict, item: dict) -> bool:
    """Soulseek search semantics: every query word appears somewhere in the path."""
    words = norm(f"{item['artist']} {item['title']}").split()
    hay = set(norm(f["path"]).split())
    return bool(words) and all(w in hay for w in words)


def passes(f: dict, item: dict, opts: dict) -> bool:
    # like both engines: comma-separated, each name trimmed, exact match on the peer name
    banned = {x.strip() for x in (opts.get("--banned-users") or "").split(",") if x.strip()}
    if f["peer"] in banned:
        return False
    fmts = [x.strip() for x in (opts.get("--format") or "").split(",") if x.strip()]
    if fmts and file_ext(f["path"]) not in fmts:
        return False
    if opts.get("--min-bitrate") and f.get("bitrate_kbps") is not None:
        if f["bitrate_kbps"] < int(opts["--min-bitrate"]):
            return False
    if opts.get("--max-samplerate") and f.get("samplerate") is not None and f.get("announce_samplerate", True):
        if f["samplerate"] > int(opts["--max-samplerate"]):
            return False
    if opts.get("--length-tol") and item["length"] and f.get("duration_s") is not None \
            and f.get("announce_length", True):
        if abs(int(f["duration_s"]) - item["length"]) > int(opts["--length-tol"]):
            return False
    if opts.get("--strict-title"):
        stem = file_base(f["path"]).rsplit(".", 1)[0]
        if not phrase_in(item["title"], stem):
            return False
    if opts.get("--strict-artist") and not phrase_in(item["artist"], f["path"]):
        return False
    return True


def display(f: dict, short: bool = True) -> str:
    parts = f["path"].replace("/", "\\").split("\\")
    tail = "\\".join(parts[-3:]) if len(parts) > 3 else "\\".join(parts)
    return f"{f['peer']}\\..\\{tail}" if len(parts) > 3 else f"{f['peer']}\\{tail}"


def json_file(f: dict) -> dict:
    d: dict = {}
    if f.get("duration_s") is not None and f.get("announce_length", True):
        d["Length"] = int(f["duration_s"])
    d["Filename"] = f["path"]
    d["Size"] = int(f.get("size") or 1000000)
    if f.get("bitrate_kbps") is not None:
        d["Bitrate"] = int(f["bitrate_kbps"])
    if f.get("samplerate") is not None and f.get("announce_samplerate", True):
        d["SampleRate"] = int(f["samplerate"])
    if f.get("bitdepth") is not None and f.get("format") in ("flac", "wav", "aiff"):
        d["BitDepth"] = int(f["bitdepth"])
    return {"User": {"Username": f["peer"], "UploadSpeed": 1.5, "HasFreeUploadSlot": True}, "File": d}


def write_audio(f: dict, item: dict, dst: Path) -> None:
    a = f.get("audio") or {}
    tags = None
    if a.get("tags", True):
        tags = {"artist": a.get("tag_artist") or f.get("artist") or item["artist"],
                "title": a.get("tag_title") or f.get("title") or item["title"]}
        if a.get("cover"):
            tags["cover"] = synth.tiny_png()
    synth.make_track(dst, fmt=f.get("format") or file_ext(f["path"]), seconds=float(f.get("duration_s") or 20),
                     samplerate=int(f.get("samplerate") or 44100), bitdepth=int(f.get("bitdepth") or 16),
                     lowpass_hz=a.get("lowpass_hz"), mp3_kbps=f.get("real_kbps") or f.get("bitrate_kbps"),
                     vbr=bool(f.get("vbr")), tags=tags, truncate_to_s=a.get("truncate_to_s"),
                     seed=int(a.get("seed", zlib.crc32(f["path"].encode("utf-8")) % 1000)),
                     float_pcm=bool(a.get("float_pcm")),
                     low_treble=bool(a.get("low_treble")),
                     mp3_info_frame=not bool(a.get("no_info_frame")))


REASONS_V3 = {"no_results": (9, "NoSearchResults", "No search results", "No Soulseek file results found."),
              "no_match": (10, "NoMatchingResults", "No matching results",
                           "No Soulseek results satisfied the file conditions."),
              "all_failed": (4, "AllDownloadsFailed", "All downloads failed", "All download attempts failed.")}
REASONS_V2 = {"no_results": (3, "NoSuitableFileFound"), "no_match": (3, "NoSuitableFileFound"),
              "all_failed": (4, "AllDownloadsFailed")}


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:  # noqa: BLE001
        pass
    dialect_env = os.environ.get("TRACKLISTER_FAKE_DIALECT", V3)
    if "--help" in argv or "-h" in argv:
        name = "help-sockseek-3.0.5.txt" if dialect_env == V3 else "help-sldl-2.6.0.txt"
        sys.stdout.write((HERE.parent / "fixtures" / "engine" / name).read_text(encoding="utf-8"))
        return 0
    if "--version" in argv:
        print("3.0.5" if dialect_env == V3 else "2.6.0.0")
        return 0
    opts, err = parse_argv(argv)
    dialect = V2 if "-p" in opts else V3
    if err is None:
        bad = (V2_ONLY if dialect == V3 else V3_ONLY) & set(opts)
        if bad:
            err = f"Unknown argument: {sorted(bad)[0]}"
    if err is None and not (opts.get("--user") and opts.get("--pass")):
        err = "Missing Soulseek username and password. Provide --user and --pass."
    if err is None and not opts.get("--no-config"):
        err = "fake engine: --no-config is required (no config file may be read)"
    if err:
        print(("Input error: " if dialect == V3 else "") + err)
        return 2 if dialect == V3 else 1
    net_path = os.environ.get("TRACKLISTER_FAKE_NETWORK")
    net = json.loads(Path(net_path).read_text(encoding="utf-8")) if net_path else {"files": [], "peers": {}}
    out_dir = Path(opts.get("--output-dir") or opts.get("-p"))
    log = Out(Path(opts["--log-file"]) if opts.get("--log-file") else None, dialect)
    user = opts["--user"]
    items = read_items(opts)
    delay = (net.get("search_delay_ms") or 0) / 1000.0
    ban_after = net.get("ban_after_searches")
    peers = net.get("peers") or {}

    if dialect == V3:
        log.line("[cli] Starting CLI session in local mode")
        log.line(f"[soulseek] Logging in as {user}..")
    else:
        log.line(f"Login {user}")
    if net.get("login_fails"):
        # wrong password / account open elsewhere: the whole run fails before any search
        if dialect == V3:
            log.line("[cli] Soulseek login failed: LoginRejectedException: INVALIDPASS", level="error")
        else:
            log.line(f"Login failed definitively for {user} after 3 attempts.", level="error")
        return 1

    if opts.get("--print") == "json-all":
        for it in items:
            res = [f for f in net.get("files", []) if is_result(f, it) and passes(f, it, opts)]
            print(json.dumps([json_file(f) for f in res], ensure_ascii=False, separators=(",", ":")))
        return 0

    if dialect == V3:
        log.line(f"[001] ExtractJob: CSV: Input: {opts['positional']}")
        log.line(f"[cli] Downloading {len(items)} tracks:")
    else:
        log.line(f"Input (CSV): {opts['positional']}")
        log.line(f"Downloading {len(items)} tracks:")
    for it in items:
        print(f"  {it['artist']} - {it['title']}" + (f" ({it['length']}s)" if it["length"] else ""))

    results: dict[int, dict] = {}
    searches = 0
    banned = False
    for it in items:
        q = f"{it['artist']} - {it['title']}"
        did = f"[{it['snum'] + 2:03d}] SongJob:"
        if ban_after is not None and searches >= int(ban_after):
            log.line(f"[soulseek] {KICKED}" if dialect == V3 else KICKED, level="error")
            banned = True
            break
        searches += 1
        log.line(f"{did} searching: {q}" if dialect == V3 else
                 f"Searching: {q}" + (f" ({it['length']}s)" if it["length"] else ""))
        if delay:
            time.sleep(delay)
        found = [f for f in net.get("files", []) if is_result(f, it)]
        cands = [f for f in found if passes(f, it, opts)]
        if not cands:
            kind = "no_results" if not found else "no_match"
            results[it["snum"]] = {"state": 2, "kind": kind, "item": it}
            if dialect == V3:
                _, _, label, msg = REASONS_V3[kind]
                log.line(f"{did} failed [{label}]: {q}")
                log.line(f"    Error: {msg}")
            else:
                log.line(f"Not found: {q}")
            continue
        done = False
        for f in cands:
            peer = peers.get(f["peer"], {})
            log.line(f"{did} downloading: {q}: {display(f)}" if dialect == V3 else
                     f"Initialize: {display(f)} [{f.get('duration_s') or -1}s]")
            if peer.get("slow"):
                time.sleep(float(peer.get("slow_s", 30)))
            if peer.get("timeout"):
                if dialect == V3:
                    log.line(f"{did} download attempt failed: {q}: {display(f)}", level="warn")
                else:
                    log.line("TimedOut:".ljust(14) + f" {display(f)}")
                continue
            name = opts.get("--name-format", "{snum}/{slsk-filename}")
            # like the real engines: Windows-invalid characters become spaces (--invalid-replace-str)
            stem = re.sub(r'[<>:"/\\|?*]', " ", file_base(f["path"]).rsplit(".", 1)[0]).strip(" .")
            ext = "." + file_ext(f["path"]) if file_ext(f["path"]) else ""
            rel = (name.replace("{snum}", str(it["snum"])).replace("{row}", str(it["line"]))
                   .replace("{slsk-filename}", stem).replace("{ext}", ext)) + ext
            dst = out_dir / Path(rel)
            if dialect == V3:
                stage = out_dir / ".sockseek-staging" / uuid.uuid4().hex / (stem + ext + ".incomplete")
                write_audio(f, it, Path(lp(stage)))
                os.makedirs(lp(dst.parent), exist_ok=True)
                os.replace(lp(stage), lp(dst))
                try:
                    os.rmdir(lp(stage.parent))
                except OSError:
                    pass
            else:
                write_audio(f, it, Path(lp(dst)))
            results[it["snum"]] = {"state": 1, "file": dst, "f": f, "item": it}
            log.line(f"{did} succeeded: {q}: {display(f)}" if dialect == V3 else
                     "Succeeded:".ljust(14) + f" {display(f)}")
            done = True
            break
        if not done:
            results[it["snum"]] = {"state": 2, "kind": "all_failed", "item": it}
            if dialect == V3:
                _, _, label, msg = REASONS_V3["all_failed"]
                log.line(f"{did} failed [{label}]: {q}")
                log.line(f"    Error: {msg}")

    # index + playlist (written also after a ban, for the items processed so far)
    idx = opts.get("--index-path")
    if idx:
        base = Path(idx).parent
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        buf.write("filepath,artist,album,title,length,tracktype,state,failurereason\n")
        for snum in sorted(results):
            r = results[snum]
            it = r["item"]
            if r["state"] == 1:
                relp = os.path.relpath(r["file"], base)
                p = "./" + (relp.replace("\\", "/") if dialect == V3 else relp)
                reason = 0
            else:
                p = ""
                reason = (REASONS_V3 if dialect == V3 else REASONS_V2)[r["kind"]][0]
            w.writerow([p, it["artist"], "", it["title"], it["length"] or -1, 0, r["state"], reason])
        buf.write("\n")
        Path(idx).write_text(buf.getvalue(), encoding="utf-8", newline="")
    if opts.get("--write-playlist") and opts.get("--playlist-path"):
        pl = Path(opts["--playlist-path"])
        lines = []
        for snum in sorted(results):
            r = results[snum]
            it = r["item"]
            if r["state"] == 1:
                lines.append(os.path.relpath(r["file"], pl.parent))
            else:
                name = (REASONS_V3 if dialect == V3 else REASONS_V2)[r["kind"]][1]
                lines.append(f"#FAIL: {it['artist']} - {it['title']} [{name}]")
        pl.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok = sum(1 for r in results.values() if r["state"] == 1)
    failed = len(items) - ok
    if banned:
        return 1
    log.line(f"[cli] Completed: {ok} succeeded, {failed} failed." if dialect == V3 else
             f"Completed: {ok} succeeded, {failed} failed.")
    if dialect == V3:
        return 1 if failed else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
