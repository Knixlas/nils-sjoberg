"""
Passbank – strukturerade traningspass som Trixa kan valja fran.
Varje pass har sport, typ, zon, faser och en enjoyment-poäng
som byggs upp baserat på atletens feedback.
"""

import json
from pathlib import Path
from typing import Optional

LIBRARY_FILE = Path(__file__).parent.parent / "workout_library.json"


def load_library() -> dict:
    if LIBRARY_FILE.exists():
        try:
            return json.loads(LIBRARY_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            return {"workouts": []}
    return {"workouts": []}


def save_library(lib: dict):
    LIBRARY_FILE.write_text(
        json.dumps(lib, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def add_workout(workout: dict) -> str:
    lib = load_library()
    # Auto-generate ID if missing
    if "id" not in workout:
        sport = workout.get("sport", "x")
        name_slug = workout.get("name", "pass").lower().replace(" ", "_")[:30]
        workout["id"] = f"{sport}_{name_slug}_{len(lib['workouts'])+1}"
    workout.setdefault("enjoyment", 0)
    workout.setdefault("times_prescribed", 0)
    workout.setdefault("times_completed", 0)
    workout.setdefault("tags", [])
    workout.setdefault("phases", [])
    lib["workouts"].append(workout)
    save_library(lib)
    return workout["id"]


def remove_workout(workout_id: str) -> bool:
    lib = load_library()
    before = len(lib["workouts"])
    lib["workouts"] = [w for w in lib["workouts"] if w["id"] != workout_id]
    if len(lib["workouts"]) < before:
        save_library(lib)
        return True
    return False


def update_enjoyment(workout_id: str, rating: float):
    lib = load_library()
    for w in lib["workouts"]:
        if w["id"] == workout_id:
            # Running average
            n = w.get("times_completed", 0) or 1
            old = w.get("enjoyment", 0)
            w["enjoyment"] = round((old * (n - 1) + rating) / n, 1)
            w["times_completed"] = n + 1
            break
    save_library(lib)


def get_workouts_for_phase(phase: str, sport: Optional[str] = None) -> list[dict]:
    lib = load_library()
    phase_lower = phase.lower()
    results = []
    for w in lib["workouts"]:
        phase_match = not w.get("phases") or any(
            phase_lower in p.lower() for p in w["phases"]
        )
        sport_match = sport is None or w.get("sport") == sport
        if phase_match and sport_match:
            results.append(w)
    return sorted(results, key=lambda w: w.get("enjoyment", 0), reverse=True)


def library_summary() -> str:
    lib = load_library()
    if not lib["workouts"]:
        return "Ingen passbank tillganglig."

    lines = [f"Passbank ({len(lib['workouts'])} pass):"]
    for sport in ["swim", "bike", "run", "strength"]:
        sport_workouts = [w for w in lib["workouts"] if w.get("sport") == sport]
        if not sport_workouts:
            continue
        lines.append(f"\n  {sport.upper()}:")
        for w in sorted(sport_workouts, key=lambda x: x.get("enjoyment", 0), reverse=True):
            enj = f"enjoyment:{w['enjoyment']}" if w.get("enjoyment") else ""
            phases = ", ".join(w.get("phases", []))
            lines.append(
                f"    [{w['id']}] {w['name']}  {w.get('zone','')}  "
                f"{w.get('duration_min','')}min  {enj}"
            )
            if w.get("description"):
                lines.append(f"      {w['description']}")
            if phases:
                lines.append(f"      Faser: {phases}")
    return "\n".join(lines)


def library_stats() -> dict:
    lib = load_library()
    stats = {}
    for w in lib["workouts"]:
        sport = w.get("sport", "other")
        stats[sport] = stats.get(sport, 0) + 1
    return stats


if __name__ == "__main__":
    print(library_summary())
    print()
    print("Stats:", library_stats())
