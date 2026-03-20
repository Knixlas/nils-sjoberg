"""
Trixa – Streamlit Web App (Multi-user)
Personlig AI-tranare driven av Claude.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

import io

import streamlit as st

# ── Page config (MUST be first st call) ────────────────────────────
st.set_page_config(
    page_title="Trixa",
    page_icon="🏊",
    layout="centered",
    initial_sidebar_state="auto",
)

# ── Debug mode: catch ALL import/startup errors ──────────────────
_IMPORT_ERROR = None
try:
    import anthropic
    import pandas as pd
    from dotenv import load_dotenv

    # Setup paths
    ROOT = Path(__file__).parent
    load_dotenv(ROOT / ".env", override=True)
    sys.path.insert(0, str(ROOT))

    # On Streamlit Cloud, secrets are in st.secrets - sync to os.environ
    try:
        for key in st.secrets:
            if isinstance(st.secrets[key], str):
                os.environ.setdefault(key, st.secrets[key])
    except Exception:
        pass

    from data.athlete_profile import AthleteProfile
    from data.phase_detector import detect_phase, phase_context
    from data.workout_library import library_summary, library_stats
    from data.knowledge_base import (
        list_articles, add_article, remove_article, knowledge_summary,
    )
    from data import db
    from data.membership import (
        get_user_tier, can_send_message, can_use_feature,
        messages_remaining, trial_days_remaining,
    )
except Exception as e:
    _IMPORT_ERROR = traceback.format_exc()
    ROOT = Path(__file__).parent

# Show import errors IMMEDIATELY
if _IMPORT_ERROR:
    st.error("App kunde inte starta. Feldetaljer:")
    st.code(_IMPORT_ERROR)
    st.stop()

SYSTEM_PROMPT_FILE = ROOT / "prompts" / "system_prompt.md"
MODEL = "claude-sonnet-4-5"
MAX_HISTORY = 20
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")
STRIPE_MONTHLY_LINK = os.environ.get("STRIPE_MONTHLY_LINK", "")
STRIPE_YEARLY_LINK = os.environ.get("STRIPE_YEARLY_LINK", "")
STRIPE_PORTAL_LINK = os.environ.get("STRIPE_PORTAL_LINK", "")

# ── TCX Workout Tool Definition ────────────────────────────────────

WORKOUT_TOOL = {
    "name": "create_workout_file",
    "description": (
        "Skapa ett strukturerat traningspass som pushas till Intervals.icu och visas pa klockan. "
        "VIKTIGT: For lopning, ange ALLTID hr_high (ovre pulsgrans) pa varje active-steg baserat pa atletens zoner. "
        "For cykling, ange ALLTID power_high (ovre wattgrans). "
        "Ange description pa varje steg - det visas pa klockan under passet."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Passnamn, t.ex. 'Sweet Spot 3x8min'"},
            "sport": {"type": "string", "enum": ["running", "biking", "swimming"], "description": "Sport"},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["warmup", "active", "rest", "cooldown"]},
                        "duration_seconds": {"type": "integer", "description": "Langd i sekunder"},
                        "repeats": {"type": "integer", "description": "Antal repetitioner (bara for intervaller)"},
                        "description": {"type": "string", "description": "Visas pa klockan, t.ex. 'Hog fart Z4' eller 'Latt jogg'"},
                        "hr_high": {"type": "integer", "description": "Ovre pulsgrans i bpm. OBLIGATORISK for lopning."},
                        "power_high": {"type": "integer", "description": "Ovre wattgrans. OBLIGATORISK for cykling."},
                    },
                    "required": ["type", "duration_seconds", "description"],
                },
                "description": "Steg i passet. Varje steg MASTE ha description och hr_high (lopning) eller power_high (cykling).",
            },
        },
        "required": ["name", "sport", "steps"],
    },
}

# ── Mobile-friendly CSS ─────────────────────────────────────────────

MOBILE_CSS = """
<style>
    /* Mobile-first: tight padding, room for bottom nav */
    .block-container {
        padding: 0.5rem 0.8rem 5rem 0.8rem !important;
        max-width: 100% !important;
    }
    h1 { font-size: 1.4rem !important; margin-bottom: 0.2rem !important; }
    h3 { font-size: 1.1rem !important; margin-top: 0.5rem !important; }
    .stChatMessage { padding: 0.4rem !important; }

    /* Hide sidebar completely */
    section[data-testid="stSidebar"] { display: none !important; }
    button[data-testid="stSidebarCollapsedControl"] { display: none !important; }

    /* Nav buttons: compact style */
    [data-testid="stButton"] > button {
        font-size: 0.85rem !important;
        padding: 0.3rem 0.5rem !important;
    }

    /* Status cards */
    .status-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border-radius: 12px;
        padding: 1rem;
        margin-bottom: 0.5rem;
        color: white;
    }
    .status-card h4 { margin: 0 0 0.3rem 0; font-size: 0.85rem; opacity: 0.7; }
    .status-card .big { font-size: 1.8rem; font-weight: 700; margin: 0; }
    .status-card .sub { font-size: 0.8rem; opacity: 0.6; }

    /* Tip box */
    .tip-box {
        background: linear-gradient(135deg, #0d7377 0%, #14919b 100%);
        border-radius: 12px;
        padding: 1rem;
        color: white;
        margin: 0.5rem 0;
    }
    .tip-box .tip-label { font-size: 0.75rem; opacity: 0.7; text-transform: uppercase; letter-spacing: 1px; }
    .tip-box .tip-text { font-size: 0.95rem; margin-top: 0.3rem; }

    /* Chat styling */
    .stChatMessage [data-testid="stMarkdownContainer"] p { line-height: 1.6; }

    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* Desktop: limit width */
    @media (min-width: 769px) {
        .block-container { max-width: 700px !important; margin: auto; }
    }
</style>
"""


# ── Helpers ──────────────────────────────────────────────────────────

WEEKDAYS_SV = ["mandag", "tisdag", "onsdag", "torsdag", "fredag", "lordag", "sondag"]


def _inject_date(text: str) -> str:
    """Replace date placeholders with actual current date info."""
    now = datetime.now()
    return (
        text
        .replace("{TODAY_DATE}", now.strftime("%Y-%m-%d"))
        .replace("{TODAY_WEEKDAY}", WEEKDAYS_SV[now.weekday()])
        .replace("{CURRENT_YEAR}", str(now.year))
        .replace("{LAST_YEAR}", str(now.year - 1))
    )


def build_system_prompt(profile: AthleteProfile) -> str:
    template = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")
    workouts = "Ingen träningsdata tillgänglig för denna användare ännu."
    vol_text = ""
    weeks = profile.weeks_to_race()
    fas_ctx = phase_context(weeks, None)
    return _inject_date(
        template
        .replace("{ATHLETE_PROFILE}", profile.to_context_string())
        .replace("{PHASE_CONTEXT}", fas_ctx)
        .replace("{RECENT_WORKOUTS}", workouts + vol_text)
        .replace("{WORKOUT_LIBRARY}", library_summary())
        .replace("{KNOWLEDGE_BASE}", knowledge_summary())
    )


def build_system_prompt_admin(profile: AthleteProfile) -> str:
    """Admin version with full workout log access."""
    from data.ingest import recent_summary, weekly_volume, DB_PATH
    template = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")
    db_path = DB_PATH if DB_PATH.exists() else None
    if db_path:
        workouts = recent_summary(db_path, days=21)
        vol = weekly_volume(db_path, weeks=8)
        if "Ingen träningsdata" not in vol:
            workouts += "\n\n" + vol
    else:
        workouts = "Ingen träningsdata tillgänglig (databas saknas)."
    weeks = profile.weeks_to_race()
    fas_ctx = phase_context(weeks, db_path)
    return _inject_date(
        template
        .replace("{ATHLETE_PROFILE}", profile.to_context_string())
        .replace("{PHASE_CONTEXT}", fas_ctx)
        .replace("{RECENT_WORKOUTS}", workouts)
        .replace("{WORKOUT_LIBRARY}", library_summary())
        .replace("{KNOWLEDGE_BASE}", knowledge_summary())
    )


def get_anthropic_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        st.error("ANTHROPIC_API_KEY saknas.")
        st.stop()
    return anthropic.Anthropic(api_key=api_key)


def parse_spreadsheet(file_bytes: bytes, filename: str) -> str:
    """Parse CSV/XLSX/XLS to a text representation Claude can read."""
    ext = filename.rsplit(".", 1)[-1].lower()
    try:
        if ext == "csv":
            df = pd.read_csv(io.BytesIO(file_bytes))
        elif ext in ("xlsx", "xls"):
            df = pd.read_excel(io.BytesIO(file_bytes))
        else:
            return f"[Okant filformat: {ext}]"

        # Limit to first 200 rows to avoid token overflow
        truncated = ""
        if len(df) > 200:
            df = df.head(200)
            truncated = f"\n(Visar 200 av {len(df)} rader)"

        summary = f"Fil: {filename} ({len(df)} rader, {len(df.columns)} kolumner)\n"
        summary += f"Kolumner: {', '.join(df.columns.astype(str))}\n\n"
        summary += df.to_string(index=False, max_rows=200)
        summary += truncated
        return summary
    except Exception as e:
        return f"[Kunde inte lasa {filename}: {e}]"


def build_message_content(text: str, attachment=None):
    """Build Claude API message content with optional file attachment."""
    if not attachment:
        return text

    blocks = []
    file_bytes = attachment["bytes"]
    mime = attachment["type"]
    filename = attachment["name"]
    ext = filename.rsplit(".", 1)[-1].lower()

    if mime.startswith("image/"):
        b64 = base64.b64encode(file_bytes).decode("utf-8")
        blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": mime, "data": b64},
        })
    elif mime == "application/pdf":
        b64 = base64.b64encode(file_bytes).decode("utf-8")
        blocks.append({
            "type": "document",
            "source": {"type": "base64", "media_type": mime, "data": b64},
        })
    elif ext in ("csv", "xlsx", "xls"):
        spreadsheet_text = parse_spreadsheet(file_bytes, filename)
        blocks.append({
            "type": "text",
            "text": f"[Bifogad data]\n{spreadsheet_text}",
        })

    blocks.append({"type": "text", "text": text or f"[Bifogad fil: {filename}]"})
    return blocks


st.markdown(MOBILE_CSS, unsafe_allow_html=True)


# ── Auth Flow ────────────────────────────────────────────────────────

def show_auth_page():
    """Login/signup page."""
    st.markdown("## Trixa")
    st.caption("Din personliga AI-tranare")
    st.markdown("---")

    tab_login, tab_signup = st.tabs(["Logga in", "Skapa konto"])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("E-post")
            password = st.text_input("Losenord", type="password")
            submitted = st.form_submit_button("Logga in", use_container_width=True)
            if submitted and email and password:
                try:
                    result = db.sign_in(email, password)
                    if result.user:
                        st.session_state.user = result.user
                        st.session_state.session = result.session
                        st.rerun()
                except Exception as e:
                    err = str(e)
                    if "Invalid login" in err:
                        st.error("Fel e-post eller losenord.")
                    else:
                        st.error(f"Inloggning misslyckades: {err}")

    with tab_signup:
        with st.form("signup_form"):
            name = st.text_input("Ditt namn")
            email_s = st.text_input("E-post", key="signup_email")
            pw_s = st.text_input("Losenord (minst 6 tecken)", type="password", key="signup_pw")
            submitted_s = st.form_submit_button("Skapa konto", use_container_width=True)
            if submitted_s and email_s and pw_s and name:
                if len(pw_s) < 6:
                    st.error("Losenordet maste vara minst 6 tecken.")
                else:
                    try:
                        result = db.sign_up(email_s, pw_s, name)
                        if result.user:
                            st.success("Konto skapat! Logga in med dina uppgifter.")
                    except Exception as e:
                        st.error(f"Registrering misslyckades: {e}")


# ── Check auth state ─────────────────────────────────────────────────

if "user" not in st.session_state:
    show_auth_page()
    st.stop()

user = st.session_state.user
session = st.session_state.session
access_token = session.access_token
is_admin = (user.email == ADMIN_EMAIL)


# ── Load user profile from Supabase ──────────────────────────────────

if "profile" not in st.session_state:
    db_profile = db.get_profile(user.id, access_token)
    if db_profile:
        athlete_dict = db.profile_to_athlete_dict(db_profile)
        tmp_profile = ROOT / f".profile_{user.id}.json"
        tmp_profile.write_text(json.dumps(athlete_dict, ensure_ascii=False), encoding="utf-8")
        st.session_state.profile = AthleteProfile(profile_file=tmp_profile)
        st.session_state.db_profile = db_profile
    else:
        st.session_state.profile = AthleteProfile.__new__(AthleteProfile)
        st.session_state.profile.name = user.user_metadata.get("name", "")
        st.session_state.profile.experience_level = "unknown"
        st.session_state.profile.goal = ""
        st.session_state.profile.sports = []
        st.session_state.profile.equipment = []
        st.session_state.profile.height_cm = None
        st.session_state.profile.weight_kg = None
        st.session_state.profile.blood_pressure = ""
        st.session_state.profile.ftp_watts = None
        st.session_state.profile.at_pace = None
        st.session_state.profile.lt_pace = None
        st.session_state.profile.at_hr = None
        st.session_state.profile.lt_hr = None
        st.session_state.profile.css = None
        st.session_state.profile.ironman_finishes = 0
        st.session_state.profile.next_race_name = ""
        st.session_state.profile.next_race_date = ""
        st.session_state.profile.health_notes = ""
        st.session_state.profile.preferences = ""
        st.session_state.profile.strength = None
        st.session_state.profile.cycle = None
        st.session_state.profile.run = None
        st.session_state.profile.swim = None
        st.session_state.db_profile = None

profile = st.session_state.profile

# ── Load subscription ────────────────────────────────────────────────

if "subscription" not in st.session_state:
    try:
        st.session_state.subscription = db.ensure_trial(user.id, access_token)
    except Exception:
        st.session_state.subscription = None

subscription = st.session_state.subscription
tier = get_user_tier(subscription, is_admin)

# ── Load conversation from Supabase ──────────────────────────────────

if "history" not in st.session_state:
    conv = db.get_conversation(user.id, access_token)
    if conv:
        st.session_state.history = conv["messages"]
        st.session_state.conv_id = conv["id"]
    else:
        st.session_state.history = []
        st.session_state.conv_id = None

history = st.session_state.history

# ── Build system prompt ──────────────────────────────────────────────

if "system_prompt" not in st.session_state:
    if is_admin:
        st.session_state.system_prompt = build_system_prompt_admin(profile)
    else:
        st.session_state.system_prompt = build_system_prompt(profile)

if "client" not in st.session_state:
    st.session_state.client = get_anthropic_client()


# ── Precompute shared data ────────────────────────────────────────────

weeks = profile.weeks_to_race()
trial_days = trial_days_remaining(subscription)


def _extract_latest_plan() -> str | None:
    """Pull the last weekly plan from chat history (assistant messages)."""
    for msg in reversed(history):
        if msg["role"] == "assistant" and msg.get("content"):
            text = msg["content"]
            # Look for plan markers
            for marker in ["VECKOPLAN", "MAN ", "Mandag", "**Man", "**Mån"]:
                if marker in text:
                    return text
    return None


def _extract_tip() -> str | None:
    """Pull a short coaching tip from the latest assistant message."""
    for msg in reversed(history):
        if msg["role"] == "assistant" and msg.get("content"):
            text = msg["content"]
            # Return last paragraph as tip (usually the personal comment)
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            if paragraphs:
                tip = paragraphs[-1]
                # Cap at ~200 chars for the card
                if len(tip) > 200:
                    tip = tip[:197] + "..."
                return tip
    return None


# ── Navigation state ──────────────────────────────────────────────────

if "active_tab" not in st.session_state:
    st.session_state.active_tab = "hem"

# Bottom nav using real Streamlit buttons (no page reload)
_nav_container = st.container()
with _nav_container:
    nc1, nc2, nc3 = st.columns(3)
    with nc1:
        if st.button("Hem", use_container_width=True, key="nav_hem",
                      type="primary" if st.session_state.active_tab == "hem" else "secondary"):
            st.session_state.active_tab = "hem"
            st.rerun()
    with nc2:
        if st.button("Chatt", use_container_width=True, key="nav_chatt",
                      type="primary" if st.session_state.active_tab == "chatt" else "secondary"):
            st.session_state.active_tab = "chatt"
            st.rerun()
    with nc3:
        if st.button("Profil", use_container_width=True, key="nav_profil",
                      type="primary" if st.session_state.active_tab == "profil" else "secondary"):
            st.session_state.active_tab = "profil"
            st.rerun()

active_tab = st.session_state.active_tab


# ── Header (always visible) ───────────────────────────────────────────

col_title, col_user = st.columns([3, 2])
with col_title:
    st.markdown("# Trixa")
with col_user:
    name_display = profile.name or user.email
    st.markdown(
        f"<div style='text-align:right; padding-top:0.7rem; font-size:0.85rem; opacity:0.6'>{name_display}</div>",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════
# TAB: HEM
# ══════════════════════════════════════════════════════════════════════

if active_tab == "hem":

    # --- Status cards row ---
    if profile.next_race_name and weeks is not None:
        fas, _ = detect_phase(weeks, None)
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f"""<div class="status-card">
                <h4>Veckor kvar</h4>
                <p class="big">{weeks}</p>
                <p class="sub">{profile.next_race_name}</p>
            </div>""", unsafe_allow_html=True)
        with c2:
            st.markdown(f"""<div class="status-card">
                <h4>Fas</h4>
                <p class="big">{fas[:10]}</p>
                <p class="sub">{profile.next_race_date or ''}</p>
            </div>""", unsafe_allow_html=True)
        with c3:
            tier_label = "Premium" if tier == "premium" else "Gratis"
            if trial_days is not None and trial_days > 0:
                tier_label = f"Trial ({trial_days}d)"
            st.markdown(f"""<div class="status-card">
                <h4>Medlemskap</h4>
                <p class="big">{tier_label}</p>
                <p class="sub">{profile.goal[:30] + '...' if profile.goal and len(profile.goal) > 30 else profile.goal or ''}</p>
            </div>""", unsafe_allow_html=True)
    else:
        # No race set — simpler status
        c1, c2 = st.columns(2)
        with c1:
            tier_label = "Premium" if tier == "premium" else "Gratis"
            if trial_days is not None and trial_days > 0:
                tier_label = f"Trial ({trial_days}d)"
            st.markdown(f"""<div class="status-card">
                <h4>Medlemskap</h4>
                <p class="big">{tier_label}</p>
            </div>""", unsafe_allow_html=True)
        with c2:
            if profile.goal:
                st.markdown(f"""<div class="status-card">
                    <h4>Mal</h4>
                    <p class="big" style="font-size:1rem">{profile.goal[:50]}</p>
                </div>""", unsafe_allow_html=True)

    # --- Tip box ---
    tip = _extract_tip()
    if tip:
        st.markdown(f"""<div class="tip-box">
            <div class="tip-label">Tank pa just nu</div>
            <div class="tip-text">{tip}</div>
        </div>""", unsafe_allow_html=True)

    # --- Weekly plan ---
    st.markdown("### Veckoplan")
    plan = _extract_latest_plan()
    if plan:
        st.markdown(plan)
    else:
        st.info("Ingen veckoplan annu. Ga till **Chatt** och be Trixa om en veckoplan!")

    # --- Workout export buttons from latest plan ---
    latest_workout = None
    for msg in reversed(history):
        if msg.get("workout"):
            latest_workout = msg["workout"]
            break
    if latest_workout:
        st.markdown("---")
        col_dl, col_icu = st.columns(2)
        with col_dl:
            from data.tcx_export import generate_tcx
            tcx_data = generate_tcx(latest_workout)
            st.download_button(
                label="Ladda ner .tcx",
                data=tcx_data,
                file_name=f"{latest_workout['name'].replace(' ', '_')}.tcx",
                mime="application/vnd.garmin.tcx+xml",
                key="home_dl_tcx",
            )
        with col_icu:
            icu_cfg = None
            try:
                icu_cfg = db.get_intervals_settings(user.id, access_token)
            except Exception:
                pass
            if icu_cfg:
                if st.button("Pusha till Intervals.icu", key="home_icu_push"):
                    from data.intervals_icu import push_workout
                    result = push_workout(icu_cfg["api_key"], icu_cfg["athlete_id"], latest_workout)
                    if result.get("success"):
                        st.success("Pushat till Intervals.icu!")
                    else:
                        st.error(f"Fel: {result.get('error', 'Okant fel')}")


# ══════════════════════════════════════════════════════════════════════
# TAB: CHATT
# ══════════════════════════════════════════════════════════════════════

if active_tab == "chatt":

    # File uploader (premium feature)
    uploaded_file = None
    if can_use_feature(tier, "attachments"):
        uploaded_file = st.file_uploader(
            "Bifoga fil",
            type=["png", "jpg", "jpeg", "webp", "gif", "pdf", "csv", "xlsx", "xls"],
            key="file_upload",
            label_visibility="collapsed",
        )

    # Display chat history
    for msg in history:
        role = msg["role"]
        if msg.get("_auto"):
            continue
        with st.chat_message("assistant" if role == "assistant" else "user",
                             avatar=None):
            if msg.get("attachments"):
                for att in msg["attachments"]:
                    if att["type"].startswith("image/"):
                        st.image(att["url"], caption=att["name"], width=300)
                    else:
                        st.markdown(f"Bifogad: **{att['name']}**")
            st.markdown(msg["content"])

            # Workout export buttons
            if msg.get("workout"):
                wo = msg["workout"]
                col_dl, col_icu = st.columns(2)
                with col_dl:
                    from data.tcx_export import generate_tcx
                    tcx_data = generate_tcx(wo)
                    st.download_button(
                        label="Ladda ner .tcx",
                        data=tcx_data,
                        file_name=f"{wo['name'].replace(' ', '_')}.tcx",
                        mime="application/vnd.garmin.tcx+xml",
                        key=f"dl_{msg.get('_ts', '')}_{wo['name']}",
                    )
                with col_icu:
                    icu_cfg = None
                    try:
                        icu_cfg = db.get_intervals_settings(user.id, access_token)
                    except Exception:
                        pass
                    if icu_cfg:
                        if st.button("Pusha till Intervals.icu", key=f"icu_{msg.get('_ts', '')}_{wo['name']}"):
                            from data.intervals_icu import push_workout
                            result = push_workout(icu_cfg["api_key"], icu_cfg["athlete_id"], wo)
                            if result.get("success"):
                                st.success("Pushat till Intervals.icu!")
                            else:
                                st.error(f"Fel: {result.get('error', 'Okant fel')}")
                    else:
                        st.caption("Koppla Intervals.icu under Profil")

    # Auto-intro on first session
    if not history:
        with st.chat_message("assistant", avatar=None):
            with st.spinner("Trixa tanker..."):
                exp = getattr(profile, "experience_level", "unknown")
                if exp in ("beginner", "unknown"):
                    intro_msg = "Hej Trixa! Ny session. Presentera dig kort och fraga vad jag vill jobba med idag."
                elif exp == "intermediate":
                    intro_msg = "Hej Trixa! Ny session. Ge mig en kort statusuppdatering och fraga vad jag vill fokusera pa."
                else:
                    intro_msg = "Hej Trixa! Ny session. Ge mig en kort statusuppdatering baserat pa min traningslogg och hur det ser ut infor nasta tavling."
                history.append({"role": "user", "content": intro_msg, "_auto": True})

                with st.session_state.client.messages.stream(
                    model=MODEL,
                    max_tokens=2048,
                    system=st.session_state.system_prompt,
                    messages=[{"role": m["role"], "content": m["content"]} for m in history[-MAX_HISTORY:]],
                ) as stream:
                    response = st.write_stream(stream.text_stream)

                history.append({"role": "assistant", "content": response})
                st.session_state.conv_id = db.save_conversation(
                    user.id, access_token, history, st.session_state.get("conv_id")
                )

    # Free tier message limit warning
    if tier != "premium" and not is_admin:
        try:
            daily_count = db.get_daily_message_count(user.id, access_token)
        except Exception:
            daily_count = 0
        remaining = messages_remaining(tier, daily_count)
        st.caption(f"{remaining} meddelanden kvar idag")

# Chat input (outside tabs — always visible at bottom)
if prompt := st.chat_input("Skriv till Trixa..."):
    # Check message limit for free users
    try:
        daily_count = db.get_daily_message_count(user.id, access_token)
    except Exception:
        daily_count = 0
    if not can_send_message(tier, daily_count):
        st.error("Du har natt dagens grans (5 meddelanden). Uppgradera till Premium for obegransat!")
        if STRIPE_MONTHLY_LINK:
            st.link_button("Uppgradera nu", STRIPE_MONTHLY_LINK)
        st.stop()

    # Increment message count
    try:
        db.increment_daily_messages(user.id, access_token)
    except Exception:
        pass

    # Handle file attachment
    attachment = None
    attachment_meta = None
    if uploaded_file is not None:
        file_bytes = uploaded_file.read()
        attachment = {
            "bytes": file_bytes,
            "type": uploaded_file.type,
            "name": uploaded_file.name,
        }
        try:
            att_url = db.upload_attachment(user.id, access_token, file_bytes, uploaded_file.name)
            attachment_meta = {"type": uploaded_file.type, "url": att_url, "name": uploaded_file.name}
        except Exception:
            attachment_meta = {"type": uploaded_file.type, "url": "", "name": uploaded_file.name}

    with st.chat_message("user"):
        if attachment_meta:
            if attachment_meta["type"].startswith("image/"):
                st.image(attachment["bytes"], caption=attachment_meta["name"], width=300)
            else:
                st.markdown(f"Bifogad: **{attachment_meta['name']}**")
        st.markdown(prompt)

    msg_entry = {"role": "user", "content": prompt}
    if attachment_meta:
        msg_entry["attachments"] = [attachment_meta]
    history.append(msg_entry)

    with st.chat_message("assistant", avatar=None):
        content = build_message_content(prompt, attachment)
        clean = []
        for m in history[-MAX_HISTORY:]:
            if m.get("_auto"):
                continue
            clean.append({"role": m["role"], "content": m["content"]})
        if attachment and clean:
            clean[-1]["content"] = content

        tools = [WORKOUT_TOOL] if can_use_feature(tier, "workout_export") else None

        if tools:
            response_obj = st.session_state.client.messages.create(
                model=MODEL,
                max_tokens=2048,
                system=st.session_state.system_prompt,
                messages=clean,
                tools=tools,
            )
            text_parts = []
            workout_data = None
            for block in response_obj.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use" and block.name == "create_workout_file":
                    workout_data = block.input

            response = "\n".join(text_parts)
            st.markdown(response)

            if workout_data:
                col_dl2, col_icu2 = st.columns(2)
                with col_dl2:
                    from data.tcx_export import generate_tcx
                    tcx_data = generate_tcx(workout_data)
                    st.download_button(
                        label="Ladda ner .tcx",
                        data=tcx_data,
                        file_name=f"{workout_data['name'].replace(' ', '_')}.tcx",
                        mime="application/vnd.garmin.tcx+xml",
                    )
                with col_icu2:
                    icu_cfg = None
                    try:
                        icu_cfg = db.get_intervals_settings(user.id, access_token)
                    except Exception:
                        pass
                    if icu_cfg:
                        if st.button("Pusha till Intervals.icu", key="icu_new"):
                            from data.intervals_icu import push_workout
                            result = push_workout(icu_cfg["api_key"], icu_cfg["athlete_id"], workout_data)
                            if result.get("success"):
                                st.success("Pushat till Intervals.icu!")
                            else:
                                st.error(f"Fel: {result.get('error', 'Okant fel')}")
                    else:
                        st.caption("Koppla Intervals.icu under Profil")
        else:
            with st.session_state.client.messages.stream(
                model=MODEL,
                max_tokens=2048,
                system=st.session_state.system_prompt,
                messages=clean,
            ) as stream:
                response = st.write_stream(stream.text_stream)
            workout_data = None

    msg_out = {"role": "assistant", "content": response, "_ts": datetime.now().isoformat()}
    if workout_data:
        msg_out["workout"] = workout_data
    history.append(msg_out)
    st.session_state.conv_id = db.save_conversation(
        user.id, access_token, history, st.session_state.get("conv_id")
    )


# ══════════════════════════════════════════════════════════════════════
# TAB: PROFIL
# ══════════════════════════════════════════════════════════════════════

if active_tab == "profil":

    # --- Race info ---
    if profile.next_race_name:
        st.markdown(f"**Nasta tavling:** {profile.next_race_name} ({profile.next_race_date})")

    # --- Training zones ---
    if profile.cycle or profile.run or profile.swim:
        with st.expander("Traningszoner", expanded=True):
            if profile.cycle:
                st.text(profile.cycle.summary())
            if profile.run:
                st.text(profile.run.summary())
            if profile.swim:
                st.text(profile.swim.summary())

    # --- Intervals.icu ---
    with st.expander("Intervals.icu"):
        icu_settings = None
        try:
            icu_settings = db.get_intervals_settings(user.id, access_token)
        except Exception:
            pass
        icu_key = st.text_input(
            "API-nyckel",
            value=icu_settings["api_key"] if icu_settings else "",
            type="password",
            key="icu_api_key",
        )
        icu_athlete = st.text_input(
            "Athlete ID",
            value=icu_settings["athlete_id"] if icu_settings else "",
            key="icu_athlete_id",
            help="Finns i URL:en pa intervals.icu (t.ex. i12345)",
        )
        if st.button("Spara Intervals.icu", use_container_width=True):
            if icu_key and icu_athlete:
                try:
                    db.save_intervals_settings(user.id, access_token, icu_key, icu_athlete)
                    st.success("Sparat!")
                except Exception as e:
                    st.error(f"Kunde inte spara: {e}")
            else:
                st.warning("Fyll i bade API-nyckel och Athlete ID.")

    # --- Membership ---
    with st.expander("Medlemskap"):
        if tier == "premium":
            if trial_days is not None and trial_days > 0:
                st.success(f"Provperiod: {trial_days} dagar kvar")
            else:
                st.success("Premium")
            if STRIPE_PORTAL_LINK:
                st.link_button("Hantera prenumeration", STRIPE_PORTAL_LINK, use_container_width=True)
        else:
            st.warning("Gratisplan (5 meddelanden/dag)")
            if STRIPE_MONTHLY_LINK:
                st.link_button("Uppgradera till Premium", STRIPE_MONTHLY_LINK, use_container_width=True)
            with st.form("redeem_code", clear_on_submit=True):
                code_input = st.text_input("Rabattkod")
                if st.form_submit_button("Anvand"):
                    if code_input:
                        ok, msg = db.apply_discount_code(user.id, code_input)
                        if ok:
                            st.success(msg)
                            del st.session_state["subscription"]
                            st.rerun()
                        else:
                            st.error(msg)

    # --- Admin panel ---
    if is_admin:
        st.markdown("---")
        st.markdown("### Admin")

        if is_admin:
            try:
                from data.ingest import recent_summary, weekly_volume, DB_PATH
                db_path = DB_PATH if DB_PATH.exists() else None
            except Exception:
                db_path = None

            if db_path:
                with st.expander("Traningslogg (21 dagar)"):
                    st.text(recent_summary(db_path, days=21))
                with st.expander("Veckovolym"):
                    st.text(weekly_volume(db_path, weeks=8))

        articles = list_articles()
        with st.expander(f"Kunskapsbas ({len(articles)} artiklar)"):
            if articles:
                for a in articles:
                    col_title, col_del = st.columns([4, 1])
                    with col_title:
                        st.write(f"**{a['title']}**")
                    with col_del:
                        if st.button("X", key=f"del_{a['id']}"):
                            remove_article(a["id"])
                            st.session_state.system_prompt = build_system_prompt_admin(profile)
                            st.rerun()
            else:
                st.write("Inga artiklar.")
            st.markdown("---")
            st.markdown("**Lagg till artikel**")
            with st.form("add_article_form", clear_on_submit=True):
                a_title = st.text_input("Titel")
                a_source = st.text_input("Kalla/URL")
                a_tags = st.text_input("Tags")
                a_content = st.text_area("Innehall", height=150)
                if st.form_submit_button("Spara"):
                    if a_title and a_content:
                        add_article(a_title, a_content, source=a_source, tags=a_tags)
                        st.session_state.system_prompt = build_system_prompt_admin(profile)
                        st.success(f"Lade till: {a_title}")
                        st.rerun()

        if st.button("Synka Strava", use_container_width=True):
            with st.spinner("Synkar..."):
                try:
                    from data.strava_sync import sync
                    sync(days=30)
                    st.session_state.system_prompt = build_system_prompt_admin(profile)
                    st.success("Strava-sync klar!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Sync misslyckades: {e}")

        with st.expander("Anvandare"):
            try:
                users = db.list_all_users()
            except Exception as e:
                st.error(f"Kunde inte ladda anvandare: {e}")
                users = []
            for u in users:
                tier_label = u["tier"]
                if u["status"] == "trialing":
                    days_left = ""
                    if u.get("trial_ends_at"):
                        try:
                            from datetime import datetime as dt, timezone as tz
                            ends = dt.fromisoformat(u["trial_ends_at"].replace("Z", "+00:00"))
                            days_left = f" ({max(0, (ends - dt.now(tz.utc)).days)}d kvar)"
                        except Exception:
                            pass
                    tier_label = f"trial{days_left}"
                col_name, col_tier, col_action = st.columns([3, 2, 2])
                with col_name:
                    st.write(f"**{u['name'] or u['email']}**")
                    st.caption(u['email'])
                with col_tier:
                    st.write(tier_label)
                with col_action:
                    new_tier = st.selectbox(
                        "Tier",
                        ["free", "premium"],
                        index=0 if u["tier"] == "free" else 1,
                        key=f"tier_{u['id']}",
                        label_visibility="collapsed",
                    )
                    if st.button("Spara", key=f"save_{u['id']}"):
                        db.set_user_tier(u["id"], new_tier)
                        st.success(f"Uppdaterat {u['name'] or u['email']} -> {new_tier}")
                        st.rerun()
                st.markdown("---")

        with st.expander("Rabattkoder"):
            try:
                codes = db.list_discount_codes()
            except Exception:
                codes = []
            if codes:
                for c in codes:
                    st.write(f"**{c['code']}** -- {c['discount_percent']}% | "
                             f"Anvant {c['times_used']}/{c['max_uses']} | "
                             f"{'Aktiv' if c.get('active') else 'Inaktiv'}")
            else:
                st.write("Inga rabattkoder.")
            st.markdown("---")
            st.markdown("**Skapa ny rabattkod**")
            with st.form("create_discount", clear_on_submit=True):
                dc_code = st.text_input("Kod (t.ex. VANNER50)")
                dc_percent = st.number_input("Rabatt %", min_value=1, max_value=100, value=100)
                dc_max = st.number_input("Max anvandningar", min_value=1, value=1)
                dc_desc = st.text_input("Beskrivning")
                if st.form_submit_button("Skapa"):
                    if dc_code:
                        db.create_discount_code(dc_code, dc_percent, dc_max, dc_desc)
                        st.success(f"Skapade rabattkod: {dc_code.upper()}")
                        st.rerun()

    # --- Actions ---
    st.markdown("---")

    if st.button("Ny konversation", use_container_width=True):
        st.session_state.history = []
        st.session_state.conv_id = None
        if "system_prompt" in st.session_state:
            del st.session_state["system_prompt"]
        st.rerun()

    if st.button("Logga ut", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
