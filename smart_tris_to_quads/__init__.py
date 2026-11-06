"""Smart Tris to Quads - a smarter Alt+J for triangulated (STL) meshes.

Modules
-------
engine.py    triangle pairing (grid-aware tris -> quads) + fan clean-up
bevels.py    "Continue Rows Through Bevels": rebuild dense bevel bands
flat.py      "Rebuild Flat CAD Faces": re-cut flat sliver areas
fullquad.py  "Full Quad": add points so only quads remain
ui.py        operator, sidebar panel, menu entry, preferences, keymap
"""

bl_info = {
    "name": "Smart Tris to Quads (grid-aware Alt+J)",
    "author": "Pavlo Botsula",
    "version": (4, 1, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Tris2Quads | Edit Mode: Face menu, Shift+Alt+J",
    "description": "Tris to quads that follows the real grid and carries rows straight "
                   "across bevels, plus a Full Quad mode that adds points to leave only quads",
    "category": "Mesh",
}

if "bpy" in locals():
    # Blender's "Reload Scripts" (F3) or the VS Code Blender extension
    # re-runs this file: reload the modules so edits are picked up.
    import importlib
    for _m in (bevels, flat, engine, fullquad, ui):  # noqa: F821
        importlib.reload(_m)

import bpy  # noqa: E402,F401  (must come before bmesh-using modules)

from . import bevels, flat, engine, fullquad, ui  # noqa: E402,F401


def register():
    ui.register()


def unregister():
    ui.unregister()
