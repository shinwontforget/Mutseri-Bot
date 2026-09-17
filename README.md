# ⚔️ Territory Wars — Discord Strategy Board Bot

A strategic Discord board game built from the ground up using `discord.py` and asynchronous PIL board rendering.

No rent. No houses. No jail. No community chest. Only geographic stats, tactical TCG cards, and lethal territory conquest duels!

---

## 📑 Table of Contents
- [🎯 Game Overview](#-game-overview)
- [🗺️ The 20-Tile Loop](#️-the-20-tile-loop)
- [⚠️ Signature Mechanic: Proximity Gamble](#️-signature-mechanic-proximity-gamble)
- [⚔️ The 7 Duels](#️-the-7-duels)
- [🃏 TCG Boost Cards](#-tcg-boost-cards)
- [💰 Economy & Strike Pardons](#-economy--strike-pardons)
- [🎮 Game Commands](#-game-commands)
- [⚙️ Server Configuration](#️-server-configuration)
- [🚀 Quick Start & Installation](#-quick-start--installation)

---

## 🎯 Game Overview

- **Elimination by Strikes**: Landing on Dead Zones or losing a Proximity Gamble inflicts strikes. Accumulating **3 strikes** eliminates a commander from the game and returns all their conquered territories to the unowned pool.
- **Zero Rent**: When landing on a rival's territory, you never pay rent. Instead, a fast-paced **Duel** is triggered. The winner takes or retains ownership of the territory!
- **Lap Dividends**: Passing START awards **+$200 cash**, **1 random TCG card**, and a **+$100 dividend per territory owned**.
- **Victory Condition**: Last commander standing wins! If the round limit (40 rounds) is reached, the commander with the fewest strikes wins (ties broken by territories owned, then cash).

---

## 🗺️ The 20-Tile Loop

The board is a symmetrical 6x6 perimeter track featuring 20 tiles:

- **Tile 0 (GLOBAL START)**: Passing or landing awards $200 + 1 TCG Card + $100 per owned territory.
- **Tiles 5 & 15 (DEAD ZONES)**: Positioned opposite each other on the loop. Landing inflicts **+1 STRIKE**.
- **Tiles 4 & 14 (Pre-Dead Zones)**: Ending your turn here triggers the **Proximity Gamble** challenge window.
- **Tiles 7, 10, 12 (NEUTRAL SANCTUARIES)**: Safe havens. Landing draws 1 TCG card.
- **14 Properties**: Real-world territories (Tokyo, Zurich, Reykjavik, Cairo, Nairobi, etc.) with three thematic stats rated 1–10:
  - 🌧️ **Climate**
  - 🏔️ **Terrain**
  - 💼 **Economy**

---

## ⚠️ Signature Mechanic: Proximity Gamble

When any commander ends their move exactly 1 tile before a Dead Zone (Tiles 4 or 14):
1. A **20-second public challenge window** opens in the channel.
2. Any active rival can click **"Challenge Proximity Gamble"** (first to click claims it).
3. A random duel is played between challenger and defender:
   - **Challenger wins** ➔ Exposed defender receives **+1 STRIKE**.
   - **Defender wins** ➔ Challenger receives **+1 STRIKE**.
   - **Both timeout** ➔ Nothing happens.
4. *Anti-Farming*: A player cannot initiate a gamble two turns in a row.

---

## ⚔️ The 7 Duels

All duels resolve in under 30 seconds in public channel messages:
1. **Reaction Duel**: Button turns green after 2–5s. First click wins; clicking early disqualifies.
2. **Memory Flash**: Emoji sequence flashes for 3s then deletes. Both retype it via modal; most accurate wins.
3. **Quick Math**: Speed arithmetic problem. First correct button click wins; wrong click disqualifies.
4. **Odd One Out**: 4 items; first to identify the category outlier wins.
5. **Geo Sprint**: Flash geographic trivia question about the contested territory's country.
6. **Stat Duel (TCG)**: Random stat chosen. Both secretly play a face-down card to boost that stat. Higher total wins.
7. **Element Clash (TCG)**: Rock-Paper-Scissors cycle:
   - *Climate beats Terrain | Terrain beats Economy | Economy beats Climate*
   - Ties broken by highest matching card value.

*Universal Tie & Timeout Rule*: Exact ties and double timeouts are retained by Defender. Single timeouts award victory to the other commander.

---

## 🃏 TCG Boost Cards

- Awarded when passing START and landing on Neutral tiles.
- Boosts one of the 3 stats by **+1 to +4** (higher values are rarer: 40% +1, 30% +2, 20% +3, 10% +4).
- **Hand limit: 5 cards**. Drawing a 6th card prompts an immediate discard selection.
- Cards are consumed when played in duels.

---

## 💰 Economy & Strike Pardons

- **Fixed Purchase vs Auction**: When landing on an unowned territory, the lander can buy it for a fixed price or send it to a 15-second live auction for all players.
- **Strike Pardons**: On your turn, pay money to erase 1 strike. Price doubles each time you use it:
  - 1st Pardon: **$500**
  - 2nd Pardon: **$1,000**
  - 3rd Pardon: **$2,000**
  - 4th Pardon: **$4,000**...

---

## 🎮 Game Commands

| Command | Description |
| :--- | :--- |
| `!start @p1 @p2 [@p3 @p4]` | Starts a 2–4 player game. Runs pre-game Closest Guess (1-100) modal to decide turn order (alias: `!start_tw`). |
| `!hand` | Sends a private message showing your held TCG cards. |
| `!territory` | Sends a private message listing your owned territories, stats, and lap dividend income. |
| `!status` | Displays the public scorecard of all players: cash, properties, cards, and strike markers. |
| `!board` | Reposts the current high-resolution board rendering. |
| `!end_tw` | Ends the current match in the channel. |

---

## ⚙️ Server Configuration

| Command | Permission | Description |
| :--- | :--- | :--- |
| `!setprefix <new_prefix>` | Manage Server | Sets a custom command prefix for your Discord server. |
| `!setchannel #c1 #c2 ...` | Manage Server | Allocates specific channels for Territory Wars. Blocks all other channels. |
| `!setchannel reset` | Manage Server | Unblocks all channels across the server. |
| `!help` | Everyone | Displays the comprehensive 3-message field guide and command manual. |

---

## 🚀 Quick Start & Installation

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
Create a `.env` file in the root directory:
```env
DISCORD_BOT_TOKEN=your_bot_token_here
PORT=8080
```

### 3. Run the Bot
```bash
python bot.py
```

### 4. Run Test Suite
```bash
python test_suite.py
```
