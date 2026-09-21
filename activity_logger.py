# Copyright (C) CVAT.ai Corporation & ROOTS Industrial Defect Annotation Platform
# SPDX-License-Identifier: MIT

"""
Persistent Activity & Audit Logging Service for Multi-User CVAT Deployment.
Supports both Google Drive cloud storage (ROOT/activity/activity-YYYY-MM.jsonl)
and local development caching.

Provides:
- Thread-safe append-only logging
- Granular event tracking:
  LOGIN, LOGOUT, TASK_CREATED, TASK_UPDATED, TASK_DELETED,
  JOB_CREATED, LABEL_CREATED, LABEL_UPDATED, LABEL_DELETED,
  ANNOTATION_CREATED, ANNOTATION_UPDATED, ANNOTATION_DELETED,
  AUTOSAVE_CHECKPOINT, DATASET_UPLOAD, DATASET_EXPORT,
  AI_SEGMENTATION, MODEL_CHANGED, LOGIN_FAILURE, DRIVE_ERROR, OAUTH_ERROR
- Every event records:
  id, timestamp, google_sub, email, role, action, resource_type,
  resource_id, task_id, job_id, ip, user_agent, status, details
- Multi-user RBAC filtering (Admins view platform, normal Users view only self)
- CSV and JSON report exports
"""

import os
import json
import csv
import io
import time
import uuid
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List, Any

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "local_server_data"
ACTIVITY_LOG_FILE = DATA_DIR / "activity.jsonl"

_lock = threading.Lock()
_activity_cache: List[dict] = []
_cloud_store = None


def set_cloud_store(store):
    """Optionally bind GoogleDrivePersistenceStore for direct cloud activity logging."""
    global _cloud_store
    _cloud_store = store


def _ensure_loaded():
    global _activity_cache
    if not _activity_cache and ACTIVITY_LOG_FILE.exists():
        try:
            entries = []
            with open(ACTIVITY_LOG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except Exception:
                            pass
            _activity_cache = entries
        except Exception as e:
            print(f"[-] Error loading local activity logs: {e}")


def log_activity(
    user=None,
    action: str = "UNKNOWN",
    resource_type: Optional[str] = None,
    resource_id: Optional[Any] = None,
    task_id: Optional[Any] = None,
    job_id: Optional[Any] = None,
    project_id: Optional[Any] = None,
    frame: Optional[int] = None,
    count: int = 1,
    label_name: Optional[str] = None,
    label_id: Optional[Any] = None,
    details: Optional[Any] = None,
    status: str = "success",
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict:
    """
    Records an activity entry persistently to memory, Google Drive (if active), and local JSONL.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    google_sub = user.get("google_sub") if user else None
    email = user.get("email") if user else ""
    role = user.get("role", "USER") if user else "USER"
    username = user.get("username") if user else "anonymous"
    user_id = user.get("id") if user else None

    # Derive resource_type if not explicitly passed
    if not resource_type:
        if task_id:
            resource_type = "task"
        elif job_id:
            resource_type = "job"
        elif label_id:
            resource_type = "label"
        elif "ANNOTATION" in action:
            resource_type = "annotation"
        elif "AUTH" in action or "LOGIN" in action:
            resource_type = "session"
        else:
            resource_type = "system"

    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": now_iso,
        "google_sub": google_sub,
        "email": email,
        "role": role,
        "user_id": user_id,
        "username": username,
        "action": action,
        "resource_type": resource_type,
        "resource_id": str(resource_id or task_id or job_id or label_id or ""),
        "task_id": task_id,
        "job_id": job_id,
        "project_id": project_id,
        "frame": frame,
        "count": count,
        "label_name": label_name,
        "label_id": label_id,
        "status": status,
        "ip": ip or "",
        "user_agent": user_agent or "",
        "details": details if isinstance(details, dict) else {"message": str(details or "")},
    }

    with _lock:
        _ensure_loaded()
        _activity_cache.append(entry)

        # 1. Sync to Google Drive cloud storage if active
        if _cloud_store and _cloud_store.is_configured():
            try:
                _cloud_store.append_activity(entry)
            except Exception as e:
                print(f"[-] Warning: Failed appending activity to Drive: {e}")

        # 2. Local append fallback
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(ACTIVITY_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            print(f"[-] Warning: Failed appending activity locally: {e}")

    return entry


def get_activities(
    current_user,
    user_id=None,
    task_id=None,
    project_id=None,
    job_id=None,
    action=None,
    date_from=None,
    date_to=None,
    limit=50,
    offset=0
) -> dict:
    """
    Retrieves filtered activities.
    Security: Normal users can ONLY view their own activities.
    """
    with _lock:
        _ensure_loaded()
        records = list(_activity_cache)

    is_admin = current_user and (
        current_user.get("role") == "ADMIN" or
        current_user.get("is_superuser") or
        "admin" in current_user.get("groups", [])
    )

    filtered = []
    for r in reversed(records):
        # RBAC check
        if not is_admin:
            if current_user and str(r.get("user_id")) != str(current_user.get("id")):
                continue
            if not current_user:
                continue
        elif user_id is not None:
            if str(r.get("user_id")) != str(user_id):
                continue

        if task_id is not None and str(r.get("task_id")) != str(task_id):
            continue
        if project_id is not None and str(r.get("project_id")) != str(project_id):
            continue
        if job_id is not None and str(r.get("job_id")) != str(job_id):
            continue
        if action and r.get("action") != action:
            continue
        if date_from and r.get("timestamp", "") < date_from:
            continue
        if date_to and r.get("timestamp", "") > date_to:
            continue

        filtered.append(r)

    total_count = len(filtered)
    paged = filtered[offset : offset + limit]

    return {
        "count": total_count,
        "results": paged,
        "limit": limit,
        "offset": offset
    }


def get_activity_summary(current_user) -> dict:
    """Aggregates metrics for Activity Dashboard."""
    with _lock:
        _ensure_loaded()
        records = list(_activity_cache)

    is_admin = current_user and (
        current_user.get("role") == "ADMIN" or
        current_user.get("is_superuser") or
        "admin" in current_user.get("groups", [])
    )

    if not is_admin:
        records = [r for r in records if current_user and str(r.get("user_id")) == str(current_user.get("id"))]

    users_seen = set()
    tasks_seen = set()
    actions_count = {
        "annotations_created": 0,
        "annotations_modified": 0,
        "annotations_deleted": 0,
        "ai_segment_operations": 0,
        "datasets_uploaded": 0,
        "exports_count": 0,
    }

    recent_cutoff = datetime.now(timezone.utc).timestamp() - (24 * 3600)
    active_users_24h = set()

    for r in records:
        uid = r.get("user_id")
        if uid:
            users_seen.add(uid)
            try:
                ts_str = r.get("timestamp", "").replace("Z", "+00:00")
                ts = datetime.fromisoformat(ts_str).timestamp()
                if ts >= recent_cutoff:
                    active_users_24h.add(uid)
            except Exception:
                pass

        tid = r.get("task_id")
        if tid:
            tasks_seen.add(tid)

        act = r.get("action", "")
        cnt = r.get("count", 1) or 1
        if act in ("ANNOTATION_CREATE", "ANNOTATION_CREATED"):
            actions_count["annotations_created"] += cnt
        elif act in ("ANNOTATION_UPDATE", "ANNOTATION_UPDATED"):
            actions_count["annotations_modified"] += cnt
        elif act in ("ANNOTATION_DELETE", "ANNOTATION_DELETED", "BULK_ANNOTATION_DELETE"):
            actions_count["annotations_deleted"] += cnt
        elif act in ("AI_SEGMENT", "SEGMENT_WHOLE", "AI_SEGMENTATION"):
            actions_count["ai_segment_operations"] += cnt
        elif act == "DATASET_UPLOAD":
            actions_count["datasets_uploaded"] += 1
        elif act in ("EXPORT_START", "EXPORT_COMPLETE", "DATASET_EXPORT"):
            actions_count["exports_count"] += 1

    return {
        "is_admin": is_admin,
        "total_users": len(users_seen),
        "active_users_24h": len(active_users_24h),
        "tasks_worked_on": len(tasks_seen),
        "annotations_created": actions_count["annotations_created"],
        "annotations_modified": actions_count["annotations_modified"],
        "annotations_deleted": actions_count["annotations_deleted"],
        "ai_segment_operations": actions_count["ai_segment_operations"],
        "datasets_uploaded": actions_count["datasets_uploaded"],
        "exports_count": actions_count["exports_count"],
        "total_events": len(records),
    }


def export_activities_csv(current_user, **kwargs) -> str:
    """Generates CSV string of filtered activities."""
    res = get_activities(current_user, limit=100000, offset=0, **kwargs)
    rows = res["results"]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "timestamp",
        "email",
        "google_sub",
        "role",
        "action",
        "resource_type",
        "resource_id",
        "task_id",
        "job_id",
        "status",
        "details"
    ])

    for r in rows:
        writer.writerow([
            r.get("timestamp", ""),
            r.get("email", "") or r.get("username", ""),
            r.get("google_sub", ""),
            r.get("role", "USER"),
            r.get("action", ""),
            r.get("resource_type", ""),
            r.get("resource_id", ""),
            r.get("task_id", "") or "",
            r.get("job_id", "") or "",
            r.get("status", "success"),
            json.dumps(r.get("details", {}))
        ])

    return output.getvalue()
