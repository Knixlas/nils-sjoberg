"""
Läser Garmin Connect CSV-export (svenska kolumnnamn) och sparar till SQLite.

Användning:
    python data/ingest.py input/activities_2024_2026.csv
    python data/ingest.py input/*.csv --replace
"""

import csv
import sqlite3
import sys
import re
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "workouts.db"

TRIATHLON_TYPES = {
    "Löpning", "Landsvägscykling", "Inomhuscykling", "Virtuell cykling",
    "Cykling", "Simbassäng", "Havssimning", "Öppet vatten",
    "Löpband", "Cykelrullarna",
}

SWIM_TYPES = {"Simbassäng", "Havssimning", "Öppet vatten"}


def _num(val: str) -> float | None:
    if not val or val.strip() in ("--", "NaN", "NaN:NaN", ""):
        return None
    v = val.strip().replace(".", "").replace(",", ".")
    v = re.sub(r"[^\d.\-]", "", v)
    try:
        return float(v)
    except ValueError:
        return None


def _dur_sec(val: str) -> int | None:
    if not val or val.strip() in ("--", "NaN"):
        return None
    parts = val.strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(float(parts[2]))
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(float(parts[1]))
    except (ValueError, IndexError):
        return None


def _sport(atype: str) -> str:
    if atype in SWIM_TYPES:
        return "swim"
    t = atype.lower()
    if any(x in t for x in ("cykling", "cykel")):
        return "bike"
    if any(x in t for x in ("löpning", "löpband")):
        return "run"
    return "other"


def _dist_km(atype: str, raw: float | None) -> float | None:
    """Simbassäng rapporterar meter, alla andra km."""
    if raw is None:
        return None
    if atype == "Simbassäng" and raw > 50:
        return raw / 1000.0
    return raw


def create_schema(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workouts (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_type    TEXT,
            sport            TEXT,
            date             TEXT,
            name             TEXT,
            distance_km      REAL,
            duration_sec     INTEGER,
            calories         REAL,
            avg_hr           INTEGER,
            max_hr           INTEGER,
            aerobic_te       REAL,
            tss              REAL,
            np_watts         REAL,
            avg_power_watts  REAL,
            avg_cadence      REAL,
            avg_pace         TEXT,
            elevation_gain_m REAL,
            avg_stride_m     REAL,
            swolf            REAL,
            swim_stroke_rate REAL,
            raw_duration     TEXT,
            UNIQUE(date, name, activity_type)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_date  ON workouts(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sport ON workouts(sport)")
    conn.commit()


def ingest(csv_path: str, db_path: Path = DB_PATH, replace: bool = False) -> tuple[int, int]:
    conn = sqlite3.connect(db_path)
    create_schema(conn)

    if replace:
        conn.execute("DELETE FROM workouts")
        conn.commit()

    rows = list(csv.DictReader(open(csv_path, encoding="utf-8-sig")))
    inserted = skipped = 0

    for row in rows:
        atype = row.get("Aktivitetstyp", "").strip()
        if atype not in TRIATHLON_TYPES:
            skipped += 1
            continue

        dur_raw = row.get("Tid", "")
        dur_sec = _dur_sec(dur_raw)
        if dur_sec and dur_sec < 300:
            skipped += 1
            continue

        dist = _dist_km(atype, _num(row.get("Distans", "")))

        try:
            conn.execute("""
                INSERT OR IGNORE INTO workouts (
                    activity_type, sport, date, name,
                    distance_km, duration_sec, calories,
                    avg_hr, max_hr, aerobic_te, tss,
                    np_watts, avg_power_watts, avg_cadence,
                    avg_pace, elevation_gain_m, avg_stride_m,
                    swolf, swim_stroke_rate, raw_duration
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                atype,
                _sport(atype),
                row.get("Datum", "").strip(),
                row.get("Namn", "").strip(),
                dist,
                dur_sec,
                _num(row.get("Kalorier", "")),
                _num(row.get("Medelpuls", "")),
                _num(row.get("Maxpuls", "")),
                _num(row.get("Aerobisk TE", "")),
                _num(row.get("Training Stress Score®", "")),
                _num(row.get("Normalized Power® (NP®)", "")),
                _num(row.get("Medelkraft", "")),
                _num(row.get("Medelcykelkadens", "")),
                row.get("Medelfart", "").strip() or None,
                _num(row.get("Total stigning", "")),
                _num(row.get("Medelsteglängd", "")),
                _num(row.get("Medel-Swolf", "")),
                _num(row.get("Medelårtagstempo", "")),
                dur_raw,
            ))
            if conn.execute("SELECT changes()").fetchone()[0]:
                inserted += 1
            else:
                skipped += 1
        except sqlite3.Error:
            skipped += 1

    conn.commit()
    conn.close()
    return inserted, skipped


def recent_summary(db_path: Path = DB_PATH, days: int = 21) -> str:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT sport, date, name, distance_km, duration_sec, avg_hr, tss, avg_pace
        FROM workouts
        WHERE date >= date('now', ?)
        ORDER BY date DESC
    """, (f"-{days} days",)).fetchall()
    conn.close()

    if not rows:
        return f"Inga registrerade träningspass de senaste {days} dagarna."

    lines = [f"Träningslogg senaste {days} dagarna ({len(rows)} pass):"]
    for r in rows:
        dur  = f"{r['duration_sec']//3600}h{(r['duration_sec']%3600)//60}m" if r["duration_sec"] else "?"
        dist = f"{r['distance_km']:.1f} km" if r["distance_km"] else ""
        tss  = f"TSS {r['tss']:.0f}" if r["tss"] else ""
        hr   = f"puls {int(r['avg_hr'])}" if r["avg_hr"] else ""
        pace = f"@{r['avg_pace']}" if r["avg_pace"] else ""
        details = "  ".join(filter(None, [dist, dur, pace, hr, tss]))
        lines.append(f"  {r['date'][:10]}  [{r['sport'].upper():4s}]  {r['name'][:38]:<38}  {details}")
    return "\n".join(lines)


def weekly_volume(db_path: Path = DB_PATH, weeks: int = 8) -> str:
    conn = sqlite3.connect(db_path)
    rows = conn.execute("""
        SELECT strftime('%Y-W%W', date) as week,
               sport,
               COUNT(*) as sessions,
               ROUND(SUM(distance_km), 1) as km,
               ROUND(SUM(duration_sec) / 3600.0, 1) as hours,
               ROUND(SUM(tss), 0) as total_tss
        FROM workouts
        WHERE date >= date('now', ?)
        GROUP BY week, sport
        ORDER BY week DESC, sport
    """, (f"-{weeks * 7} days",)).fetchall()
    conn.close()

    if not rows:
        return "Ingen träningsdata tillgänglig för veckovolym."

    lines = [f"Veckovolym senaste {weeks} veckor:"]
    current = None
    for w, sport, sess, km, hours, tss in rows:
        if w != current:
            current = w
            lines.append(f"\n  {w}")
        lines.append(f"    {sport.upper():5s}  {sess} pass  {hours or 0:.1f}h  {km or 0:.1f} km  TSS {tss or 0:.0f}")
    return "\n".join(lines)


def db_stats(db_path: Path = DB_PATH) -> str:
    if not db_path.exists():
        return "Ingen databas hittad."
    conn = sqlite3.connect(db_path)
    total  = conn.execute("SELECT COUNT(*) FROM workouts").fetchone()[0]
    oldest = conn.execute("SELECT MIN(date) FROM workouts").fetchone()[0]
    newest = conn.execute("SELECT MAX(date) FROM workouts").fetchone()[0]
    by_sport = conn.execute("""
        SELECT sport, COUNT(*) FROM workouts GROUP BY sport ORDER BY COUNT(*) DESC
    """).fetchall()
    conn.close()
    lines = [f"Databas: {total} pass  ({oldest[:10]} - {newest[:10]})"]
    for sport, n in by_sport:
        lines.append(f"  {sport.upper():5s}: {n} pass")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Användning: python data/ingest.py <fil.csv> [fil2.csv ...] [--replace]")
        sys.exit(1)

    replace   = "--replace" in sys.argv
    csv_files = [f for f in sys.argv[1:] if not f.startswith("--")]
    first     = True

    for csv_file in csv_files:
        ins, skp = ingest(csv_file, replace=(replace and first))
        first = False
        print(f"  {Path(csv_file).name}: {ins} inlagda, {skp} överhoppade")

    print()
    print(db_stats())
    print()
    print(weekly_volume(weeks=12))
