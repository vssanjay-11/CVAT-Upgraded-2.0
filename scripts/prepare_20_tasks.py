#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
"""
scripts/prepare_20_tasks.py
===========================
ROOTS Platform -- Prepare 20 New Annotation Tasks from G:\\A_50 Dataset.

Storage: GOOGLE DRIVE ONLY -- No local D: drive copy is made.
Source images are read directly from G:\\A_50 and streamed to:
  Drive Root: 1NRmlelgPqA61sEpK6AyyYg_eSIE-LdZD
    /tasks/task_N_A50-Batch-NN/
         /source/   <- all 1,250 images uploaded here
         /metadata/ <- meta.json, task manifest
         /exports/

DB (local_server_data/db.json) records task metadata so the server
can serve/reference images via Drive file IDs.

Design:
- Source: G:\\A_50 directory (38,833 images available)
- Take first 25,000 images in deterministic natural sort order
- Split into 20 tasks x 1,250 images each (no overlap, no duplication)
- Task names: "Task {N} -- A50-Batch-{N:02d}"  (N = 1 to 20)
- Register each task in local_server_data/db.json (metadata only)
- Drive manifest written per task so server can rebuild from Drive

Usage:
    python scripts/prepare_20_tasks.py [--dry-run] [--source G:\\A_50] [--limit 25000]
    python scripts/prepare_20_tasks.py --start-at 1  (resume from a specific task)
"""

import argparse
import json
import mimetypes
import os
import re
import shutil
import sys
import time
from pathlib import Path

# ---- Project root on sys.path so we can import our modules ----
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DB_FILE = PROJECT_ROOT / "local_server_data" / "db.json"
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def natural_sort_key(name: str):
    """Case-insensitive natural sort so filenames sort deterministically."""
    parts = re.split(r'(\d+)', name.lower())
    return [int(p) if p.isdigit() else p for p in parts]


def task_name_for(n: int) -> str:
    return f"Task {n} \u2014 A50-Batch-{n:02d}"


def collect_images(source_dir: Path, limit: int) -> list:
    all_files = [
        f for f in source_dir.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
    ]
    all_files.sort(key=lambda f: natural_sort_key(f.name))
    print(f"[OK] Found {len(all_files)} images in {source_dir}")
    if len(all_files) < limit:
        raise ValueError(f"Source has {len(all_files)} images, need {limit}.")
    selected = all_files[:limit]
    print(f"[OK] Selected first {len(selected)} images for {NUM_TASKS} tasks.")
    return selected


def load_db() -> dict:
    return json.loads(DB_FILE.read_text(encoding="utf-8"))


def save_db(db: dict):
    DB_FILE.write_text(json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8")


def register_task_in_db(db: dict, task_id: int, job_id: int,
                         task_name: str, images: list, label_id: int,
                         drive_folders: dict) -> dict:
    """Register task metadata in db. Images are on Drive, not local."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    labels = [{
        "id": label_id,
        "name": "DEFECT",
        "color": "#ff0000",
        "type": "polygon",
        "attributes": [],
        "sublabels": [],
        "has_parent": False,
    }]
    db["labels"][str(task_id)] = labels

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
        # Drive storage references
        "storage": "google_drive",
        "drive_folder_id": drive_folders.get("task_folder_id"),
        "drive_source_folder_id": drive_folders.get("source_folder_id"),
        "drive_metadata_folder_id": drive_folders.get("metadata_folder_id"),
    }
    db["tasks"][str(task_id)] = task

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

    db["annotations"][str(job_id)] = {
        "version": 0,
        "tags": [],
        "shapes": [],
        "tracks": [],
    }
    return db


def upload_images_to_drive(drive_svc, images: list, source_folder_id: str,
                             task_n: int, dry_run: bool) -> list:
    """
    Upload image files directly from G:\\A_50 to Drive source folder.
    Returns list of {filename, drive_file_id, size} dicts.
    """
    if dry_run:
        return [{"filename": img.name, "drive_file_id": "DRY_RUN", "size": 0}
                for img in images]

    uploaded = []
    total = len(images)
    for idx, src_path in enumerate(images, 1):
        mime, _ = mimetypes.guess_type(str(src_path))
        mime = mime or "image/jpeg"

        try:
            result = drive_svc.upload_file(src_path, source_folder_id)
            uploaded.append({
                "filename": src_path.name,
                "drive_file_id": result["file_id"],
                "size": result.get("size", 0),
            })
            if idx % 100 == 0 or idx == total:
                print(f"    [{idx}/{total}] uploaded {src_path.name}")
        except Exception as e:
            print(f"    [!] FAILED uploading {src_path.name}: {e}", file=sys.stderr)
            raise

    return uploaded


def write_drive_meta(drive_svc, task_id: int, task_name: str,
                      images: list, uploaded: list,
                      metadata_folder_id: str, dry_run: bool):
    """Write meta.json and manifest to Drive metadata/ folder."""
    if dry_run:
        return

    import io as _io

    frames = []
    for idx, src_path in enumerate(images):
        up = uploaded[idx] if idx < len(uploaded) else {}
        frames.append({
            "id": idx,
            "name": src_path.name,
            "width": 0,
            "height": 0,
            "drive_file_id": up.get("drive_file_id"),
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
        "storage": "google_drive",
        "cloud_storage_id": None,
        "chunks_updated_date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "chapters": None,
    }

    manifest = {
        "task_id": task_id,
        "task_name": task_name,
        "image_count": len(uploaded),
        "total_bytes": sum(u.get("size", 0) for u in uploaded),
        "files": uploaded,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    # Upload meta.json to Drive (stream from memory, no local file)
    try:
        from googleapiclient.http import MediaIoBaseUpload
        for fname, data in [("meta.json", meta), ("task_manifest.json", manifest)]:
            payload = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
            media = MediaIoBaseUpload(
                _io.BytesIO(payload),
                mimetype="application/json",
                resumable=False
            )
            file_metadata = {
                "name": fname,
                "parents": [metadata_folder_id],
                "mimeType": "application/json"
            }
            drive_svc.service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id",
                supportsAllDrives=True
            ).execute()
            print(f"    Wrote {fname} to Drive metadata folder.")
    except Exception as e:
        print(f"    [!] Failed writing metadata to Drive: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Prepare 20 annotation tasks -- images go DIRECTLY to Google Drive"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Plan without uploading or writing any files")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE,
                        help=f"Source image directory (default: {DEFAULT_SOURCE})")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"Images to use (default: {DEFAULT_LIMIT})")
    parser.add_argument("--start-at", type=int, default=1,
                        help="Resume from task N (1-20) if a previous run was interrupted")
    args = parser.parse_args()

    print("=" * 70)
    print("  ROOTS -- Prepare 20 Tasks -> Google Drive")
    print(f"  Mode: {'DRY-RUN (zero uploads)' if args.dry_run else 'LIVE -- images upload to Drive'}")
    print(f"  Source: {args.source}")
    print(f"  Images: {args.limit} total, {IMAGES_PER_TASK}/task x {NUM_TASKS} tasks")
    print(f"  Target: Google Drive folder 1NRmlelgPqA61sEpK6AyyYg_eSIE-LdZD")
    print("=" * 70)

    # -- Source validation
    if not args.source.exists():
        raise FileNotFoundError(f"Source directory not found: {args.source}")

    all_images = collect_images(args.source, args.limit)

    names = [img.name for img in all_images]
    assert len(names) == len(set(names)), "DUPLICATE FILENAMES -- ABORT"
    assert len(all_images) == NUM_TASKS * IMAGES_PER_TASK

    # -- DB load
    db = load_db()

    # -- Verify protected tasks
    for tid_str, expected_name in PROTECTED_TASK_NAMES.items():
        t = db["tasks"].get(tid_str, {})
        print(f"[OK] Protected Task {tid_str}: '{t.get('name', 'NOT FOUND')}'")
    ann5 = db["annotations"].get("5", {})
    shapes5 = len(ann5.get("shapes", []))
    if shapes5 != 1865:
        raise RuntimeError(f"Task 5 annotation count {shapes5} != 1865 -- ABORT")
    print(f"[OK] Task 5 annotations: {shapes5} shapes -- baseline safe")

    next_task_id = db.get("next_task_id", 17)
    next_job_id = db.get("next_job_id", 17)
    next_label_id = db.get("next_label_id", 10)
    print(f"[OK] Starting IDs: task={next_task_id}, job={next_job_id}")

    # -- Build plan
    plan = []
    for n in range(1, NUM_TASKS + 1):
        si = (n - 1) * IMAGES_PER_TASK
        plan.append({
            "n": n,
            "task_id": next_task_id + (n - 1),
            "job_id": next_job_id + (n - 1),
            "label_id": next_label_id + (n - 1),
            "name": task_name_for(n),
            "images": all_images[si: si + IMAGES_PER_TASK],
        })

    # -- Print assignment table
    print()
    print(f"{'N':>3}  {'Task ID':>7}  {'Name':<35}  {'First Image'}")
    print("-" * 100)
    for p in plan:
        print(f"{p['n']:>3}  {p['task_id']:>7}  {p['name']:<35}  {p['images'][0].name}")

    if args.dry_run:
        print("\n[DRY-RUN] Nothing uploaded. Run without --dry-run to execute.")
        return

    # -- Init Drive service
    print("\nInitializing Google Drive connection...")
    from google_drive_storage import GoogleDriveStorageService
    drive_svc = GoogleDriveStorageService()
    if not drive_svc.is_configured():
        print("[!] ERROR: Google Drive is NOT configured (no credentials found).")
        print("    Make sure token.json exists (from prior Google login) or set")
        print("    GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_SERVICE_ACCOUNT_JSON.")
        sys.exit(1)
    print("[OK] Drive connected.\n")

    # -- DB backup
    backup = DB_FILE.parent / f"db_before_20tasks_{int(time.time())}.json"
    shutil.copy2(DB_FILE, backup)
    print(f"DB backup: {backup.name}")

    # -- Execute uploads
    for p in plan:
        n = p["n"]
        if n < args.start_at:
            print(f"[SKIP] Task {n} (--start-at {args.start_at})")
            continue

        task_id = p["task_id"]
        job_id = p["job_id"]
        label_id = p["label_id"]
        name = p["name"]
        images = p["images"]

        print(f"\n{'='*60}")
        print(f"[Task {n:02d}/{NUM_TASKS}] '{name}' | ID={task_id} | {IMAGES_PER_TASK} images")
        print(f"{'='*60}")

        # 1. Create Drive folder structure
        print(f"  Creating Drive folders...")
        try:
            drive_folders = drive_svc.ensure_task_folders(task_id, name)
            print(f"  source_folder: {drive_folders['source_folder_id']}")
        except Exception as e:
            print(f"  [!] FAILED creating Drive folders: {e}", file=sys.stderr)
            raise

        # 2. Upload images straight from G:\A_50 to Drive source/
        print(f"  Uploading {IMAGES_PER_TASK} images to Drive source/...")
        t0 = time.time()
        uploaded = upload_images_to_drive(
            drive_svc, images,
            drive_folders["source_folder_id"],
            n, dry_run=False
        )
        elapsed = time.time() - t0
        print(f"  Uploaded {len(uploaded)} images in {elapsed:.0f}s")

        # 3. Write meta.json + manifest to Drive metadata/
        print(f"  Writing metadata to Drive...")
        write_drive_meta(
            drive_svc, task_id, name, images, uploaded,
            drive_folders["metadata_folder_id"],
            dry_run=False
        )

        # 4. Register in local db.json (metadata only, no local images)
        db = register_task_in_db(db, task_id, job_id, name, images, label_id, drive_folders)
        db["next_task_id"] = task_id + 1
        db["next_job_id"] = job_id + 1
        db["next_label_id"] = label_id + 1
        save_db(db)
        print(f"  [DONE] Task {n} registered in DB with Drive storage references.")

    # -- Final save and summary
    save_db(db)
    print(f"\n{'='*70}")
    print(f"[COMPLETE] All {NUM_TASKS} tasks uploaded to Google Drive.")
    print(f"  Task IDs: {plan[0]['task_id']} -- {plan[-1]['task_id']}")
    print(f"  Drive root: 1NRmlelgPqA61sEpK6AyyYg_eSIE-LdZD/tasks/")
    print(f"  DB: local_server_data/db.json updated (metadata only, no local images)")
    print(f"  Protected tasks preserved: ID=5 ({PROTECTED_TASK_NAMES['5']}), ID=10")
    print("=" * 70)


if __name__ == "__main__":
    main()
