import math
import sys

import _setup  # noqa: F401
import bmesh


def to_bmesh(m):
    bm = bmesh.new()
    lay = bm.verts.layers.int.new("orig")
    vs = [bm.verts.new(p) for p in m["v3"]]
    for i, v in enumerate(vs):
        v[lay] = i
    for t in m["tris"]:
        bm.faces.new([vs[i] for i in t])
    bm.verts.index_update()
    bm.verts.ensure_lookup_table()
    bm.normal_update()
    return bm


def faces_of(bm):
    lay = bm.verts.layers.int["orig"]
    return [tuple(v[lay] for v in f.verts) for f in bm.faces]


def quad_quality(f):
    """Worst corner-angle deviation from 90 deg (degrees)."""
    vs = [v.co for v in f.verts]
    worst = 0.0
    for i in range(4):
        a, b, c = vs[i - 1], vs[i], vs[(i + 1) % 4]
        u, w = a - b, c - b
        if u.length < 1e-12 or w.length < 1e-12:
            return 180.0
        ang = math.degrees(u.angle(w))
        worst = max(worst, abs(ang - 90))
    return worst


def is_convex(f):
    vs = [v.co for v in f.verts]
    n = f.normal
    s = None
    for i in range(4):
        e1 = vs[(i + 1) % 4] - vs[i]
        e2 = vs[(i + 2) % 4] - vs[(i + 1) % 4]
        d = e1.cross(e2).dot(n)
        if abs(d) < 1e-14:
            continue
        if s is None:
            s = d > 0
        elif (d > 0) != s:
            return False
    return True


def metrics(bm, gt):
    gtset = set(gt)
    tris = quads = good = bogus = concave = ngons = 0
    qual = []
    for f in bm.faces:
        n = len(f.verts)
        if n > 4:
            ngons += 1
        if n == 3:
            tris += 1
        elif n == 4:
            quads += 1
            key = frozenset(v[bm.verts.layers.int['orig']] for v in f.verts)
            if key in gtset:
                good += 1
            else:
                bogus += 1
            if not is_convex(f):
                concave += 1
            qual.append(quad_quality(f))
    qual.sort()
    return dict(
        tris=tris, quads=quads, ngons=ngons,
        gt_recovered=f"{good}/{len(gt)}",
        other_quads=bogus, concave=concave,
        bad_shape=sum(1 for q in qual if q > 60),
        median_dev=round(qual[len(qual) // 2], 1) if qual else None,
    )


def run_stock(bm, topo=0.0, face=40.0, shape=40.0, sharp_angle=None):
    if sharp_angle is not None:
        lim = math.radians(sharp_angle)
        for e in bm.edges:
            if len(e.link_faces) == 2 and e.calc_face_angle() >= lim:
                e.smooth = False
    bmesh.ops.join_triangles(
        bm, faces=bm.faces[:], cmp_sharp=sharp_angle is not None,
        angle_face_threshold=math.radians(face),
        angle_shape_threshold=math.radians(shape),
        topology_influence=topo)
