"""
Supabase database operations for multi-user Nils Sjöberg.
Handles profiles and conversation history per user.
"""

import os
import json
from supabase import create_client, Client


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


def update_subscription(user_id: str, data: dict):
    """Update subscription (service key, bypasses RLS)."""
    admin = get_admin_client()
    admin.table("subscriptions").update(data).eq("user_id", user_id).execute()


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
