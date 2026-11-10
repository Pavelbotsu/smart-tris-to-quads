# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pavlo Botsula
"""Grid-aware tris -> quads (the engine of the add-on).

Why stock Alt+J goes wrong
--------------------------
A triangulated quad grid can be paired up in three ways: across the cell
diagonals (= the real grid) or across either family of grid lines (= a grid
rotated ~45 deg). Blender's join_triangles scores each pair on its own and
merges greedily, so wherever real cells are skewed or skinny (bevels, curved
areas next to bevels) the wrong pairing can win locally. Result: zig-zag edge
flow plus rows of leftover triangles wherever the wrong pattern runs out.

What this does instead
----------------------
  1. Build every allowed pair (convex, not too warped, corners within sane
     limits, never across a sharp / seam / material edge).
  2. Best-first growth: start from the most obvious quads and spread,
     preferring pairs whose side edges continue *straight* out of the
     neighbouring quads (edge flow).
  3. Augmenting chains: for each leftover triangle, look for a chain of
     re-pairings ending at another leftover triangle; flipping it gives one
     more quad. Only chains that don't make the surrounding quads worse in
     total are used. This is what repairs regions that grew the wrong way.
  4. Local swaps between neighbouring quads when both get better.
  5. Optional: merge what still can't be a quad (fans next to dense bevels)
     into neighbouring faces when the result still has exactly 4 real
     corners - a face that looks and behaves like a quad, with the extra
     vertices sitting on its straight sides.
"""
import heapq
import math

import bmesh

from .bevels import rebuild_strips
from .flat import rebuild_flat_regions

_acos = math.acos
_HALF_PI = math.pi / 2


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a):
    l = math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])
    if l < 1e-20:
        return (0.0, 0.0, 0.0)
    return (a[0] / l, a[1] / l, a[2] / l)


def _ang_u(u, w):
    """angle between two unit vectors"""
    c = u[0] * w[0] + u[1] * w[1] + u[2] * w[2]
    if c > 1.0:
        c = 1.0
    elif c < -1.0:
        c = -1.0
    return _acos(c)



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
    """angle between two mathutils Vectors (used by the n-gon pass)"""
    lu, lw = u.length, w.length
    if lu < 1e-12 or lw < 1e-12:
        return math.pi
    c = u.dot(w) / (lu * lw)
    return math.acos(max(-1.0, min(1.0, c)))


def _ek(a, b):
    return (a, b) if a < b else (b, a)


def grid_tris_to_quads(
    bm, faces,
    face_threshold=math.radians(40.0),
    max_corner_dev=math.radians(70.0),
    sharp_angle=None,
    respect_sharp=True, respect_seams=True, respect_materials=True,
    augment=True, swaps=True, max_search=4000, max_aug_cost=0.8,
    merge_leftovers=False, ngon_max_verts=8, ngon_face_threshold=math.radians(10.0),
    continue_loops=False, straight_tol=math.radians(5.0), bevel_crease=math.radians(6.0),
    rebuild_flat=False,
    w_shape=0.75, w_diag=0.10, w_plan=0.15,
    progress=None,
):
    """Convert the triangles among `faces` to quads in place.
    Returns a stats dict."""
    n_flat = 0
    if rebuild_flat:
        def _blk(e):
            return ((respect_sharp and not e.smooth) or (respect_seams and e.seam))
        n_flat, _ = rebuild_flat_regions(bm, [f for f in faces if f.is_valid], is_blocked=_blk)

    bm.verts.index_update()
    bm.faces.index_update()
    bm.normal_update()

    tris = [f for f in faces if f.is_valid and len(f.verts) == 3]
    nT = len(tris)
    tid_of = {f.index: i for i, f in enumerate(tris)}
    tv = [tuple(v.index for v in f.verts) for f in tris]
    co = [tuple(v.co) for v in bm.verts]
    tri_n = [tuple(f.normal) for f in tris]

    # longest edge of every triangle
    longest = []
    for (a, b, c) in tv:
        pa, pb, pc = co[a], co[b], co[c]
        lab = _dot(_sub(pa, pb), _sub(pa, pb))
        lbc = _dot(_sub(pb, pc), _sub(pb, pc))
        lca = _dot(_sub(pc, pa), _sub(pc, pa))
        if lab >= lbc and lab >= lca:
            longest.append(_ek(a, b))
        elif lbc >= lca:
            longest.append(_ek(b, c))
        else:
            longest.append(_ek(c, a))

    # edge -> scope triangles on it
    edge_tris = {}
    for t, (a, b, c) in enumerate(tv):
        for k in (_ek(a, b), _ek(b, c), _ek(c, a)):
            edge_tris.setdefault(k, []).append(t)

    # ------------------------------------------------------------------ 1
    cand_t, cand_q, cand_e, cand_s, cand_side = [], [], [], [], []
    adj = [[] for _ in range(nT)]          # tri -> [(other tri, cand)]
    lim_cos_face = math.cos(face_threshold)

    for e in bm.edges:
        ev = e.verts
        u, v = ev[0].index, ev[1].index
        key = _ek(u, v)
        lt = edge_tris.get(key)
        if lt is None or len(lt) != 2:
            continue
        if len(e.link_faces) != 2:
            continue
        if respect_sharp and not e.smooth:
            continue
        if respect_seams and e.seam:
            continue
        t1, t2 = lt
        n1, n2 = tri_n[t1], tri_n[t2]
        cfa = _dot(n1, n2)
        if cfa < lim_cos_face:
            continue
        if sharp_angle is not None and _acos(max(-1.0, min(1.0, cfa))) >= sharp_angle:
            continue
        if respect_materials and tris[t1].material_index != tris[t2].material_index:
            continue

        a1 = tv[t1][0] if tv[t1][0] not in key else (tv[t1][1] if tv[t1][1] not in key else tv[t1][2])
        b2 = tv[t2][0] if tv[t2][0] not in key else (tv[t2][1] if tv[t2][1] not in key else tv[t2][2])
        i = tv[t1].index(u)
        quad = (a1, u, b2, v) if tv[t1][(i + 1) % 3] == v else (a1, v, b2, u)

        n = (n1[0] + n2[0], n1[1] + n2[1], n1[2] + n2[2])
        pts = [co[k] for k in quad]
        ok = True
        dsum = 0.0
        sides = []
        for k in range(4):
            p0, p1, p2 = pts[k - 1], pts[k], pts[(k + 1) % 4]
            d01 = _sub(p1, p0)
            d12 = _sub(p2, p1)
            if _dot(_cross(d01, d12), n) <= 0:
                ok = False
                break
            ang = _ang_u(_unit(_sub(p0, p1)), _unit(d12))
            d = abs(ang - _HALF_PI)
            if d > max_corner_dev:
                ok = False
                break
            dsum += d
        if not ok:
            continue
        shape = (dsum / 4) / _HALF_PI
        diag = (2 - (longest[t1] == key) - (longest[t2] == key)) / 2
        fa = _acos(max(-1.0, min(1.0, cfa)))
        s = w_shape * shape + w_diag * diag + w_plan * fa / max(face_threshold, 1e-6)

        # side edges, the outward edge directions at both ends of each side,
        # and the triangle on the far side (for edge-flow scoring)
        for k in range(4):
            x, y = quad[k], quad[(k + 1) % 4]
            ox = _unit(_sub(co[quad[k - 1]], co[x]))
            oy = _unit(_sub(co[quad[(k + 2) % 4]], co[y]))
            sk = _ek(x, y)
            far = -1
            for t in edge_tris.get(sk, ()):
                if t != t1 and t != t2:
                    far = t
            sides.append((sk, x, ox, oy, far))

        c = len(cand_t)
        cand_t.append((t1, t2))
        cand_q.append(quad)
        cand_e.append(e)
        cand_s.append(s)
        cand_side.append(sides)
        adj[t1].append((t2, c))
        adj[t2].append((t1, c))

    if progress:
        progress(0.25)

    mate = [-1] * nT

    def partner(t):
        c = mate[t]
        if c < 0:
            return -1
        a, b = cand_t[c]
        return b if a == t else a

    # ------------------------------------------------------------------ 2
    # edge -> (vert x, outward dir at x, outward dir at the other vert) of
    # an existing quad on that edge. Seeded with quads already in the mesh.
    edge_quad = {}
    scope_ids = set(tid_of)
    for f in bm.faces:
        if len(f.verts) != 4 or f.index in scope_ids:
            continue
        q = [v.index for v in f.verts]
        for k in range(4):
            x, y = q[k], q[(k + 1) % 4]
            edge_quad[_ek(x, y)] = (
                x, _unit(_sub(co[q[k - 1]], co[x])), _unit(_sub(co[q[(k + 2) % 4]], co[y])))

    def grow_score(c):
        tot = 0.0
        nnb = 0
        for (sk, x, ox, oy, far) in cand_side[c]:
            P = edge_quad.get(sk)
            if P is None:
                continue
            px, pa, pb = P
            if px == x:
                vx, vy = pa, pb
            else:
                vx, vy = pb, pa
            # straight continuation <=> the two outward directions are opposite
            tot += _ang_u((-vx[0], -vx[1], -vx[2]), ox) + _ang_u((-vy[0], -vy[1], -vy[2]), oy)
            nnb += 1
        if not nnb:
            return cand_s[c] + 0.15
        cont = (tot / (2 * nnb)) / _HALF_PI
        return 0.4 * cand_s[c] + 0.6 * cont - 0.03 * (nnb - 1)

    best = [grow_score(c) for c in range(len(cand_t))]
    heap = [(best[c], c) for c in range(len(cand_t))]
    heapq.heapify(heap)
    while heap:
        s, c = heapq.heappop(heap)
        if s != best[c]:
            continue
        t1, t2 = cand_t[c]
        if mate[t1] >= 0 or mate[t2] >= 0:
            continue
        mate[t1] = mate[t2] = c
        for (sk, x, ox, oy, far) in cand_side[c]:
            edge_quad[sk] = (x, ox, oy)
        for (sk, x, ox, oy, far) in cand_side[c]:
            if far < 0 or mate[far] >= 0:
                continue
            for (o, c2) in adj[far]:
                if mate[o] >= 0:
                    continue
                s2 = grow_score(c2)
                if s2 != best[c2]:
                    best[c2] = s2
                    heapq.heappush(heap, (s2, c2))

    n_greedy = sum(1 for t in range(nT) if mate[t] >= 0) // 2
    if progress:
        progress(0.5)

    # ------------------------------------------------------------------ 3
    n_aug = 0
    if augment:
        for r in range(nT):
            if mate[r] >= 0 or not adj[r]:
                continue
            # alternating search r -(new pair)- y =(old pair)= z -(new)- ...
            # ordered by quality cost (new pair scores minus old ones)
            parent = {r: None}
            cost = {r: 0.0}
            seen = {r}
            pq = [(0.0, r)]
            found = None
            while pq and len(seen) < max_search:
                cx, x = heapq.heappop(pq)
                if cx != cost.get(x) or cx > max_aug_cost:
                    continue
                for (y, c) in adj[x]:
                    if y in seen:
                        continue
                    if mate[y] < 0:
                        tot = cx + cand_s[c]
                        if tot <= max_aug_cost and (found is None or tot < found[0]):
                            found = (tot, x, c, y)
                        continue
                    z = partner(y)
                    if z in seen:
                        continue
                    seen.add(y)
                    seen.add(z)
                    parent[z] = (x, c, y)
                    cost[z] = cx + cand_s[c] - cand_s[mate[y]]
                    heapq.heappush(pq, (cost[z], z))
                if found is not None and (not pq or pq[0][0] >= found[0]):
                    break
            if found is None:
                continue
            _, x, c, y = found
            mate[x] = mate[y] = c
            while parent[x] is not None:
                px, pc, py = parent[x]
                mate[py] = mate[px] = pc
                x = px
            n_aug += 1

    # ------------------------------------------------------------------ 4
    n_swap = 0
    if swaps:
        cand_index = {}
        for c, (a, b) in enumerate(cand_t):
            cand_index[(a, b)] = c
            cand_index[(b, a)] = c
        improved = True
        sweeps = 0
        while improved and sweeps < 4:
            improved = False
            sweeps += 1
            for x in range(nT):
                y = partner(x)
                if y < 0:
                    continue
                cxy = mate[x]
                for (a, cxa) in adj[x]:
                    if a == y:
                        continue
                    b = partner(a)
                    if b < 0 or b == x or b == y:
                        continue
                    cby = cand_index.get((b, y))
                    if cby is None:
                        continue
                    if cand_s[cxa] + cand_s[cby] + 0.02 < cand_s[cxy] + cand_s[mate[a]]:
                        mate[x] = mate[a] = cxa
                        mate[b] = mate[y] = cby
                        n_swap += 1
                        improved = True
                        break

    if progress:
        progress(0.75)

    # ------------------------------------------------------------------ apply
    chosen = sorted({mate[t] for t in range(nT) if mate[t] >= 0})
    leftover = [tris[t] for t in range(nT) if mate[t] < 0]
    region = []
    if merge_leftovers:
        # keep handles on the new faces for the n-gon pass
        for c in chosen:
            t1, t2 = cand_t[c]
            nf = bmesh.utils.face_join([tris[t1], tris[t2]])
            if nf is not None:
                region.append(nf)
    elif chosen:
        bmesh.ops.dissolve_edges(bm, edges=[cand_e[c] for c in chosen],
                                 use_verts=False, use_face_split=False)

    n_fan = n_lines = n_verts = 0
    if merge_leftovers:
        bm.normal_update()
        n_fan, scope = merge_fans(
            bm, region + leftover, max_verts=ngon_max_verts, face_threshold=ngon_face_threshold,
            respect_sharp=respect_sharp, respect_seams=respect_seams,
            respect_materials=respect_materials, sharp_angle=sharp_angle)
        if continue_loops:
            def _blocked(e):
                return ((respect_sharp and not e.smooth) or (respect_seams and e.seam) or
                        (respect_materials and len(e.link_faces) == 2 and
                         e.link_faces[0].material_index != e.link_faces[1].material_index))
            _nb, n_lines, n_verts = rebuild_strips(
                bm, scope, crease=bevel_crease, straight_tol=straight_tol, is_blocked=_blocked)
    if progress:
        progress(1.0)

    return dict(tris_in=nT, quads=len(chosen), greedy=n_greedy, augmented=n_aug,
                swaps=n_swap, tris_left=nT - 2 * len(chosen), ngon_merges=n_fan,
                bevel_lines=n_lines, verts_removed=n_verts, flat_regions=n_flat)


# ---------------------------------------------------------------------------
# Optional clean-up of what can't become a quad
# ---------------------------------------------------------------------------

def _real_corners(cos, n, corner_tol):
    """(number of vertices where the outline really turns, convex?)"""
    k = len(cos)
    corners = 0
    for i in range(k):
        p0, p1, p2 = cos[i - 1], cos[i], cos[(i + 1) % k]
        d1, d2 = p1 - p0, p2 - p1
        if d1.length < 1e-12 or d2.length < 1e-12:
            return 99, False
        turn = _angle(d1, d2)
        if d1.cross(d2).dot(n) < 0:
            if turn > corner_tol:
                return 99, False      # real reflex corner -> concave
            continue                  # a hair reflex, but basically straight
        if turn > corner_tol:
            corners += 1
    return corners, True


def merge_fans(bm, scope_faces, corner_tol=math.radians(20.0),
               face_threshold=math.radians(20.0),
               respect_sharp=True, respect_seams=True, respect_materials=True,
               sharp_angle=None, max_verts=8):
    """Merge leftover triangles (and quads that are really triangles with an
    extra vertex) into a neighbour when the merged face still has exactly 4
    real corners."""
    scope = set(f for f in scope_faces if f.is_valid)

    def corners_of(f):
        return _real_corners([v.co for v in f.verts], f.normal, corner_tol)[0]

    def blocked(e):
        if respect_sharp and not e.smooth:
            return True
        if respect_seams and e.seam:
            return True
        lf = e.link_faces
        if len(lf) != 2:
            return True
        if sharp_angle is not None and e.calc_face_angle(0.0) >= sharp_angle:
            return True
        if respect_materials and lf[0].material_index != lf[1].material_index:
            return True
        return False

    merged = 0
    work = sorted((f for f in scope if corners_of(f) < 4), key=_fkey, reverse=True)
    while work:
        f = work.pop()
        if not f.is_valid or f not in scope or corners_of(f) >= 4:
            continue
        best = None
        for e in f.edges:
            if blocked(e):
                continue
            g = e.link_faces[0] if e.link_faces[1] == f else e.link_faces[1]
            if g not in scope or _angle(f.normal, g.normal) > face_threshold:
                continue
            fv = list(f.verts)
            gv = list(g.verts)
            a, b = e.verts
            i = fv.index(a)
            fv = fv[i:] + fv[:i]
            if fv[1] == b:
                fv = fv[1:] + fv[:1]
            s0, s1 = fv[0], fv[-1]
            j = gv.index(s1)
            gv = gv[j:] + gv[:j]
            if gv[-1] != s0:
                continue
            outline = fv + gv[1:-1]
            if len(outline) > max_verts:
                continue
            n = f.normal * f.calc_area() + g.normal * g.calc_area()
            if n.length < 1e-12:
                continue
            n.normalize()
            corners, convex = _real_corners([v.co for v in outline], n, corner_tol)
            if not convex or corners > 4 or corners < 3:
                continue
            key = (0 if corners == 4 else 1, len(outline))
            if best is None or key < best[0]:
                best = (key, g)
        if best is None:
            continue
        g = best[1]
        scope.discard(f)
        scope.discard(g)
        nf = bmesh.utils.face_join([f, g])
        if nf is None:
            continue
        nf.normal_update()
        scope.add(nf)
        merged += 1
        if corners_of(nf) < 4:
            work.append(nf)
    return merged, scope
