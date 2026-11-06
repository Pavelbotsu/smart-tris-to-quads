"""Second test set: real quad models built with Blender's own tools (bevelled
box, bevelled cylinder with an inset), triangulated the way STL exporters do,
then converted back. Ground truth = the original quads."""
import math
import sys
import time

import bpy  # noqa: F401
import bmesh
from mathutils import Matrix

import bench
from smart_tris_to_quads import engine as flowquads
import plot


def bevelled_box(cuts=8, segs=3, width=0.08):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    bmesh.ops.scale(bm, vec=(1.6, 1.0, 0.6), verts=bm.verts)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=cuts, use_grid_fill=True)
    bm.normal_update()
    sharp = [e for e in bm.edges if len(e.link_faces) == 2 and e.calc_face_angle() > 1.0]
    bmesh.ops.bevel(bm, geom=sharp + list({v for e in sharp for v in e.verts}),
                    offset=width, segments=segs, affect='EDGES', profile=0.5)
    return bm


def bevelled_cylinder(n=48, rings=6, segs=3):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=n,
                          radius1=1.0, radius2=1.0, depth=1.2)
    # cut the side into rings
    side = [e for e in bm.edges if abs(e.verts[0].co.z - e.verts[1].co.z) > 0.5]
    bmesh.ops.subdivide_edges(bm, edges=side, cuts=rings, use_grid_fill=True)
    caps = [f for f in bm.faces if len(f.verts) > 4]
    # inset the caps a few times -> rings of quads on the caps
    for _ in range(3):
        res = bmesh.ops.inset_region(bm, faces=caps, thickness=0.15, depth=0.0)
    bm.normal_update()
    sharp = [e for e in bm.edges if len(e.link_faces) == 2 and e.calc_face_angle() > 1.0]
    bmesh.ops.bevel(bm, geom=sharp + list({v for e in sharp for v in e.verts}),
                    offset=0.06, segments=segs, affect='EDGES', profile=0.5)
    return bm


def prepare(bm, method):
    bm.verts.index_update()
    gt = [frozenset(v.index for v in f.verts) for f in bm.faces if len(f.verts) == 4]
    bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method=method, ngon_method='BEAUTY')
    bm.verts.index_update()
    v3 = [tuple(v.co) for v in bm.verts]
    tris = [tuple(v.index for v in f.verts) for f in bm.faces]
    return dict(v3=v3, tris=tris, gt=gt)


def run(name, make, method):
    src = make()
    m = prepare(src, method)
    src.free()
    print(f"\n{name} / triangulated {method}: {len(m['tris'])} tris, {len(m['gt'])} original quads")
    out = {}
    for label, fn in [
        ("stock Alt+J", lambda bm: bench.run_stock(bm)),
        ("stock topo=1", lambda bm: bench.run_stock(bm, topo=1.0)),
        ("NEW", lambda bm: flowquads.grid_tris_to_quads(bm, bm.faces[:])),
        ("NEW+fans", lambda bm: flowquads.grid_tris_to_quads(bm, bm.faces[:], merge_leftovers=True)),
    ]:
        bm = bench.to_bmesh(m)
        t0 = time.time()
        fn(bm)
        dt = time.time() - t0
        r = bench.metrics(bm, m["gt"])
        print(f"  {label:14s} tris={r['tris']:5d} quads={r['quads']:5d} ngons={r['ngons']:4d} "
              f"true={r['gt_recovered']:>11s} wrong-way={r['other_quads']:5d} {dt*1000:.0f}ms")
        out[label] = (bm, r)
    return m, out


if __name__ == "__main__":
    for method in ("FIXED", "BEAUTY", "ALTERNATE"):
        run("bevelled box", bevelled_box, method)
        run("bevelled cylinder", bevelled_cylinder, method)
