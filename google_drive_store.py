# Copyright (C) CVAT.ai Corporation & ROOTS Industrial Defect Annotation Platform
# SPDX-License-Identifier: MIT

"""
Authoritative Google Drive Persistence Store for ROOTS Platform.
Folder Root: 1NRmlelgPqA61sEpK6AyyYg_eSIE-LdZD (My Drive / Shared Drive)

Provides:
- Task-scoped and job-scoped persistent cloud storage
- Strict 503 CLOUD_STORAGE_UNAVAILABLE on failure in production (NO silent fallback)
- Optimistic concurrency control (revision verification, 409 Conflict)
- Persistent Drive file/folder ID indexing (zero redundant searches)
- Direct memory-to-Drive streaming (avoids disk dependence)
- Structured activity logging and autosave checkpointing to Drive
"""

import os
import io
import re
import json
import time
import uuid
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from drive_index import DriveIndex

GOOGLE_DRIVE_ROOT_FOLDER_ID = os.environ.get(
    "GOOGLE_DRIVE_ROOT_FOLDER_ID",
    "1NRmlelgPqA61sEpK6AyyYg_eSIE-LdZD"
).strip()

PERSISTENCE_BACKEND = os.environ.get("PERSISTENCE_BACKEND", "local").strip().lower()

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload, MediaFileUpload
    from googleapiclient.errors import HttpError
    from google.oauth2 import service_account
    from google.oauth2.credentials import Credentials
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False


class CloudStorageUnavailableError(Exception):
    """Raised when cloud storage is unreachable or unconfigured in production mode."""
    def __init__(self, message: str = "Google Drive cloud storage is unavailable."):
        super().__init__(message)
        self.status_code = 503
        self.error_code = "CLOUD_STORAGE_UNAVAILABLE"


class DocumentConflictError(Exception):
    """Raised when an optimistic concurrency conflict is detected."""
    def __init__(self, message: str = "Revision conflict detected."):
        super().__init__(message)
        self.status_code = 409
        self.error_code = "DOCUMENT_CONFLICT"


def sanitize_folder_name(name: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_\-]', '_', str(name))[:50]


class GoogleDrivePersistenceStore:
    """
    Authoritative Persistence Store backed by Google Drive.
    Implements all required application persistence operations.
    """

    def __init__(self, root_folder_id: Optional[str] = None):
        self.root_folder_id = root_folder_id or GOOGLE_DRIVE_ROOT_FOLDER_ID
        self.service = None
        self.index = DriveIndex()
        self._lock = threading.RLock()
        self._init_service()

    def _init_service(self):
        if not GOOGLE_API_AVAILABLE:
            return

        creds = None

        # 1. Priority for My Drive: OAuth User Credentials (carries personal storage quota)
        token_path = os.environ.get("GOOGLE_OAUTH_TOKEN_PATH") or "token.json"
        token_file = Path(__file__).resolve().parent / token_path
        if token_file.exists():
            try:
                with open(token_file, "r", encoding="utf-8") as f:
                    token_info = json.load(f)
                creds = Credentials.from_authorized_user_info(
                    token_info, scopes=["https://www.googleapis.com/auth/drive"]
                )
                print(f"[+] Loaded OAuth User Credentials from: {token_file.name}")
            except Exception as e:
                print(f"[-] Failed loading OAuth token from {token_file}: {e}")

        if not creds:
            token_json = os.environ.get("GOOGLE_OAUTH_TOKEN_JSON")
            if token_json:
                try:
                    token_info = json.loads(token_json)
                    creds = Credentials.from_authorized_user_info(
                        token_info, scopes=["https://www.googleapis.com/auth/drive"]
                    )
                    print("[+] Loaded OAuth User Credentials from GOOGLE_OAUTH_TOKEN_JSON.")
                except Exception as e:
                    print(f"[-] Failed loading OAuth token: {e}")

        # 2. Priority for Shared Drives: Service Account
        if not creds:
            sa_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get("GOOGLE_SERVICE_ACCOUNT_PATH")
            if not sa_path:
                local_sa = Path(__file__).resolve().parent / "google-service-account.json"
                if local_sa.exists():
                    sa_path = str(local_sa)

            sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

            if sa_json:
                try:
                    info = json.loads(sa_json)
                    creds = service_account.Credentials.from_service_account_info(
                        info, scopes=["https://www.googleapis.com/auth/drive"]
                    )
                except Exception as e:
                    print(f"[-] Failed loading credentials from GOOGLE_SERVICE_ACCOUNT_JSON: {e}")
            elif sa_path and Path(sa_path).exists():
                try:
                    creds = service_account.Credentials.from_service_account_file(
                        sa_path, scopes=["https://www.googleapis.com/auth/drive"]
                    )
                    print(f"[+] Loaded Service Account credentials from: {sa_path}")
                except Exception as e:
                    print(f"[-] Failed loading credentials from {sa_path}: {e}")

        # 3. Fallback: Application Default Credentials (ADC)
        if not creds:
            try:
                import google.auth
                creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/drive"])
                print("[+] Loaded Google Application Default Credentials (ADC).")
            except Exception as e:
                pass

        if creds:
            try:
                self.service = build("drive", "v3", credentials=creds, cache_discovery=False)
                print("[+] GoogleDrivePersistenceStore: API client initialized.")
            except Exception as e:
                print(f"[-] Failed to build Google Drive client: {e}")

    def is_configured(self) -> bool:
        return self.service is not None

    def _ensure_connected(self):
        if not self.service:
            raise CloudStorageUnavailableError(
                "Google Drive service is not configured. Google credentials are missing or invalid."
            )

    # -------------------------------------------------------------------------
    # Core Drive Folder & File Operations (Direct Memory Stream)
    # -------------------------------------------------------------------------

    def get_or_create_folder(self, folder_name: str, parent_id: str, index_key: Optional[str] = None) -> str:
        """Idempotently creates/retrieves a folder using DriveIndex cache."""
        self._ensure_connected()
        with self._lock:
            if index_key:
                cached_id = self.index.get_folder_id(index_key)
                if cached_id:
                    return cached_id

            safe_name = folder_name.replace("'", "\\'")
            query = (
                f"name = '{safe_name}' and "
                f"'{parent_id}' in parents and "
                f"mimeType = 'application/vnd.google-apps.folder' and "
                f"trashed = false"
            )

            try:
                res = self.service.files().list(
                    q=query,
                    fields="files(id, name)",
                    spaces="drive",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True
                ).execute()

                files = res.get("files", [])
                if files:
                    fid = files[0]["id"]
                    if index_key:
                        self.index.set_folder_id(index_key, fid)
                    return fid

                file_metadata = {
                    "name": folder_name,
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": [parent_id]
                }
                folder = self.service.files().create(
                    body=file_metadata,
                    fields="id",
                    supportsAllDrives=True
                ).execute()

                fid = folder.get("id")
                if index_key:
                    self.index.set_folder_id(index_key, fid)
                return fid
            except Exception as e:
                raise CloudStorageUnavailableError(f"Failed to access folder '{folder_name}' in Drive: {e}")

    def read_json_file(self, file_id: str) -> dict:
        """Reads a JSON file from Drive into memory."""
        self._ensure_connected()
        try:
            req = self.service.files().get_media(fileId=file_id, supportsAllDrives=True)
            bio = io.BytesIO()
            downloader = MediaIoBaseDownload(bio, req)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            bio.seek(0)
            return json.loads(bio.read().decode("utf-8"))
        except Exception as e:
            raise CloudStorageUnavailableError(f"Failed reading Drive file {file_id}: {e}")

    def write_json_file(
        self,
        filename: str,
        parent_id: str,
        data: Any,
        file_id: Optional[str] = None,
        index_key: Optional[str] = None
    ) -> str:
        """Writes in-memory JSON data to Drive (create or update)."""
        self._ensure_connected()
        with self._lock:
            try:
                payload_bytes = json.dumps(data, indent=2).encode("utf-8")
                media = MediaIoBaseUpload(
                    io.BytesIO(payload_bytes),
                    mimetype="application/json",
                    resumable=False
                )

                target_file_id = file_id or (self.index.get_file_id(index_key) if index_key else None)

                if target_file_id:
                    # Update existing file
                    updated = self.service.files().update(
                        fileId=target_file_id,
                        media_body=media,
                        fields="id",
                        supportsAllDrives=True
                    ).execute()
                    fid = updated.get("id")
                else:
                    # Create new file
                    metadata = {
                        "name": filename,
                        "parents": [parent_id],
                        "mimeType": "application/json"
                    }
                    created = self.service.files().create(
                        body=metadata,
                        media_body=media,
                        fields="id",
                        supportsAllDrives=True
                    ).execute()
                    fid = created.get("id")

                if index_key:
                    self.index.set_file_id(index_key, fid)

                return fid
            except Exception as e:
                raise CloudStorageUnavailableError(f"Failed writing '{filename}' to Drive: {e}")

    # -------------------------------------------------------------------------
    # Hierarchy & System Initialization
    # -------------------------------------------------------------------------

    def init_drive_hierarchy(self) -> Dict[str, str]:
        """Ensures the standard system/activity/tasks/models hierarchy exists."""
        self._ensure_connected()
        with self._lock:
            sys_id = self.get_or_create_folder("system", self.root_folder_id, "folder_system")
            users_id = self.get_or_create_folder("users", sys_id, "folder_users")
            sess_id = self.get_or_create_folder("sessions", sys_id, "folder_sessions")
            act_id = self.get_or_create_folder("activity", self.root_folder_id, "folder_activity")
            tasks_id = self.get_or_create_folder("tasks", self.root_folder_id, "folder_tasks")
            models_id = self.get_or_create_folder("models", self.root_folder_id, "folder_models")

            # Try loading existing drive_index.json
            idx_file_id = self.find_file_in_folder("drive_index.json", sys_id)
            if idx_file_id:
                self.index.set_file_id("file_drive_index", idx_file_id)
                try:
                    loaded_idx = self.read_json_file(idx_file_id)
                    self.index.load_from_dict(loaded_idx)
                except Exception as e:
                    print(f"[-] Warning loading drive_index.json: {e}")

            return {
                "system": sys_id,
                "users": users_id,
                "sessions": sess_id,
                "activity": act_id,
                "tasks": tasks_id,
                "models": models_id,
            }

    def sync_drive_index(self):
        """Persists the in-memory DriveIndex to ROOT/system/drive_index.json."""
        if not self.service:
            return
        with self._lock:
            sys_id = self.index.get_folder_id("folder_system")
            if not sys_id:
                return
            self.index.index["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.index.index["revision"] += 1
            self.write_json_file(
                "drive_index.json",
                sys_id,
                self.index.to_dict(),
                index_key="file_drive_index"
            )

    def find_file_in_folder(self, filename: str, folder_id: str) -> Optional[str]:
        """Finds a file ID by name in folder_id."""
        self._ensure_connected()
        safe_name = filename.replace("'", "\\'")
        query = (
            f"name = '{safe_name}' and "
            f"'{folder_id}' in parents and "
            f"trashed = false"
        )
        res = self.service.files().list(
            q=query,
            fields="files(id, name)",
            spaces="drive",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        files = res.get("files", [])
        return files[0]["id"] if files else None

    # -------------------------------------------------------------------------
    # Optimistic Concurrency Document Envelope
    # -------------------------------------------------------------------------

    def _wrap_document(self, data: Any, revision: int = 1, updated_by: Optional[str] = None) -> dict:
        return {
            "schema_version": 1,
            "revision": revision,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": updated_by or "system",
            "data": data,
        }

    def _check_and_increment_revision(
        self,
        current_envelope: Optional[dict],
        expected_revision: Optional[int],
        updated_by: Optional[str] = None,
        new_data: Any = None
    ) -> dict:
        current_rev = current_envelope.get("revision", 1) if current_envelope else 0
        if expected_revision is not None and expected_revision != current_rev:
            raise DocumentConflictError(
                f"Document modified concurrently. Current revision: {current_rev}, expected: {expected_revision}"
            )
        return self._wrap_document(new_data, revision=current_rev + 1, updated_by=updated_by)

    # -------------------------------------------------------------------------
    # Application State Operations (get_state, save_state)
    # -------------------------------------------------------------------------

    def get_state(self) -> dict:
        """Retrieves global application state from system/app_state.json."""
        self._ensure_connected()
        file_id = self.index.get_file_id("file_app_state")
        if not file_id:
            sys_id = self.index.get_folder_id("folder_system") or self.get_or_create_folder("system", self.root_folder_id)
            file_id = self.find_file_in_folder("app_state.json", sys_id)
            if file_id:
                self.index.set_file_id("file_app_state", file_id)

        if not file_id:
            # Default fresh state
            return {
                "schema_version": 1,
                "revision": 1,
                "data": {
                    "next_task_id": 1,
                    "next_job_id": 1,
                    "next_label_id": 1,
                    "next_user_id": 2,
                    "active_tasks": [],
                }
            }

        return self.read_json_file(file_id)

    def save_state(self, state_dict: dict, expected_revision: Optional[int] = None, updated_by: Optional[str] = None) -> dict:
        """Saves global application state to system/app_state.json with optimistic locking."""
        self._ensure_connected()
        with self._lock:
            sys_id = self.index.get_folder_id("folder_system") or self.get_or_create_folder("system", self.root_folder_id, "folder_system")
            current = self.get_state()
            new_envelope = self._check_and_increment_revision(current, expected_revision, updated_by, state_dict)
            fid = self.write_json_file("app_state.json", sys_id, new_envelope, index_key="file_app_state")
            self.sync_drive_index()
            return new_envelope

    def get_users(self) -> dict:
        """Retrieves users dictionary from users/users.json."""
        self._ensure_connected()
        file_id = self.index.get_file_id("file_users")
        if not file_id:
            users_fid = self.index.get_folder_id("folder_users") or self.get_or_create_folder("users", self.root_folder_id, "folder_users")
            file_id = self.find_file_in_folder("users.json", users_fid)
            if file_id:
                self.index.set_file_id("file_users", file_id)
        if not file_id:
            return {}
        envelope = self.read_json_file(file_id)
        return envelope.get("data", envelope)

    def save_users(self, users_dict: dict, expected_revision: Optional[int] = None, updated_by: Optional[str] = None) -> dict:
        """Saves users dictionary to users/users.json with optimistic locking."""
        self._ensure_connected()
        with self._lock:
            users_fid = self.index.get_folder_id("folder_users") or self.get_or_create_folder("users", self.root_folder_id, "folder_users")
            file_id = self.index.get_file_id("file_users")
            current = self.read_json_file(file_id) if file_id else None
            new_envelope = self._check_and_increment_revision(current, expected_revision, updated_by, users_dict)
            self.write_json_file("users.json", users_fid, new_envelope, file_id=file_id, index_key="file_users")
            self.sync_drive_index()
            return new_envelope

    # -------------------------------------------------------------------------
    # Task Operations (get_task, save_task, delete_task, list_tasks, create_task)
    # -------------------------------------------------------------------------

    def _ensure_task_folders(self, task_id: int, task_name: str) -> Dict[str, str]:
        """Idempotently ensures the task folder tree exists on Drive."""
        tasks_root = self.index.get_folder_id("folder_tasks") or self.get_or_create_folder("tasks", self.root_folder_id, "folder_tasks")
        clean_name = sanitize_folder_name(task_name)
        folder_name = f"task_{task_id}_{clean_name}"

        t_fid = self.get_or_create_folder(folder_name, tasks_root, f"task_{task_id}")
        m_fid = self.get_or_create_folder("metadata", t_fid, f"task_{task_id}_metadata")
        s_fid = self.get_or_create_folder("source", t_fid, f"task_{task_id}_source")
        a_fid = self.get_or_create_folder("annotations", t_fid, f"task_{task_id}_annotations")
        c_fid = self.get_or_create_folder("checkpoints", a_fid, f"task_{task_id}_checkpoints")
        e_fid = self.get_or_create_folder("exports", t_fid, f"task_{task_id}_exports")

        return {
            "task": t_fid,
            "metadata": m_fid,
            "source": s_fid,
            "annotations": a_fid,
            "checkpoints": c_fid,
            "exports": e_fid,
        }

    def get_task(self, task_id: int) -> Optional[dict]:
        """Retrieves task metadata envelope from tasks/task_<id>_<name>/metadata/task.json."""
        self._ensure_connected()
        file_id = self.index.get_file_id(f"task_{task_id}_meta")
        if not file_id:
            m_fid = self.index.get_folder_id(f"task_{task_id}_metadata")
            if m_fid:
                file_id = self.find_file_in_folder("task.json", m_fid)
                if file_id:
                    self.index.set_file_id(f"task_{task_id}_meta", file_id)

        if not file_id:
            return None

        envelope = self.read_json_file(file_id)
        return envelope.get("data", envelope)

    def save_task(
        self,
        task_id: int,
        task_data: dict,
        expected_revision: Optional[int] = None,
        updated_by: Optional[str] = None
    ) -> dict:
        """Saves task metadata to Drive under metadata/task.json with optimistic locking."""
        self._ensure_connected()
        with self._lock:
            folders = self._ensure_task_folders(task_id, task_data.get("name", f"task_{task_id}"))
            m_fid = folders["metadata"]

            file_id = self.index.get_file_id(f"task_{task_id}_meta")
            current_envelope = self.read_json_file(file_id) if file_id else None

            new_envelope = self._check_and_increment_revision(
                current_envelope, expected_revision, updated_by, task_data
            )
            self.write_json_file("task.json", m_fid, new_envelope, index_key=f"task_{task_id}_meta")
            self.sync_drive_index()
            return new_envelope

    def delete_task(self, task_id: int) -> bool:
        """Permanently trashes the task folder in Google Drive."""
        self._ensure_connected()
        with self._lock:
            t_fid = self.index.get_folder_id(f"task_{task_id}")
            if not t_fid:
                tasks_root = self.index.get_folder_id("folder_tasks") or self.get_or_create_folder("tasks", self.root_folder_id)
                res = self.service.files().list(
                    q=f"name contains 'task_{task_id}_' and '{tasks_root}' in parents and trashed = false",
                    fields="files(id)",
                    supportsAllDrives=True
                ).execute()
                files = res.get("files", [])
                if files:
                    t_fid = files[0]["id"]

            if t_fid:
                self.service.files().delete(fileId=t_fid, supportsAllDrives=True).execute()
                self.index.remove_key(f"task_{task_id}")
                self.index.remove_key(f"task_{task_id}_meta")
                self.index.remove_key(f"task_{task_id}_labels")
                self.index.remove_key(f"task_{task_id}_annotations")
                self.sync_drive_index()
                return True
            return False

    def list_tasks(self) -> List[dict]:
        """Lists all tasks persisted in Google Drive."""
        self._ensure_connected()
        tasks_root = self.index.get_folder_id("folder_tasks") or self.get_or_create_folder("tasks", self.root_folder_id)
        res = self.service.files().list(
            q=f"'{tasks_root}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
            fields="files(id, name)",
            spaces="drive",
            supportsAllDrives=True,
            pageSize=100
        ).execute()

        tasks = []
        for f in res.get("files", []):
            name = f.get("name", "")
            if name.startswith("task_"):
                parts = name.split("_")
                if len(parts) >= 2 and parts[1].isdigit():
                    tid = int(parts[1])
                    t_data = self.get_task(tid)
                    if t_data:
                        tasks.append(t_data)
        return sorted(tasks, key=lambda x: x.get("id", 0))

    def create_task(self, task_data: dict, labels: Optional[List[dict]] = None, user_id: Optional[int] = None) -> dict:
        """Creates a new task and writes initial metadata and labels to Drive."""
        self._ensure_connected()
        with self._lock:
            state_envelope = self.get_state()
            state = state_envelope.get("data", state_envelope)
            new_id = state.get("next_task_id", 1)
            state["next_task_id"] = new_id + 1
            if "active_tasks" not in state:
                state["active_tasks"] = []
            state["active_tasks"].append(new_id)

            task_data["id"] = new_id
            self.save_state(state, expected_revision=state_envelope.get("revision"))

            # Save task metadata
            self.save_task(new_id, task_data, updated_by=f"user_{user_id}")

            # Save labels if provided
            if labels is not None:
                self.save_labels(new_id, labels, updated_by=f"user_{user_id}")

            return task_data

    def update_task(self, task_id: int, task_data: dict, expected_revision: Optional[int] = None, updated_by: Optional[str] = None) -> dict:
        return self.save_task(task_id, task_data, expected_revision=expected_revision, updated_by=updated_by)

    # -------------------------------------------------------------------------
    # Label Operations (get_labels, save_labels)
    # -------------------------------------------------------------------------

    def get_labels(self, task_id: int) -> List[dict]:
        """Retrieves dynamic labels for a task from metadata/labels.json."""
        self._ensure_connected()
        file_id = self.index.get_file_id(f"task_{task_id}_labels")
        if not file_id:
            m_fid = self.index.get_folder_id(f"task_{task_id}_metadata")
            if m_fid:
                file_id = self.find_file_in_folder("labels.json", m_fid)
                if file_id:
                    self.index.set_file_id(f"task_{task_id}_labels", file_id)

        if not file_id:
            return []

        envelope = self.read_json_file(file_id)
        return envelope.get("data", envelope)

    def save_labels(
        self,
        task_id: int,
        labels: List[dict],
        expected_revision: Optional[int] = None,
        updated_by: Optional[str] = None
    ) -> dict:
        """Saves dynamic labels to Drive under metadata/labels.json."""
        self._ensure_connected()
        with self._lock:
            folders = self._ensure_task_folders(task_id, f"task_{task_id}")
            m_fid = folders["metadata"]

            file_id = self.index.get_file_id(f"task_{task_id}_labels")
            current_envelope = self.read_json_file(file_id) if file_id else None

            new_envelope = self._check_and_increment_revision(
                current_envelope, expected_revision, updated_by, labels
            )
            self.write_json_file("labels.json", m_fid, new_envelope, index_key=f"task_{task_id}_labels")
            self.sync_drive_index()
            return new_envelope

    # -------------------------------------------------------------------------
    # Annotation Operations (get_job_annotations, save_job_annotations, checkpoints)
    # -------------------------------------------------------------------------

    def get_job_annotations(self, job_id: int, task_id: Optional[int] = None) -> dict:
        """Retrieves job annotations from Drive annotations/job_<jid>.json."""
        self._ensure_connected()
        file_id = self.index.get_file_id(f"job_{job_id}_annotations")

        if not file_id and task_id:
            a_fid = self.index.get_folder_id(f"task_{task_id}_annotations")
            if a_fid:
                file_id = self.find_file_in_folder(f"job_{job_id}.json", a_fid)
                if file_id:
                    self.index.set_file_id(f"job_{job_id}_annotations", file_id)

        if not file_id:
            return {"version": 0, "tags": [], "shapes": [], "tracks": []}

        envelope = self.read_json_file(file_id)
        return envelope.get("data", envelope)

    def save_job_annotations(
        self,
        job_id: int,
        annotations: dict,
        task_id: Optional[int] = None,
        expected_revision: Optional[int] = None,
        updated_by: Optional[str] = None
    ) -> dict:
        """Saves annotations to Drive under annotations/job_<jid>.json with optimistic locking."""
        self._ensure_connected()
        with self._lock:
            tid = task_id or job_id
            folders = self._ensure_task_folders(tid, f"task_{tid}")
            a_fid = folders["annotations"]

            file_id = self.index.get_file_id(f"job_{job_id}_annotations")
            current_envelope = self.read_json_file(file_id) if file_id else None

            new_envelope = self._check_and_increment_revision(
                current_envelope, expected_revision, updated_by, annotations
            )
            self.write_json_file(
                f"job_{job_id}.json",
                a_fid,
                new_envelope,
                index_key=f"job_{job_id}_annotations"
            )
            self.sync_drive_index()
            return new_envelope

    def save_checkpoint(
        self,
        job_id: int,
        checkpoint_data: dict,
        task_id: Optional[int] = None,
        updated_by: Optional[str] = None
    ) -> str:
        """Saves an immutable autosave checkpoint to tasks/task_<id>/annotations/checkpoints/."""
        self._ensure_connected()
        with self._lock:
            tid = task_id or job_id
            folders = self._ensure_task_folders(tid, f"task_{tid}")
            c_fid = folders["checkpoints"]

            timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            cp_filename = f"checkpoint_job_{job_id}_{timestamp_str}.json"

            envelope = self._wrap_document(checkpoint_data, revision=1, updated_by=updated_by)
            fid = self.write_json_file(cp_filename, c_fid, envelope)
            return fid

    def load_checkpoints(self, job_id: int, task_id: Optional[int] = None, limit: int = 10) -> List[dict]:
        """Lists recent autosave checkpoints from Drive."""
        self._ensure_connected()
        tid = task_id or job_id
        folders = self._ensure_task_folders(tid, f"task_{tid}")
        c_fid = folders["checkpoints"]

        res = self.service.files().list(
            q=f"'{c_fid}' in parents and name contains 'checkpoint_job_{job_id}_' and trashed = false",
            fields="files(id, name, createdTime)",
            orderBy="createdTime desc",
            pageSize=limit,
            supportsAllDrives=True
        ).execute()

        checkpoints = []
        for f in res.get("files", []):
            checkpoints.append({
                "file_id": f["id"],
                "filename": f["name"],
                "created_time": f.get("createdTime"),
            })
        return checkpoints

    # -------------------------------------------------------------------------
    # Activity & Audit Operations (append_activity, read_activity)
    # -------------------------------------------------------------------------

    def append_activity(self, event_dict: dict) -> str:
        """
        Appends an activity event into Google Drive activity log.
        Stored monthly as ROOT/activity/activity-YYYY-MM.jsonl.
        """
        self._ensure_connected()
        with self._lock:
            act_fid = self.index.get_folder_id("folder_activity") or self.get_or_create_folder("activity", self.root_folder_id, "folder_activity")
            month_str = datetime.now(timezone.utc).strftime("%Y-%m")
            filename = f"activity-{month_str}.jsonl"

            file_id = self.index.get_file_id(f"activity_{month_str}")
            if not file_id:
                file_id = self.find_file_in_folder(filename, act_fid)
                if file_id:
                    self.index.set_file_id(f"activity_{month_str}", file_id)

            line_str = json.dumps(event_dict) + "\n"
            line_bytes = line_str.encode("utf-8")

            if file_id:
                # Download existing content, append new line, and update
                req = self.service.files().get_media(fileId=file_id, supportsAllDrives=True)
                bio = io.BytesIO()
                downloader = MediaIoBaseDownload(bio, req)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                bio.write(line_bytes)
                bio.seek(0)

                media = MediaIoBaseUpload(bio, mimetype="application/x-ndjson", resumable=False)
                self.service.files().update(
                    fileId=file_id,
                    media_body=media,
                    supportsAllDrives=True
                ).execute()
                fid = file_id
            else:
                # Create initial month file
                bio = io.BytesIO(line_bytes)
                media = MediaIoBaseUpload(bio, mimetype="application/x-ndjson", resumable=False)
                created = self.service.files().create(
                    body={"name": filename, "parents": [act_fid], "mimeType": "application/x-ndjson"},
                    media_body=media,
                    fields="id",
                    supportsAllDrives=True
                ).execute()
                fid = created.get("id")
                self.index.set_file_id(f"activity_{month_str}", fid)
                self.sync_drive_index()

            return fid

    def read_activity(self, limit: int = 50, offset: int = 0, current_user: Optional[dict] = None) -> Dict[str, Any]:
        """Reads recent activity logs directly from Drive."""
        self._ensure_connected()
        act_fid = self.index.get_folder_id("folder_activity") or self.get_or_create_folder("activity", self.root_folder_id)
        res = self.service.files().list(
            q=f"'{act_fid}' in parents and mimeType = 'application/x-ndjson' and trashed = false",
            fields="files(id, name, createdTime)",
            orderBy="name desc",
            pageSize=3,
            supportsAllDrives=True
        ).execute()

        all_events = []
        for f in res.get("files", []):
            try:
                req = self.service.files().get_media(fileId=f["id"], supportsAllDrives=True)
                bio = io.BytesIO()
                downloader = MediaIoBaseDownload(bio, req)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                bio.seek(0)
                for line in bio.read().decode("utf-8").splitlines():
                    if line.strip():
                        all_events.append(json.loads(line))
            except Exception as e:
                print(f"[-] Error reading activity file {f['id']}: {e}")

        # Filter by RBAC
        is_admin = current_user and (
            current_user.get("role") == "ADMIN" or
            current_user.get("is_superuser") or
            "admin" in current_user.get("groups", [])
        )

        filtered = []
        for ev in reversed(all_events):
            if not is_admin:
                if current_user and str(ev.get("user_id")) != str(current_user.get("id")):
                    continue
                if not current_user:
                    continue
            filtered.append(ev)

        total_count = len(filtered)
        paged = filtered[offset : offset + limit]

        return {
            "count": total_count,
            "results": paged,
            "limit": limit,
            "offset": offset
        }

    # -------------------------------------------------------------------------
    # Manifest & Export Operations
    # -------------------------------------------------------------------------

    def save_manifest(self, task_id: int, manifest: dict) -> str:
        self._ensure_connected()
        folders = self._ensure_task_folders(task_id, f"task_{task_id}")
        return self.write_json_file("manifest.json", folders["metadata"], manifest, index_key=f"task_{task_id}_manifest")

    def load_manifest(self, task_id: int) -> Optional[dict]:
        self._ensure_connected()
        file_id = self.index.get_file_id(f"task_{task_id}_manifest")
        if not file_id:
            folders = self._ensure_task_folders(task_id, f"task_{task_id}")
            file_id = self.find_file_in_folder("manifest.json", folders["metadata"])
            if file_id:
                self.index.set_file_id(f"task_{task_id}_manifest", file_id)

        if not file_id:
            return None
        return self.read_json_file(file_id)

    def save_export(self, task_id: int, export_filename: str, local_zip_path: Path) -> Dict[str, Any]:
        """Uploads a generated ZIP export to tasks/task_<id>/exports/."""
        self._ensure_connected()
        folders = self._ensure_task_folders(task_id, f"task_{task_id}")
        e_fid = folders["exports"]

        path = Path(local_zip_path)
        if not path.exists():
            raise FileNotFoundError(f"Export zip does not exist: {path}")

        media = MediaFileUpload(str(path), mimetype="application/zip", resumable=True)
        file = self.service.files().create(
            body={"name": export_filename, "parents": [e_fid]},
            media_body=media,
            fields="id, name, size, webViewLink",
            supportsAllDrives=True
        ).execute()

        return {
            "file_id": file.get("id"),
            "name": file.get("name"),
            "size": int(file.get("size", path.stat().st_size)),
            "web_view_link": file.get("webViewLink")
        }

    def load_export(self, drive_file_id: str, target_local_path: Path) -> Path:
        """Downloads a cloud-stored export zip to temporary local path."""
        self._ensure_connected()
        req = self.service.files().get_media(fileId=drive_file_id, supportsAllDrives=True)
        target = Path(target_local_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        with open(target, "wb") as f:
            downloader = MediaIoBaseDownload(f, req)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        return target

    # -------------------------------------------------------------------------
    # Health Check
    # -------------------------------------------------------------------------

    def health_check(self) -> Dict[str, Any]:
        """Verifies Google Drive connectivity and root folder access."""
        if not self.service:
            return {
                "status": "unavailable",
                "provider": "google_drive",
                "configured": False,
                "error": "Google credentials not configured"
            }

        try:
            # Query root folder metadata
            folder = self.service.files().get(
                fileId=self.root_folder_id,
                fields="id, name, capabilities, driveId",
                supportsAllDrives=True
            ).execute()

            return {
                "status": "ok",
                "provider": "google_drive",
                "configured": True,
                "root_folder_id": self.root_folder_id,
                "root_folder_name": folder.get("name"),
                "can_edit": folder.get("capabilities", {}).get("canAddChildren", True)
            }
        except Exception as e:
            return {
                "status": "error",
                "provider": "google_drive",
                "configured": True,
                "root_folder_id": self.root_folder_id,
                "error": str(e)
            }
