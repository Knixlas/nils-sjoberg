"""
Intervals.icu API integration for pushing structured workouts.
Uses the bulk events endpoint with text description format.
"""
from __future__ import annotations

import base64
import requests

API_BASE = "https://intervals.icu/api/v1"

SPORT_MAP = {
    "running": "Run",
    "biking": "Ride",
    "swimming": "Swim",
    "run": "Run",
    "ride": "Ride",
    "swim": "Swim",
    "cycling": "Ride",
}


def _auth_header(api_key: str) -> dict:
    """Build Basic Auth header for Intervals.icu."""
    token = base64.b64encode(f"API_KEY:{api_key}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
    }


def workout_to_description(workout: dict) -> str:
    """Convert our workout tool output to Intervals.icu text description format.

    The text format is parsed by Intervals.icu into structured workouts:
    - '- 15m 60% Warmup' for warmup/cooldown steps
    - '3x' for repeats
    - '- 5m 100%' for intervals with intensity
    - HR targets: '- 5m 140-155bpm'
    """
    lines = []
    i = 0
    steps = workout.get("steps", [])

    while i < len(steps):
        step = steps[i]
        step_type = step.get("type", "active")
        duration_s = step.get("duration_seconds", 0)
        duration_str = _format_duration(duration_s)
        desc = step.get("description", "")
        intensity = _format_intensity(step)

        repeats = step.get("repeats", 1)

        if step_type == "warmup":
            label = desc or "Warmup"
            lines.append(f"- {duration_str} {intensity} {label}".strip())
        elif step_type == "cooldown":
            label = desc or "Cooldown"
            lines.append(f"- {duration_str} {intensity} {label}".strip())
        elif step_type == "rest":
            label = desc or "Rest"
            lines.append(f"- {duration_str} {intensity} {label}".strip())
        elif step_type == "active":
            # Check if this is part of a repeat block
            if repeats and repeats > 1:
                lines.append(f"{repeats}x")
                lines.append(f"- {duration_str} {intensity} {desc}".strip())
                # Check if next step is rest (interval pair)
                if i + 1 < len(steps) and steps[i + 1].get("type") == "rest":
                    rest = steps[i + 1]
                    rest_dur = _format_duration(rest.get("duration_seconds", 0))
                    rest_int = _format_intensity(rest)
                    lines.append(f"- {rest_dur} {rest_int} Rest".strip())
                    i += 1  # skip rest step
            else:
                lines.append(f"- {duration_str} {intensity} {desc}".strip())

        i += 1

    return "\n".join(lines)


def _format_duration(seconds: int) -> str:
    """Format seconds to human-readable duration."""
    if seconds <= 0:
        return "0s"
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    remaining = seconds % 60
    if remaining == 0:
        return f"{minutes}m"
    return f"{minutes}m{remaining}s"


def _format_intensity(step: dict) -> str:
    """Format intensity target for Intervals.icu description."""
    # Prefer HR targets (most universal)
    hr_low = step.get("hr_low")
    hr_high = step.get("hr_high")
    if hr_low and hr_high:
        return f"{hr_low}-{hr_high}bpm"
    if hr_low:
        return f"{hr_low}bpm"

    # Power targets (cycling)
    power_low = step.get("power_low")
    power_high = step.get("power_high")
    if power_low and power_high:
        return f"{power_low}-{power_high}w"
    if power_low:
        return f"{power_low}w"

    # Fallback: guess zone from step type
    step_type = step.get("type", "active")
    if step_type == "warmup":
        return "55%"
    if step_type == "cooldown":
        return "50%"
    if step_type == "rest":
        return "40%"
    return ""


def push_workout(
    api_key: str,
    athlete_id: str,
    workout: dict,
    date: str | None = None,
) -> dict:
    """Push a structured workout to Intervals.icu calendar.

    Args:
        api_key: Intervals.icu API key
        athlete_id: Athlete ID (or "0" for authenticated user)
        workout: Workout dict from Claude tool_use (name, sport, steps)
        date: Optional ISO date string (YYYY-MM-DD). Defaults to today.

    Returns:
        API response dict or error dict
    """
    if not date:
        from datetime import date as d
        date = d.today().isoformat()

    sport = SPORT_MAP.get(workout.get("sport", "running").lower(), "Run")
    description = workout_to_description(workout)
    total_seconds = sum(
        s.get("duration_seconds", 0) * s.get("repeats", 1) for s in workout.get("steps", [])
    )

    event = {
        "category": "WORKOUT",
        "start_date_local": f"{date}T00:00:00",
        "name": workout.get("name", "Workout"),
        "type": sport,
        "description": description,
        "moving_time": total_seconds,
    }

    url = f"{API_BASE}/athlete/{athlete_id}/events/bulk"
    headers = _auth_header(api_key)

    try:
        resp = requests.post(url, json=[event], headers=headers, timeout=15)
        if resp.status_code in (200, 201):
            return {"success": True, "data": resp.json()}
        else:
            return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
