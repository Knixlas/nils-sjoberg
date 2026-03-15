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
