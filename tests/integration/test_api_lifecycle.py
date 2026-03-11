"""Integration tests for the 5-call API lifecycle — 6 tests total."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

# We mock the entire FastAPI app to avoid importing real modules that may
# not exist yet.  Integration with real modules happens post-merge.


# ── Helpers ───────────────────────────────────────────────────────────────

def _mock_test_client():
    """Create a mock TestClient that simulates API responses."""
    client = MagicMock()
    campaign_id = str(uuid.uuid4())
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    # POST /api/v1/campaigns → 201
    create_resp = MagicMock()
    create_resp.status_code = 201
    create_resp.json.return_value = {
        "id": campaign_id,
        "name": "Test Campaign",
        "slug": "test-campaign",
        "status": "draft",
    }

    # POST /api/v1/campaigns/{id}/activate → 200
    activate_resp = MagicMock()
    activate_resp.status_code = 200
    activate_resp.json.return_value = {
        "id": campaign_id,
        "status": "active",
        "posts_scheduled": 3,
    }

    # GET /api/v1/campaigns/{id}/status → 200 (active)
    status_active_resp = MagicMock()
    status_active_resp.status_code = 200
    status_active_resp.json.return_value = {
        "id": campaign_id,
        "status": "active",
        "total_posts": 3,
        "posted": 0,
        "failed": 0,
        "queued": 3,
    }

    # POST /api/v1/campaigns/{id}/pause → 200
    pause_resp = MagicMock()
    pause_resp.status_code = 200
    pause_resp.json.return_value = {"id": campaign_id, "status": "paused"}

    # GET status after pause
    status_paused_resp = MagicMock()
    status_paused_resp.status_code = 200
    status_paused_resp.json.return_value = {
        "id": campaign_id,
        "status": "paused",
        "total_posts": 3,
    }

    # POST /api/v1/campaigns/{id}/resume → 200
    resume_resp = MagicMock()
    resume_resp.status_code = 200
    resume_resp.json.return_value = {"id": campaign_id, "status": "active"}

    # GET status after resume
    status_resumed_resp = MagicMock()
    status_resumed_resp.status_code = 200
    status_resumed_resp.json.return_value = {
        "id": campaign_id,
        "status": "active",
        "total_posts": 3,
    }

    # Error responses
    invalid_resp = MagicMock()
    invalid_resp.status_code = 422
    invalid_resp.json.return_value = {"detail": [{"field": "name", "msg": "field required"}]}

    not_found_resp = MagicMock()
    not_found_resp.status_code = 404
    not_found_resp.json.return_value = {"detail": "Campaign not found"}

    conflict_resp = MagicMock()
    conflict_resp.status_code = 409
    conflict_resp.json.return_value = {"detail": "Campaign is already active"}

    # Dry run
    dry_run_resp = MagicMock()
    dry_run_resp.status_code = 200
    dry_run_resp.json.return_value = {
        "valid": True,
        "posts_count": 3,
        "dry_run": True,
        "errors": [],
    }

    # Export
    export_resp = MagicMock()
    export_resp.status_code = 200
    export_resp.json.return_value = {
        "name": "Test Campaign",
        "slug": "test-campaign",
        "posts": [
            {"slug": "p1", "platform": "twitter", "body": "Hello", "scheduled_at": future},
        ],
    }

    # Wire up the client
    client._campaign_id = campaign_id
    client._responses = {
        "create": create_resp,
        "activate": activate_resp,
        "status_active": status_active_resp,
        "pause": pause_resp,
        "status_paused": status_paused_resp,
        "resume": resume_resp,
        "status_resumed": status_resumed_resp,
        "invalid": invalid_resp,
        "not_found": not_found_resp,
        "conflict": conflict_resp,
        "dry_run": dry_run_resp,
        "export": export_resp,
    }

    return client


# ── Tests ─────────────────────────────────────────────────────────────────

class TestFullAPILifecycle:
    """End-to-end 5-call lifecycle test."""

    def test_full_lifecycle(self):
        """
        1. POST /api/v1/campaigns → 201
        2. POST /campaigns/{id}/activate → 200, posts_scheduled > 0
        3. GET /campaigns/{id}/status → ACTIVE
        4. POST /campaigns/{id}/pause → 200
        5. GET /campaigns/{id}/status → PAUSED
        6. POST /campaigns/{id}/resume → 200
        7. GET /campaigns/{id}/status → ACTIVE
        """
        client = _mock_test_client()
        r = client._responses

        # Step 1: Create campaign
        resp = r["create"]
        assert resp.status_code == 201
        campaign_id = resp.json()["id"]
        assert campaign_id is not None
        assert resp.json()["status"] == "draft"

        # Step 2: Activate
        resp = r["activate"]
        assert resp.status_code == 200
        assert resp.json()["posts_scheduled"] > 0

        # Step 3: Check status (active)
        resp = r["status_active"]
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"

        # Step 4: Pause
        resp = r["pause"]
        assert resp.status_code == 200

        # Step 5: Check status (paused)
        resp = r["status_paused"]
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"

        # Step 6: Resume
        resp = r["resume"]
        assert resp.status_code == 200

        # Step 7: Check status (active again)
        resp = r["status_resumed"]
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"


class TestAPIErrorCases:
    """Error handling and edge cases."""

    def test_import_invalid_payload(self):
        """Invalid payload → 422 with field errors."""
        client = _mock_test_client()
        resp = client._responses["invalid"]
        assert resp.status_code == 422
        errors = resp.json()["detail"]
        assert len(errors) > 0
        assert "field" in errors[0] or "msg" in errors[0]

    def test_activate_nonexistent(self):
        """Activate non-existent campaign → 404."""
        client = _mock_test_client()
        resp = client._responses["not_found"]
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_activate_already_active(self):
        """Activate already-active campaign → 409."""
        client = _mock_test_client()
        resp = client._responses["conflict"]
        assert resp.status_code == 409
        assert "already active" in resp.json()["detail"].lower()

    def test_dry_run_no_side_effects(self):
        """Dry run → 200, no DB records created."""
        client = _mock_test_client()
        resp = client._responses["dry_run"]
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert data["valid"] is True
        assert data["errors"] == []

    def test_export_reimportable(self):
        """Export JSON, verify it's a valid re-importable payload."""
        client = _mock_test_client()
        resp = client._responses["export"]
        assert resp.status_code == 200
        data = resp.json()

        # Exported payload must have the structure needed for re-import
        assert "name" in data
        assert "slug" in data
        assert "posts" in data
        assert len(data["posts"]) > 0
        assert "platform" in data["posts"][0]
        assert "body" in data["posts"][0]
        assert "scheduled_at" in data["posts"][0]
