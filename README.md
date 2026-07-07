# Conflux Alert Bot

An asynchronous, Python-based Telegram bot for real-time cryptocurrency price alerts. Conflux connects directly to exchange websockets to monitor prices and sends you an instant Telegram notification when your target price band is hit.

## Features

- **Live Websocket Streams**: Monitors tick-by-tick data directly from exchange websockets (no REST API polling limits).
- **Supported Exchanges**: Binance (Spot), Bitget (Spot), and OKX (Spot).
- **Band-Based Triggers**: Alerts trigger when the price enters your target band, or if it gaps entirely through your band between two ticks.
- **One-Shot Alerts**: Once an alert triggers, it is marked as triggered and will not spam you again.
- **Dynamic Subscriptions**: You can create alerts on the fly via Telegram, and the bot instantly subscribes to the new coin's websocket stream without needing a restart.
- **Interactive UI**: View your active alerts via Telegram and delete them instantly with a single button tap.

## Prerequisites

- Python 3.9 or higher
- A Telegram Bot Token (get one from [@BotFather](https://t.me/botfather) on Telegram)

## Installation

1. **Clone the repository** (if you haven't already):
   ```bash
   git clone <your-repo-url>
   cd conflux
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Secrets**:
   Copy the example environment file and add your credentials:
   ```bash
   cp .env.example .env
   ```
   Open `.env` and fill in:
   - `TELEGRAM_BOT_TOKEN`: Your bot's API token.
   - `TELEGRAM_CHAT_ID`: Your personal Telegram User ID (find this via [@userinfobot](https://t.me/userinfobot)).

## Usage

Start the bot:
```bash
python3 -m alert_bot.main
```
*Note: To keep the bot running 24/7, deploy this on a cloud server (VPS) like DigitalOcean, AWS, or Heroku, and run it using a background process manager like `systemd` or `tmux`.*

### Telegram Commands

Once the bot is running, send these commands to it in Telegram:

- `/newalert <symbol> <exchange> <target_price> <range_pct> [note...]`
  *Example:* `/newalert BTCUSDT binance 65000 2 resistance retest`
  Creates a new alert. (Note: For OKX, use hyphenated symbols like `BTC-USDT`).

- `/listalerts`
  Shows all your alerts (active and triggered). It also generates interactive inline buttons so you can delete alerts with one tap.

- `/deletealert <id>`
  Manually delete an alert by its ID (useful if you prefer typing over using the inline buttons).

## Architecture

- **Core Loop**: `asyncio` runs the websocket connections concurrently alongside the Telegram bot poller.
- **Database**: SQLite3 in WAL mode handles concurrent reads/writes for alerts and price logs.
- **Trigger Logic**: Evaluates every incoming tick for inside-band matches and gap-through crossings.

## Security Warning
**Never commit your `.env` file.** The repository includes a `.gitignore` designed to prevent accidentally uploading your Telegram bot tokens.
