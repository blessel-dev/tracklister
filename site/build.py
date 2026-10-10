"""Assemble the Tracklister website (GitHub Pages) into one folder, deterministically.

SPDX-License-Identifier: GPL-3.0-or-later

    python site/build.py --out _site
    python site/build.py --out .tmp/_site --readme-dir <folder with the README images>

The same inputs give byte-identical output, locally and in .github/workflows/pages.yml. It needs the
standard library plus the pinned site tools in site/requirements-site.lock.txt (fontTools and
brotli, for the WOFF2 fonts).

What it copies into --out:
- site/: index.html, 404.html, css/, js/ (and img/, if site-only images are ever added). In the
  HTML, every {{icon:NAME}} mark becomes the brand's single-path SVG icon
  src/tracklister/assets/icons/NAME.svg, inlined and coloured by CSS (currentColor);
- css/tokens.css, written from src/tracklister/assets/tokens.json (the Hormigon and Noche colours),
  so the site never drifts from the app's palette;
- img/: the README images, docs/readme/**/*.png (screenshots, logo, social preview, state icons);
- img/brand/ and favicon.ico: the lockups, the header textures, the Blessel logo and the T icon;
- fonts/: Inter (400, 600, 700) and JetBrains Mono (400), subset to Latin, Latin-1 and Latin
  Extended-A (plus common punctuation) and converted to WOFF2, next to their OFL licence texts.

Before it finishes it checks the result and exits 1 on any problem: every local href, src and CSS
url() resolves; every same-page #anchor exists; every <img> has width and height with the file's
own aspect ratio; there is no inline script, <style> element, style="" or on*="" attribute (the
pages' CSP forbids them); and no {{...}} mark is left.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "site"
ASSETS = REPO / "src" / "tracklister" / "assets"
README_IMAGES = REPO / "docs" / "readme"

# site/ entries that are build inputs, not pages
NOT_PUBLISHED = {"build.py", "requirements-site.lock.txt", "__pycache__"}
# where the 404 page is served from on GitHub Pages (404.html must use root-relative paths, because
# GitHub serves it for missing URLs at any depth)
BASE_PATH = "/tracklister/"

BRAND = {  # src/tracklister/assets/<key> -> <out>/<value>
    "lockup/header-ink@2x.png": "img/brand/header-ink@2x.png",
    "lockup/header-light@2x.png": "img/brand/header-light@2x.png",
    "logo/blessel-ink@2x.png": "img/brand/blessel-ink@2x.png",
    "logo/blessel-light@2x.png": "img/brand/blessel-light@2x.png",
    "textures/header-hormigon.jpg": "img/brand/header-hormigon.jpg",
    "textures/header-noche.jpg": "img/brand/header-noche.jpg",
    "icon/png/tracklister-32.png": "img/brand/tracklister-32.png",
    "icon/png/tracklister-256.png": "img/brand/tracklister-256.png",
    "icon/tracklister.ico": "favicon.ico",
}

FONTS = (  # (source in assets/fonts, output in fonts/)
    ("Inter-Regular.ttf", "inter-400.woff2"),
    ("Inter-SemiBold.ttf", "inter-600.woff2"),
    ("Inter-Bold.ttf", "inter-700.woff2"),
    ("JetBrainsMono-Regular.ttf", "jetbrains-mono-400.woff2"),
)
FONT_LICENCES = ("OFL-Inter.txt", "OFL-JetBrainsMono.txt")
# Basic Latin, Latin-1 Supplement and Latin Extended-A (Spanish, and names such as "Dārin"), plus
# general punctuation (dashes, quotes, ellipsis, bullets), the euro and trade marks, arrows,
# multiplication/minus signs and <= / >=.
UNICODE_RANGES = ((0x0020, 0x007E), (0x00A0, 0x017F), (0x2000, 0x206F), (0x20AC, 0x20AC),
                  (0x2122, 0x2122), (0x2190, 0x2193), (0x2212, 0x2212), (0x2264, 0x2265))

MARKER = ".site-build"            # written into --out; a folder without it is never wiped
TEXT_SUFFIXES = {".html", ".css", ".js", ".txt", ".svg", ".json", ".xml", ".webmanifest"}
ICON_MARK = re.compile(r"\{\{icon:([a-z0-9_\-]+)\}\}")


class BuildError(Exception):
    pass


# ---- inputs ---------------------------------------------------------------------------------
def lf(data: bytes) -> bytes:
    """Text files are published with LF line endings, whatever the checkout used."""
    return data.replace(b"\r\n", b"\n")


def icon_svg(name: str) -> str:
    src = ASSETS / "icons" / f"{name}.svg"
    if not src.is_file():
        raise BuildError(f"icono desconocido: {{{{icon:{name}}}}} (falta {src.relative_to(REPO)})")
    root = ET.fromstring(src.read_text(encoding="utf-8"))
    paths = [el.get("d") for el in root.iter() if el.tag.endswith("path") and el.get("d")]
    if len(paths) != 1:
        raise BuildError(f"{src.name}: se esperaba un solo <path>, hay {len(paths)}")
    view_box = root.get("viewBox", "0 0 24 24")
    return (f'<svg class="ico" viewBox="{view_box}" width="24" height="24" aria-hidden="true" '
            f'focusable="false"><path d="{paths[0]}"/></svg>')


def render_html(text: str) -> str:
    return ICON_MARK.sub(lambda m: icon_svg(m.group(1)), text)


def tokens_css(tokens: dict) -> str:
    default = tokens["default_theme"]
    out = ["/* Generated by site/build.py from src/tracklister/assets/tokens.json. Do not edit. */",
           "/* Colours of the app's two themes; the default theme also applies without data-theme. */"]
    for theme in sorted(tokens["themes"], key=lambda t: (t != default, t)):
        colors = tokens["themes"][theme]["colors"]
        selector = f':root[data-theme="{theme}"]'
        if theme == default:
            selector = f":root,\n{selector}"
        scheme = "dark" if theme == "noche" else "light"
        out.append(f"{selector} {{")
        out.append(f"  color-scheme: {scheme};")
        for key in sorted(colors):
            value = colors[key]
            if not re.fullmatch(r"#[0-9a-f]{6}", value):
                raise BuildError(f"tokens.json: color raro en {theme}.{key}: {value!r}")
            out.append(f"  --{key.replace('_', '-')}: {value};")
        out.append("}")
    out.append(":root {")
    out.append(f"  --radius: {int(tokens['radius_px'])}px;")
    out.append(f"  --border: {int(tokens['border_px'])}px;")
    out.append(f"  --border-strong: {int(tokens['border_strong_px'])}px;")
    out.append("}")
    return "\n".join(out) + "\n"


def unicodes() -> list[int]:
    return [cp for lo, hi in UNICODE_RANGES for cp in range(lo, hi + 1)]


def make_woff2(src: Path, dst: Path) -> None:
    try:
        from fontTools import subset
    except ImportError as exc:      # pragma: no cover - the message is the point
        raise BuildError("falta fontTools: instala site/requirements-site.lock.txt en un venv") from exc
    try:
        import brotli  # noqa: F401  (fontTools needs it for WOFF2)
    except ImportError as exc:
        raise BuildError("falta brotli: instala site/requirements-site.lock.txt en un venv") from exc
    opts = subset.Options()
    opts.flavor = "woff2"
    opts.name_IDs = ["*"]            # keep the copyright and licence entries of the name table
    opts.name_legacy = True
    opts.name_languages = ["*"]
    opts.notdef_outline = True
    opts.hinting = False             # the web renderers do not need TrueType hinting
    opts.recalc_timestamp = False    # deterministic output
    font = subset.load_font(str(src), opts)
    try:
        sub = subset.Subsetter(opts)
        sub.populate(unicodes=unicodes())
        sub.subset(font)
        dst.parent.mkdir(parents=True, exist_ok=True)
        subset.save_font(font, str(dst), opts)
    finally:
        font.close()


# ---- output folder --------------------------------------------------------------------------
def prepare_out(out: Path) -> None:
    resolved = out.resolve()
    for protected in (REPO.resolve(), SITE.resolve(), ASSETS.resolve()):
        if resolved == protected or resolved in protected.parents:
            raise BuildError(f"--out no puede ser {protected} ni una carpeta que lo contenga")
    if out.exists():
        if not out.is_dir():
            raise BuildError(f"{out} no es una carpeta")
        if any(out.iterdir()) and not (out / MARKER).is_file():
            raise BuildError(f"{out} no está vacía y no es una salida de site/build.py: no la toco")
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / MARKER).write_text("Built by site/build.py; the whole folder is rebuilt every time.\n",
                              encoding="utf-8", newline="\n")


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    data = src.read_bytes()
    if src.suffix.lower() in TEXT_SUFFIXES:
        data = lf(data)
    dst.write_bytes(data)


def copy_site(out: Path) -> None:
    for src in sorted(SITE.rglob("*")):
        rel = src.relative_to(SITE)
        if any(part in NOT_PUBLISHED for part in rel.parts) or not src.is_file():
            continue
        if src.suffix in (".pyc", ".py"):
            continue
        dst = out / rel
        if src.suffix.lower() == ".html":
            dst.parent.mkdir(parents=True, exist_ok=True)
            text = lf(src.read_bytes()).decode("utf-8")
            dst.write_bytes(render_html(text).encode("utf-8"))
        else:
            copy_file(src, dst)


def copy_readme_images(out: Path, readme_dir: Path) -> int:
    if not readme_dir.is_dir():
        raise BuildError(f"no existe la carpeta de imágenes del README: {readme_dir}")
    n = 0
    for src in sorted(readme_dir.rglob("*.png")):
        copy_file(src, out / "img" / src.relative_to(readme_dir))
        n += 1
    if not n:
        raise BuildError(f"no hay ninguna imagen PNG en {readme_dir}")
    return n


def copy_brand(out: Path) -> None:
    for rel_src, rel_dst in BRAND.items():
        src = ASSETS / rel_src
        if not src.is_file():
            raise BuildError(f"falta el recurso de marca {src.relative_to(REPO)}")
        copy_file(src, out / rel_dst)


def build_fonts(out: Path) -> None:
    for src_name, dst_name in FONTS:
        make_woff2(ASSETS / "fonts" / src_name, out / "fonts" / dst_name)
    for name in FONT_LICENCES:
        copy_file(ASSETS / "fonts" / name, out / "fonts" / name)


# ---- checks ---------------------------------------------------------------------------------
def image_size(path: Path) -> tuple[int, int] | None:
    data = path.read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            i += 2 + seg_len
    return None


class PageScan(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[tuple[str, str, int]] = []      # (attribute, value, line)
        self.ids: set[str] = set()
        self.imgs: list[tuple[dict, int]] = []
        self.problems: list[str] = []
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        line = self.getpos()[0]
        if "id" in a:
            self.ids.add(a["id"])
        for k in a:
            if k == "style":
                self.problems.append(f"línea {line}: atributo style en <{tag}>")
            if k.startswith("on"):
                self.problems.append(f"línea {line}: manejador {k} en <{tag}>")
        if tag == "style":
            self.problems.append(f"línea {line}: elemento <style>")
        if tag == "script":
            if not a.get("src"):
                self.problems.append(f"línea {line}: <script> sin src")
            self._in_script = True
        for k in ("href", "src"):
            if k in a:
                if a[k].strip().lower().startswith("javascript:"):
                    self.problems.append(f"línea {line}: enlace javascript:")
                self.refs.append((k, a[k], line))
        if "srcset" in a:
            for part in a["srcset"].split(","):
                if part.strip():
                    self.refs.append(("srcset", part.strip().split()[0], line))
        if tag == "img":
            self.imgs.append((a, line))

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False

    def handle_data(self, data):
        if self._in_script and data.strip():
            self.problems.append(f"línea {self.getpos()[0]}: <script> con código dentro")


def resolve_local(out: Path, page: Path, ref: str) -> Path | None:
    """Local file a reference points to, or None for external/anchor/data references."""
    parts = urlsplit(ref)
    if parts.scheme or parts.netloc or ref.startswith("#") or not parts.path:
        return None
    path = unquote(parts.path)
    if path.startswith("/"):
        if not path.startswith(BASE_PATH):
            return out / "__fuera_del_sitio__" / path.lstrip("/")
        target = out / path[len(BASE_PATH):]
    else:
        target = (page.parent / path)
    if path.endswith("/") or target.is_dir():
        target = target / "index.html"
    return target


def check(out: Path) -> list[str]:
    problems: list[str] = []
    for page in sorted(out.rglob("*.html")):
        rel = page.relative_to(out).as_posix()
        text = page.read_text(encoding="utf-8")
        if "{{" in text or "}}" in text:
            problems.append(f"{rel}: queda una marca {{{{...}}}}")
        scan = PageScan()
        scan.feed(text)
        scan.close()
        problems += [f"{rel}: {p}" for p in scan.problems]
        for attr, ref, line in scan.refs:
            if ref.startswith("#") and len(ref) > 1 and unquote(ref[1:]) not in scan.ids:
                problems.append(f"{rel}:{line}: ancla {ref} sin destino")
            target = resolve_local(out, page, ref)
            if target is not None and not target.is_file():
                problems.append(f"{rel}:{line}: {attr}={ref!r} no existe")
        for a, line in scan.imgs:
            src = resolve_local(out, page, a.get("src", ""))
            if "alt" not in a:
                problems.append(f"{rel}:{line}: <img> sin alt")
            try:
                w, h = int(a.get("width", "")), int(a.get("height", ""))
            except ValueError:
                problems.append(f"{rel}:{line}: <img> sin width/height numéricos")
                continue
            size = image_size(src) if src is not None and src.is_file() else None
            if size and abs((w / h) - (size[0] / size[1])) > 0.01 * (size[0] / size[1]):
                problems.append(f"{rel}:{line}: {a.get('src')} mide {size[0]}x{size[1]}, "
                                f"pero width/height dicen {w}x{h}")
    for css in sorted(out.rglob("*.css")):
        rel = css.relative_to(out).as_posix()
        for m in re.finditer(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", css.read_text(encoding="utf-8")):
            target = resolve_local(out, css, m.group(1))
            if target is not None and not target.is_file():
                problems.append(f"{rel}: url({m.group(1)}) no existe")
    return problems


def tree_digest(out: Path) -> tuple[int, int, str]:
    h = hashlib.sha256()
    files = total = 0
    for p in sorted(x for x in out.rglob("*") if x.is_file()):
        data = p.read_bytes()
        h.update(p.relative_to(out).as_posix().encode("utf-8") + b"\0" + hashlib.sha256(data).digest())
        files += 1
        total += len(data)
    return files, total, h.hexdigest()


def build(out: Path, readme_dir: Path) -> int:
    prepare_out(out)
    copy_site(out)
    tokens = json.loads((ASSETS / "tokens.json").read_text(encoding="utf-8"))
    (out / "css").mkdir(parents=True, exist_ok=True)
    (out / "css" / "tokens.css").write_bytes(tokens_css(tokens).encode("utf-8"))
    n_images = copy_readme_images(out, readme_dir)
    copy_brand(out)
    build_fonts(out)
    problems = check(out)
    files, total, digest = tree_digest(out)
    print(f"site: {files} archivos, {total / 1024:.0f} KB, {n_images} imágenes del README, sha256 {digest}")
    for p in problems:
        print(f"ERROR {p}")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=REPO / "_site", help="carpeta de salida (se rehace entera)")
    ap.add_argument("--readme-dir", type=Path, default=README_IMAGES,
                    help="carpeta con las imágenes del README (por defecto docs/readme)")
    args = ap.parse_args(argv)
    try:
        return build(args.out.resolve(), args.readme_dir.resolve())
    except BuildError as exc:
        print(f"ERROR {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
