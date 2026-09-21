# Copyright (C) CVAT.ai Corporation
# SPDX-License-Identifier: MIT

"""
Complete CVAT-Compatible Dataset Exporters for Local CVAT Fork.
Handles specification-compliant dataset packaging for:
1. CVAT for images 1.1 (XML)
2. COCO 1.0 (JSON)
3. Ultralytics YOLO Segmentation 1.0 (data.yaml + normalized polygon coords)
4. LabelMe 3.0 (per-image JSON)
5. Segmentation mask 1.1 (raster PNG masks)
6. Datumaro 1.0 (JSON)

Validates every archive before marking export successful.
"""

import json
import os
import shutil
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from PIL import Image, ImageDraw

FORMAT_REGISTRY = [
    {
        "name": "CVAT for images 1.1",
        "ext": "zip",
        "version": "1.1",
        "enabled": True,
        "dimension": "2d",
    },
    {
        "name": "COCO 1.0",
        "ext": "zip",
        "version": "1.0",
        "enabled": True,
        "dimension": "2d",
    },
    {
        "name": "Ultralytics YOLO Segmentation 1.0",
        "ext": "zip",
        "version": "1.0",
        "enabled": True,
        "dimension": "2d",
    },
    {
        "name": "LabelMe 3.0",
        "ext": "zip",
        "version": "3.0",
        "enabled": True,
        "dimension": "2d",
    },
    {
        "name": "Segmentation mask 1.1",
        "ext": "zip",
        "version": "1.1",
        "enabled": True,
        "dimension": "2d",
    },
    {
        "name": "Datumaro 1.0",
        "ext": "zip",
        "version": "1.0",
        "enabled": True,
        "dimension": "2d",
    },
]

PALETTE_COLORS = [
    (0, 0, 0),        # Background: 0
    (0, 128, 0),      # Class 1: Green
    (128, 0, 0),      # Class 2: Maroon
    (0, 0, 128),      # Class 3: Navy
    (128, 128, 0),    # Class 4: Olive
    (128, 0, 128),    # Class 5: Purple
    (0, 128, 128),    # Class 6: Teal
    (192, 192, 192),  # Class 7: Silver
    (255, 0, 0),      # Class 8: Red
    (0, 255, 0),      # Class 9: Lime
    (0, 0, 255),      # Class 10: Blue
    (255, 255, 0),    # Class 11: Yellow
    (255, 0, 255),    # Class 12: Magenta
    (0, 255, 255),    # Class 13: Cyan
]


def build_cvat_xml(
    frames: List[Dict[str, Any]],
    shapes_by_frame: Dict[int, List[Dict[str, Any]]],
    task_labels: List[Dict[str, Any]],
    task_id: str,
    task_name: str,
) -> bytes:
    """Generate official CVAT 1.1 XML bytes."""
    root = ET.Element("annotations")
    ET.SubElement(root, "version").text = "1.1"

    meta_elem = ET.SubElement(root, "meta")
    task_elem = ET.SubElement(meta_elem, "task")
    ET.SubElement(task_elem, "id").text = str(task_id)
    ET.SubElement(task_elem, "name").text = str(task_name)
    ET.SubElement(task_elem, "size").text = str(len(frames))
    ET.SubElement(task_elem, "mode").text = "annotation"
    ET.SubElement(task_elem, "overlap").text = "0"
    ET.SubElement(task_elem, "bugtracker").text = ""
    ET.SubElement(task_elem, "created").text = "2026-09-19T00:00:00Z"
    ET.SubElement(task_elem, "updated").text = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    labels_elem = ET.SubElement(task_elem, "labels")
    labels_by_id = {}
    for lbl in task_labels:
        labels_by_id[lbl["id"]] = lbl
        lbl_elem = ET.SubElement(labels_elem, "label")
        ET.SubElement(lbl_elem, "name").text = lbl.get("name", "part")
        ET.SubElement(lbl_elem, "color").text = lbl.get("color", "#00ff00")
        ET.SubElement(lbl_elem, "type").text = lbl.get("type", "any")

    for idx, fobj in enumerate(frames):
        fname = fobj.get("name", f"{idx:06d}.jpg")
        w = fobj.get("width", 640)
        h = fobj.get("height", 480)
        img_elem = ET.SubElement(root, "image", {
            "id": str(idx),
            "name": fname,
            "width": str(w),
            "height": str(h)
        })

        for s in shapes_by_frame.get(idx, []):
            stype = s.get("type", "polygon")
            lid = s.get("label_id")
            label_name = labels_by_id.get(lid, {}).get("name", "part")
            pts = s.get("points", [])
            occ = "1" if s.get("occluded") else "0"
            z = str(s.get("z_order", 0))

            if stype in ("rectangle", "box"):
                if len(pts) >= 4:
                    xtl = min(pts[0], pts[2])
                    ytl = min(pts[1], pts[3])
                    xbr = max(pts[0], pts[2])
                    ybr = max(pts[1], pts[3])
                    ET.SubElement(img_elem, "box", {
                        "label": label_name,
                        "occluded": occ,
                        "z_order": z,
                        "xtl": f"{xtl:.2f}",
                        "ytl": f"{ytl:.2f}",
                        "xbr": f"{xbr:.2f}",
                        "ybr": f"{ybr:.2f}"
                    })
            else:
                pts_str = ";".join([f"{pts[i]:.2f},{pts[i+1]:.2f}" for i in range(0, len(pts), 2)]) if pts else ""
                tag_name = stype if stype in ("polygon", "polyline", "points") else "polygon"
                ET.SubElement(img_elem, tag_name, {
                    "label": label_name,
                    "occluded": occ,
                    "z_order": z,
                    "points": pts_str
                })

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def build_coco_dict(
    frames: List[Dict[str, Any]],
    shapes_by_frame: Dict[int, List[Dict[str, Any]]],
    task_labels: List[Dict[str, Any]],
    task_name: str,
) -> Dict[str, Any]:
    """Generate official COCO 1.0 dict with separate instance segmentations."""
    coco_dict = {
        "licenses": [{"name": "", "id": 0, "url": ""}],
        "info": {
            "contributor": "",
            "date_created": time.strftime("%Y-%m-%d"),
            "description": str(task_name),
            "url": "",
            "version": "1.0",
            "year": 2026,
        },
        "categories": [
            {"id": lbl["id"], "name": lbl["name"], "supercategory": ""}
            for lbl in task_labels
        ],
        "images": [],
        "annotations": [],
    }

    anno_counter = 1
    for idx, fobj in enumerate(frames):
        fname = fobj.get("name", f"{idx:06d}.jpg")
        w = fobj.get("width", 640)
        h = fobj.get("height", 480)
        img_id = idx + 1
        coco_dict["images"].append({
            "id": img_id,
            "width": w,
            "height": h,
            "file_name": fname,
            "license": 0,
            "flickr_url": "",
            "coco_url": "",
            "date_captured": 0,
        })
        for s in shapes_by_frame.get(idx, []):
            pts = s.get("points", [])
            lid = s.get("label_id", 1)
            xs = [pts[i] for i in range(0, len(pts), 2)] if pts else [0]
            ys = [pts[i+1] for i in range(0, len(pts), 2)] if pts else [0]
            bx = min(xs)
            by = min(ys)
            bw = max(xs) - bx
            bh = max(ys) - by
            coco_dict["annotations"].append({
                "id": anno_counter,
                "image_id": img_id,
                "category_id": lid,
                "segmentation": [pts] if pts else [],
                "area": round(float(bw * bh), 2),
                "bbox": [round(float(bx), 2), round(float(by), 2), round(float(bw), 2), round(float(bh), 2)],
                "iscrowd": 0,
            })
            anno_counter += 1

    return coco_dict


def build_yolo_seg_data(
    frames: List[Dict[str, Any]],
    shapes_by_frame: Dict[int, List[Dict[str, Any]]],
    task_labels: List[Dict[str, Any]],
) -> Tuple[str, str, Dict[str, str]]:
    """
    Generate Ultralytics YOLO Segmentation data.yaml, train.txt, and label text files.
    Coordinates are normalized to [0, 1] relative to frame width and height.
    Class IDs are mapped 0..N-1 based on task_labels order.
    Matches standard industrial format:
    - data.yaml (with names, nc, path: ., train: train.txt)
    - train.txt (paths pointing to 'original image/{name}')
    - labels/train/*.txt
    """
    label_to_yolo_idx = {}
    class_names = []
    for idx, lbl in enumerate(task_labels):
        label_to_yolo_idx[lbl["id"]] = idx
        class_names.append(lbl["name"])

    # Build data.yaml
    names_lines = ["names:"]
    for i, name in enumerate(class_names):
        names_lines.append(f"  {i}: {name}")
    yaml_lines = names_lines + [
        f"nc: {len(class_names)}",
        "path: .",
        "train: train.txt",
    ]
    yaml_content = "\n".join(yaml_lines) + "\n"

    # Build train.txt
    train_lines = [f"original image/{fobj.get('name', f'{idx:06d}.jpg')}" for idx, fobj in enumerate(frames)]
    train_txt_content = "\n".join(train_lines) + "\n"

    label_files = {}
    for idx, fobj in enumerate(frames):
        fname = fobj.get("name", f"{idx:06d}.jpg")
        stem = Path(fname).stem
        w = float(fobj.get("width", 640))
        h = float(fobj.get("height", 480))

        lines = []
        for s in shapes_by_frame.get(idx, []):
            pts = s.get("points", [])
            lid = s.get("label_id")
            yolo_cid = label_to_yolo_idx.get(lid, 0)

            if len(pts) >= 6:
                # Normalize points
                norm_pts = []
                for i in range(0, len(pts), 2):
                    nx = max(0.0, min(1.0, pts[i] / w))
                    ny = max(0.0, min(1.0, pts[i+1] / h))
                    norm_pts.append(f"{nx:.6f}")
                    norm_pts.append(f"{ny:.6f}")
                lines.append(f"{yolo_cid} " + " ".join(norm_pts))

        label_files[f"{stem}.txt"] = "\n".join(lines) + ("\n" if lines else "")

    return yaml_content, train_txt_content, label_files


def build_labelme_files(
    frames: List[Dict[str, Any]],
    shapes_by_frame: Dict[int, List[Dict[str, Any]]],
    task_labels: List[Dict[str, Any]],
) -> Dict[str, str]:
    """Generate per-image LabelMe JSON files."""
    labels_by_id = {lbl["id"]: lbl for lbl in task_labels}
    json_files = {}

    for idx, fobj in enumerate(frames):
        fname = fobj.get("name", f"{idx:06d}.jpg")
        stem = Path(fname).stem
        w = int(fobj.get("width", 640))
        h = int(fobj.get("height", 480))

        labelme_shapes = []
        for s in shapes_by_frame.get(idx, []):
            pts = s.get("points", [])
            lid = s.get("label_id")
            label_name = labels_by_id.get(lid, {}).get("name", "part")

            pts_2d = [[round(pts[i], 2), round(pts[i+1], 2)] for i in range(0, len(pts), 2)]
            labelme_shapes.append({
                "label": label_name,
                "points": pts_2d,
                "group_id": None,
                "description": "",
                "shape_type": "polygon",
                "flags": {},
            })

        doc = {
            "version": "5.0.1",
            "flags": {},
            "shapes": labelme_shapes,
            "imagePath": fname,
            "imageData": None,
            "imageHeight": h,
            "imageWidth": w,
        }
        json_files[f"{stem}.json"] = json.dumps(doc, indent=2)

    return json_files


def build_segmentation_masks(
    frames: List[Dict[str, Any]],
    shapes_by_frame: Dict[int, List[Dict[str, Any]]],
    task_labels: List[Dict[str, Any]],
) -> Tuple[str, Dict[str, bytes]]:
    """
    Generate raster PNG masks for Segmentation mask 1.1 format.
    Returns (label_map_text, {filename: png_bytes}).
    """
    label_to_val = {}
    label_map_lines = ["# label:color_rgb:parts:actions", "background:0,0,0::"]
    for idx, lbl in enumerate(task_labels, start=1):
        label_to_val[lbl["id"]] = idx
        color = PALETTE_COLORS[idx % len(PALETTE_COLORS)]
        label_map_lines.append(f"{lbl['name']}:{color[0]},{color[1]},{color[2]}::")

    label_map_txt = "\n".join(label_map_lines) + "\n"
    mask_bytes = {}

    for idx, fobj in enumerate(frames):
        fname = fobj.get("name", f"{idx:06d}.jpg")
        stem = Path(fname).stem
        w = int(fobj.get("width", 640))
        h = int(fobj.get("height", 480))

        mask_img = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(mask_img)

        for s in shapes_by_frame.get(idx, []):
            pts = s.get("points", [])
            lid = s.get("label_id")
            val = label_to_val.get(lid, 1)

            if len(pts) >= 6:
                poly = [(pts[i], pts[i+1]) for i in range(0, len(pts), 2)]
                draw.polygon(poly, fill=val)

        buf = io.BytesIO()
        mask_img.save(buf, format="PNG")
        mask_bytes[f"{stem}.png"] = buf.getvalue()

    return label_map_txt, mask_bytes


import io

def build_datumaro_dict(
    frames: List[Dict[str, Any]],
    shapes_by_frame: Dict[int, List[Dict[str, Any]]],
    task_labels: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Generate Datumaro 1.0 JSON format dictionary."""
    label_to_idx = {lbl["id"]: idx for idx, lbl in enumerate(task_labels)}
    datumaro_doc = {
        "info": {},
        "categories": {
            "label": {
                "labels": [{"name": lbl["name"], "parent": ""} for lbl in task_labels],
                "attributes": [],
            }
        },
        "items": [],
    }

    anno_counter = 1
    for idx, fobj in enumerate(frames):
        fname = fobj.get("name", f"{idx:06d}.jpg")
        stem = Path(fname).stem
        w = int(fobj.get("width", 640))
        h = int(fobj.get("height", 480))

        annos = []
        for s in shapes_by_frame.get(idx, []):
            pts = s.get("points", [])
            lid = s.get("label_id")
            dm_label_id = label_to_idx.get(lid, 0)

            annos.append({
                "id": anno_counter,
                "type": "polygon",
                "label_id": dm_label_id,
                "points": [round(p, 2) for p in pts],
                "attributes": {},
            })
            anno_counter += 1

        datumaro_doc["items"].append({
            "id": stem,
            "annotations": annos,
            "image": {"path": fname, "size": [h, w]},
        })

    return datumaro_doc


def validate_exported_archive(
    zip_path: Path,
    format_name: str,
    expected_image_count: int,
    expected_shape_count: int,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Validates the generated ZIP archive structure, files, and annotations.
    """
    if not zip_path.exists():
        return False, "Archive file does not exist on disk", {}

    stats = {
        "archive_size_bytes": zip_path.stat().st_size,
        "format": format_name,
        "file_count": 0,
        "parsed_shapes": 0,
    }

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            namelist = zf.namelist()
            stats["file_count"] = len(namelist)

            fmt = format_name.lower()

            if "cvat" in fmt:
                if "annotations.xml" not in namelist:
                    return False, "Missing annotations.xml in CVAT export", stats
                xml_data = zf.read("annotations.xml")
                root = ET.fromstring(xml_data)
                images = root.findall("image")
                shapes = 0
                for img in images:
                    shapes += len(img.findall("polygon")) + len(img.findall("box")) + len(img.findall("polyline"))
                stats["parsed_images"] = len(images)
                stats["parsed_shapes"] = shapes
                if shapes != expected_shape_count:
                    return False, f"Shape count mismatch in CVAT XML: {shapes} vs expected {expected_shape_count}", stats

            elif "coco" in fmt:
                target_json = next((n for n in namelist if n.endswith(".json")), None)
                if not target_json:
                    return False, "Missing JSON in COCO export", stats
                coco = json.loads(zf.read(target_json).decode("utf-8"))
                images = coco.get("images", [])
                annos = coco.get("annotations", [])
                stats["parsed_images"] = len(images)
                stats["parsed_shapes"] = len(annos)
                if len(annos) != expected_shape_count:
                    return False, f"Shape count mismatch in COCO JSON: {len(annos)} vs expected {expected_shape_count}", stats

            elif "yolo" in fmt:
                if "data.yaml" not in namelist:
                    return False, "Missing data.yaml in YOLO export", stats
                txt_files = [n for n in namelist if n.startswith("labels/train/") and n.endswith(".txt")]
                if not txt_files:
                    txt_files = [n for n in namelist if n.startswith("labels/") and n.endswith(".txt")]
                shapes = 0
                for tf in txt_files:
                    lines = [ln.strip() for ln in zf.read(tf).decode("utf-8").splitlines() if ln.strip()]
                    shapes += len(lines)
                stats["parsed_shapes"] = shapes
                if shapes != expected_shape_count:
                    return False, f"Shape count mismatch in YOLO export: {shapes} vs expected {expected_shape_count}", stats

            elif "labelme" in fmt:
                json_files = [n for n in namelist if n.endswith(".json")]
                shapes = 0
                for jf in json_files:
                    doc = json.loads(zf.read(jf).decode("utf-8"))
                    shapes += len(doc.get("shapes", []))
                stats["parsed_shapes"] = shapes
                if shapes != expected_shape_count:
                    return False, f"Shape count mismatch in LabelMe export: {shapes} vs expected {expected_shape_count}", stats

            elif "mask" in fmt:
                png_files = [n for n in namelist if n.startswith("SegmentationClass/") and n.endswith(".png")]
                stats["parsed_images"] = len(png_files)
                if len(png_files) != expected_image_count:
                    return False, f"Mask image count mismatch: {len(png_files)} vs expected {expected_image_count}", stats

            elif "datumaro" in fmt:
                target_json = next((n for n in namelist if n.endswith("default.json")), None)
                if not target_json:
                    return False, "Missing default.json in Datumaro export", stats
                dm = json.loads(zf.read(target_json).decode("utf-8"))
                items = dm.get("items", [])
                shapes = sum(len(it.get("annotations", [])) for it in items)
                stats["parsed_images"] = len(items)
                stats["parsed_shapes"] = shapes
                if shapes != expected_shape_count:
                    return False, f"Shape count mismatch in Datumaro export: {shapes} vs expected {expected_shape_count}", stats

    except Exception as e:
        return False, f"Validation error: {e}", stats

    return True, "Archive validated successfully", stats
