import os
import sys
from pathlib import Path
import json
import urllib.request
import urllib.parse
import urllib.error

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import dotenv_values

env_root = dotenv_values(ROOT / ".env")
env_backend = dotenv_values(ROOT / "backend" / ".env")
combined_env = {**env_root, **env_backend, **os.environ}


def check_all_keys():
    report = {}

    # 1. Groq API
    groq_key = combined_env.get("GROQ_API_KEY", "").strip("\"' ")
    if not groq_key:
        report["Groq API"] = {"status": "MISSING", "details": "GROQ_API_KEY not configured"}
    else:
        masked = groq_key[:7] + "..." + groq_key[-4:]
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {groq_key}", "User-Agent": "Synora/1.0"}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                models = [m.get("id") for m in data.get("data", [])]
                report["Groq API"] = {
                    "valid": True,
                    "status": "VALID & ACTIVE",
                    "key": masked,
                    "whisper_audio_ready": "whisper-large-v3-turbo" in models or any("whisper" in m for m in models),
                    "chat_completion_ready": True,
                    "active_models_count": len(models),
                }
        except Exception as exc:
            report["Groq API"] = {"valid": False, "status": "FAILED", "key": masked, "error": str(exc)}

    # 2. NVIDIA NIM API
    nv_key = combined_env.get("NVIDIA_API_KEY", "").strip("\"' ")
    if not nv_key:
        report["NVIDIA NIM API"] = {"status": "MISSING", "details": "NVIDIA_API_KEY not configured"}
    else:
        masked = nv_key[:7] + "..." + nv_key[-4:]
        req = urllib.request.Request(
            "https://integrate.api.nvidia.com/v1/models",
            headers={"Authorization": f"Bearer {nv_key}", "User-Agent": "Synora/1.0"}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                models = [m.get("id") for m in data.get("data", [])]
                report["NVIDIA NIM API"] = {
                    "valid": True,
                    "status": "VALID & ACTIVE",
                    "key": masked,
                    "models_registered": len(models),
                    "llama_vision_ready": "meta/llama-3.2-11b-vision-instruct" in models,
                    "deepseek_ready": any("deepseek" in m for m in models),
                }
        except Exception as exc:
            report["NVIDIA NIM API"] = {"valid": False, "status": "FAILED", "key": masked, "error": str(exc)}

    # 3. Google OAuth Client ID & Secret
    g_cid = combined_env.get("GOOGLE_CLIENT_ID", "").strip("\"' ")
    g_sec = combined_env.get("GOOGLE_CLIENT_SECRET", "").strip("\"' ")
    g_refresh = combined_env.get("GOOGLE_REFRESH_TOKEN", "").strip("\"' ")

    google_rep = {}
    if g_cid and g_sec:
        # Check against Google OAuth Token Endpoint
        payload = urllib.parse.urlencode({
            "code": "dummy_test_code_to_verify_credentials",
            "client_id": g_cid,
            "client_secret": g_sec,
            "redirect_uri": "http://localhost:8000/auth/google/callback",
            "grant_type": "authorization_code",
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                google_rep["credentials"] = {"valid": True, "status": "VALID"}
        except urllib.error.HTTPError as err:
            err_json = {}
            try:
                err_json = json.loads(err.read().decode())
            except Exception:
                pass
            # If client_id/secret are valid, Google returns 'invalid_grant' for dummy code.
            # If client_id or secret is rejected, Google returns 'invalid_client'.
            if err_json.get("error") == "invalid_grant":
                google_rep["credentials"] = {
                    "valid": True,
                    "status": "VALID & AUTHENTICATED BY GOOGLE",
                    "client_id": g_cid[:14] + "..." + g_cid[-14:],
                    "client_secret": g_sec[:6] + "..." + g_sec[-4:],
                }
            elif err_json.get("error") == "invalid_client":
                google_rep["credentials"] = {
                    "valid": False,
                    "status": "REJECTED BY GOOGLE (Invalid Client ID or Secret)",
                    "error": err_json.get("error_description"),
                }
            else:
                google_rep["credentials"] = {
                    "valid": False,
                    "status": f"HTTP {err.code}",
                    "details": err_json,
                }
        except Exception as exc:
            google_rep["credentials"] = {"valid": False, "status": "ERROR", "error": str(exc)}
    else:
        google_rep["credentials"] = {"valid": False, "status": "INCOMPLETE (Client ID or Secret missing)"}

    # Refresh Token check
    if g_refresh:
        token_payload = urllib.parse.urlencode({
            "client_id": g_cid,
            "client_secret": g_sec,
            "refresh_token": g_refresh,
            "grant_type": "refresh_token",
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=token_payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                token_data = json.loads(resp.read().decode())
                google_rep["refresh_token"] = {
                    "valid": True,
                    "status": "VALID & ACTIVE",
                    "token_exchange": "SUCCESS",
                }
        except urllib.error.HTTPError as err:
            google_rep["refresh_token"] = {
                "valid": False,
                "status": f"REJECTED BY GOOGLE (HTTP {err.code})",
                "details": err.read().decode(errors="ignore"),
            }
        except Exception as exc:
            google_rep["refresh_token"] = {"valid": False, "status": "ERROR", "error": str(exc)}
    else:
        google_rep["refresh_token"] = {
            "status": "NOT SET IN .ENV (Uses Web OAuth Login)",
            "details": "Click 'Connect' under Google Meet on the Sources page to link an account."
        }

    report["Google OAuth"] = google_rep
    return report


if __name__ == "__main__":
    rep = check_all_keys()
    print(json.dumps(rep, indent=2))
