"""Shared settings. Everything overridable from .env."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # dotenv is optional
    pass

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
STATE_FILE = ROOT / "state.json"
CREDENTIALS_FILE = ROOT / "credentials.json"  # Google OAuth desktop client
TOKEN_FILE = ROOT / "token.json"

SHEET_ID = os.getenv("BUNNY_SHEET_ID", "1sYmDaDuCBFXY5KAzoY9texjWBwuIOcRXrwtWBpCQufE")
SHEET_TAB = os.getenv("BUNNY_SHEET_TAB", "Untitled")
DRIVE_FOLDER = os.getenv("BUNNY_DRIVE_FOLDER", "Bunny Intake")

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
JUDGE_MODEL = os.getenv("BUNNY_JUDGE_MODEL", "claude-opus-5-5")

# Roster columns (header row 1). Looked up by header text so column moves don't break us.
COL_NAME = "Name"
COL_PILLAR = "Pillar"
COL_STANCE = "Mirror side / stance"
COL_TYPE = "Type"
COL_FEEDS = "Feed links (YouTube / podcast / Substack)"
COL_WHY = "Why they're here"
COL_STATUS = "Status"
COL_SOURCE = "Source of discovery"

UA = "Mozilla/5.0 (bunny-intake research script)"
