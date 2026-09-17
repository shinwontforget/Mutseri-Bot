"""
duels.py - All 7 Duels for Territory Wars

Resolves in under 30 seconds.
Spectator-friendly (public messages).
Handles:
  - Both timing out (defender retains)
  - One timing out (other wins)
  - Exact ties (defender retains)
"""

import asyncio
import random
import difflib
import discord
from discord import ui
from territories import get_tile

# ---------------------------------------------------------------------------
# Helper: Pick a random duel type (1 to 7)
# ---------------------------------------------------------------------------
DUEL_TYPES = [
    "reaction",
    "memory_flash",
    "quick_math",
    "odd_one_out",
    "geo_sprint",
    "stat_duel",
    "element_clash"
]

def pick_random_duel_type(challenger_cards: list, defender_cards: list) -> str:
    """Picks one of 7 duels randomly."""
    return random.choice(DUEL_TYPES)


# ---------------------------------------------------------------------------
# Base Duel Result Container
# ---------------------------------------------------------------------------
class DuelResult:
    def __init__(self, winner_id: int | None, loser_id: int | None, summary: str, consumed_cards: dict[int, list[str]] = None):
        self.winner_id = winner_id
        self.loser_id = loser_id
        self.summary = summary
        self.consumed_cards = consumed_cards or {}  # user_id -> [card_id, ...]


def _get_or_create_future():
    try:
        return asyncio.get_running_loop().create_future()
    except RuntimeError:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.create_future()

# ---------------------------------------------------------------------------
# 1. Reaction Duel View
# ---------------------------------------------------------------------------
class ReactionDuelView(ui.View):
    def __init__(self, challenger_id: int, defender_id: int, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.challenger_id = challenger_id
        self.defender_id = defender_id
        self.is_active = False
        self.resolved_future = _get_or_create_future()
        self.message = None

    async def start_countdown(self, message: discord.Message):
        self.message = message
        delay = random.uniform(2.0, 4.5)
        await asyncio.sleep(delay)

        if not self.resolved_future.done():
            self.is_active = True
            for item in self.children:
                if isinstance(item, ui.Button):
                    item.label = "⚡ STRIKE NOW!"
                    item.style = discord.ButtonStyle.success
                    item.disabled = False
            try:
                await self.message.edit(
                    content=f"⚡ **STRIKE NOW!** Click the button! (<@{self.challenger_id}> vs <@{self.defender_id}>)",
                    view=self
                )
            except Exception:
                pass

    @ui.button(label="WAIT...", style=discord.ButtonStyle.danger, custom_id="reaction_btn")
    async def reaction_click(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        if user_id not in (self.challenger_id, self.defender_id):
            await interaction.response.send_message("Only the dueling players can participate!", ephemeral=True)
            return

        if self.resolved_future.done():
            await interaction.response.defer()
            return

        await interaction.response.defer()

        other_id = self.defender_id if user_id == self.challenger_id else self.challenger_id

        if not self.is_active:
            # False start / early click disqualification!
            res = DuelResult(
                winner_id=other_id,
                loser_id=user_id,
                summary=f"🚨 <@{user_id}> clicked too early and is DISQUALIFIED! <@{other_id}> wins!"
            )
            self.resolved_future.set_result(res)
            self.stop()
        else:
            # First valid reaction wins
            res = DuelResult(
                winner_id=user_id,
                loser_id=other_id,
                summary=f"⚡ <@{user_id}> struck first and wins the Reaction Duel!"
            )
            self.resolved_future.set_result(res)
            self.stop()

    async def on_timeout(self):
        if not self.resolved_future.done():
            # Double timeout: defender retains
            res = DuelResult(
                winner_id=self.defender_id,
                loser_id=self.challenger_id,
                summary=f"⌛ Time expired! Neither player reacted. Defender <@{self.defender_id}> wins by default."
            )
            self.resolved_future.set_result(res)
        self.stop()


# ---------------------------------------------------------------------------
# 2. Memory Flash View & Modal
# ---------------------------------------------------------------------------
EMOJI_POOL = ["🌲", "🌊", "🌋", "🏔️", "☀️", "❄️", "🌴", "⚡"]

class MemoryFlashModal(ui.Modal, title="Memory Flash Sequence"):
    sequence_input = ui.TextInput(
        label="Type the emojis in order",
        placeholder="e.g. 🌲 🌋 🌊 🏔️",
        required=True,
        max_length=50
    )

    def __init__(self, target_sequence: list[str], callback):
        super().__init__()
        self.target_sequence = target_sequence
        self.callback = callback

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_text = self.sequence_input.value.strip()
        await self.callback(interaction.user.id, user_text)


class MemoryFlashView(ui.View):
    def __init__(self, challenger_id: int, defender_id: int, sequence: list[str], timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.challenger_id = challenger_id
        self.defender_id = defender_id
        self.sequence = sequence
        self.submissions = {}  # user_id -> input_text
        self.resolved_future = _get_or_create_future()
        self.message = None

    async def start_flash(self, message: discord.Message):
        self.message = message
        # Show for 3 seconds then hide
        await asyncio.sleep(3.0)
        if not self.resolved_future.done():
            try:
                await self.message.edit(
                    content=(
                        f"🧠 **Memory Flash!** The sequence has disappeared!\n"
                        f"<@{self.challenger_id}> and <@{self.defender_id}>, click below and retype the sequence!"
                    ),
                    view=self
                )
            except Exception:
                pass

    @ui.button(label="📝 Submit Sequence", style=discord.ButtonStyle.primary, custom_id="memory_btn")
    async def open_modal(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        if user_id not in (self.challenger_id, self.defender_id):
            await interaction.response.send_message("Only the dueling players can participate!", ephemeral=True)
            return

        if user_id in self.submissions:
            await interaction.response.send_message("You have already submitted your guess!", ephemeral=True)
            return

        modal = MemoryFlashModal(self.sequence, self.record_submission)
        await interaction.response.send_modal(modal)

    async def record_submission(self, user_id: int, text: str):
        self.submissions[user_id] = text

        # Check if both have submitted
        if self.challenger_id in self.submissions and self.defender_id in self.submissions:
            self.resolve_duel()

    def calculate_score(self, text: str) -> float:
        # Compare submitted string characters against target sequence joined
        target_str = "".join(self.sequence)
        cleaned_user = text.replace(" ", "")
        return difflib.SequenceMatcher(None, target_str, cleaned_user).ratio()

    def resolve_duel(self):
        if self.resolved_future.done():
            return

        c_text = self.submissions.get(self.challenger_id)
        d_text = self.submissions.get(self.defender_id)

        target_display = " ".join(self.sequence)

        if c_text is None and d_text is None:
            # Both timeout
            res = DuelResult(
                winner_id=self.defender_id,
                loser_id=self.challenger_id,
                summary=f"⌛ Neither player submitted in time! Target was: `{target_display}`. Defender <@{self.defender_id}> wins."
            )
        elif c_text is None:
            res = DuelResult(
                winner_id=self.defender_id,
                loser_id=self.challenger_id,
                summary=f"⌛ Challenger timed out! Target was: `{target_display}`. Defender <@{self.defender_id}> wins."
            )
        elif d_text is None:
            res = DuelResult(
                winner_id=self.challenger_id,
                loser_id=self.defender_id,
                summary=f"⌛ Defender timed out! Target was: `{target_display}`. Challenger <@{self.challenger_id}> wins."
            )
        else:
            c_score = self.calculate_score(c_text)
            d_score = self.calculate_score(d_text)

            if c_score > d_score:
                winner_id = self.challenger_id
                loser_id = self.defender_id
                reason = f"Challenger was more accurate ({c_score:.0%} vs {d_score:.0%})!"
            elif d_score > c_score:
                winner_id = self.defender_id
                loser_id = self.challenger_id
                reason = f"Defender was more accurate ({d_score:.0%} vs {c_score:.0%})!"
            else:
                winner_id = self.defender_id
                loser_id = self.challenger_id
                reason = f"Exact tie in accuracy ({d_score:.0%})! Defender retains."

            res = DuelResult(
                winner_id=winner_id,
                loser_id=loser_id,
                summary=f"🧠 **Memory Flash Result!** Target was: `{target_display}`.\n{reason} <@{winner_id}> wins!"
            )

        self.resolved_future.set_result(res)
        self.stop()

    async def on_timeout(self):
        self.resolve_duel()


# ---------------------------------------------------------------------------
# 3. Quick Math View
# ---------------------------------------------------------------------------
class QuickMathView(ui.View):
    def __init__(self, challenger_id: int, defender_id: int, question: str, correct_ans: int, options: list[int], timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.challenger_id = challenger_id
        self.defender_id = defender_id
        self.question = question
        self.correct_ans = correct_ans
        self.resolved_future = _get_or_create_future()

        for opt in options:
            btn = ui.Button(label=str(opt), style=discord.ButtonStyle.secondary)
            btn.callback = self.make_callback(opt)
            self.add_item(btn)

    def make_callback(self, chosen: int):
        async def btn_callback(interaction: discord.Interaction):
            user_id = interaction.user.id
            if user_id not in (self.challenger_id, self.defender_id):
                await interaction.response.send_message("Only the dueling players can answer!", ephemeral=True)
                return

            if self.resolved_future.done():
                await interaction.response.defer()
                return

            await interaction.response.defer()
            other_id = self.defender_id if user_id == self.challenger_id else self.challenger_id

            if chosen == self.correct_ans:
                res = DuelResult(
                    winner_id=user_id,
                    loser_id=other_id,
                    summary=f"🧮 <@{user_id}> correctly answered `{self.correct_ans}` first and wins!"
                )
            else:
                res = DuelResult(
                    winner_id=other_id,
                    loser_id=user_id,
                    summary=f"❌ <@{user_id}> chose wrong answer `{chosen}`! Correct was `{self.correct_ans}`. <@{other_id}> wins!"
                )
            self.resolved_future.set_result(res)
            self.stop()
        return btn_callback

    async def on_timeout(self):
        if not self.resolved_future.done():
            res = DuelResult(
                winner_id=self.defender_id,
                loser_id=self.challenger_id,
                summary=f"⌛ Time expired on math duel! Correct answer was `{self.correct_ans}`. Defender <@{self.defender_id}> retains."
            )
            self.resolved_future.set_result(res)
        self.stop()


# ---------------------------------------------------------------------------
# 4. Odd One Out View
# ---------------------------------------------------------------------------
ODD_ONE_OUT_POOLS = [
    {
        "category": "Deserts",
        "items": ["Sahara", "Gobi", "Mojave"],
        "odd": "Amazon (Rainforest)",
        "options": ["Sahara", "Gobi", "Mojave", "Amazon"]
    },
    {
        "category": "Mountain Ranges",
        "items": ["Alps", "Andes", "Himalayas"],
        "odd": "Pacific (Ocean)",
        "options": ["Alps", "Andes", "Himalayas", "Pacific"]
    },
    {
        "category": "Asian Capitals",
        "items": ["Tokyo", "Seoul", "Bangkok"],
        "odd": "Madrid (Europe)",
        "options": ["Tokyo", "Seoul", "Bangkok", "Madrid"]
    },
    {
        "category": "Island Nations",
        "items": ["Iceland", "Japan", "Madagascar"],
        "odd": "Switzerland (Landlocked)",
        "options": ["Iceland", "Japan", "Madagascar", "Switzerland"]
    },
    {
        "category": "Volcanoes",
        "items": ["Fuji", "Vesuvius", "Etna"],
        "odd": "Everest (Non-volcanic)",
        "options": ["Fuji", "Vesuvius", "Etna", "Everest"]
    }
]

class OddOneOutView(ui.View):
    def __init__(self, challenger_id: int, defender_id: int, item_data: dict, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.challenger_id = challenger_id
        self.defender_id = defender_id
        self.item_data = item_data
        self.odd_item = item_data["options"][-1]  # The odd option text
        self.resolved_future = _get_or_create_future()

        shuffled_options = list(item_data["options"])
        random.shuffle(shuffled_options)

        for opt in shuffled_options:
            btn = ui.Button(label=opt, style=discord.ButtonStyle.secondary)
            btn.callback = self.make_callback(opt)
            self.add_item(btn)

    def make_callback(self, chosen: str):
        async def btn_callback(interaction: discord.Interaction):
            user_id = interaction.user.id
            if user_id not in (self.challenger_id, self.defender_id):
                await interaction.response.send_message("Only the dueling players can answer!", ephemeral=True)
                return

            if self.resolved_future.done():
                await interaction.response.defer()
                return

            await interaction.response.defer()
            other_id = self.defender_id if user_id == self.challenger_id else self.challenger_id

            # The odd item starts with the name in odd string
            if chosen in self.item_data["odd"]:
                res = DuelResult(
                    winner_id=user_id,
                    loser_id=other_id,
                    summary=f"🎯 <@{user_id}> correctly identified the odd one out: **{self.item_data['odd']}**!"
                )
            else:
                res = DuelResult(
                    winner_id=other_id,
                    loser_id=user_id,
                    summary=f"❌ <@{user_id}> picked '{chosen}' which belongs to {self.item_data['category']}. <@{other_id}> wins!"
                )
            self.resolved_future.set_result(res)
            self.stop()
        return btn_callback

    async def on_timeout(self):
        if not self.resolved_future.done():
            res = DuelResult(
                winner_id=self.defender_id,
                loser_id=self.challenger_id,
                summary=f"⌛ Time expired on Odd One Out! The odd item was: **{self.item_data['odd']}**. Defender <@{self.defender_id}> retains."
            )
            self.resolved_future.set_result(res)
        self.stop()


# ---------------------------------------------------------------------------
# 5. Geo Sprint View
# ---------------------------------------------------------------------------
class GeoSprintView(ui.View):
    def __init__(self, challenger_id: int, defender_id: int, question: str, correct_ans: str, options: list[str], timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.challenger_id = challenger_id
        self.defender_id = defender_id
        self.question = question
        self.correct_ans = correct_ans
        self.resolved_future = _get_or_create_future()

        for opt in options:
            btn = ui.Button(label=opt, style=discord.ButtonStyle.secondary)
            btn.callback = self.make_callback(opt)
            self.add_item(btn)

    def make_callback(self, chosen: str):
        async def btn_callback(interaction: discord.Interaction):
            user_id = interaction.user.id
            if user_id not in (self.challenger_id, self.defender_id):
                await interaction.response.send_message("Only the dueling players can answer!", ephemeral=True)
                return

            if self.resolved_future.done():
                await interaction.response.defer()
                return

            await interaction.response.defer()
            other_id = self.defender_id if user_id == self.challenger_id else self.challenger_id

            if chosen.lower() == self.correct_ans.lower():
                res = DuelResult(
                    winner_id=user_id,
                    loser_id=other_id,
                    summary=f"🌍 <@{user_id}> correctly answered **{self.correct_ans}** and wins the Geo Sprint!"
                )
            else:
                res = DuelResult(
                    winner_id=other_id,
                    loser_id=user_id,
                    summary=f"❌ <@{user_id}> answered '{chosen}'! Correct was **{self.correct_ans}**. <@{other_id}> wins!"
                )
            self.resolved_future.set_result(res)
            self.stop()
        return btn_callback

    async def on_timeout(self):
        if not self.resolved_future.done():
            res = DuelResult(
                winner_id=self.defender_id,
                loser_id=self.challenger_id,
                summary=f"⌛ Time expired on Geo Sprint! Correct was **{self.correct_ans}**. Defender <@{self.defender_id}> retains."
            )
            self.resolved_future.set_result(res)
        self.stop()


# ---------------------------------------------------------------------------
# 6. Stat Duel View (TCG)
# ---------------------------------------------------------------------------
class StatDuelView(ui.View):
    def __init__(self, challenger_id: int, defender_id: int, contested_stat: str, base_val: int, c_cards: list, d_cards: list, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.challenger_id = challenger_id
        self.defender_id = defender_id
        self.contested_stat = contested_stat
        self.base_val = base_val
        self.cards = {challenger_id: c_cards, defender_id: d_cards}
        self.played_card = {challenger_id: None, defender_id: None}
        self.resolved_future = _get_or_create_future()

    @ui.button(label="🃏 Play Card Face-Down", style=discord.ButtonStyle.primary, custom_id="stat_card_btn")
    async def play_card_btn(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        if user_id not in (self.challenger_id, self.defender_id):
            await interaction.response.send_message("Only the dueling players can participate!", ephemeral=True)
            return

        if self.played_card[user_id] is not None:
            await interaction.response.send_message("You have already locked in your card!", ephemeral=True)
            return

        user_cards = self.cards[user_id]

        options = [
            discord.SelectOption(label="Pass (Play +0)", value="PASS", description="Play no card (0 bonus)")
        ]
        for c in user_cards:
            options.append(discord.SelectOption(
                label=f"{c['name']} ({c['stat'].capitalize()} +{c['value']})",
                value=c["id"],
                description=f"Boosts {c['stat']} by +{c['value']}"
            ))

        select = ui.Select(placeholder="Choose a card to play face-down...", options=options[:25])

        async def select_callback(s_interaction: discord.Interaction):
            await s_interaction.response.defer()
            chosen_val = select.values[0]
            if chosen_val == "PASS":
                self.played_card[user_id] = "PASS"
                await s_interaction.followup.send("🔒 You locked in: **Pass (+0)**.", ephemeral=True)
            else:
                card = next((c for c in user_cards if c["id"] == chosen_val), None)
                self.played_card[user_id] = card
                await s_interaction.followup.send(f"🔒 You locked in face-down: **{card['title']}**.", ephemeral=True)

            if self.played_card[self.challenger_id] is not None and self.played_card[self.defender_id] is not None:
                self.resolve_duel()

        select.callback = select_callback
        ephemeral_view = ui.View()
        ephemeral_view.add_item(select)
        await interaction.response.send_message("Select your secret card:", view=ephemeral_view, ephemeral=True)

    def resolve_duel(self):
        if self.resolved_future.done():
            return

        c_choice = self.played_card[self.challenger_id]
        d_choice = self.played_card[self.defender_id]

        c_bonus = 0
        c_consumed = []
        c_desc = "No Card (+0)"
        if isinstance(c_choice, dict):
            if c_choice["stat"].lower() == self.contested_stat.lower():
                c_bonus = c_choice["value"]
            c_desc = f"{c_choice['name']} (+{c_choice['value']} {c_choice['stat'].capitalize()})"
            c_consumed.append(c_choice["id"])

        d_bonus = 0
        d_consumed = []
        d_desc = "No Card (+0)"
        if isinstance(d_choice, dict):
            if d_choice["stat"].lower() == self.contested_stat.lower():
                d_bonus = d_choice["value"]
            d_desc = f"{d_choice['name']} (+{d_choice['value']} {d_choice['stat'].capitalize()})"
            d_consumed.append(d_choice["id"])

        c_total = self.base_val + c_bonus
        d_total = self.base_val + d_bonus

        consumed_map = {
            self.challenger_id: c_consumed,
            self.defender_id: d_consumed
        }

        stat_name = self.contested_stat.capitalize()
        summary_intro = (
            f"🃏 **Stat Duel Reveal!** Contested Stat: **{stat_name}** (Base: {self.base_val})\n"
            f"⚔️ Challenger <@{self.challenger_id}> played: `{c_desc}` ➔ Total: **{c_total}**\n"
            f"🛡️ Defender <@{self.defender_id}> played: `{d_desc}` ➔ Total: **{d_total}**\n"
        )

        if c_total > d_total:
            winner_id = self.challenger_id
            loser_id = self.defender_id
            res_text = f"🏆 Challenger <@{winner_id}> wins with higher {stat_name} total ({c_total} vs {d_total})!"
        elif d_total > c_total:
            winner_id = self.defender_id
            loser_id = self.challenger_id
            res_text = f"🏆 Defender <@{winner_id}> wins with higher {stat_name} total ({d_total} vs {c_total})!"
        else:
            winner_id = self.defender_id
            loser_id = self.challenger_id
            res_text = f"⚖️ Exact tie ({d_total} = {c_total})! Defender <@{winner_id}> retains."

        res = DuelResult(
            winner_id=winner_id,
            loser_id=loser_id,
            summary=summary_intro + res_text,
            consumed_cards=consumed_map
        )
        self.resolved_future.set_result(res)
        self.stop()

    async def on_timeout(self):
        # Auto fill missing with PASS and resolve
        for pid in (self.challenger_id, self.defender_id):
            if self.played_card[pid] is None:
                self.played_card[pid] = "PASS"
        self.resolve_duel()


# ---------------------------------------------------------------------------
# 7. Element Clash View (TCG)
# Climate beats Terrain, Terrain beats Economy, Economy beats Climate.
# ---------------------------------------------------------------------------
class ElementClashView(ui.View):
    def __init__(self, challenger_id: int, defender_id: int, c_cards: list, d_cards: list, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.challenger_id = challenger_id
        self.defender_id = defender_id
        self.cards = {challenger_id: c_cards, defender_id: d_cards}
        self.choices = {challenger_id: None, defender_id: None}
        self.resolved_future = _get_or_create_future()

    @ui.button(label="⚔️ Choose Element", style=discord.ButtonStyle.primary, custom_id="element_btn")
    async def choose_element_btn(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        if user_id not in (self.challenger_id, self.defender_id):
            await interaction.response.send_message("Only the dueling players can participate!", ephemeral=True)
            return

        if self.choices[user_id] is not None:
            await interaction.response.send_message("You have already locked in your element!", ephemeral=True)
            return

        user_cards = self.cards[user_id]

        options = [
            discord.SelectOption(label="🌧️ Climate", value="climate", description="Beats Terrain. Loses to Economy."),
            discord.SelectOption(label="🏔️ Terrain", value="terrain", description="Beats Economy. Loses to Climate."),
            discord.SelectOption(label="💼 Economy", value="economy", description="Beats Climate. Loses to Terrain."),
        ]

        select = ui.Select(placeholder="Select your element...", options=options)

        async def select_callback(s_interaction: discord.Interaction):
            chosen_elem = select.values[0]

            matching_cards = [c for c in user_cards if c["stat"].lower() == chosen_elem.lower()]

            if not matching_cards:
                self.choices[user_id] = {"element": chosen_elem, "card": None}
                await s_interaction.response.send_message(f"🔒 Locked in: **{chosen_elem.capitalize()}** (No tie-breaker card held).", ephemeral=True)
                if self.choices[self.challenger_id] is not None and self.choices[self.defender_id] is not None:
                    self.resolve_duel()
                return

            # Let player pick matching card for tie break
            card_opts = [
                discord.SelectOption(label="No Tie-Breaker Card", value="NONE", description="Save card (+0)")
            ]
            for c in matching_cards:
                card_opts.append(discord.SelectOption(
                    label=f"{c['name']} (+{c['value']})",
                    value=c["id"],
                    description=f"Tie-breaker power +{c['value']}"
                ))

            card_select = ui.Select(placeholder="Choose tie-breaker card...", options=card_opts[:25])

            async def card_callback(c_interaction: discord.Interaction):
                c_val = card_select.values[0]
                card = next((c for c in matching_cards if c["id"] == c_val), None)
                self.choices[user_id] = {"element": chosen_elem, "card": card}
                card_name = card['title'] if card else "None"
                await c_interaction.response.send_message(f"🔒 Locked in: **{chosen_elem.capitalize()}** | Tie-Breaker: `{card_name}`.", ephemeral=True)
                if self.choices[self.challenger_id] is not None and self.choices[self.defender_id] is not None:
                    self.resolve_duel()

            card_select.callback = card_callback
            v = ui.View()
            v.add_item(card_select)
            await s_interaction.response.send_message(f"Selected **{chosen_elem.capitalize()}**. Choose optional tie-breaker card:", view=v, ephemeral=True)

        select.callback = select_callback
        ephemeral_view = ui.View()
        ephemeral_view.add_item(select)
        await interaction.response.send_message("Select your element:", view=ephemeral_view, ephemeral=True)

    def resolve_duel(self):
        if self.resolved_future.done():
            return

        c_choice = self.choices[self.challenger_id] or {"element": random.choice(["climate", "terrain", "economy"]), "card": None}
        d_choice = self.choices[self.defender_id] or {"element": random.choice(["climate", "terrain", "economy"]), "card": None}

        c_elem = c_choice["element"].lower()
        d_elem = d_choice["element"].lower()

        c_card = c_choice["card"]
        d_card = d_choice["card"]

        c_val = c_card["value"] if c_card else 0
        d_val = d_card["value"] if d_card else 0

        consumed = {
            self.challenger_id: [c_card["id"]] if c_card else [],
            self.defender_id: [d_card["id"]] if d_card else []
        }

        # Matchup: Climate > Terrain > Economy > Climate
        BEATS = {
            "climate": "terrain",
            "terrain": "economy",
            "economy": "climate"
        }

        summary_intro = (
            f"🌀 **Element Clash Reveal!**\n"
            f"⚔️ Challenger <@{self.challenger_id}>: **{c_elem.capitalize()}** (Card: {c_card['name'] if c_card else 'None'} +{c_val})\n"
            f"🛡️ Defender <@{self.defender_id}>: **{d_elem.capitalize()}** (Card: {d_card['name'] if d_card else 'None'} +{d_val})\n"
        )

        if BEATS[c_elem] == d_elem:
            winner_id = self.challenger_id
            loser_id = self.defender_id
            res_text = f"🏆 {c_elem.capitalize()} defeats {d_elem.capitalize()}! Challenger <@{winner_id}> wins!"
        elif BEATS[d_elem] == c_elem:
            winner_id = self.defender_id
            loser_id = self.challenger_id
            res_text = f"🏆 {d_elem.capitalize()} defeats {c_elem.capitalize()}! Defender <@{winner_id}> wins!"
        else:
            # Same element: Tie-break with card value
            if c_val > d_val:
                winner_id = self.challenger_id
                loser_id = self.defender_id
                res_text = f"⚖️ Same element! Challenger played higher card (+{c_val} vs +{d_val})! <@{winner_id}> wins!"
            elif d_val > c_val:
                winner_id = self.defender_id
                loser_id = self.challenger_id
                res_text = f"⚖️ Same element! Defender played higher card (+{d_val} vs +{c_val})! <@{winner_id}> wins!"
            else:
                winner_id = self.defender_id
                loser_id = self.challenger_id
                res_text = f"⚖️ Exact tie on element and card (+{d_val})! Defender <@{winner_id}> retains."

        res = DuelResult(
            winner_id=winner_id,
            loser_id=loser_id,
            summary=summary_intro + res_text,
            consumed_cards=consumed
        )
        self.resolved_future.set_result(res)
        self.stop()

    async def on_timeout(self):
        self.resolve_duel()


# ---------------------------------------------------------------------------
# Duel Launcher Factory
# ---------------------------------------------------------------------------
def create_duel(duel_type: str, challenger_id: int, defender_id: int, contested_tile_pos: int, c_cards: list, d_cards: list) -> tuple[ui.View, str]:
    """
    Creates and returns the appropriate (View, prompt_message) for the given duel.
    """
    tile = get_tile(contested_tile_pos)

    if duel_type == "reaction":
        view = ReactionDuelView(challenger_id, defender_id)
        msg = (
            f"⚔️ **DUEL: Reaction Duel!**\n"
            f"<@{challenger_id}> (Challenger) vs <@{defender_id}> (Defender)\n"
            f"Click the button when it turns **GREEN**! Clicking early causes instant disqualification!"
        )
        return view, msg

    elif duel_type == "memory_flash":
        seq = random.sample(EMOJI_POOL, 4)
        view = MemoryFlashView(challenger_id, defender_id, seq)
        msg = (
            f"⚔️ **DUEL: Memory Flash!**\n"
            f"<@{challenger_id}> vs <@{defender_id}>\n"
            f"Memorize this sequence (disappears in 3 seconds!):\n"
            f"## {' '.join(seq)}"
        )
        return view, msg

    elif duel_type == "quick_math":
        op = random.choice(["+", "-", "*"])
        if op == "+":
            a = random.randint(14, 58)
            b = random.randint(15, 62)
            ans = a + b
        elif op == "-":
            a = random.randint(35, 95)
            b = random.randint(12, 45)
            ans = a - b
        else:
            a = random.randint(4, 9)
            b = random.randint(6, 12)
            ans = a * b

        distractors = set()
        while len(distractors) < 3:
            delta = random.choice([-10, -5, -2, -1, 1, 2, 5, 10])
            cand = ans + delta
            if cand != ans and cand > 0:
                distractors.add(cand)

        options = list(distractors) + [ans]
        random.shuffle(options)
        q_text = f"{a} {op} {b} = ?"
        view = QuickMathView(challenger_id, defender_id, q_text, ans, options)
        msg = (
            f"⚔️ **DUEL: Quick Math!**\n"
            f"<@{challenger_id}> vs <@{defender_id}>\n"
            f"Solve first: **{q_text}**"
        )
        return view, msg

    elif duel_type == "odd_one_out":
        data = random.choice(ODD_ONE_OUT_POOLS)
        view = OddOneOutView(challenger_id, defender_id, data)
        msg = (
            f"⚔️ **DUEL: Odd One Out!**\n"
            f"<@{challenger_id}> vs <@{defender_id}>\n"
            f"Which item does NOT belong in the category?"
        )
        return view, msg

    elif duel_type == "geo_sprint":
        trivia = tile.get("trivia", {})
        q_kind = random.choice(["hemisphere", "coastal", "size"])

        if q_kind == "hemisphere":
            correct = trivia.get("hemisphere", "Northern")
            options = ["Northern", "Southern"]
            q = f"Which hemisphere is **{tile['name']}, {tile['country']}** in?"
        elif q_kind == "coastal":
            correct = "Coastal" if trivia.get("coastal", True) else "Landlocked"
            options = ["Coastal", "Landlocked"]
            q = f"Is **{tile['country']}** coastal or landlocked?"
        else:
            # Size comparison
            larger = trivia.get("larger_than", ["Monaco"])
            comp_country = random.choice(larger)
            correct = tile["country"]
            options = [tile["country"], comp_country]
            random.shuffle(options)
            q = f"Which country has a larger land area: **{tile['country']}** or **{comp_country}**?"

        view = GeoSprintView(challenger_id, defender_id, q, correct, options)
        msg = (
            f"⚔️ **DUEL: Geo Sprint!**\n"
            f"<@{challenger_id}> vs <@{defender_id}>\n"
            f"Contested Territory: **{tile.get('flag', '')} {tile['name']}, {tile.get('country', '')}**\n"
            f"**{q}**"
        )
        return view, msg

    elif duel_type == "stat_duel":
        stat = random.choice(["climate", "terrain", "economy"])
        base_val = tile.get("stats", {}).get(stat, 5)
        view = StatDuelView(challenger_id, defender_id, stat, base_val, c_cards, d_cards)
        msg = (
            f"⚔️ **DUEL: Stat Duel (TCG)!**\n"
            f"<@{challenger_id}> vs <@{defender_id}>\n"
            f"Contested Territory: **{tile.get('flag', '')} {tile['name']}**\n"
            f"Contested Stat: **{stat.capitalize()}** (Base: **{base_val}**)\n"
            f"Click below to play a secret card to boost this stat!"
        )
        return view, msg

    else:  # element_clash
        view = ElementClashView(challenger_id, defender_id, c_cards, d_cards)
        msg = (
            f"⚔️ **DUEL: Element Clash (TCG)!**\n"
            f"<@{challenger_id}> vs <@{defender_id}>\n"
            f"Rules: **Climate > Terrain > Economy > Climate**\n"
            f"Click below to choose your element and optional tie-breaker card!"
        )
        return view, msg
