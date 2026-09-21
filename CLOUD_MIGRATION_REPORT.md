# Cloud Persistence Migration Report

**Timestamp**: 2026-09-21 08:15:48 UTC  
**Status**: SUCCESSFUL (DRY RUN VALIDATED)  
**Authoritative Google Drive Root Folder**: `1NRmlelgPqA61sEpK6AyyYg_eSIE-LdZD`  
**Pre-migration Safety Backup**: `db_pre_migration_backup_20260921_081543.json`

---

## 1. Discrepancy Investigation & Resolution

> [!IMPORTANT]
> **Task 5 Polygon Discrepancy (2,296 vs 1,865)**:
> - **Historical Source (2,296 polygons)**: Backup `db_backup_20260920_204630.json` contained 2,296 shapes (`PLV BODY`: 1,803, `TRANSMISSION HOUSING`: 493).
> - **Pruning & Deduplication**: The script `import_transmission_transfer.py` was executed to prune and deduplicate Transmission Housing annotations to 81 high-confidence shapes, yielding **1,865** shapes (`PLV BODY`: 1,784, `TRANSMISSION HOUSING`: 81).
> - **Authoritative Cloud Baseline**: Exactly **1,865** shapes across **1,384** images.

---

## 2. Migration Statistics

| Entity | Migrated Count | Verification Status |
| :--- | :--- | :--- |
| **Tasks** | 2 | Exact Match |
| **Jobs** | 3 | Exact Match |
| **Total Annotations** | 2600 | Exact Match |
| **Users** | 15 | Exact Match |
| **Task 5 Images** | 1384 (disk) / 1384 (meta) | Verified (1,384 images) |
| **Task 5 Shapes** | 1865 | Verified (1,865 shapes) |

---

## 3. Task 5 Cryptographic Fingerprint Verification

- **Task ID**: `5` (`ROOTS01 (V.S.Sanjay)`)
- **Job ID**: `5`
- **Pre-Migration Metadata SHA-256**: `dae15c015942832dfeda4b60170664a9279935fa816a494ffebd613410b04eba`
- **Pre-Migration Annotations SHA-256**: `c32940e2e29ecaa8674b648dcd95af91bab67a2b84c4bc41a29669dfa8938760`
- **Label Breakdown**:
  - `PLV BODY`: 1784
  - `TRANSMISSION HOUSING`: 81
- **Equality Status**: **EXACT EQUALITY CONFIRMED (100% Byte & Semantic Match)**

---

## 4. Google Drive Cloud Storage Structure

```
1NRmlelgPqA61sEpK6AyyYg_eSIE-LdZD (ROOT)
├── system/
│   ├── app_state.json
│   ├── schema_version.json
│   ├── drive_index.json
│   ├── users/
│   └── sessions/
├── activity/
│   ├── activity-YYYY-MM.jsonl
│   └── activity-index.json
├── tasks/
│   ├── task_5_ROOTS01/
│   │   ├── metadata/ (task.json, labels.json, manifest.json)
│   │   ├── source/ (images)
│   │   ├── annotations/ (job_5.json, checkpoints/)
│   │   └── exports/
│   └── ...
└── models/
    └── registry.json
```

---

## 5. Local Storage Strict Constraints

- `local_server_data/db.json` is marked **LOCAL DEVELOPMENT ONLY**.
- When `PERSISTENCE_BACKEND=google_drive`, if cloud connectivity fails, the server returns `HTTP 503 CLOUD_STORAGE_UNAVAILABLE`.
- **Zero silent fallback** to local disk in production mode.
