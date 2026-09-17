"""
tcg_cards.py - TCG Card System for Territory Wars

Features:
- Geographic trait cards boosting Climate, Terrain, or Economy (+1 to +4).
- Rarity weights: +1 (40%), +2 (30%), +3 (20%), +4 (10%).
- Hand management with hand limit 5.
"""

import random
import uuid

# Base geographic traits definitions
TRAIT_TEMPLATES = [
    # Climate Traits
    {"name": "Tropical Monsoon", "stat": "climate", "icon": "🌧️"},
    {"name": "Sahara Heatwave", "stat": "climate", "icon": "☀️"},
    {"name": "Polar Vortex", "stat": "climate", "icon": "❄️"},
    {"name": "Trade Winds", "stat": "climate", "icon": "💨"},
    {"name": "El Niño Current", "stat": "climate", "icon": "🌊"},
    {"name": "Temperate Front", "stat": "climate", "icon": "⛅"},
    {"name": "Geothermal Vent", "stat": "climate", "icon": "🌋"},
    {"name": "Arctic Aurora", "stat": "climate", "icon": "✨"},

    # Terrain Traits
    {"name": "Alpine Ridge", "stat": "terrain", "icon": "🏔️"},
    {"name": "Canyon Trench", "stat": "terrain", "icon": "🏜️"},
    {"name": "Dense Rainforest", "stat": "terrain", "icon": "🌴"},
    {"name": "Volcanic Rift", "stat": "terrain", "icon": "🌋"},
    {"name": "Highland Plateau", "stat": "terrain", "icon": "⛰️"},
    {"name": "Fjord Basin", "stat": "terrain", "icon": "🏞️"},
    {"name": "Delta Marshland", "stat": "terrain", "icon": "🌾"},
    {"name": "Granite Escarpment", "stat": "terrain", "icon": "🪨"},

    # Economy Traits
    {"name": "Trade Corridor", "stat": "economy", "icon": "🚢"},
    {"name": "Fintech District", "stat": "economy", "icon": "💳"},
    {"name": "Deepwater Harbor", "stat": "economy", "icon": "⚓"},
    {"name": "Industrial Hub", "stat": "economy", "icon": "🏭"},
    {"name": "Rare Mineral Deposit", "stat": "economy", "icon": "💎"},
    {"name": "Aviation Gateway", "stat": "economy", "icon": "🛫"},
    {"name": "Tech Research Cluster", "stat": "economy", "icon": "🔬"},
    {"name": "Global Financial Exchange", "stat": "economy", "icon": "📈"},
]

VALUE_WEIGHTS = [(1, 40), (2, 30), (3, 20), (4, 10)]

def generate_random_card() -> dict:
    """Generates a unique TCG card with a geographic trait and weighted stat value."""
    template = random.choice(TRAIT_TEMPLATES)
    # Weighted pick for value +1 to +4
    values, weights = zip(*VALUE_WEIGHTS)
    val = random.choices(values, weights=weights, k=1)[0]

    return {
        "id": str(uuid.uuid4())[:8],
        "name": template["name"],
        "stat": template["stat"],  # 'climate', 'terrain', or 'economy'
        "value": val,
        "icon": template["icon"],
        "title": f"{template['name']} — {template['stat'].capitalize()} +{val}"
    }

def format_card_line(card: dict) -> str:
    """Formats a single card for display in chat or ephemeral views."""
    return f"`[{card['id']}]` {card['icon']} **{card['name']}** — *{card['stat'].capitalize()} +{card['value']}*"
