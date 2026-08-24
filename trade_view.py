import discord

# ---------------------------------------------------------------------------
# Counter-offer modal — lets Player B amend trade terms and send them back
# ---------------------------------------------------------------------------

class CounterOfferModal(discord.ui.Modal, title="📝 Counter-Offer Terms"):
    """
    Discord modal (popup form) for Player B to specify revised trade terms.
    Shown when they click 'Counter-Offer' on a TradeProposalView.
    Fields are pre-filled with the original proposal so it's easy to tweak.
    """

    offered_cash = discord.ui.TextInput(
        label="Cash you offer (leave 0 for none)",
        placeholder="e.g. 150",
        required=True,
        max_length=10,
    )
    offered_props = discord.ui.TextInput(
        label="Properties you offer (names/cities, comma-sep)",
        placeholder="e.g. Tokyo, London (or leave blank)",
        required=False,
        max_length=200,
    )
    requested_cash = discord.ui.TextInput(
        label="Cash you want in return (leave 0 for none)",
        placeholder="e.g. 0",
        required=True,
        max_length=10,
    )
    requested_props = discord.ui.TextInput(
        label="Properties you want (names/cities, comma-sep)",
        placeholder="e.g. Paris (or leave blank)",
        required=False,
        max_length=200,
    )

    def __init__(
        self,
        game,
        original_sender: discord.Member,
        counter_sender: discord.Member,
        original_view: "TradeProposalView",
        # Pre-fill hints (displayed as placeholder text)
        orig_offer_cash: int = 0,
        orig_req_cash: int = 0,
    ):
        super().__init__()
        self.game = game
        self.original_sender = original_sender  # person who proposed first (now receives counter)
        self.counter_sender = counter_sender      # person counter-offering (was the target)
        self.original_view = original_view

        # Pre-fill with the received terms (reversed perspective)
        self.offered_cash.default = str(orig_req_cash)   # B will now offer what A requested
        self.requested_cash.default = str(orig_offer_cash)  # B wants what A offered

    async def on_submit(self, interaction: discord.Interaction):
        from trade_view import TradeProposalView  # local import to avoid circular reference

        # --- Parse cash fields ---
        def parse_cash(raw: str) -> int | None:
            cleaned = raw.strip().replace("$", "").replace(",", "")
            if cleaned == "" or cleaned == "0":
                return 0
            return int(cleaned) if cleaned.isdigit() else None

        new_offer_cash = parse_cash(self.offered_cash.value)
        new_req_cash = parse_cash(self.requested_cash.value)

        if new_offer_cash is None or new_req_cash is None:
            await interaction.response.send_message(
                "⚠️ Cash amounts must be whole numbers (e.g. `150`).", ephemeral=True
            )
            return

        # --- Parse property fields ---
        def parse_props(raw: str, owner_id: int) -> tuple[list[int], str | None]:
            props = []
            if not raw.strip():
                return props, None
            tokens = [t.strip() for t in raw.split(",") if t.strip()]
            for tok in tokens:
                pos = self.game.find_property_by_name(tok, owner_id)
                if pos is None:
                    return [], f"Property `{tok}` not found or not owned by <@{owner_id}>."
                if pos not in props:
                    props.append(pos)
            return props, None

        new_offer_props, err1 = parse_props(self.offered_props.value, self.counter_sender.id)
        if err1:
            await interaction.response.send_message(f"⚠️ {err1}", ephemeral=True)
            return

        new_req_props, err2 = parse_props(self.requested_props.value, self.original_sender.id)
        if err2:
            await interaction.response.send_message(f"⚠️ {err2}", ephemeral=True)
            return

        if not new_offer_props and new_offer_cash == 0 and not new_req_props and new_req_cash == 0:
            await interaction.response.send_message(
                "⚠️ A counter-offer must include at least one property or cash amount!", ephemeral=True
            )
            return

        # Validate houses check (standard Monopoly rule — no trading improved properties)
        for p in new_offer_props:
            if self.game.board[p].get("houses", 0) > 0:
                await interaction.response.send_message(
                    f"⚠️ Cannot offer **{self.game.board[p]['name']}** while it has houses!", ephemeral=True
                )
                return
        for p in new_req_props:
            if self.game.board[p].get("houses", 0) > 0:
                await interaction.response.send_message(
                    f"⚠️ Cannot request **{self.game.board[p]['name']}** while it has houses!", ephemeral=True
                )
                return

        # Disable original trade view
        self.original_view.disable_all_items()
        self.original_view.stop()
        if self.original_view.message:
            try:
                await self.original_view.message.edit(
                    content=(
                        f"🔄 **Counter-Offer Sent** by **{self.counter_sender.display_name}** "
                        f"→ waiting for **{self.original_sender.display_name}**'s response."
                    ),
                    view=self.original_view,
                    embed=None,
                )
            except Exception:
                pass

        # Build the new (reversed) TradeProposalView
        new_view = TradeProposalView(
            self.game,
            sender=self.counter_sender,
            target=self.original_sender,
            offer_props=new_offer_props,
            offer_cash=new_offer_cash,
            req_props=new_req_props,
            req_cash=new_req_cash,
        )

        offer_desc = [f"• 🏠 **{self.game.board[p]['name']}**" for p in new_offer_props]
        if new_offer_cash > 0:
            offer_desc.append(f"• 💰 **${new_offer_cash} Cash**")

        req_desc = [f"• 🏠 **{self.game.board[p]['name']}**" for p in new_req_props]
        if new_req_cash > 0:
            req_desc.append(f"• 💰 **${new_req_cash} Cash**")

        counter_text = (
            f"🔄 **COUNTER-OFFER** (⏱️ 90s limit)\n"
            f"**From:** {self.counter_sender.mention} ➔ **To:** {self.original_sender.mention}\n\n"
            f"📤 **Offered by {self.counter_sender.display_name}:**\n"
            f"{chr(10).join(offer_desc) if offer_desc else '• Nothing'}\n\n"
            f"📥 **Requested from {self.original_sender.display_name}:**\n"
            f"{chr(10).join(req_desc) if req_desc else '• Nothing'}\n\n"
            f"{self.original_sender.mention}, click **Accept Deal** or **Decline Deal** below within 90 seconds!"
        )

        await interaction.response.send_message(content=counter_text, view=new_view)
        new_view.message = await interaction.original_response()


# ---------------------------------------------------------------------------
# Main trade proposal view
# ---------------------------------------------------------------------------

class TradeProposalView(discord.ui.View):
    def __init__(
        self,
        game,
        sender: discord.Member,
        target: discord.Member,
        offer_props: list[int],
        offer_cash: int,
        req_props: list[int],
        req_cash: int,
    ):
        super().__init__(timeout=90.0)  # 90-second trade limit
        self.game = game
        self.sender = sender
        self.target = target
        self.offer_props = offer_props
        self.offer_cash = offer_cash
        self.req_props = req_props
        self.req_cash = req_cash
        self.message: discord.Message | None = None
        self._processing = False

    def disable_all_items(self):
        for item in self.children:
            item.disabled = True

    async def on_timeout(self):
        self.disable_all_items()
        if self.message:
            try:
                await self.message.edit(
                    content=f"⏱️ **Trade Proposal Expired (90s)** between {self.sender.mention} and {self.target.mention}.",
                    view=self,
                    embed=None
                )
            except Exception:
                pass

    @discord.ui.button(label="✅ Accept Deal", style=discord.ButtonStyle.green, custom_id="trade_accept")
    async def accept_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message(f"Only {self.target.display_name} can accept this trade proposal!", ephemeral=True)
            return

        if self._processing:
            return
        self._processing = True

        sender_state = self.game.get_player_state(self.sender.id)
        target_state = self.game.get_player_state(self.target.id)

        # Check if either player is bankrupt or eliminated
        if sender_state.get("bankrupt", False) or target_state.get("bankrupt", False):
            await interaction.response.send_message("Trade cancelled: one of the players has declared bankruptcy.", ephemeral=True)
            self.disable_all_items()
            self.stop()
            return

        if sender_state["money"] < self.offer_cash:
            await interaction.response.send_message(f"{self.sender.display_name} no longer has enough cash (${self.offer_cash})!", ephemeral=True)
            self._processing = False
            return
        if target_state["money"] < self.req_cash:
            await interaction.response.send_message(f"{self.target.display_name} does not have enough cash (${self.req_cash})!", ephemeral=True)
            self._processing = False
            return

        # Check that properties are still owned and not built on (in Monopoly, cannot trade properties with houses)
        for p in self.offer_props:
            if p not in sender_state["properties"]:
                await interaction.response.send_message(f"{self.sender.display_name} no longer owns {self.game.board[p]['name']}!", ephemeral=True)
                self._processing = False
                return
            if self.game.board[p].get("houses", 0) > 0:
                await interaction.response.send_message(f"Cannot trade {self.game.board[p]['name']} while it still has houses built on it!", ephemeral=True)
                self._processing = False
                return

        for p in self.req_props:
            if p not in target_state["properties"]:
                await interaction.response.send_message(f"{self.target.display_name} no longer owns {self.game.board[p]['name']}!", ephemeral=True)
                self._processing = False
                return
            if self.game.board[p].get("houses", 0) > 0:
                await interaction.response.send_message(f"Cannot trade {self.game.board[p]['name']} while it still has houses built on it!", ephemeral=True)
                self._processing = False
                return

        sender_state["money"] -= self.offer_cash
        sender_state["money"] += self.req_cash
        target_state["money"] -= self.req_cash
        target_state["money"] += self.offer_cash

        for pos in self.offer_props:
            if pos in sender_state["properties"]:
                sender_state["properties"].remove(pos)
                target_state["properties"].append(pos)
                self.game.properties_owned[pos] = self.target.id

        for pos in self.req_props:
            if pos in target_state["properties"]:
                target_state["properties"].remove(pos)
                sender_state["properties"].append(pos)
                self.game.properties_owned[pos] = self.sender.id

        self.game.invalidate_static_cache()
        self.game.record_activity()
        self.game.log_event(f"🤝 TRADE COMPLETED between {self.sender.display_name} and {self.target.display_name}!")
        self.disable_all_items()
        self.stop()

        # Build compact summary of swapped items
        offer_names = [f"**{self.game.board[p]['name']}**" for p in self.offer_props]
        if self.offer_cash > 0:
            offer_names.append(f"**${self.offer_cash} cash**")
        req_names = [f"**{self.game.board[p]['name']}**" for p in self.req_props]
        if self.req_cash > 0:
            req_names.append(f"**${self.req_cash} cash**")

        text = (
            f"🤝 **Trade Deal Accepted!**\n"
            f"**{self.sender.display_name}** gave: {', '.join(offer_names) if offer_names else 'Nothing'}\n"
            f"**{self.target.display_name}** gave: {', '.join(req_names) if req_names else 'Nothing'}"
        )
        await interaction.response.edit_message(content=text, view=self, embed=None)

    @discord.ui.button(label="🔄 Counter-Offer", style=discord.ButtonStyle.blurple, custom_id="trade_counter")
    async def counter_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Let the target propose revised terms back to the sender."""
        if interaction.user.id != self.target.id:
            await interaction.response.send_message(
                f"Only {self.target.display_name} can send a counter-offer!", ephemeral=True
            )
            return

        if self._processing:
            await interaction.response.send_message("This trade is already being processed.", ephemeral=True)
            return

        self._processing = True

        modal = CounterOfferModal(
            game=self.game,
            original_sender=self.sender,
            counter_sender=self.target,
            original_view=self,
            orig_offer_cash=self.offer_cash,
            orig_req_cash=self.req_cash,
        )
        # Pre-fill property hints as placeholder text in the modal labels
        if self.req_props:
            modal.offered_props.default = ", ".join(
                self.game.board[p].get("city", self.game.board[p]["name"]) for p in self.req_props
            )
        if self.offer_props:
            modal.requested_props.default = ", ".join(
                self.game.board[p].get("city", self.game.board[p]["name"]) for p in self.offer_props
            )

        await interaction.response.send_modal(modal)

    @discord.ui.button(label="❌ Decline Deal", style=discord.ButtonStyle.red, custom_id="trade_decline")
    async def decline_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id and interaction.user.id != self.sender.id:
            await interaction.response.send_message("You cannot reject this proposal!", ephemeral=True)
            return

        self.disable_all_items()
        self.stop()
        text = f"❌ **Trade Declined:** The trade offer between **{self.sender.display_name}** and **{self.target.display_name}** was declined."
        await interaction.response.edit_message(content=text, view=self, embed=None)
