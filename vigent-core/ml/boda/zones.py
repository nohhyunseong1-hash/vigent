import json
from pathlib import Path
from typing import List, Tuple

def load_zones(path: str = None):
    base = Path(__file__).resolve().parent
    cfg = base / 'config'
    if path:
        p = Path(path)
    else:
        p = cfg / 'zones.json'
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding='utf-8'))
    # expect format { "zones": { name: [[x,y],...] } }
    return data.get('zones', {})


def point_in_poly(x: float, y: float, poly: List[Tuple[float, float]]) -> bool:
    # ray casting algorithm
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        intersect = ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-9) + xi)
        if intersect:
            inside = not inside
        j = i
    return inside


def bbox_centroid(box):
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def map_detections_to_zones(detections: list, zones_cfg: dict) -> Tuple[list, dict]:
    """Return detections with 'zone' key and a dict counts per zone."""
    zones_polys = {name: [(pt[0], pt[1]) for pt in poly] for name, poly in zones_cfg.items()}
    counts = {name: 0 for name in zones_polys.keys()}
    for det in detections:
        cx, cy = bbox_centroid(det['box'])
        det_zone = None
        for name, poly in zones_polys.items():
            if point_in_poly(cx, cy, poly):
                det_zone = name
                counts[name] += 1
                break
        det['zone'] = det_zone or 'unknown'
    return detections, counts
