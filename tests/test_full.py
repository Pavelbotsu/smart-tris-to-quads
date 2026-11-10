# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pavlo Botsula
import sys, time, math
import bpy  # noqa
import bmesh
from mathutils.bvhtree import BVHTree
from collections import Counter
import _setup  # noqa: F401
import bench, meshgen, test_blender_models as T
from smart_tris_to_quads import engine as flowquads, fullquad


def run(m, loops=True):
    bm = bench.to_bmesh(m)
    from mathutils.bvhtree import BVHTree as _B
    surf = _B.FromBMesh(bm)
    orig = BVHTree.FromPolygons([tuple(p) for p in m["v3"]], [tuple(t) for t in m["tris"]])
    t0 = time.time()
    flowquads.grid_tris_to_quads(bm, bm.faces[:], sharp_angle=0.5236, merge_leftovers=True,
                                 continue_loops=loops)
    t1 = time.time()
    r = fullquad.full_quads(bm, set(bm.faces), surface=surf)
    t2 = time.time()
    hist = Counter(min(len(f.verts), 5) for f in bm.faces)
    # shape check: every vertex and every face centre must lie on the original surface
    dev = 0.0
    for v in bm.verts:
        dev = max(dev, orig.find_nearest(v.co)[3])
    size = max((max(c) - min(c)) for c in zip(*m["v3"]))
    # quad shape
    worst = []
    for f in bm.faces:
        if len(f.verts) == 4:
            worst.append(bench.quad_quality(f))
    worst.sort()
    return bm, dict(hist=dict(hist), **r, shape_dev_pct=round(100 * dev / size, 4),
                    median_corner_dev=round(worst[len(worst) // 2], 1),
                    corners_over_60=sum(1 for w in worst if w > 60),
                    t_quads=round(t1 - t0, 2), t_full=round(t2 - t1, 2))


if __name__ == "__main__":
    cases = [("cad", meshgen.panel_mesh("cad")), ("poly", meshgen.panel_mesh("poly")),
             ("cad/random", meshgen.panel_mesh("cad", diag="random", seed=1))]
    for meth in ("FIXED", "BEAUTY"):
        cases.append(("box/" + meth, T.prepare(T.bevelled_box(), meth)))
        cases.append(("cyl/" + meth, T.prepare(T.bevelled_cylinder(), meth)))
    for name, m in cases:
        bm, r = run(m)
        print(f"{name:12s}", r)
        bm.free()
