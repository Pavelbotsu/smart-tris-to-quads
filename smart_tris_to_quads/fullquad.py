"""Full Quad: turn whatever is left after the tris->quads pass (triangles,
n-gons) into quads only, without moving any original vertex.

A face with an odd number of corners can never be cut into quads on its own:
each quad uses an even number of edge-ends. So:

  1. Pair up the odd faces. For each one, find the cheapest chain of faces to
     another odd face (or to an open border) and mark the edges the chain
     crosses. Putting one new point on each marked edge makes both ends even
     and leaves the faces in between even. Long edges are preferred, so the
     faces cut in half along the way stay close to square.
  2. Cut every face that isn't a good quad into quads: the best set of
     straight cuts between its own points, or, when that would give bad
     shapes (e.g. a triangle that got one extra point), one new point inside
     the face with cuts to every other corner.
  3. Slide only the new points along the surface to even out the quads.
     Points on a sharp edge or the open border only slide along that edge,
     points on curved areas stay put, so the shape doesn't change.
"""
import heapq
import itertools
import math
from functools import lru_cache

import bmesh
from mathutils import Vector



def _fkey(f):
    c = f.calc_center_median()
    return (round(c.x, 6), round(c.y, 6), round(c.z, 6), len(f.verts))


def _ekey(e):
    a, b = e.verts
    c = (a.co + b.co) * 0.5
    return (round(c.x, 6), round(c.y, 6), round(c.z, 6))


def _vkey(v):
    return (round(v.co.x, 6), round(v.co.y, 6), round(v.co.z, 6))

def _angle(u, w):
    lu, lw = u.length, w.length
    if lu < 1e-12 or lw < 1e-12:
        return math.pi
    c = u.dot(w) / (lu * lw)
    return math.acos(max(-1.0, min(1.0, c)))


# ---------------------------------------------------------------------------
# 1. parity
# ---------------------------------------------------------------------------

def _pair_odd_faces(bm, scope, max_visit=20000):
    lens = sorted(e.calc_length() for f in scope for e in f.edges)
    med = lens[len(lens) // 2] if lens else 1.0

    def ecost(e):
        # cheap to cut a long edge (halves stay square), dear to cut a short one
        return 0.25 + med / max(e.calc_length(), 1e-9 * med)

    def crossable(e):
        lf = e.link_faces
        return len(lf) == 2 and lf[0] in scope and lf[1] in scope

    def border(e):
        return len(e.link_faces) == 1

    odd = [f for f in scope if len(f.verts) % 2 == 1]
    odd.sort(key=_fkey)
    unmatched = set(odd)
    split = set()
    pairs = 0
    for f0 in odd:
        if f0 not in unmatched:
            continue
        dist = {f0: 0.0}
        prev = {}
        tie = itertools.count()
        pq = [(0.0, next(tie), f0)]
        best = None                       # (cost, end face or None, end edge)
        seen = 0
        while pq:
            d, _, f = heapq.heappop(pq)
            if d != dist.get(f):
                continue
            if best is not None and d >= best[0]:
                break
            seen += 1
            if seen > max_visit:
                break
            if f is not f0 and f in unmatched:
                best = (d, f, None)
                break
            for e in f.edges:
                if border(e):
                    c = d + ecost(e) + 2.0            # border: last resort
                    if best is None or c < best[0]:
                        best = (c, None, e)
                    continue
                if not crossable(e):
                    continue
                g = e.link_faces[0] if e.link_faces[1] == f else e.link_faces[1]
                nd = d + ecost(e)
                if nd < dist.get(g, float("inf")):
                    dist[g] = nd
                    prev[g] = (f, e)
                    heapq.heappush(pq, (nd, next(tie), g))
        if best is None:
            continue
        _, g, last = best
        unmatched.discard(f0)
        path = []
        if g is None:
            # walk back from the face that owns the border edge
            owner = last.link_faces[0]
            path.append(last)
            f = owner
        else:
            unmatched.discard(g)
            f = g
        while f is not f0:
            pf, e = prev[f]
            path.append(e)
            f = pf
        for e in path:
            split ^= {e}                  # cutting an edge twice = not at all
        pairs += 1
    return split, pairs, len(unmatched)


# ---------------------------------------------------------------------------
# 2. quadrangulate
# ---------------------------------------------------------------------------

def _quad_cost(p, n, limit=math.radians(80.0)):
    """0 = perfect square corners, inf = unusable (concave / folded)."""
    dev = 0.0
    worst = 0.0
    for i in range(4):
        a, b, c = p[i - 1], p[i], p[(i + 1) % 4]
        d1, d2 = b - a, c - b
        if d1.length < 1e-12 or d2.length < 1e-12:
            return float("inf")
        if d1.cross(d2).dot(n) <= 0:
            return float("inf")
        x = abs(_angle(a - b, c - b) - math.pi / 2)
        dev += x
        worst = max(worst, x)
    if worst > limit:
        return float("inf")
    return dev / (2 * math.pi) + 0.5 * (worst / (math.pi / 2)) ** 2


def _plan_chords(cos, n, limit=math.radians(80.0)):
    """Best way to cut polygon `cos` into quads using only its own points.
    Returns (cost, [quads as index tuples]) or (inf, None)."""
    k = len(cos)

    @lru_cache(maxsize=None)
    def dp(i, j):
        size = j - i + 1
        if size == 2:
            return 0.0, ()
        if size < 4 or size % 2:
            return float("inf"), None
        best = (float("inf"), None)
        for a in range(i + 1, j, 2):
            for b in range(a + 1, j, 2):
                q = _quad_cost([cos[i], cos[a], cos[b], cos[j]], n, limit)
                if q == float("inf"):
                    continue
                c1, l1 = dp(i, a)
                c2, l2 = dp(a, b)
                c3, l3 = dp(b, j)
                tot = q + c1 + c2 + c3
                if tot < best[0]:
                    best = (tot, ((i, a, b, j),) + l1 + l2 + l3)
        return best

    c, quads = dp(0, k - 1)
    dp.cache_clear()
    return c, (list(quads) if quads is not None else None)


def _plan_center(cos, n, limit=math.radians(80.0)):
    """One new point inside, cuts to every other corner. The point is tried
    at the middle and at each 'missing corner' position (completing one of
    the quads to a parallelogram), e.g. the inner corner when a rectangle
    got extra points on two neighbouring sides."""
    k = len(cos)
    mid = sum(cos, Vector()) / k
    best = (float("inf"), None, None)
    for off in (0, 1):
        spokes = [(s % k, (s + 1) % k, (s + 2) % k) for s in range(off, k + off, 2)]
        cands = [mid]
        for (a, b, c) in spokes:
            cands.append(cos[a] + cos[c] - cos[b])
        cands.append(sum(cands[1:], Vector()) / (len(cands) - 1))
        for pt in cands:
            pt = pt - n * (pt - mid).dot(n)          # keep it in the face
            tot = 0.0
            for (a, b, c) in spokes:
                tot += _quad_cost([cos[a], cos[b], cos[c], pt], n, limit)
                if tot == float("inf"):
                    break
            if tot < best[0]:
                best = (tot, [(a, b, c, -1) for (a, b, c) in spokes], pt)
    return best


def _plan_steiner(cos, n):
    """Cut the face along a short path through 1 or 2 new inner points,
    then cut both halves with straight chords. This is the classic
    '3 segments on one side, 1 on the other' transition, generalised.
    New points start halfway from a 'flat' point (one in the middle of a
    straight side) towards the middle of the face."""
    k = len(cos)
    c = sum(cos, Vector()) / k
    turn = []
    for i in range(k):
        turn.append(_angle(cos[i] - cos[i - 1], cos[(i + 1) % k] - cos[i]))
    flats = [i for i in range(k) if turn[i] < math.radians(25.0)] or list(range(k))
    best = (float("inf"), None)

    def pulled(i, t=0.5):
        p = cos[i] + (c - cos[i]) * t
        return p - n * (p - c).dot(n)

    def ring(i, j):
        out = []
        x = i
        while True:
            out.append(x)
            if x == j:
                return out
            x = (x + 1) % k

    # one new point: path i -> P -> j
    for s_ in flats:
        P = pulled(s_)
        for i in range(k):
            for j in range(k):
                if i == j:
                    continue
                ra, rb = ring(i, j), ring(j, i)
                if (len(ra) + 1) % 2 or (len(rb) + 1) % 2:
                    continue
                pa = [cos[x] for x in ra] + [P]
                pb = [cos[x] for x in rb] + [P]
                ca, qa = _plan_chords(pa, n)
                if qa is None or ca >= best[0]:
                    continue
                cb, qb = _plan_chords(pb, n)
                if qb is None or ca + cb >= best[0]:
                    continue
                best = (ca + cb, ([P], (ra, [0]), qa, (rb, [0]), qb))
    if best[1] is not None:
        return best
    # two new points: path i -> P -> Q -> j
    for s_ in flats:
        for t_ in flats:
            if s_ == t_:
                continue
            P, Q = pulled(s_), pulled(t_)
            for i in range(k):
                for j in range(k):
                    if i == j:
                        continue
                    ra, rb = ring(i, j), ring(j, i)
                    if len(ra) % 2 or len(rb) % 2:
                        continue
                    pa = [cos[x] for x in ra] + [Q, P]
                    pb = [cos[x] for x in rb] + [P, Q]
                    ca, qa = _plan_chords(pa, n)
                    if qa is None or ca >= best[0]:
                        continue
                    cb, qb = _plan_chords(pb, n)
                    if qb is None or ca + cb >= best[0]:
                        continue
                    best = (ca + cb, ([P, Q], (ra, [1, 0]), qa, (rb, [0, 1]), qb))
    return best


class _Budget:
    calls = 0
    cache = {}


def _plan_face(cos, n, depth=3, limit=math.radians(80.0), pen=0.35):
    key = (tuple((round(p.x, 6), round(p.y, 6), round(p.z, 6)) for p in cos), depth, round(limit, 3))
    hit = _Budget.cache.get(key)
    if hit is not None:
        return hit
    _Budget.calls += 1
    if _Budget.calls > 700:                  # this face is too awkward: give up on it
        return float("inf"), None, None
    res = _plan_face_(cos, n, depth, limit, pen)
    _Budget.cache[key] = res
    return res


def _plan_face_(cos, n, depth=3, limit=math.radians(80.0), pen=0.35):
    """Best quad layout for a polygon. Returns (cost, new_points, quads) with
    quad indices pointing into cos + new_points, or (inf, None, None).
    Tries, in order: straight cuts between its own points, one centre point,
    and - if neither works - peels off one awkward 'flat' point at a time by
    cutting from it through a new inner point to another corner."""
    k = len(cos)
    inf = float("inf")
    if k < 4 or k % 2:
        return inf, None, None
    best = (inf, None, None)
    dc, dq = _plan_chords(cos, n, limit)
    if dq is not None:
        best = (dc, [], dq)
    cc, cq, cpt = _plan_center(cos, n, limit)
    if cq is not None and cc + pen * (k // 2) < best[0]:
        best = (cc + pen * (k // 2), [cpt], [tuple(k if i < 0 else i for i in q) for q in cq])
    if best[1] is not None or depth <= 0:
        return best
    c = sum(cos, Vector()) / k
    turn = [_angle(cos[i] - cos[i - 1], cos[(i + 1) % k] - cos[i]) for i in range(k)]
    flats = [i for i in range(k) if turn[i] < math.radians(25.0)]
    for s_ in flats:
        for t in (0.5,):
            P = cos[s_] + (c - cos[s_]) * t
            P = P - n * (P - c).dot(n)
            for d in range(2, k - 1):
                if (d + 2) % 2:              # both halves must be even
                    continue
                j = (s_ + d) % k
                ra = [(s_ + x) % k for x in range(d + 1)]            # s .. j
                rb = [(j + x) % k for x in range(k - d + 1)]         # j .. s
                pa = [cos[x] for x in ra] + [P]
                pb = [cos[x] for x in rb] + [P]
                ca, pta, qa = _plan_face(pa, n, depth - 1, limit, pen)
                if qa is None or ca + pen >= best[0]:
                    continue
                cb, ptb, qb = _plan_face(pb, n, depth - 1, limit, pen)
                if qb is None or ca + cb + pen >= best[0]:
                    continue
                # re-index both halves into cos + [P] + pta + ptb
                base = k
                idxP = base
                ia = {i: ra[i] for i in range(len(ra))}
                ia[len(ra)] = idxP
                for x in range(len(pta)):
                    ia[len(ra) + 1 + x] = base + 1 + x
                ib = {i: rb[i] for i in range(len(rb))}
                ib[len(rb)] = idxP
                for x in range(len(ptb)):
                    ib[len(rb) + 1 + x] = base + 1 + len(pta) + x
                quads = [tuple(ia[i] for i in q) for q in qa] + [tuple(ib[i] for i in q) for q in qb]
                best = (ca + cb + pen, [P] + list(pta) + list(ptb), quads)
    return best


def _plan_ring(cos, n):
    """Last resort for awkward faces (e.g. three points on one side, one on
    the other): a ring of quads just inside the outline, then the inner
    polygon - which is convex by construction - gets the centre plan."""
    k = len(cos)
    c = sum(cos, Vector()) / k
    # local 2D frame along the face's long direction
    best_axis, best_len = None, -1.0
    for p in cos:
        d = p - c
        d = d - n * d.dot(n)
        if d.length > best_len:
            best_axis, best_len = d, d.length
    if best_len < 1e-12:
        return float("inf"), None
    u = best_axis.normalized()
    w = n.cross(u).normalized()
    xy = [((p - c).dot(u), (p - c).dot(w)) for p in cos]
    ax = max(abs(x) for x, _ in xy) or 1e-9
    ay = max(abs(y) for _, y in xy) or 1e-9
    best = (float("inf"), None)
    for t in (0.5, 0.4, 0.6, 0.3):
        inner = []
        for (x, y) in xy:
            th = math.atan2(y / ay, x / ax)
            inner.append(c + u * (t * ax * math.cos(th)) + w * (t * ay * math.sin(th)))
        tot = 0.0
        for i in range(k):
            j = (i + 1) % k
            tot += _quad_cost([cos[i], cos[j], inner[j], inner[i]], n, math.radians(89.0))
            if tot == float("inf"):
                break
        if tot == float("inf"):
            continue
        ic, iq, ipt = _plan_center(inner, n)
        if iq is None or ic == float("inf"):
            ic, iq = _plan_chords(inner, n)
            ipt = None
            if iq is None:
                continue
        if tot + ic < best[0]:
            best = (tot + ic, (inner, iq, ipt))
    return best


def _split_big(bm, f):
    """Cut a big face in two with its shortest chord that leaves two even
    faces of at least 4 points each and stays inside the face."""
    vs = list(f.verts)
    k = len(vs)
    n = f.normal
    c = f.calc_center_median()
    ax = (vs[0].co - c)
    ax = (ax - n * ax.dot(n)).normalized()
    ay = n.cross(ax)
    pts = [((v.co - c).dot(ax), (v.co - c).dot(ay)) for v in vs]

    def inside(x, y):
        res = False
        for i in range(k):
            x1, y1 = pts[i - 1]
            x2, y2 = pts[i]
            if (y1 > y) != (y2 > y):
                if x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                    res = not res
        return res

    def crosses(i, j):
        a, b = pts[i], pts[j]
        for e in range(k):
            p, q = e - 1, e
            p %= k
            if p in (i, j) or q in (i, j):
                continue
            c1, c2 = pts[p], pts[q]
            d1 = (b[0] - a[0]) * (c1[1] - a[1]) - (b[1] - a[1]) * (c1[0] - a[0])
            d2 = (b[0] - a[0]) * (c2[1] - a[1]) - (b[1] - a[1]) * (c2[0] - a[0])
            d3 = (c2[0] - c1[0]) * (a[1] - c1[1]) - (c2[1] - c1[1]) * (a[0] - c1[0])
            d4 = (c2[0] - c1[0]) * (b[1] - c1[1]) - (c2[1] - c1[1]) * (b[0] - c1[0])
            if d1 * d2 < 0 and d3 * d4 < 0:
                return True
        return False

    best = None
    for i in range(k):
        for j in range(i + 3, k, 2):
            if k - (j - i) < 3:
                continue
            if bm.edges.get((vs[i], vs[j])) is not None:
                continue
            mx = (pts[i][0] + pts[j][0]) / 2
            my = (pts[i][1] + pts[j][1]) / 2
            if not inside(mx, my) or crosses(i, j):
                continue
            L = (vs[i].co - vs[j].co).length
            # balance the two halves a bit
            bal = abs((j - i) - (k - (j - i)))
            score = L * (1.0 + 0.05 * bal)
            if best is None or score < best[0]:
                best = (score, vs[i], vs[j])
    if best is None:
        return None
    r = bmesh.utils.face_split(f, best[1], best[2])
    if not r or r[0] is None:
        return None
    f.normal_update()
    r[0].normal_update()
    return [f, r[0]]


def _quadrangulate(bm, faces, new_verts, add_penalty=0.35):
    made = 0
    failed = 0
    stack = list(faces)
    while stack:
        f = stack.pop()
        if not f.is_valid:
            continue
        k = len(f.verts)
        if k % 2:
            failed += 1
            continue
        if k > 12:
            parts = _split_big(bm, f)
            if parts:
                stack.extend(parts)
            else:
                failed += 1
            continue
        vs = list(f.verts)
        cos = [v.co.copy() for v in vs]
        n = f.normal.copy()
        if n.length < 1e-12:
            continue
        if k == 4 and _quad_cost(cos, n) < 0.25:
            continue                          # already a decent quad
        _Budget.calls = 0
        _Budget.cache = {}
        cost, pts, quads = _plan_face(cos, n, depth=3 if k <= 6 else 2)
        if quads is None:
            _Budget.calls = 0
            cost, pts, quads = _plan_face(cos, n, depth=2, limit=math.radians(89.0))
        if quads is None:
            # needle-thin CAD geometry: accept very thin quads rather than leave an n-gon
            _Budget.calls = 0
            dc, dq = _plan_chords(cos, n, math.radians(89.99))
            if dq is not None:
                cost, pts, quads = dc, [], dq
        if k == 4 and quads is not None and (not pts or cost >= _quad_cost(cos, n)):
            continue                          # nothing better than what's there
        if quads is None:
            rc, rplan = _plan_ring(cos, n)
            if rplan is not None and _apply_ring(bm, f, vs, rplan, new_verts):
                made += 1
            else:
                failed += 1
            continue
        extra = [bm.verts.new(p) for p in pts]
        allv = vs + extra
        created = []
        ok = True
        for q in quads:
            try:
                nf = bm.faces.new([allv[i] for i in q])
            except ValueError:
                ok = False
                break
            nf.material_index = f.material_index
            nf.smooth = f.smooth
            nf.select = f.select
            created.append(nf)
        if not ok:
            for nf in created:
                bm.faces.remove(nf)
            for v in extra:
                if not v.link_edges:
                    bm.verts.remove(v)
            failed += 1
            continue
        bm.faces.remove(f)
        for nf in created:
            nf.normal_update()
        new_verts.update(extra)
        made += len(created)
    return made, failed


def _apply_steiner(bm, f, vs, plan, new_verts):
    pts, (ra, ea), qa, (rb, eb), qb = plan
    extra = [bm.verts.new(p) for p in pts]
    la = [vs[x] for x in ra] + [extra[i] for i in ea]
    lb = [vs[x] for x in rb] + [extra[i] for i in eb]
    created = []
    ok = True
    for loop, quads in ((la, qa), (lb, qb)):
        for q in quads:
            try:
                nf = bm.faces.new([loop[i] for i in q])
            except ValueError:
                ok = False
                break
            nf.material_index = f.material_index
            nf.smooth = f.smooth
            nf.select = f.select
            created.append(nf)
        if not ok:
            break
    if not ok:
        for nf in created:
            bm.faces.remove(nf)
        for v in extra:
            if not v.link_edges:
                bm.verts.remove(v)
        return False
    bm.faces.remove(f)
    for nf in created:
        nf.normal_update()
    new_verts.update(extra)
    return True


def _apply_ring(bm, f, vs, plan, new_verts):
    inner_co, iq, ipt = plan
    k = len(vs)
    inner = [bm.verts.new(p) for p in inner_co]
    center = bm.verts.new(ipt) if ipt is not None else None
    created = []
    quads = [[vs[i], vs[(i + 1) % k], inner[(i + 1) % k], inner[i]] for i in range(k)]
    for q in iq:
        quads.append([center if i < 0 else inner[i] for i in q])
    ok = True
    for q in quads:
        try:
            nf = bm.faces.new(q)
        except ValueError:
            ok = False
            break
        nf.material_index = f.material_index
        nf.smooth = f.smooth
        nf.select = f.select
        created.append(nf)
    if not ok:
        for nf in created:
            bm.faces.remove(nf)
        for v in inner + ([center] if center is not None else []):
            if not v.link_edges:
                bm.verts.remove(v)
        return False
    bm.faces.remove(f)
    for nf in created:
        nf.normal_update()
    new_verts.update(inner)
    if center is not None:
        new_verts.add(center)
    return True


# ---------------------------------------------------------------------------
# 3. relax the new points
# ---------------------------------------------------------------------------

def _relax(bm, new_verts, constraint, iters=25, step=0.4, surface=None):
    for _ in range(iters):
        moved = 0
        for v in new_verts:
            if not v.is_valid or not v.link_edges:
                continue
            kind, data = constraint.get(v, ("plane", None))
            if kind == "fixed":
                continue
            # where would v sit if each quad around it were a parallelogram?
            ideal = []
            for f in v.link_faces:
                fv = list(f.verts)
                if len(fv) != 4:
                    continue
                i = fv.index(v)
                ideal.append(fv[i - 1].co + fv[(i + 1) % 4].co - fv[(i + 2) % 4].co)
            if ideal:
                target = sum(ideal, Vector()) / len(ideal)
                nb = sum((e.other_vert(v).co for e in v.link_edges), Vector()) / len(v.link_edges)
                target = target * 0.7 + nb * 0.3
            else:
                target = sum((e.other_vert(v).co for e in v.link_edges), Vector()) / len(v.link_edges)
            d = (target - v.co) * step
            if kind == "line":
                d = data * d.dot(data)
            else:
                nrm = Vector()
                for f in v.link_faces:
                    nrm += f.normal
                if nrm.length < 1e-12:
                    continue
                nrm.normalize()
                d = d - nrm * d.dot(nrm)
            if d.length < 1e-9:
                continue
            old = v.co.copy()
            before = [(f, f.normal.copy()) for f in v.link_faces]
            v.co = old + d
            if surface is not None:
                hit = surface.find_nearest(v.co)
                if hit[0] is not None:
                    v.co = hit[0]
            ok = True
            for f, n0 in before:
                f.normal_update()
                cs = [x.co for x in f.verts]
                if f.normal.dot(n0) < 0.7 or (len(cs) == 4 and _quad_cost(cs, f.normal) == float("inf")):
                    ok = False
                    break
            if not ok:
                v.co = old
                for f, _ in before:
                    f.normal_update()
            else:
                moved += 1
        if not moved:
            break


# ---------------------------------------------------------------------------

def full_quads(bm, scope_faces, flat_tol=math.radians(5.0), relax=True, surface=None):
    """Make every face in scope a quad. Returns a stats dict."""
    bm.normal_update()
    scope = {f for f in scope_faces if f.is_valid}

    split, pairs, unpaired = _pair_odd_faces(bm, scope)

    # where may each new point slide afterwards?
    constraint = {}
    new_verts = set()
    for e in sorted(split, key=_ekey):
        if not e.is_valid:
            continue
        a, b = e.verts
        line = (b.co - a.co)
        lf = e.link_faces
        bent = len(lf) != 2 or e.calc_face_angle(0.0) > flat_tol or not e.smooth or e.seam
        _, nv = bmesh.utils.edge_split(e, a, 0.5)
        new_verts.add(nv)
        if bent:
            constraint[nv] = ("line", line.normalized() if line.length > 1e-12 else Vector())
        else:
            constraint[nv] = ("plane", None)

    touched = {f for v in new_verts for f in v.link_faces}
    work = sorted((f for f in (scope | touched) if f.is_valid), key=_fkey, reverse=True)
    bm.normal_update()
    before_new = set(new_verts)
    made, failed = _quadrangulate(bm, work, new_verts)
    for v in new_verts - before_new:
        constraint[v] = ("plane", None)       # centre points: stay in the face

    # centre points of faces that weren't flat stay where they are
    for v in new_verts - before_new:
        if not v.is_valid:
            continue
        ns = [f.normal for f in v.link_faces]
        if any(_angle(ns[0], x) > flat_tol * 2 for x in ns[1:]):
            constraint[v] = ("fixed", None)

    if relax and new_verts:
        bm.normal_update()
        _relax(bm, sorted((v for v in new_verts if v.is_valid), key=_vkey), constraint, surface=surface)
    if surface is not None:
        # every new point sits exactly on the original surface
        for v in new_verts:
            if v.is_valid:
                hit = surface.find_nearest(v.co)
                if hit[0] is not None:
                    v.co = hit[0]
        bm.normal_update()

    left = sum(1 for f in bm.faces if f.is_valid and len(f.verts) != 4
               and (f in scope or any(v in new_verts for v in f.verts)))
    return dict(odd_pairs=pairs, unpaired=unpaired, points_added=len(new_verts),
                quads_made=made, not_quads=left)
