# Copyright (C) CVAT.ai Corporation & ROOTS Industrial Defect Annotation Platform
# SPDX-License-Identifier: MIT

"""
Drive File ID Index Manager.
Caches and persists Google Drive file and folder IDs to eliminate repeated Drive API searches.
State is cached locally in memory and persisted to Google Drive at ROOT/system/drive_index.json.
"""

import json
import threading
from typing import Dict, Optional, Any


class DriveIndex:
    def __init__(self):
        self._lock = threading.RLock()
        self.index: Dict[str, Any] = {
            "folders": {},
            "files": {},
            "revision": 1,
            "updated_at": None,
        }

    def load_from_dict(self, data: dict):
        with self._lock:
            if not isinstance(data, dict):
                return
            folders = data.get("folders", {})
            files = data.get("files", {})
            self.index["folders"].update(folders)
            self.index["files"].update(files)
            self.index["revision"] = data.get("revision", self.index["revision"])
            self.index["updated_at"] = data.get("updated_at", self.index["updated_at"])

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "folders": dict(self.index["folders"]),
                "files": dict(self.index["files"]),
                "revision": self.index["revision"],
                "updated_at": self.index.get("updated_at"),
            }

    def get_folder_id(self, key: str) -> Optional[str]:
        with self._lock:
            return self.index["folders"].get(key)

    def set_folder_id(self, key: str, folder_id: str):
        with self._lock:
            self.index["folders"][key] = folder_id

    def get_file_id(self, key: str) -> Optional[str]:
        with self._lock:
            return self.index["files"].get(key)

    def set_file_id(self, key: str, file_id: str):
        with self._lock:
            self.index["files"][key] = file_id

    def remove_key(self, key: str):
        with self._lock:
            self.index["folders"].pop(key, None)
            self.index["files"].pop(key, None)
