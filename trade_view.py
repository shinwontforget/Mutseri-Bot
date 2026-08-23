import discord

class TradeProposalView(discord.ui.View):
    def __init__(self, game, sender: discord.Member, target: discord.Member, offer_props: list[int], offer_cash: int, req_props: list[int], req_cash: int):
        super().__init__(timeout=90.0)  # 90-second trade limit
        self.game = game
        self.sender = sender
        self.target = target
        self.offer_props = offer_props
        self.offer_cash = offer_cash
        self.req_props = req_props
        self.req_cash = req_cash
        self.message: discord.Message | None = None

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

        sender_state = self.game.get_player_state(self.sender.id)
        target_state = self.game.get_player_state(self.target.id)

        if sender_state["money"] < self.offer_cash:
            await interaction.response.send_message(f"{self.sender.display_name} no longer has enough cash (${self.offer_cash})!", ephemeral=True)
            return
        if target_state["money"] < self.req_cash:
            await interaction.response.send_message(f"{self.target.display_name} does not have enough cash (${self.req_cash})!", ephemeral=True)
            return

        # Check that properties are still owned and not built on (in Monopoly, cannot trade properties with houses)
        for p in self.offer_props:
            if p not in sender_state["properties"]:
                await interaction.response.send_message(f"{self.sender.display_name} no longer owns {self.game.board[p]['name']}!", ephemeral=True)
                return
            if self.game.board[p].get("houses", 0) > 0:
                await interaction.response.send_message(f"Cannot trade {self.game.board[p]['name']} while it still has houses built on it!", ephemeral=True)
                return

        for p in self.req_props:
            if p not in target_state["properties"]:
                await interaction.response.send_message(f"{self.target.display_name} no longer owns {self.game.board[p]['name']}!", ephemeral=True)
                return
            if self.game.board[p].get("houses", 0) > 0:
                await interaction.response.send_message(f"Cannot trade {self.game.board[p]['name']} while it still has houses built on it!", ephemeral=True)
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

        self.game.log_event(f"🤝 TRADE COMPLETED between {self.sender.display_name} and {self.target.display_name}!")
        self.disable_all_items()
        
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

    @discord.ui.button(label="❌ Decline Deal", style=discord.ButtonStyle.red, custom_id="trade_decline")
    async def decline_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id and interaction.user.id != self.sender.id:
            await interaction.response.send_message("You cannot reject this proposal!", ephemeral=True)
            return

        self.disable_all_items()
        text = f"❌ **Trade Declined:** The trade offer between **{self.sender.display_name}** and **{self.target.display_name}** was declined."
        await interaction.response.edit_message(content=text, view=self, embed=None)

    def disable_all_items(self):
        for item in self.children:
            item.disabled = True

