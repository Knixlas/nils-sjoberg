"""
Onboarding for ny atlet. Borjar med mal och motivation,
anpassar djupet baserat pa erfarenhetsniva.

Kor med: python onboarding.py

Steg:
  1. Namn och mal
  2. Erfarenhetsniva (bestamms av svar)
  3. Utrustning
  4. Tavling (valfritt)
  5. Testvarden (bara om relevant)
  6. Halsa
  7. Preferenser
"""

import json
import sys
from pathlib import Path
from datetime import date

PROFILE_FILE = Path(__file__).parent / "athlete_data.json"
DB_PATH      = Path(__file__).parent / "workouts.db"


def ask(prompt: str, required: bool = True, default: str = "") -> str:
    while True:
        suffix = f" [{default}]" if default else " (valfri, Enter for att hoppa over)" if not required else ""
        val = input(f"{prompt}{suffix}: ").strip()
        if val:
            return val
        if default:
            return default
        if not required:
            return ""
        print("  > Svaret kravs.")


def ask_int(prompt: str, default: int = None) -> int | None:
    while True:
        suf = f" [{default}]" if default else " (valfri)"
        val = input(f"{prompt}{suf}: ").strip()
        if not val and default is not None:
            return default
        if not val:
            return None
        try:
            return int(val)
        except ValueError:
            print("  > Ange ett heltal.")


def ask_float(prompt: str, default: float = None) -> float | None:
    while True:
        suf = f" [{default}]" if default else " (valfri)"
        val = input(f"{prompt}{suf}: ").strip()
        if not val and default is not None:
            return default
        if not val:
            return None
        try:
            return float(val.replace(",", "."))
        except ValueError:
            print("  > Ange ett tal.")


def ask_date(prompt: str) -> str:
    while True:
        val = input(f"{prompt} (YYYY-MM-DD): ").strip()
        if not val:
            return ""
        try:
            d = date.fromisoformat(val)
            if d < date.today():
                print("  > Datumet ar passerat. Ange ett framtida datum.")
                continue
            return val
        except ValueError:
            print("  > Format: AAAA-MM-DD, t.ex. 2026-08-15")


def ask_pace(prompt: str, default: str = "") -> str:
    while True:
        suf = f" [{default}]" if default else " (valfri, Enter for att hoppa over)"
        val = input(f"{prompt} (MM:SS/km){suf}: ").strip()
        if not val and default:
            return default
        if not val:
            return ""
        if ":" in val and len(val.split(":")) == 2:
            return val
        print("  > Format: MM:SS, t.ex. 4:45")


def separator(title: str):
    print()
    print(f"  -- {title} --")
    print()


def run_onboarding() -> dict:
    print()
    print("+--------------------------------------------------+")
    print("|  Hej! Jag ar Nils Sjoberg, din personliga tranare.|")
    print("|  Beratta lite om dig sa hittar vi ratt start!     |")
    print("+--------------------------------------------------+")
    print()

    data = {}

    # 1. Namn och mal
    separator("1. Vem ar du och vad vill du uppna?")
    data["name"] = ask("Ditt namn")

    print()
    print("  Vad ar ditt traningsmal? Nagra exempel:")
    print("  [1] Springa 5 km utan att ga")
    print("  [2] Fa en bra tranansvana och ma bra")
    print("  [3] Klara en triathlon (sprint/olympisk)")
    print("  [4] Klara en Ironman eller langdistans")
    print("  [5] Annat (beskriv fritt)")
    print()
    goal_choice = ""
    while goal_choice not in ("1", "2", "3", "4", "5"):
        goal_choice = input("  Valj [1-5]: ").strip()

    goal_map = {
        "1": "Springa 5 km utan att ga",
        "2": "Fa en bra tranansvana och ma bra",
        "3": "Klara en triathlon",
        "4": "Klara en Ironman / langdistans",
    }
    if goal_choice == "5":
        data["goal"] = ask("Beskriv ditt mal")
    else:
        data["goal"] = goal_map[goal_choice]

    # 2. Erfarenhet
    separator("2. Var ar du idag?")
    print("  Hur skulle du beskriva din tranaingsbakgrund?")
    print("  [1] Nyborjare - tranar sallan eller aldrig")
    print("  [2] Motionar  - tranar regelbundet men utan struktur")
    print("  [3] Avancerad - tranar strukturerat, har testvarden")
    print()
    exp_choice = ""
    while exp_choice not in ("1", "2", "3"):
        exp_choice = input("  Valj [1-3]: ").strip()

    exp_map = {"1": "beginner", "2": "intermediate", "3": "advanced"}
    data["experience_level"] = exp_map[exp_choice]

    # Vilka sporter?
    print()
    if goal_choice in ("3", "4"):
        data["sports"] = ["swim", "bike", "run"]
        print("  > Triathlon: sim, cykel och lopning.")
    elif goal_choice in ("1",):
        data["sports"] = ["run"]
        print("  > Fokus: lopning.")
    else:
        print("  Vilka aktiviteter vill du gora?")
        print("  1=Lopning  2=Cykel  3=Simning  4=Styrka")
        print("  Valj flera med komma, t.ex. 1,2,4")
        sport_input = input("  Sporter: ").strip()
        sport_map = {"1": "run", "2": "bike", "3": "swim", "4": "strength"}
        data["sports"] = [sport_map[s.strip()] for s in sport_input.split(",") if s.strip() in sport_map]
        if not data["sports"]:
            data["sports"] = ["run"]

    # 3. Utrustning
    separator("3. Utrustning")
    print("  Vilken trananigsutrustning har du? (Valj alla som stammer)")
    print("  [1] Sportklocka (Garmin, Apple Watch, etc.)")
    print("  [2] Pulsband")
    print("  [3] Wattmatare (cykel)")
    print("  [4] Indoor trainer / rulle")
    print("  [5] Inget av ovan - bara skor och viljan!")
    print()
    eq_input = input("  Valj (t.ex. 1,2): ").strip()
    eq_map = {
        "1": "sportklocka", "2": "pulsband", "3": "wattmatare", "4": "indoor trainer",
    }
    if "5" in eq_input or not eq_input:
        data["equipment"] = []
        print("  > Det gar bra! Vi borjar med upplevd anstrangning.")
        if data["experience_level"] != "advanced":
            print("  > Tips: En sportklocka och pulsband gor det lattare att folja utvecklingen.")
    else:
        data["equipment"] = [eq_map[e.strip()] for e in eq_input.split(",") if e.strip() in eq_map]

    # 4. Grunddata (snabb)
    separator("4. Lite om dig")
    data["height_cm"]      = ask_int("Langd (cm)", default=None)
    data["weight_kg"]      = ask_float("Vikt (kg)", default=None)
    data["blood_pressure"] = ""

    # 5. Tavling (valfritt)
    separator("5. Har du ett specifikt datum du tranar mot?")
    print("  T.ex. en tavling, ett lopp, eller ett personligt mal-datum.")
    print("  Tryck Enter om du inte har nagot specifikt datum.")
    data["next_race_name"] = ask("Namn pa tavling/mal", required=False)
    if data["next_race_name"]:
        data["next_race_date"] = ask_date("Datum")
        if data["next_race_date"]:
            weeks = (date.fromisoformat(data["next_race_date"]) - date.today()).days // 7
            print(f"\n  > {weeks} veckor kvar till {data['next_race_name']}.")
    else:
        data["next_race_date"] = ""

    # 6. Testvarden - BARA for avancerade eller de som har utrustning
    if data["experience_level"] == "advanced":
        separator("6. Testvarden")
        print("  Om du inte har ett varde - tryck Enter.")
        if "bike" in data["sports"]:
            data["ftp_watts"] = ask_int("FTP (watt)")
        if "run" in data["sports"]:
            data["at_pace"] = ask_pace("AT-fart lopning")
            data["lt_pace"] = ask_pace("LT-fart lopning (aerob troskel)")
            data["at_hr"]   = ask_int("AT-puls (slag/min)")
            data["lt_hr"]   = ask_int("LT-puls (slag/min)")
        if "swim" in data["sports"]:
            data["css"] = ask_pace("CSS simning (min:sek/100m)")
    elif data["experience_level"] == "intermediate" and "pulsband" in data.get("equipment", []):
        separator("6. Pulsvarden (valfritt)")
        print("  Om du kanner till din maxpuls eller vilpuls - fyll i.")
        print("  Annars hoppar vi over detta och anvander upplevd anstrangning.")
        data["at_hr"] = ask_int("Ungefar maxpuls (slag/min)")
        data["lt_hr"] = ask_int("Vilpuls (slag/min)")
    else:
        print()
        print("  > Vi skippar testvarden for nu - Nils anvander upplevd anstrangning (RPE).")
        print("  > Nar du vill kan du gora tester for att fa mer exakta zoner.")

    # 7. Halsa
    separator("7. Halsosituation")
    print("  Beratta om eventuella halsoproblem, skador eller mediciner")
    print("  som kan paverka tranaingen. (Enter for att hoppa over)")
    data["health_notes"] = ask("Halsoanteckningar", required=False)

    # 8. Styrka (kort)
    data["strength"] = {}
    if data["experience_level"] == "advanced":
        separator("8. Styrkevarden (valfritt)")
        data["strength"] = {
            "benchpress_kg":     ask_float("Bankpress (kg)"),
            "squat_kg":          ask_float("Knaboj (kg)"),
            "deadlift_kg":       ask_float("Marklyft (kg)"),
            "overhead_press_kg": ask_float("Axelpress (kg)"),
            "pullups_reps":      ask_int("Pull-ups (antal reps)"),
        }

    # 9. Preferenser
    separator("8. Preferenser")
    data["preferences"] = ask("Nagot mer Nils bor veta? (tider, dagar, begransningar)", required=False)
    data["ironman_finishes"] = 0
    if data["experience_level"] == "advanced" and "swim" in data["sports"]:
        data["ironman_finishes"] = ask_int("Antal Ironman/langdistans klara", default=0)

    # Garmin CSV
    separator("9. Traningshistorik (valfritt)")
    print("  Om du har exporterat aktiviteter fran Garmin Connect (CSV),")
    print("  kan du importera dem for att Nils ska se din historik.")
    csv_path = ask("Sokvag till Garmin CSV-fil", required=False)
    if csv_path and Path(csv_path).exists():
        input_dir = Path(__file__).parent / "input"
        input_dir.mkdir(exist_ok=True)
        dest = input_dir / Path(csv_path).name
        dest.write_bytes(Path(csv_path).read_bytes())
        print(f"  > Sparad till {dest}")
        print("  > Importerar...")
        sys.path.insert(0, str(Path(__file__).parent))
        from data.ingest import ingest
        ins, skp = ingest(str(dest), replace=True)
        print(f"  > {ins} pass importerade.")
    elif csv_path:
        print(f"  > Filen hittades inte: {csv_path}")

    # Spara
    # Se till att alla nycklar finns (defaults for de som inte fylldes i)
    data.setdefault("ftp_watts", None)
    data.setdefault("at_pace", None)
    data.setdefault("lt_pace", None)
    data.setdefault("at_hr", None)
    data.setdefault("lt_hr", None)
    data.setdefault("css", None)
    data.setdefault("equipment", [])
    data.setdefault("sports", ["run"])

    PROFILE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("+--------------------------------------------------+")
    print("|  Profil sparad!                                    |")
    print("+--------------------------------------------------+")
    print()
    level_desc = {"beginner": "Nyborjare", "intermediate": "Motionar", "advanced": "Avancerad"}
    print(f"  Niva: {level_desc.get(data['experience_level'], data['experience_level'])}")
    print(f"  Mal: {data['goal']}")
    if data.get("next_race_name"):
        print(f"  Tavling: {data['next_race_name']} ({data.get('next_race_date', '')})")
    print()
    print("  Starta Nils:  streamlit run app.py")
    print()

    return data


if __name__ == "__main__":
    if PROFILE_FILE.exists():
        print(f"\n  En profil finns redan ({PROFILE_FILE.name}).")
        ans = input("  Kor om onboarding och skriv over? [j/N]: ").strip().lower()
        if ans != "j":
            print("  Avbryter.\n")
            sys.exit(0)
    run_onboarding()
