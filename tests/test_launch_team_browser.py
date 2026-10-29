"""Chromium walkthrough of the local launch team."""

from __future__ import annotations

import socket
import threading
from pathlib import Path

import httpx
import pytest
import uvicorn

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

from launch_os_v11.api.app import create_app  # noqa: E402
from launch_os_v11.platform.config import Settings  # noqa: E402
from launch_os_v11.product.runtime import LaunchRoomRuntime  # noqa: E402


def test_owner_browser_runs_the_launch_team(tmp_path: Path) -> None:
    database = tmp_path / "team-browser.sqlite"
    runtime = LaunchRoomRuntime.open(f"sqlite+pysqlite:///{database}", environment="test")
    app = create_app(settings=Settings(LAUNCH_OS_ENV="test"), launch_room=runtime)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        thread.join(0.1)
    assert server.started
    base = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(base_url=base, timeout=5) as client:
            assert client.get("/health/live").status_code == 200
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            owner = browser.new_context()
            page = owner.new_page()
            page.set_default_timeout(60_000)
            page.goto(f"{base}/launch-room")
            page.fill("input[name='business_name']", "Northwind Studio")
            page.fill("input[name='offer_name']", "Three-week course")
            page.fill(
                "textarea[name='goal']",
                "Launch a course for the existing audience in three weeks.",
            )
            page.click("#open-room")
            page.wait_for_selector("#run-launch-team")
            page.click("#run-launch-team")
            page.wait_for_selector("#team-critic")
            assert "NOT_YET_PROVEN" in page.content()
            assert "TEST_DOUBLE" in page.content()
            assert "UNKNOWN" in page.locator("#team-roles").inner_text()
            assert "publications 0" in page.content()
            page.fill("#team-budget", "50000")
            page.fill("#team-weeks", "2")
            page.fill("#team-offer-wording", "Include office hours in the unpublished draft")
            page.click("#apply-team-change")
            page.wait_for_selector("#team-critic")
            text = page.locator("#launch-team").inner_text()
            assert "2-week sequence" in text
            assert "unpublished draft" in text
            assert "v1" in page.locator("#team-audience").inner_text()
            room_url = page.url
            other = browser.new_context()
            denied = other.new_page()
            response = denied.goto(room_url)
            assert response is not None
            assert response.status == 404
            assert "unpublished draft" not in denied.content()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(5)
