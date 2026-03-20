"""
Nils Sjöberg – Streamlit Web App (Multi-user)
Personlig AI-tränare driven av Claude.

Kör med: streamlit run app.py
"""

import base64
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

import io

import streamlit as st

# ── Debug mode: catch ALL import/startup errors ──────────────────
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
    _IMPORT_ERROR = None
except Exception as e:
    _IMPORT_ERROR = traceback.format_exc()
    ROOT = Path(__file__).parent

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
    "description": "Skapa en nedladdningsbar träningspassfil (.tcx) som kan importeras i Garmin Connect eller TrainingPeaks. Använd detta när du föreslår ett strukturerat träningspass.",
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
                        "duration_seconds": {"type": "integer", "description": "Längd i sekunder"},
                        "repeats": {"type": "integer", "description": "Antal repetitioner (bara för intervaller)"},
                        "description": {"type": "string"},
                        "hr_low": {"type": "integer", "description": "Pulsmål lågt (bpm)"},
                        "hr_high": {"type": "integer", "description": "Pulsmål högt (bpm)"},
                        "power_low": {"type": "integer", "description": "Effektmål lågt (watt)"},
                        "power_high": {"type": "integer", "description": "Effektmål högt (watt)"},
                    },
                    "required": ["type", "duration_seconds"],
                },
                "description": "Steg i passet",
            },
        },
        "required": ["name", "sport", "steps"],
    },
}

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


# ── Page config ──────────────────────────────────────────────────────

st.set_page_config(
    page_title="Nils Sjöberg",
    page_icon="🏊",
    layout="centered",
    initial_sidebar_state="auto",
)

# Show import errors if any
if _IMPORT_ERROR:
    st.error("App kunde inte starta. Feldetaljer:")
    st.code(_IMPORT_ERROR)
    st.stop()

st.markdown(MOBILE_CSS, unsafe_allow_html=True)


# ── Auth Flow ────────────────────────────────────────────────────────

def show_auth_page():
    """Login/signup page."""
    st.markdown("## Nils Sjoberg")
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


# ── Sidebar ──────────────────────────────────────────────────────────

with st.sidebar:
    weeks = profile.weeks_to_race()

    st.markdown("## Nils Sjoberg")
    st.caption("Personlig Tranare")
    st.markdown(f"Inloggad som **{profile.name or user.email}**")

    # Membership status
    trial_days = trial_days_remaining(subscription)
    if tier == "premium" and not is_admin:
        if trial_days is not None and trial_days > 0:
            st.success(f"Provperiod: {trial_days} dagar kvar")
        else:
            st.success("Premium")
    elif not is_admin:
        try:
            daily_count = db.get_daily_message_count(user.id, access_token)
        except Exception:
            daily_count = 0
        remaining = messages_remaining(tier, daily_count)
        st.warning(f"Gratis -- {remaining} meddelanden kvar idag")
        if STRIPE_MONTHLY_LINK:
            st.link_button("Uppgradera till Premium", STRIPE_MONTHLY_LINK, use_container_width=True)
        with st.expander("Har du en rabattkod?"):
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
        with st.expander("Traningszoner"):
            if profile.cycle:
                st.text(profile.cycle.summary())
            if profile.run:
                st.text(profile.run.summary())
            if profile.swim:
                st.text(profile.swim.summary())

    # Admin-only: training log, strava sync, knowledge base
    if is_admin:
        from data.ingest import recent_summary, weekly_volume, DB_PATH
        db_path = DB_PATH if DB_PATH.exists() else None
        fas, _ = detect_phase(weeks, db_path)

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

    # Stripe portal link for premium users
    if tier == "premium" and not is_admin and STRIPE_PORTAL_LINK:
        if st.button("Hantera prenumeration", use_container_width=True):
            st.markdown(f"[Oppna Stripe-portalen]({STRIPE_PORTAL_LINK})")

    # ── Admin Panel ───────────────────────────────────────────────
    if is_admin:
        st.divider()
        st.markdown("### Admin")

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
                    st.write(f"**{c['code']}** — {c['discount_percent']}% | "
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

st.title("Nils Sjoberg")
if profile.goal:
    st.caption(profile.goal)

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
        # Show attachments if any
        if msg.get("attachments"):
            for att in msg["attachments"]:
                if att["type"].startswith("image/"):
                    st.image(att["url"], caption=att["name"], width=300)
                else:
                    st.markdown(f"Bifogad: **{att['name']}**")
        st.markdown(msg["content"])

        # Show download button for workout exports
        if msg.get("workout"):
            from data.tcx_export import generate_tcx
            wo = msg["workout"]
            tcx_data = generate_tcx(wo)
            st.download_button(
                label=f"Ladda ner {wo['name']}.tcx",
                data=tcx_data,
                file_name=f"{wo['name'].replace(' ', '_')}.tcx",
                mime="application/vnd.garmin.tcx+xml",
                key=f"dl_{msg.get('_ts', '')}_{wo['name']}",
            )

# Auto-intro on first session
if not history:
    with st.chat_message("assistant", avatar=None):
        with st.spinner("Nils tanker..."):
            exp = getattr(profile, "experience_level", "unknown")
            if exp in ("beginner", "unknown"):
                intro_msg = "Hej Nils! Ny session. Presentera dig kort och fraga vad jag vill jobba med idag."
            elif exp == "intermediate":
                intro_msg = "Hej Nils! Ny session. Ge mig en kort statusuppdatering och fraga vad jag vill fokusera pa."
            else:
                intro_msg = "Hej Nils! Ny session. Ge mig en kort statusuppdatering baserat pa min traningslogg och hur det ser ut infor nasta tavling."
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
        # Upload to Supabase Storage (best effort)
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
        # Build message content (with optional attachment for Claude)
        content = build_message_content(prompt, attachment)
        clean = []
        for m in history[-MAX_HISTORY:]:
            if m.get("_auto"):
                continue
            clean.append({"role": m["role"], "content": m["content"]})
        # Replace last message content with multimodal content if attachment
        if attachment and clean:
            clean[-1]["content"] = content

        # Use tool for workout export if premium
        tools = [WORKOUT_TOOL] if can_use_feature(tier, "workout_export") else None

        # Non-streaming call when tools are enabled (tool_use not supported with streaming)
        if tools:
            response_obj = st.session_state.client.messages.create(
                model=MODEL,
                max_tokens=2048,
                system=st.session_state.system_prompt,
                messages=clean,
                tools=tools,
            )
            # Process response
            text_parts = []
            workout_data = None
            for block in response_obj.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use" and block.name == "create_workout_file":
                    workout_data = block.input

            response = "\n".join(text_parts)
            st.markdown(response)

            # Show download button if workout was generated
            if workout_data:
                from data.tcx_export import generate_tcx
                tcx_data = generate_tcx(workout_data)
                st.download_button(
                    label=f"Ladda ner {workout_data['name']}.tcx",
                    data=tcx_data,
                    file_name=f"{workout_data['name'].replace(' ', '_')}.tcx",
                    mime="application/vnd.garmin.tcx+xml",
                )
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
