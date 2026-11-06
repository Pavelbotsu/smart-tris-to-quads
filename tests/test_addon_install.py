"""End-to-end check: install the built zip in Blender (pip `bpy` module or
`blender -b --python`), run the operator in Object and Edit Mode, Full Quad,
and check the shape is unchanged.

Run:  python tools/build.py  &&  python tests/test_addon_install.py
"""
import glob
import os
import sys
from collections import Counter

import bpy
import bmesh
from mathutils.bvhtree import BVHTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import meshgen  # noqa: E402

zips = sorted(glob.glob(os.path.join(HERE, "..", "dist", "smart_tris_to_quads-*.zip")))
assert zips, "build the zip first: python tools/build.py"
bpy.ops.preferences.addon_install(filepath=zips[-1], overwrite=True)
bpy.ops.preferences.addon_enable(module="smart_tris_to_quads")
print("installed", os.path.basename(zips[-1]), "in Blender", bpy.app.version_string)

m = meshgen.panel_mesh("cad")


def new_obj(name):
    me = bpy.data.meshes.new(name)
    me.from_pydata(m["v3"], [], m["tris"])
    me.update()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    for o in bpy.context.scene.objects:
        o.select_set(o == ob)
    bpy.context.view_layer.objects.active = ob
    return ob


orig = BVHTree.FromPolygons([tuple(p) for p in m["v3"]], [tuple(t) for t in m["tris"]])
fails = 0

ob = new_obj("smart")
bpy.ops.mesh.grid_tris_to_quads()
h = Counter(len(p.vertices) for p in ob.data.polygons)
print("smart:", dict(h))
fails += h.get(3, 0) > 60

ob = new_obj("full")
bpy.ops.mesh.grid_tris_to_quads(full_quad=True)
h = Counter(len(p.vertices) for p in ob.data.polygons)
dev = max(orig.find_nearest(v.co)[3] for v in ob.data.vertices)
print("full quad:", dict(h), "max shape deviation %.2e" % dev)
fails += set(h) != {4}
fails += dev > 1e-4

ob = new_obj("edit")
bpy.ops.object.mode_set(mode='EDIT')
bm = bmesh.from_edit_mesh(ob.data)
for f in bm.faces:
    f.select_set(f.calc_center_median().x > 5.0)
bmesh.update_edit_mesh(ob.data)
bpy.ops.mesh.grid_tris_to_quads(full_quad=True)
bm = bmesh.from_edit_mesh(ob.data)
left = Counter(len(f.verts) for f in bm.faces if f.calc_center_median().x < 4.7)
right = Counter(len(f.verts) for f in bm.faces if f.calc_center_median().x > 5.3)
bpy.ops.object.mode_set(mode='OBJECT')
print("edit mode: selected side", dict(right), "| unselected side", dict(left))
fails += set(left) != {3}
fails += set(right) != {4}

bpy.ops.preferences.addon_disable(module="smart_tris_to_quads")
print("PASS" if not fails else f"FAIL ({fails})")
sys.exit(1 if fails else 0)
