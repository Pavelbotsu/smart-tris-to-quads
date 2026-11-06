"""Synthetic test meshes that imitate triangulated STL exports of
hard-surface / CAD models: curved face patches meshed as structured grids,
narrow bevel/fillet strips, strips meeting at T-junctions, and density
mismatches between neighbouring patches (fans / zipped rows).

Every regular grid cell is recorded as ground truth (the 4 verts of the quad
the triangles came from), so we can measure how many real quads an
algorithm recovers and how many bogus quads it invents.
"""
import math
import random


class Builder:
    def __init__(self):
        self.key2idx = {}
        self.v2 = []
        self.tris = []
        self.gt_cells = []          # list of frozenset(4 vert idx)

    def vid(self, p):
        k = (round(p[0], 6), round(p[1], 6))
        i = self.key2idx.get(k)
        if i is None:
            i = len(self.v2)
            self.key2idx[k] = i
            self.v2.append((p[0], p[1]))
        return i

    def tri(self, a, b, c):
        if len({a, b, c}) < 3:
            return
        pa, pb, pc = self.v2[a], self.v2[b], self.v2[c]
        cross = (pb[0] - pa[0]) * (pc[1] - pa[1]) - (pb[1] - pa[1]) * (pc[0] - pa[0])
        if abs(cross) < 1e-12:
            return
        if cross < 0:
            b, c = c, b
        self.tris.append((a, b, c))


def lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def seg_points(p0, p1, n):
    return [lerp(p0, p1, i / n) for i in range(n + 1)]


def polyline(segs):
    """segs: list of (p0, p1, n). Returns concatenated point list."""
    pts = []
    for (p0, p1, n) in segs:
        s = seg_points(p0, p1, n)
        if pts:
            s = s[1:]
        pts.extend(s)
    return pts


def eval_poly(pts, t):
    """Point at arc-length fraction t along polyline."""
    lens = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    total = sum(lens)
    target = t * total
    acc = 0.0
    for i, l in enumerate(lens):
        if acc + l >= target - 1e-12:
            u = 0.0 if l == 0 else (target - acc) / l
            return lerp(pts[i], pts[i + 1], min(max(u, 0.0), 1.0))
        acc += l
    return pts[-1]


def mesh_patch(B, Lpts, Rpts, nu, nv, diag="consistent", rng=None):
    """Mesh a patch bounded by polylines L and R (both running bottom->top).
    Interior columns are blends of L and R with nv segments. Equal-count
    neighbouring columns become regular quad cells (split by a diagonal);
    unequal ones are zipped with triangles, like a CAD tessellator does
    where patches of different density meet."""
    cols = [Lpts]
    for k in range(1, nu):
        s = k / nu
        col = []
        for j in range(nv + 1):
            t = j / nv
            a = eval_poly(Lpts, t)
            b = eval_poly(Rpts, t)
            col.append(lerp(a, b, s))
        cols.append(col)
    cols.append(Rpts)

    for A, Bc in zip(cols[:-1], cols[1:]):
        ia = [B.vid(p) for p in A]
        ib = [B.vid(p) for p in Bc]
        if len(ia) == len(ib):
            for j in range(len(ia) - 1):
                a0, a1, b0, b1 = ia[j], ia[j + 1], ib[j], ib[j + 1]
                flip = False
                if diag == "random":
                    flip = rng.random() < 0.5
                elif diag == "alternate":
                    flip = j % 2 == 1
                if not flip:
                    B.tri(a0, b0, b1)
                    B.tri(a0, b1, a1)
                else:
                    B.tri(a0, b0, a1)
                    B.tri(b0, b1, a1)
                B.gt_cells.append(frozenset((a0, a1, b0, b1)))
        else:
            i = j = 0
            na, nb = len(ia) - 1, len(ib) - 1
            while i < na or j < nb:
                if j == nb or (i < na and
                               math.dist(B.v2[ia[i + 1]], B.v2[ib[j]]) <
                               math.dist(B.v2[ia[i]], B.v2[ib[j + 1]])):
                    B.tri(ia[i], ib[j], ia[i + 1])
                    i += 1
                else:
                    B.tri(ia[i], ib[j], ib[j + 1])
                    j += 1


def seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.dist(p, (ax + t * dx, ay + t * dy))


def panel_mesh(variant="cad", diag="consistent", seed=0, radius=6.0):
    """Curved panel with a top strip, bottom strip, a diagonal strip and a
    short horizontal strip that T-junctions into the diagonal one - roughly
    the layout in the user's screenshot.

    variant="cad":  strips are tessellated much denser than the faces next
                    to them (fans/zips everywhere along the seams).
    variant="poly": strip density matches the neighbouring faces, as if a
                    quad model with bevels had been triangulated on export.
    """
    rng = random.Random(seed)
    B = Builder()

    def xl(y):  # left edge of diagonal strip
        return 1.6 + (5.6 - y) * (3.0 / 4.6)

    A, Bp = (0, 6), (10, 6)
    C, D, E, F = (0, 5.6), (1.6, 5.6), (2.0, 5.6), (10, 5.6)
    G, H = (0, 2.8), (xl(2.8), 2.8)
    I, J = (0, 2.6), (xl(2.6), 2.6)
    K, Lq, M, N = (0, 1.0), (4.6, 1.0), (5.0, 1.0), (10, 1.0)
    O, P = (0, 0.6), (10, 0.6)

    n_CD, n_EF, n_MN, n_KL = 4, 10, 10, 7
    if variant == "cad":
        n_HD, n_JL, n_EM = 22, 12, 40
        n_GC, n_KI, n_NF = 8, 4, 12
        nv_right, nv_lt, nv_lb = 12, 8, 4
        n_OP = 30
    else:  # poly: densities line up
        n_GC, n_KI = 8, 4
        n_HD, n_JL = 8, 4
        n_EM = 8 + 2 + 4
        n_NF = n_EM
        nv_right, nv_lt, nv_lb = n_EM, 8, 4
        n_OP = n_KL + 3 + n_MN

    # top strip: L = C-D-E-F, R = A-B
    mesh_patch(B, polyline([(C, D, n_CD), (D, E, 3), (E, F, n_EF)]),
               polyline([(A, Bp, n_CD + 3 + n_EF if variant == "poly" else 24)]),
               3, n_CD + 3 + n_EF, diag, rng)
    # right face: L = M-E, R = N-F
    mesh_patch(B, polyline([(M, E, n_EM)]), polyline([(N, F, n_NF)]),
               n_EF, nv_right, diag, rng)
    # diagonal strip: L = Lq-J-H-D, R = M-E
    mesh_patch(B, polyline([(Lq, J, n_JL), (J, H, 2), (H, D, n_HD)]),
               polyline([(M, E, n_EM)]), 3, n_EM, diag, rng)
    # middle strip: L = I-J, R = G-H
    mesh_patch(B, polyline([(I, J, n_KL)]), polyline([(G, H, n_CD)]),
               2, max(n_KL, n_CD), diag, rng)
    # left-top face: L = G-C, R = H-D
    mesh_patch(B, polyline([(G, C, n_GC)]), polyline([(H, D, n_HD)]),
               n_CD, nv_lt, diag, rng)
    # left-bottom face: L = K-I, R = Lq-J
    mesh_patch(B, polyline([(K, I, n_KI)]), polyline([(Lq, J, n_JL)]),
               n_KL, nv_lb, diag, rng)
    # bottom strip: L = O-P, R = K-Lq-M-N
    mesh_patch(B, polyline([(O, P, n_OP)]),
               polyline([(K, Lq, n_KL), (Lq, M, 3), (M, N, n_MN)]),
               3, n_KL + 3 + n_MN, diag, rng)

    strips = [((0, 5.8), (10, 5.8), 0.2),
              ((0, 0.8), (10, 0.8), 0.2),
              ((0, 2.7), (xl(2.7), 2.7), 0.1),
              ((1.8, 5.6), (4.8, 1.0), 0.2 * math.sin(math.atan2(4.6, 3.0)))]

    v3 = []
    for (x, y) in B.v2:
        z = 0.0
        for a, b, hw in strips:
            d = seg_dist((x, y), a, b)
            if d < hw + 1e-9:
                z = min(z, -0.35 * hw * (1 - (d / hw) ** 2))
        ang = (y - 3.0) / radius
        r = radius + z
        v3.append((x, r * math.sin(ang), r * math.cos(ang) - radius))

    return dict(v3=v3, v2=B.v2, tris=B.tris, gt=B.gt_cells)


if __name__ == "__main__":
    for var in ("cad", "poly"):
        m = panel_mesh(var)
        print(var, len(m["v3"]), "verts", len(m["tris"]), "tris", len(m["gt"]), "gt cells")
