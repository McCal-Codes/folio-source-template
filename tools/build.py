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

    index_bytes = (json.dumps(build_index(source, manifests), indent=2) + "\n").encode()
    (SITE / "index.json").write_bytes(index_bytes)

    key = read_key(args)
    if key:
        spki, key_id = public_key(key)
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

    validator = ROOT / "tools" / "folio-pkg.py"
    print()
    checked = subprocess.run([sys.executable, str(validator), "validate", str(SITE)])
    if checked.returncode != 0:
        fail("the source this built does not pass the validator")

    print(f"\n{len(manifests)} package(s) in _site, ready to serve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
