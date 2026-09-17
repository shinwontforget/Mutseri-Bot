"""
bot.py - Discord Bot Interface for Territory Wars

Features:
- Commands:
    !start @p1 @p2 [@p3 @p4] (alias: !start_tw)
    !hand
    !territory
    !status
    !board
    !end_tw
    !setprefix <new_prefix>
    !setchannel <#chan1> <#chan2> ... (or 'reset' to allow all)
    !help (detailed 3-message game and command guide)
- Pre-game Closest Guess modal minigame to establish turn order
- Asynchronous PIL rendering via run_in_executor
- Strict deferral pattern: `await interaction.response.defer()` at top of callbacks
- Public channel duels (spectator friendly)
- No embeds for turn flow (board image + plain text messages)
- Strike pardons & auctions
- Proximity Gamble 20-second challenge window
- Channel restrictions and per-guild custom prefix persistence
- Web health check server for cloud hosting
"""

import os
import io
import asyncio
import logging
import discord
from discord.ext import commands
from aiohttp import web
from dotenv import load_dotenv

from game import TerritoryWarsGame, DEFAULT_TURN_CAP
from territories import get_tile, PRE_DEAD_ZONE_POSITIONS, DEAD_ZONE_POSITIONS, NEUTRAL_POSITIONS
from tcg_cards import format_card_line
from duels import create_duel, pick_random_duel_type
from board_renderer import render_board_image_async, render_board_animation_async, PLAYER_NEON_SCHEMES
from stats_db import get_player_stats, record_game_win
import config_manager

load_dotenv()

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("TerritoryWars")

intents = discord.Intents.default()
intents.message_content = True

def get_bot_prefix(bot_instance, message: discord.Message) -> str:
    """Dynamically resolves server-specific command prefix."""
    if not message.guild:
        return "!"
    return config_manager.get_prefix(message.guild.id)

bot = commands.Bot(command_prefix=get_bot_prefix, intents=intents, help_command=None)

# Active games per channel: channel_id -> TerritoryWarsGame
active_games: dict[int, TerritoryWarsGame] = {}


# ---------------------------------------------------------------------------
# Channel Restriction Global Check
# ---------------------------------------------------------------------------
@bot.check
async def check_channel_permission(ctx: commands.Context) -> bool:
    """Ensures commands are only run in allocated channels (if configured)."""
    # Management & help commands always permitted for admins anywhere
    if ctx.command and ctx.command.name in ("setchannel", "setprefix", "help"):
        return True

    if not ctx.guild:
        return True

    if not config_manager.is_channel_allowed(ctx.guild.id, ctx.channel.id):
        allowed_ids = config_manager.get_allowed_channels(ctx.guild.id)
        if allowed_ids:
            mentions = " ".join([f"<#{cid}>" for cid in allowed_ids])
            await ctx.reply(
                f"🚫 **Channel Blocked**: Territory Wars commands can only be played in: {mentions}",
                mention_author=False
            )
            return False
    return True


# ---------------------------------------------------------------------------
# Pre-Game Minigame: Closest Guess
# ---------------------------------------------------------------------------
class GuessModal(discord.ui.Modal, title="Closest Guess (1-100)"):
    guess_input = discord.ui.TextInput(
        label="Enter your guess (1 - 100):",
        placeholder="e.g. 42",
        required=True,
        max_length=3
    )

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        val = self.guess_input.value.strip()
        try:
            guess_int = int(val)
            guess_int = max(1, min(100, guess_int))
        except ValueError:
            guess_int = 50
        await self.callback(interaction.user.id, guess_int, interaction)


class ClosestGuessView(discord.ui.View):
    def __init__(self, players: list, target_num: int, timeout: float = 20.0):
        super().__init__(timeout=timeout)
        self.players = players
        self.player_ids = {p.id for p in players}
        self.target_num = target_num
        self.guesses: dict[int, int] = {}
        self.resolved_future = asyncio.get_running_loop().create_future()

    @discord.ui.button(label="🎯 Enter Guess (1-100)", style=discord.ButtonStyle.primary)
    async def enter_guess(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.player_ids:
            await interaction.response.send_message("Only players in this game may submit a guess!", ephemeral=True)
            return

        if interaction.user.id in self.guesses:
            await interaction.response.send_message(f"You already submitted your guess: **{self.guesses[interaction.user.id]}**!", ephemeral=True)
            return

        async def record_guess(user_id: int, guess: int, modal_interaction: discord.Interaction):
            self.guesses[user_id] = guess
            await modal_interaction.followup.send(f"✅ Your guess **{guess}** has been registered!", ephemeral=True)
            if len(self.guesses) >= len(self.players):
                if not self.resolved_future.done():
                    self.resolved_future.set_result(self.guesses)
                self.stop()

        modal = GuessModal(record_guess)
        await interaction.response.send_modal(modal)

    async def on_timeout(self):
        if not self.resolved_future.done():
            self.resolved_future.set_result(self.guesses)
        self.stop()


# ---------------------------------------------------------------------------
# Turn View: Roll Die & Strike Pardon
# ---------------------------------------------------------------------------
class TurnActionView(discord.ui.View):
    def __init__(self, game: TerritoryWarsGame, player_id: int, channel: discord.TextChannel):
        super().__init__(timeout=90.0)
        self.game = game
        self.player_id = player_id
        self.channel = channel

        can_pardon, _ = game.can_pardon_strike(player_id)
        cost = game.get_pardon_cost(player_id)
        self.pardon_btn.label = f"🏥 Pardon Strike (${cost})"
        self.pardon_btn.disabled = not can_pardon

    @discord.ui.button(label="🎲 Roll Die (1-6)", style=discord.ButtonStyle.primary, custom_id="tw_roll_btn")
    async def roll_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("It is not your turn!", ephemeral=True)
            return

        await interaction.response.defer()
        self.stop()
        for item in self.children:
            item.disabled = True
        try:
            await interaction.edit_original_response(view=self)
        except Exception:
            pass

        await handle_player_roll(self.game, self.player_id, self.channel)

    @discord.ui.button(label="🏥 Pardon Strike", style=discord.ButtonStyle.secondary, custom_id="tw_pardon_btn")
    async def pardon_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("It is not your turn!", ephemeral=True)
            return

        await interaction.response.defer()
        success, new_strikes, next_cost = self.game.pardon_strike(self.player_id)
        if success:
            await self.channel.send(f"🏥 <@{self.player_id}> paid for a Strike Pardon! Remaining strikes: **{new_strikes}** (Next pardon: **${next_cost}**).")
            can_pardon, _ = self.game.can_pardon_strike(self.player_id)
            button.label = f"🏥 Pardon Strike (${next_cost})"
            button.disabled = not can_pardon
            await interaction.edit_original_response(view=self)
        else:
            await interaction.followup.send("Could not purchase pardon.", ephemeral=True)


# ---------------------------------------------------------------------------
# Unowned Property View: Buy vs Auction
# ---------------------------------------------------------------------------
class PropertyDecisionView(discord.ui.View):
    def __init__(self, game: TerritoryWarsGame, player_id: int, pos: int, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.game = game
        self.player_id = player_id
        self.pos = pos
        self.tile = get_tile(pos)
        self.price = self.tile.get("price", 250)
        self.choice = None

        st = game.get_player_state(player_id)
        self.buy_btn.label = f"💵 Buy for ${self.price}"
        if st["money"] < self.price:
            self.buy_btn.disabled = True

    @discord.ui.button(label="💵 Buy", style=discord.ButtonStyle.success)
    async def buy_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("Only the landing player can make this choice!", ephemeral=True)
            return
        await interaction.response.defer()
        self.choice = "BUY"
        self.stop()

    @discord.ui.button(label="🔨 Send to Auction", style=discord.ButtonStyle.secondary)
    async def auction_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("Only the landing player can make this choice!", ephemeral=True)
            return
        await interaction.response.defer()
        self.choice = "AUCTION"
        self.stop()

    async def on_timeout(self):
        if not self.choice:
            self.choice = "AUCTION"
        self.stop()


# ---------------------------------------------------------------------------
# Auction View
# ---------------------------------------------------------------------------
class TerritoryAuctionView(discord.ui.View):
    def __init__(self, game: TerritoryWarsGame, pos: int, starting_bid: int, channel: discord.TextChannel, timeout: float = 15.0):
        super().__init__(timeout=timeout)
        self.game = game
        self.pos = pos
        self.current_bid = starting_bid
        self.current_bidder_id = None
        self.channel = channel
        self.active_player_ids = {p.id for p in game.get_active_players()}

    async def register_bid(self, user_id: int, raise_amount: int, interaction: discord.Interaction):
        st = self.game.get_player_state(user_id)
        new_bid = self.current_bid + raise_amount
        if st["money"] < new_bid:
            await interaction.followup.send(f"Insufficient funds! You have ${st['money']}, bid requires ${new_bid}.", ephemeral=True)
            return

        self.current_bid = new_bid
        self.current_bidder_id = user_id
        self.timeout = 15.0

        tile = get_tile(self.pos)
        await self.channel.send(f"🔨 <@{user_id}> raised bid to **${new_bid}** on **{tile['name']}**! (15s remaining)")

    @discord.ui.button(label="+$25", style=discord.ButtonStyle.primary)
    async def bid_25(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.active_player_ids:
            await interaction.response.send_message("You are not active in this auction!", ephemeral=True)
            return
        await interaction.response.defer()
        await self.register_bid(interaction.user.id, 25, interaction)

    @discord.ui.button(label="+$50", style=discord.ButtonStyle.primary)
    async def bid_50(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.active_player_ids:
            await interaction.response.send_message("You are not active in this auction!", ephemeral=True)
            return
        await interaction.response.defer()
        await self.register_bid(interaction.user.id, 50, interaction)

    @discord.ui.button(label="+$100", style=discord.ButtonStyle.primary)
    async def bid_100(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.active_player_ids:
            await interaction.response.send_message("You are not active in this auction!", ephemeral=True)
            return
        await interaction.response.defer()
        await self.register_bid(interaction.user.id, 100, interaction)

    async def on_timeout(self):
        self.stop()


# ---------------------------------------------------------------------------
# Proximity Gamble View (20s Challenge Window)
# ---------------------------------------------------------------------------
class ProximityGambleView(discord.ui.View):
    def __init__(self, game: TerritoryWarsGame, exposed_player_id: int, timeout: float = 20.0):
        super().__init__(timeout=timeout)
        self.game = game
        self.exposed_player_id = exposed_player_id
        self.challenger_id = None
        self.resolved_future = asyncio.get_running_loop().create_future()

    @discord.ui.button(label="⚔️ Challenge Proximity Gamble!", style=discord.ButtonStyle.danger, custom_id="gamble_btn")
    async def challenge_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        can, reason = self.game.can_initiate_gamble(user_id, self.exposed_player_id)
        if not can:
            await interaction.response.send_message(f"❌ {reason}", ephemeral=True)
            return

        await interaction.response.defer()
        self.challenger_id = user_id
        self.game.record_gamble_attempt(user_id)
        self.stop()
        if not self.resolved_future.done():
            self.resolved_future.set_result(user_id)

    async def on_timeout(self):
        if not self.resolved_future.done():
            self.resolved_future.set_result(None)
        self.stop()


# ---------------------------------------------------------------------------
# Discard Card View (when hand > 5)
# ---------------------------------------------------------------------------
class DiscardCardView(discord.ui.View):
    def __init__(self, game: TerritoryWarsGame, player_id: int, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.game = game
        self.player_id = player_id
        st = game.get_player_state(player_id)

        options = []
        for c in st["cards"]:
            options.append(discord.SelectOption(
                label=f"{c['name']} ({c['stat'].capitalize()} +{c['value']})",
                value=c["id"],
                description=f"Discard {c['name']}"
            ))

        select = discord.ui.Select(placeholder="Hand limit 5 exceeded! Choose a card to discard:", options=options[:25])
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        card_id = self.children[0].values[0]
        self.game.remove_card_from_player(self.player_id, card_id)
        await interaction.followup.send("🗑️ Card discarded.", ephemeral=True)
        self.stop()


# ---------------------------------------------------------------------------
# Turn Progression & Roll Execution
# ---------------------------------------------------------------------------
async def handle_player_roll(game: TerritoryWarsGame, player_id: int, channel: discord.TextChannel):
    """Executes the complete turn flow for the player's roll."""
    st = game.get_player_state(player_id)
    p_name = st["member"].display_name
    old_pos = st["position"]

    roll = game.roll_dice()
    move_info = game.move_player(player_id, roll)
    new_pos = move_info["new_pos"]
    tile = move_info["tile"]

    # 1. Post movement board animation
    anim_buf = await render_board_animation_async(game, player_id, old_pos, new_pos)
    anim_file = discord.File(anim_buf, filename="tw_move.gif")
    await channel.send(
        f"🎲 **{p_name}** rolled a **{roll}** and stepped to Tile {new_pos}: **{tile['name']}**!",
        file=anim_file
    )

    # 2. Check START pass
    if move_info["passed_start"]:
        pass_msg = f"🚩 **{p_name}** passed START! Received **+${move_info['start_payout']}** and drawn TCG Card: `{move_info['drawn_card']['title']}`."
        await channel.send(pass_msg)
        if move_info["needs_discard"]:
            d_view = DiscardCardView(game, player_id)
            await channel.send(f"<@{player_id}> Your hand exceeds 5 cards! Choose a card to discard:", view=d_view)

    # 3. Check Proximity Gamble (ends move 1 tile before Dead Zone)
    if move_info["is_pre_dead_zone"]:
        await channel.send(
            f"⚠️ **PROXIMITY GAMBLE OPPORTUNITY!** ⚠️\n"
            f"**{p_name}** ended their move 1 tile before a DEAD ZONE (Tile {new_pos})!\n"
            f"Any active rival has **20 seconds** to challenge them to a gamble duel!\n"
            f"*(Challenger wins ➔ Exposed gains strike | Defender wins ➔ Challenger gains strike)*"
        )
        gamble_view = ProximityGambleView(game, player_id)
        g_msg = await channel.send(view=gamble_view)

        challenger_id = await gamble_view.resolved_future
        if challenger_id:
            ch_st = game.get_player_state(challenger_id)
            await channel.send(f"⚔️ **PROXIMITY GAMBLE CLAIMED!** <@{challenger_id}> ({ch_st['member'].display_name}) challenges <@{player_id}> ({p_name})!")
            duel_type = pick_random_duel_type(ch_st["cards"], st["cards"])
            d_view, d_prompt = create_duel(duel_type, challenger_id, player_id, new_pos, ch_st["cards"], st["cards"])
            d_msg = await channel.send(d_prompt, view=d_view)

            if hasattr(d_view, "start_countdown"):
                asyncio.create_task(d_view.start_countdown(d_msg))
            elif hasattr(d_view, "start_flash"):
                asyncio.create_task(d_view.start_flash(d_msg))

            duel_res = await d_view.resolved_future
            await channel.send(duel_res.summary)

            for pid, card_ids in duel_res.consumed_cards.items():
                for cid in card_ids:
                    game.remove_card_from_player(pid, cid)

            if duel_res.loser_id:
                new_strikes, is_elim = game.add_strike(duel_res.loser_id)
                await channel.send(f"🚨 <@{duel_res.loser_id}> gained a STRIKE! Strikes: **{new_strikes}/3**{' 💀 ELIMINATED!' if is_elim else ''}")

                if duel_res.loser_id == player_id and is_elim:
                    await check_and_advance_turn(game, channel)
                    return

    # 4. Resolve landed tile action
    if tile["type"] == "dead_zone":
        new_strikes, is_elim = game.add_strike(player_id)
        await channel.send(
            f"☠️ **DEAD ZONE!** <@{player_id}> landed on **{tile['name']}** and received +1 STRIKE!\n"
            f"Current strikes: **{new_strikes}/3**{' 💀 ELIMINATED!' if is_elim else ''}"
        )

    elif tile["type"] == "neutral":
        card, needs_discard = game.add_card_to_player(player_id)
        await channel.send(f"🎴 **{p_name}** visited {tile['name']} and drew TCG Card: `{card['title']}`!")
        if needs_discard:
            d_view = DiscardCardView(game, player_id)
            await channel.send(f"<@{player_id}> Your hand exceeds 5 cards! Choose a card to discard:", view=d_view)

    elif tile["type"] == "property":
        owner_id = game.properties_owned.get(new_pos)

        if owner_id is None:
            dec_view = PropertyDecisionView(game, player_id, new_pos)
            await channel.send(
                f"🏛️ **{p_name}** landed on unowned territory **{tile['name']}, {tile['country']}**!\n"
                f"Price: **${tile.get('price', 250)}** | Stats: Climate **{tile['stats']['climate']}**, Terrain **{tile['stats']['terrain']}**, Economy **{tile['stats']['economy']}**.",
                view=dec_view
            )
            await dec_view.wait()

            if dec_view.choice == "BUY":
                bought = game.buy_property(player_id, new_pos)
                if bought:
                    await channel.send(f"🏛️ <@{player_id}> bought **{tile['name']}** for **${tile.get('price', 250)}**!")
                else:
                    await channel.send("Could not complete purchase. Sending to auction!")
                    await run_auction(game, new_pos, channel)
            else:
                await run_auction(game, new_pos, channel)

        elif owner_id == player_id:
            await channel.send(f"🛡️ **{p_name}** inspected their own territory **{tile['name']}**. All quiet.")

        else:
            owner_st = game.get_player_state(owner_id)
            await channel.send(
                f"⚔️ **TERRITORY CONQUEST DUEL!**\n"
                f"<@{player_id}> ({p_name}) invaded <@{owner_id}>'s ({owner_st['member'].display_name}) territory **{tile['name']}**!\n"
                f"NO RENT is paid! The winner takes/retains ownership of the territory!"
            )
            duel_type = pick_random_duel_type(st["cards"], owner_st["cards"])
            d_view, d_prompt = create_duel(duel_type, player_id, owner_id, new_pos, st["cards"], owner_st["cards"])
            d_msg = await channel.send(d_prompt, view=d_view)

            if hasattr(d_view, "start_countdown"):
                asyncio.create_task(d_view.start_countdown(d_msg))
            elif hasattr(d_view, "start_flash"):
                asyncio.create_task(d_view.start_flash(d_msg))

            duel_res = await d_view.resolved_future
            await channel.send(duel_res.summary)

            for pid, card_ids in duel_res.consumed_cards.items():
                for cid in card_ids:
                    game.remove_card_from_player(pid, cid)

            if duel_res.winner_id == player_id:
                game.transfer_property(owner_id, player_id, new_pos)
                await channel.send(f"🚩 **CONQUEST!** <@{player_id}> seized ownership of **{tile['name']}** from <@{owner_id}>!")
            else:
                await channel.send(f"🛡️ **DEFENSE!** <@{owner_id}> successfully defended and retains **{tile['name']}**!")

    # Advance turn
    await check_and_advance_turn(game, channel)


async def run_auction(game: TerritoryWarsGame, pos: int, channel: discord.TextChannel):
    """Runs a live auction for an unowned property."""
    tile = get_tile(pos)
    start_bid = tile.get("price", 250) // 2
    auc_view = TerritoryAuctionView(game, pos, start_bid, channel)
    await channel.send(
        f"🔨 **TERRITORY AUCTION: {tile['name']}**!\n"
        f"Starting Bid: **${start_bid}**! Click buttons to raise bid (15s timer):",
        view=auc_view
    )
    await auc_view.wait()

    if auc_view.current_bidder_id:
        winner_id = auc_view.current_bidder_id
        final_price = auc_view.current_bid
        w_st = game.get_player_state(winner_id)
        w_st["money"] -= final_price
        w_st["properties"].append(pos)
        game.properties_owned[pos] = winner_id
        game.invalidate_static_cache()
        await channel.send(f"🎉 **AUCTION WON!** <@{winner_id}> won **{tile['name']}** for **${final_price}**!")
    else:
        await channel.send(f"🔨 No bids were placed. **{tile['name']}** remains unowned.")


async def check_and_advance_turn(game: TerritoryWarsGame, channel: discord.TextChannel):
    """Checks game over conditions and starts next player's turn."""
    is_over, outcome = game.check_game_over()
    if is_over:
        winner = outcome["winner"]
        reason = outcome["reason"]
        all_ids = [p.id for p in game.player_list]
        record_game_win(winner.id, all_ids)

        board_buf = await render_board_image_async(game)
        file = discord.File(board_buf, filename="tw_game_over.png")
        await channel.send(
            f"🏆 **GAME OVER — VICTORY!** 🏆\n"
            f"Congratulations to <@{winner.id}> (**{winner.display_name}**)!\n"
            f"{reason}",
            file=file
        )
        if channel.id in active_games:
            del active_games[channel.id]
        return

    game.next_turn()
    next_player = game.get_current_player()
    st = game.get_player_state(next_player.id)

    board_buf = await render_board_image_async(game)
    board_file = discord.File(board_buf, filename="tw_board.png")

    view = TurnActionView(game, next_player.id, channel)
    await channel.send(
        f"🎯 **Round {game.round_count}/{DEFAULT_TURN_CAP}** — It is <@{next_player.id}>'s turn! (Cash: **${st['money']}** | Strikes: **{st['strikes']}/3**)",
        file=board_file,
        view=view
    )


# ---------------------------------------------------------------------------
# Bot Commands
# ---------------------------------------------------------------------------
@bot.command(name="start", aliases=["start_tw"])
async def cmd_start(ctx: commands.Context):
    """
    !start @p1 @p2 [@p3 @p4] - Starts a Territory Wars game (alias: !start_tw).
    Runs Closest Guess pre-game minigame to establish turn order.
    """
    if ctx.channel.id in active_games:
        prefix = config_manager.get_prefix(ctx.guild.id if ctx.guild else None)
        await ctx.send(f"⚠️ A game is already active in this channel! Use `{prefix}end_tw` to end it.")
        return

    players = list(ctx.message.mentions)
    if ctx.author not in players:
        players.insert(0, ctx.author)

    unique_players = []
    for p in players:
        if p not in unique_players and not p.bot:
            unique_players.append(p)

    prefix = config_manager.get_prefix(ctx.guild.id if ctx.guild else None)
    if len(unique_players) < 2:
        await ctx.send(f"❌ Territory Wars requires at least 2 human players! Usage: `{prefix}start @player1 @player2`")
        return
    if len(unique_players) > 4:
        await ctx.send("❌ Maximum 4 players per game! Please mention between 2 and 4 players.")
        return

    # Pre-game Closest Guess minigame
    import random
    secret_target = random.randint(1, 100)

    guess_view = ClosestGuessView(unique_players, secret_target)
    player_tags = " ".join([p.mention for p in unique_players])
    await ctx.send(
        f"🎮 **TERRITORY WARS — PRE-GAME TURN ORDER!**\n"
        f"Players: {player_tags}\n"
        f"A secret number between **1 and 100** has been chosen.\n"
        f"Click below and enter your guess within **20 seconds**! Closest guess goes first!",
        view=guess_view
    )

    guesses = await guess_view.resolved_future

    def dist_key(p):
        if p.id in guesses:
            return (0, abs(guesses[p.id] - secret_target))
        return (1, random.random())

    ordered_players = sorted(unique_players, key=dist_key)
    order_announcement = []
    for rank, p in enumerate(ordered_players, 1):
        g_val = guesses.get(p.id, "No submission")
        order_announcement.append(f"**#{rank}** {p.display_name} (Guess: `{g_val}`)")

    await ctx.send(
        f"🎯 **Closest Guess Results!** Target Number was: **{secret_target}**!\n"
        f"**Turn Order:**\n" + "\n".join(order_announcement)
    )

    game = TerritoryWarsGame(ordered_players)
    active_games[ctx.channel.id] = game

    board_buf = await render_board_image_async(game)
    board_file = discord.File(board_buf, filename="tw_start_board.png")

    first_player = game.get_current_player()
    first_view = TurnActionView(game, first_player.id, ctx.channel)
    await ctx.send(
        f"⚔️ **TERRITORY WARS BEGINS!**\n"
        f"Starting Commander: <@{first_player.id}> (**{first_player.display_name}**)!\n"
        f"Roll the die or buy a strike pardon to begin:",
        file=board_file,
        view=first_view
    )


@bot.command(name="hand")
async def cmd_hand(ctx: commands.Context):
    """!hand - View your held TCG cards (ephemeral DM)."""
    game = active_games.get(ctx.channel.id)
    if not game:
        await ctx.reply("No active Territory Wars game in this channel.", mention_author=False)
        return

    st = game.get_player_state(ctx.author.id)
    if not st:
        await ctx.reply("You are not a player in this game.", mention_author=False)
        return

    cards = st["cards"]
    if not cards:
        await ctx.author.send("🃏 Your hand is currently empty.")
        await ctx.reply("📬 Sent your hand details via DM!", mention_author=False)
        return

    lines = [f"🃏 **Your TCG Cards ({len(cards)}/5):**"]
    for c in cards:
        lines.append(format_card_line(c))

    await ctx.author.send("\n".join(lines))
    await ctx.reply("📬 Sent your hand details via DM!", mention_author=False)


@bot.command(name="territory")
async def cmd_territory(ctx: commands.Context):
    """!territory - View your owned territories and stats (ephemeral DM)."""
    game = active_games.get(ctx.channel.id)
    if not game:
        await ctx.reply("No active Territory Wars game in this channel.", mention_author=False)
        return

    st = game.get_player_state(ctx.author.id)
    if not st:
        await ctx.reply("You are not a player in this game.", mention_author=False)
        return

    props = st["properties"]
    if not props:
        await ctx.author.send("🏛️ You currently own 0 territories.")
        await ctx.reply("📬 Sent your territory details via DM!", mention_author=False)
        return

    lines = [f"🏛️ **Your Territories ({len(props)}/14):**"]
    for pos in props:
        t = get_tile(pos)
        stats = t["stats"]
        lines.append(
            f"• **{t['name']}, {t['country']}** (Tile {pos}): "
            f"🌧️ Climate {stats['climate']} | 🏔️ Terrain {stats['terrain']} | 💼 Economy {stats['economy']}"
        )
    lap_income = len(props) * 100
    lines.append(f"\n💰 **Lap Dividend Income:** +${lap_income} each time you pass START!")

    await ctx.author.send("\n".join(lines))
    await ctx.reply("📬 Sent your territory portfolio via DM!", mention_author=False)


@bot.command(name="status")
async def cmd_status(ctx: commands.Context):
    """!status - Public status overview for all players."""
    game = active_games.get(ctx.channel.id)
    if not game:
        await ctx.send("No active Territory Wars game in this channel.")
        return

    lines = [f"📊 **TERRITORY WARS STATUS (Round {game.round_count}/{DEFAULT_TURN_CAP}):**"]
    for i, p in enumerate(game.player_list):
        st = game.get_player_state(p.id)
        scheme = PLAYER_NEON_SCHEMES[i % len(PLAYER_NEON_SCHEMES)]
        elim_tag = " [💀 ELIMINATED]" if st["is_eliminated"] else ""
        strikes_str = "❌ " * st["strikes"] + "⚪ " * (3 - st["strikes"])
        lines.append(
            f"**{scheme['label']}** {p.display_name}: 💰 ${st['money']} | 🏛️ {len(st['properties'])} props | "
            f"🃏 {len(st['cards'])} cards | Strikes: {strikes_str.strip()}{elim_tag}"
        )

    await ctx.send("\n".join(lines))


@bot.command(name="board")
async def cmd_board(ctx: commands.Context):
    """!board - Reposts the current board image."""
    game = active_games.get(ctx.channel.id)
    if not game:
        await ctx.send("No active Territory Wars game in this channel.")
        return

    board_buf = await render_board_image_async(game)
    board_file = discord.File(board_buf, filename="tw_board.png")
    await ctx.send("🗺️ **Current Territory Wars Board:**", file=board_file)


@bot.command(name="end_tw")
async def cmd_end_tw(ctx: commands.Context):
    """!end_tw - Terminate the ongoing game."""
    if ctx.channel.id in active_games:
        del active_games[ctx.channel.id]
        await ctx.send("🛑 The ongoing Territory Wars game has been terminated.")
    else:
        await ctx.send("No active game to terminate.")


# ---------------------------------------------------------------------------
# Server Configuration Commands: !setprefix & !setchannel
# ---------------------------------------------------------------------------
@bot.command(name="setprefix")
async def cmd_setprefix(ctx: commands.Context, new_prefix: str = None):
    """
    !setprefix <prefix> - Sets a custom command prefix for this Discord server.
    Requires Manage Server or Administrator permission.
    """
    if not ctx.guild:
        await ctx.send("Prefixes can only be set inside servers.")
        return

    if not (ctx.author.guild_permissions.manage_guild or ctx.author.guild_permissions.administrator):
        await ctx.reply("❌ You need the **Manage Server** permission to change the bot prefix.", mention_author=False)
        return

    if not new_prefix or len(new_prefix.strip()) == 0:
        current = config_manager.get_prefix(ctx.guild.id)
        await ctx.reply(f"Current server prefix is `{current}`. Usage: `{current}setprefix <new_prefix>`", mention_author=False)
        return

    prefix_cleaned = new_prefix.strip()[:5]  # Limit length to max 5 chars
    config_manager.set_prefix(ctx.guild.id, prefix_cleaned)
    await ctx.reply(
        f"✅ **Prefix Updated!** Server command prefix is now `{prefix_cleaned}`.\n"
        f"Example: `{prefix_cleaned}start @player1 @player2`",
        mention_author=False
    )


@bot.command(name="setchannel")
async def cmd_setchannel(ctx: commands.Context, *args):
    """
    !setchannel <#channel1> <#channel2> ... - Allocates channels for Territory Wars.
    All other channels will be blocked from using game commands.
    Use '!setchannel reset' or '!setchannel all' to allow all channels.
    """
    if not ctx.guild:
        await ctx.send("Channel allocation can only be configured inside servers.")
        return

    if not (ctx.author.guild_permissions.manage_guild or ctx.author.guild_permissions.administrator):
        await ctx.reply("❌ You need the **Manage Server** permission to allocate game channels.", mention_author=False)
        return

    current_prefix = config_manager.get_prefix(ctx.guild.id)

    if not args:
        current_channels = config_manager.get_allowed_channels(ctx.guild.id)
        if not current_channels:
            await ctx.reply(
                f"ℹ️ **No channel restrictions active.** Territory Wars can currently be played in any channel.\n"
                f"To allocate specific channels: `{current_prefix}setchannel #channel1 #channel2`",
                mention_author=False
            )
        else:
            mentions = " ".join([f"<#{cid}>" for cid in current_channels])
            await ctx.reply(
                f"🎮 **Currently Allocated Channels:** {mentions}\n"
                f"All other channels are blocked. Use `{current_prefix}setchannel reset` to unblock all channels.",
                mention_author=False
            )
        return

    # Check for reset keyword
    first_arg = args[0].lower()
    if first_arg in ("reset", "clear", "all", "none"):
        config_manager.set_allowed_channels(ctx.guild.id, [])
        await ctx.reply("🔓 **All channels unblocked!** Territory Wars can now be played anywhere in this server.", mention_author=False)
        return

    # Collect channels from mentions or search by name/ID
    target_channel_ids = []

    # 1. Channel mentions in the message
    for ch in ctx.message.channel_mentions:
        if ch.id not in target_channel_ids:
            target_channel_ids.append(ch.id)

    # 2. Text arguments (names or IDs)
    for arg in args:
        cleaned = arg.strip("<#>").strip()
        if cleaned.isdigit():
            cid = int(cleaned)
            ch = ctx.guild.get_channel(cid)
            if ch and cid not in target_channel_ids:
                target_channel_ids.append(cid)
        else:
            ch = discord.utils.get(ctx.guild.text_channels, name=cleaned.lower())
            if ch and ch.id not in target_channel_ids:
                target_channel_ids.append(ch.id)

    if not target_channel_ids:
        await ctx.reply(
            f"❌ No valid channels found from `{args}`.\n"
            f"Please mention channels directly (e.g. `{current_prefix}setchannel #game-room #bot-spam`) or use channel IDs.",
            mention_author=False
        )
        return

    config_manager.set_allowed_channels(ctx.guild.id, target_channel_ids)
    mentions = " ".join([f"<#{cid}>" for cid in target_channel_ids])
    await ctx.reply(
        f"🔒 **Channel Allocation Successful!**\n"
        f"Territory Wars is now strictly restricted to: {mentions}\n"
        f"All other channels are **blocked** from running game commands.\n"
        f"*(Use `{current_prefix}setchannel reset` anytime to unblock all channels.)*",
        mention_author=False
    )


# ---------------------------------------------------------------------------
# Detailed 3-Message Help Command
# ---------------------------------------------------------------------------
@bot.command(name="help")
async def cmd_help(ctx: commands.Context):
    """!help - Comprehensive 3-message detailed guide to Territory Wars."""
    prefix = config_manager.get_prefix(ctx.guild.id if ctx.guild else None)

    # Message 1: Overview & Board Architecture
    msg1 = (
        f"╔══════════════════════════════════════════════════════════════╗\n"
        f"   🗺️ **TERRITORY WARS — MASTER FIELD GUIDE (Part 1 of 3)**\n"
        f"╚══════════════════════════════════════════════════════════════╝\n\n"
        f"**Territory Wars** is a strategic territory conquest board game built from the ground up.\n"
        f"No rent. No houses. No jail. No luck cards. Only geographic stats, tactical TCG cards, and lethal duels!\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 **OBJECTIVE & WIN CONDITIONS**\n"
        f"• **Strikes System**: Accumulate **3 STRIKES** and you are **ELIMINATED**!\n"
        f"• When eliminated, all your conquered territories are stripped and released back to unowned.\n"
        f"• **Victory**: Last commander standing wins!\n"
        f"• **Round Cap ({DEFAULT_TURN_CAP} Rounds)**: If the round cap is reached, the commander with **fewest strikes** wins.\n"
        f"  *(Ties broken by: Most Territories Owned ➔ Highest Cash Balance)*.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🗺️ **THE 20-TILE PERIMETER BOARD**\n"
        f"The board is a 6x6 perimeter track with exactly 20 tiles:\n\n"
        f"• **Tile 0 (GLOBAL START)**: Passing or landing awards **+$200 cash**, **1 random TCG card**, and **+$100 dividend per territory owned**!\n"
        f"• **Tiles 5 & 15 (DEAD ZONES)**: Symmetrically opposite each other on the loop. Landing immediately adds **+1 STRIKE**!\n"
        f"• **Tiles 7, 10, 12 (NEUTRAL SANCTUARY)**: Safe zones. Landing draws **1 TCG Card** (hand limit: 5).\n"
        f"• **14 Real-World Territories**: Each carries three real-world thematic stats rated 1–10:\n"
        f"  🌧️ **Climate** | 🏔️ **Terrain** | 💼 **Economy**\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ **PROXIMITY GAMBLE — THE SIGNATURE MECHANIC**\n"
        f"• **Tiles 4 & 14** sit exactly 1 tile before the lethal Dead Zones.\n"
        f"• When a commander ends their movement on Tile 4 or 14, a **20-second public challenge window** opens!\n"
        f"• Any active rival can click **'Challenge Proximity Gamble'** (first to click claims it):\n"
        f"  ⚔️ **Challenger Wins** ➔ Exposed player receives a **+1 STRIKE**.\n"
        f"  🛡️ **Defender Wins** ➔ Challenger receives a **+1 STRIKE**.\n"
        f"  ⚖️ **Timeout** ➔ Nothing happens.\n"
        f"• *Symmetric Risk*: Attacking someone near death can backfire and strike you down!\n"
        f"• *Anti-Farming*: A commander cannot initiate a gamble two turns in a row."
    )

    # Message 2: Duels, TCG Cards & Survival Economy
    msg2 = (
        f"╔══════════════════════════════════════════════════════════════╗\n"
        f"   ⚔️ **DUELS, CARDS & ECONOMY (Part 2 of 3)**\n"
        f"╚══════════════════════════════════════════════════════════════╝\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚔️ **TERRITORY CONQUEST DUELS (Zero Rent!)**\n"
        f"Landing on a rival's territory incurs **NO RENT**. Instead, a randomly selected **DUEL** triggers between the lander (Challenger) and owner (Defender).\n"
        f"The winner takes/retains ownership of the contested territory! All duels resolve in under 30s:\n\n"
        f"1. ⚡ **Reaction Duel**: A button appears after a random 2–5s delay. First valid click wins. Clicking early causes instant disqualification!\n"
        f"2. 🧠 **Memory Flash**: An emoji sequence flashes for 3 seconds then vanishes. Both commanders retype it via modal; most accurate wins!\n"
        f"3. 🧮 **Quick Math**: Speed arithmetic problem with 4 options. First correct answer wins; wrong answer disqualifies!\n"
        f"4. 🎯 **Odd One Out**: 4 items shown; first to identify the category outlier wins!\n"
        f"5. 🌍 **Geo Sprint**: Flash geographic trivia about the contested territory's country (hemisphere, coastal/landlocked, size comparison).\n"
        f"6. 🃏 **Stat Duel (TCG)**: Contested stat (Climate, Terrain, Economy) chosen at random. Both play a secret face-down card. Cards reveal simultaneously modifying the stat; higher total wins!\n"
        f"7. 🌀 **Element Clash (TCG)**: Rock-Paper-Scissors cycle:\n"
        f"   **Climate beats Terrain | Terrain beats Economy | Economy beats Climate**\n"
        f"   Both commanders secretly pick an element. Ties are broken by whoever played the higher-value card of that type!\n\n"
        f"⚖️ *Universal Duel Rules*: Exact ties & double timeouts are retained by Defender. Single timeouts award win to other player.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🃏 **TCG BOOST CARDS**\n"
        f"• Awarded when passing START and landing on Neutral tiles.\n"
        f"• Cards represent real-world traits (e.g. *Monsoon Belt +3*, *Alpine Ridge +4*, *Trade Corridor +2*).\n"
        f"• Values range **+1 to +4** (higher values are rarer: 40% +1, 30% +2, 20% +3, 10% +4).\n"
        f"• **Hand Limit: 5**. Drawing a 6th card prompts an immediate discard choice.\n"
        f"• Cards are consumed when played in duels.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 **SURVIVAL ECONOMY & STRIKE PARDONS**\n"
        f"• **Unowned Property Choice**: Lander chooses to **Buy** (fixed price) or send to **Auction** (15s live bidding view for all players).\n"
        f"• **Lap Dividends**: Holding territory funds your survival! Passing START pays **+$200 base + $100 per owned territory**.\n"
        f"• **Strike Pardons**: At any time on your turn, click **'Pardon Strike'** to erase 1 strike!\n"
        f"  Price doubles on each use: **$500 ➔ $1,000 ➔ $2,000 ➔ $4,000...**"
    )

    # Message 3: Commands & Server Management
    msg3 = (
        f"╔══════════════════════════════════════════════════════════════╗\n"
        f"   📜 **COMMAND REFERENCE & SERVER SETTINGS (Part 3 of 3)**\n"
        f"╚══════════════════════════════════════════════════════════════╝\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎮 **GAME COMMANDS**\n"
        f"• `{prefix}start @p1 @p2 [@p3 @p4]`\n"
        f"  Starts a new game for 2 to 4 commanders (alias: `{prefix}start_tw`).\n"
        f"  Runs the **Closest Guess (1-100)** modal minigame to establish turn order!\n\n"
        f"• `{prefix}hand`\n"
        f"  Sends an ephemeral private message with your held TCG cards and stats.\n\n"
        f"• `{prefix}territory`\n"
        f"  Sends an ephemeral private message with your owned territories and lap dividend income.\n\n"
        f"• `{prefix}status`\n"
        f"  Displays a public scorecard of all players: cash, territory counts, card counts, and strike status (`❌ ❌ ⚪`).\n\n"
        f"• `{prefix}board`\n"
        f"  Posts a fresh high-resolution rendering of the current board map.\n\n"
        f"• `{prefix}end_tw`\n"
        f"  Terminates the ongoing game in the current channel.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ **SERVER CONFIGURATION COMMANDS (Admins)**\n"
        f"• `{prefix}setprefix <new_prefix>`\n"
        f"  Customizes the command prefix for your Discord server. Example: `{prefix}setprefix tw!`\n\n"
        f"• `{prefix}setchannel #channel1 #channel2 ...`\n"
        f"  Allocates specific channels for Territory Wars. All other channels become **blocked** from running game commands!\n"
        f"  *Reset*: Type `{prefix}setchannel reset` to unblock all channels across the server.\n\n"
        f"• `{prefix}help`\n"
        f"  Displays this 3-part comprehensive field guide.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 *Tip: Spectators can watch all battles and dice rolls directly in the channel. Prepare your tactics and claim the globe!*"
    )

    await ctx.send(msg1)
    await ctx.send(msg2)
    await ctx.send(msg3)


# ---------------------------------------------------------------------------
# Health check web server for hosting platforms
# ---------------------------------------------------------------------------
async def start_health_server():
    async def handle_ping(request):
        return web.Response(text="Territory Wars Bot is alive and healthy!")

    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Health check web server running on port {port}")


@bot.event
async def on_ready():
    logger.info(f"Bot logged in as {bot.user.name} ({bot.user.id})")
    try:
        await start_health_server()
    except Exception as e:
        logger.warning(f"Could not start web health check server: {e}")


def main():
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        logger.error("DISCORD_BOT_TOKEN environment variable not found.")
        return
    bot.run(token)

if __name__ == "__main__":
    main()
