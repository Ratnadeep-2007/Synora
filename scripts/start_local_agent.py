"""Start this laptop as a Synora local agent for the Render deployment.

Only the two pieces that cannot run on Render are started locally:
  1. Vexa stack (Docker) - joins Google Meets and records them.
  2. Baileys bridge (Docker) - links WhatsApp and forwards group messages.

Everything else (frontend, backend API, Neon database) is the Render
deployment, shared with other users at https://synora-frontend.onrender.com

This script:
  - ensures Docker + the Vexa stack are up (gateway :18056),
  - (re)starts the Baileys bridge container pointed at the Render backend
    (webhook secret fetched from Render at runtime, never stored in git),
  - opens a Cloudflare quick tunnel to the Vexa gateway and writes the
    tunnel URL into the Render backend env (VEXA_BASE_URL), redeploying
    the backend if the URL changed,
  - prints a status summary.

Usage: python scripts/start_local_agent.py   (or start_agent.bat / start.bat option 7)
Stop:  docker stop synora-baileys; taskkill /IM cloudflared.exe /F;
       docker compose down in the Vexa directory.
"""
import re
import subprocess
import sys
import time
from pathlib import Path

import requests
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
BACKEND_SERVICE_ID = "srv-db85cm5g1s2s7393sd20"  # Render service "Synora"
RENDER_API = "https://api.render.com/v1"
RENDER_BACKEND_URL = "https://synora-oduz.onrender.com"
FRONTEND_URL = "https://synora-frontend.onrender.com"
VEXA_GATEWAY = "http://localhost:18056"
VEXA_DIR = Path(r"E:\webstack\trikaal\vexa-local")
LOG_DIR = ROOT / "artifacts" / "local-agent"


def ok(msg):
    print(f"[OK] {msg}", flush=True)


def warn(msg):
    print(f"[!]  {msg}", flush=True)


def fail(msg):
    print(f"[ERROR] {msg}", flush=True)
    sys.exit(1)


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def docker_ready() -> bool:
    return run(["docker", "info"]).returncode == 0


def ensure_docker():
    if docker_ready():
        ok("Docker is running")
        return
    desktop = Path(r"C:\Program Files\Docker\Docker\Docker Desktop.exe")
    if desktop.exists():
        warn("Docker not running - starting Docker Desktop...")
        subprocess.Popen([str(desktop)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            if docker_ready():
                ok("Docker is running")
                return
            time.sleep(5)
    fail("Docker is not running and could not be started. Start Docker Desktop manually.")


def vexa_healthy() -> bool:
    try:
        return requests.get(VEXA_GATEWAY + "/health", timeout=5).status_code == 200
    except requests.RequestException:
        return False


def ensure_vexa():
    if vexa_healthy():
        ok("Vexa gateway healthy on :18056")
        return
    if not VEXA_DIR.exists():
        fail(f"Vexa stack not running and {VEXA_DIR} not found. Start the Vexa compose stack first.")
    warn("Vexa gateway down - running docker compose up -d in the Vexa directory...")
    result = run(["docker", "compose", "up", "-d"], cwd=VEXA_DIR)
    if result.returncode != 0:
        fail("docker compose up failed:\n" + (result.stderr or result.stdout)[-500:])
    for _ in range(36):
        if vexa_healthy():
            ok("Vexa gateway healthy on :18056")
            return
        time.sleep(5)
    fail("Vexa gateway did not become healthy in 180s. Check: docker ps / docker compose logs.")


def render_headers() -> dict:
    cli_yaml = Path.home() / ".render" / "cli.yaml"
    match = re.search(r"^\s+key:\s*(\S+)", cli_yaml.read_text(), re.M)
    if not match:
        fail("Render CLI token not found. Run `render login` once, then retry.")
    return {"Authorization": "Bearer " + match.group(1)}


def get_render_env(headers) -> dict:
    r = requests.get(f"{RENDER_API}/services/{BACKEND_SERVICE_ID}/env-vars?limit=100", headers=headers, timeout=30)
    r.raise_for_status()
    return {row["envVar"]["key"]: row["envVar"]["value"] for row in r.json()}


def ensure_baileys(headers, render_env):
    secret = render_env.get("WHATSAPP_WEBHOOK_SECRET", "")
    if not secret:
        fail("WHATSAPP_WEBHOOK_SECRET missing on the Render backend; cannot wire the bridge.")
    image = "synora-baileys-bridge:latest"
    if run(["docker", "image", "inspect", image]).returncode != 0:
        warn("Building Baileys bridge image (first run)...")
        build = run(["docker", "build", "-t", image, str(ROOT / "services" / "baileys-bridge")])
        if build.returncode != 0:
            fail("Baileys image build failed:\n" + (build.stderr or "")[-500:])
    auth_dir = ROOT / "services" / "baileys-bridge" / "baileys_auth_info"
    auth_dir.mkdir(parents=True, exist_ok=True)
    run(["docker", "rm", "-f", "synora-baileys"])
    result = run([
        "docker", "run", "-d", "--name", "synora-baileys", "--restart", "unless-stopped",
        "-e", f"SYNORA_BACKEND_URL={RENDER_BACKEND_URL}",
        "-e", f"SYNORA_WHATSAPP_WEBHOOK_SECRET={secret}",
        "-v", f"{auth_dir}:/data/baileys_auth_info",
        image,
    ])
    if result.returncode != 0:
        fail("Could not start Baileys container:\n" + (result.stderr or "")[-500:])
    linked = (auth_dir / "creds.json").exists()
    ok("Baileys bridge running -> " + RENDER_BACKEND_URL)
    if not linked:
        warn("WhatsApp not linked yet. Scan the QR once: docker logs -f synora-baileys")
        warn("Phone: WhatsApp -> Settings -> Linked Devices -> Link a Device.")


def find_cloudflared() -> Path:
    for candidate in (
        Path(r"C:\Program Files (x86)\cloudflared\cloudflared.exe"),
        Path(r"C:\Program Files\cloudflared\cloudflared.exe"),
    ):
        if candidate.exists():
            return candidate
    found = run(["where", "cloudflared"])
    if found.returncode == 0 and found.stdout.strip():
        return Path(found.stdout.strip().splitlines()[0])
    fail("cloudflared not found. Install: winget install Cloudflare.cloudflared")


def start_tunnel() -> str:
    exe = find_cloudflared()
    run(["taskkill", "/IM", "cloudflared.exe", "/F"])  # replace any previous quick tunnel
    time.sleep(2)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "cloudflared.log"
    log_file = open(log_path, "w", encoding="utf-8")
    subprocess.Popen(
        [str(exe), "tunnel", "--url", VEXA_GATEWAY, "--no-autoupdate"],
        stdout=log_file, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
    )
    for _ in range(30):
        time.sleep(2)
        text = log_path.read_text(encoding="utf-8", errors="ignore")
        match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", text)
        if match:
            ok(f"Cloudflare tunnel: {match.group(0)}")
            return match.group(0)
    fail(f"Tunnel URL not found in {log_path}. Is the Vexa gateway up?")


def point_render_at_tunnel(headers, render_env, tunnel_url):
    local_env = dotenv_values(ROOT / ".env")
    desired = {
        "VEXA_ENABLED": "true",
        "VEXA_BASE_URL": tunnel_url,
        "VEXA_API_KEY": local_env.get("VEXA_API_KEY", ""),
        "VEXA_BOT_NAME": local_env.get("VEXA_BOT_NAME", "Synora"),
    }
    if not desired["VEXA_API_KEY"]:
        fail("VEXA_API_KEY missing in repo .env; Render backend cannot authenticate to Vexa.")
    if all(render_env.get(k) == v for k, v in desired.items()):
        ok("Render backend already points at this tunnel")
        return
    merged = dict(render_env)
    merged.update(desired)
    payload = [{"key": k, "value": v} for k, v in merged.items()]
    r = requests.put(f"{RENDER_API}/services/{BACKEND_SERVICE_ID}/env-vars", headers=headers, json=payload, timeout=30)
    r.raise_for_status()
    dep = requests.post(f"{RENDER_API}/services/{BACKEND_SERVICE_ID}/deploys", headers=headers, json={}, timeout=30)
    print(f"[OK] Render backend env updated (VEXA_BASE_URL={tunnel_url}); redeploy: HTTP {dep.status_code}", flush=True)
    warn("Backend takes ~1-2 min to redeploy before it can drive the bot.")


def main():
    print("=== Synora local agent (Vexa + Baileys -> Render) ===", flush=True)
    ensure_docker()
    ensure_vexa()
    headers = render_headers()
    render_env = get_render_env(headers)
    ensure_baileys(headers, render_env)
    tunnel_url = start_tunnel()
    point_render_at_tunnel(headers, render_env, tunnel_url)
    print()
    print("Agent is UP. Other users just open: " + FRONTEND_URL)
    print("  - Meet bot: start captures from the Render UI (bot joins from this laptop)")
    print("  - WhatsApp: bridge logs/QR -> docker logs -f synora-baileys")
    print("Keep this laptop on with Docker running while the agent is needed.")


if __name__ == "__main__":
    main()
