#!/usr/bin/env python3
# Copyright (C) CVAT.ai Corporation
# SPDX-License-Identifier: MIT

"""
Automated Build Script for CVAT Standalone Executable
1. Builds production frontend bundle via yarn/webpack
2. Executes PyInstaller with buildappv1_cvat.spec
3. Generates portable zip distribution package
"""

import sys
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

def run_cmd(cmd, cwd=REPO_ROOT, shell=True):
    print(f"\n[>] Executing: {cmd}")
    res = subprocess.run(cmd, cwd=cwd, shell=shell)
    if res.returncode != 0:
        print(f"[!] Command failed with exit code: {res.returncode}")
        return False
    return True

def main():
    print("=" * 65)
    print("      CVAT Standalone Application - Packaging Automation       ")
    print("=" * 65)

    ui_dist = REPO_ROOT / "cvat-ui" / "dist"
    index_html = ui_dist / "index.html"

    # Step 1: Build UI if missing or rebuild
    print("\n[*] Step 1: Checking Webpack production build...")
    build_needed = not index_html.exists()
    if build_needed:
        print("    Production bundle missing. Running yarn workspace cvat-ui run build...")
    else:
        print("    Found existing dist. Running fresh build to ensure latest changes...")

    success = run_cmd("corepack yarn workspace cvat-ui run build")
    if not success and not index_html.exists():
        print("[!] Error: Failed to generate cvat-ui static build.")
        sys.exit(1)

    # Step 2: Ensure PyInstaller is installed
    print("\n[*] Step 2: Checking PyInstaller...")
    try:
        import PyInstaller
        print(f"    Found PyInstaller {PyInstaller.__version__}")
    except ImportError:
        print("    Installing PyInstaller...")
        run_cmd(f'"{sys.executable}" -m pip install pyinstaller')

    # Step 3: Run PyInstaller with buildappv1_cvat.spec
    print("\n[*] Step 3: Running PyInstaller packaging...")
    spec_file = REPO_ROOT / "buildappv1_cvat.spec"
    if not spec_file.exists():
        print(f"[!] Error: Spec file not found at {spec_file}")
        sys.exit(1)

    cmd = f'"{sys.executable}" -m PyInstaller "{spec_file}" --noconfirm --clean'
    if not run_cmd(cmd):
        print("[!] Error: PyInstaller build failed.")
        sys.exit(1)

    # Step 4: Verify generated executable
    exe_path = REPO_ROOT / "dist" / "CVAT_App.exe"
    if not exe_path.exists():
        print(f"[!] Error: Expected output {exe_path} does not exist.")
        sys.exit(1)

    print(f"\n[SUCCESS] Executable built at: {exe_path}")
    print(f"          Size: {exe_path.stat().st_size / (1024 * 1024):.2f} MB")

    # Step 5: Create portable ZIP package containing exe and new application code
    print("\n[*] Step 5: Packaging portable zip archive with application code and executable...")
    zip_path = REPO_ROOT / "dist" / "CVAT_App_Portable.zip"
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 1. Add executable
        zf.write(exe_path, arcname="CVAT_App.exe")
        print("    + Added CVAT_App.exe")

        # 2. Add launcher script and spec
        zf.write(REPO_ROOT / "cvat_app_launcher.py", arcname="cvat_app_launcher.py")
        zf.write(REPO_ROOT / "buildappv1_cvat.spec", arcname="buildappv1_cvat.spec")

        # 3. Add config.json and README
        config_file = REPO_ROOT / "config.json"
        if config_file.exists():
            zf.write(config_file, arcname="config.json")
        readme = REPO_ROOT / "README.md"
        if readme.exists():
            zf.write(readme, arcname="README.md")

        # 4. Add compiled static UI files (cvat-ui/dist)
        if ui_dist.exists():
            for root, _, files in os.walk(ui_dist):
                for f in files:
                    full_p = Path(root) / f
                    rel_p = full_p.relative_to(REPO_ROOT)
                    zf.write(full_p, arcname=str(rel_p))
            print("    + Added compiled application bundle (cvat-ui/dist)")

        # 5. Add custom new application code (dense segmentation components)
        custom_code_files = [
            Path("cvat-ui/src/components/annotation-page/standard-workspace/controls-side-bar/segment-whole-modal.tsx"),
            Path("cvat-ui/src/components/annotation-page/standard-workspace/controls-side-bar/tools-control.tsx"),
            Path("cvat-core/src/dense-contour.ts"),
            Path("cvat-core/src/api.ts"),
            Path("cvat-core/src/index.ts"),
            Path("cvat-ui/src/cvat-core-wrapper.ts"),
            Path("cvat-ui/package.json"),
            Path("package.json"),
        ]
        for rel_file in custom_code_files:
            abs_file = REPO_ROOT / rel_file
            if abs_file.exists():
                zf.write(abs_file, arcname=f"new_application_code/{rel_file}")
        print("    + Added new application source code files")

    print(f"\n[SUCCESS] Portable Zip created at: {zip_path}")
    print(f"          Size: {zip_path.stat().st_size / (1024 * 1024):.2f} MB")
    print("\n" + "=" * 65)
    print("Build complete! You can now use Inno Setup with cvat_installer.iss")
    print("=" * 65)

if __name__ == '__main__':
    main()
