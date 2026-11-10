# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pavlo Botsula
"""Package the add-on into dist/smart_tris_to_quads-<version>.zip.

The zip works both ways:
- Blender 4.2+: installed as an extension (reads blender_manifest.toml).
- Blender 3.6 - 4.1: installed as a legacy add-on (reads bl_info).

Install the zip in Blender: Edit > Preferences > Add-ons > (v) > Install from Disk.

Run:
  python tools/build.py                   build the zip
  python tools/build.py --notes           print this version's CHANGELOG section (release notes)
  python tools/build.py --check-tag v4.1.0  fail if the tag does not match the version
"""
import argparse
import ast
import os
import re
import sys
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PKG_NAME = "smart_tris_to_quads"
PKG = os.path.join(ROOT, PKG_NAME)
MANIFEST = "blender_manifest.toml"


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def bl_info_version():
    tree = ast.parse(_read(os.path.join(PKG, "__init__.py")))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "bl_info":
            info = ast.literal_eval(node.value)
            return ".".join(str(x) for x in info["version"])
    sys.exit("error: bl_info not found in __init__.py")


def manifest_version():
    m = re.search(r'^version\s*=\s*"([^"]+)"', _read(os.path.join(PKG, MANIFEST)), re.M)
    if not m:
        sys.exit(f"error: no version in {MANIFEST}")
    return m.group(1)


def version():
    """The add-on version. bl_info and the manifest must agree."""
    a, b = bl_info_version(), manifest_version()
    if a != b:
        sys.exit(f"error: version mismatch: bl_info says {a}, {MANIFEST} says {b}")
    return a


def release_notes(ver):
    """The '## [ver]' section of CHANGELOG.md, without its heading."""
    text = _read(os.path.join(ROOT, "CHANGELOG.md"))
    m = re.search(rf"^## \[{re.escape(ver)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    if not m or not m.group(1).strip():
        sys.exit(f"error: CHANGELOG.md has no section for [{ver}]")
    return m.group(1).strip()


def build():
    ver = version()
    out_dir = os.path.join(ROOT, "dist")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{PKG_NAME}-{ver}.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(os.listdir(PKG)):
            if name.endswith(".py") or name == MANIFEST:
                z.write(os.path.join(PKG, name), f"{PKG_NAME}/{name}")
        z.write(os.path.join(ROOT, "LICENSE"), f"{PKG_NAME}/LICENSE")
    print("built", out)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--notes", action="store_true", help="print release notes and exit")
    ap.add_argument("--check-tag", metavar="TAG", help="fail unless TAG == v<version>")
    args = ap.parse_args()

    if args.check_tag:
        ver = version()
        if args.check_tag != f"v{ver}":
            sys.exit(f"error: tag {args.check_tag} does not match add-on version v{ver}")
        print(f"tag {args.check_tag} matches version {ver}")
        return
    if args.notes:
        print(release_notes(version()))
        return
    build()


if __name__ == "__main__":
    main()
