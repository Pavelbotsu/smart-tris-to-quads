"""Rebuild flat areas.

CAD exporters cover a flat face with a handful of huge sliver triangles that
run edge to edge. Pairing those gives long random slivers. Because the area
is perfectly flat, its inside can be redrawn freely without changing the
shape: clear it to one face, then cut it with straight, parallel lines that
connect points facing each other on the two sides of the outline, i.e. the
rows/rungs arriving from the fillets and faces around it carry straight on
across. Pieces that don't come out as quads are left for the normal steps
(Full Quad finishes them).
"""
import math

import bmesh
from mathutils import Vector


def _angle(u, w):
    lu, lw = u.length, w.length
    if lu < 1e-12 or lw < 1e-12:
        return math.pi
    c = u.dot(w) / (lu * lw)
    return math.acos(max(-1.0, min(1.0, c)))


def _fkey(f):
    c = f.calc_center_median()
    return (round(c.x, 6), round(c.y, 6), round(c.z, 6), len(f.verts))


def _quad_worst(f):
    vs = [v.co for v in f.verts]
    w = 0.0
    for i in range(4):
        a, b, c = vs[i - 1], vs[i], vs[(i + 1) % 4]
        w = max(w, abs(_angle(a - b, c - b) - math.pi / 2))
    return w


def _match(a_pos, b_pos, skip):
    n, m = len(a_pos), len(b_pos)
    INF = float("inf")
    D = [[INF] * (m + 1) for _ in range(n + 1)]
    P = [[None] * (m + 1) for _ in range(n + 1)]
    D[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            d = D[i][j]
            if d == INF:
                continue
            if i < n and d + skip < D[i + 1][j]:
                D[i + 1][j] = d + skip
                P[i + 1][j] = (i, j, False)
            if j < m and d + skip < D[i][j + 1]:
                D[i][j + 1] = d + skip
                P[i][j + 1] = (i, j, False)
            if i < n and j < m:
                c = abs(a_pos[i] - b_pos[j])
                if c < 2 * skip and d + c < D[i + 1][j + 1]:
                    D[i + 1][j + 1] = d + c
                    P[i + 1][j + 1] = (i, j, True)
    pairs = []
    i, j = n, m
    while (i, j) != (0, 0):
        pi, pj, ok = P[i][j]
        if ok:
            pairs.append((pi, pj))
        i, j = pi, pj
    pairs.reverse()
    return pairs


def _outline(faces):
    fs = set(faces)
    bedges = [e for f in faces for e in f.edges
              if sum(1 for g in e.link_faces if g in fs) == 1]
    ve = {}
    for e in bedges:
        for v in e.verts:
            ve.setdefault(v, []).append(e)
    if not ve or any(len(x) != 2 for x in ve.values()):
        return None
    # one single loop only (no holes)
    start = min(ve, key=lambda v: (round(v.co.x, 6), round(v.co.y, 6), round(v.co.z, 6)))
    loop = [start]
    prev_e = ve[start][0]
    v = prev_e.other_vert(start)
    while v is not start:
        loop.append(v)
        es = ve[v]
        nxt = es[0] if es[1] is prev_e else es[1]
        prev_e = nxt
        v = nxt.other_vert(v)
        if len(loop) > len(ve):
            return None
    if len(loop) != len(ve):
        return None                           # several loops = a face with holes
    return loop


def _plan_cuts(loop, n, c):
    """Cut lines across the outline along direction `c` (unit, in the plane).
    Returns (score, [(i, j)]) with loop indices, or None."""
    k = len(loop)
    u = n.cross(c).normalized()
    t = [v.co.dot(u) for v in loop]
    i0 = min(range(k), key=lambda i: t[i])
    i1 = max(range(k), key=lambda i: t[i])
    if i0 == i1:
        return None
    ca = [(i0 + x) % k for x in range((i1 - i0) % k + 1)]          # i0 -> i1
    cb = [(i1 + x) % k for x in range((i0 - i1) % k + 1)]          # i1 -> i0
    cb = list(reversed(cb))                                         # i0 -> i1
    tol = 1e-6 * (t[i1] - t[i0] + 1e-12)
    for ch in (ca, cb):                       # both sides must run one way along u
        for a, b in zip(ch[:-1], ch[1:]):
            if t[b] < t[a] - tol:
                return None
    ia = ca[1:-1]
    ib = cb[1:-1]
    ta = [t[i] for i in ia]
    tb = [t[i] for i in ib]
    allt = sorted(ta + tb)
    gaps = sorted(b - a for a, b in zip(allt[:-1], allt[1:]) if b - a > tol)
    typ = gaps[len(gaps) // 2] if gaps else (t[i1] - t[i0])
    pairs = _match(ta, tb, skip=0.5 * typ)
    cuts = [(ia[p], ib[q]) for p, q in pairs]
    if not cuts:
        return None
    slant = sum(abs(ta[p] - tb[q]) for p, q in pairs) / (len(pairs) * max(typ, 1e-12))
    unmatched = (len(ia) - len(pairs)) + (len(ib) - len(pairs))
    score = unmatched + 0.5 * slant
    return score, cuts


def _segments_cross(p1, p2, q1, q2, n):
    def orient(a, b, c):
        return (b - a).cross(c - a).dot(n)
    d1, d2 = orient(p1, p2, q1), orient(p1, p2, q2)
    d3, d4 = orient(q1, q2, p1), orient(q1, q2, p2)
    return d1 * d2 < 0 and d3 * d4 < 0


def rebuild_flat_regions(bm, scope_faces, flat_tol=math.radians(0.5), min_faces=3,
                         is_blocked=None):
    """Returns (regions rebuilt, cut lines)."""
    scope = {f for f in scope_faces if f.is_valid}
    bm.normal_update()
    seen = set()
    n_regions = n_cuts = 0
    for f0 in sorted(scope, key=_fkey):
        if f0 in seen or not f0.is_valid:
            continue
        n0 = f0.normal.copy()
        comp = [f0]
        seen.add(f0)
        stack = [f0]
        while stack:
            f = stack.pop()
            for e in f.edges:
                if len(e.link_faces) != 2 or (is_blocked is not None and is_blocked(e)):
                    continue
                g = e.link_faces[0] if e.link_faces[1] == f else e.link_faces[1]
                if g in seen or g not in scope:
                    continue
                if _angle(g.normal, n0) > flat_tol or _angle(g.normal, f.normal) > flat_tol:
                    continue
                if f.material_index != g.material_index:
                    continue
                seen.add(g)
                comp.append(g)
                stack.append(g)
        if len(comp) < min_faces:
            continue
        loop = _outline(comp)
        if loop is None or len(loop) < 5:
            continue
        # Only redraw CAD-style areas: the triangles span the whole face, with
        # (almost) no points inside it. A triangulated grid has plenty of
        # inner points and is left to the normal pairing, which handles it well.
        perim = sum((loop[i].co - loop[i - 1].co).length for i in range(len(loop)))
        area = sum(f.calc_area() for f in comp)
        if perim <= 0 or area / (perim * perim) < 0.035:
            continue                          # a long thin strip (one row): leave it
        inner = {v for f in comp for v in f.verts} - set(loop)
        if len(inner) > 0.1 * len(loop):
            continue
        # and the triangles are slivers (a CAD export), not reasonable shapes
        mins = []
        for f in comp:
            if len(f.verts) == 3:
                a, b, c = (v.co for v in f.verts)
                mins.append(min(_angle(b - a, c - a), _angle(a - b, c - b), _angle(a - c, b - c)))
        if not mins or sorted(mins)[len(mins) // 2] > math.radians(15.0):
            continue
        n = Vector()
        for f in comp:
            n += f.normal * f.calc_area()
        if n.length < 1e-12:
            continue
        n.normalize()
        # candidate cut directions: along the rows arriving from outside,
        # and the outline's main axes
        dirs = []
        for v in loop:
            for e in v.link_edges:
                if any(g in comp for g in e.link_faces):
                    continue
                d = v.co - e.other_vert(v).co
                d = d - n * d.dot(n)
                if d.length > 1e-12:
                    dirs.append(d.normalized())
        c0 = sum((v.co for v in loop), Vector()) / len(loop)
        far = max(loop, key=lambda v: (v.co - c0).length)
        ax = far.co - c0
        ax = ax - n * ax.dot(n)
        if ax.length > 1e-12:
            ax.normalize()
            dirs += [ax, n.cross(ax).normalized()]
        # cluster: keep a few distinct directions (lines don't care about sign)
        cand = []
        for d in dirs:
            if all(abs(d.dot(x)) < math.cos(math.radians(8)) for x in cand):
                cand.append(d)
            if len(cand) >= 12:
                break
        best = None
        for d in cand:
            r = _plan_cuts(loop, n, d)
            if r is not None and (best is None or r[0] < best[0]):
                best = r
        if best is None:
            continue
        cuts = best[1]
        # every cut must stay inside the outline
        okc = []
        for (i, j) in cuts:
            a, b = loop[i].co, loop[j].co
            bad = False
            for x in range(len(loop)):
                p, q = loop[x - 1], loop[x]
                if p in (loop[i], loop[j]) or q in (loop[i], loop[j]):
                    continue
                if _segments_cross(a, b, p.co, q.co, n):
                    bad = True
                    break
            if not bad:
                okc.append((i, j))
        if not okc:
            continue
        res = bmesh.ops.dissolve_faces(bm, faces=comp, use_verts=False)
        region = [f for f in res.get("region", []) if f.is_valid]
        if len(region) != 1:
            continue
        made = 0
        for (i, j) in okc:
            va, vb = loop[i], loop[j]
            if bm.edges.get((va, vb)) is not None:
                continue
            rs = set(region)
            common = [g for g in va.link_faces if vb in g.verts and g in rs]
            if not common:
                continue
            r = bmesh.utils.face_split(common[0], va, vb)
            if r and r[0] is not None:
                region.append(r[0])
                made += 1
        n_regions += 1
        n_cuts += made
    return n_regions, n_cuts
