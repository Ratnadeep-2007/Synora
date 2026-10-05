"""
Voice-activated meeting capture, managed from the API.

The capture itself lives in a standalone script rather than in the API process.
That is deliberate: capturing audio needs `soundcard` and `numpy`, and the
interpreter running the API does not carry those. Spawning the script as a
subprocess keeps an audio dependency out of the web server and means a capture
crash cannot take the API down.

Lifecycle: arm -> armed (waiting for voice) -> recording -> processing ->
ingested, or failed. The script publishes progress to a small JSON state file
which this service reads, so the UI can poll instead of scraping a console.
"""

import json
import logging
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Interpreter that has the audio dependencies. Overridable because the API's own
# interpreter deliberately does not have them.
CAPTURE_PYTHON = os.environ.get(
    "SYNORA_CAPTURE_PYTHON", r"C:\Users\ratna\anaconda3\python.exe"
)
CAPTURE_SCRIPT = Path(
    os.environ.get(
        "SYNORA_CAPTURE_SCRIPT",
        str(Path(os.environ.get("TEMP", ".")) / "opencode" / "auto_capture_meeting.py"),
    )
)

_lock = threading.Lock()
_proc: Optional[subprocess.Popen] = None
_job: Dict[str, Any] = {}


def _state_path() -> Path:
    d = Path(os.environ.get("TEMP", ".")) / "synora-captures"
    d.mkdir(parents=True, exist_ok=True)
    return d / "auto_capture_state.json"


def _read_state() -> Dict[str, Any]:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _running() -> bool:
    return _proc is not None and _proc.poll() is None


class AutoCaptureService:
    def __init__(self, capture_python: Optional[str] = None, script: Optional[Path] = None):
        self.python = capture_python or CAPTURE_PYTHON
        self.script = Path(script) if script else CAPTURE_SCRIPT

    # ------------------------------------------------------------------
    def preflight(self) -> Dict[str, Any]:
        """Report whether capture can actually run, and why not if it cannot."""
        py_ok = Path(self.python).exists()
        script_ok = self.script.exists()
        missing: List[str] = []
        if not py_ok:
            missing.append(f"capture interpreter not found: {self.python}")
        if not script_ok:
            missing.append(f"capture script not found: {self.script}")
        return {
            "ready": py_ok and script_ok,
            "python": self.python,
            "script": str(self.script),
            "problems": missing,
        }

    # ------------------------------------------------------------------
    def arm(
        self,
        project_id: str,
        candidate_project_ids: Optional[List[str]] = None,
        max_minutes: int = 20,
        speakers: int = 0,
        keep_audio: bool = True,
    ) -> Dict[str, Any]:
        global _proc, _job

        pre = self.preflight()
        if not pre["ready"]:
            return {"ok": False, "error": "capture_unavailable", "problems": pre["problems"]}

        with _lock:
            if _running():
                self._terminate_locked()

            # The script refuses to start if the state file belongs to a live run.
            _state_path().unlink(missing_ok=True)

            cmd = [
                self.python, "-u", str(self.script),
                "--auto",
                "--project", project_id,
                "--max-minutes", str(max_minutes),
                "--keep-audio",
            ]
            if candidate_project_ids:
                cmd += ["--projects", ",".join(candidate_project_ids)]
            if speakers and speakers > 1:
                cmd += ["--speakers", str(speakers)]

            creationflags = 0
            if os.name == "nt":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            try:
                _proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=str(Path(r"E:\webstack\trikaal\synora_2")),
                    creationflags=creationflags,
                )
            except Exception as exc:
                _proc = None
                logger.error("auto_capture_spawn_failed: %s", exc)
                return {"ok": False, "error": "spawn_failed", "detail": str(exc)}

            _job = {
                "job_id": f"acap_{uuid.uuid4().hex[:12]}",
                "project_id": project_id,
                "candidate_project_ids": candidate_project_ids or [],
                "started_at": datetime.now(timezone.utc).isoformat(),
                "pid": _proc.pid,
                "command": cmd,
            }

        logger.info("auto_capture_armed: job=%s project=%s candidates=%s", _job["job_id"], project_id, candidate_project_ids)
        return {"ok": True, **_job, "preflight": pre}

    # ------------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        running = _running()
        state = _read_state() if running else {}
        # The state file outlives the process, so it must not be reported as the
        # live stage once nothing is running. A finished run's state is still
        # returned, but under last_state so the UI can show it as a result
        # rather than as something currently happening.
        if running:
            stage = state.get("status") or "starting"
        else:
            stage = "idle"
        return {
            "running": running,
            "stage": stage,
            "job": _job or None,
            "state": state or None,
            "last_state": None if running else (_read_state() or None),
        }

    # ------------------------------------------------------------------
    def stop(self) -> Dict[str, Any]:
        global _proc
        with _lock:
            stopped = self._terminate_locked()
        return {"ok": True, "stopped": stopped, "status": self.status()}

    # ------------------------------------------------------------------
    def _terminate_locked(self) -> bool:
        global _proc
        if not _running():
            _proc = None
            return False
        try:
            _proc.terminate()
            try:
                _proc.wait(timeout=8)
            except Exception:
                _proc.kill()
        except Exception as exc:
            logger.warning("auto_capture_terminate_failed: %s", exc)
        _proc = None
        return True

    # ------------------------------------------------------------------
    def logs(self, limit: int = 80) -> List[str]:
        """Recent console output from the capture script, for UI display."""
        if _proc is None or _proc.stdout is None:
            return []
        try:
            return [ln.rstrip() for ln in _proc.stdout.readlines()[-limit:]]
        except Exception:
            return []
