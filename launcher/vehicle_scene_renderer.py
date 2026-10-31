"""Depth-buffered, local CPU rendering; no web runtime or graphics driver needed.

Each physical object contributes its nearest surface per pixel. These object
layers are sorted and alpha composited per pixel, not by triangle centroid.
Back faces of a transparent volume do not accumulate opaque-looking mesh seams.
"""
import math

import numpy as np
from PIL import Image


def rasterize(width, height, objects, background=(23, 27, 34)):
    """Return RGB image and nearest selectable object IDs (zero = background).

    Objects contain projected triangles, RGB colors per triangle, opacity and
    a stable picking ID. Context shells use ID zero and cannot steal a click.
    Tile compositing bounds temporary memory even with many crew/module layers.
    """
    layers = []
    for obj in objects:
        alpha = float(obj['alpha'])
        if alpha <= 0 or not obj['triangles']:
            continue
        depth = np.full((height, width), -np.inf, np.float32)
        color = np.zeros((height, width, 3), np.uint8)
        for points, rgb in obj['triangles']:
            p = np.asarray(points, dtype=np.float32)
            x0 = max(0, int(math.floor(p[:, 0].min())))
            x1 = min(width, int(math.ceil(p[:, 0].max())))
            y0 = max(0, int(math.floor(p[:, 1].min())))
            y1 = min(height, int(math.ceil(p[:, 1].max())))
            if x1 <= x0 or y1 <= y0:
                continue
            a, b, c = p
            denominator = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
            if abs(denominator) < 1.e-5:
                continue
            ys, xs = np.ogrid[y0:y1, x0:x1]
            u = ((b[1]-c[1])*(xs+.5-c[0])+(c[0]-b[0])*(ys+.5-c[1]))/denominator
            v = ((c[1]-a[1])*(xs+.5-c[0])+(a[0]-c[0])*(ys+.5-c[1]))/denominator
            z = u*a[2]+v*b[2]+(1-u-v)*c[2]
            region = depth[y0:y1, x0:x1]
            mask = (u >= -1.e-6) & (v >= -1.e-6) & (u+v <= 1.000001) & (z > region)
            region[mask] = z[mask]
            color[y0:y1, x0:x1][mask] = rgb
        layers.append((depth, color, min(1., alpha), obj['id']))
    output = np.empty((height, width, 3), np.uint8)
    picks = np.zeros((height, width), np.int32)
    for y in range(0, height, 32):
        end = min(y+32, height)
        shape = (end-y, width)
        rgb = np.empty(shape+(3,), np.float32)
        rgb[:] = background
        if layers:
            z = np.stack([layer[0][y:end] for layer in layers])
            order = np.argsort(z, axis=0, kind='stable')
            colors = np.stack([layer[1][y:end] for layer in layers])
            alphas = np.asarray([layer[2] for layer in layers], np.float32)
            ids = np.asarray([layer[3] for layer in layers], np.int32)
            for rank in range(len(layers)):
                idx = order[rank]
                valid = np.isfinite(np.take_along_axis(z, idx[None], axis=0)[0])
                alpha = (alphas[idx]*valid)[..., None]
                paint = np.take_along_axis(colors, idx[None, ..., None], axis=0)[0]
                rgb = paint*alpha + rgb*(1-alpha)
                selectable = valid & (ids[idx] != 0) & (alphas[idx] >= .08)
                picks[y:end][selectable] = ids[idx][selectable]
                # A fully opaque, unselectable shell hides rear geometry too.
                blocked = valid & (ids[idx] == 0) & (alphas[idx] >= .999)
                picks[y:end][blocked] = 0
        output[y:end] = np.clip(rgb, 0, 255).astype(np.uint8)
    return Image.fromarray(output), picks
