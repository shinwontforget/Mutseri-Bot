import random
from countries import TIER_BUDGET, TIER_MID_LOW, TIER_MID_HIGH, TIER_PREMIUM
from cards import get_fresh_chance_deck, get_fresh_treasury_deck

HOUSE_PRICES = {
    "brown": 50,
    "light_blue": 50,
    "pink": 100,
    "orange": 100,
    "red": 150,
    "yellow": 150,
    "green": 200,
    "dark_blue": 200,
}

def _make_city_tile(country, city_index, color, price, rent):
    """Create a single city property tile from a country's city list."""
    c = country
    city = c["cities"][city_index]
    return {
        "name": f"{c['flag']} {city}, {c['name']} (#{c['rank']})",
        "type": "property",
        "color": color,
        "price": price,
        "rent": rent,  # [base, 1 house, 2 houses, 3 houses, 4 houses, skyscraper]
        "country_rank": c["rank"],
        "country": c["name"],
        "city": city,
        "houses": 0,
        "is_mortgaged": False,
        "house_price": HOUSE_PRICES.get(color, 100)
    }

def generate_random_country_board():
    """Generates a symmetric 40-tile World Edition Monopoly board."""
    budget_pair   = random.sample(TIER_BUDGET,   2)
    mid_low_pair  = random.sample(TIER_MID_LOW,  2)
    mid_high_pair = random.sample(TIER_MID_HIGH, 2)
    premium_pair  = random.sample(TIER_PREMIUM,  2)

    b1, b2     = budget_pair
    ml1, ml2   = mid_low_pair
    mh1, mh2   = mid_high_pair
    p1, p2     = premium_pair

    board = [
        # CORNER 0
        {"name": "🛫 START / GO", "type": "go"},

        # PATH 1 — Budget (Top Row — Red Headers)
        _make_city_tile(b1, 0, "red",        60,  [2,  10,  30,  90,  160,  250]),
        {"name": "🏦 World Treasury",            "type": "community_chest"},
        _make_city_tile(b1, 1, "red",        60,  [4,  20,  60, 180,  320,  450]),
        {"name": "📉 Budget Import Duty",        "type": "tax", "amount": 75},
        {"name": "✈️ JFK International Airport", "type": "railroad", "price": 200, "is_mortgaged": False},
        _make_city_tile(b2, 0, "red",       100, [6,  30,  90, 270,  400,  550]),
        {"name": "🌐 Global News Event",         "type": "chance"},
        _make_city_tile(b2, 1, "red",       120, [8,  40, 100, 300,  450,  600]),
        {"name": "⚡ Global Solar Grid",         "type": "utility", "price": 150, "is_mortgaged": False},

        # CORNER 10
        {"name": "🛂 Customs Clearance / Border Control", "type": "jail"},

        # PATH 2 — Mid-Low (Right Column — Green Headers)
        _make_city_tile(ml1, 0, "green",   140, [10,  50, 150, 450,  625,  750]),
        {"name": "🏦 World Treasury",           "type": "community_chest"},
        _make_city_tile(ml1, 1, "green",   160, [12,  60, 180, 500,  700,  900]),
        {"name": "🧾 Regional Business Tax",    "type": "tax", "amount": 125},
        {"name": "✈️ Heathrow Airport",         "type": "railroad", "price": 200, "is_mortgaged": False},
        _make_city_tile(ml2, 0, "green", 180, [14,  70, 200, 550,  750,  950]),
        {"name": "🌐 Global News Event",        "type": "chance"},
        _make_city_tile(ml2, 1, "green", 200, [16,  80, 220, 600,  800, 1000]),
        {"name": "📡 Satellite Telecom Network","type": "utility", "price": 150, "is_mortgaged": False},

        # CORNER 20
        {"name": "🏝️ International Waters", "type": "free_parking"},

        # PATH 3 — Mid-High (Bottom Row — Light Blue Headers)
        _make_city_tile(mh1, 0, "light_blue", 220, [18,  90, 250, 700,  875, 1050]),
        {"name": "🏦 World Treasury",          "type": "community_chest"},
        _make_city_tile(mh1, 1, "light_blue", 240, [20, 100, 300, 750,  925, 1100]),
        {"name": "💼 Corporate Travel Tax",    "type": "tax", "amount": 175},
        {"name": "✈️ Haneda Airport",          "type": "railroad", "price": 200, "is_mortgaged": False},
        _make_city_tile(mh2, 0, "light_blue", 260, [22, 110, 330, 800,  975, 1150]),
        {"name": "🌐 Global News Event",       "type": "chance"},
        _make_city_tile(mh2, 1, "light_blue", 280, [24, 120, 360, 850, 1025, 1200]),
        {"name": "☢️ Nuclear Energy Grid",     "type": "utility", "price": 200, "is_mortgaged": False},

        # CORNER 30
        {"name": "🚨 Deportation / Border Violation", "type": "go_to_jail"},

        # PATH 4 — Premium (Left Column — Pink Headers)
        _make_city_tile(p1, 0, "pink",     300, [26, 130, 390,  900, 1100, 1275]),
        {"name": "🏦 World Treasury",             "type": "community_chest"},
        _make_city_tile(p1, 1, "pink",     320, [28, 150, 450, 1000, 1200, 1400]),
        {"name": "📈 Luxury Tariff",              "type": "tax", "amount": 250},
        {"name": "✈️ Dubai International Airport","type": "railroad", "price": 200, "is_mortgaged": False},
        _make_city_tile(p2, 0, "pink", 350, [35, 175, 500, 1100, 1300, 1500]),
        {"name": "🌐 Global News Event",          "type": "chance"},
        _make_city_tile(p2, 1, "pink", 400, [50, 200, 600, 1400, 1700, 2000]),
        {"name": "🛰️ Global Satellite Hub",      "type": "utility", "price": 200, "is_mortgaged": False},
    ]

    return board

class MonopolyGame:
    def __init__(self, players, board=None):
        self.board = board if board is not None else generate_random_country_board()
        self.players = {
            player.id: {
                "member": player,
                "money": 1500, 
                "position": 0,
                "in_jail": False,
                "jail_turns": 0,
                "has_jail_card": 0,
                "properties": [],
                "has_rolled": False,
                "bankrupt": False
            } for player in players
        }
        self.turn_index = 0
        self.turn_count = 1
        self.player_list = players
        self.properties_owned = {} # pos -> player_id
        self.log = []
        self.turn_message_history = []  # list of {"turn": int, "messages": list[discord.Message]}
        self.chance_deck = get_fresh_chance_deck()
        self.treasury_deck = get_fresh_treasury_deck()
        
    def get_current_player(self):
        # Skip bankrupt players
        active_count = sum(1 for p in self.player_list if not self.players[p.id]["bankrupt"])
        if active_count == 0:
            return self.player_list[0]
        
        while self.players[self.player_list[self.turn_index].id]["bankrupt"]:
            self.turn_index = (self.turn_index + 1) % len(self.player_list)
            
        return self.player_list[self.turn_index]
        
    def get_player_state(self, player_id):
        return self.players[player_id]

    def log_event(self, message):
        self.log.append(message)

    def next_turn(self):
        current_player_id = self.get_current_player().id
        self.players[current_player_id]["has_rolled"] = False
        self.turn_index = (self.turn_index + 1) % len(self.player_list)
        self.turn_count += 1
        # Advance to next active non-bankrupt player
        self.get_current_player()
        
    def roll_dice(self):
        return random.randint(1, 6), random.randint(1, 6)

    def move_player(self, player_id, steps) -> tuple[int, int]:
        player = self.players[player_id]
        if player["in_jail"] or player["bankrupt"]:
            return player["position"], player["position"]

        old_pos = player["position"]
        new_pos = (old_pos + steps) % 40
        player["position"] = new_pos

        if new_pos == 0:
            # Landed exactly on START — collect double salary
            player["money"] += 400
            self.log_event(f"🛫 {player['member'].display_name} landed exactly on START and collected $400!")
        elif new_pos < old_pos:
            # Passed through START — collect standard salary
            player["money"] += 200
            self.log_event(f"🛫 {player['member'].display_name} passed START and collected $200.")

        self.log_event(f"{player['member'].display_name} moved to {self.board[new_pos]['name']}.")
        self.handle_landing(player_id, new_pos)
        return old_pos, new_pos
        
    def handle_landing(self, player_id, pos):
        tile = self.board[pos]
        player = self.players[player_id]
        
        if tile["type"] == "tax":
            player["money"] -= tile["amount"]
            self.log_event(f"{player['member'].display_name} paid {tile['name']} of ${tile['amount']}.")
        elif tile["type"] == "go_to_jail":
            player["position"] = 10
            player["in_jail"] = True
            player["jail_turns"] = 0
            self.log_event(f"{player['member'].display_name} was held at Border Control!")
        elif tile["type"] == "chance":
            self.draw_and_execute_card(player_id, "chance")
        elif tile["type"] == "community_chest":
            self.draw_and_execute_card(player_id, "treasury")
        elif tile["type"] in ["property", "railroad", "utility"]:
            if pos in self.properties_owned:
                owner_id = self.properties_owned[pos]
                if owner_id != player_id and not self.board[pos].get("is_mortgaged", False):
                    rent = self.calculate_rent(pos)
                    player["money"] -= rent
                    self.players[owner_id]["money"] += rent
                    self.log_event(f"{player['member'].display_name} paid ${rent} rent to {self.players[owner_id]['member'].display_name}.")
                elif self.board[pos].get("is_mortgaged", False):
                    self.log_event(f"{tile['name']} is mortgaged. No rent collected!")
            else:
                self.log_event(f"{tile['name']} is unowned. {player['member'].display_name} can buy it for ${tile['price']}.")

    # --- Card Actions ---
    def draw_and_execute_card(self, player_id, deck_type: str) -> dict:
        player = self.players[player_id]
        card = self.chance_deck.draw_card() if deck_type == "chance" else self.treasury_deck.draw_card()
        action = card["action"]
        
        self.log_event(f"🎴 {player['member'].display_name} drew: {card['title']} — {card['description']}")
        
        if action == "money":
            player["money"] += card["amount"]
        elif action == "go_to_jail":
            player["position"] = 10
            player["in_jail"] = True
            player["jail_turns"] = 0
        elif action == "jail_free":
            player["has_jail_card"] += 1
        elif action == "move_to":
            old_pos = player["position"]
            target = card["target"]
            if card.get("pass_go", False) and target < old_pos:
                player["money"] += 200
                self.log_event(f"{player['member'].display_name} passed START and collected $200.")
            player["position"] = target
            self.handle_landing(player_id, target)
        elif action == "move_relative":
            new_pos = (player["position"] + card["steps"]) % 40
            player["position"] = new_pos
            self.handle_landing(player_id, new_pos)
        elif action == "move_to_nearest":
            pos = player["position"]
            airports = [5, 15, 25, 35]
            target = min(airports, key=lambda a: (a - pos) % 40)
            if target < pos:
                player["money"] += 200
            player["position"] = target
            self.handle_landing(player_id, target)
        elif action == "collect_from_players":
            amt = card["amount"]
            for pid, pdata in self.players.items():
                if pid != player_id and not pdata["bankrupt"]:
                    pdata["money"] -= amt
                    player["money"] += amt
        elif action == "repairs":
            total_houses = sum(self.board[p].get("houses", 0) for p in player["properties"] if self.board[p].get("houses", 0) < 5)
            total_skyscrapers = sum(1 for p in player["properties"] if self.board[p].get("houses", 0) == 5)
            cost = (total_houses * card["house_cost"]) + (total_skyscrapers * card["skyscraper_cost"])
            player["money"] -= cost
            if cost > 0:
                self.log_event(f"{player['member'].display_name} paid ${cost} in property repairs.")

        return card

    # --- Monopolies, Houses & Mortgages ---
    def has_monopoly(self, player_id, color: str) -> bool:
        color_tiles = [i for i, t in enumerate(self.board) if t.get("color") == color]
        if not color_tiles:
            return False
        return all(self.properties_owned.get(pos) == player_id for pos in color_tiles)

    def calculate_rent(self, pos) -> int:
        tile = self.board[pos]
        if tile.get("is_mortgaged", False):
            return 0
            
        t_type = tile["type"]
        if t_type == "property":
            houses = tile.get("houses", 0)
            owner_id = self.properties_owned.get(pos)
            if houses > 0:
                return tile["rent"][houses]
            elif owner_id and self.has_monopoly(owner_id, tile["color"]):
                return tile["rent"][0] * 2
            return tile["rent"][0]
        elif t_type == "railroad":
            owner_id = self.properties_owned[pos]
            owner = self.players[owner_id]
            count = sum(1 for p in owner["properties"] if self.board[p]["type"] == "railroad" and not self.board[p].get("is_mortgaged", False))
            return 25 * (2 ** (count - 1)) if count > 0 else 25
        elif t_type == "utility":
            return 20
        return 0

    def build_house(self, player_id, pos) -> bool:
        tile = self.board[pos]
        player = self.players[player_id]
        if (
            tile["type"] == "property"
            and self.properties_owned.get(pos) == player_id
            and self.has_monopoly(player_id, tile["color"])
            and tile["houses"] < 5
            and player["money"] >= tile["house_price"]
        ):
            player["money"] -= tile["house_price"]
            tile["houses"] += 1
            h_label = "Skyscraper" if tile["houses"] == 5 else f"House #{tile['houses']}"
            self.log_event(f"🏗️ {player['member'].display_name} built a {h_label} on {tile['name']} for ${tile['house_price']}.")
            return True
        return False

    def sell_house(self, player_id, pos) -> bool:
        tile = self.board[pos]
        player = self.players[player_id]
        if tile["type"] == "property" and self.properties_owned.get(pos) == player_id and tile["houses"] > 0:
            refund = tile["house_price"] // 2
            tile["houses"] -= 1
            player["money"] += refund
            self.log_event(f"🏷️ {player['member'].display_name} sold a house on {tile['name']} for ${refund}.")
            return True
        return False

    def mortgage_property(self, player_id, pos) -> bool:
        tile = self.board[pos]
        player = self.players[player_id]
        if (
            self.properties_owned.get(pos) == player_id
            and not tile.get("is_mortgaged", False)
            and tile.get("houses", 0) == 0
        ):
            mortgage_val = tile["price"] // 2
            tile["is_mortgaged"] = True
            player["money"] += mortgage_val
            self.log_event(f"🏦 {player['member'].display_name} mortgaged {tile['name']} for ${mortgage_val}.")
            return True
        return False

    def unmortgage_property(self, player_id, pos) -> bool:
        tile = self.board[pos]
        player = self.players[player_id]
        cost = int((tile["price"] // 2) * 1.10)
        if (
            self.properties_owned.get(pos) == player_id
            and tile.get("is_mortgaged", False)
            and player["money"] >= cost
        ):
            tile["is_mortgaged"] = False
            player["money"] -= cost
            self.log_event(f"🏦 {player['member'].display_name} unmortgaged {tile['name']} for ${cost}.")
            return True
        return False

    def buy_property(self, player_id, pos) -> bool:
        tile = self.board[pos]
        player = self.players[player_id]
        if pos not in self.properties_owned and player["money"] >= tile["price"]:
            player["money"] -= tile["price"]
            self.properties_owned[pos] = player_id
            player["properties"].append(pos)
            self.log_event(f"{player['member'].display_name} bought {tile['name']} for ${tile['price']}.")
            return True
        return False

    # --- Jail Mechanics ---
    def pay_jail_bail(self, player_id) -> bool:
        player = self.players[player_id]
        if player["in_jail"] and player["money"] >= 50:
            player["money"] -= 50
            player["in_jail"] = False
            player["jail_turns"] = 0
            self.log_event(f"💳 {player['member'].display_name} paid $50 bail to exit Border Control!")
            return True
        return False

    def attempt_jail_doubles(self, player_id) -> tuple[int, int, bool]:
        player = self.players[player_id]
        d1, d2 = self.roll_dice()
        if d1 == d2:
            player["in_jail"] = False
            player["jail_turns"] = 0
            self.log_event(f"🎲 {player['member'].display_name} rolled DOUBLES ({d1}, {d2}) and escaped Border Control!")
            self.move_player(player_id, d1 + d2)
            player["has_rolled"] = True
            return d1, d2, True
        else:
            player["jail_turns"] += 1
            self.log_event(f"🎲 {player['member'].display_name} rolled {d1} and {d2} (No doubles). Stays in Border Control.")
            player["has_rolled"] = True
            return d1, d2, False

    def use_jail_card(self, player_id) -> bool:
        player = self.players[player_id]
        if player["in_jail"] and player["has_jail_card"] > 0:
            player["has_jail_card"] -= 1
            player["in_jail"] = False
            player["jail_turns"] = 0
            self.log_event(f"🎟️ {player['member'].display_name} used a Diplomatic Pass to escape Border Control!")
            return True
        return False

    # --- Bankruptcy Safety Net ---
    def get_player_net_worth(self, player_id) -> int:
        player = self.players[player_id]
        total = player["money"]
        for pos in player["properties"]:
            tile = self.board[pos]
            if not tile.get("is_mortgaged", False):
                total += tile["price"] // 2
            houses = tile.get("houses", 0)
            if houses > 0:
                total += houses * (tile["house_price"] // 2)
        return total

    def declare_bankruptcy(self, player_id, creditor_id=None):
        player = self.players[player_id]
        player["bankrupt"] = True
        player["money"] = 0
        
        # Surrender properties
        for pos in list(player["properties"]):
            if creditor_id and creditor_id in self.players:
                self.properties_owned[pos] = creditor_id
                self.players[creditor_id]["properties"].append(pos)
            else:
                if pos in self.properties_owned:
                    del self.properties_owned[pos]
                self.board[pos]["houses"] = 0
                self.board[pos]["is_mortgaged"] = False
                
        player["properties"] = []
        creditor_name = self.players[creditor_id]["member"].display_name if creditor_id else "the Bank"
        self.log_event(f"💥 {player['member'].display_name} declared BANKRUPTCY and surrendered assets to {creditor_name}!")

    def get_unowned_properties(self) -> list[dict]:
        """Returns all unowned buyable tiles (properties, railroads, utilities)."""
        unowned = []
        for pos, tile in enumerate(self.board):
            if tile["type"] in ["property", "railroad", "utility"] and pos not in self.properties_owned:
                unowned.append({"pos": pos, **tile})
        return unowned

    def get_player_properties_detail(self, player_id: int) -> list[dict]:
        """Returns structured details of all properties owned by player_id."""
        player = self.players.get(player_id)
        if not player:
            return []
        details = []
        for pos in player["properties"]:
            tile = self.board[pos]
            rent = self.calculate_rent(pos)
            has_mono = self.has_monopoly(player_id, tile.get("color", "")) if tile.get("color") else False
            details.append({
                "pos": pos,
                "name": tile["name"],
                "city": tile.get("city", ""),
                "country": tile.get("country", ""),
                "type": tile["type"],
                "color": tile.get("color", ""),
                "price": tile.get("price", 0),
                "houses": tile.get("houses", 0),
                "is_mortgaged": tile.get("is_mortgaged", False),
                "rent": rent,
                "has_monopoly": has_mono
            })
        return details

    def find_property_by_name(self, query: str, player_id: int | None = None) -> int | None:
        """Finds a property position by city name, country, full name, or tile number (1-39)."""
        q = query.strip().lower()
        if q.isdigit():
            pos = int(q)
            if 0 <= pos < 40 and self.board[pos]["type"] in ["property", "railroad", "utility"]:
                if player_id is None or pos in self.players[player_id]["properties"]:
                    return pos

        candidates = []
        for pos, tile in enumerate(self.board):
            if tile["type"] not in ["property", "railroad", "utility"]:
                continue
            if player_id is not None and pos not in self.players[player_id]["properties"]:
                continue

            city = tile.get("city", "").lower()
            country = tile.get("country", "").lower()
            name = tile.get("name", "").lower()

            if q == city or q == country or q == name:
                return pos
            if q in city or q in country or q in name:
                candidates.append(pos)

        return candidates[0] if candidates else None
