"""Configuration — loads secrets from environment, defines constants."""

from __future__ import annotations

import os
import logging

from dotenv import load_dotenv

load_dotenv()

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("conflux")

# ── Secrets (loaded from .env — never logged, never hardcoded) ───────
TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    logger.warning(
        "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in environment. "
        "Bot will not be able to send notifications."
    )

# ── Constants ────────────────────────────────────────────────────────
DB_PATH: str = os.environ.get("DB_PATH", "alerts.db")
VALID_EXCHANGES: set[str] = {"binance", "bitget", "okx"}
