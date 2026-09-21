#!/usr/bin/env python3
"""Build this folder into a Folio source, ready to be served.

    python3 tools/build.py                 build and, if a key is available, sign
    python3 tools/build.py --key key.pem   sign with a key file instead of the environment
    python3 tools/build.py --no-sign       build only, which is what a pull request should do

It reads `source.json` and every folder under `packages/`, then writes `_site/`:

    _site/index.json          the list, built from the packages so it can never disagree with them
    _site/entry.json          the signed pointer to the list, with its sha256 and size
    _site/entry.json.sig      the signature, base64 DER, over entry.json's exact bytes
    _site/key.pub             the public key, so a phone can pin it the first time
    _site/packages/*.foliopkg one zip per package
    _site/assets/             the pictures the list and the pages point at
    _site/index.html          a web page for people who open the address in a browser, with an Open in Folio button

The signing key never lives in the repository. In CI it comes from the FOLIO_SOURCE_KEY secret; locally, point --key
at a file you keep elsewhere. Everything else about a source is public by design.

Signing follows Folio's ADR 0002: ECDSA P-256 with SHA-256, signatures base64 DER, the key published as base64 SPKI,
and `keyId` the first eight bytes of the key's SHA-256. The work is done with openssl, which is on every runner and
every Mac, so this script needs nothing installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / "_site"
PACKAGE_FILES = {".json", ".png", ".webp", ".jpg", ".jpeg", ".js"}
DEFAULT_MAX_AGE_DAYS = 14


def signing_time() -> int:
    """When the index was signed: SOURCE_DATE_EPOCH if it is set (seconds, or an ISO 8601 date), otherwise now.

    A push passes its push time, so rebuilding the same push gives the same bytes. A scheduled or manual run passes
    nothing and gets the current time, which is what keeps the index from going stale between pushes.
    """
    raw = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    if raw.isdigit():
        return int(raw)
    if raw:
        from datetime import datetime
        return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp())
    return int(time.time())


def fail(message: str) -> None:
    print(f"build: {message}", file=sys.stderr)
    raise SystemExit(1)


def openssl(args: list[str], stdin: bytes | None = None) -> bytes:
    try:
        done = subprocess.run(["openssl", *args], input=stdin, capture_output=True, check=True)
    except FileNotFoundError:
        fail("openssl is not installed, and the signing needs it")
    except subprocess.CalledProcessError as problem:
        fail(f"openssl {args[0]} failed: {problem.stderr.decode().strip()}")
    return done.stdout


def read_key(args) -> pathlib.Path | None:
    """The private key, from --key or from FOLIO_SOURCE_KEY, written somewhere only this process can read it."""
    if args.no_sign:
        return None
    if args.key:
        path = pathlib.Path(args.key)
        if not path.is_file():
            fail(f"{path} is not there")
        return path
    pem = os.environ.get("FOLIO_SOURCE_KEY", "").strip()
    if not pem:
        return None
    path = SITE.parent / ".signing-key.pem"
    path.write_text(pem + "\n")
    path.chmod(0o600)
    return path


def pack(folder: pathlib.Path, manifest: dict, out: pathlib.Path) -> None:
    """One package folder into one .foliopkg. Times are fixed so an unchanged package builds byte for byte the same."""
    files = sorted(p for p in folder.rglob("*") if p.is_file())
    for path in files:
        if path.suffix.lower() not in PACKAGE_FILES:
            fail(f"{path.relative_to(ROOT)}: a package may not contain this kind of file")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            info = zipfile.ZipInfo(str(path.relative_to(folder)), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())


def is_app(manifest: dict) -> bool:
    """An app of its own: Android installs it, so there is no .foliopkg, only where to get the APK."""
    return "externalApp" in manifest.get("kind", [])


def app_download(folder: pathlib.Path) -> dict | None:
    """
    Where an app's APK is, from app.json beside its manifest: {"url", "sha256", "size"}.

    Written by whatever makes the release, not by hand, because the checksum is the whole point and a typed one is
    a typo waiting. Without it the listing still works - Folio sends people to the stores in its `via` list - it
    just can't install the app itself.
    """
    path = folder / "app.json"
    if not path.is_file():
        return None
    app = json.loads(path.read_text())
    missing = [k for k in ("url", "sha256", "size") if k not in app]
    if missing:
        fail(f"{path.relative_to(ROOT)} is missing {', '.join(missing)}")
    if not str(app["url"]).startswith("https://"):
        fail(f"{path.relative_to(ROOT)}: an app's url must be an https:// link")
    return {"url": app["url"], "sha256": app["sha256"].lower(), "size": int(app["size"])}


def build_index(source: dict, packages: list[dict]) -> dict:
    """The index is generated, never hand-written, so it cannot drift from the packages it lists."""
    index = {
        "$schema": "https://folio.mccal.dev/schema/v1/index.schema.json",
        "format": 1,
        "name": source["name"],
    }
    for optional in ("description", "icon", "issuesUrl"):
        if source.get(optional):
            index[optional] = source[optional]
    if source.get("featured"):
        index["featured"] = source["featured"]
    index["packages"] = []
    for manifest, download in packages:
        entry = {"id": manifest["id"], "version": manifest["version"]}
        # Without url, sha256 and size a phone has nowhere to download from and nothing to check it against, so
        # every package this template published used to fail at Get.
        if download:
            entry.update(download)
        entry["manifest"] = {k: v for k, v in manifest.items() if k != "$schema"}
        index["packages"].append(entry)
    return index


def sign(path: pathlib.Path, key: pathlib.Path) -> None:
    der = openssl(["dgst", "-sha256", "-sign", str(key), str(path)])
    import base64

    path.with_suffix(path.suffix + ".sig").write_text(base64.b64encode(der).decode() + "\n")


def public_key(key: pathlib.Path) -> tuple[str, str]:
    """Returns the key as base64 SPKI and the keyId Folio will look for: the first 8 bytes of its SHA-256."""
    import base64

    spki = openssl(["ec", "-in", str(key), "-pubout", "-outform", "DER"])
    return base64.b64encode(spki).decode(), hashlib.sha256(spki).hexdigest()[:16].upper()


# The web page a person sees when they open the source's address in a browser. Folio never reads it: the phone
# only fetches entry.json, index.json and what they point at.
PAGE_MIN_FOLIO = "0.6.6"

PAGE_STYLE = """
:root{color-scheme:light dark;--bg:#f2f2f7;--card:#fff;--text:#000;--muted:#6c6c70;--line:#c6c6c8;--accent:#007aff;--field:#e9e9eb}
@media (prefers-color-scheme:dark){:root{--bg:#000;--card:#1c1c1e;--text:#fff;--muted:#98989f;--line:#38383a;--accent:#0a84ff;--field:#2c2c2e}}
*{box-sizing:border-box}
[hidden]{display:none!important}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);font:17px/1.4 -apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,Roboto,"Segoe UI",sans-serif;overflow-wrap:anywhere}
main{max-width:640px;margin:0 auto;padding:32px 16px 48px}
header{text-align:center;margin-bottom:24px}
header img{width:96px;height:96px;border-radius:22px;display:block;margin:0 auto 14px;box-shadow:0 1px 3px rgba(0,0,0,.15)}
h1{font-size:28px;line-height:1.2;margin:0 0 8px;font-weight:700}
header p{margin:0;color:var(--muted);font-size:16px}
.open{display:block;margin:20px 0 8px;padding:15px 20px;border-radius:14px;background:var(--accent);color:#fff;text-align:center;font-weight:600;text-decoration:none;font-size:17px}
.hint{color:var(--muted);font-size:13px;margin:0 16px 20px;text-align:center}
h2{font-size:13px;font-weight:400;text-transform:uppercase;letter-spacing:.02em;color:var(--muted);margin:28px 16px 7px}
.group{background:var(--card);border-radius:12px;overflow:hidden}
.row{display:flex;align-items:center;gap:12px;padding:11px 16px;position:relative}
.pkg+.pkg::before{content:"";position:absolute;top:0;right:0;left:76px;border-top:.5px solid var(--line)}
.pkg img,.pkg .blank{width:48px;height:48px;border-radius:11px;flex:none;background:var(--field)}
.pkg div{min-width:0;flex:1}
.pkg b{font-weight:600;display:block}
.pkg .meta{color:var(--muted);font-size:13px}
.pkg .desc{color:var(--muted);font-size:15px;margin-top:2px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.address code{flex:1;min-width:0;font:15px/1.4 ui-monospace,"SF Mono",Menlo,monospace;word-break:break-all}
button{font:inherit;font-size:15px;color:var(--accent);background:var(--field);border:0;border-radius:999px;padding:6px 14px;flex:none;cursor:pointer}
.fingerprint{font:15px/1.6 ui-monospace,"SF Mono",Menlo,monospace;padding:12px 16px;word-spacing:.2em}
.note{color:var(--muted);font-size:13px;margin:7px 16px 0}
footer{margin-top:32px;text-align:center;font-size:13px;color:var(--muted)}
footer a{color:var(--accent);text-decoration:none}
"""

PAGE_SCRIPT = """
(function () {
  var base = location.origin + location.pathname.replace(/[^/]*$/, "");
  var address = document.getElementById("address");
  var code = address.querySelector("code");
  code.textContent = base;
  address.hidden = false;
  document.getElementById("no-address").hidden = true;
  if (location.protocol === "https:") {
    var open = document.getElementById("open");
    open.href = "folio://source/" + encodeURIComponent(base);
    open.hidden = false;
    document.getElementById("open-hint").hidden = false;
  } else {
    document.getElementById("not-https").hidden = false;
  }
  var copy = document.getElementById("copy");
  copy.addEventListener("click", function () {
    function done() { copy.textContent = "Copied"; setTimeout(function () { copy.textContent = "Copy"; }, 1500); }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(base).then(done, function () {});
    } else {
      var range = document.createRange();
      range.selectNodeContents(code);
      var selection = getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      try { if (document.execCommand("copy")) done(); } catch (e) {}
    }
  });
})();
"""


def english(value) -> str:
    """A name or description as the page shows it: the string itself, or the English one of a translated set."""
    if isinstance(value, dict):
        return str(value.get("en") or next(iter(value.values()), ""))
    return "" if value is None else str(value)


def newer_than(version: str, floor: str) -> bool:
    def parts(text: str) -> list[int]:
        return [int(p) if p.isdigit() else 0 for p in text.split("-")[0].split(".")]
    return parts(version) > parts(floor)


def build_page(index: dict, fingerprint: str | None) -> str:
    """index.html, from the index this build just wrote, so the page can't disagree with what a phone reads."""
    from html import escape

    name = escape(english(index.get("name")))
    description = english(index.get("description"))
    icon = index.get("icon")
    out = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="color-scheme" content="light dark">',
        f"<title>{name}, a Folio source</title>",
    ]
    if description:
        out.append(f'<meta name="description" content="{escape(description)}">')
    if icon:
        out.append(f'<link rel="icon" href="{escape(icon)}">')
    out += [f"<style>{PAGE_STYLE}</style>", "</head>", "<body>", "<main>", "<header>"]
    if icon:
        out.append(f'<img src="{escape(icon)}" alt="">')
    out.append(f"<h1>{name}</h1>")
    if description:
        out.append(f"<p>{escape(description)}</p>")
    out += [
        "</header>",
        '<a class="open" id="open" href="#" hidden>Open in Folio</a>',
        '<p class="hint" id="open-hint" hidden>This opens Folio\'s Add a source sheet with this address filled in. '
        "It works on an Android phone with Folio 0.6.6 or later.</p>",
        '<p class="hint" id="not-https" hidden>Folio only adds sources served over https, '
        "so the Open in Folio button is left out here.</p>",
        "<h2>Address</h2>",
        '<div class="group">',
        '<div class="row address" id="address" hidden><code></code><button type="button" id="copy">Copy</button></div>',
        '<div class="row" id="no-address">Copy this page\'s address from the address bar and add it in Folio as a source.</div>',
        "</div>",
        f'<p class="note">Needs Folio {PAGE_MIN_FOLIO} or later. Folio shows the source\'s key fingerprint '
        "and asks you to confirm it before it trusts the source.</p>",
    ]
    if fingerprint:
        groups = " ".join(fingerprint[i:i + 4] for i in range(0, len(fingerprint), 4))
        out += [
            "<h2>Key fingerprint</h2>",
            f'<div class="group"><div class="fingerprint">{escape(groups)}</div></div>',
            '<p class="note">The fingerprint Folio shows when you add this source should match this one.</p>',
        ]

    packages = index.get("packages", [])
    out.append(f"<h2>{len(packages)} package{'' if len(packages) == 1 else 's'}</h2>")
    out.append('<div class="group">')
    apps = []
    for entry in packages:
        manifest = entry.get("manifest", {})
        package_name = english(manifest.get("name")) or entry.get("id", "")
        meta = [f"Version {entry.get('version', manifest.get('version', ''))}"]
        if "externalApp" in manifest.get("kind", []):
            meta.append("App")
            apps.append(package_name)
        min_folio = str(manifest.get("minFolio", ""))
        if min_folio and newer_than(min_folio, PAGE_MIN_FOLIO):
            meta.append(f"Needs Folio {min_folio}")
        out.append('<div class="row pkg">')
        package_icon = manifest.get("icon")
        out.append(f'<img src="{escape(package_icon)}" alt="">' if package_icon else '<span class="blank"></span>')
        out.append(f"<div><b>{escape(package_name)}</b>")
        out.append(f'<div class="meta">{escape(", ".join(meta))}</div>')
        package_description = english(manifest.get("description"))
        if package_description:
            out.append(f'<div class="desc">{escape(package_description)}</div>')
        out.append("</div></div>")
    out.append("</div>")
    if apps:
        if len(apps) == 1:
            line = f"{apps[0]} is an app of its own, so Android asks you before installing it."
        else:
            line = f"{', '.join(apps[:-1])} and {apps[-1]} are apps of their own, so Android asks you before installing them."
        out.append(f'<p class="note">{escape(line)}</p>')

    out.append("<footer>")
    links = ['<a href="index.json">index.json</a>']
    if str(index.get("issuesUrl", "")).startswith("https://"):
        links.append(f'<a href="{escape(index["issuesUrl"])}">Report a problem</a>')
    out.append(" &middot; ".join(links))
    out += ["</footer>", "</main>", f"<script>{PAGE_SCRIPT}</script>", "</body>", "</html>", ""]
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build this folder into a Folio source.")
    parser.add_argument("--key", help="a PEM private key to sign with")
    parser.add_argument("--no-sign", action="store_true", help="build without signing")
    args = parser.parse_args()

    source = json.loads((ROOT / "source.json").read_text())
    folders = sorted(p for p in (ROOT / "packages").iterdir() if p.is_dir()) if (ROOT / "packages").is_dir() else []
    if not folders:
        fail("there are no packages under packages/")

    if SITE.exists():
        shutil.rmtree(SITE)
    (SITE / "packages").mkdir(parents=True)

    manifests = []
    for folder in folders:
        manifest_path = folder / "manifest.json"
        if not manifest_path.is_file():
            fail(f"{folder.relative_to(ROOT)} has no manifest.json")
        manifest = json.loads(manifest_path.read_text())
        if is_app(manifest):
            manifests.append((manifest, app_download(folder)))
            continue
        archive = SITE / "packages" / f"{manifest['id']}.foliopkg"
        pack(folder, manifest, archive)
        data = archive.read_bytes()
        manifests.append((manifest, {
            "url": f"packages/{archive.name}",
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }))

    if (ROOT / "assets").is_dir():
        shutil.copytree(ROOT / "assets", SITE / "assets")
    if (ROOT / "revoked.json").is_file():
        shutil.copy(ROOT / "revoked.json", SITE / "revoked.json")

    index = build_index(source, manifests)
    index_bytes = (json.dumps(index, indent=2) + "\n").encode()
    (SITE / "index.json").write_bytes(index_bytes)

    fingerprint = None
    key = read_key(args)
    if key:
        spki, key_id = public_key(key)
        import base64

        fingerprint = hashlib.sha256(base64.b64decode(spki)).hexdigest().upper()
        (SITE / "key.pub").write_text(spki + "\n")
        entry = {
            "format": 1,
            "keyId": key_id,
            "timestamp": signing_time(),
            "maxAge": int(source.get("maxAgeDays", DEFAULT_MAX_AGE_DAYS)) * 24 * 60 * 60,
            "index": {
                "path": "index.json",
                "sha256": hashlib.sha256(index_bytes).hexdigest(),
                "size": len(index_bytes),
            },
        }
        (SITE / "entry.json").write_bytes((json.dumps(entry, indent=2) + "\n").encode())
        sign(SITE / "entry.json", key)
        if (SITE / "revoked.json").is_file():
            sign(SITE / "revoked.json", key)
        if key.name == ".signing-key.pem":
            key.unlink()
        print(f"signed with key {key_id}")
    else:
        print("not signed: Folio will call this source an unknown developer")

    (SITE / "index.html").write_text(build_page(index, fingerprint))

    validator = ROOT / "tools" / "folio-pkg.py"
    print()
    checked = subprocess.run([sys.executable, str(validator), "validate", str(SITE)])
    if checked.returncode != 0:
        fail("the source this built does not pass the validator")

    print(f"\n{len(manifests)} package(s) in _site, ready to serve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
