"""Provision the explicitly requested demo owner; keep credentials in ignored env files.

Uses ordinary Neon Auth signup for password hashing. Administrative SQL marks
only this seeded account verified (its .example address has no mailbox) and
assigns application ownership. It never disables verification for other users.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import secrets
import sys

import requests
from dotenv import dotenv_values
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
AUTH_URL = "https://ep-hidden-star-b30n47zs.neonauth.c-4.ap-southeast-1.aws.neon.tech/neondb/auth"
FRONTEND = "https://synora-frontend.onrender.com"


def main():
    os.environ["DATABASE_URL"] = dotenv_values(ROOT / ".env.admin-bootstrap", encoding="utf-8-sig")["DATABASE_URL"]
    sys.path.insert(0, str(ROOT / "backend"))
    from app.core.database import engine

    credentials_path = ROOT / ".env.sample-admin"
    saved = dotenv_values(credentials_path) if credentials_path.exists() else {}
    email = saved.get("SAMPLE_ADMIN_EMAIL") or "admin@synora.example"
    password = saved.get("SAMPLE_ADMIN_PASSWORD") or secrets.token_urlsafe(24)
    with engine.connect() as db:
        existing = db.execute(text('SELECT id FROM neon_auth."user" WHERE email = :email'), {"email": email}).first()
    if existing and not saved:
        raise RuntimeError("Sample email already exists; refusing to replace its credentials.")
    if not existing:
        credentials_path.write_text(f"SAMPLE_ADMIN_EMAIL={email}\nSAMPLE_ADMIN_PASSWORD={password}\nSAMPLE_WORKSPACE_ID=ws_default\nSAMPLE_FRONTEND_URL={FRONTEND}\n", encoding="utf-8")
        response = requests.post(AUTH_URL + "/sign-up/email", headers={"Origin": FRONTEND}, json={"email": email, "password": password, "name": "Synora Demo Admin"}, timeout=60)
        print("Neon signup HTTP", response.status_code)
    with engine.begin() as db:
        user = db.execute(text('SELECT id FROM neon_auth."user" WHERE email = :email'), {"email": email}).first()
        if not user:
            raise RuntimeError("Auth signup did not create the sample account.")
        subject = str(user.id)
        db.execute(text('UPDATE neon_auth."user" SET "emailVerified" = true, "updatedAt" = now() WHERE id = :id AND email = :email'), {"id": subject, "email": email})
        user_id = "usr_neon_" + hashlib.sha256(subject.encode()).hexdigest()[:32]
        db.execute(text("INSERT INTO users (id,email,name,created_at,updated_at) VALUES (:id,:email,:name,now(),now()) ON CONFLICT (email) DO NOTHING"), {"id": user_id, "email": email, "name": "Synora Demo Admin"})
        user_id = db.execute(text("SELECT id FROM users WHERE email = :email"), {"email": email}).scalar_one()
        db.execute(text("INSERT INTO workspaces (id,name,description,created_at,updated_at) VALUES ('ws_default','Synora Demo Workspace','Workspace for the shared sample admin.',now(),now()) ON CONFLICT (id) DO NOTHING"))
        # Only rename an empty, generically named workspace.
        db.execute(text("UPDATE workspaces SET name='Synora Demo Workspace',updated_at=now() WHERE id='ws_default' AND name IN ('Synora Workspace','Default Workspace') AND NOT EXISTS (SELECT 1 FROM projects WHERE workspace_id='ws_default')"))
        db.execute(text("INSERT INTO workspace_memberships (id,workspace_id,user_id,role,status,created_at,updated_at) VALUES (:id,'ws_default',:user_id,'owner','active',now(),now()) ON CONFLICT (workspace_id,user_id) DO UPDATE SET role='owner',status='active',updated_at=now()"), {"id": "wmem_" + secrets.token_hex(8), "user_id": user_id})
    response = requests.post(AUTH_URL + "/sign-in/email", headers={"Origin": FRONTEND}, json={"email": email, "password": password}, timeout=60)
    print("Neon sign-in HTTP", response.status_code)
    if not response.ok or not response.json().get("token"):
        raise RuntimeError("Sample account sign-in failed; no session token returned.")
    print("Sample account provisioned:", email)
    print("Workspace: ws_default; role: owner; status: active")
    print("Credentials saved to ignored .env.sample-admin (password not logged).")


if __name__ == "__main__":
    main()
