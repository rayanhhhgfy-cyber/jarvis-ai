# ====================================================================
# JARVIS OMEGA — PWA + Web Push tests
# ====================================================================
"""
Verifies the installable-PWA surface and the Web Push endpoints:
manifest + service worker + icons served from the backend, the
dashboard HTML carrying the Apple/PWA tags and the Connectors tab, and
the notification subscribe/send flow (with VAPID keys unset in tests,
send must fail plainly with 503 rather than pretending to deliver).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app


def test_manifest_served_with_correct_content():
    with TestClient(app) as client:
        resp = client.get("/manifest.json")
    assert resp.status_code == 200
    assert "application/manifest+json" in resp.headers["content-type"]
    manifest = resp.json()
    assert manifest["name"] == "J.A.R.V.I.S. OMEGA"
    assert manifest["short_name"] == "JARVIS"
    assert manifest["display"] == "standalone"
    assert manifest["theme_color"] == "#00d4ff"
    assert manifest["background_color"] == "#0a0a1a"
    assert manifest["start_url"] == "/"
    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert "192x192" in sizes
    assert "512x512" in sizes


def test_service_worker_served_with_push_handler():
    with TestClient(app) as client:
        resp = client.get("/sw.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]
    assert "no-cache" in resp.headers.get("cache-control", "")
    assert 'addEventListener("push"' in resp.text
    assert 'addEventListener("notificationclick"' in resp.text
    assert "showNotification" in resp.text


def test_pwa_icons_exist_at_declared_sizes():
    with TestClient(app) as client:
        for name, expected_size in (
            ("icon-192.png", 192),
            ("icon-512.png", 512),
            ("apple-touch-icon.png", 180),
        ):
            resp = client.get(f"/icons/{name}")
            assert resp.status_code == 200, name
            assert "image/png" in resp.headers["content-type"]
            assert len(resp.content) > 1000, name
        # Allowlist only: no arbitrary file access.
        assert client.get("/icons/secret.png").status_code == 404


def test_dashboard_html_has_pwa_tags_and_connectors_tab():
    with TestClient(app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert 'rel="manifest" href="/manifest.json"' in html
    assert 'apple-mobile-web-app-capable' in html
    assert 'apple-mobile-web-app-status-bar-style' in html
    assert 'apple-mobile-web-app-title' in html
    assert 'apple-touch-icon' in html
    assert 'id="tab-connectors"' in html
    assert 'loadConnectors' in html
    assert 'enableNotifications' in html
    assert 'toggleVoiceInput' in html
    assert 'registerServiceWorker' in html
    # API base must be same-origin (works on Render/iPhone). The old
    # hardcoded localhost line is gone; localhost survives only as the
    # file:// preview fallback, which never triggers when served.
    assert "window.location.origin" in html
    assert "const API = 'http://localhost:8000'" not in html


def test_vapid_public_key_endpoint_reports_unconfigured_in_tests():
    with TestClient(app) as client:
        resp = client.get("/api/notifications/vapid-public-key")
    assert resp.status_code == 200
    data = resp.json()
    assert "public_key" in data
    assert data["configured"] is False  # no VAPID keys in the test env


def test_push_subscribe_validation_and_save():
    with TestClient(app) as client:
        bad = client.post("/api/notifications/subscribe", json={
            "device_id": "test-device", "subscription": {"endpoint": "https://example.com/push"},
        })
        assert bad.status_code == 422  # keys missing
        good = client.post("/api/notifications/subscribe", json={
            "device_id": "test-device",
            "subscription": {
                "endpoint": "https://example.com/push/abc",
                "keys": {"p256dh": "fake-p256dh", "auth": "fake-auth"},
            },
        })
        assert good.status_code == 200
        assert good.json()["subscribed"] is True
        unsub = client.post("/api/notifications/unsubscribe", json={
            "device_id": "test-device",
            "subscription": {
                "endpoint": "https://example.com/push/abc",
                "keys": {"p256dh": "fake-p256dh", "auth": "fake-auth"},
            },
        })
        assert unsub.status_code == 200
        assert unsub.json()["subscribed"] is False


def test_push_send_without_vapid_keys_fails_plainly():
    with TestClient(app) as client:
        resp = client.post("/api/notifications/send", json={
            "title": "test", "body": "test body",
        })
    assert resp.status_code == 503
    assert "VAPID_PRIVATE_KEY" in resp.json()["detail"]


def test_connectors_listed_on_full_app():
    with TestClient(app) as client:
        resp = client.get("/api/connectors")
    assert resp.status_code == 200
    data = resp.json()
    ids = {c["id"] for c in data["connectors"]}
    assert ids == {"messenger", "instagram"}
    assert "responder" in data
    assert data["responder"]["enabled"] is False  # off by default
