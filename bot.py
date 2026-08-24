import os
import re
import time
import asyncio
import logging
import discord
from aiohttp import web
from discord.ext import commands
from game import MonopolyGame, generate_random_country_board
from board_renderer import render_board_image, render_board_movement_animation
from trade_view import TradeProposalView
from stats_db import (
    get_player_stats, record_game_win, claim_daily,
    get_top_leaderboard, set_custom_token
)
from dotenv import load_dotenv

load_dotenv()

PLAYER_TOKENS = ["🔴", "🔵", "🟢", "🟡"]

COLOR_LABELS = {
    "brown":     "🟤",
    "light_blue":"🔵",
    "pink":      "🩷",
    "orange":    "🟠",
    "red":       "🔴",
    "yellow":    "🟡",
    "green":     "🟢",
    "dark_blue": "💙",
}

async def cleanup_turn_messages(game, channel):
    """Auto-deletes messages from 2 or more full turns ago."""
    if not channel or not hasattr(game, "turn_message_history"):
        return
    remaining_history = []
    for entry in game.turn_message_history:
        # Auto-delete after 2 full turns complete
        if game.turn_count - entry["turn"] >= 2:
            for msg in entry["messages"]:
                try:
                    await msg.delete()
                except Exception:
                    pass
        else:
            remaining_history.append(entry)
    game.turn_message_history = remaining_history

def format_active_event(game) -> str | None:
    """Returns a formatted banner string if a world event is currently active."""
    if game.active_event:
        ev = game.active_event
        rem = ev.get("turns_remaining", 0)
        turn_str = f"{rem} turn{'s' if rem != 1 else ''} remaining"
        return f"🌍 **Active World Event:** {ev['title']} — {ev['description']} (⏳ {turn_str})"
    return None

def format_scorecard_lines(game) -> str:
    """Formats player cash and property balances in clean plain text."""
    lines = []
    for i, p in enumerate(game.player_list):
        st = game.get_player_state(p.id)
        stat = get_player_stats(p.id, p.display_name)
        token = stat.get("custom_token") or PLAYER_TOKENS[i % len(PLAYER_TOKENS)]
        jail_tag = " [🔒 In Border Control]" if st["in_jail"] else ""
        bankrupt_tag = " [💥 BANKRUPT]" if st.get("bankrupt", False) else ""
        prop_cnt = len(st["properties"])
        lines.append(f"{token} **{p.display_name}**: 💰 ${st['money']} | 🏠 {prop_cnt} props{jail_tag}{bankrupt_tag}")
    
    event_str = format_active_event(game)
    if event_str:
        lines.append(f"\n{event_str}")
    return "\n".join(lines)

def parse_trade_args(game, sender_id: int, target_id: int, raw_args: str) -> tuple[list[int], int, list[int], int, str | None]:
    """
    Parses arbitrary combinations of properties and cash for trade proposals.
    Supports:
      - '100 50'
      - 'Tokyo for London'
      - 'Tokyo 100 for London 50'
      - 'offer: Tokyo, 100 req: London, 50'
      - 'Tokyo, New York to London, 100'
    """
    if not raw_args.strip():
        return [], 0, [], 0, "Please specify what you are offering and requesting. Example: `!trade @user Tokyo $100 for London $50`"

    text = raw_args.strip()

    # Split into offered vs requested using standard keywords
    split_match = re.search(r'(\bfor\b|\bto\b|\breq:\s*|\brequest:\s*|\brequesting:\s*|\bwants?:\s*|\bwant\b|\bwants\b)', text, re.IGNORECASE)
    if split_match:
        offer_str = text[:split_match.start()].strip()
        req_str = text[split_match.end():].strip()
    else:
        parts = text.split()
        if len(parts) == 2:
            offer_str = parts[0]
            req_str = parts[1]
        else:
            found_split = False
            for split_idx in range(1, len(parts)):
                cand_offer = " ".join(parts[:split_idx])
                cand_req = " ".join(parts[split_idx:])
                if (game.find_property_by_name(cand_offer, sender_id) is not None or cand_offer.replace('$', '').replace(',', '').isdigit()) and \
                   (game.find_property_by_name(cand_req, target_id) is not None or cand_req.replace('$', '').replace(',', '').isdigit()):
                    offer_str = cand_offer
                    req_str = cand_req
                    found_split = True
                    break
            if not found_split:
                return [], 0, [], 0, "Could not separate offer and request. Use `for` (e.g. `!trade @user [offer] for [request]`)."

    offer_str = re.sub(r'^(offer|offering|give|giving):\s*', '', offer_str, flags=re.IGNORECASE).strip()
    req_str = re.sub(r'^(req|request|requesting|want|wants):\s*', '', req_str, flags=re.IGNORECASE).strip()

    def parse_side(side_str: str, player_id: int):
        cash = 0
        props = []
        tokens = [t.strip() for t in re.split(r'[,;]+|\s+', side_str) if t.strip()]
        unmatched_words = []

        for tok in tokens:
            num_clean = tok.replace('$', '').replace(',', '')
            if num_clean.isdigit():
                cash += int(num_clean)
            else:
                unmatched_words.append(tok)

        if unmatched_words:
            full_phrase = " ".join(unmatched_words)
            pos = game.find_property_by_name(full_phrase, player_id)
            if pos is not None:
                props.append(pos)
            else:
                for word in unmatched_words:
                    p = game.find_property_by_name(word, player_id)
                    if p is not None and p not in props:
                        props.append(p)
                    elif p is None:
                        return None, None, f"Property `{word}` not found or not owned by <@{player_id}>!"

        return props, cash, None

    offer_props, offer_cash, err1 = parse_side(offer_str, sender_id)
    if err1:
        return [], 0, [], 0, err1

    req_props, req_cash, err2 = parse_side(req_str, target_id)
    if err2:
        return [], 0, [], 0, err2

    if not offer_props and offer_cash == 0 and not req_props and req_cash == 0:
        return [], 0, [], 0, "A trade proposal must include at least one cash amount or property!"

    return offer_props, offer_cash, req_props, req_cash, None


# ---------------------------------------------------------------------------
# Auction View — lightweight turn-based bidding mode
# ---------------------------------------------------------------------------

class AuctionView(discord.ui.View):
    """
    Handles property auctions when the landed-on player declines to purchase.
    Cycles through eligible bidders in turn order.
    """
    def __init__(self, game, channel_id: int, pos: int, decliner_id: int, parent_turn_view: "TurnView"):
        super().__init__(timeout=30.0)
        self.game = game
        self.channel_id = channel_id
        self.pos = pos
        self.tile = game.board[pos]
        self.decliner_id = decliner_id
        self.parent_turn_view = parent_turn_view

        # Eligible bidders: all active non-bankrupt players (excluding decliner)
        self.active_bidders = [
            p for p in game.player_list
            if not game.players[p.id]["bankrupt"] and p.id != decliner_id
        ]
        self.bidder_idx = 0
        self.highest_bid = 0
        self.highest_bidder: discord.Member | None = None
        self.message: discord.Message | None = None
        self.concluded = False
        self.setup_auction_buttons()

    def setup_auction_buttons(self):
        self.clear_items()
        if not self.active_bidders or self.concluded:
            return

        current_bidder = self.active_bidders[self.bidder_idx % len(self.active_bidders)]
        bidder_money = self.game.players[current_bidder.id]["money"]

        # Option: Bid +$10
        if bidder_money >= self.highest_bid + 10:
            b10 = discord.ui.Button(label=f"💵 Bid ${self.highest_bid + 10} (+10)", style=discord.ButtonStyle.green, custom_id="bid_10")
            b10.callback = lambda i: self.handle_bid(i, 10)
            self.add_item(b10)

        # Option: Bid +$25
        if bidder_money >= self.highest_bid + 25:
            b25 = discord.ui.Button(label=f"💵 Bid ${self.highest_bid + 25} (+25)", style=discord.ButtonStyle.blurple, custom_id="bid_25")
            b25.callback = lambda i: self.handle_bid(i, 25)
            self.add_item(b25)

        # Option: Bid +$50
        if bidder_money >= self.highest_bid + 50:
            b50 = discord.ui.Button(label=f"💵 Bid ${self.highest_bid + 50} (+50)", style=discord.ButtonStyle.primary, custom_id="bid_50")
            b50.callback = lambda i: self.handle_bid(i, 50)
            self.add_item(b50)

        # Option: Pass
        pass_btn = discord.ui.Button(label="❌ Pass", style=discord.ButtonStyle.red, custom_id="auction_pass")
        pass_btn.callback = self.handle_pass
        self.add_item(pass_btn)

    def build_auction_text(self) -> str:
        if not self.active_bidders:
            return f"🏛️ **Auction for {self.tile['name']} has ended.**"

        current_bidder = self.active_bidders[self.bidder_idx % len(self.active_bidders)]
        high_str = f"**${self.highest_bid}** by {self.highest_bidder.mention}" if self.highest_bidder else "*No bids yet ($0)*"
        remaining_names = ", ".join(p.display_name for p in self.active_bidders)

        return (
            f"🏛️ **PROPERTY AUCTION: {self.tile['name']}** (List Price: ${self.tile['price']})\n"
            f"💰 **Current High Bid:** {high_str}\n"
            f"👥 **Active Bidders ({len(self.active_bidders)}):** {remaining_names}\n\n"
            f"👉 **{current_bidder.mention}'s turn to bid or pass** (⏱️ 30s limit)"
        )

    async def on_timeout(self):
        if self.concluded:
            return
        # Current bidder automatically passes on timeout
        if self.active_bidders:
            current_bidder = self.active_bidders[self.bidder_idx % len(self.active_bidders)]
            self.game.log_event(f"⏱️ {current_bidder.display_name} timed out in auction and passed.")
            self.active_bidders.remove(current_bidder)
            await self.check_auction_end_or_advance()

    async def handle_bid(self, interaction: discord.Interaction, increment: int):
        if not self.active_bidders:
            return
        current_bidder = self.active_bidders[self.bidder_idx % len(self.active_bidders)]
        if interaction.user.id != current_bidder.id:
            await interaction.response.send_message(f"It's {current_bidder.display_name}'s turn to bid!", ephemeral=True)
            return

        new_bid = self.highest_bid + increment
        bidder_state = self.game.players[current_bidder.id]
        if bidder_state["money"] < new_bid:
            await interaction.response.send_message("You don't have enough money for this bid!", ephemeral=True)
            return

        self.highest_bid = new_bid
        self.highest_bidder = current_bidder
        self.game.log_event(f"🏛️ {current_bidder.display_name} bid ${new_bid} on {self.tile['name']}.")

        # If only 1 bidder left and they just bid, they win
        if len(self.active_bidders) == 1:
            await self.conclude_auction(interaction)
            return

        # Advance to next bidder
        self.bidder_idx = (self.bidder_idx + 1) % len(self.active_bidders)
        self.setup_auction_buttons()
        await interaction.response.edit_message(content=self.build_auction_text(), view=self)

    async def handle_pass(self, interaction: discord.Interaction):
        if not self.active_bidders:
            return
        current_bidder = self.active_bidders[self.bidder_idx % len(self.active_bidders)]
        if interaction.user.id != current_bidder.id:
            await interaction.response.send_message(f"It's {current_bidder.display_name}'s turn to act!", ephemeral=True)
            return

        self.game.log_event(f"🏛️ {current_bidder.display_name} passed on {self.tile['name']}.")
        self.active_bidders.remove(current_bidder)
        await self.check_auction_end_or_advance(interaction)

    async def check_auction_end_or_advance(self, interaction: discord.Interaction | None = None):
        # Case 1: No bidders left or only 1 bidder left who holds highest bid
        if len(self.active_bidders) == 0 or (len(self.active_bidders) == 1 and self.highest_bidder == self.active_bidders[0]):
            await self.conclude_auction(interaction)
            return

        self.bidder_idx %= len(self.active_bidders)
        self.setup_auction_buttons()
        if interaction:
            await interaction.response.edit_message(content=self.build_auction_text(), view=self)
        elif self.message:
            try:
                await self.message.edit(content=self.build_auction_text(), view=self)
            except Exception:
                pass

    async def conclude_auction(self, interaction: discord.Interaction | None = None):
        self.concluded = True
        self.stop()
        for item in self.children:
            item.disabled = True

        channel = bot.get_channel(self.channel_id)
        if self.highest_bidder and self.highest_bid > 0:
            winner = self.highest_bidder
            self.game.players[winner.id]["money"] -= self.highest_bid
            self.game.properties_owned[self.pos] = winner.id
            self.game.players[winner.id]["properties"].append(self.pos)
            self.game.invalidate_static_cache()
            self.game.log_event(f"🎉 {winner.display_name} WON the auction for {self.tile['name']} for ${self.highest_bid}!")

            win_text = (
                f"🎉 **AUCTION CONCLUDED!**\n"
                f"🏆 **{winner.mention}** won **{self.tile['name']}** with a winning bid of **${self.highest_bid}**!\n"
                f"💰 Balance remaining: **${self.game.players[winner.id]['money']}**"
            )
        else:
            win_text = (
                f"🏛️ **AUCTION CONCLUDED!**\n"
                f"All players passed. **{self.tile['name']}** remains unowned."
            )

        if interaction:
            await interaction.response.edit_message(content=win_text, view=self)
        elif self.message:
            try:
                await self.message.edit(content=win_text, view=self)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Main Turn View
# ---------------------------------------------------------------------------

class TurnView(discord.ui.View):
    def __init__(self, game, channel_id):
        super().__init__(timeout=None)
        self.game = game
        self.game.current_view = self
        self.channel_id = channel_id
        self.timer_task = None
        self.message: discord.Message | None = None
        self._rolling = False  # double-click guard for roll
        self._buying = False   # double-click guard for buy
        self.setup_buttons()
        self.reset_timer()

    def stop(self):
        if self.timer_task and not self.timer_task.done():
            self.timer_task.cancel()
        super().stop()

    def reset_timer(self):
        if self.timer_task and not self.timer_task.done():
            self.timer_task.cancel()
        self.timer_task = asyncio.create_task(self.turn_timeout_task())

    async def turn_timeout_task(self):
        try:
            await asyncio.sleep(90)  # 90-second turn limit
            if self.channel_id not in active_games or active_games.get(self.channel_id) != self.game:
                return

            self.game.consecutive_inactive_turns += 1

            channel = bot.get_channel(self.channel_id)
            if self.game.consecutive_inactive_turns >= 5:
                if self.channel_id in active_games:
                    del active_games[self.channel_id]
                self.stop()
                if channel:
                    await channel.send(
                        "🛑 **GAME OVER — INACTIVITY**\n"
                        "⏱️ The game was ended automatically because all players have been inactive for 5 consecutive turns."
                    )
                return

            current_player = self.game.get_current_player()
            player_state = self.game.get_player_state(current_player.id)

            if not player_state["has_rolled"]:
                d1, d2 = self.game.roll_dice()
                total = d1 + d2
                self.game.log_event(f"⏱️ AUTO-ROLL: {current_player.display_name} rolled {d1} and {d2} (Total: {total})")
                self.game.move_player(current_player.id, total)
                player_state["has_rolled"] = True

            self.game.log_event(f"⏱️ TIME EXPIRED: {current_player.display_name}'s turn was automatically ended.")
            self.game.next_turn()

            next_p = self.game.get_current_player()
            if not channel:
                return

            # Offload PIL rendering to executor thread
            buf = await asyncio.to_thread(render_board_image, self.game)
            visual_file = discord.File(buf, filename="monopoly_board.png")
            deadline_ts = int(time.time()) + 90

            inactivity_warn = f" (⚠️ Inactivity: {self.game.consecutive_inactive_turns}/5 turns without player input)"
            action_text = (
                f"⏱️ **Turn Timer Expired (90s)**{inactivity_warn}\n"
                f"**{current_player.display_name}** took too long! Turn automatically passed to **{next_p.mention}**."
            )
            financial_text = f"💰 **Player Balances:**\n{format_scorecard_lines(self.game)}"
            status_text = f"⏳ **Turn Status:** It is now **{next_p.display_name}**'s turn! (⏱️ Expires <t:{deadline_ts}:R>)"

            self.setup_buttons()
            await self.send_turn_bundle(channel, visual_file, action_text, financial_text, status_text)
            self.reset_timer()
        except asyncio.CancelledError:
            pass

    def setup_buttons(self):
        self.clear_items()
        current_player = self.game.get_current_player()
        player_state = self.game.get_player_state(current_player.id)

        # 1. Jail Options
        if player_state["in_jail"]:
            bail_btn = discord.ui.Button(label="💳 Pay $50 Bail", style=discord.ButtonStyle.green, custom_id="bail")
            bail_btn.callback = self.bail_callback
            self.add_item(bail_btn)

            doubles_btn = discord.ui.Button(label="🎲 Roll Doubles", style=discord.ButtonStyle.blurple, custom_id="doubles")
            doubles_btn.callback = self.doubles_callback
            self.add_item(doubles_btn)

            if player_state.get("has_jail_card", 0) > 0:
                pass_btn = discord.ui.Button(label="🎟️ Use Diplomatic Pass", style=discord.ButtonStyle.gold, custom_id="jail_pass")
                pass_btn.callback = self.jail_card_callback
                self.add_item(pass_btn)

        # 2. Emergency Bankruptcy Rescue
        elif player_state["money"] < 0:
            mort_btn = discord.ui.Button(label="🏦 Mortgage Property", style=discord.ButtonStyle.secondary, custom_id="mortgage")
            mort_btn.callback = self.mortgage_callback
            self.add_item(mort_btn)

            sell_btn = discord.ui.Button(label="🏷️ Sell House", style=discord.ButtonStyle.secondary, custom_id="sell_house")
            sell_btn.callback = self.sell_house_callback
            self.add_item(sell_btn)

            bankrupt_btn = discord.ui.Button(label="💥 Declare Bankruptcy", style=discord.ButtonStyle.danger, custom_id="bankruptcy")
            bankrupt_btn.callback = self.bankruptcy_callback
            self.add_item(bankrupt_btn)

        # 3. Normal Turn Actions
        else:
            if not player_state["has_rolled"]:
                roll_btn = discord.ui.Button(label="🎲 Roll Dice", style=discord.ButtonStyle.blurple, custom_id="roll")
                roll_btn.callback = self.roll_callback
                self.add_item(roll_btn)
            else:
                pos = player_state["position"]
                tile = self.game.board[pos]

                # Genuine decision: unowned property and player has enough money to buy
                if (
                    tile["type"] in ["property", "railroad", "utility"]
                    and pos not in self.game.properties_owned
                    and player_state["money"] >= tile["price"]
                ):
                    buy_btn = discord.ui.Button(label=f"🏠 Buy for ${tile['price']}", style=discord.ButtonStyle.green, custom_id="buy")
                    buy_btn.callback = self.buy_callback
                    self.add_item(buy_btn)

                    decline_btn = discord.ui.Button(label="🚫 Decline / Auction", style=discord.ButtonStyle.secondary, custom_id="decline_auction")
                    decline_btn.callback = self.decline_callback
                    self.add_item(decline_btn)

                has_monopolies = any(self.game.has_monopoly(current_player.id, color) for color in COLOR_LABELS)
                if has_monopolies:
                    build_btn = discord.ui.Button(label="🏗️ Build House", style=discord.ButtonStyle.primary, custom_id="build")
                    build_btn.callback = self.build_callback
                    self.add_item(build_btn)

                has_mortgaged = any(self.game.board[p].get("is_mortgaged", False) for p in player_state["properties"])
                if has_mortgaged:
                    unmort_btn = discord.ui.Button(label="🔓 Unmortgage Property", style=discord.ButtonStyle.secondary, custom_id="unmortgage")
                    unmort_btn.callback = self.unmortgage_callback
                    self.add_item(unmort_btn)

                end_btn = discord.ui.Button(label="⏩ End Turn", style=discord.ButtonStyle.red, custom_id="end")
                end_btn.callback = self.end_callback
                self.add_item(end_btn)

        board_btn = discord.ui.Button(label="📋 View Board", style=discord.ButtonStyle.grey, custom_id="board")
        board_btn.callback = self.board_callback
        self.add_item(board_btn)

    async def send_turn_bundle(self, channel: discord.TextChannel, visual_file: discord.File, action_text: str, financial_text: str, status_text: str):
        """Sends the 3 grouped plain-text turn messages with the board image/GIF and handles 2-turn auto-cleanup."""
        msg1 = await channel.send(content=action_text, file=visual_file)
        msg2 = await channel.send(content=financial_text)
        msg3 = await channel.send(content=status_text, view=self)
        self.message = msg3
        self.game.turn_message_history.append({
            "turn": self.game.turn_count,
            "messages": [msg1, msg2, msg3]
        })
        await cleanup_turn_messages(self.game, channel)

    async def roll_callback(self, interaction: discord.Interaction):
        current_player = self.game.get_current_player()
        if interaction.user.id != current_player.id:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        player_state = self.game.get_player_state(current_player.id)
        if player_state.get("has_rolled", False) or self._rolling:
            await interaction.response.send_message("You have already rolled this turn!", ephemeral=True)
            return
        self._rolling = True
        player_state["has_rolled"] = True

        self.game.record_activity()
        await interaction.response.defer()

        d1, d2 = self.game.roll_dice()
        total = d1 + d2
        old_pos, new_pos = self.game.move_player(current_player.id, total)
        current_tile = self.game.board[new_pos]

        # Offload animated GIF rendering to executor thread
        anim_buf = await asyncio.to_thread(render_board_movement_animation, self.game, current_player.id, old_pos, new_pos)
        visual_file = discord.File(anim_buf, filename="monopoly_move.gif")

        deadline_ts = int(time.time()) + 90
        recent_log = self.game.log[-2:] if len(self.game.log) >= 2 else self.game.log[-1:]

        # Auto-resolve note if trivial tile / insufficient funds
        auto_note = ""
        if current_tile["type"] in ["property", "railroad", "utility"]:
            if new_pos not in self.game.properties_owned and player_state["money"] < current_tile["price"]:
                auto_note = f"\n⚠️ *Insufficient funds to buy {current_tile['name']} (${current_tile['price']}) — purchase skipped.*"

        action_text = (
            f"🎲 **{current_player.display_name}** rolled **[{d1}, {d2}] (Total: {total})**!\n"
            f"📍 Landed on **{current_tile['name']}**.{auto_note}\n"
            f"📜 " + " | ".join(recent_log)
        )
        financial_text = (
            f"💰 **Financial Summary:** Balance: **${player_state['money']}** "
            f"(Net Worth: **${self.game.get_player_net_worth(current_player.id)}** | Properties: **{len(player_state['properties'])}**)"
        )
        status_text = f"⏳ **Turn Status:** **{current_player.display_name}**'s turn — Choose an action below (⏱️ Expires <t:{deadline_ts}:R>)"

        self._rolling = False
        self.setup_buttons()
        self.reset_timer()
        await self.send_turn_bundle(interaction.channel, visual_file, action_text, financial_text, status_text)

    async def buy_callback(self, interaction: discord.Interaction):
        current_player = self.game.get_current_player()
        if interaction.user.id != current_player.id:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        player_state = self.game.get_player_state(current_player.id)
        pos = player_state["position"]
        tile = self.game.board[pos]

        # Double-click guard
        if self._buying:
            await interaction.response.send_message("Purchase already in progress!", ephemeral=True)
            return
        # Verify property is still available
        if pos in self.game.properties_owned:
            await interaction.response.send_message(f"**{tile['name']}** is already owned!", ephemeral=True)
            return
        if player_state["money"] < tile["price"]:
            await interaction.response.send_message(f"You don't have enough money to buy {tile['name']} (${tile['price']})!", ephemeral=True)
            return

        self._buying = True
        self.game.record_activity()
        await interaction.response.defer()
        self.game.buy_property(current_player.id, pos)

        buf = await asyncio.to_thread(render_board_image, self.game)
        visual_file = discord.File(buf, filename="monopoly_board.png")
        deadline_ts = int(time.time()) + 90

        action_text = f"🏠 **Property Purchased!** **{current_player.display_name}** bought **{tile['name']}** for **${tile['price']}**!"
        financial_text = f"💰 **Financial Summary:** Spent **${tile['price']}** | Cash Remaining: **${player_state['money']}**"
        status_text = f"⏳ **Turn Status:** **{current_player.display_name}**'s turn (⏱️ Expires <t:{deadline_ts}:R>)"

        self._buying = False
        self.setup_buttons()
        self.reset_timer()
        await self.send_turn_bundle(interaction.channel, visual_file, action_text, financial_text, status_text)

    async def decline_callback(self, interaction: discord.Interaction):
        """Starts an auction among the other active players for the declined property."""
        current_player = self.game.get_current_player()
        if interaction.user.id != current_player.id:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        player_state = self.game.get_player_state(current_player.id)
        pos = player_state["position"]
        tile = self.game.board[pos]

        if pos in self.game.properties_owned:
            await interaction.response.send_message("This property is already owned!", ephemeral=True)
            return

        self.game.record_activity()
        await interaction.response.defer()

        self.game.log_event(f"🏛️ {current_player.display_name} declined to buy {tile['name']}. Starting auction!")

        # Refresh turn view without the buy/decline buttons
        self.setup_buttons()
        # Remove buy/decline buttons from the current turn view
        self.clear_items()
        has_monopolies = any(self.game.has_monopoly(current_player.id, color) for color in COLOR_LABELS)
        if has_monopolies:
            build_btn = discord.ui.Button(label="🏗️ Build House", style=discord.ButtonStyle.primary, custom_id="build")
            build_btn.callback = self.build_callback
            self.add_item(build_btn)

        end_btn = discord.ui.Button(label="⏩ End Turn", style=discord.ButtonStyle.red, custom_id="end")
        end_btn.callback = self.end_callback
        self.add_item(end_btn)

        board_btn = discord.ui.Button(label="📋 View Board", style=discord.ButtonStyle.grey, custom_id="board")
        board_btn.callback = self.board_callback
        self.add_item(board_btn)

        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

        # Spawn Auction View in channel
        auction_view = AuctionView(self.game, interaction.channel_id, pos, current_player.id, self)
        auc_msg = await interaction.channel.send(content=auction_view.build_auction_text(), view=auction_view)
        auction_view.message = auc_msg

    async def build_callback(self, interaction: discord.Interaction):
        current_player = self.game.get_current_player()
        if interaction.user.id != current_player.id:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        player_state = self.game.get_player_state(current_player.id)
        buildable = [p for p in player_state["properties"] if self.game.has_monopoly(current_player.id, self.game.board[p].get("color", "")) and self.game.board[p]["houses"] < 5]

        if not buildable:
            await interaction.response.send_message("You don't have any complete monopoly properties to build on!", ephemeral=True)
            return

        pos = buildable[0]
        tile = self.game.board[pos]
        if player_state["money"] < tile["house_price"]:
            await interaction.response.send_message(f"Not enough cash to build on {tile['name']} (${tile['house_price']})!", ephemeral=True)
            return

        self.game.record_activity()
        await interaction.response.defer()
        self.game.build_house(current_player.id, pos)

        buf = await asyncio.to_thread(render_board_image, self.game)
        visual_file = discord.File(buf, filename="monopoly_board.png")
        deadline_ts = int(time.time()) + 90

        action_text = f"🏗️ **Construction Complete!** Built house/skyscraper on **{tile['name']}** for **${tile['house_price']}**!"
        financial_text = f"💰 **Financial Summary:** Spent **${tile['house_price']}** | Cash Remaining: **${player_state['money']}**"
        status_text = f"⏳ **Turn Status:** **{current_player.display_name}**'s turn (⏱️ Expires <t:{deadline_ts}:R>)"

        self.setup_buttons()
        self.reset_timer()
        await self.send_turn_bundle(interaction.channel, visual_file, action_text, financial_text, status_text)

    async def mortgage_callback(self, interaction: discord.Interaction):
        current_player = self.game.get_current_player()
        if interaction.user.id != current_player.id:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        player_state = self.game.get_player_state(current_player.id)
        unmortgaged = [p for p in player_state["properties"] if not self.game.board[p].get("is_mortgaged", False)]
        if not unmortgaged:
            await interaction.response.send_message("You have no eligible properties to mortgage!", ephemeral=True)
            return

        self.game.record_activity()
        await interaction.response.defer()
        pos = unmortgaged[0]
        self.game.mortgage_property(current_player.id, pos)
        tile = self.game.board[pos]

        buf = await asyncio.to_thread(render_board_image, self.game)
        visual_file = discord.File(buf, filename="monopoly_board.png")
        deadline_ts = int(time.time()) + 90

        action_text = f"🏦 **Property Mortgaged:** Mortgaged **{tile['name']}** and received **${tile['price'] // 2}**!"
        financial_text = f"💰 **Financial Summary:** Cash Balance: **${player_state['money']}**"
        status_text = f"⏳ **Turn Status:** **{current_player.display_name}**'s turn (⏱️ Expires <t:{deadline_ts}:R>)"

        self.setup_buttons()
        self.reset_timer()
        await self.send_turn_bundle(interaction.channel, visual_file, action_text, financial_text, status_text)

    async def unmortgage_callback(self, interaction: discord.Interaction):
        current_player = self.game.get_current_player()
        if interaction.user.id != current_player.id:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        player_state = self.game.get_player_state(current_player.id)
        mortgaged = [p for p in player_state["properties"] if self.game.board[p].get("is_mortgaged", False)]
        if not mortgaged:
            await interaction.response.send_message("You have no mortgaged properties to unmortgage!", ephemeral=True)
            return

        pos = mortgaged[0]
        tile = self.game.board[pos]
        cost = int((tile["price"] // 2) * 1.10)
        if player_state["money"] < cost:
            await interaction.response.send_message(f"You need ${cost} to unmortgage {tile['name']}!", ephemeral=True)
            return

        self.game.record_activity()
        await interaction.response.defer()
        self.game.unmortgage_property(current_player.id, pos)

        buf = await asyncio.to_thread(render_board_image, self.game)
        visual_file = discord.File(buf, filename="monopoly_board.png")
        deadline_ts = int(time.time()) + 90

        action_text = f"🔓 **Property Unmortgaged:** Unmortgaged **{tile['name']}** for **${cost}**!"
        financial_text = f"💰 **Financial Summary:** Cash Balance: **${player_state['money']}**"
        status_text = f"⏳ **Turn Status:** **{current_player.display_name}**'s turn (⏱️ Expires <t:{deadline_ts}:R>)"

        self.setup_buttons()
        self.reset_timer()
        await self.send_turn_bundle(interaction.channel, visual_file, action_text, financial_text, status_text)

    async def sell_house_callback(self, interaction: discord.Interaction):
        current_player = self.game.get_current_player()
        if interaction.user.id != current_player.id:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        player_state = self.game.get_player_state(current_player.id)
        houses = [p for p in player_state["properties"] if self.game.board[p].get("houses", 0) > 0]
        if not houses:
            await interaction.response.send_message("You have no houses to sell!", ephemeral=True)
            return

        self.game.record_activity()
        await interaction.response.defer()
        pos = houses[0]
        self.game.sell_house(current_player.id, pos)
        tile = self.game.board[pos]

        buf = await asyncio.to_thread(render_board_image, self.game)
        visual_file = discord.File(buf, filename="monopoly_board.png")
        deadline_ts = int(time.time()) + 90

        action_text = f"🏷️ **House Sold:** Sold house on **{tile['name']}** for **${tile['house_price'] // 2}**."
        financial_text = f"💰 **Financial Summary:** Cash Balance: **${player_state['money']}**"
        status_text = f"⏳ **Turn Status:** **{current_player.display_name}**'s turn (⏱️ Expires <t:{deadline_ts}:R>)"

        self.setup_buttons()
        self.reset_timer()
        await self.send_turn_bundle(interaction.channel, visual_file, action_text, financial_text, status_text)

    async def bail_callback(self, interaction: discord.Interaction):
        current_player = self.game.get_current_player()
        if interaction.user.id != current_player.id:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        if not self.game.pay_jail_bail(current_player.id):
            await interaction.response.send_message("You need $50 to pay bail!", ephemeral=True)
            return

        self.game.record_activity()
        await interaction.response.defer()
        
        # Lightweight update — token position and board appearance remain unchanged on bail
        self.setup_buttons()
        self.reset_timer()
        deadline_ts = int(time.time()) + 90
        
        action_text = "💳 **Bail Paid:** Escaped Border Control! You are now free to roll."
        financial_text = f"💰 **Financial Summary:** Cash Balance: **${self.game.players[current_player.id]['money']}**"
        status_text = f"⏳ **Turn Status:** **{current_player.display_name}**'s turn — Roll the dice! (⏱️ Expires <t:{deadline_ts}:R>)"
        
        if self.message:
            try:
                await self.message.edit(content=f"{action_text}\n{financial_text}\n{status_text}", view=self)
            except Exception:
                pass
        else:
            await interaction.channel.send(content=f"{action_text}\n{financial_text}\n{status_text}", view=self)

    async def doubles_callback(self, interaction: discord.Interaction):
        current_player = self.game.get_current_player()
        if interaction.user.id != current_player.id:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        self.game.record_activity()
        await interaction.response.defer()
        d1, d2, escaped = self.game.attempt_jail_doubles(current_player.id)
        deadline_ts = int(time.time()) + 90

        if escaped:
            anim_buf = await asyncio.to_thread(render_board_movement_animation, self.game, current_player.id, 10, self.game.players[current_player.id]["position"])
            visual_file = discord.File(anim_buf, filename="monopoly_move.gif")
            action_text = f"🎲 **DOUBLES ROLLED [{d1}, {d2}]!** Escaped Border Control and moved forward!"
        else:
            buf = await asyncio.to_thread(render_board_image, self.game)
            visual_file = discord.File(buf, filename="monopoly_board.png")
            action_text = f"🎲 Rolled **[{d1}, {d2}]** (No doubles). Remain held in Border Control."

        player_state = self.game.get_player_state(current_player.id)
        financial_text = f"💰 **Financial Summary:** Cash Balance: **${player_state['money']}**"
        status_text = f"⏳ **Turn Status:** **{current_player.display_name}**'s turn (⏱️ Expires <t:{deadline_ts}:R>)"

        self.setup_buttons()
        self.reset_timer()
        await self.send_turn_bundle(interaction.channel, visual_file, action_text, financial_text, status_text)

    async def jail_card_callback(self, interaction: discord.Interaction):
        current_player = self.game.get_current_player()
        if interaction.user.id != current_player.id:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        self.game.record_activity()
        await interaction.response.defer()
        self.game.use_jail_card(current_player.id)

        # Lightweight update — token position and board appearance remain unchanged
        self.setup_buttons()
        self.reset_timer()
        deadline_ts = int(time.time()) + 90
        
        action_text = "🎟️ **Diplomatic Pass Used:** Diplomatic immunity granted! You are now free to roll."
        player_state = self.game.get_player_state(current_player.id)
        financial_text = f"💰 **Financial Summary:** Cash Balance: **${player_state['money']}**"
        status_text = f"⏳ **Turn Status:** **{current_player.display_name}**'s turn — Roll the dice! (⏱️ Expires <t:{deadline_ts}:R>)"

        if self.message:
            try:
                await self.message.edit(content=f"{action_text}\n{financial_text}\n{status_text}", view=self)
            except Exception:
                pass
        else:
            await interaction.channel.send(content=f"{action_text}\n{financial_text}\n{status_text}", view=self)

    async def bankruptcy_callback(self, interaction: discord.Interaction):
        current_player = self.game.get_current_player()
        if interaction.user.id != current_player.id:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        self.game.record_activity()
        await interaction.response.defer()
        self.game.declare_bankruptcy(current_player.id)
        active_players = [p for p in self.game.player_list if not self.game.players[p.id]["bankrupt"]]

        if len(active_players) == 1:
            winner = active_players[0]
            record_game_win(winner.id, [p.id for p in self.game.player_list])
            if self.channel_id in active_games:
                del active_games[self.channel_id]
            self.stop()
            await interaction.channel.send(
                f"🏆 **GAME OVER — VICTORY!**\n🎉 **{winner.mention}** is the sole surviving Monopoly Tycoon and wins the game!"
            )
            return

        self.game.next_turn()
        next_player = self.game.get_current_player()
        deadline_ts = int(time.time()) + 90

        buf = await asyncio.to_thread(render_board_image, self.game)
        visual_file = discord.File(buf, filename="monopoly_board.png")

        action_text = f"💥 **Bankruptcy Declared:** **{current_player.display_name}** has surrendered all assets and was eliminated!"
        financial_text = f"💰 **Player Balances:**\n{format_scorecard_lines(self.game)}"
        status_text = f"⏳ **Turn Status:** It is now **{next_player.display_name}**'s turn! (⏱️ Expires <t:{deadline_ts}:R>)"

        self.setup_buttons()
        self.reset_timer()
        await self.send_turn_bundle(interaction.channel, visual_file, action_text, financial_text, status_text)

    async def end_callback(self, interaction: discord.Interaction):
        current_player = self.game.get_current_player()
        if interaction.user.id != current_player.id:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        player_state = self.game.get_player_state(current_player.id)
        if player_state["money"] < 0:
            await interaction.response.send_message("⚠️ You have a negative cash balance! Mortgage properties, sell houses, trade, or declare bankruptcy before ending your turn.", ephemeral=True)
            return

        self.game.record_activity()
        await interaction.response.defer()
        self.game.next_turn()
        next_player = self.game.get_current_player()
        deadline_ts = int(time.time()) + 90

        buf = await asyncio.to_thread(render_board_image, self.game)
        visual_file = discord.File(buf, filename="monopoly_board.png")

        event_announcement = ""
        if getattr(self.game, "_just_triggered_event", None):
            ev = self.game._just_triggered_event
            event_announcement = f"\n🌍 **NEW WORLD EVENT:** {ev['title']} — {ev['description']}!"
        elif getattr(self.game, "_just_expired_event", None):
            exp = self.game._just_expired_event
            event_announcement = f"\n📰 **World Event Expired:** {exp['title']} has concluded."

        action_text = (
            f"⏩ **Turn Ended:** **{current_player.display_name}** finished their turn.{event_announcement}\n"
            f"🎲 **It is now {next_player.mention}'s turn!**"
        )
        financial_text = f"💰 **Player Balances:**\n{format_scorecard_lines(self.game)}"
        status_text = f"⏳ **Turn Status:** **{next_player.display_name}**'s turn — Roll the dice! (⏱️ Expires <t:{deadline_ts}:R>)"

        self.setup_buttons()
        self.reset_timer()
        await self.send_turn_bundle(interaction.channel, visual_file, action_text, financial_text, status_text)

    async def board_callback(self, interaction: discord.Interaction):
        # Only active players in this game may request the board
        player_ids = [p.id for p in self.game.player_list]
        if interaction.user.id not in player_ids:
            await interaction.response.send_message("Only players in this game can view the board!", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        # Run heavy PIL rendering off the event loop to keep the bot responsive
        buf = await asyncio.to_thread(render_board_image, self.game)
        file = discord.File(buf, filename="monopoly_board.png")
        await interaction.followup.send(content="📋 **Current Monopoly Board State:**", file=file, ephemeral=True)


intents = discord.Intents.default()
intents.message_content = True
intents.members = True

def get_prefix(bot, message):
    prefixes = ["ms!", "!"]
    content = message.content or ""
    content_lower = content.lower()
    matched = []
    for p in prefixes:
        if content_lower.startswith(p):
            # Return prefix preserving exact case from user message
            matched.append(content[:len(p)])
    if bot.user:
        return commands.when_mentioned_or(*(matched or prefixes))(bot, message)
    return matched or prefixes

bot = commands.Bot(command_prefix=get_prefix, case_insensitive=True, intents=intents, help_command=None)

active_games = {}
pending_lobbies = {}

async def launch_monopoly_game(channel, players: list[discord.Member]):
    """Initializes and launches a new active Monopoly match with board rendering and player scorecards."""
    board = generate_random_country_board()
    game = MonopolyGame(players, board=board)
    active_games[channel.id] = game

    # Apply daily bonus cash buffers to starting balances if claimed
    for p in players:
        st = get_player_stats(p.id, p.display_name)
        if st.get("bonus_cash", 0) > 0:
            game.players[p.id]["money"] += st["bonus_cash"]
            st["bonus_cash"] = 0

    first_player = game.get_current_player()
    player_mentions = ", ".join(p.mention for p in players)
    deadline_ts = int(time.time()) + 90

    view = TurnView(game, channel.id)
    buf = await asyncio.to_thread(render_board_image, game)
    visual_file = discord.File(buf, filename="monopoly_board.png")

    action_text = (
        f"🌍 **Mutseri's World Monopoly Started!**\n"
        f"A unique randomized world board has been generated!\n"
        f"**Players:** {player_mentions}\n\n"
        f"🎲 **{first_player.mention}** goes first!"
    )
    financial_text = f"💰 **Player Balances:**\n{format_scorecard_lines(game)}"
    status_text = f"⏳ **Turn Status:** **{first_player.display_name}**'s turn! (⏱️ Expires <t:{deadline_ts}:R>)"

    await view.send_turn_bundle(channel, visual_file, action_text, financial_text, status_text)


class MatchLobbyView(discord.ui.View):
    def __init__(self, host: discord.Member, opponents: list[discord.Member], channel_id: int):
        super().__init__(timeout=60.0)  # 60-second lobby response limit
        self.host = host
        self.opponents = opponents
        self.all_players = [host] + opponents
        self.channel_id = channel_id
        self.accepted_ids = {host.id}
        self.message: discord.Message | None = None

    def build_lobby_text(self) -> str:
        lines = [f"• {self.host.mention} 👑 **Host** (Ready)"]
        for opp in self.opponents:
            if opp.id in self.accepted_ids:
                lines.append(f"• {opp.mention} ✅ **Accepted**")
            else:
                lines.append(f"• {opp.mention} ⏳ *Waiting for response...*")

        count = len(self.accepted_ids)
        total = len(self.all_players)
        return (
            f"🎲 **Monopoly Match Invitation** (⏱️ 60s limit)\n"
            f"**Host:** {self.host.mention} has challenged you to a game of World Monopoly!\n\n"
            f"👥 **Players ({count}/{total} ready):**\n"
            + "\n".join(lines) + "\n\n"
            f"*All invited opponents must click **Accept Match** below to start!*"
        )

    def disable_all_items(self):
        for item in self.children:
            item.disabled = True

    async def on_timeout(self):
        if self.channel_id in pending_lobbies and pending_lobbies.get(self.channel_id) == self:
            del pending_lobbies[self.channel_id]
        self.disable_all_items()
        if self.message:
            try:
                await self.message.edit(
                    content="⏱️ **Match Invitation Expired (60s)**. Not all players accepted in time.",
                    view=self
                )
            except Exception:
                pass

    @discord.ui.button(label="⚔️ Accept Match", style=discord.ButtonStyle.green, custom_id="lobby_accept")
    async def accept_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in [p.id for p in self.all_players]:
            await interaction.response.send_message("You were not invited to this match!", ephemeral=True)
            return

        if interaction.user.id in self.accepted_ids:
            await interaction.response.send_message("You have already accepted this match!", ephemeral=True)
            return

        self.accepted_ids.add(interaction.user.id)

        # Check if all players have accepted
        if len(self.accepted_ids) == len(self.all_players):
            if self.channel_id in pending_lobbies:
                del pending_lobbies[self.channel_id]
            self.disable_all_items()
            self.stop()
            await interaction.response.edit_message(
                content=f"🎉 **All players accepted!** Initializing Monopoly match...\n\n{self.build_lobby_text()}",
                view=self
            )
            channel = bot.get_channel(self.channel_id)
            if channel:
                await launch_monopoly_game(channel, self.all_players)
        else:
            await interaction.response.edit_message(content=self.build_lobby_text(), view=self)

    @discord.ui.button(label="❌ Decline", style=discord.ButtonStyle.red, custom_id="lobby_decline")
    async def decline_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in [p.id for p in self.all_players]:
            await interaction.response.send_message("You are not part of this match invite!", ephemeral=True)
            return

        if self.channel_id in pending_lobbies:
            del pending_lobbies[self.channel_id]

        self.disable_all_items()
        self.stop()

        if interaction.user.id == self.host.id:
            msg = f"🛑 **Match Cancelled:** The match invitation was cancelled by host {self.host.mention}."
        else:
            msg = f"❌ **Match Declined:** {interaction.user.mention} declined the match invitation. Game cancelled."

        await interaction.response.edit_message(content=msg, view=self)


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    print('------')

MIN_PLAYERS = 2
MAX_FREE_PLAYERS = 4

@bot.command(name="start_monopoly", aliases=["sm", "start", "monopoly"])
async def start_monopoly(ctx, *opponents: discord.Member):
    if ctx.channel.id in active_games:
        await ctx.send("A game is already running in this channel!")
        return

    if ctx.channel.id in pending_lobbies:
        await ctx.send("A match invitation is already waiting for player responses in this channel! Please accept, decline, or wait for it to expire.")
        return

    if not opponents:
        await ctx.send("Please mention 1 to 3 opponents to play! Example: `!sm @User1 @User2`")
        return

    if any(opp.bot for opp in opponents):
        await ctx.send("You cannot play against a bot!")
        return

    if ctx.author in opponents:
        await ctx.send("You cannot play against yourself!")
        return

    unique_opponents = []
    for opp in opponents:
        if opp not in unique_opponents:
            unique_opponents.append(opp)

    players = [ctx.author] + unique_opponents
    if len(players) < MIN_PLAYERS:
        await ctx.send("You need at least 2 players to start a game!")
        return

    if len(players) > MAX_FREE_PLAYERS:
        await ctx.send(f"Free games support up to {MAX_FREE_PLAYERS} players!")
        return

    lobby_view = MatchLobbyView(ctx.author, unique_opponents, ctx.channel.id)
    pending_lobbies[ctx.channel.id] = lobby_view
    msg = await ctx.send(content=lobby_view.build_lobby_text(), view=lobby_view)
    lobby_view.message = msg

@bot.command(name="trade", aliases=["t"])
async def trade(ctx, target: discord.Member, *, trade_details: str = ""):
    """
    Propose an arbitrary trade deal (money, properties, or mixed) with another player.
    Usage:
      !trade @user Tokyo 100 for London 50
      !trade @user 100 200
      !trade @user offer: Tokyo, $100 req: London, $50
    """
    if ctx.channel.id not in active_games:
        await ctx.send("No active Monopoly game in this channel!")
        return

    game = active_games[ctx.channel.id]
    if ctx.author.id not in game.players or target.id not in game.players:
        await ctx.send("Both players must be active in the current Monopoly game!")
        return

    if ctx.author.id == target.id:
        await ctx.send("You cannot trade with yourself!")
        return

    offer_props, offer_cash, req_props, req_cash, err = parse_trade_args(game, ctx.author.id, target.id, trade_details)
    if err:
        await ctx.send(f"⚠️ {err}")
        return

    sender_state = game.get_player_state(ctx.author.id)
    target_state = game.get_player_state(target.id)

    if sender_state["money"] < offer_cash:
        await ctx.send(f"You don't have enough cash (${offer_cash}) to offer!")
        return
    if target_state["money"] < req_cash:
        await ctx.send(f"{target.display_name} does not have enough cash (${req_cash}) for this request!")
        return

    # Check for properties with houses
    for p in offer_props:
        if game.board[p].get("houses", 0) > 0:
            await ctx.send(f"You cannot trade **{game.board[p]['name']}** while it has houses on it! Sell houses first.")
            return
    for p in req_props:
        if game.board[p].get("houses", 0) > 0:
            await ctx.send(f"Cannot request **{game.board[p]['name']}** while it has houses on it.")
            return

    view = TradeProposalView(game, ctx.author, target, offer_props, offer_cash, req_props, req_cash)

    offer_desc = [f"• 🏠 **{game.board[p]['name']}** (${game.board[p]['price']})" for p in offer_props]
    if offer_cash > 0:
        offer_desc.append(f"• 💰 **${offer_cash} Cash**")

    req_desc = [f"• 🏠 **{game.board[p]['name']}** (${game.board[p]['price']})" for p in req_props]
    if req_cash > 0:
        req_desc.append(f"• 💰 **${req_cash} Cash**")

    proposal_text = (
        f"🤝 **TRADE PROPOSAL** (⏱️ 90s limit)\n"
        f"**From:** {ctx.author.mention} ➔ **To:** {target.mention}\n\n"
        f"📤 **Offered by {ctx.author.display_name}:**\n"
        f"{chr(10).join(offer_desc) if offer_desc else '• Nothing'}\n\n"
        f"📥 **Requested from {target.display_name}:**\n"
        f"{chr(10).join(req_desc) if req_desc else '• Nothing'}\n\n"
        f"{target.mention}, click **Accept Deal**, **Counter-Offer**, or **Decline Deal** below within 90 seconds!"
    )
    msg = await ctx.send(content=proposal_text, view=view)
    view.message = msg

@bot.command(name="property", aliases=["properties", "props", "p"])
async def property_cmd(ctx, member: discord.Member = None):
    """Shows owned properties, mortgaged status, house/skyscraper counts, and current rent."""
    if ctx.channel.id not in active_games:
        await ctx.send("There is no active Monopoly game in this channel!")
        return

    game = active_games[ctx.channel.id]
    target = member or ctx.author
    if target.id not in game.players:
        await ctx.send(f"**{target.display_name}** is not in the active game!")
        return

    props = game.get_player_properties_detail(target.id)
    if not props:
        await ctx.send(f"🏠 **{target.display_name}** does not own any properties yet.")
        return

    lines = []
    total_houses = 0
    total_skyscrapers = 0
    monopolies = set()

    for p in props:
        house_tag = ""
        if p["houses"] == 5:
            house_tag = " | 🏙️ **Skyscraper**"
            total_skyscrapers += 1
        elif p["houses"] > 0:
            house_tag = f" | 🏠 **{p['houses']} Houses**"
            total_houses += p["houses"]

        mort_tag = " | 🔴 **MORTGAGED**" if p["is_mortgaged"] else ""
        color_icon = COLOR_LABELS.get(p.get("color", ""), "📍")
        mono_tag = " ⭐ **Monopoly!**" if p["has_monopoly"] else ""
        if p["has_monopoly"]:
            monopolies.add(p["color"])

        lines.append(f"{color_icon} **{p['name']}** — Rent: **${p['rent']}**{house_tag}{mort_tag}{mono_tag}")

    summary_line = (
        f"📊 **Summary:** {len(props)} Properties | {len(monopolies)} Monopolies | "
        f"{total_houses} Houses | {total_skyscrapers} Skyscrapers"
    )

    msg = (
        f"🏠 **Properties Owned by {target.display_name}** ({len(props)} total):\n"
        + "\n".join(lines) + "\n\n" + summary_line
    )
    await ctx.send(msg)

@bot.command(name="balance", aliases=["bal", "cash", "money"])
async def balance_cmd(ctx, member: discord.Member = None):
    """Shows player's current cash balance, net worth, equity, and status."""
    if ctx.channel.id not in active_games:
        await ctx.send("There is no active Monopoly game in this channel!")
        return

    game = active_games[ctx.channel.id]
    target = member or ctx.author
    if target.id not in game.players:
        await ctx.send(f"**{target.display_name}** is not in the active game!")
        return

    st = game.get_player_state(target.id)
    net_worth = game.get_player_net_worth(target.id)
    tile_name = game.board[st["position"]]["name"]
    jail_status = f"🔒 In Border Control (Turns: {st['jail_turns']})" if st["in_jail"] else "Free"
    passes = st.get("has_jail_card", 0)

    msg = (
        f"💰 **Financial Overview — {target.display_name}**\n"
        f"💵 **Cash Balance:** ${st['money']}\n"
        f"🏠 **Properties Owned:** {len(st['properties'])}\n"
        f"🏦 **Total Net Worth:** ${net_worth}\n"
        f"📍 **Position:** Tile #{st['position']} ({tile_name})\n"
        f"🛂 **Border Control:** {jail_status} | 🎟️ Passes: {passes}"
    )
    await ctx.send(msg)

@bot.command(name="left", aliases=["unowned", "available", "remaining"])
async def left_cmd(ctx):
    """Shows properties still available/unowned on the board."""
    if ctx.channel.id not in active_games:
        await ctx.send("There is no active Monopoly game in this channel!")
        return

    game = active_games[ctx.channel.id]
    unowned = game.get_unowned_properties()

    if not unowned:
        await ctx.send("🗺️ **All properties on the board have been purchased!**")
        return

    # Group unowned by color or type
    groups = {}
    for p in unowned:
        grp = p.get("color") or p.get("type", "other")
        groups.setdefault(grp, []).append(p)

    tier_names = {
        "red": "🔴 Budget Tier",
        "green": "🟢 Mid-Low Tier",
        "light_blue": "🔵 Mid-High Tier",
        "pink": "🩷 Premium Tier",
        "railroad": "✈️ International Airports",
        "utility": "⚡ Global Utilities"
    }

    sections = []
    for grp_key, items in groups.items():
        title = tier_names.get(grp_key, f"📍 {grp_key.title()}")
        item_lines = [f" • **{item['name']}** — ${item['price']}" for item in items]
        sections.append(f"**{title}** ({len(items)} available):\n" + "\n".join(item_lines))

    msg = f"🗺️ **Available Properties on Board ({len(unowned)} remaining):**\n\n" + "\n\n".join(sections)
    await ctx.send(msg)

@bot.command(name="daily", aliases=["d"])
async def daily(ctx):
    """Claims daily reward cash and streak bonuses."""
    success, msg, reward = claim_daily(ctx.author.id, ctx.author.display_name)
    await ctx.send(f"🎡 **Daily Monopoly Reward:**\n{msg}")

@bot.command(name="stats", aliases=["s"])
async def stats(ctx, member: discord.Member = None):
    """Displays player statistics and career performance."""
    target = member or ctx.author
    st = get_player_stats(target.id, target.display_name)

    played = st.get("games_played", 0)
    wins = st.get("wins", 0)
    win_rate = (wins / played * 100) if played > 0 else 0.0
    token = st.get("custom_token") or "🔴"

    msg = (
        f"📊 **Tycoon Career Stats — {target.display_name}**\n"
        f"• Equipped Token: {token}\n"
        f"• Career Wins: 🏆 {wins}\n"
        f"• Games Played: 🎲 {played}\n"
        f"• Win Rate: 📈 {win_rate:.1f}%\n"
        f"• Daily Streak: 🔥 {st.get('daily_streak', 0)} days\n"
        f"• Bonus Cash Buffer: 💰 ${st.get('bonus_cash', 0)}"
    )
    await ctx.send(msg)

@bot.command(name="leaderboard", aliases=["lb", "top"])
async def leaderboard(ctx):
    """Displays top 10 Monopoly Tycoons on the server."""
    top_players = get_top_leaderboard(10)
    if not top_players:
        await ctx.send("No game history recorded yet!")
        return

    lines = []
    medals = ["🥇", "🥈", "🥉"]
    for i, p in enumerate(top_players):
        rank_icon = medals[i] if i < 3 else f"`#{i+1:02d}`"
        token = p.get("custom_token") or "🎲"
        lines.append(
            f"{rank_icon} {token} **{p.get('display_name', 'Player')}** — 🏆 {p.get('wins', 0)} Wins ({p.get('games_played', 0)} played)"
        )

    await ctx.send(f"🏆 **Server Monopoly Leaderboard:**\n\n" + "\n".join(lines))

@bot.command(name="set_token", aliases=["st", "token"])
async def set_token(ctx, emoji: str):
    """Equips a custom player token emoji."""
    success, msg = set_custom_token(ctx.author.id, ctx.author.display_name, emoji)
    await ctx.send(msg)

@bot.command(name="end_monopoly", aliases=["em", "end", "stop"])
async def end_monopoly(ctx):
    if ctx.channel.id in pending_lobbies:
        lobby = pending_lobbies.pop(ctx.channel.id)
        lobby.stop()
        await ctx.send("🛑 The pending match invitation in this channel has been cancelled.")
        return

    if ctx.channel.id in active_games:
        game = active_games.pop(ctx.channel.id)
        if hasattr(game, "current_view") and game.current_view:
            game.current_view.stop()
        await ctx.send("🛑 The Monopoly game in this channel has been ended.")
    else:
        await ctx.send("There is no active Monopoly game or match invitation in this channel.")

@bot.command(name="board", aliases=["b"])
async def board(ctx):
    if ctx.channel.id not in active_games:
        await ctx.send("There is no active Monopoly game in this channel!")
        return
    game = active_games[ctx.channel.id]
    buf = await asyncio.to_thread(render_board_image, game)
    file = discord.File(buf, filename="monopoly_board.png")
    await ctx.send(content="📋 **Live Monopoly Board:**", file=file)

@bot.command(name="help", aliases=["h"])
async def help_command(ctx):
    """Displays a list of all available commands and how to play."""
    help_text = (
        "🌍 **Mutseri's World Monopoly — Command Guide**\n"
        "Prefixes: `!` or `ms!`\n\n"
        "🎮 **Game Controls:**\n"
        "• `!start_monopoly` (`!sm`) @user1 [@user2] — Start a 2–4 player game.\n"
        "• `!board` (`!b`) — View the live 2D board image.\n"
        "• `!end_monopoly` (`!em`) — End the active Monopoly game.\n\n"
        "ℹ️ **Info Commands:**\n"
        "• `!property` (`!p`) [@user] — View owned properties, houses, rent, and mortgaged status.\n"
        "• `!balance` (`!bal`) [@user] — Check cash, net worth, equity, and border control status.\n"
        "• `!left` (`!unowned`) — View remaining available properties on the board.\n\n"
        "🤝 **Trading:**\n"
        "• `!trade` (`!t`) @user [offer] for [request] — Propose a trade (money, property, or mixed).\n"
        "  Examples:\n"
        "  `!trade @user Tokyo 100 for London 50`\n"
        "  `!trade @user 100 200`\n"
        "  `!trade @user offer: Tokyo, $100 req: London, $50`\n\n"
        "💰 **Daily Rewards & Career:**\n"
        "• `!daily` (`!d`) — Claim daily cash + streak bonus.\n"
        "• `!stats` (`!s`) [@user] — View career wins, total games, win rate, and streak.\n"
        "• `!leaderboard` (`!lb`) — View the top server Monopoly Tycoons.\n"
        "• `!set_token` (`!st`) <emoji> — Equip a custom token emoji."
    )
    try:
        await ctx.author.send(help_text)
        if ctx.guild:
            await ctx.send(f"📬 {ctx.author.mention}, I've sent you the command guide in your Direct Messages!")
    except discord.Forbidden:
        await ctx.send(help_text)

# ---------------------------------------------------------------------------
# Keep-alive web server (required by Render; pinged by UptimeRobot)
# ---------------------------------------------------------------------------
async def health_check(request):
    return web.Response(text="Bot is alive!")

async def run_webserver():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Keep-alive server running on port {port}")

async def main():
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN environment variable is not set.")
        return
    await run_webserver()
    await bot.start(token)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return  # Silently ignore unknown commands
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"⚠️ Missing argument: `{error.param.name}`. Use `!help` for command usage.", delete_after=10)
        return
    if isinstance(error, commands.BadArgument):
        await ctx.send(f"⚠️ Invalid argument. Use `!help` for command usage.", delete_after=10)
        return
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Command on cooldown. Try again in **{error.retry_after:.1f}s**.", delete_after=5)
        return
    # Log unexpected errors to console/server logs only — never expose to public chat
    logging.error("Unhandled command error in '%s': %s", ctx.command, error, exc_info=error)
    await ctx.send("⚠️ An internal error occurred while processing this command.", delete_after=10)

if __name__ == "__main__":
    asyncio.run(main())
