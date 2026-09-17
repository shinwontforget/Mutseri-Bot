"""
game.py - Core Game Logic Engine for Territory Wars (20-Tile Redesign)

Replaces all legacy Monopoly rules (rent, houses, jail, tax, mortgages)
with Territory Wars mechanics:
- 20-tile loop
- Geographic properties & stats
- Territory conquer duels
- Proximity Gamble window (1 tile before Dead Zones)
- TCG cards (hand limit 5)
- Strike Pardons ($500, $1000, $2000...)
- Elimination at 3 strikes
- Turn cap (40 rounds) with tie-breakers
"""

import random
from territories import BOARD_TILES, DEAD_ZONE_POSITIONS, PRE_DEAD_ZONE_POSITIONS, NEUTRAL_POSITIONS, PROPERTY_POSITIONS, get_tile
from tcg_cards import generate_random_card

START_PASS_BONUS = 200
START_PROP_DIVIDEND = 100
MAX_HAND_LIMIT = 5
MAX_STRIKES = 3
DEFAULT_TURN_CAP = 40  # 40 rounds across players

class TerritoryWarsGame:
    def __init__(self, players: list, turn_order_override: list = None):
        """
        Initializes a new game of Territory Wars.
        `players`: list of discord Member / User objects.
        """
        ordered_players = turn_order_override if turn_order_override else list(players)
        self.player_list = ordered_players
        self.board = BOARD_TILES

        self.players = {}
        for p in self.player_list:
            # Each player starts with $1000 and 1 random card
            starting_card = generate_random_card()
            self.players[p.id] = {
                "member": p,
                "money": 1000,
                "position": 0,
                "strikes": 0,
                "cards": [starting_card],
                "properties": [],  # list of tile indices
                "pardon_count": 0,
                "is_eliminated": False,
                "has_rolled": False,
            }

        self.properties_owned = {}  # pos -> player_id
        self.turn_index = 0
        self.round_count = 1
        self.total_turns_taken = 0
        self.log = []
        self.turn_message_history = []

        # Proximity Gamble cooldown tracking
        self.last_gamble_challenger_id = None
        self.last_gamble_turn = -99

        # Static board rendering cache
        self._static_board_cache = None
        self._static_board_cache_key = None

    def invalidate_static_cache(self):
        """Invalidates the cached static board layer when ownership changes."""
        self._static_board_cache = None
        self._static_board_cache_key = None

    def log_event(self, msg: str):
        self.log.append(msg)

    def get_player_state(self, player_id: int) -> dict:
        return self.players.get(player_id)

    def get_active_players(self) -> list:
        """Returns list of players who are not eliminated."""
        return [p for p in self.player_list if not self.players[p.id]["is_eliminated"]]

    def get_current_player(self):
        """Returns the current active player whose turn it is."""
        active = self.get_active_players()
        if not active:
            return self.player_list[0]

        # Advance until we find a non-eliminated player
        while self.players[self.player_list[self.turn_index].id]["is_eliminated"]:
            self.turn_index = (self.turn_index + 1) % len(self.player_list)

        return self.player_list[self.turn_index]

    def roll_dice(self) -> int:
        """Rolls a single 6-sided die (1-6)."""
        return random.randint(1, 6)

    def add_card_to_player(self, player_id: int) -> tuple[dict, bool]:
        """
        Awards 1 random TCG card to the player.
        Returns (card, needs_discard).
        If cards count > MAX_HAND_LIMIT, needs_discard is True.
        """
        card = generate_random_card()
        st = self.players[player_id]
        st["cards"].append(card)
        needs_discard = len(st["cards"]) > MAX_HAND_LIMIT
        return card, needs_discard

    def remove_card_from_player(self, player_id: int, card_id: str) -> bool:
        """Removes a specific card from the player's hand (e.g. discard or played)."""
        st = self.players[player_id]
        for i, c in enumerate(st["cards"]):
            if c["id"] == card_id:
                st["cards"].pop(i)
                return True
        return False

    def move_player(self, player_id: int, steps: int) -> dict:
        """
        Advances player by `steps` tiles.
        Calculates START pass bonus ($200 + 1 card + $100/property).
        Returns a dict summarizing the move.
        """
        st = self.players[player_id]
        old_pos = st["position"]
        new_pos = (old_pos + steps) % len(self.board)
        st["position"] = new_pos

        # Check if passed or landed on START (tile 0)
        passed_start = (old_pos + steps) >= len(self.board)
        start_payout = 0
        drawn_card = None
        needs_discard = False

        if passed_start:
            num_props = len(st["properties"])
            start_payout = START_PASS_BONUS + (START_PROP_DIVIDEND * num_props)
            st["money"] += start_payout
            drawn_card, needs_discard = self.add_card_to_player(player_id)
            self.log_event(
                f"🚩 **{st['member'].display_name}** passed START! Received **+${start_payout}** "
                f"(${START_PASS_BONUS} + ${START_PROP_DIVIDEND}x{num_props} properties) and drawn TCG Card: `{drawn_card['title']}`."
            )

        tile = get_tile(new_pos)

        # Check if landed on pre-dead zone (triggers Proximity Gamble window)
        is_pre_dead_zone = new_pos in PRE_DEAD_ZONE_POSITIONS

        return {
            "old_pos": old_pos,
            "new_pos": new_pos,
            "steps": steps,
            "passed_start": passed_start,
            "start_payout": start_payout,
            "drawn_card": drawn_card,
            "needs_discard": needs_discard,
            "tile": tile,
            "is_pre_dead_zone": is_pre_dead_zone
        }

    def add_strike(self, player_id: int) -> tuple[int, bool]:
        """
        Adds 1 strike to player.
        If strikes reach 3, eliminates the player and returns all owned properties to unowned pool.
        Returns (strikes_count, is_now_eliminated).
        """
        st = self.players[player_id]
        st["strikes"] += 1
        eliminated = False

        if st["strikes"] >= MAX_STRIKES:
            st["is_eliminated"] = True
            eliminated = True
            # Return all owned properties to unowned
            for pos in list(st["properties"]):
                if pos in self.properties_owned:
                    del self.properties_owned[pos]
            st["properties"].clear()
            self.invalidate_static_cache()
            self.log_event(f"💀 **{st['member'].display_name}** accumulated 3 STRIKES and has been ELIMINATED! All their territories are released!")

        return st["strikes"], eliminated

    def get_pardon_cost(self, player_id: int) -> int:
        """Returns the current strike pardon cost for the player: 500 * (2 ** count)."""
        count = self.players[player_id]["pardon_count"]
        return 500 * (2 ** count)

    def can_pardon_strike(self, player_id: int) -> tuple[bool, str]:
        """Checks if a player can pay for a strike pardon."""
        st = self.players[player_id]
        if st["strikes"] <= 0:
            return False, "You have 0 strikes to pardon."
        cost = self.get_pardon_cost(player_id)
        if st["money"] < cost:
            return False, f"Insufficient funds! A pardon costs **${cost}**, but you only have **${st['money']}**."
        return True, ""

    def pardon_strike(self, player_id: int) -> tuple[bool, int, int]:
        """
        Pardons 1 strike.
        Deducts money, decreases strikes, doubles next cost.
        Returns (success, new_strikes, next_cost).
        """
        can, reason = self.can_pardon_strike(player_id)
        if not can:
            return False, 0, 0

        st = self.players[player_id]
        cost = self.get_pardon_cost(player_id)
        st["money"] -= cost
        st["strikes"] = max(0, st["strikes"] - 1)
        st["pardon_count"] += 1
        next_cost = self.get_pardon_cost(player_id)

        self.log_event(f"🏥 **{st['member'].display_name}** purchased a Strike Pardon for **${cost}**! (Remaining strikes: {st['strikes']}, next pardon: ${next_cost})")
        return True, st["strikes"], next_cost

    def buy_property(self, player_id: int, pos: int) -> bool:
        """Purchases an unowned property at fixed price."""
        st = self.players[player_id]
        tile = get_tile(pos)
        price = tile.get("price", 250)

        if pos in self.properties_owned:
            return False
        if st["money"] < price:
            return False

        st["money"] -= price
        st["properties"].append(pos)
        self.properties_owned[pos] = player_id
        self.invalidate_static_cache()
        self.log_event(f"🏛️ **{st['member'].display_name}** bought **{tile['name']}, {tile['country']}** for **${price}**.")
        return True

    def transfer_property(self, from_player_id: int, to_player_id: int, pos: int):
        """Transfers ownership of a property from one player to another (e.g. duel win)."""
        tile = get_tile(pos)
        from_st = self.players.get(from_player_id)
        to_st = self.players.get(to_player_id)

        if from_st and pos in from_st["properties"]:
            from_st["properties"].remove(pos)

        if to_st and pos not in to_st["properties"]:
            to_st["properties"].append(pos)

        self.properties_owned[pos] = to_player_id
        self.invalidate_static_cache()
        self.log_event(f"🚩 Ownership of **{tile['name']}** transferred to **{to_st['member'].display_name}**!")

    def can_initiate_gamble(self, challenger_id: int, exposed_player_id: int) -> tuple[bool, str]:
        """
        Checks if challenger can challenge the exposed player:
        - Must not be the exposed player
        - Challenger must not be eliminated
        - Challenger cannot initiate a gamble two turns in a row
        """
        if challenger_id == exposed_player_id:
            return False, "You cannot challenge yourself!"

        ch_st = self.players[challenger_id]
        if ch_st["is_eliminated"]:
            return False, "Eliminated players cannot initiate gambles."

        # Anti-farming: cannot challenge two turns in a row
        if self.last_gamble_challenger_id == challenger_id and (self.total_turns_taken - self.last_gamble_turn) <= 1:
            return False, "You cannot initiate a Proximity Gamble two turns in a row!"

        return True, ""

    def record_gamble_attempt(self, challenger_id: int):
        """Records gamble challenge to enforce anti-farming cooldown."""
        self.last_gamble_challenger_id = challenger_id
        self.last_gamble_turn = self.total_turns_taken

    def check_game_over(self) -> tuple[bool, dict | None]:
        """
        Checks if the game has ended:
        1. Only 1 active player remains -> that player wins!
        2. Turn cap (40 rounds) reached -> ranked by fewest strikes, then properties owned, then money.
        """
        active = self.get_active_players()
        if len(active) == 1:
            winner = active[0]
            return True, {
                "winner": winner,
                "reason": f"Last commander standing! All rival players were eliminated.",
                "rankings": [winner]
            }
        elif len(active) == 0:
            # Tie / all eliminated simultaneously
            return True, {
                "winner": self.player_list[0],
                "reason": "All players were eliminated.",
                "rankings": self.player_list
            }

        # Check turn cap
        if self.round_count > DEFAULT_TURN_CAP:
            # Sort active players by fewest strikes -> most properties -> most money
            def rank_key(p):
                st = self.players[p.id]
                return (
                    st["strikes"],            # Ascending (fewer strikes is better)
                    -len(st["properties"]),   # Descending (more properties is better)
                    -st["money"]              # Descending (more money is better)
                )

            ranked = sorted(active, key=rank_key)
            winner = ranked[0]
            w_st = self.players[winner.id]
            return True, {
                "winner": winner,
                "reason": (
                    f"Turn limit ({DEFAULT_TURN_CAP} rounds) reached!\n"
                    f"**{winner.display_name}** wins with **{w_st['strikes']} strikes**, "
                    f"**{len(w_st['properties'])} properties**, and **${w_st['money']}**!"
                ),
                "rankings": ranked
            }

        return False, None

    def next_turn(self):
        """Advances turn to next active player."""
        current = self.get_current_player()
        self.players[current.id]["has_rolled"] = False

        self.turn_index = (self.turn_index + 1) % len(self.player_list)
        self.total_turns_taken += 1

        # Check if full round completed
        if self.turn_index == 0:
            self.round_count += 1

        # Advance past any eliminated player
        self.get_current_player()
