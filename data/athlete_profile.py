"""
Atletprofil. Kan läsas från JSON-fil (genereras av onboarding.py)
eller använda hårdkodade defaults (Niklas Svidén, för utveckling).

Prioritering: athlete_data.json → defaults
"""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional
import json

PROFILE_FILE = Path(__file__).parent.parent / "athlete_data.json"


@dataclass
class CycleZones:
    ftp: int
    z1_max: int = field(init=False)
    z2_min: int = field(init=False)
    z2_max: int = field(init=False)
    z3_min: int = field(init=False)
    z3_max: int = field(init=False)
    z4_min: int = field(init=False)
    z4_max: int = field(init=False)
    z5_min: int = field(init=False)

    def __post_init__(self):
        self.z1_max = int(self.ftp * 0.55)
        self.z2_min = int(self.ftp * 0.55)
        self.z2_max = int(self.ftp * 0.75)
        self.z3_min = int(self.ftp * 0.75)
        self.z3_max = int(self.ftp * 0.90)
        self.z4_min = int(self.ftp * 0.90)
        self.z4_max = int(self.ftp * 1.05)
        self.z5_min = int(self.ftp * 1.05)

    def summary(self) -> str:
        return (
            f"Cykelzoner (FTP: {self.ftp}W)\n"
            f"  Z1 Återhämtning: < {self.z1_max}W\n"
            f"  Z2 Aerob bas:    {self.z2_min}–{self.z2_max}W\n"
            f"  Z3 Tempo:        {self.z3_min}–{self.z3_max}W\n"
            f"  Z4 Tröskel:      {self.z4_min}–{self.z4_max}W\n"
            f"  Z5 VO2max:       > {self.z5_min}W"
        )


@dataclass
class RunZones:
    at_pace_str: str
    lt_pace_str: str
    at_hr: int
    lt_hr: int

    @staticmethod
    def _to_sec(pace: str) -> int:
        m, s = pace.split(":")
        return int(m) * 60 + int(s)

    @staticmethod
    def _to_pace(secs: int) -> str:
        return f"{secs // 60}:{secs % 60:02d}"

    def summary(self) -> str:
        at = self._to_sec(self.at_pace_str)
        lt = self._to_sec(self.lt_pace_str)
        return (
            f"Löpzoner (AT: {self.at_pace_str}/km, puls {self.at_hr})\n"
            f"  Z1 Återhämtning: > {self._to_pace(int(lt * 1.10))}/km   puls < {int(self.lt_hr * 0.85)}\n"
            f"  Z2 Aerob bas:    {self._to_pace(int(at * 1.15))}–{self._to_pace(int(lt * 1.10))}/km   puls {int(self.lt_hr * 0.85)}–{self.lt_hr}\n"
            f"  Z3 Tempo:        {self._to_pace(int(at * 1.06))}–{self._to_pace(int(at * 1.15))}/km   puls {self.lt_hr}–{int(self.at_hr * 0.95)}\n"
            f"  Z4 Tröskel:      {self.at_pace_str}–{self._to_pace(int(at * 1.06))}/km   puls {int(self.at_hr * 0.95)}–{self.at_hr}\n"
            f"  Z5 VO2max:       < {self.at_pace_str}/km   puls > {self.at_hr}"
        )


@dataclass
class SwimZones:
    css_str: str

    @staticmethod
    def _to_sec(pace: str) -> int:
        m, s = pace.split(":")
        return int(m) * 60 + int(s)

    @staticmethod
    def _to_pace(secs: int) -> str:
        return f"{secs // 60}:{secs % 60:02d}"

    def summary(self) -> str:
        css = self._to_sec(self.css_str)
        return (
            f"Simzoner (CSS: {self.css_str}/100m)\n"
            f"  Z1 Återhämtning: > {self._to_pace(int(css * 1.20))}/100m\n"
            f"  Z2 Aerob bas:    {self._to_pace(int(css * 1.08))}–{self._to_pace(int(css * 1.20))}/100m\n"
            f"  Z3 Tempo:        {self._to_pace(int(css * 1.02))}–{self._to_pace(int(css * 1.08))}/100m\n"
            f"  Z4 Tröskel:      {self.css_str}–{self._to_pace(int(css * 1.02))}/100m\n"
            f"  Z5 Sprint:       < {self._to_pace(int(css * 0.95))}/100m"
        )


@dataclass
class StrengthProfile:
    benchpress_kg: Optional[float] = None
    squat_kg: Optional[float] = None
    deadlift_kg: Optional[float] = None
    overhead_press_kg: Optional[float] = None
    pullups_reps: Optional[int] = None

    def summary(self) -> str:
        lines = ["Styrkevärden"]
        pairs = [
            ("Bänkpress", self.benchpress_kg, "kg"),
            ("Knäböj", self.squat_kg, "kg"),
            ("Marklyft", self.deadlift_kg, "kg"),
            ("Axelpress", self.overhead_press_kg, "kg"),
            ("Pull-ups", self.pullups_reps, "reps"),
        ]
        for label, val, unit in pairs:
            if val:
                lines.append(f"  {label:<12} {val} {unit}")
            else:
                lines.append(f"  {label:<12} –")
        return "\n".join(lines)


class AthleteProfile:
    """
    Läser profil från athlete_data.json om den finns,
    annars används Niklas hårdkodade defaults (för utveckling).

    experience_level: "beginner", "intermediate", "advanced"
    Styr hur Trixa kommunicerar (RPE vs zoner, enkel vs teknisk).
    """

    def __init__(self, profile_file: Path = PROFILE_FILE):
        if profile_file.exists():
            self._load_from_file(profile_file)
        else:
            self._load_defaults()
        self._build_zones()

    def _load_defaults(self):
        """Niklas Svidén – används under utveckling."""
        self.name             = "Niklas Svidén"
        self.experience_level = "advanced"
        self.goal             = "Ironman Kalmar 2026"
        self.sports           = ["swim", "bike", "run"]
        self.equipment        = ["sportklocka", "pulsband", "wattmätare", "indoor trainer"]
        self.height_cm        = 178
        self.weight_kg        = 89
        self.blood_pressure   = "130/80"
        self.ftp_watts        = 180
        self.at_pace          = "4:45"
        self.lt_pace          = "6:15"
        self.at_hr            = 170
        self.lt_hr            = 150
        self.css              = "2:30"
        self.ironman_finishes = 13
        self.next_race_name   = "Ironman Kalmar 2026"
        self.next_race_date   = "2026-08-15"
        self.health_notes     = (
            "Hypotyreos sedan 2017 (medicineras). Påverkar återhämtning och "
            "energinivå – extra viktigt att inte underåterhämta. Blodtryck 130/80."
        )
        self.preferences      = (
            "9-dagarscykel med tre vilodagar varav två sammanhängande. "
            "Träningstid varierar, periodvis under 5h/vecka."
        )
        self.strength = StrengthProfile(
            benchpress_kg=30, squat_kg=50, deadlift_kg=80, overhead_press_kg=20
        )

    def _load_from_file(self, path: Path):
        """Läser profil skapad av onboarding.py."""
        d = json.loads(path.read_text(encoding="utf-8"))
        self.name             = d.get("name", "Okänd")
        self.experience_level = d.get("experience_level", "unknown")
        self.goal             = d.get("goal", "")
        self.sports           = d.get("sports", [])
        self.equipment        = d.get("equipment", [])
        self.height_cm        = d.get("height_cm")
        self.weight_kg        = d.get("weight_kg")
        self.blood_pressure   = d.get("blood_pressure", "")
        self.ftp_watts        = d.get("ftp_watts")
        self.at_pace          = d.get("at_pace")
        self.lt_pace          = d.get("lt_pace")
        self.at_hr            = d.get("at_hr")
        self.lt_hr            = d.get("lt_hr")
        self.css              = d.get("css")
        self.ironman_finishes = d.get("ironman_finishes", 0)
        self.next_race_name   = d.get("next_race_name", "")
        self.next_race_date   = d.get("next_race_date", "")
        self.health_notes     = d.get("health_notes", "")
        self.preferences      = d.get("preferences", "")
        s = d.get("strength", {})
        self.strength = StrengthProfile(
            benchpress_kg=s.get("benchpress_kg"),
            squat_kg=s.get("squat_kg"),
            deadlift_kg=s.get("deadlift_kg"),
            overhead_press_kg=s.get("overhead_press_kg"),
            pullups_reps=s.get("pullups_reps"),
        )

    def _build_zones(self):
        if self.ftp_watts:
            self.cycle = CycleZones(ftp=self.ftp_watts)
        else:
            self.cycle = None
        if self.at_pace and self.lt_pace and self.at_hr and self.lt_hr:
            self.run = RunZones(
                at_pace_str=self.at_pace,
                lt_pace_str=self.lt_pace,
                at_hr=self.at_hr,
                lt_hr=self.lt_hr,
            )
        else:
            self.run = None
        if self.css:
            self.swim = SwimZones(css_str=self.css)
        else:
            self.swim = None

    def weeks_to_race(self) -> Optional[int]:
        if not self.next_race_date:
            return None
        try:
            race = date.fromisoformat(self.next_race_date)
            return max(0, (race - date.today()).days // 7)
        except ValueError:
            return None

    def full_summary(self) -> str:
        weeks = self.weeks_to_race()
        race_info = ""
        if self.next_race_name and weeks is not None:
            race_info = f"Nästa tävling: {self.next_race_name} ({self.next_race_date}) — {weeks} veckor kvar"

        lines = [
            f"=== ATLETPROFIL: {self.name} ===",
            f"Erfarenhetsnivå: {self.experience_level}",
        ]
        if self.goal:
            lines.append(f"Mål: {self.goal}")
        if self.sports:
            lines.append(f"Sporter: {', '.join(self.sports)}")
        if self.equipment:
            lines.append(f"Utrustning: {', '.join(self.equipment)}")
        if self.height_cm:
            bp = f"   Blodtryck: {self.blood_pressure}" if self.blood_pressure else ""
            lines.append(f"Längd: {self.height_cm} cm   Vikt: {self.weight_kg} kg{bp}")
        if self.ironman_finishes:
            lines.append(f"Ironman-mål: {self.ironman_finishes} klara")
        if race_info:
            lines.append(race_info)
        if self.health_notes:
            lines.append(f"Hälsa: {self.health_notes}")
        if self.preferences:
            lines.append(f"Preferenser: {self.preferences}")

        # Zoner visas bara om de finns
        if self.cycle:
            lines += ["", self.cycle.summary()]
        if self.run:
            lines += ["", self.run.summary()]
        if self.swim:
            lines += ["", self.swim.summary()]
        if not self.cycle and not self.run and not self.swim:
            lines.append("\nInga testvärden/zoner registrerade – använd RPE (upplevd ansträngning 1-10).")

        lines += ["", self.strength.summary()]
        return "\n".join(lines)

    def to_context_string(self) -> str:
        return self.full_summary()


if __name__ == "__main__":
    print(AthleteProfile().full_summary())
