# ROOTS Industrial Defect Annotation & AI Segmentation Platform
## Production Cloud & Multi-User Deployment Guide

This document provides exact, end-to-end instructions for deploying the ROOTS Defect Annotation Platform to a production cloud architecture with Vercel frontend hosting, persistent backend services, Google OAuth 2.0 authentication, Google Drive dataset storage, and decoupled YOLO11s AI inference.

---

### 1. Google Cloud Project Setup
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project or select your existing organization project (e.g., `roots-defect-cvat`).
3. Enable the required Google APIs:
   - **Google Drive API**
   - **Identity and Access Management (IAM) API**

---

### 2. Google OAuth 2.0 Credentials
1. Navigate to **APIs & Services** > **OAuth consent screen**.
   - User Type: **Internal** (for company workspace) or **External**.
   - App name: `ROOTS Defect Annotation Platform`
   - User support email & Developer contact email.
   - Scopes: `.../auth/userinfo.email`, `.../auth/userinfo.profile`, `openid`.
2. Navigate to **APIs & Services** > **Credentials** > **Create Credentials** > **OAuth Client ID**.
   - Application type: **Web application**.
   - Name: `ROOTS CVAT Web Client`.
   - Authorized JavaScript origins:
     - `http://localhost:3000` (development)
     - `https://your-vercel-domain.vercel.app` (production Vercel frontend)
   - Authorized redirect URIs:
     - `http://localhost:7000/api/auth/google/callback`
     - `https://your-api-domain.com/api/auth/google/callback`
     - `https://your-vercel-domain.vercel.app/api/auth/google/callback`
3. Save `Client ID` and `Client Secret` securely. **Never commit them to git or frontend bundles.**

---

### 3. Google Drive Dataset Storage Configuration
- **Production Root Folder ID**: `1NRmlelgPqA61sEpK6AyyYg_eSIE-LdZD`
- **Drive URL**: `https://drive.google.com/drive/folders/1NRmlelgPqA61sEpK6AyyYg_eSIE-LdZD`

#### Permission Model:
1. The target folder is a **My Drive** folder owned by `113047635709444326708`.
2. Create a Service Account in GCP Console:
   - Navigate to **IAM & Admin** > **Service Accounts** > **Create Service Account** (`roots-cvat-drive-storage`).
   - Create and download a JSON key.
3. Grant permissions in Google Drive:
   - Open the Google Drive folder in a browser.
   - Click **Share**.
   - Add the service account email (e.g., `roots-cvat-drive-storage@roots-defect-cvat.iam.gserviceaccount.com`) with **Editor** role.
4. Set environment variables on the backend:
   ```bash
   GOOGLE_DRIVE_ROOT_FOLDER_ID=1NRmlelgPqA61sEpK6AyyYg_eSIE-LdZD
   GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
   ```

---

### 4. Persistent Application Database Setup
Production multi-user operations require a persistent database (e.g. managed PostgreSQL like Supabase, Neon, GCP Cloud SQL, or AWS RDS):
1. Provision a PostgreSQL instance (v14+).
2. Configure connection pooling (PgBouncer recommended for high concurrency).
3. Set `DATABASE_URL=postgresql://user:password@host:5432/roots_cvat` in the backend environment.

---

### 5. Persistent Backend Deployment (Python Server)
Because the Python server handles persistent operations, file buffering, and long-running exports/chunk processing, deploy it to a persistent container service (such as Render, Railway, Fly.io, or GCP Cloud Run / Compute Engine):
1. Package the backend container using `Dockerfile`:
   ```dockerfile
   FROM python:3.10-slim
   WORKDIR /app
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   COPY . .
   EXPOSE 7000
   CMD ["python", "cvat_local_server.py"]
   ```
2. Configure production environment variables as shown in `.env.example`.
3. Verify backend health endpoint:
   `GET https://your-backend-api.com/api/server/health` -> returns `{"status": "OK"}`.

---

### 6. Decoupled AI Inference Deployment (YOLO11s GPU Server)
The YOLO models (`yolo11s-seg.pt`, `housing_cover_seg/best.pt`) require CUDA GPU acceleration:
1. Deploy the AI inference service on a GPU-enabled host (GCP G2/T4 instance, RunPod, AWS EC2 G4dn, or local workstation):
   - Command: `python cvat_local_server.py` or dedicated inference microservice.
   - Models are cached in memory upon first call.
2. Ensure network security:
   - Restrict incoming requests to only the persistent API backend IP via firewall or VPC peering.

---

### 7. Vercel Frontend Deployment
1. Import repository into [Vercel](https://vercel.com).
2. Set Framework Preset: **Other**.
3. Build Settings:
   - Root Directory: `./`
   - Build Command: `cd cvat-ui && npm run build`
   - Output Directory: `cvat-ui/dist`
4. Set Environment Variables in Vercel Project Settings:
   - `REACT_APP_API_URL=https://your-backend-api.com`
   - `GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com`
5. Configure `vercel.json` rewrites (already provided in root directory).
6. Deploy!

---

### 8. Admin User Bootstrap
1. Set `ADMIN_GOOGLE_EMAIL=your-admin-email@gmail.com` on the backend.
2. The user signs in via "Continue with Google".
3. The system matches the authenticated identity against `ADMIN_GOOGLE_EMAIL` and grants the `ADMIN` role.
4. Admins can access the **Admin Dashboard**, view all user activities, download reports, and delete tasks.

---

### 9. Task 5 Protection & Data Migration Checklist
> [!IMPORTANT]
> Task 5 (`ROOTS01`, 1,384 images, 1,865 polygons) must remain 100% untouched until staging testing is fully validated.

1. **Pre-migration Safety**:
   - Verify backup exists at:
     `local_server_data/backups/db_pre_cloud_migration_20260921_120220.json`
2. **Staging Test with Temporary Task**:
   - Create a test task with 5–20 images.
   - Verify Google OAuth login.
   - Verify normal users get `HTTP 403 Forbidden` on `DELETE /api/tasks/{id}`.
   - Verify label creation, renaming, and safeguard deletion blocking.
   - Verify autosave checkpointing persists work.
   - Verify Google Drive upload syncs to `1NRmlelgPqA61sEpK6AyyYg_eSIE-LdZD`.
3. **Task 5 Production Migration Verification**:
   - Compare pre- and post-migration counts:
     - Image count: **1,384**
     - Shape polygons: **1,865**

---

### 10. Rollback Procedure
If any issue occurs during deployment:
1. Revert Vercel deployment to the previous immutable deployment hash.
2. Restore database state from `local_server_data/backups/db_pre_cloud_migration_20260921_120220.json`.
3. Restart local server:
   ```powershell
   .venv-yolo\Scripts\python.exe cvat_local_server.py
   ```
4. Verify Task 5 integrity via:
   ```powershell
   python scratch/test_phase123.py
   ```
