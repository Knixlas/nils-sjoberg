"""
Nils Sjöberg – Streamlit Web App (Multi-user)
Personlig AI-tränare driven av Claude.

Kör med: streamlit run app.py
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import anthropic
import streamlit as st
from dotenv import load_dotenv

# Setup paths
ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env", override=True)
sys.path.insert(0, str(ROOT))

from data.athlete_profile import AthleteProfile
from data.phase_detector import detect_phase, phase_context
from data.workout_library import library_summary, library_stats
from data.knowledge_base import (
    list_articles, add_article, remove_article, knowledge_summary,
)
from data import db

SYSTEM_PROMPT_FILE = ROOT / "prompts" / "system_prompt.md"
MODEL = "claude-sonnet-4-5"
MAX_HISTORY = 20
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")

# ── Mobile-friendly CSS ─────────────────────────────────────────────

MOBILE_CSS = """
<style>
    /* Compact header on mobile */
    @media (max-width: 768px) {
        .block-container { padding: 1rem 0.5rem !important; }
        h1 { font-size: 1.5rem !important; }
        .stChatMessage { padding: 0.5rem !important; }
        section[data-testid="stSidebar"] { width: 280px !important; }
    }
    /* Clean chat styling */
    .stChatMessage [data-testid="stMarkdownContainer"] p {
        line-height: 1.6;
    }
    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
</style>
"""


# ── Helpers ──────────────────────────────────────────────────────────

def build_system_prompt(profile: AthleteProfile) -> str:
    template = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")
    # For non-admin users, no workout log data
    workouts = "Ingen träningsdata tillgänglig för denna användare ännu."
    vol_text = ""
    weeks = profile.weeks_to_race()
    fas_ctx = phase_context(weeks, None)
    return (
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
    workouts = recent_summary(DB_PATH, days=21)
    vol = weekly_volume(DB_PATH, weeks=8)
    if "Ingen träningsdata" not in vol:
        workouts += "\n\n" + vol
    weeks = profile.weeks_to_race()
    fas_ctx = phase_context(weeks, DB_PATH)
    return (
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


# ── Page config ──────────────────────────────────────────────────────

st.set_page_config(
    page_title="Nils Sjöberg",
    page_icon="🏊",
    layout="centered",
    initial_sidebar_state="auto",
)
st.markdown(MOBILE_CSS, unsafe_allow_html=True)


# ── Auth Flow ────────────────────────────────────────────────────────

def show_auth_page():
    """Login/signup page."""
    st.markdown("## 🏊‍♂️ Nils Sjöberg")
    st.caption("Din personliga AI-tränare")
    st.markdown("---")

    tab_login, tab_signup = st.tabs(["Logga in", "Skapa konto"])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("E-post")
            password = st.text_input("Lösenord", type="password")
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
                        st.error("Fel e-post eller lösenord.")
                    else:
                        st.error(f"Inloggning misslyckades: {err}")

    with tab_signup:
        with st.form("signup_form"):
            name = st.text_input("Ditt namn")
            email_s = st.text_input("E-post", key="signup_email")
            pw_s = st.text_input("Lösenord (minst 6 tecken)", type="password", key="signup_pw")
            submitted_s = st.form_submit_button("Skapa konto", use_container_width=True)
            if submitted_s and email_s and pw_s and name:
                if len(pw_s) < 6:
                    st.error("Lösenordet måste vara minst 6 tecken.")
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
        # Write temp file for AthleteProfile to read
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


# ── Sidebar ──────────────────────────────────────────────────────────

with st.sidebar:
    weeks = profile.weeks_to_race()

    st.markdown("## 🏊‍♂️ Nils Sjöberg")
    st.caption("Personlig Tränare")
    st.markdown(f"Inloggad som **{profile.name or user.email}**")

    st.divider()

    if profile.next_race_name and weeks is not None:
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Veckor kvar", f"{weeks}v")
        with col2:
            fas, _ = detect_phase(weeks, None)
            st.metric("Fas", fas[:12])
        st.info(f"**{profile.next_race_name}**\n\n{profile.next_race_date}")
        st.divider()

    # Training zones (only if they exist)
    if profile.cycle or profile.run or profile.swim:
        with st.expander("Träningszoner"):
            if profile.cycle:
                st.text(profile.cycle.summary())
            if profile.run:
                st.text(profile.run.summary())
            if profile.swim:
                st.text(profile.swim.summary())

    # Admin-only: training log, strava sync, knowledge base
    if is_admin:
        from data.ingest import recent_summary, weekly_volume, DB_PATH
        fas, _ = detect_phase(weeks, DB_PATH)

        with st.expander("Träningslogg (21 dagar)"):
            st.text(recent_summary(DB_PATH, days=21))

        with st.expander("Veckovolym"):
            st.text(weekly_volume(DB_PATH, weeks=8))

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
            st.markdown("**Lägg till artikel**")
            with st.form("add_article_form", clear_on_submit=True):
                a_title = st.text_input("Titel")
                a_source = st.text_input("Källa/URL")
                a_tags = st.text_input("Tags")
                a_content = st.text_area("Innehåll", height=150)
                if st.form_submit_button("Spara"):
                    if a_title and a_content:
                        add_article(a_title, a_content, source=a_source, tags=a_tags)
                        st.session_state.system_prompt = build_system_prompt_admin(profile)
                        st.success(f"Lade till: {a_title}")
                        st.rerun()

        st.divider()

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

    st.divider()

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


# ── Main chat area ───────────────────────────────────────────────────

st.title("Nils Sjöberg")
if profile.goal:
    st.caption(profile.goal)

# Display chat history
for msg in history:
    role = msg["role"]
    if msg.get("_auto"):
        continue
    with st.chat_message("assistant" if role == "assistant" else "user",
                         avatar="🏋️" if role == "assistant" else None):
        st.markdown(msg["content"])

# Auto-intro on first session
if not history:
    with st.chat_message("assistant", avatar="🏋️"):
        with st.spinner("Nils tänker..."):
            exp = getattr(profile, "experience_level", "unknown")
            if exp in ("beginner", "unknown"):
                intro_msg = "Hej Nils! Ny session. Presentera dig kort och fråga vad jag vill jobba med idag."
            elif exp == "intermediate":
                intro_msg = "Hej Nils! Ny session. Ge mig en kort statusuppdatering och fråga vad jag vill fokusera på."
            else:
                intro_msg = "Hej Nils! Ny session. Ge mig en kort statusuppdatering baserat på min träningslogg och hur det ser ut inför nästa tävling."
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

# Chat input
if prompt := st.chat_input("Skriv till Nils..."):
    with st.chat_message("user"):
        st.markdown(prompt)
    history.append({"role": "user", "content": prompt})

    with st.chat_message("assistant", avatar="🏋️"):
        clean = [{"role": m["role"], "content": m["content"]}
                 for m in history[-MAX_HISTORY:] if not m.get("_auto")]
        with st.session_state.client.messages.stream(
            model=MODEL,
            max_tokens=2048,
            system=st.session_state.system_prompt,
            messages=clean,
        ) as stream:
            response = st.write_stream(stream.text_stream)

    history.append({"role": "assistant", "content": response})
    st.session_state.conv_id = db.save_conversation(
        user.id, access_token, history, st.session_state.get("conv_id")
    )
