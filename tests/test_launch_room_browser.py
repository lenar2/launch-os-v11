"""Browser walkthrough of the local Launch Room.

Requires Playwright and Chromium in the environment that runs this file.
The default unit run skips it when Playwright is not installed.
"""

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


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def test_owner_browser_completes_the_room_and_a_second_browser_cannot(tmp_path: Path) -> None:
    database = tmp_path / "browser-room.sqlite"
    runtime = LaunchRoomRuntime.open(f"sqlite+pysqlite:///{database}", environment="test")
    app = create_app(settings=Settings(LAUNCH_OS_ENV="test"), launch_room=runtime)
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = 0
    while not server.started and deadline < 50:
        thread.join(0.1)
        deadline += 1
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
            page.fill("input[name='offer_name']", "Pilot cohort")
            page.fill("textarea[name='goal']", "Get a clear yes on the shorter cohort.")
            page.fill("input[name='audience']", "Past students")
            page.fill("input[name='known_fact']", "Three people asked for a shorter cohort.")
            page.click("#open-room")
            page.wait_for_selector("#next-step")
            assert "UNKNOWN" in page.locator("#unknown").inner_text()
            assert "NOT_PROVEN" in page.content()
            assert "Three people asked for a shorter cohort." in page.locator("#known").inner_text()
            assert "owner_user_id" not in page.content()
            room_url = page.url
            page.click("#ask-team")
            page.wait_for_selector("#decision")
            assert "Do not publish" in page.locator("#decision").inner_text()
            assert "Publish immediately" in page.locator("#alternatives").inner_text()
            page.fill("#revision-note", "Mention Thursday review hours.")
            page.locator("form[action$='/revision'] button").click()
            page.wait_for_selector("#next-step")
            page.click("#ask-team")
            page.wait_for_selector("#decision")
            assert "Thursday review hours" in page.content()
            page.click("#approve")
            page.wait_for_selector("#next-step")
            assert "APPROVED" in page.content()
            page.click("#prepare-draft")
            page.wait_for_selector("#draft-body")
            assert "Thursday review hours" in page.locator("#draft-text").inner_text()
            edited = "Pilot cohort\n\nThe owner rewrote this unpublished draft."
            page.fill("#draft-body", edited)
            page.click("#save-draft")
            page.wait_for_selector("#draft-text")
            assert edited in page.locator("#draft-text").inner_text()
            assert "UNKNOWN" in page.locator("#unknown").inner_text()
            assert "publications 0" in page.content()
            stranger = browser.new_context()
            other = stranger.new_page()
            other.set_default_timeout(15_000)
            denied = other.goto(room_url)
            assert denied is not None
            assert denied.status == 404
            assert "The owner rewrote this unpublished draft." not in other.content()
            assert "Get a clear yes" not in other.content()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(5)
