"""
Strava OAuth-hantering.
Läser credentials från .env, refreshar access token automatiskt.
Sparar tokens till .strava_tokens.json för återanvändning.
"""

import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

TOKENS_FILE   = Path(__file__).parent.parent / ".strava_tokens.json"
TOKEN_URL     = "https://www.strava.com/oauth/token"
CLIENT_ID     = os.getenv("STRAVA_CLIENT_ID")
CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")


def _save_tokens(tokens: dict):
    TOKENS_FILE.write_text(json.dumps(tokens, indent=2), encoding="utf-8")


def _load_tokens() -> dict | None:
    if TOKENS_FILE.exists():
        try:
            return json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            return None
    return None


def refresh_access_token(refresh_token: str) -> dict:
    """Byter refresh token mot ett nytt access token."""
    resp = requests.post(TOKEN_URL, data={
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type":    "refresh_token",
        "refresh_token": refresh_token,
    })
    resp.raise_for_status()
    tokens = resp.json()
    _save_tokens(tokens)
    return tokens


def get_access_token() -> str:
    """
    Returnerar ett giltigt access token.
    Refreshar automatiskt om det gått ut.
    """
    tokens = _load_tokens()

    # Första gången – använd refresh token från .env
    if not tokens:
        refresh_token = os.getenv("STRAVA_REFRESH_TOKEN")
        if not refresh_token:
            raise EnvironmentError("STRAVA_REFRESH_TOKEN saknas i .env")
        tokens = refresh_access_token(refresh_token)

    # Kolla om access token är nära att gå ut (60s marginal)
    expires_at = tokens.get("expires_at", 0)
    if time.time() > expires_at - 60:
        tokens = refresh_access_token(tokens["refresh_token"])

    return tokens["access_token"]


if __name__ == "__main__":
    print("Hämtar access token...")
    token = get_access_token()
    tokens = _load_tokens()
    expires = tokens.get("expires_at", 0)
    print(f"OK! Token giltig, gar ut: {time.strftime('%Y-%m-%d %H:%M', time.localtime(expires))}")
