"""Make the add-on package importable from the tests (outside Blender, with the
`bpy` pip module) and expose its modules under short names."""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import bpy  # noqa: E402,F401  (must be imported before bmesh)
