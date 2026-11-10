# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pavlo Botsula
import time
import sys

import _setup  # noqa: F401
import bench
import meshgen
import test_blender_models as T
from smart_tris_to_quads import engine as flowquads

cases = []
for var in ("poly", "cad"):
    for d in ("consistent", "random"):
        cases.append((f"{var}/{d}", meshgen.panel_mesh(var, diag=d, seed=1)))
for meth in ("FIXED", "ALTERNATE", "BEAUTY"):
    cases.append(("box/" + meth, T.prepare(T.bevelled_box(), meth)))
    cases.append(("cyl/" + meth, T.prepare(T.bevelled_cylinder(), meth)))

methods = [
    ("stock", lambda bm: bench.run_stock(bm)),
    ("stock topo1", lambda bm: bench.run_stock(bm, topo=1.0)),
    ("NEW", lambda bm: flowquads.grid_tris_to_quads(bm, bm.faces[:])),
    ("NEW+ngon", lambda bm: flowquads.grid_tris_to_quads(bm, bm.faces[:], merge_leftovers=True, sharp_angle=0.5236)),
    ("NEW+loops", lambda bm: flowquads.grid_tris_to_quads(bm, bm.faces[:], merge_leftovers=True,
                                                          continue_loops=True, sharp_angle=0.5236)),
]
print(f"{'case':16s}" + "".join(f"{n:>24s}" for n, _ in methods))
print(f"{'':16s}" + "".join(f"{'tris/true/wrong/ngon':>24s}" for _ in methods))
for name, m in cases:
    row = f"{name:16s}"
    for _, fn in methods:
        bm = bench.to_bmesh(m)
        fn(bm)
        r = bench.metrics(bm, m["gt"])
        row += f"{r['tris']:>8d}/{r['gt_recovered'].split('/')[0]:>4s}/{r['other_quads']:>4d}/{r['ngons']:>3d}  "
        bm.free()
    print(row + f" (of {len(m['gt'])} true quads, {len(m['tris'])} tris)")
