"""
Bestämmer aktuell träningsfas baserat på:
- Veckor kvar till nästa A-tävling
- Senaste veckans träningstid (vid låg volym → förberedelsefas)
- Optionellt: läser fas-specifika prompts från prompts/-mappen
"""

from datetime import date
from pathlib import Path
from typing import Optional
import sqlite3

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
DB_PATH     = Path(__file__).parent.parent / "workouts.db"


PHASES = [
    # (fas-namn, fil-prefix, min_veckor, max_veckor)
    ("Återhämtningsfas",   "2.3.6", -4,  0),
    ("Tävlingsfas",        "2.3.5",  0,  1),
    ("Toppningsfas",       "2.3.4",  1,  10),
    ("Byggfas",            "2.3.3", 10,  16),
    ("Grundträningsfas",   "2.3.2", 16,  20),
    ("Förberedelsefas",    "2.3.1", 20, 999),
]

LOW_VOLUME_THRESHOLD_HOURS = 5.0   # under denna → alltid förberedelsefas


def get_recent_weekly_hours(db_path: Path = DB_PATH, weeks: int = 2) -> float:
    """Genomsnittlig träningstid per vecka de senaste N veckorna."""
    if db_path is None or not db_path.exists():
        return 0.0
    conn = sqlite3.connect(db_path)
    result = conn.execute("""
        SELECT SUM(duration_sec) / 3600.0 / ?
        FROM workouts
        WHERE date >= date('now', ?)
    """, (weeks, f"-{weeks * 7} days")).fetchone()
    conn.close()
    return float(result[0] or 0.0)


def detect_phase(weeks_to_race: Optional[int], db_path: Path = DB_PATH) -> tuple[str, str]:
    """
    Returnerar (fas_namn, fas_prefix) för aktuell fas.

    Logik:
    1. Om träningstid < 5h/vecka → Förberedelsefas
    2. Annars: välj fas baserat på veckor kvar
    3. Om inget tävlingsdatum → Förberedelsefas
    """
    if weeks_to_race is None:
        return "Förberedelsefas", "2.3.1"

    avg_hours = get_recent_weekly_hours(db_path)
    if avg_hours < LOW_VOLUME_THRESHOLD_HOURS and weeks_to_race > 10:
        return "Förberedelsefas", "2.3.1"

    for fas_namn, prefix, min_w, max_w in PHASES:
        if min_w <= weeks_to_race < max_w:
            return fas_namn, prefix

    return "Förberedelsefas", "2.3.1"


def load_phase_prompt(prefix: str) -> Optional[str]:
    """
    Försöker läsa fas-specifik prompt från prompts/-mappen.
    Letar efter filer som börjar med prefixet (t.ex. "2.3.1").
    Returnerar None om ingen fil hittas.
    """
    for candidate in PROMPTS_DIR.glob(f"{prefix}*.md"):
        return candidate.read_text(encoding="utf-8")
    return None


def phase_context(weeks_to_race: Optional[int], db_path: Path = DB_PATH) -> str:
    """
    Returnerar en textsträng med fasinfo redo att injiceras i system-prompten.
    Inkluderar fas-specifik prompt om den finns som fil.
    """
    fas_namn, prefix = detect_phase(weeks_to_race, db_path)
    avg_hours = get_recent_weekly_hours(db_path)

    lines = [
        f"Aktuell träningsfas: {fas_namn}",
        f"Veckor till nästa tävling: {weeks_to_race if weeks_to_race is not None else 'okänt'}",
        f"Genomsnittlig träningstid senaste 2 veckorna: {avg_hours:.1f}h/vecka",
    ]

    extra = load_phase_prompt(prefix)
    if extra:
        lines += ["", f"--- Fas-instruktioner ({fas_namn}) ---", extra]
    else:
        lines.append(f"(Ingen fas-specifik prompt hittad för {prefix} – lägg till {prefix}_*.md i prompts/)")

    return "\n".join(lines)


if __name__ == "__main__":
    # Test
    from data.athlete_profile import AthleteProfile
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    profile = AthleteProfile()
    weeks = profile.weeks_to_race()
    fas, prefix = detect_phase(weeks)
    avg_h = get_recent_weekly_hours()

    print(f"Veckor till race:    {weeks}")
    print(f"Genomsn. tim/vecka:  {avg_h:.1f}h")
    print(f"Fas:                 {fas}  ({prefix})")
    prompt = load_phase_prompt(prefix)
    print(f"Fas-prompt:          {'hittad' if prompt else 'saknas – lägg till ' + prefix + '_*.md i prompts/'}")
