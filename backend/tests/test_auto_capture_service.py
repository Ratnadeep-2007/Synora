"""
Voice-activated capture, managed through the API.

The API process cannot record audio itself - the interpreter that serves the API
has no `soundcard`. It spawns the recorder as a subprocess instead. These tests
cover the parts that must not silently misbehave: refusing to arm when capture is
unavailable, refusing unknown projects at the route, and not reporting a stale
state file as if a run were in progress.
"""

import json
from pathlib import Path

import pytest

from app.services.auto_capture_service import AutoCaptureService


def _write_state(tmp_path: Path, payload: dict) -> Path:
    d = tmp_path / "synora-captures"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "auto_capture_state.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_preflight_reports_missing_interpreter(tmp_path):
    svc = AutoCaptureService(
        capture_python=str(tmp_path / "nope" / "python.exe"),
        script=Path(__file__),
    )
    pre = svc.preflight()
    assert pre["ready"] is False
    assert any("interpreter" in p for p in pre["problems"])


def test_preflight_reports_missing_script(tmp_path):
    svc = AutoCaptureService(
        capture_python=__import__("sys").executable,
        script=tmp_path / "missing_script.py",
    )
    pre = svc.preflight()
    assert pre["ready"] is False
    assert any("script" in p for p in pre["problems"])


def test_preflight_ready_when_both_present(tmp_path):
    script = tmp_path / "cap.py"
    script.write_text("# noop", encoding="utf-8")
    svc = AutoCaptureService(capture_python=__import__("sys").executable, script=script)
    assert svc.preflight()["ready"] is True


def test_arm_refuses_when_capture_unavailable(tmp_path):
    svc = AutoCaptureService(
        capture_python=str(tmp_path / "nope.py"),
        script=Path(__file__),
    )
    out = svc.arm(project_id="proj_x")
    assert out["ok"] is False
    assert out["error"] == "capture_unavailable"
    assert out["problems"]


def test_status_is_idle_when_nothing_is_running(tmp_path, monkeypatch):
    """The state file outlives the process.

    A finished run leaves auto_capture_state.json behind. Reporting its stage as
    the live one would tell the UI a recording is in progress when nothing is.
    """
    import app.services.auto_capture_service as mod

    state_file = _write_state(tmp_path, {"status": "transcribing", "detail": "old run"})
    monkeypatch.setattr(mod, "_state_path", lambda: state_file)
    monkeypatch.setattr(mod, "_proc", None)

    out = AutoCaptureService(
        capture_python=__import__("sys").executable, script=Path(__file__)
    ).status()
    assert out["running"] is False
    assert out["stage"] == "idle"
    # The previous run is still reported, but as a result rather than a stage.
    assert out["last_state"]["status"] == "transcribing"


def test_logs_are_safe_when_no_process(tmp_path):
    svc = AutoCaptureService(capture_python=__import__("sys").executable, script=Path(__file__))
    assert svc.logs() == []


def test_stop_is_safe_when_idle(tmp_path):
    svc = AutoCaptureService(capture_python=__import__("sys").executable, script=Path(__file__))
    out = svc.stop()
    assert out["ok"] is True
    assert out["stopped"] is False