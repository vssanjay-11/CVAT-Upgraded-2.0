#!/usr/bin/env python3
# Copyright (C) CVAT.ai Corporation & ROOTS Industrial Defect Annotation Platform
# SPDX-License-Identifier: MIT

"""
Authentication and Role-Based Access Control (RBAC) Module.
Natively implements:
- Real Google OAuth 2.0 / OpenID Connect identity verification
- Secure session tokens (HttpOnly cookies and Bearer/Token headers)
- Session persistence, expiration, and refresh
- User management with stable external Google Subject ID (sub)
- Strict role enforcement (ADMIN vs USER)
- Initial admin assignment via ADMIN_GOOGLE_EMAIL
- Structured error codes (OAUTH_CONFIGURATION_ERROR, etc.)
- Canonical redirect URI handling and diagnostic endpoint support
"""

import os
import time
import secrets
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from typing import Optional, Dict, Any, Tuple
import requests

# Load local .env if present
def _load_dotenv():
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("\"'")
                        if k and k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass

_load_dotenv()

# Environment Variables
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_REDIRECT_URI = os.environ.get(
    "GOOGLE_REDIRECT_URI",
    "http://localhost:7000/api/auth/google/callback"
).strip()
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000").strip()
SESSION_SECRET = os.environ.get("SESSION_SECRET", "roots-cvat-production-secret-session-2026").strip()
ADMIN_GOOGLE_EMAIL = os.environ.get("ADMIN_GOOGLE_EMAIL", "sanjay@gmail.com").strip().lower()

# Default session duration: 7 days
SESSION_DURATION_SECONDS = 7 * 24 * 60 * 60

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_TOKENINFO_ENDPOINT = "https://oauth2.googleapis.com/tokeninfo"


def get_oauth_config_status() -> dict:
    """Safe diagnostic info for admins. Never exposes client secrets or tokens."""
    _load_dotenv()
    cid = os.environ.get("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID).strip()
    csec = os.environ.get("GOOGLE_CLIENT_SECRET", GOOGLE_CLIENT_SECRET).strip()
    r_uri = os.environ.get("GOOGLE_REDIRECT_URI", GOOGLE_REDIRECT_URI).strip()
    f_url = os.environ.get("FRONTEND_URL", FRONTEND_URL).strip()
    admin_email = os.environ.get("ADMIN_GOOGLE_EMAIL", ADMIN_GOOGLE_EMAIL).strip()
    return {
        "configured": bool(cid and csec),
        "redirect_uri": r_uri,
        "frontend_url": f_url,
        "client_id_present": bool(cid),
        "client_secret_present": bool(csec),
        "admin_bootstrap_configured": bool(admin_email),
    }


def sanitize_user(user_dict: dict) -> dict:
    """Return public safe user representation without sensitive secrets."""
    if not user_dict:
        return {}
    clean = dict(user_dict)
    clean.pop("password_hash", None)
    clean.pop("google_refresh_token", None)
    clean.pop("google_access_token", None)
    uid = clean.get("id", 1)
    clean["url"] = f"/api/users/{uid}"
    return clean


def get_google_auth_url(state: str = None, redirect_uri: str = None) -> str:
    """Generate Google OAuth 2.0 authorization redirect URL."""
    _load_dotenv()
    cid = os.environ.get("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID).strip()
    r_uri = redirect_uri or os.environ.get("GOOGLE_REDIRECT_URI", GOOGLE_REDIRECT_URI).strip()
    params = {
        "client_id": cid,
        "redirect_uri": r_uri,
        "response_type": "code",
        "scope": "openid email profile https://www.googleapis.com/auth/drive",
        "access_type": "offline",
        "prompt": "consent select_account",
    }
    if state:
        params["state"] = state
    return f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"


def verify_google_id_token(id_token: str) -> Tuple[Optional[dict], Optional[str]]:
    """
    Verify Google JWT ID Token directly using Google's secure tokeninfo endpoint.
    Guarantees cryptographically validated identity without trusting client input.
    Returns: (user_info_dict, error_code)
    """
    try:
        resp = requests.get(
            GOOGLE_TOKENINFO_ENDPOINT,
            params={"id_token": id_token},
            timeout=8
        )
        if resp.status_code != 200:
            return None, "OAUTH_ID_TOKEN_INVALID"
        payload = resp.json()

        # Verify audience if client ID is configured
        if GOOGLE_CLIENT_ID and payload.get("aud") != GOOGLE_CLIENT_ID:
            return None, "OAUTH_AUDIENCE_MISMATCH"

        # Verify email is verified by Google
        if str(payload.get("email_verified", "")).lower() not in ("true", "1"):
            return None, "OAUTH_EMAIL_NOT_VERIFIED"

        google_sub = payload.get("sub")
        if not google_sub:
            return None, "OAUTH_ID_TOKEN_INVALID"

        return {
            "google_sub": google_sub,
            "email": str(payload.get("email", "")).strip().lower(),
            "name": payload.get("name") or payload.get("email", "").split("@")[0],
            "picture": payload.get("picture", ""),
        }, None
    except Exception as e:
        print(f"[!] Error verifying Google ID token: {e}", flush=True)
        return None, "OAUTH_ID_TOKEN_INVALID"


def exchange_google_code(code: str, redirect_uri: str = None) -> Tuple[Optional[dict], Optional[str]]:
    """
    Exchange authorization code for validated Google user info.
    Returns: (user_info_dict, error_code)
    """
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return None, "OAUTH_CONFIGURATION_ERROR"

    r_uri = redirect_uri or GOOGLE_REDIRECT_URI
    try:
        token_resp = requests.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": r_uri,
                "grant_type": "authorization_code"
            },
            timeout=10
        )
        if token_resp.status_code != 200:
            print(f"[!] Google code exchange failed: {token_resp.status_code} {token_resp.text}", flush=True)
            return None, "OAUTH_TOKEN_EXCHANGE_FAILED"

        tokens = token_resp.json()

        # Persist OAuth user token for Google Drive cloud storage
        if tokens.get("access_token"):
            token_data = {
                "token": tokens.get("access_token"),
                "refresh_token": tokens.get("refresh_token"),
                "token_uri": GOOGLE_TOKEN_ENDPOINT,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "scopes": ["https://www.googleapis.com/auth/drive"],
            }
            token_path = Path(__file__).resolve().parent / "token.json"
            if not token_data["refresh_token"] and token_path.exists():
                try:
                    with open(token_path, "r", encoding="utf-8") as f:
                        old_token = json.load(f)
                    token_data["refresh_token"] = old_token.get("refresh_token")
                except Exception:
                    pass
            try:
                with open(token_path, "w", encoding="utf-8") as f:
                    json.dump(token_data, f, indent=2)
                print(f"[+] Saved user OAuth token to {token_path.name} for Drive cloud storage.", flush=True)
            except Exception as e:
                print(f"[-] Failed saving token.json: {e}", flush=True)

        id_token = tokens.get("id_token")
        if id_token:
            verified, err = verify_google_id_token(id_token)
            if verified:
                return verified, None
            if err:
                return None, err

        # Fallback to userinfo with access token
        access_token = tokens.get("access_token")
        if access_token:
            u_resp = requests.get(
                GOOGLE_USERINFO_ENDPOINT,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=8
            )
            if u_resp.status_code == 200:
                data = u_resp.json()
                if not data.get("sub"):
                    return None, "OAUTH_ID_TOKEN_INVALID"
                return {
                    "google_sub": data.get("sub"),
                    "email": str(data.get("email", "")).strip().lower(),
                    "name": data.get("name") or data.get("email", "").split("@")[0],
                    "picture": data.get("picture", ""),
                }, None

        return None, "OAUTH_TOKEN_EXCHANGE_FAILED"
    except Exception as e:
        print(f"[!] Error exchanging Google OAuth code: {e}", flush=True)
        return None, "OAUTH_TOKEN_EXCHANGE_FAILED"


# Alias for backward compatibility
exchange_code_for_tokens = exchange_google_code


def get_or_create_google_user(user_info: dict, db: dict) -> dict:
    """
    Retrieve or create persistent user record based on immutable Google Subject ID (google_sub).
    Enforces initial ADMIN role if email matches ADMIN_GOOGLE_EMAIL.
    """
    if "users" not in db:
        db["users"] = {}
    if "next_user_id" not in db:
        db["next_user_id"] = 2

    google_sub = user_info["google_sub"]
    email = user_info["email"]
    display_name = user_info.get("name") or email.split("@")[0]
    picture = user_info.get("picture", "")
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # 1. Search existing user by immutable google_sub
    matched_user = None
    for k, u in db["users"].items():
        if isinstance(u, dict) and u.get("google_sub") == google_sub:
            matched_user = u
            break

    # 2. Fallback search by email for initial link
    if not matched_user:
        for k, u in db["users"].items():
            if isinstance(u, dict) and str(u.get("email", "")).strip().lower() == email:
                matched_user = u
                break

    # Check if this email is configured as primary admin
    is_admin_email = bool(ADMIN_GOOGLE_EMAIL and email == ADMIN_GOOGLE_EMAIL)

    if matched_user:
        # Update identity profile with latest details
        matched_user["google_sub"] = google_sub
        matched_user["email"] = email
        if display_name:
            matched_user["display_name"] = display_name
            parts = display_name.split(" ", 1)
            matched_user["first_name"] = parts[0]
            matched_user["last_name"] = parts[1] if len(parts) > 1 else ""
        if picture:
            matched_user["avatar_url"] = picture
        matched_user["last_login"] = now_iso
        matched_user["last_activity_at"] = now_iso
        matched_user["is_active"] = True

        # Enforce server-side ADMIN bootstrap if configured
        if is_admin_email and matched_user.get("role") != "ADMIN":
            matched_user["role"] = "ADMIN"
            matched_user["is_staff"] = True
            matched_user["is_superuser"] = True
            matched_user["groups"] = ["admin"]

        return matched_user

    # 3. Create brand new user on first login
    new_uid = db["next_user_id"]
    db["next_user_id"] += 1

    role = "ADMIN" if is_admin_email else "USER"
    parts = display_name.split(" ", 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else ""

    # Generate safe unique username
    base_uname = email.split("@")[0].replace(".", "_")
    uname = base_uname
    idx = 1
    while uname in db["users"]:
        uname = f"{base_uname}_{idx}"
        idx += 1

    new_user = {
        "id": new_uid,
        "username": uname,
        "google_sub": google_sub,
        "email": email,
        "display_name": display_name,
        "first_name": first_name,
        "last_name": last_name,
        "avatar_url": picture,
        "role": role,
        "groups": ["admin"] if role == "ADMIN" else ["user"],
        "is_staff": (role == "ADMIN"),
        "is_superuser": (role == "ADMIN"),
        "is_active": True,
        "created_at": now_iso,
        "date_joined": now_iso,
        "last_login": now_iso,
        "last_activity_at": now_iso,
        "email_verification_required": False,
        "has_analytics_access": True,
    }

    db["users"][str(new_uid)] = new_user
    db["users"][uname] = new_user

    print(f"[+] Created persistent user #{new_uid} ('{uname}', {email}, sub={google_sub}) with role {role}", flush=True)
    return new_user


def create_session(user_dict: dict, db: dict) -> str:
    """Create a persistent session token with expiration."""
    if "sessions" not in db:
        db["sessions"] = {}
    if "tokens" not in db:
        db["tokens"] = {}

    session_token = secrets.token_hex(32)
    now = time.time()
    expires_at = now + SESSION_DURATION_SECONDS

    uid = user_dict.get("id")
    uname = user_dict.get("username", "admin")

    db["sessions"][session_token] = {
        "user_id": uid,
        "username": uname,
        "created_at": now,
        "expires_at": expires_at
    }

    db["tokens"][session_token] = str(uid)
    return session_token


def destroy_session(token: str, db: dict):
    """Invalidate session upon logout."""
    if "sessions" in db:
        db["sessions"].pop(token, None)
    if "tokens" in db:
        db["tokens"].pop(token, None)


def build_session_cookie(session_token: str, is_https: bool = False, max_age: int = SESSION_DURATION_SECONDS) -> str:
    """
    Builds standard compliant HttpOnly session cookie.
    If HTTPS is active (cross-site capable), sets SameSite=None; Secure.
    Otherwise sets SameSite=Lax.
    """
    cookie_parts = [
        f"sessionid={session_token}",
        "Path=/",
        "HttpOnly",
        f"Max-Age={max_age}",
    ]
    if is_https:
        cookie_parts.append("SameSite=None")
        cookie_parts.append("Secure")
    else:
        cookie_parts.append("SameSite=Lax")

    return "; ".join(cookie_parts)


def parse_cookie_header(cookie_header: str) -> dict:
    """Extract cookies from standard HTTP Cookie header."""
    cookies = {}
    if not cookie_header:
        return cookies
    for part in cookie_header.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


def get_user_from_headers(headers, db: dict) -> Optional[dict]:
    """
    Securely authenticate user from request headers.
    Checks:
    1. Authorization: Bearer <session_token> or Token <session_token>
    2. Cookie: sessionid=<token> or cvat_session=<token>
    3. Legacy local dev token
    Returns None if unauthenticated.
    """
    token = None

    auth_header = headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    elif auth_header.startswith("Token "):
        token = auth_header[6:].strip()

    if not token:
        cookie_header = headers.get("Cookie", "")
        cookies = parse_cookie_header(cookie_header)
        token = cookies.get("sessionid") or cookies.get("cvat_session") or cookies.get("token")

    if not token:
        return None

    now = time.time()

    if "sessions" in db and token in db["sessions"]:
        session = db["sessions"][token]
        if session.get("expires_at", 0) < now:
            db["sessions"].pop(token, None)
            return None

        uid = str(session.get("user_id"))
        user = db.get("users", {}).get(uid)
        if not user:
            uname = session.get("username")
            user = db.get("users", {}).get(uname)

        if user and user.get("is_active", True):
            user["last_activity_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            return sanitize_user(user)

    if "tokens" in db and token in db["tokens"]:
        identifier = str(db["tokens"][token])
        user = db.get("users", {}).get(identifier)
        if user and user.get("is_active", True):
            user["last_activity_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            return sanitize_user(user)

    return None
