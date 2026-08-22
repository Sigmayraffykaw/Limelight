# 🍋 Limelight

A Discord server minigame bot with its own virtual currency.

## Games

- `/rps` — Rock Paper Scissors, optional virtual-coin bet
- `/coinflip` — Heads or tails with a virtual-coin bet
- `/dice` — Roll against Limelight, optional bet
- `/guess` — Guess a number from 1–10, optional bet
- `/trivia` — 15-second trivia round
- `/blacktea` — Type a word containing the shown letters before time runs out

## Economy

- `/balance`
- `/daily`
- `/pay`
- `/leaderboard`
- `/stats`

New users begin with 500 🍋. Daily rewards give 250 🍋. Game balances and stats are stored in SQLite and persist between restarts as long as `limelight.db` is kept.

## Setup

1. Install Python 3.11 or newer.
2. Run `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env`.
4. Put your Discord bot token in `.env` as `DISCORD_TOKEN=YOUR_TOKEN`.
5. In the Discord Developer Portal, enable **Message Content Intent** for the bot. This is needed for Black Tea and Trivia.
6. Invite the bot with the `bot` and `applications.commands` scopes.
7. Run `python bot.py`.

The bot syncs its slash commands automatically when it starts.

## Important

The betting system uses Limelight's fictional in-server currency only. It does not support real money, Robux, crypto, gift cards, or cash-value prizes.
