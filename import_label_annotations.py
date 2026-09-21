"""
CVAT Annotation Label Transfer & Selective Importer
===================================================
Allows transferring annotations label-by-label from an original CVAT export
(or clipboard / raw file) into the local CVAT database for Task #5 / Job #5.

Usage Examples:
---------------
1. List labels present in an exported CVAT XML or ZIP file:
   python import_label_annotations.py annotations.xml --list-labels

2. Import only "PLV BODY" annotations from an original CVAT export:
   python import_label_annotations.py annotations.xml --label "PLV BODY"

3. Import and map a differently named label:
   python import_label_annotations.py annotations.xml --label "body_part" --target-label "PLV BODY"

4. Import from a zip file exported from CVAT:
   python import_label_annotations.py cvat_export.zip --label "TRANSMISSION HOUSING"

5. Import directly from a JSON or text file containing points:
   python import_label_annotations.py shapes.json --label "PLV BODY"
"""

import sys
import os
import json
import zipfile
import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "local_server_data"
DB_PATH = DATA_DIR / "db.json"

def load_db():
    if not DB_PATH.exists():
        print(f"[!] Database file not found at {DB_PATH}")
        sys.exit(1)
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(db):
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2)

def extract_xml_from_input(source_path):
    source = Path(source_path)
    if not source.exists():
        print(f"[!] Source file not found: {source_path}")
        sys.exit(1)

    if source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source, "r") as z:
            for name in z.namelist():
                if name.endswith(".xml") or name == "annotations.xml":
                    return z.read(name).decode("utf-8"), "xml"
                if name.endswith(".json") and "instances" in name.lower():
                    return z.read(name).decode("utf-8"), "coco_json"
        print("[!] No recognized annotation file (XML or COCO JSON) found in zip.")
        sys.exit(1)

    with open(source, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    trimmed = content.strip()
    if trimmed.startswith("<") or "<annotations>" in trimmed:
        return content, "xml"
    if trimmed.startswith("{") or trimmed.startswith("["):
        return content, "json"

    return content, "raw"

def parse_annotations_from_xml(xml_content):
    root = ET.fromstring(xml_content)
    shapes_by_label = {}

    for image in root.findall(".//image"):
        frame_idx = int(image.get("id", 0))
        # Polygons
        for poly in image.findall("polygon"):
            lbl = poly.get("label", "").strip()
            pts_str = poly.get("points", "")
            pts = []
            for pair in pts_str.split(";"):
                if "," in pair:
                    coords = pair.split(",")
                    pts.extend([float(coords[0].strip()), float(coords[1].strip())])
            if pts and lbl:
                shapes_by_label.setdefault(lbl, []).append({
                    "type": "polygon",
                    "frame": frame_idx,
                    "points": pts,
                    "occluded": poly.get("occluded") == "1",
                    "z_order": int(poly.get("z_order", 0)),
                    "rotation": 0,
                    "attributes": [],
                    "elements": [],
                    "group": 0,
                    "source": "manual",
                })
        # Boxes
        for box in image.findall("box"):
            lbl = box.get("label", "").strip()
            xtl = float(box.get("xtl", 0))
            ytl = float(box.get("ytl", 0))
            xbr = float(box.get("xbr", 0))
            ybr = float(box.get("ybr", 0))
            if lbl:
                shapes_by_label.setdefault(lbl, []).append({
                    "type": "rectangle",
                    "frame": frame_idx,
                    "points": [xtl, ytl, xbr, ybr],
                    "occluded": box.get("occluded") == "1",
                    "z_order": int(box.get("z_order", 0)),
                    "rotation": 0,
                    "attributes": [],
                    "elements": [],
                    "group": 0,
                    "source": "manual",
                })

    return shapes_by_label

def parse_annotations_from_json(json_content):
    data = json.loads(json_content)
    shapes_by_label = {}

    # Standard COCO format
    if isinstance(data, dict) and "annotations" in data and "categories" in data:
        cat_map = {c["id"]: c["name"] for c in data.get("categories", [])}
        img_id_to_frame = {}
        for idx, img in enumerate(data.get("images", [])):
            img_id_to_frame[img["id"]] = idx

        for ann in data.get("annotations", []):
            lbl = cat_map.get(ann.get("category_id"), "default")
            frame = img_id_to_frame.get(ann.get("image_id"), 0)
            if "segmentation" in ann and ann["segmentation"]:
                seg = ann["segmentation"][0] if isinstance(ann["segmentation"][0], list) else ann["segmentation"]
                shapes_by_label.setdefault(lbl, []).append({
                    "type": "polygon",
                    "frame": frame,
                    "points": [float(p) for p in seg],
                    "occluded": False,
                    "z_order": 0,
                    "rotation": 0,
                    "attributes": [],
                    "elements": [],
                    "group": 0,
                    "source": "manual",
                })
            elif "bbox" in ann and ann["bbox"]:
                x, y, w, h = ann["bbox"]
                shapes_by_label.setdefault(lbl, []).append({
                    "type": "rectangle",
                    "frame": frame,
                    "points": [float(x), float(y), float(x + w), float(y + h)],
                    "occluded": False,
                    "z_order": 0,
                    "rotation": 0,
                    "attributes": [],
                    "elements": [],
                    "group": 0,
                    "source": "manual",
                })

    # Raw list of shapes: [{ label: ..., points: ..., frame: ... }]
    elif isinstance(data, list):
        for item in data:
            lbl = item.get("label") or item.get("labelName") or "default"
            pts = item.get("points") or []
            frame = int(item.get("frame", 0))
            stype = item.get("shapeType") or item.get("type") or "polygon"
            if pts:
                shapes_by_label.setdefault(lbl, []).append({
                    "type": stype,
                    "frame": frame,
                    "points": [float(p) for p in pts],
                    "occluded": bool(item.get("occluded", False)),
                    "z_order": int(item.get("z_order", item.get("zOrder", 0))),
                    "rotation": 0,
                    "attributes": [],
                    "elements": [],
                    "group": 0,
                    "source": "manual",
                })

    return shapes_by_label

def main():
    parser = argparse.ArgumentParser(description="Transfer and import annotations label-by-label into local CVAT")
    parser.add_argument("source", nargs="?", help="Path to exported XML file, ZIP archive, or JSON file")
    parser.add_argument("--task-id", type=int, default=5, help="Target CVAT Task ID (default: 5)")
    parser.add_argument("--job-id", type=int, default=5, help="Target CVAT Job ID (default: 5)")
    parser.add_argument("--label", type=str, help="Source label name to extract and import (e.g. 'PLV BODY')")
    parser.add_argument("--target-label", type=str, help="Target label name in Task #5 (defaults to matching --label)")
    parser.add_argument("--list-labels", action="store_true", help="List all labels found in the source file without importing")
    parser.add_argument("--replace-label", action="store_true", help="Replace existing annotations of the target label instead of merging")
    args = parser.parse_args()

    if not args.source:
        parser.print_help()
        sys.exit(0)

    content, ftype = extract_xml_from_input(args.source)

    if ftype == "xml":
        shapes_by_label = parse_annotations_from_xml(content)
    elif ftype == "json" or ftype == "coco_json":
        shapes_by_label = parse_annotations_from_json(content)
    else:
        print(f"[!] Unsupported file format: {ftype}")
        sys.exit(1)

    all_labels = list(shapes_by_label.keys())
    print(f"\n[*] Found {len(all_labels)} label(s) in source file:")
    for lbl in all_labels:
        print(f"    - '{lbl}' ({len(shapes_by_label[lbl])} shapes)")

    if args.list_labels:
        print("\n[+] Done listing labels.")
        return

    if not args.label:
        print("\n[!] Please specify which label to import using --label \"<LABEL_NAME>\"")
        print("    Example: python import_label_annotations.py " + args.source + " --label \"" + all_labels[0] + "\"")
        return

    # Match source label
    source_label = args.label.strip()
    matched_src = None
    for lbl in all_labels:
        if lbl.lower() == source_label.lower():
            matched_src = lbl
            break

    if not matched_src:
        print(f"[!] Label '{source_label}' not found in source file. Available: {all_labels}")
        sys.exit(1)

    shapes_to_import = shapes_by_label[matched_src]
    print(f"\n[*] Extracting {len(shapes_to_import)} shapes for label '{matched_src}'...")

    # Load local database
    db = load_db()
    task_id_str = str(args.task_id)
    job_id_str = str(args.job_id)

    task_labels = db.get("labels", {}).get(task_id_str, [])
    if not task_labels:
        print(f"[!] No labels configured for Task #{task_id_str} in local database.")
        sys.exit(1)

    # Determine target label in local task
    target_label_name = (args.target_label or args.label).strip().lower()
    target_label_obj = None
    for l in task_labels:
        if l["name"].strip().lower() == target_label_name:
            target_label_obj = l
            break
        if target_label_name in l["name"].strip().lower() or l["name"].strip().lower() in target_label_name:
            target_label_obj = l
            break

    if not target_label_obj:
        available_task_labels = [l["name"] for l in task_labels]
        print(f"[!] Could not match label '{target_label_name}' with local task labels: {available_task_labels}")
        print(f"    Please specify --target-label with one of the available labels above.")
        sys.exit(1)

    target_label_id = target_label_obj["id"]
    print(f"[+] Mapping shapes to target label: '{target_label_obj['name']}' (ID: {target_label_id})")

    # Prepare shapes with matched label_id
    for s in shapes_to_import:
        s["label_id"] = target_label_id

    # Update job annotations
    if job_id_str not in db.get("annotations", {}):
        db.setdefault("annotations", {})[job_id_str] = {"shapes": [], "tracks": [], "tags": [], "version": 0}

    existing_shapes = db["annotations"][job_id_str].get("shapes", [])

    if args.replace_label:
        filtered_shapes = [s for s in existing_shapes if s.get("label_id") != target_label_id]
        print(f"[-] Replaced {len(existing_shapes) - len(filtered_shapes)} existing shapes for '{target_label_obj['name']}'.")
        existing_shapes = filtered_shapes

    existing_shapes.extend(shapes_to_import)
    db["annotations"][job_id_str]["shapes"] = existing_shapes
    save_db(db)

    print(f"\n[SUCCESS] Imported {len(shapes_to_import)} annotations for '{target_label_obj['name']}' into Job #{job_id_str}!")
    print(f"[*] Total shapes now in Job #{job_id_str}: {len(existing_shapes)}")
    print("[*] Refresh your CVAT browser tab to see the updated annotations instantly.\n")

if __name__ == "__main__":
    main()
