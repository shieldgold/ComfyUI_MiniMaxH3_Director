"""Fixed six-face cameras in the upstream Pixal3D Z-up convention."""
import math

VIEWS = ('front', 'left', 'back', 'right', 'top', 'bottom')
ANGLES = {'front': (0, 0), 'left': (90, 0), 'back': (180, 0),
          'right': (270, 0), 'top': (0, 90), 'bottom': (0, -90)}

def camera_matrices(names, fov):
    if not names or names[0] != 'front':
        raise ValueError('A front view is required to establish the model orientation')
    if not math.isfinite(fov) or not 1 <= fov <= 170:
        raise ValueError('FOV must be finite and between 1 and 170 degrees')
    distance = 1.1 * 0.5 / math.tan(math.radians(fov) / 2)
    matrices = []
    for name in names:
        az, el = map(math.radians, ANGLES[name])
        back = (math.sin(az)*math.cos(el), -math.cos(az)*math.cos(el), math.sin(el))
        right = (math.cos(az), math.sin(az), 0)
        up = (back[1]*right[2]-back[2]*right[1],
              back[2]*right[0]-back[0]*right[2],
              back[0]*right[1]-back[1]*right[0])
        matrices.append([[right[i], up[i], back[i], back[i]*distance] for i in range(3)] + [[0,0,0,1]])
    return matrices

def batch_size_for_views(sizes):
    if not sizes or any(s < 1 for s in sizes):
        raise ValueError('Each connected view must contain at least one image')
    batch = max(sizes)
    if any(s not in (1, batch) for s in sizes):
        raise ValueError('View batches must match; only a single image can be broadcast')
    return batch
