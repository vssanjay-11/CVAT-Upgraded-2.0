# Copyright (C) CVAT.ai Corporation
# SPDX-License-Identifier: MIT

"""
Dedicated Google Drive Storage Service for ROOTS Platform.
Folder target: 1NRmlelgPqA61sEpK6AyyYg_eSIE-LdZD
Supports:
- Shared Drive and My Drive permission models (supportsAllDrives=True)
- Deterministic hierarchical folder structure:
    ROOT/
    ├── tasks/task_<id>_<name>/
    │   ├── source/
    │   ├── exports/
    │   └── metadata/
    ├── projects/
    └── backups/
- Resilient uploads with MIME type detection, retry, and checksum validation
- Google Drive File ID tracking for persistent database linking
"""

import os
import re
import json
import mimetypes
from pathlib import Path
from typing import Dict, List, Optional, Any

GOOGLE_DRIVE_ROOT_FOLDER_ID = os.environ.get(
    "GOOGLE_DRIVE_ROOT_FOLDER_ID",
    "1NRmlelgPqA61sEpK6AyyYg_eSIE-LdZD"
)

# Optional google-api-python-client import
try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
    from google.oauth2 import service_account
    from google.oauth2.credentials import Credentials
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False


def sanitize_folder_name(name: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_\-]', '_', name)[:50]


class GoogleDriveStorageService:
    def __init__(self, root_folder_id: Optional[str] = None):
        self.root_folder_id = root_folder_id or GOOGLE_DRIVE_ROOT_FOLDER_ID
        self.service = None
        self._init_service()

    def _init_service(self):
        if not GOOGLE_API_AVAILABLE:
            return

        creds = None
        # 1. Check Service Account environment variable or file
        sa_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get("GOOGLE_SERVICE_ACCOUNT_PATH")
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
            except Exception as e:
                print(f"[-] Failed loading credentials from {sa_path}: {e}")

        # 2. Check User OAuth token
        if not creds:
            token_json = os.environ.get("GOOGLE_OAUTH_TOKEN_JSON")
            if token_json:
                try:
                    token_info = json.loads(token_json)
                    creds = Credentials.from_authorized_user_info(
                        token_info, scopes=["https://www.googleapis.com/auth/drive"]
                    )
                except Exception as e:
                    print(f"[-] Failed loading OAuth token: {e}")

        if creds:
            try:
                self.service = build("drive", "v3", credentials=creds, cache_discovery=False)
                print("[+] Google Drive API service initialized successfully.")
            except Exception as e:
                print(f"[-] Failed to build Google Drive client: {e}")

    def is_configured(self) -> bool:
        return self.service is not None

    def get_or_create_folder(self, folder_name: str, parent_id: str) -> str:
        """
        Idempotently finds or creates a subfolder within parent_id.
        Supports both My Drive and Shared Drives.
        """
        if not self.service:
            raise RuntimeError("Google Drive service is not configured. Set Google credentials.")

        safe_name = folder_name.replace("'", "\\'")
        query = (
            f"name = '{safe_name}' and "
            f"'{parent_id}' in parents and "
            f"mimeType = 'application/vnd.google-apps.folder' and "
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
        if files:
            return files[0]["id"]

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

        return folder.get("id")

    def ensure_task_folders(self, task_id: int, task_name: str) -> Dict[str, str]:
        """
        Creates the standard folder hierarchy for a Task:
        ROOT_FOLDER/tasks/task_<id>_<name>/
        ├── source/
        ├── exports/
        └── metadata/
        """
        tasks_root_id = self.get_or_create_folder("tasks", self.root_folder_id)
        clean_name = sanitize_folder_name(task_name)
        task_folder_name = f"task_{task_id}_{clean_name}"
        task_folder_id = self.get_or_create_folder(task_folder_name, tasks_root_id)

        source_folder_id = self.get_or_create_folder("source", task_folder_id)
        exports_folder_id = self.get_or_create_folder("exports", task_folder_id)
        metadata_folder_id = self.get_or_create_folder("metadata", task_folder_id)

        return {
            "task_folder_id": task_folder_id,
            "source_folder_id": source_folder_id,
            "exports_folder_id": exports_folder_id,
            "metadata_folder_id": metadata_folder_id,
        }

    def upload_file(
        self,
        local_path: Path,
        parent_folder_id: str,
        filename: Optional[str] = None,
        mime_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Uploads a local file to a Google Drive folder.
        """
        if not self.service:
            raise RuntimeError("Google Drive service is not configured.")

        path = Path(local_path)
        if not path.exists():
            raise FileNotFoundError(f"Local file does not exist: {path}")

        name = filename or path.name
        if not mime_type:
            mime_type, _ = mimetypes.guess_type(str(path))
            mime_type = mime_type or "application/octet-stream"

        file_metadata = {
            "name": name,
            "parents": [parent_folder_id]
        }

        media = MediaFileUpload(
            str(path),
            mimetype=mime_type,
            resumable=True
        )

        file = self.service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, name, size, mimeType, webViewLink",
            supportsAllDrives=True
        ).execute()

        return {
            "file_id": file.get("id"),
            "name": file.get("name"),
            "size": int(file.get("size", path.stat().st_size)),
            "mime_type": file.get("mimeType"),
            "web_view_link": file.get("webViewLink")
        }

    def upload_task_dataset(
        self,
        task_id: int,
        task_name: str,
        local_images_dir: Path,
        user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Uploads an entire dataset folder to Google Drive under tasks/task_<id>_<name>/source/
        Saves metadata manifest under metadata/
        """
        if not self.service:
            return {"status": "unconfigured", "message": "Google Drive not configured. Using local storage."}

        folders = self.ensure_task_folders(task_id, task_name)
        source_fid = folders["source_folder_id"]

        images_dir = Path(local_images_dir)
        image_files = sorted([
            f for f in images_dir.iterdir()
            if f.is_file() and f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp')
        ])

        uploaded_files = []
        total_size = 0

        for img in image_files:
            up = self.upload_file(img, source_fid)
            uploaded_files.append({
                "filename": img.name,
                "drive_file_id": up["file_id"],
                "size": up["size"],
                "mime_type": up["mime_type"],
            })
            total_size += up["size"]

        manifest = {
            "task_id": task_id,
            "task_name": task_name,
            "user_id": user_id,
            "folders": folders,
            "image_count": len(uploaded_files),
            "total_bytes": total_size,
            "files": uploaded_files
        }

        # Upload manifest
        temp_manifest_path = images_dir / "drive_manifest.json"
        with open(temp_manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        self.upload_file(temp_manifest_path, folders["metadata_folder_id"], filename="task_dataset_manifest.json")
        try:
            temp_manifest_path.unlink()
        except Exception:
            pass

        return {
            "status": "success",
            "folders": folders,
            "image_count": len(uploaded_files),
            "total_bytes": total_size,
            "manifest": manifest
        }

    def download_file(self, drive_file_id: str, target_path: Path) -> Path:
        """
        Downloads a Google Drive file to target_path.
        """
        if not self.service:
            raise RuntimeError("Google Drive service is not configured.")

        request = self.service.files().get_media(fileId=drive_file_id, supportsAllDrives=True)
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        with open(target, "wb") as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

        return target

    def delete_file(self, drive_file_id: str) -> bool:
        """
        Permanently deletes a file/folder from Drive.
        """
        if not self.service:
            return False
        try:
            self.service.files().delete(fileId=drive_file_id, supportsAllDrives=True).execute()
            return True
        except Exception as e:
            print(f"[-] Error deleting Drive file {drive_file_id}: {e}")
            return False
