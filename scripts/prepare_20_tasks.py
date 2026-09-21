#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
"""
scripts/prepare_20_tasks.py
===========================
ROOTS Platform — Prepare 20 New Tasks from G:\\A_50 Dataset.

Design:
- Source: G:\\A_50 directory (38,833 images available)
- Take first 25,000 images in deterministic natural sort order
- Split into 20 tasks × 1,250 images each (no overlap, no duplication)
- Task names: "Task {N} — A50-Batch-{N:02d}"  (N = 1 to 20)
- Register each task in local_server_data/db.json
- Copy images to local_server_data/tasks/<id>/images/
- Create task directory structure (meta.json, preview.jpg)

IMPORTANT:
- Task 5 and Task 10 are PROTECTED — their names, IDs and annotations are preserved
- New tasks get IDs from next_task_id onward (currently 17)
- Run validate_20_tasks.py first to dry-run without any writes

Usage:
    python scripts/prepare_20_tasks.py [--dry-run] [--source G:\\A_50] [--limit 25000]
"""

import argparse
import json
import os
import shutil
import time
import hashlib
from pathlib import Path

# ─── Configuration ────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_FILE = PROJECT_ROOT / "local_server_data" / "db.json"
TASKS_DIR = PROJECT_ROOT / "local_server_data" / "tasks"
DEFAULT_SOURCE = Path("G:/A_50")
DEFAULT_LIMIT = 25000
IMAGES_PER_TASK = 1250
NUM_TASKS = 20
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}

PROTECTED_TASK_IDS = {"5", "10"}
PROTECTED_TASK_NAMES = {
    "5": "Task 21 \u2014 ROOTS01 (V.S.Sanjay)",
    "10": "Task 22 \u2014 roots06shakthivel",
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def natural_sort_key(name: str):
    """Case-insensitive natural sort key for filenames."""
    import re
    parts = re.split(r'(\d+)', name.lower())
    result = []
    for p in parts:
        result.append(int(p) if p.isdigit() else p)
    return result


def collect_images(source_dir: Path, limit: int) -> list:
    """Collect up to `limit` image files from source_dir, deterministically sorted."""
    all_files = [
        f for f in source_dir.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
    ]
    all_files.sort(key=lambda f: natural_sort_key(f.name))
    print(f"Found {len(all_files)} images in {source_dir}")
    if len(all_files) < limit:
        raise ValueError(
            f"Source has only {len(all_files)} images but {limit} are required. "
            f"Adjust --limit or add more images."
        )
    selected = all_files[:limit]
    print(f"Selected first {len(selected)} images for 20 tasks.")
    return selected


def task_name_for(n: int) -> str:
    return f"Task {n} \u2014 A50-Batch-{n:02d}"


def make_label_id(base_label_id: int, offset: int) -> int:
    return base_label_id + offset


def load_db() -> dict:
    return json.loads(DB_FILE.read_text(encoding="utf-8"))


def save_db(db: dict):
    DB_FILE.write_text(json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8")


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def create_task_directories(task_id: int, dry_run: bool):
    task_dir = TASKS_DIR / str(task_id)
    images_dir = task_dir / "images"
    chunks_dir = task_dir / "chunks"
    if not dry_run:
        images_dir.mkdir(parents=True, exist_ok=True)
        chunks_dir.mkdir(parents=True, exist_ok=True)
    return task_dir, images_dir, chunks_dir


def copy_images(images: list, dest_dir: Path, dry_run: bool) -> list:
    """Copy images to dest_dir. Returns list of frame dicts."""
    frames = []
    for idx, src_path in enumerate(images):
        dest = dest_dir / src_path.name
        if not dry_run:
            shutil.copy2(src_path, dest)
        frames.append({
            "id": idx,
            "name": src_path.name,
            "width": 0,      # Will be populated if PIL is available
            "height": 0,
            "related_files": 0,
        })
    return frames


def try_get_image_size(path: Path):
    try:
        from PIL import Image
        with Image.open(path) as img:
            return img.size  # (width, height)
    except Exception:
        return (0, 0)


def create_meta_json(task_dir: Path, task_id: int, task_name: str,
                      images: list, dry_run: bool):
    """Create tasks/<id>/meta.json in the format cvat_local_server.py expects."""
    frames = []
    for idx, src_path in enumerate(images):
        w, h = (0, 0)
        if not dry_run:
            dest = task_dir / "images" / src_path.name
            if dest.exists():
                w, h = try_get_image_size(dest)
            else:
                w, h = try_get_image_size(src_path)
        frames.append({
            "id": idx,
            "name": src_path.name,
            "width": w,
            "height": h,
            "related_files": 0,
        })

    meta = {
        "chunk_size": IMAGES_PER_TASK,
        "size": IMAGES_PER_TASK,
        "image_quality": 80,
        "start_frame": 0,
        "stop_frame": IMAGES_PER_TASK - 1,
        "frame_filter": "",
        "frames": frames,
        "deleted_frames": [],
        "included_frames": None,
        "storage": "local",
        "cloud_storage_id": None,
        "chunks_updated_date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "chapters": None,
    }
    if not dry_run:
        meta_path = task_dir / "meta.json"
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


def create_preview(images: list, task_dir: Path, dry_run: bool):
    """Copy first image as preview.jpg."""
    if not images or dry_run:
        return
    src = images[0]
    dest = task_dir / "preview.jpg"
    try:
        from PIL import Image
        with Image.open(src) as img:
            img_rgb = img.convert("RGB")
            img_rgb.thumbnail((400, 300))
            img_rgb.save(str(dest), "JPEG", quality=70)
    except Exception:
        shutil.copy2(src, dest)


def register_task_in_db(db: dict, task_id: int, job_id: int,
                          task_name: str, images: list,
                          label_id: int) -> dict:
    """Register the task, job, labels, and empty annotations in db."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Labels
    labels = [
        {
            "id": label_id,
            "name": "DEFECT",
            "color": "#ff0000",
            "type": "polygon",
            "attributes": [],
            "sublabels": [],
            "has_parent": False,
        }
    ]
    db["labels"][str(task_id)] = labels

    # Task
    image_list = [img.name for img in images]
    task = {
        "id": task_id,
        "name": task_name,
        "status": "annotation",
        "size": IMAGES_PER_TASK,
        "mode": "annotation",
        "dimension": "2d",
        "owner": {"id": 1, "username": "admin"},
        "assignee": None,
        "bug_tracker": "",
        "overlap": 0,
        "segment_size": IMAGES_PER_TASK,
        "image_quality": 80,
        "data_chunk_size": IMAGES_PER_TASK,
        "created_date": now,
        "updated_date": now,
        "labels": labels,
        "jobs": [job_id],
        "image_list": image_list,
        "project_id": None,
        "subset": "",
        "organization": None,
    }
    db["tasks"][str(task_id)] = task

    # Job
    job = {
        "id": job_id,
        "task_id": task_id,
        "task_name": task_name,
        "status": "annotation",
        "start_frame": 0,
        "stop_frame": IMAGES_PER_TASK - 1,
        "assignee": None,
        "reviewer": None,
        "stage": "annotation",
        "state": "new",
        "created_date": now,
        "updated_date": now,
        "dimension": "2d",
        "data_chunk_size": IMAGES_PER_TASK,
        "mode": "annotation",
        "type": "annotation",
    }
    db["jobs"][str(job_id)] = job

    # Empty annotations
    db["annotations"][str(job_id)] = {
        "version": 0,
        "tags": [],
        "shapes": [],
        "tracks": [],
    }

    return db


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Prepare 20 annotation tasks from G:\\A_50")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print plan without writing any files")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE,
                        help=f"Source image directory (default: {DEFAULT_SOURCE})")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"Number of images to use (default: {DEFAULT_LIMIT})")
    args = parser.parse_args()

    print("=" * 70)
    print(f"  ROOTS — Prepare 20 Tasks from A_50 Dataset")
    print(f"  Mode: {'DRY-RUN (no files written)' if args.dry_run else 'LIVE (files will be created)'}")
    print(f"  Source: {args.source}")
    print(f"  Images to use: {args.limit}")
    print(f"  Tasks: {NUM_TASKS} × {IMAGES_PER_TASK} images")
    print("=" * 70)

    # Validate source
    if not args.source.exists():
        raise FileNotFoundError(f"Source directory not found: {args.source}")

    # Collect images
    all_images = collect_images(args.source, args.limit)

    # Validate no duplicates
    names = [img.name for img in all_images]
    assert len(names) == len(set(names)), "DUPLICATE FILENAMES DETECTED — ABORT"
    print(f"✓ No duplicate filenames in selected set.")

    # Validate split coverage
    assert len(all_images) == NUM_TASKS * IMAGES_PER_TASK, \
        f"Expected {NUM_TASKS * IMAGES_PER_TASK}, got {len(all_images)}"
    print(f"✓ Split check: {NUM_TASKS} × {IMAGES_PER_TASK} = {len(all_images)} images")

    # Load DB
    db = load_db()

    # Verify protected tasks
    for tid_str, expected_name in PROTECTED_TASK_NAMES.items():
        t = db["tasks"].get(tid_str, {})
        if t:
            print(f"✓ Protected Task {tid_str} present: '{t.get('name')}'")
        else:
            print(f"⚠ WARNING: Protected Task {tid_str} not found in db!")

    # Verify annotations for Task 5
    ann5 = db["annotations"].get("5", {})
    shapes5 = len(ann5.get("shapes", []))
    print(f"✓ Task 5 (Job 5) annotations: {shapes5} shapes")
    if shapes5 != 1865:
        raise RuntimeError(f"Task 5 annotation count is {shapes5}, expected 1865 — ABORT")

    # Determine starting IDs
    next_task_id = db.get("next_task_id", 17)
    next_job_id = db.get("next_job_id", 17)
    next_label_id = db.get("next_label_id", 10)

    print(f"\nStarting IDs: task={next_task_id}, job={next_job_id}, label={next_label_id}")
    print()

    # Plan all 20 tasks
    plan = []
    for n in range(1, NUM_TASKS + 1):
        start_idx = (n - 1) * IMAGES_PER_TASK
        end_idx = n * IMAGES_PER_TASK
        task_images = all_images[start_idx:end_idx]
        task_id = next_task_id + (n - 1)
        job_id = next_job_id + (n - 1)
        label_id = next_label_id + (n - 1)
        name = task_name_for(n)
        plan.append({
            "n": n,
            "task_id": task_id,
            "job_id": job_id,
            "label_id": label_id,
            "name": name,
            "images": task_images,
            "first_image": task_images[0].name,
            "last_image": task_images[-1].name,
        })

    # Print plan
    print(f"{'N':>3}  {'Task ID':>7}  {'Job ID':>6}  {'Name':<35}  {'First Image':<45}  {'Last Image'}")
    print("-" * 140)
    for p in plan:
        print(f"{p['n']:>3}  {p['task_id']:>7}  {p['job_id']:>6}  {p['name']:<35}  {p['first_image']:<45}  {p['last_image']}")

    if args.dry_run:
        print("\n[DRY-RUN] No files written. Run without --dry-run to execute.")
        return

    # LIVE execution
    print(f"\n{'='*70}")
    print("LIVE EXECUTION — Creating tasks...")
    print("="*70)

    # Backup DB before modification
    backup_name = DB_FILE.parent / f"db_before_20tasks_{int(time.time())}.json"
    shutil.copy2(DB_FILE, backup_name)
    print(f"DB backup: {backup_name}")

    for p in plan:
        task_id = p["task_id"]
        job_id = p["job_id"]
        name = p["name"]
        images = p["images"]
        label_id = p["label_id"]
        n = p["n"]

        print(f"\n[Task {n:02d}] Creating '{name}' (ID={task_id}, Job={job_id})...")
        task_dir, images_dir, chunks_dir = create_task_directories(task_id, dry_run=False)

        # Copy images
        print(f"  Copying {len(images)} images...")
        start_t = time.time()
        for src_path in images:
            dest = images_dir / src_path.name
            if not dest.exists():
                shutil.copy2(src_path, dest)
        elapsed = time.time() - start_t
        print(f"  Copied in {elapsed:.1f}s")

        # Create meta.json
        meta = create_meta_json(task_dir, task_id, name, images, dry_run=False)
        print(f"  meta.json: {meta['size']} frames")

        # Create preview
        create_preview(images, task_dir, dry_run=False)

        # Register in DB
        db = register_task_in_db(db, task_id, job_id, name, images, label_id)

        # Update DB counters
        db["next_task_id"] = task_id + 1
        db["next_job_id"] = job_id + 1
        db["next_label_id"] = label_id + 1

        # Save DB after each task (checkpoint writes)
        save_db(db)
        print(f"  ✓ Task {n} registered in DB.")

    # Final DB save
    save_db(db)

    # Summary
    print(f"\n{'='*70}")
    print(f"✓ ALL 20 TASKS CREATED SUCCESSFULLY")
    print(f"  IDs used: {plan[0]['task_id']} — {plan[-1]['task_id']}")
    print(f"  Jobs: {plan[0]['job_id']} — {plan[-1]['job_id']}")
    print(f"  Images: {len(all_images)} total, {IMAGES_PER_TASK} per task")
    print(f"  Protected tasks: ID=5 ('{PROTECTED_TASK_NAMES['5']}'), ID=10 ('{PROTECTED_TASK_NAMES['10']}')")
    print("="*70)


if __name__ == "__main__":
    main()
