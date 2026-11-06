import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection


def plot_faces(ax, v2, faces, title, gt=None):
    """faces: list of vertex-index tuples. Tris filled red, quads matching
    ground truth light, other quads (invented) orange, ngons purple."""
    gtset = set(gt) if gt else None
    polys, colors = [], []
    for f in faces:
        polys.append([v2[i] for i in f])
        if len(f) == 3:
            colors.append("#e8505b")
        elif len(f) == 4:
            if gtset is None or frozenset(f) in gtset:
                colors.append("#dfe6ee")
            else:
                colors.append("#f5a623")
        else:
            colors.append("#9b59b6")
    pc = PolyCollection(polys, facecolors=colors, edgecolors="#1f2d3d", linewidths=0.35)
    ax.add_collection(pc)
    xs = [p[0] for p in v2]
    ys = [p[1] for p in v2]
    ax.set_xlim(min(xs) - 0.1, max(xs) + 0.1)
    ax.set_ylim(min(ys) - 0.1, max(ys) + 0.1)
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=10)
    ax.axis("off")


def save_grid(panels, path, cols=1, w=11, h=5.2):
    rows = (len(panels) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(w * cols, h * rows))
    if rows * cols == 1:
        axes = [axes]
    else:
        axes = list(axes.flat) if hasattr(axes, "flat") else list(axes)
    for ax, p in zip(axes, panels):
        plot_faces(ax, *p)
    for ax in axes[len(panels):]:
        ax.axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
