"""Package the add-on into dist/smart_tris_to_quads-<version>.zip.

Install the zip in Blender: Edit > Preferences > Add-ons > (v) > Install from Disk.
Run:  python tools/build.py
"""
import ast
import os
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PKG = os.path.join(ROOT, "smart_tris_to_quads")


def version():
    src = open(os.path.join(PKG, "__init__.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "bl_info":
            info = ast.literal_eval(node.value)
            return ".".join(str(x) for x in info["version"])
    return "0.0.0"


def main():
    out_dir = os.path.join(ROOT, "dist")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"smart_tris_to_quads-{version()}.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(os.listdir(PKG)):
            if name.endswith(".py"):
                z.write(os.path.join(PKG, name), f"smart_tris_to_quads/{name}")
    print("built", out)
    return out


if __name__ == "__main__":
    main()
