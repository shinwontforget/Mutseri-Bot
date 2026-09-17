"""
territories.py - Board and Property Definitions for Territory Wars (20 Tiles)

Board Layout (20 tiles, indices 0 to 19):
  - Tile 0: START (Corner 1, Top-Left)
  - Tiles 1-4: Top Row (3 Properties + 1 Pre-DZ Property)
  - Tile 5: DEAD ZONE 1 (Corner 2, Top-Right)
  - Tiles 6-9: Right Column (3 Properties + 1 Neutral)
  - Tile 10: NEUTRAL 1 (Corner 3, Bottom-Right)
  - Tiles 11-14: Bottom Row (3 Properties + 1 Pre-DZ Property)
  - Tile 15: DEAD ZONE 2 (Corner 4, Bottom-Left - opposite Tile 5!)
  - Tiles 16-19: Left Column (4 Properties)
"""

BOARD_TILES = [
    # Tile 0: START Corner
    {
        "index": 0,
        "type": "start",
        "name": "GLOBAL START",
        "short_name": "START",
        "description": "Pass to receive $200, 1 TCG Card, and $100 per owned territory.",
    },

    # Tile 1: Property
    {
        "index": 1,
        "type": "property",
        "name": "Tokyo",
        "country": "Japan",
        "flag": "🇯🇵",
        "color": "#00C4FF",  # Cyan
        "price": 320,
        "stats": {"climate": 7, "terrain": 6, "economy": 10},
        "trivia": {
            "hemisphere": "Northern",
            "coastal": True,
            "continent": "Asia",
            "larger_than": ["United Kingdom", "Germany", "Italy", "New Zealand"],
            "smaller_than": ["France", "Spain", "United States", "China", "Brazil"]
        }
    },

    # Tile 2: Property
    {
        "index": 2,
        "type": "property",
        "name": "Reykjavik",
        "country": "Iceland",
        "flag": "🇮🇸",
        "color": "#00C4FF",  # Cyan
        "price": 240,
        "stats": {"climate": 2, "terrain": 8, "economy": 7},
        "trivia": {
            "hemisphere": "Northern",
            "coastal": True,
            "continent": "Europe",
            "larger_than": ["Portugal", "Austria", "Switzerland", "Ireland"],
            "smaller_than": ["Norway", "United Kingdom", "Germany", "Japan"]
        }
    },

    # Tile 3: Property
    {
        "index": 3,
        "type": "property",
        "name": "Cairo",
        "country": "Egypt",
        "flag": "🇪🇬",
        "color": "#22C55E",  # Green
        "price": 230,
        "stats": {"climate": 9, "terrain": 4, "economy": 6},
        "trivia": {
            "hemisphere": "Northern",
            "coastal": True,
            "continent": "Africa",
            "larger_than": ["France", "Germany", "Japan", "United Kingdom"],
            "smaller_than": ["China", "Brazil", "Canada", "Australia"]
        }
    },

    # Tile 4: Property (1 tile before DEAD ZONE 1 -> Proximity Gamble triggers!)
    {
        "index": 4,
        "type": "property",
        "name": "Zurich",
        "country": "Switzerland",
        "flag": "🇨🇭",
        "color": "#22C55E",  # Green
        "price": 350,
        "stats": {"climate": 5, "terrain": 9, "economy": 10},
        "trivia": {
            "hemisphere": "Northern",
            "coastal": False,  # Landlocked
            "continent": "Europe",
            "larger_than": ["Belgium", "Netherlands", "Slovenia"],
            "smaller_than": ["France", "Germany", "Spain", "Italy", "Japan"]
        }
    },

    # Tile 5: DEAD ZONE 1 (Corner 2, Top-Right)
    {
        "index": 5,
        "type": "dead_zone",
        "name": "DEAD ZONE 1",
        "short_name": "DEAD ZONE",
        "description": "Lethal hazard! Landing adds +1 Strike. 3 Strikes = Elimination!",
    },

    # Tile 6: Property
    {
        "index": 6,
        "type": "property",
        "name": "Nairobi",
        "country": "Kenya",
        "flag": "🇰🇪",
        "color": "#F97316",  # Orange
        "price": 220,
        "stats": {"climate": 8, "terrain": 7, "economy": 5},
        "trivia": {
            "hemisphere": "Southern",  # Nairobi is slightly south of equator
            "coastal": True,
            "continent": "Africa",
            "larger_than": ["France", "Spain", "Germany", "Japan"],
            "smaller_than": ["Brazil", "Australia", "Canada", "China"]
        }
    },

    # Tile 7: NEUTRAL Tile 1
    {
        "index": 7,
        "type": "neutral",
        "name": "Oasis Sanctuary",
        "short_name": "DRAW",
        "description": "Neutral zone. Land here to draw 1 TCG Card.",
    },

    # Tile 8: Property
    {
        "index": 8,
        "type": "property",
        "name": "Rio de Janeiro",
        "country": "Brazil",
        "flag": "🇧🇷",
        "color": "#F97316",  # Orange
        "price": 260,
        "stats": {"climate": 9, "terrain": 7, "economy": 6},
        "trivia": {
            "hemisphere": "Southern",
            "coastal": True,
            "continent": "South America",
            "larger_than": ["Australia", "India", "Argentina", "Mexico", "France"],
            "smaller_than": ["Russia", "Canada", "China", "United States"]
        }
    },

    # Tile 9: Property
    {
        "index": 9,
        "type": "property",
        "name": "London",
        "country": "United Kingdom",
        "flag": "🇬🇧",
        "color": "#EAB308",  # Yellow
        "price": 300,
        "stats": {"climate": 4, "terrain": 5, "economy": 9},
        "trivia": {
            "hemisphere": "Northern",
            "coastal": True,
            "continent": "Europe",
            "larger_than": ["Greece", "Portugal", "Austria", "Ireland"],
            "smaller_than": ["Germany", "France", "Spain", "Japan", "Norway"]
        }
    },

    # Tile 10: NEUTRAL Tile 2 (Corner 3, Bottom-Right)
    {
        "index": 10,
        "type": "neutral",
        "name": "World Trade Expo",
        "short_name": "DRAW",
        "description": "Neutral sanctuary. Land here to draw 1 TCG Card.",
    },

    # Tile 11: Property
    {
        "index": 11,
        "type": "property",
        "name": "Singapore",
        "country": "Singapore",
        "flag": "🇸🇬",
        "color": "#EAB308",  # Yellow
        "price": 340,
        "stats": {"climate": 8, "terrain": 3, "economy": 10},
        "trivia": {
            "hemisphere": "Northern",
            "coastal": True,
            "continent": "Asia",
            "larger_than": ["Vatican City", "Monaco", "Nauru"],
            "smaller_than": ["Japan", "United Kingdom", "France", "Switzerland"]
        }
    },

    # Tile 12: NEUTRAL Tile 3
    {
        "index": 12,
        "type": "neutral",
        "name": "Archival Vault",
        "short_name": "DRAW",
        "description": "Neutral haven. Land here to draw 1 TCG Card.",
    },

    # Tile 13: Property
    {
        "index": 13,
        "type": "property",
        "name": "Sydney",
        "country": "Australia",
        "flag": "🇦🇺",
        "color": "#A855F7",  # Purple
        "price": 280,
        "stats": {"climate": 8, "terrain": 6, "economy": 8},
        "trivia": {
            "hemisphere": "Southern",
            "coastal": True,
            "continent": "Oceania",
            "larger_than": ["India", "Argentina", "Mexico", "France", "Germany"],
            "smaller_than": ["Russia", "Canada", "China", "United States"]
        }
    },

    # Tile 14: Property (1 tile before DEAD ZONE 2 -> Proximity Gamble triggers!)
    {
        "index": 14,
        "type": "property",
        "name": "Kathmandu",
        "country": "Nepal",
        "flag": "🇳🇵",
        "color": "#A855F7",  # Purple
        "price": 220,
        "stats": {"climate": 3, "terrain": 10, "economy": 4},
        "trivia": {
            "hemisphere": "Northern",
            "coastal": False,  # Landlocked
            "continent": "Asia",
            "larger_than": ["Greece", "Portugal", "Austria", "Switzerland"],
            "smaller_than": ["France", "Spain", "Germany", "Japan", "India"]
        }
    },

    # Tile 15: DEAD ZONE 2 (Corner 4, Bottom-Left - exactly opposite Tile 5)
    {
        "index": 15,
        "type": "dead_zone",
        "name": "DEAD ZONE 2",
        "short_name": "DEAD ZONE",
        "description": "Lethal hazard! Landing adds +1 Strike. 3 Strikes = Elimination!",
    },

    # Tile 16: Property
    {
        "index": 16,
        "type": "property",
        "name": "Oslo",
        "country": "Norway",
        "flag": "🇳🇴",
        "color": "#EF4444",  # Red
        "price": 290,
        "stats": {"climate": 2, "terrain": 8, "economy": 9},
        "trivia": {
            "hemisphere": "Northern",
            "coastal": True,
            "continent": "Europe",
            "larger_than": ["United Kingdom", "Italy", "Germany", "Poland"],
            "smaller_than": ["France", "Spain", "Sweden", "Canada"]
        }
    },

    # Tile 17: Property
    {
        "index": 17,
        "type": "property",
        "name": "Dubai",
        "country": "United Arab Emirates",
        "flag": "🇦🇪",
        "color": "#EF4444",  # Red
        "price": 310,
        "stats": {"climate": 10, "terrain": 4, "economy": 9},
        "trivia": {
            "hemisphere": "Northern",
            "coastal": True,
            "continent": "Asia",
            "larger_than": ["Ireland", "Switzerland", "Belgium"],
            "smaller_than": ["France", "Spain", "United Kingdom", "Japan"]
        }
    },

    # Tile 18: Property
    {
        "index": 18,
        "type": "property",
        "name": "Vancouver",
        "country": "Canada",
        "flag": "🇨🇦",
        "color": "#06B6D4",  # Teal/Cyan
        "price": 270,
        "stats": {"climate": 4, "terrain": 8, "economy": 8},
        "trivia": {
            "hemisphere": "Northern",
            "coastal": True,
            "continent": "North America",
            "larger_than": ["United States", "China", "Brazil", "Australia", "India"],
            "smaller_than": ["Russia"]
        }
    },

    # Tile 19: Property
    {
        "index": 19,
        "type": "property",
        "name": "Paris",
        "country": "France",
        "flag": "🇫🇷",
        "color": "#06B6D4",  # Teal/Cyan
        "price": 300,
        "stats": {"climate": 6, "terrain": 5, "economy": 9},
        "trivia": {
            "hemisphere": "Northern",
            "coastal": True,
            "continent": "Europe",
            "larger_than": ["Spain", "Germany", "United Kingdom", "Italy", "Japan"],
            "smaller_than": ["United States", "Brazil", "Australia", "Canada"]
        }
    }
]

DEAD_ZONE_POSITIONS = [5, 15]
PRE_DEAD_ZONE_POSITIONS = [4, 14]
NEUTRAL_POSITIONS = [7, 10, 12]
PROPERTY_POSITIONS = [1, 2, 3, 4, 6, 8, 9, 11, 13, 14, 16, 17, 18, 19]

def get_tile(pos: int) -> dict:
    """Returns the tile definition for a position 0-19."""
    return BOARD_TILES[pos % 20]
