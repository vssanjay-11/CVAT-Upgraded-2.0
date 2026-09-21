import zipfile
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ZIP_PATH = BASE_DIR / "Transmission Transfer.zip"
DB_PATH = BASE_DIR / "local_server_data" / "db.json"

def densify_polygon(pts, max_gap=2.5):
    """
    Interpolates points along polygon edges so that adjacent dots
    are never separated by more than max_gap pixels, preserving
    the exact outline geometry.
    """
    new_pts = []
    n = len(pts)
    for i in range(n):
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        new_pts.append(p1)
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        dist = math.hypot(dx, dy)
        if dist > max_gap:
            steps = int(math.ceil(dist / max_gap))
            for k in range(1, steps):
                interp_x = round(p1[0] + (dx * k / steps), 2)
                interp_y = round(p1[1] + (dy * k / steps), 2)
                new_pts.append((interp_x, interp_y))
    return new_pts

def main():
    print(f"[*] Reading {ZIP_PATH}...")
    with zipfile.ZipFile(ZIP_PATH, "r") as z:
        xml_content = z.read("annotations.xml").decode("utf-8")
    
    root = ET.fromstring(xml_content)
    
    # Target: PLV BODY on frames 15 to 70
    imported_shapes = []
    frames_processed = set()
    
    for img in root.findall(".//image"):
        iid = int(img.get("id", -1))
        if 15 <= iid <= 70:
            for p in img.findall("polygon"):
                if p.get("label") == "PLV BODY":
                    pts_str = p.get("points", "")
                    raw_pairs = [
                        (float(pair.split(",")[0].strip()), float(pair.split(",")[1].strip()))
                        for pair in pts_str.split(";") if "," in pair
                    ]
                    
                    dense_pairs = densify_polygon(raw_pairs, max_gap=2.5)
                    flat_points = []
                    for pt in dense_pairs:
                        flat_points.extend([pt[0], pt[1]])
                    
                    shape_obj = {
                        "type": "polygon",
                        "occluded": p.get("occluded") == "1",
                        "z_order": int(p.get("z_order", 0)),
                        "points": flat_points,
                        "rotation": 0,
                        "attributes": [],
                        "elements": [],
                        "frame": iid,
                        "label_id": 10,  # PLV BODY in Task #5
                        "group": 0,
                        "source": "manual",
                    }
                    imported_shapes.append(shape_obj)
                    frames_processed.add(iid)

    print(f"\n[*] Total PLV BODY shapes extracted from frames 15..70: {len(imported_shapes)} across {len(frames_processed)} frames.")
    
    # Load db.json
    print(f"[*] Loading {DB_PATH}...")
    with open(DB_PATH, "r", encoding="utf-8") as f:
        db = json.load(f)
    
    job_id = "5"
    existing_shapes = db["annotations"].get(job_id, {}).get("shapes", [])
    print(f"[*] Current shapes in Job #{job_id}: {len(existing_shapes)}")
    
    # Remove any existing shapes on frames 15..70 if any to avoid duplicates
    filtered_shapes = [s for s in existing_shapes if not (15 <= s.get("frame", -1) <= 70 and s.get("label_id") == 10)]
    
    print(f"[*] Kept {len(filtered_shapes)} existing shapes.")
    filtered_shapes.extend(imported_shapes)
    
    db["annotations"][job_id]["shapes"] = filtered_shapes
    
    # Save db.json
    print(f"[*] Saving updated database to {DB_PATH}...")
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2)
    
    print(f"\n[SUCCESS] Successfully imported {len(imported_shapes)} densified PLV BODY shapes into Job #{job_id} for frames 15 to 70!")
    print(f"[*] Total shapes now in Job #{job_id}: {len(filtered_shapes)}")

if __name__ == "__main__":
    main()
