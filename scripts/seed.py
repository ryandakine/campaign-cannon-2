#!/usr/bin/env python3
"""Seed script — creates a demo campaign with 5 posts across 3 platforms.

Usage:
    python scripts/seed.py
"""

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def main():
    """Create a sample 'Demo Campaign' with 5 posts."""
    try:
        from campaign_cannon.db.connection import get_session
        from campaign_cannon.db.models import Campaign, Post, CampaignStatus, PostState, Platform
    except ImportError:
        print("[seed] Could not import campaign_cannon modules.")
        print("[seed] Generating seed payload as JSON instead.\n")
        _print_json_seed()
        return

    tomorrow_9am = (
        datetime.now(timezone.utc)
        .replace(hour=9, minute=0, second=0, microsecond=0)
        + timedelta(days=1)
    )

    campaign_id = uuid.uuid4()
    campaign = Campaign(
        id=campaign_id,
        name="Demo Campaign",
        slug="demo-campaign",
        description="Sample campaign created by seed script",
        status=CampaignStatus.DRAFT,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    posts = [
        Post(
            id=uuid.uuid4(),
            campaign_id=campaign_id,
            platform="twitter",
            body="Excited to share our latest update! Check it out. #demo #launch",
            state=PostState.DRAFT,
            scheduled_at=tomorrow_9am,
            idempotency_key=f"{campaign_id}-tweet-text-{tomorrow_9am.isoformat()}",
            retry_count=0,
            max_retries=3,
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
        Post(
            id=uuid.uuid4(),
            campaign_id=campaign_id,
            platform="twitter",
            body="Behind the scenes of our product development journey. #buildinpublic",
            state=PostState.DRAFT,
            scheduled_at=tomorrow_9am + timedelta(hours=1),
            idempotency_key=f"{campaign_id}-tweet-img-{(tomorrow_9am + timedelta(hours=1)).isoformat()}",
            retry_count=0,
            max_retries=3,
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
        Post(
            id=uuid.uuid4(),
            campaign_id=campaign_id,
            platform="reddit",
            title="We just launched something new — feedback welcome!",
            body="Hey everyone! We've been working on this for months and we're finally ready to share. Here's what we built and why...\n\nLooking forward to your thoughts!",
            state=PostState.DRAFT,
            scheduled_at=tomorrow_9am + timedelta(hours=2),
            idempotency_key=f"{campaign_id}-reddit-text-{(tomorrow_9am + timedelta(hours=2)).isoformat()}",
            retry_count=0,
            max_retries=3,
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
        Post(
            id=uuid.uuid4(),
            campaign_id=campaign_id,
            platform="reddit",
            title="Useful resource: How we solved X problem",
            body="We wrote up our approach to solving X. Link in comments.\n\nhttps://example.com/blog/solving-x",
            state=PostState.DRAFT,
            scheduled_at=tomorrow_9am + timedelta(hours=3),
            idempotency_key=f"{campaign_id}-reddit-link-{(tomorrow_9am + timedelta(hours=3)).isoformat()}",
            retry_count=0,
            max_retries=3,
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
        Post(
            id=uuid.uuid4(),
            campaign_id=campaign_id,
            platform="linkedin",
            body="Thrilled to announce our latest milestone! After months of development, we're ready to share what we've been building.\n\nKey highlights:\n- Feature A: Solves problem X\n- Feature B: 10x improvement over previous approach\n- Feature C: Community-driven development\n\nWould love to hear your thoughts! #innovation #launch #buildinpublic",
            state=PostState.DRAFT,
            scheduled_at=tomorrow_9am + timedelta(hours=4),
            idempotency_key=f"{campaign_id}-linkedin-text-{(tomorrow_9am + timedelta(hours=4)).isoformat()}",
            retry_count=0,
            max_retries=3,
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
    ]

    try:
        with get_session() as session:
            session.add(campaign)
            for post in posts:
                session.add(post)
            session.commit()
            print(f"[seed] Created campaign: {campaign.name} ({campaign.id})")
            print(f"[seed] Created {len(posts)} posts:")
            for p in posts:
                print(f"  - {p.platform}: {p.body[:50]}... @ {p.scheduled_at}")
            print("\n[seed] Done! Run 'campaign-cannon' to start the server.")
    except Exception as e:
        print(f"[seed] Error: {e}")
        print("[seed] Make sure the database is initialized (run migrations first).")
        sys.exit(1)


def _print_json_seed():
    """Print seed data as JSON for manual import."""
    import json

    tomorrow_9am = (
        datetime.now(timezone.utc)
        .replace(hour=9, minute=0, second=0, microsecond=0)
        + timedelta(days=1)
    )

    payload = {
        "name": "Demo Campaign",
        "slug": "demo-campaign",
        "description": "Sample campaign created by seed script",
        "posts": [
            {
                "slug": "tweet-text",
                "platform": "twitter",
                "body": "Excited to share our latest update! Check it out. #demo #launch",
                "scheduled_at": tomorrow_9am.isoformat(),
            },
            {
                "slug": "tweet-img",
                "platform": "twitter",
                "body": "Behind the scenes of our product development journey. #buildinpublic",
                "scheduled_at": (tomorrow_9am + timedelta(hours=1)).isoformat(),
            },
            {
                "slug": "reddit-text",
                "platform": "reddit",
                "title": "We just launched something new — feedback welcome!",
                "body": "Hey everyone! We've been working on this for months...",
                "scheduled_at": (tomorrow_9am + timedelta(hours=2)).isoformat(),
            },
            {
                "slug": "reddit-link",
                "platform": "reddit",
                "title": "Useful resource: How we solved X problem",
                "body": "We wrote up our approach. https://example.com/blog/solving-x",
                "scheduled_at": (tomorrow_9am + timedelta(hours=3)).isoformat(),
            },
            {
                "slug": "linkedin-text",
                "platform": "linkedin",
                "body": "Thrilled to announce our latest milestone! #innovation #launch",
                "scheduled_at": (tomorrow_9am + timedelta(hours=4)).isoformat(),
            },
        ],
    }
    print(json.dumps(payload, indent=2))
    print("\n[seed] Import this JSON via: POST /api/v1/campaigns")


if __name__ == "__main__":
    main()
