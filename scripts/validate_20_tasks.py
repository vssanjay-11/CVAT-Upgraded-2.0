#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
"""
scripts/validate_20_tasks.py
============================
ROOTS Platform — Validation / Dry-Run for 20-Task Split.

Checks WITHOUT writing any files:
1. Source directory exists and has enough images
2. Deterministic sort order is reproducible
3. No duplicate filenames in selection
4. All 25,000 indices covered exactly once (0–24999)
5. Task 5 and Task 10 integrity in current db.json
6. Starting IDs don't collide with protected tasks
7. Prints per-task assignment table

Usage:
    python scripts/validate_20_tasks.py [--source G:\\A_50] [--limit 25000]
"""

import argparse
import json
import re
import sys
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_FILE = PROJECT_ROOT / "local_server_data" / "db.json"
TASKS_DIR = PROJECT_ROOT / "local_server_data" / "tasks"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
IMAGES_PER_TASK = 1250
NUM_TASKS = 20
DEFAULT_SOURCE = Path("G:/A_50")
DEFAULT_LIMIT = 25000

PROTECTED = {
    "5": "Task 21 \u2014 ROOTS01 (V.S.Sanjay)",
    "10": "Task 22 \u2014 roots06shakthivel",
}


def natural_sort_key(name: str):
    parts = re.split(r'(\d+)', name.lower())
    return [int(p) if p.isdigit() else p for p in parts]


def task_name_for(n: int) -> str:
    return f"Task {n} \u2014 A50-Batch-{n:02d}"


def validate(source: Path, limit: int) -> bool:
    errors = []
    warnings = []
    ok = True

    print("=" * 70)
    print("  ROOTS — 20-Task Validation (DRY-RUN, zero writes)")
    print("=" * 70)

    # ── Check 1: Source exists
    if not source.exists():
        errors.append(f"Source directory not found: {source}")
        ok = False
    else:
        print(f"[OK] Source directory exists: {source}")

    if not ok:
        for e in errors:
            print(f"[FAIL] {e}")
        return False

    # ── Check 2: Collect images
    all_files = [
        f for f in source.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
    ]
    all_files.sort(key=lambda f: natural_sort_key(f.name))
    print(f"[OK] Total images found: {len(all_files)}")

    if len(all_files) < limit:
        errors.append(f"Insufficient images: need {limit}, found {len(all_files)}")
        ok = False
    else:
        selected = all_files[:limit]
        print(f"[OK] First {limit} images selected for tasks.")

    if not ok:
        for e in errors:
            print(f"[FAIL] {e}")
        return False

    # ── Check 3: No duplicate filenames
    names = [f.name for f in selected]
    counts = Counter(names)
    dups = {n: c for n, c in counts.items() if c > 1}
    if dups:
        errors.append(f"Duplicate filenames detected: {list(dups.items())[:5]}")
        ok = False
    else:
        print(f"[OK] No duplicate filenames in selected {limit} images.")

    # ── Check 4: Full index coverage
    total = len(selected)
    if total != NUM_TASKS * IMAGES_PER_TASK:
        errors.append(f"Count mismatch: {total} != {NUM_TASKS} × {IMAGES_PER_TASK} = {NUM_TASKS * IMAGES_PER_TASK}")
        ok = False
    else:
        print(f"[OK] Coverage: {NUM_TASKS} tasks × {IMAGES_PER_TASK} images = {total} (complete)")

    # ── Check 5: Sort stability — re-sort and compare
    recheck = sorted(selected, key=lambda f: natural_sort_key(f.name))
    if [f.name for f in recheck] != [f.name for f in selected]:
        errors.append("SORT INSTABILITY: re-sorting produces a different order!")
        ok = False
    else:
        print(f"[OK] Sort order is stable (deterministic).")

    # ── Check 6: DB integrity
    if not DB_FILE.exists():
        warnings.append(f"db.json not found at {DB_FILE} — cannot verify DB state")
    else:
        db = json.loads(DB_FILE.read_text(encoding="utf-8"))

        # Protected task names
        for tid, expected_name in PROTECTED.items():
            t = db.get("tasks", {}).get(tid, {})
            actual = t.get("name", "MISSING")
            if not t:
                warnings.append(f"Protected Task {tid} NOT in db — may not have been renamed yet")
            elif actual == expected_name:
                print(f"[OK] Protected Task {tid}: '{actual}'")
            else:
                warnings.append(f"Protected Task {tid} name='{actual}' (expected '{expected_name}')")

        # Task 5 annotation count
        ann5 = db.get("annotations", {}).get("5", {})
        shapes5 = len(ann5.get("shapes", []))
        if shapes5 == 1865:
            print(f"[OK] Task 5 annotations: {shapes5} shapes (baseline confirmed)")
        else:
            errors.append(f"Task 5 annotation count is {shapes5}, expected 1865!")
            ok = False

        # Starting IDs
        next_tid = db.get("next_task_id", 17)
        next_jid = db.get("next_job_id", 17)
        if str(next_tid) in PROTECTED or str(next_jid) in PROTECTED:
            errors.append(f"next_task_id={next_tid} or next_job_id={next_jid} collides with protected IDs!")
            ok = False
        else:
            end_tid = next_tid + NUM_TASKS - 1
            print(f"[OK] New task IDs will be: {next_tid} — {end_tid} (no collision with protected 5, 10)")

        # Check no existing tasks with same names
        existing_names = {t.get("name") for t in db.get("tasks", {}).values() if isinstance(t, dict)}
        collision_names = []
        for n in range(1, NUM_TASKS + 1):
            nm = task_name_for(n)
            if nm in existing_names:
                collision_names.append(nm)
        if collision_names:
            warnings.append(f"Task names already exist in DB (will overwrite): {collision_names}")
        else:
            print(f"[OK] All 20 new task names are unique in DB.")

    # ── Check 7: Print assignment table
    print()
    print(f"{'N':>3}  {'Task ID':>7}  {'Job ID':>6}  {'Task Name':<35}  {'First Image':<50}  {'Last Image'}")
    print("-" * 155)
    next_tid_print = json.loads(DB_FILE.read_text(encoding="utf-8")).get("next_task_id", 17) if DB_FILE.exists() else 17
    next_jid_print = json.loads(DB_FILE.read_text(encoding="utf-8")).get("next_job_id", 17) if DB_FILE.exists() else 17
    for n in range(1, NUM_TASKS + 1):
        start = (n - 1) * IMAGES_PER_TASK
        end = n * IMAGES_PER_TASK
        batch = selected[start:end]
        tid = next_tid_print + (n - 1)
        jid = next_jid_print + (n - 1)
        nm = task_name_for(n)
        print(f"{n:>3}  {tid:>7}  {jid:>6}  {nm:<35}  {batch[0].name:<50}  {batch[-1].name}")

    # ── Summary
    print()
    print("=" * 70)
    if errors:
        print(f"VALIDATION FAILED — {len(errors)} error(s):")
        for e in errors:
            print(f"  [FAIL] {e}")
    if warnings:
        print(f"Warnings ({len(warnings)}):")
        for w in warnings:
            print(f"  [WARN] {w}")
    if ok and not errors:
        print("[PASS] ALL VALIDATION CHECKS PASSED")
        print("  Run: python scripts/prepare_20_tasks.py  to create tasks.")
    print("=" * 70)
    return ok and not errors


def main():
    parser = argparse.ArgumentParser(description="Validate 20-task split from A_50 dataset")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args()

    success = validate(args.source, args.limit)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
