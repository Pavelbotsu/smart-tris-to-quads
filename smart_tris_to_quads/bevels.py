# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pavlo Botsula
"""Rebuild bevel strips so the rows of the neighbouring faces carry straight on
across them (what the user draws by hand).

  1. Split the mesh into patches along crease edges.
  2. Long thin patches are bevel bands; neighbouring bands that share a long
     side are one bevel (a multi-segment bevel).
  3. For each bevel: its two long sides, and the points where rows of the
     neighbouring faces arrive on each side.
  4. Pair arrivals on the two sides that face each other; arrivals without a
     partner cross straight over to the nearest point on the other side.
  5. Each pair becomes one line across the bevel (following existing edges as
     straight as possible). Every other cross-edge inside the bevel is removed.
  6. Vertices left alone in the middle of straight edges are removed.
"""
import bisect
import math

import bmesh



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


def _boundary_loops(faces):
    """Ordered vertex loops around a face set (list of lists of BMVerts) and
    the set of its boundary edges."""
    fs = set(faces)
    bedges = set()
    for f in fs:
        for e in f.edges:
            n = sum(1 for g in e.link_faces if g in fs)
            if n == 1:
                bedges.add(e)
    # walk: each boundary vertex has (normally) two boundary edges
    v_edges = {}
    for e in bedges:
        for v in e.verts:
            v_edges.setdefault(v, []).append(e)
    if any(len(es) != 2 for es in v_edges.values()):
        return None, bedges
    loops = []
    seen = set()
    for e0 in sorted(bedges, key=_ekey):
        if e0 in seen:
            continue
        loop = []
        v = e0.verts[0]
        e = e0
        while e not in seen:
            seen.add(e)
            loop.append(v)
            v = e.other_vert(v)
            e = v_edges[v][0] if v_edges[v][1] == e else v_edges[v][1]
        loops.append(loop)
    return loops, bedges


def _polyline_len(vs):
    return sum((vs[i + 1].co - vs[i].co).length for i in range(len(vs) - 1))


def _project_param(p, side):
    """Arc-length parameter of the closest point to p on polyline `side`."""
    best, best_t = None, 0.0
    acc = 0.0
    for i in range(len(side) - 1):
        a, b = side[i].co, side[i + 1].co
        d = b - a
        L = d.length
        if L < 1e-12:
            continue
        t = max(0.0, min(1.0, (p - a).dot(d) / (L * L)))
        q = a + d * t
        dist = (p - q).length
        if best is None or dist < best:
            best, best_t = dist, acc + t * L
        acc += L
    return best_t


def _params(side):
    out = [0.0]
    for i in range(len(side) - 1):
        out.append(out[-1] + (side[i + 1].co - side[i].co).length)
    return out


def _match(a_pos, b_pos, skip):
    """Order-preserving matching of two sorted position lists (DP alignment).
    Returns list of (i, j) pairs."""
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
        pi, pj, matched = P[i][j]
        if matched:
            pairs.append((pi, pj))
        i, j = pi, pj
    pairs.reverse()
    return pairs




ALLOW_RINGS = False


def _band_sides(faces):
    """Split the outline of a long thin band into its two long sides A and B
    (both running the same way). Returns (A, B, ring) or None."""
    loops, bedges = _boundary_loops(faces)
    if not loops:
        return None
    if len(loops) == 2 and not ALLOW_RINGS:  # closed band (around a rim): left alone
        return None
    if len(loops) == 2:                      # closed band (around a rim)
        A, B = loops
        if len(A) < 3 or len(B) < 3:
            return None
        # start B at the vertex nearest A[0], run it the same way round
        j = min(range(len(B)), key=lambda i: (B[i].co - A[0].co).length)
        B = B[j:] + B[:j]
        if (B[1].co - B[0].co).dot(A[1].co - A[0].co) < 0:
            B = [B[0]] + list(reversed(B[1:]))
        return A + [A[0]], B + [B[0]], True, bedges
    if len(loops) != 1:
        return None
    loop = loops[0]
    k = len(loop)
    if k < 4:
        return None
    # the two ends of a long thin band = the two boundary points furthest
    # apart (double sweep). Robust to slivers and spikes along the sides.
    i0 = max(range(k), key=lambda i: (loop[i].co - loop[0].co).length)
    i1 = max(range(k), key=lambda i: (loop[i].co - loop[i0].co).length)
    if i0 == i1:
        return None
    if i1 < i0:
        i0, i1 = i1, i0
    A = loop[i0:i1 + 1]
    B = list(reversed(loop[i1:] + loop[:i0 + 1]))
    if len(A) < 2 or len(B) < 2:
        return None
    # The far points are corners of the band's ends, so each side picked up
    # an end edge. Move each split onto the real corners: the sharpest turns
    # within about one band width of each far point.
    ds = sorted([_dist_to_poly(v.co, B) for v in A[1:-1]] or [0.0])
    w = ds[len(ds) // 2] if ds else 0.0
    turn = []
    for i in range(k):
        p0, p1, p2 = loop[i - 1].co, loop[i].co, loop[(i + 1) % k].co
        turn.append(_angle(p1 - p0, p2 - p1))

    def first_corner(i, step):
        acc, j = 0.0, i
        for _ in range(k):
            nj = (j + step) % k
            acc += (loop[nj].co - loop[j].co).length
            if acc > 2.0 * w:
                return None, None
            j = nj
            if turn[j] > math.radians(45.0):
                return j, acc
        return None, None

    def end_split(i, step_a):
        jp, dp = first_corner(i, step_a)
        jm, dm = first_corner(i, -step_a)
        if jp is not None and (jm is None or dp <= dm):
            return jp, i
        if jm is not None:
            return i, jm
        return i, i

    a0, b0 = end_split(i0, +1)
    a1, b1 = end_split(i1, -1)

    def walk(s_, t_, step):
        out, j = [loop[s_]], s_
        while j != t_:
            j = (j + step) % k
            out.append(loop[j])
            if len(out) > k:
                return None
        return out

    A2 = walk(a0, a1, +1)
    B2 = walk(b0, b1, -1)
    if A2 and B2 and len(A2) >= 2 and len(B2) >= 2 and not (set(A2) & set(B2)):
        A, B = A2, B2
    la, lb = _polyline_len(A), _polyline_len(B)
    if min(la, lb) < 0.5 * max(la, lb):
        return None
    return A, B, False, bedges


def _dist_to_poly(p, side):
    best = None
    for i in range(len(side) - 1):
        a, b = side[i].co, side[i + 1].co
        d = b - a
        L2 = d.length_squared
        t = 0.0 if L2 < 1e-24 else max(0.0, min(1.0, (p - a).dot(d) / L2))
        x = (p - (a + d * t)).length
        if best is None or x < best:
            best = x
    return best if best is not None else 0.0


def _parallel_sides(A, B):
    """A real bevel band: the two sides stay about the same distance apart
    all the way along (rules out T- and L-shaped pieces)."""
    da = [_dist_to_poly(v.co, B) for v in A[1:-1]] or [0.0]
    db = [_dist_to_poly(v.co, A) for v in B[1:-1]] or [0.0]
    ds = sorted(da + db)
    w = ds[len(ds) // 2]
    if w <= 0:
        return False
    return max(ds) <= 3.0 * w


def rebuild_strips(bm, scope_faces, crease=math.radians(10.0), thin_ratio=0.035,
                   straight_tol=math.radians(5.0), is_blocked=None):
    """Make the rows of the faces next to a bevel carry straight on across it.
    Returns (bevel bands rebuilt, lines drawn, verts removed)."""
    scope = {f for f in scope_faces if f.is_valid}
    bm.normal_update()

    def is_crease(e):
        lf = e.link_faces
        if len(lf) != 2:
            return True
        if is_blocked is not None and is_blocked(e):
            return True
        return e.calc_face_angle(0.0) >= crease

    # ---- patches between creases; the long thin ones are bevel bands ----
    patch_of = {}
    patches = []
    for f0 in sorted(scope, key=_fkey):
        if f0 in patch_of:
            continue
        pid = len(patches)
        comp = [f0]
        patch_of[f0] = pid
        stack = [f0]
        while stack:
            f = stack.pop()
            for e in f.edges:
                if is_crease(e):
                    continue
                for g in e.link_faces:
                    if g is not f and g in scope and g not in patch_of:
                        patch_of[g] = pid
                        comp.append(g)
                        stack.append(g)
        patches.append(comp)

    bands = {}
    thin_any = set()
    for pid, comp in enumerate(patches):
        cs = set(comp)
        area = sum(f.calc_area() for f in comp)
        perim = sum(e.calc_length() for f in comp for e in f.edges
                    if sum(1 for g in e.link_faces if g in cs) == 1)
        if perim <= 0 or area / (perim * perim) >= thin_ratio:
            continue
        thin_any.add(pid)
        sides = _band_sides(comp)
        if sides is None:
            continue
        A, B, ring, bedges = sides
        if not _parallel_sides(A, B):
            continue
        bands[pid] = dict(faces=comp, A=A, B=B, ring=ring, bedges=bedges, done=False)

    if not bands:
        return 0, 0, 0

    def side_state(band, side):
        """(waiting?, arrival indices, anchored-on-a-real-face?)"""
        fs = set(band["faces"])
        ends = set() if band["ring"] else {side[0], side[-1]}
        n_wait = 0
        n_side = 0
        face_arr = False
        arr = []
        for idx, v in enumerate(side):
            if v in ends or (band["ring"] and idx == len(side) - 1):
                continue
            n_side += 1
            for f in v.link_faces:
                if f in fs:
                    continue
                pid = patch_of.get(f)
                if pid in bands and bands[pid] is not band and not bands[pid]["done"]:
                    n_wait += 1
                    break
            for e in v.link_edges:
                if e in band["bedges"] or any(g in fs for g in e.link_faces):
                    continue
                pids = {patch_of.get(g) for g in e.link_faces}
                # rows of a dense bevel we couldn't rebuild don't count
                if e.link_faces and all(p in thin_any and not (p in bands and bands[p]["done"])
                                        for p in pids):
                    continue
                if any(p not in thin_any for p in pids):
                    face_arr = True
                arr.append(idx)
                break
        # only a band along most of this side has to be done first
        waiting = n_wait > 0.3 * max(1, n_side)
        return waiting, arr, face_arr

    n_bands = n_lines = 0
    touched = set()
    for _round in range(4 * len(bands) + 4):
        todo = [b for b in bands.values() if not b["done"]]
        if not todo:
            break
        st = [(b, side_state(b, b["A"]), side_state(b, b["B"])) for b in todo]
        # 1) both sides settled  2) outermost bands, anchored on a real face
        # 3) anything with one settled side that has rows arriving
        batch = [x for x in st if not x[1][0] and not x[2][0] and (x[1][1] or x[2][1])]
        if not batch:
            batch = [x for x in st if (not x[1][0] and x[1][2]) or (not x[2][0] and x[2][2])]
        if not batch:
            batch = [x for x in st if (not x[1][0] and x[1][1]) or (not x[2][0] and x[2][1])][:1]
        if not batch:
            break
        for (b, sa, sb) in batch:
            if b["done"]:
                continue
            arr_a = sa[1] if not sa[0] else []
            arr_b = sb[1] if not sb[0] else []
            k, t = _rebuild_band(bm, b, arr_a, arr_b)
            b["done"] = True
            if k:
                n_bands += 1
                n_lines += k
                touched |= t

    # ---- vertices left alone on straight edges ----------------------------
    n_verts = 0
    for v in sorted((v for v in touched if v.is_valid), key=_vkey):
        if not v.is_valid or len(v.link_edges) != 2:
            continue
        e1, e2 = v.link_edges
        if e1.smooth != e2.smooth or e1.seam != e2.seam:
            continue
        lf = v.link_faces
        if any(len(f.verts) <= 3 for f in lf):
            continue
        a, b = e1.other_vert(v), e2.other_vert(v)
        if _angle(v.co - a.co, b.co - v.co) > straight_tol:
            continue
        bmesh.ops.dissolve_verts(bm, verts=[v])
        n_verts += 1
    return n_bands, n_lines, n_verts


def _rebuild_band(bm, band, arr_a, arr_b):
    A, B, ring = band["A"], band["B"], band["ring"]
    faces = [f for f in band["faces"] if f.is_valid]
    if not faces or (not arr_a and not arr_b):
        return 0, set()
    pa, pb = _params(A), _params(B)
    a_on_b = [_project_param(A[i].co, B) for i in arr_a]
    b_pos = [pb[j] for j in arr_b]
    gaps = []
    for lst in (sorted(a_on_b), sorted(b_pos)):
        gaps += [lst[i + 1] - lst[i] for i in range(len(lst) - 1)]
    gaps.sort()
    typ = gaps[len(gaps) // 2] if gaps else pb[-1]
    pairs = _match(a_on_b, b_pos, skip=0.5 * typ)

    lo = 0 if ring else 1

    def nearest(params, t, n):
        best, bi = None, None
        for i in range(lo, n - 1):
            d = abs(params[i] - t)
            if best is None or d < best:
                best, bi = d, i
        return bi

    lines = [(arr_a[i], arr_b[j]) for i, j in pairs]
    ma = {i for i, _ in pairs}
    mb = {j for _, j in pairs}
    for i in range(len(arr_a)):
        if i not in ma:
            jb = nearest(pb, a_on_b[i], len(B))
            if jb is not None:
                lines.append((arr_a[i], jb))
    for j in range(len(arr_b)):
        if j not in mb:
            ia = nearest(pa, _project_param(B[arr_b[j]].co, A), len(A))
            if ia is not None:
                lines.append((ia, arr_b[j]))
    lines.sort(key=lambda l: (l[0], l[1]))
    clean = []
    for (ia, ib) in lines:
        if clean and (ia <= clean[-1][0] or ib <= clean[-1][1]):
            continue
        clean.append((ia, ib))
    if not clean:
        return 0, set()

    # every line must go across the band, not along it
    ds = sorted([_dist_to_poly(v.co, B) for v in A[1:-1]] or [0.0])
    w = ds[len(ds) // 2]
    seglens = sorted((A[i + 1].co - A[i].co).length for i in range(len(A) - 1))
    s_len = seglens[len(seglens) // 2] if seglens else 0.0
    for (ia, ib) in clean:
        if (A[ia].co - B[ib].co).length > 3.0 * w + 2.0 * s_len:
            return 0, set()

    fs = set(faces)
    verts = {v for f in faces for v in f.verts}
    side_a, side_b = set(A), set(B)
    if not ring:
        # never touch the end edges of the band
        pass

    # which rail a vertex sits on: 0 = side A ... rows = side B
    hop = {v: 0 for v in A}
    queue = list(A)
    qi = 0
    while qi < len(queue):
        v = queue[qi]
        qi += 1
        for e in v.link_edges:
            if not any(g in fs for g in e.link_faces):
                continue
            x = e.other_vert(v)
            if x in verts and x not in hop:
                hop[x] = hop[v] + 1
                queue.append(x)
    inner_b = sorted([hop[v] for v in B[1:-1] if v in hop] or [hop.get(v, 1) for v in B])
    rows = max(1, inner_b[len(inner_b) // 2])

    def level_of(v):
        if v in side_a:
            return 0
        if v in side_b:
            return rows
        da = _dist_to_poly(v.co, A)
        db = _dist_to_poly(v.co, B)
        u = da / (da + db) if da + db > 1e-12 else 0.5
        return min(rows - 1, max(1, int(round(u * rows)))) if rows > 1 else 0.5

    # bent across? then flattening would change the shape: leave it
    for f in faces:
        for e in f.edges:
            if len(e.link_faces) == 2 and all(g in fs for g in e.link_faces):
                a, b = e.verts
                if level_of(a) != level_of(b) and e.calc_face_angle(0.0) > math.radians(12.0):
                    return 0, set()

    # 1. cut the new lines first (nothing is deleted yet, so a failed cut
    #    can't leave a hole)
    outside = {g for v in verts for g in v.link_faces if g not in fs}
    line_edges = set()
    made = 0
    status = []                          # (position along A, succeeded?)
    for (ia, ib) in clean:
        va, vb = A[ia], B[ib]
        ok = False
        e = bm.edges.get((va, vb))
        if e is not None:
            line_edges.add(e)
            ok = True
        else:
            try:
                res = bmesh.ops.connect_vert_pair(bm, verts=[va, vb], faces_exclude=list(outside))
                new_e = res.get("edges", [])
            except (RuntimeError, ValueError):
                new_e = []
            if new_e:
                line_edges.update(new_e)
                ok = True
        made += ok
        status.append((pa[ia], ok))
    if not made:
        return 0, set()
    status.sort()
    pos_list = [p for p, _ in status]

    def safe_to_clear(t):
        # only clear between two lines that both worked
        i = bisect.bisect_left(pos_list, t)
        left_ok = status[i - 1][1] if i > 0 else True
        right_ok = status[i][1] if i < len(status) else True
        return left_ok and right_ok

    # 2. the band now = faces using only band verts (old + cut points)
    band_faces = set()
    stack = [f for f in faces if f.is_valid]
    for f in list(stack):
        for v in f.verts:
            for g in v.link_faces:
                if g not in outside:
                    band_faces.add(g)
    verts = {v for f in band_faces for v in f.verts}

    # 3. drop every cross edge that isn't one of the lines; keep the rails
    dissolve = []
    for f in band_faces:
        for e in f.edges:
            if e in line_edges or len(e.link_faces) != 2:
                continue
            if not all(g in band_faces for g in e.link_faces):
                continue
            a, b = e.verts
            la, lb = level_of(a), level_of(b)
            if la == lb:
                continue                     # a rail: part of the bevel's shape
            if not safe_to_clear(_project_param((a.co + b.co) * 0.5, A)):
                continue
            dissolve.append(e)
    dissolve = sorted(set(dissolve), key=_ekey)
    if ring:
        # make sure every remaining piece is bounded by a line
        pass
    if dissolve:
        bmesh.ops.dissolve_edges(bm, edges=dissolve, use_verts=False, use_face_split=False)
    loose = [v for v in verts if v.is_valid and not v.link_edges]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context='VERTS')
    return made, {v for v in verts if v.is_valid}
