"""
Supabase database operations for multi-user Nils Sjöberg.
Handles profiles and conversation history per user.
"""

import os
import json
from datetime import date, datetime, timedelta, timezone
from supabase import create_client, Client

TRIAL_DAYS = 30


def get_client() -> Client:
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_ANON_KEY", "")
    return create_client(url, key)


def get_admin_client() -> Client:
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return create_client(url, key)


# ── Auth ────────────────────────────────────────────────────────────

def sign_up(email: str, password: str, name: str = "") -> dict:
    client = get_client()
    result = client.auth.sign_up({
        "email": email,
        "password": password,
        "options": {"data": {"name": name}},
    })
    return result


def sign_in(email: str, password: str) -> dict:
    client = get_client()
    result = client.auth.sign_in_with_password({
        "email": email,
        "password": password,
    })
    return result


# ── Profiles ────────────────────────────────────────────────────────

def get_profile(user_id: str, access_token: str) -> dict | None:
    client = get_client()
    client.postgrest.auth(access_token)
    result = client.table("profiles").select("*").eq("id", user_id).execute()
    if result.data:
        return result.data[0]
    return None


def update_profile(user_id: str, access_token: str, data: dict) -> dict:
    client = get_client()
    client.postgrest.auth(access_token)
    result = client.table("profiles").update(data).eq("id", user_id).execute()
    return result.data[0] if result.data else {}


def set_admin(email: str):
    """Mark a user as admin (run with service key)."""
    admin = get_admin_client()
    admin.table("profiles").update({"is_admin": True}).eq("email", email).execute()


# ── Conversations ───────────────────────────────────────────────────

def get_conversation(user_id: str, access_token: str) -> dict | None:
    client = get_client()
    client.postgrest.auth(access_token)
    result = (
        client.table("conversations")
        .select("*")
        .eq("user_id", user_id)
        .order("updated_at", desc=True)
        .limit(1)
        .execute()
    )
    if result.data:
        return result.data[0]
    return None


def save_conversation(user_id: str, access_token: str, messages: list, conv_id: str = None) -> str:
    client = get_client()
    client.postgrest.auth(access_token)
    if conv_id:
        client.table("conversations").update({
            "messages": messages,
        }).eq("id", conv_id).execute()
        return conv_id
    else:
        result = client.table("conversations").insert({
            "user_id": user_id,
            "messages": messages,
        }).execute()
        return result.data[0]["id"] if result.data else ""


def delete_conversation(user_id: str, access_token: str, conv_id: str):
    client = get_client()
    client.postgrest.auth(access_token)
    client.table("conversations").delete().eq("id", conv_id).eq("user_id", user_id).execute()


# ── Subscriptions ──────────────────────────────────────────────────

def get_subscription(user_id: str, access_token: str) -> dict | None:
    client = get_client()
    client.postgrest.auth(access_token)
    result = client.table("subscriptions").select("*").eq("user_id", user_id).execute()
    if result.data:
        return result.data[0]
    return None


def ensure_trial(user_id: str, access_token: str) -> dict:
    """Create a trial subscription if user has none. Returns subscription."""
    sub = get_subscription(user_id, access_token)
    if sub:
        return sub
    # Create trial
    trial_end = (datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS)).isoformat()
    admin = get_admin_client()
    result = admin.table("subscriptions").insert({
        "user_id": user_id,
        "tier": "premium",
        "status": "trialing",
        "trial_ends_at": trial_end,
    }).execute()
    return result.data[0] if result.data else {"status": "trialing", "tier": "premium", "trial_ends_at": trial_end}


def update_subscription(user_id: str, data: dict):
    """Update subscription (service key, bypasses RLS)."""
    admin = get_admin_client()
    existing = admin.table("subscriptions").select("id").eq("user_id", user_id).execute()
    if existing.data:
        admin.table("subscriptions").update(data).eq("user_id", user_id).execute()
    else:
        data["user_id"] = user_id
        admin.table("subscriptions").insert(data).execute()


# ── Admin: User Management ────────────────────────────────────────

def list_all_users() -> list:
    """List all users with profiles and subscriptions (admin only)."""
    admin = get_admin_client()
    profiles = admin.table("profiles").select("id, name, email, experience_level, created_at").execute()
    subs = admin.table("subscriptions").select("user_id, tier, status, trial_ends_at, discount_code").execute()
    sub_map = {s["user_id"]: s for s in (subs.data or [])}

    users = []
    for p in (profiles.data or []):
        sub = sub_map.get(p["id"], {})
        users.append({
            "id": p["id"],
            "name": p.get("name", ""),
            "email": p.get("email", ""),
            "experience_level": p.get("experience_level", "unknown"),
            "created_at": p.get("created_at", ""),
            "tier": sub.get("tier", "free"),
            "status": sub.get("status", "none"),
            "trial_ends_at": sub.get("trial_ends_at"),
            "discount_code": sub.get("discount_code"),
        })
    return users


def set_user_tier(user_id: str, tier: str, status: str = "active"):
    """Set a user's subscription tier (admin action)."""
    update_subscription(user_id, {"tier": tier, "status": status})


# ── Discount Codes ────────────────────────────────────────────────

def get_discount_code(code: str) -> dict | None:
    """Look up a discount code."""
    admin = get_admin_client()
    result = admin.table("discount_codes").select("*").eq("code", code.upper()).execute()
    if result.data:
        return result.data[0]
    return None


def create_discount_code(code: str, discount_percent: int, max_uses: int = 1, description: str = "") -> dict:
    """Create a new discount code (admin action)."""
    admin = get_admin_client()
    result = admin.table("discount_codes").insert({
        "code": code.upper(),
        "discount_percent": discount_percent,
        "max_uses": max_uses,
        "times_used": 0,
        "description": description,
        "active": True,
    }).execute()
    return result.data[0] if result.data else {}


def apply_discount_code(user_id: str, code: str) -> tuple[bool, str]:
    """Apply a discount code to a user. Returns (success, message)."""
    dc = get_discount_code(code)
    if not dc:
        return False, "Ogiltig rabattkod."
    if not dc.get("active", False):
        return False, "Rabattkoden ar inte langre aktiv."
    if dc["times_used"] >= dc["max_uses"]:
        return False, "Rabattkoden har redan anvants max antal ganger."

    admin = get_admin_client()

    # Apply: 100% = free premium, otherwise record discount
    if dc["discount_percent"] >= 100:
        update_subscription(user_id, {
            "tier": "premium",
            "status": "active",
            "discount_code": code.upper(),
        })
    else:
        update_subscription(user_id, {
            "discount_code": code.upper(),
        })

    # Increment usage
    admin.table("discount_codes").update({
        "times_used": dc["times_used"] + 1,
    }).eq("id", dc["id"]).execute()

    return True, f"Rabattkod {code.upper()} tillämpad! ({dc['discount_percent']}% rabatt)"


def list_discount_codes() -> list:
    """List all discount codes (admin only)."""
    admin = get_admin_client()
    result = admin.table("discount_codes").select("*").order("created_at", desc=True).execute()
    return result.data or []


# ── Daily Message Counts ───────────────────────────────────────────

def get_daily_message_count(user_id: str, access_token: str) -> int:
    from datetime import date
    client = get_client()
    client.postgrest.auth(access_token)
    today = date.today().isoformat()
    result = (
        client.table("daily_message_counts")
        .select("count")
        .eq("user_id", user_id)
        .eq("message_date", today)
        .execute()
    )
    if result.data:
        return result.data[0]["count"]
    return 0


def increment_daily_messages(user_id: str, access_token: str) -> int:
    from datetime import date
    client = get_client()
    client.postgrest.auth(access_token)
    today = date.today().isoformat()

    # Try to update existing row
    result = (
        client.table("daily_message_counts")
        .select("id, count")
        .eq("user_id", user_id)
        .eq("message_date", today)
        .execute()
    )
    if result.data:
        new_count = result.data[0]["count"] + 1
        client.table("daily_message_counts").update(
            {"count": new_count}
        ).eq("id", result.data[0]["id"]).execute()
        return new_count
    else:
        client.table("daily_message_counts").insert({
            "user_id": user_id,
            "message_date": today,
            "count": 1,
        }).execute()
        return 1


# ── File Attachments (Supabase Storage) ────────────────────────────

def upload_attachment(user_id: str, access_token: str, file_bytes: bytes, filename: str) -> str:
    """Upload file to Supabase Storage, return public URL."""
    from datetime import datetime
    client = get_client()
    client.postgrest.auth(access_token)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"{user_id}/{ts}_{filename}"
    client.storage.from_("chat-attachments").upload(path, file_bytes)
    return client.storage.from_("chat-attachments").get_public_url(path)


# ── Helpers ────────────────────────────────────────────────────────

def profile_to_athlete_dict(profile: dict) -> dict:
    """Convert Supabase profile row to the format AthleteProfile expects."""
    return {
        "name": profile.get("name", ""),
        "experience_level": profile.get("experience_level", "unknown"),
        "goal": profile.get("goal", ""),
        "sports": profile.get("sports", []),
        "equipment": profile.get("equipment", []),
        "height_cm": profile.get("height_cm"),
        "weight_kg": float(profile["weight_kg"]) if profile.get("weight_kg") else None,
        "blood_pressure": profile.get("blood_pressure", ""),
        "ftp_watts": profile.get("ftp_watts"),
        "at_pace": profile.get("at_pace"),
        "lt_pace": profile.get("lt_pace"),
        "at_hr": profile.get("at_hr"),
        "lt_hr": profile.get("lt_hr"),
        "css": profile.get("css"),
        "ironman_finishes": profile.get("ironman_finishes", 0),
        "next_race_name": profile.get("next_race_name", ""),
        "next_race_date": profile.get("next_race_date", ""),
        "health_notes": profile.get("health_notes", ""),
        "preferences": profile.get("preferences", ""),
        "strength": profile.get("strength", {}),
    }
