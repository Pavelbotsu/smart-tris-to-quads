import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from mathutils import Vector

def draw3d(ax, bm, title, center=None, radius=None, new=None, elev=30, azim=45):
    polys, cols = [], []
    for f in bm.faces:
        c = f.calc_center_median()
        if center is not None and (c - Vector(center)).length > radius:
            continue
        polys.append([tuple(v.co) for v in f.verts])
        k = len(f.verts)
        cols.append('#e8505b' if k == 3 else ('#dfe6ee' if k == 4 else '#9b59b6'))
    pc = Poly3DCollection(polys, facecolors=cols, edgecolors='#1f2d3d', linewidths=0.4)
    ax.add_collection3d(pc)
    if new:
        pts = [tuple(v.co) for v in new if v.is_valid and (center is None or (v.co - Vector(center)).length <= radius)]
        if pts:
            xs, ys, zs = zip(*pts); ax.scatter(xs, ys, zs, s=5, color='#0b7a3e', depthshade=False)
    if center is not None:
        for setter, c in zip((ax.set_xlim, ax.set_ylim, ax.set_zlim), center):
            setter(c - radius * 0.8, c + radius * 0.8)
    else:
        allp = [v.co for v in bm.verts]
        lo = [min(p[i] for p in allp) for i in range(3)]; hi = [max(p[i] for p in allp) for i in range(3)]
        m = max(h - l for l, h in zip(lo, hi)) / 2
        for setter, l, h in zip((ax.set_xlim, ax.set_ylim, ax.set_zlim), lo, hi):
            c = (l + h) / 2; setter(c - m, c + m)
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off(); ax.set_title(title, fontsize=11)
