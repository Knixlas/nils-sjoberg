"""
Synkar aktiviteter från Strava API till workouts.db.

Användning:
    python data/strava_sync.py              # synka nya sedan senaste
    python data/strava_sync.py --full       # hämta allt (max ~3 år)
    python data/strava_sync.py --days 30    # senaste 30 dagarna
"""

import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))
from data.strava_auth import get_access_token
from data.ingest import create_schema, db_stats, weekly_volume

DB_PATH      = Path(__file__).parent.parent / "workouts.db"
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"

# Strava sport → vår sport-klassificering
SPORT_MAP = {
    "Run":              "run",
    "TrailRun":         "run",
    "Treadmill":        "run",
    "VirtualRun":       "run",
    "Ride":             "bike",
    "VirtualRide":      "bike",
    "EBikeRide":        "bike",
    "MountainBikeRide": "bike",
    "GravelRide":       "bike",
    "Swim":             "swim",
    "OpenWaterSwim":    "swim",
}

# Strava sport-typer vi vill spara
WANTED_TYPES = set(SPORT_MAP.keys())


def _speed_to_pace(speed_ms: float | None, sport: str) -> str | None:
    """
    Konverterar m/s → min:sek/km (löpning/simning)
    eller km/h (cykling).
    """
    if not speed_ms or speed_ms <= 0:
        return None
    if sport in ("run", "swim"):
        secs_per_km = 1000 / speed_ms
        m = int(secs_per_km // 60)
        s = int(secs_per_km % 60)
        return f"{m}:{s:02d}"
    # cykling: km/h
    return f"{speed_ms * 3.6:.1f}"


def _ts(dt_str: str) -> int:
    """ISO-sträng → unix timestamp."""
    return int(datetime.fromisoformat(dt_str.replace("Z", "+00:00")).timestamp())


def get_last_sync_time(db_path: Path = DB_PATH) -> int:
    """Returnerar unix-timestamp för senaste aktivitet i databasen."""
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(db_path)
    result = conn.execute(
        "SELECT MAX(date) FROM workouts WHERE source='strava'"
    ).fetchone()[0]
    conn.close()
    if not result:
        return 0
    try:
        dt = datetime.fromisoformat(result.replace(" ", "T"))
        return int(dt.replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return 0


def fetch_activities(after: int = 0, per_page: int = 100) -> list[dict]:
    """Hämtar aktiviteter från Strava API, paginerar automatiskt."""
    token    = get_access_token()
    headers  = {"Authorization": f"Bearer {token}"}
    all_acts = []
    page     = 1

    while True:
        params = {"per_page": per_page, "page": page}
        if after:
            params["after"] = after

        resp = requests.get(ACTIVITIES_URL, headers=headers, params=params)

        # Rate limit-hantering
        if resp.status_code == 429:
            print("  Rate limit – väntar 60s...")
            time.sleep(60)
            continue

        resp.raise_for_status()
        batch = resp.json()

        if not batch:
            break

        # Filtrera direkt
        wanted = [a for a in batch if a.get("type") in WANTED_TYPES or
                  a.get("sport_type") in WANTED_TYPES]
        all_acts.extend(wanted)
        print(f"  Sida {page}: {len(batch)} hämtade, {len(wanted)} relevanta")

        if len(batch) < per_page:
            break
        page += 1
        time.sleep(0.5)  # snäll mot API:et

    return all_acts


def upsert_activity(conn: sqlite3.Connection, act: dict):
    """Lägger till eller uppdaterar en aktivitet i databasen."""
    atype = act.get("sport_type") or act.get("type", "")
    sport = SPORT_MAP.get(atype, "other")
    if sport == "other":
        return

    date_str = act.get("start_date_local", "")[:19].replace("T", " ")
    name     = act.get("name", "")
    dist_m   = act.get("distance", 0) or 0
    dist_km  = dist_m / 1000.0 if dist_m else None
    dur_sec  = act.get("moving_time") or act.get("elapsed_time")
    avg_hr   = act.get("average_heartrate")
    max_hr   = act.get("max_heartrate")
    avg_spd  = act.get("average_speed")
    elev     = act.get("total_elevation_gain")
    avg_pow  = act.get("average_watts")
    np_watts = act.get("weighted_average_watts")
    avg_cad  = act.get("average_cadence")
    tss      = None  # Strava ger inte TSS via basic API

    avg_pace = _speed_to_pace(avg_spd, sport)

    conn.execute("""
        INSERT INTO workouts (
            activity_type, sport, date, name,
            distance_km, duration_sec, avg_hr, max_hr,
            avg_pace, elevation_gain_m, avg_power_watts,
            np_watts, avg_cadence, tss, raw_duration, source
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(date, name, activity_type) DO UPDATE SET
            distance_km      = excluded.distance_km,
            duration_sec     = excluded.duration_sec,
            avg_hr           = excluded.avg_hr,
            max_hr           = excluded.max_hr,
            avg_pace         = excluded.avg_pace,
            elevation_gain_m = excluded.elevation_gain_m,
            avg_power_watts  = excluded.avg_power_watts,
            np_watts         = excluded.np_watts,
            avg_cadence      = excluded.avg_cadence,
            source           = 'strava'
    """, (
        atype, sport, date_str, name,
        dist_km, dur_sec, avg_hr, max_hr,
        avg_pace, elev, avg_pow,
        np_watts, avg_cad, tss,
        f"{dur_sec // 3600}:{(dur_sec % 3600) // 60:02d}" if dur_sec else None,
        "strava",
    ))


def sync(full: bool = False, days: int = None, db_path: Path = DB_PATH):
    """Huvudfunktion för synkronisering."""
    conn = sqlite3.connect(db_path)
    create_schema(conn)

    # Lägg till source-kolumn om den saknas (bakåtkompatibilitet)
    try:
        conn.execute("ALTER TABLE workouts ADD COLUMN source TEXT DEFAULT 'csv'")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # kolumnen finns redan

    conn.close()

    # Bestäm från vilket datum vi hämtar
    if full:
        after = 0
        print("Hämtar all historik från Strava...")
    elif days:
        after = int(time.time()) - days * 86400
        print(f"Hämtar aktiviteter de senaste {days} dagarna...")
    else:
        after = get_last_sync_time(db_path)
        if after:
            dt = datetime.fromtimestamp(after).strftime("%Y-%m-%d %H:%M")
            print(f"Synkar sedan senaste Strava-aktivitet: {dt}")
        else:
            # Ingen Strava-data ännu – hämta 90 dagar
            after = int(time.time()) - 90 * 86400
            print("Ingen tidigare Strava-sync – hämtar senaste 90 dagarna...")

    acts = fetch_activities(after=after)
    print(f"\nBearbetar {len(acts)} aktiviteter...")

    conn = sqlite3.connect(db_path)
    inserted = 0
    for act in acts:
        before = conn.execute("SELECT changes()").fetchone()[0]
        upsert_activity(conn, act)
        if conn.execute("SELECT changes()").fetchone()[0] != before or True:
            inserted += 1

    conn.commit()
    conn.close()

    print(f"\nOK! Strava-sync klar: {inserted} aktiviteter bearbetade")
    print()
    print(db_stats(db_path))
    print()
    print(weekly_volume(db_path, weeks=4))


if __name__ == "__main__":
    full = "--full" in sys.argv
    days = None
    for arg in sys.argv[1:]:
        if arg.startswith("--days="):
            days = int(arg.split("=")[1])
        elif arg == "--days" and sys.argv.index(arg) + 1 < len(sys.argv):
            try:
                days = int(sys.argv[sys.argv.index(arg) + 1])
            except (ValueError, IndexError):
                pass

    sync(full=full, days=days)
