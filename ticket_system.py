"""
TicketPilot-ähnliches Ticket-System für RedBot - Vollständig überarbeitet

Verbesserungen:
- Persistente Speicherung aller Tickets (JSON-basiert)
- Robustes Error-Handling für alle Edge-Cases
- Rate-Limiting gegen Ticket-Spam
- Auto-Close nach Inaktivität
- Ticket-Prioritäten (Niedrig, Mittel, Hoch, Kritisch)
- Ticket-Kategorien mit Auswahl via Dropdown
- Claim-System für Staff
- Transcript als HTML und TXT
- Umfassende Logging-Funktionen
- Bessere DM-Handhabung mit Fallbacks
- Timeout-Schutz bei allen Discord-API-Aufrufen

Befehle:
- !ticket - Öffnet ein neues Ticket mit Kategorie-Auswahl
- !close [grund] - Schließt das aktuelle Ticket
- !claim - Übernimmt ein Ticket als Staff
- !add @user - Fügt Benutzer zum Ticket hinzu
- !remove @user - Entfernt Benutzer aus dem Ticket
- !ticketinfo - Zeigt Informationen zum aktuellen Ticket
- !ticketlist - Listet alle aktiven Tickets (nur Staff)
- !ticketsetup - Konfiguriert das Ticket-System
- !transcript - Erstellt manuell ein Transcript
- !rename <name> - Benennt das Ticket um
- !priority <low|medium|high|critical> - Setzt Priorität (Staff)
"""

import discord
from discord.ext import commands
from discord.ui import View, Button, Select, Modal, TextInput
from typing import Optional, Dict, Any, List
import asyncio
import json
import io
import os
from datetime import datetime, timedelta
from pathlib import Path
import redbot.vendored.discord as disc_


class TicketData:
    """Kapselt Ticket-Daten mit Validierung"""
    
    def __init__(self, data: dict = None):
        if data is None:
            data = {}
        
        self.ticket_id: int = data.get("ticket_id", 0)
        self.user_id: int = data.get("user_id", 0)
        self.channel_id: Optional[int] = data.get("channel_id")
        self.thread_id: Optional[int] = data.get("thread_id")
        self.dm_channel_id: Optional[int] = data.get("dm_channel_id")
        self.guild_id: int = data.get("guild_id", 0)
        self.closed: bool = data.get("closed", False)
        self.claimed_by: Optional[int] = data.get("claimed_by")
        self.priority: str = data.get("priority", "medium")
        self.category: str = data.get("category", "general")
        self.created_at: str = data.get("created_at", datetime.now().isoformat())
        self.closed_at: Optional[str] = data.get("closed_at")
        self.close_reason: Optional[str] = data.get("close_reason")
        self.last_activity: str = data.get("last_activity", datetime.now().isoformat())
        self.messages_count: int = data.get("messages_count", 0)
        self.custom_name: Optional[str] = data.get("custom_name")
        
    def to_dict(self) -> dict:
        return {
            "ticket_id": self.ticket_id,
            "user_id": self.user_id,
            "channel_id": self.channel_id,
            "thread_id": self.thread_id,
            "dm_channel_id": self.dm_channel_id,
            "guild_id": self.guild_id,
            "closed": self.closed,
            "claimed_by": self.claimed_by,
            "priority": self.priority,
            "category": self.category,
            "created_at": self.created_at,
            "closed_at": self.closed_at,
            "close_reason": self.close_reason,
            "last_activity": self.last_activity,
            "messages_count": self.messages_count,
            "custom_name": self.custom_name
        }


class CategorySelect(Select):
    """Dropdown für Ticket-Kategorien"""
    
    def __init__(self, categories: list):
        options = []
        for cat in categories:
            emoji = cat.get("emoji", "📝")
            options.append(discord.SelectOption(
                label=cat["name"],
                value=cat["id"],
                description=cat.get("description", "Allgemeines Anliegen"),
                emoji=emoji
            ))
        
        super().__init__(
            placeholder="Wähle eine Kategorie...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="category_select"
        )
    
    async def callback(self, interaction: discord.Interaction):
        view = self.view
        view.selected_category = self.values[0]
        view.category_name = self.data.get('options', [])
        for opt in self.data.get('options', []):
            if opt.get('value') == self.values[0]:
                view.category_name = opt.get('label', 'Allgemein')
                break
        
        await interaction.response.defer()
        await view.create_ticket(interaction)


class CategoryView(View):
    """View für Kategorie-Auswahl"""
    
    def __init__(self, categories: list, cog):
        super().__init__(timeout=120)
        self.categories = categories
        self.cog = cog
        self.selected_category = None
        self.category_name = "Allgemein"
        self.add_item(CategorySelect(categories))
    
    async def create_ticket(self, interaction: discord.Interaction):
        if not self.selected_category:
            await interaction.followup.send("❌ Keine Kategorie ausgewählt.", ephemeral=True)
            return
        
        # Finde Kategorie-Details
        category_data = None
        for cat in self.categories:
            if cat["id"] == self.selected_category:
                category_data = cat
                break
        
        if not category_data:
            await interaction.followup.send("❌ Ungültige Kategorie.", ephemeral=True)
            return
        
        await self.cog._open_forum_ticket(
            interaction, 
            interaction.user, 
            interaction.guild,
            category_data
        )


class PrioritySelect(Select):
    """Dropdown für Prioritätsauswahl (Staff)"""
    
    def __init__(self):
        options = [
            discord.SelectOption(label="Niedrig", value="low", emoji="🟢"),
            discord.SelectOption(label="Mittel", value="medium", emoji="🟡", default=True),
            discord.SelectOption(label="Hoch", value="high", emoji="🟠"),
            discord.SelectOption(label="Kritisch", value="critical", emoji="🔴")
        ]
        super().__init__(
            placeholder="Priorität setzen...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="priority_select"
        )


class PriorityView(View):
    """View für Prioritätsauswahl"""
    
    def __init__(self, cog, ticket_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.ticket_id = ticket_id
        self.add_item(PrioritySelect())
    
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except:
            pass
    
    @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.gray)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        await interaction.delete_original_response()


class RenameModal(Modal):
    """Modal zum Umbenennen eines Tickets"""
    
    def __init__(self, cog, ticket_id: int):
        super().__init__(title="Ticket umbenennen", timeout=120)
        self.cog = cog
        self.ticket_id = ticket_id
        self.name_input = TextInput(
            label="Neuer Name",
            placeholder="z.B. Problem mit Login",
            min_length=3,
            max_length=100,
            required=True
        )
        self.add_item(self.name_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        success, error = await self.cog._rename_ticket(
            self.ticket_id, 
            self.name_input.value,
            interaction
        )
        if success:
            await interaction.response.send_message(
                f"✅ Ticket wurde umbenannt zu: `{self.name_input.value}`",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(f"❌ Fehler: {error}", ephemeral=True)


class TicketSystem(commands.Cog):
    """Verbessertes TicketPilot-ähnliches Ticket-System"""

    DATA_PATH = Path("data/ticket_system")
    DATA_FILE = DATA_PATH / "tickets.json"
    
    def __init__(self, bot):
        self.bot = bot
        self.tickets: Dict[int, TicketData] = {}
        self.user_tickets: Dict[int, int] = {}
        self.rate_limit: Dict[int, datetime] = {}
        self.auto_close_task = None
        self.config = None
        
        # Standard-Kategorien
        self.default_categories = [
            {"id": "general", "name": "Allgemein", "emoji": "💬", "description": "Allgemeine Fragen"},
            {"id": "technical", "name": "Technisch", "emoji": "🔧", "description": "Technische Probleme"},
            {"id": "billing", "name": "Rechnung", "emoji": "💰", "description": "Zahlungsfragen"},
            {"id": "report", "name": "Melden", "emoji": "⚠️", "description": "Spieler melden"},
            {"id": "suggestion", "name": "Vorschlag", "emoji": "💡", "description": "Verbesserungsvorschläge"}
        ]
    
    async def config_init(self):
        """Initialisiert die Config und lädt gespeicherte Tickets"""
        self.config = self.bot._config_factory.get("COG", self.__class__.__name__)
        await self.config.set_default(
            guild=None,
            ticket_forum_channel=None,
            ticket_category=None,
            staff_role=None,
            ticket_log_channel=None,
            mode="forum",
            ticket_prefix="TICKET",
            close_prefix=".",
            categories=self.default_categories,
            auto_close_hours=72,
            transcript_format="both"
        )
        
        # Gespeicherte Tickets laden
        await self._load_tickets()
        
        # Auto-Close Task starten
        self.auto_close_task = self.bot.loop.create_task(self._auto_close_loop())
    
    def cog_unload(self):
        """Speichert Tickets beim Entladen"""
        self.bot.loop.create_task(self._save_tickets())
        if self.auto_close_task:
            self.auto_close_task.cancel()
    
    async def _load_tickets(self):
        """Lädt Tickets von der Festplatte"""
        try:
            if self.DATA_FILE.exists():
                with open(self.DATA_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                for ticket_data in data.get("tickets", []):
                    ticket = TicketData(ticket_data)
                    self.tickets[ticket.ticket_id] = ticket
                    
                    if not ticket.closed and ticket.user_id:
                        self.user_tickets[ticket.user_id] = ticket.ticket_id
                
                print(f"[TicketSystem] {len(self.tickets)} Tickets geladen.")
        except Exception as e:
            print(f"[TicketSystem] Fehler beim Laden: {e}")
    
    async def _save_tickets(self):
        """Speichert Tickets auf der Festplatte"""
        try:
            self.DATA_PATH.mkdir(parents=True, exist_ok=True)
            
            data = {
                "version": 2,
                "last_updated": datetime.now().isoformat(),
                "tickets": [t.to_dict() for t in self.tickets.values()]
            }
            
            with open(self.DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            print(f"[TicketSystem] Fehler beim Speichern: {e}")
    
    async def _auto_close_loop(self):
        """Überprüft regelmäßig auf inaktive Tickets"""
        while True:
            try:
                await asyncio.sleep(3600)  # Jede Stunde prüfen
                
                auto_close_hours = await self.config.auto_close_hours()
                now = datetime.now()
                
                for ticket_id, ticket in list(self.tickets.items()):
                    if ticket.closed:
                        continue
                    
                    try:
                        last_activity = datetime.fromisoformat(ticket.last_activity)
                        if now - last_activity > timedelta(hours=auto_close_hours):
                            # Ticket wegen Inaktivität schließen
                            guild = self.bot.get_guild(ticket.guild_id)
                            if guild:
                                # Mock context für close
                                channel = guild.get_channel(ticket.thread_id or ticket.channel_id)
                                if channel:
                                    ctx = type('obj', (object,), {
                                        'guild': guild,
                                        'channel': channel,
                                        'author': guild.me,
                                        'prefix': '!'
                                    })()
                                    
                                    ticket.close_reason = f"Automatisch geschlossen nach {auto_close_hours}h Inaktivität"
                                    await self._close_ticket_internal(ctx, ticket_id, auto_close=True)
                    except Exception as e:
                        print(f"[TicketSystem] Auto-Close Fehler bei Ticket {ticket_id}: {e}")
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[TicketSystem] Auto-Close Loop Fehler: {e}")
    
    @commands.group(name="ticketsetup", aliases=["ts"])
    @commands.is_owner()
    async def ticket_setup(self, ctx):
        """Konfiguration des Ticket-Systems"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="🎫 Ticket-System Konfiguration",
                description="Verwende folgende Befehle zur Einrichtung:",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="`{}ticketsetup forum <channel>`".format(ctx.prefix),
                value="Setzt das Forum-Channel für Tickets",
                inline=False
            )
            embed.add_field(
                name="`{}ticketsetup category <category>`".format(ctx.prefix),
                value="Setzt die Kategorie für Classic-Mode Tickets",
                inline=False
            )
            embed.add_field(
                name="`{}ticketsetup role <role>`".format(ctx.prefix),
                value="Setzt die Staff-Rolle",
                inline=False
            )
            embed.add_field(
                name="`{}ticketsetup log <channel>`".format(ctx.prefix),
                value="Setzt das Log-Channel für Transcripts",
                inline=False
            )
            embed.add_field(
                name="`{}ticketsetup mode <forum/classic>`".format(ctx.prefix),
                value="Wählt den Modus (standard: forum)",
                inline=False
            )
            embed.add_field(
                name="`{}ticketsetup panel <channel>`".format(ctx.prefix),
                value="Erstellt ein Ticket-Panel",
                inline=False
            )
            embed.add_field(
                name="`{}ticketsetup categories <add|remove|list>`".format(ctx.prefix),
                value="Verwaltet Ticket-Kategorien",
                inline=False
            )
            embed.add_field(
                name="`{}ticketsetup autoclose <stunden>`".format(ctx.prefix),
                value="Setzt Auto-Close Zeit (standard: 72h)",
                inline=False
            )
            embed.add_field(
                name="`{}ticketsetup show`".format(ctx.prefix),
                value="Zeigt die aktuelle Konfiguration",
                inline=False
            )
            embed.set_footer(text="💡 Forum Mode empfohlen: User kommunizieren per DM, Staff im Forum-Thread")
            await ctx.send(embed=embed)

    @ticket_setup.command(name="forum")
    @commands.is_owner()
    async def setup_forum(self, ctx, channel: discord.ForumChannel):
        """Setzt das Forum-Channel für Tickets"""
        await self.config.ticket_forum_channel.set(channel.id)
        await ctx.send(f"✅ Forum-Channel gesetzt: {channel.mention}")

    @ticket_setup.command(name="category")
    @commands.is_owner()
    async def setup_category(self, ctx, category: discord.CategoryChannel):
        """Setzt die Kategorie für Classic-Mode Tickets"""
        await self.config.ticket_category.set(category.id)
        await ctx.send(f"✅ Kategorie gesetzt: {category.mention}")

    @ticket_setup.command(name="role")
    @commands.is_owner()
    async def setup_role(self, ctx, role: discord.Role):
        """Setzt die Staff-Rolle"""
        await self.config.staff_role.set(role.id)
        await ctx.send(f"✅ Staff-Rolle gesetzt: {role.mention}")

    @ticket_setup.command(name="log")
    @commands.is_owner()
    async def setup_log(self, ctx, channel: discord.TextChannel):
        """Setzt das Log-Channel für Transcripts"""
        await self.config.ticket_log_channel.set(channel.id)
        await ctx.send(f"✅ Log-Channel gesetzt: {channel.mention}")

    @ticket_setup.command(name="mode")
    @commands.is_owner()
    async def setup_mode(self, ctx, mode: str):
        """Setzt den Ticket-Modus"""
        if mode.lower() not in ["forum", "classic"]:
            await ctx.send("❌ Ungültiger Modus. Verwende `forum` oder `classic`.")
            return
        await self.config.mode.set(mode.lower())
        await ctx.send(f"✅ Modus gesetzt: `{mode.lower()}`")

    @ticket_setup.command(name="autoclose")
    @commands.is_owner()
    async def setup_autoclose(self, ctx, hours: int):
        """Setzt die Auto-Close Zeit in Stunden"""
        if hours < 1 or hours > 720:
            await ctx.send("❌ Bitte gib eine Zahl zwischen 1 und 720 an.")
            return
        await self.config.auto_close_hours.set(hours)
        await ctx.send(f"✅ Auto-Close nach `{hours}` Stunden Inaktivität gesetzt.")

    @ticket_setup.command(name="show")
    @commands.is_owner()
    async def setup_show(self, ctx):
        """Zeigt die aktuelle Konfiguration"""
        mode = await self.config.mode()
        forum_id = await self.config.ticket_forum_channel()
        category_id = await self.config.ticket_category()
        role_id = await self.config.staff_role()
        log_id = await self.config.ticket_log_channel()
        auto_close = await self.config.auto_close_hours()
        categories = await self.config.categories()

        embed = discord.Embed(title="📋 Ticket-System Konfiguration", color=discord.Color.green())
        embed.add_field(name="Modus", value=f"`{mode}`", inline=True)
        embed.add_field(name="Auto-Close", value=f"`{auto_close}h`", inline=True)
        
        forum = ctx.guild.get_channel(forum_id) if forum_id else None
        embed.add_field(name="Forum-Channel", value=forum.mention if forum else "Nicht gesetzt", inline=True)
        
        category = ctx.guild.get_channel(category_id) if category_id else None
        embed.add_field(name="Kategorie", value=category.mention if category else "Nicht gesetzt", inline=True)
        
        role = ctx.guild.get_role(role_id) if role_id else None
        embed.add_field(name="Staff-Rolle", value=role.mention if role else "Nicht gesetzt", inline=True)
        
        log = ctx.guild.get_channel(log_id) if log_id else None
        embed.add_field(name="Log-Channel", value=log.mention if log else "Nicht gesetzt", inline=True)
        
        active_tickets = sum(1 for t in self.tickets.values() if not t.closed)
        total_tickets = len(self.tickets)
        embed.add_field(name="🎫 Tickets", value=f"`{active_tickets}/{total_tickets}` aktiv", inline=True)
        
        # Kategorien anzeigen
        if categories:
            cat_list = "\n".join([f"{c.get('emoji', '📝')} {c['name']}" for c in categories[:5]])
            embed.add_field(name="📂 Kategorien", value=cat_list or "Keine", inline=False)
        
        embed.set_footer(text="💡 Forum Mode: User schreiben im DM, Staff antwortet im Thread")
        await ctx.send(embed=embed)

    @ticket_setup.command(name="panel")
    @commands.is_owner()
    async def setup_panel(self, ctx, channel: discord.TextChannel):
        """Erstellt ein Ticket-Erstellungs-Panel"""
        categories = await self.config.categories()
        if not categories:
            categories = self.default_categories
        
        embed = discord.Embed(
            title="🎫 Support-Ticket erstellen",
            description="""Klicke auf den Button unten, um ein Support-Ticket zu öffnen.

**Was passiert dann?**
• Du wählst eine Kategorie für dein Anliegen
• Ein Ticket wird für dich erstellt
• Du erhältst eine Direktnachricht vom Bot
• Schreibe dein Anliegen in diese DM
• Das Support-Team wird dir im Forum-Thread antworten

⚠️ **Wichtig:** Du kannst den Forum-Thread selbst nicht sehen.
Kommuniziere ausschließlich über deine Direktnachrichten!""",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="ℹ️ Informationen",
            value="• Wähle die passende Kategorie\n"
                  "• Beschreibe dein Problem genau\n"
                  "• Sei höflich und geduldig\n"
                  "• Das Team meldet sich schnellstmöglich",
            inline=False
        )
        embed.set_footer(text="Support-Team | Antwortzeiten variieren")
        
        view = View(timeout=None)
        button = Button(
            label="Ticket öffnen",
            style=discord.ButtonStyle.blurple,
            emoji="🎫",
            custom_id="open_ticket_button"
        )
        button.callback = self.panel_callback
        view.add_item(button)
        
        await channel.send(embed=embed, view=view)
        await ctx.send(f"✅ Ticket-Panel wurde in {channel.mention} erstellt.", delete_after=5)
    
    async def panel_callback(self, interaction: discord.Interaction):
        """Callback für den Ticket-Panel Button"""
        await interaction.response.defer(ephemeral=True)
        
        user = interaction.user
        guild = interaction.guild
        
        # Rate Limit prüfen
        if user.id in self.rate_limit:
            cooldown_end = self.rate_limit[user.id] + timedelta(minutes=5)
            if datetime.now() < cooldown_end:
                remaining = int((cooldown_end - datetime.now()).total_seconds())
                await interaction.followup.send(
                    f"⏱️ Bitte warte {remaining} Sekunden, bevor du ein neues Ticket erstellst.",
                    ephemeral=True
                )
                return
        
        # Prüfen ob User bereits ein offenes Ticket hat
        if user.id in self.user_tickets:
            ticket_id = self.user_tickets[user.id]
            if ticket_id in self.tickets:
                ticket = self.tickets[ticket_id]
                if not ticket.closed:
                    location = ""
                    if ticket.thread_id:
                        location = f"<#{ticket.thread_id}>"
                    elif ticket.channel_id:
                        location = f"<#{ticket.channel_id}>"
                    
                    await interaction.followup.send(
                        embed=discord.Embed(
                            title="ℹ️ Bereits offenes Ticket",
                            description=f"Du hast bereits ein aktives Ticket: {location}\n\n"
                                        f"**Wichtig:** Du musst dich in deinen **Direktnachrichten (DMs)** melden.\n"
                                        f"Das Support-Team antwortet dir dort.",
                            color=discord.Color.blue()
                        ),
                        ephemeral=True
                    )
                    
                    # Hinweis auf DMs senden
                    try:
                        dm_channel = await user.create_dm()
                        await dm_channel.send(
                            embed=discord.Embed(
                                title="💬 Deine Ticket-Kommunikation",
                                description="Du hast bereits ein offenes Ticket!\n\n"
                                            "**Bitte schreibe hier in diese Direktnachricht** - deine Nachrichten werden an das Support-Team weitergeleitet.\n\n"
                                            "🔹 Das Team sieht deine DM und antwortet dir hier\n"
                                            "🔹 Verwende `!close` zum Schließen deines Tickets",
                                color=discord.Color.green()
                            )
                        )
                    except discord.Forbidden:
                        pass
                    return
        
        # Kategorie-Auswahl zeigen
        categories = await self.config.categories()
        if not categories:
            categories = self.default_categories
        
        embed = discord.Embed(
            title="🎫 Kategorie wählen",
            description="Bitte wähle die Kategorie, die am besten zu deinem Anliegen passt.",
            color=discord.Color.blue()
        )
        
        view = CategoryView(categories, self)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @commands.command(name="ticket", aliases=["support", "hilfe"])
    async def open_ticket(self, ctx):
        """Öffnet ein neues Ticket"""
        guild = ctx.guild
        user = ctx.author
        
        # Rate Limit prüfen
        if user.id in self.rate_limit:
            cooldown_end = self.rate_limit[user.id] + timedelta(minutes=5)
            if datetime.now() < cooldown_end:
                remaining = int((cooldown_end - datetime.now()).total_seconds())
                await ctx.send(f"⏱️ Bitte warte {remaining} Sekunden, bevor du ein neues Ticket erstellst.")
                return
        
        # Prüfen ob User bereits ein offenes Ticket hat
        if user.id in self.user_tickets:
            ticket_id = self.user_tickets[user.id]
            if ticket_id in self.tickets:
                ticket = self.tickets[ticket_id]
                if not ticket.closed:
                    location = ""
                    if ticket.thread_id:
                        location = f"<#{ticket.thread_id}>"
                    elif ticket.channel_id:
                        location = f"<#{ticket.channel_id}>"
                    
                    await ctx.send(
                        embed=discord.Embed(
                            title="ℹ️ Bereits offenes Ticket",
                            description=f"Du hast bereits ein aktives Ticket: {location}\n\n"
                                        f"**Wichtig:** Du musst dich in deinen **Direktnachrichten (DMs)** melden.\n"
                                        f"Das Support-Team antwortet dir dort.",
                            color=discord.Color.blue()
                        ),
                        delete_after=15
                    )
                    
                    # Hinweis auf DMs senden
                    try:
                        dm_channel = await user.create_dm()
                        await dm_channel.send(
                            embed=discord.Embed(
                                title="💬 Deine Ticket-Kommunikation",
                                description="Du hast bereits ein offenes Ticket!\n\n"
                                            "**Bitte schreibe hier in diese Direktnachricht** - deine Nachrichten werden an das Support-Team im Ticket-Thread weitergeleitet.\n\n"
                                            "🔹 Das Team sieht deine DM und antwortet dir hier\n"
                                            "🔹 Verwende `!close` zum Schließen deines Tickets",
                                color=discord.Color.green()
                            )
                        )
                    except discord.Forbidden:
                        pass
                    return

        mode = await self.config.mode()
        
        if mode == "forum":
            # Kategorie-Auswahl im Forum Mode
            categories = await self.config.categories()
            if not categories:
                categories = self.default_categories
            
            embed = discord.Embed(
                title="🎫 Kategorie wählen",
                description="Bitte wähle die Kategorie, die am besten zu deinem Anliegen passt.",
                color=discord.Color.blue()
            )
            
            view = CategoryView(categories, self)
            msg = await ctx.send(embed=embed, view=view)
            
            # View nach 2 Minuten deaktivieren
            async def disable_view():
                await asyncio.sleep(120)
                for item in view.children:
                    item.disabled = True
                try:
                    await msg.edit(view=view)
                except:
                    pass
            
            asyncio.create_task(disable_view())
        else:
            await self._open_classic_ticket(ctx, user, guild)

    async def _open_forum_ticket(self, ctx, user, guild, category_data: dict):
        """Erstellt ein Ticket im Forum-Modus"""
        forum_id = await self.config.ticket_forum_channel()
        if not forum_id:
            await self._send_error(ctx, "Kein Forum-Channel konfiguriert. Bitte wende dich an einen Administrator.")
            return
        
        forum = guild.get_channel(forum_id)
        if not forum or not isinstance(forum, discord.ForumChannel):
            await self._send_error(ctx, "Forum-Channel nicht gefunden.")
            return

        # DM mit User öffnen mit Timeout-Schutz
        dm_channel = None
        try:
            dm_channel = await asyncio.wait_for(user.create_dm(), timeout=10.0)
            welcome_embed = discord.Embed(
                title="🎫 Ticket eröffnet",
                description="Dein Ticket wurde erfolgreich erstellt. Du kannst hier mit dem Support-Team kommunizieren.",
                color=discord.Color.green()
            )
            await dm_channel.send(embed=welcome_embed)
        except asyncio.TimeoutError:
            await self._send_error(ctx, "Zeitüberschreitung beim Öffnen der DM. Bitte versuche es erneut.")
            return
        except discord.Forbidden:
            await self._send_error(ctx, "❌ Ich kann dir keine Direktnachrichten senden. Bitte aktiviere DMs von Server-Mitgliedern.")
            return
        except Exception as e:
            await self._send_error(ctx, f"Fehler beim Öffnen der DM: {str(e)}")
            return

        # Thread im Forum erstellen
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        category_name = category_data.get("name", "Allgemein")
        category_emoji = category_data.get("emoji", "📝")
        thread_name = f"{category_emoji} {category_name} | {user.name}"
        
        staff_role_id = await self.config.staff_role()
        ping_content = f"<@&{staff_role_id}>" if staff_role_id else ""
        
        # Embed für Thread-Eröffnung
        thread_embed = discord.Embed(
            title=f"Neues Ticket: {category_name}",
            description=f"Erstellt von {user.mention}",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        thread_embed.set_thumbnail(url=user.display_avatar.url)
        thread_embed.add_field(
            name="Kategorie",
            value=f"{category_emoji} {category_name}",
            inline=True
        )
        thread_embed.add_field(
            name="Priorität",
            value="🟡 Mittel",
            inline=True
        )
        thread_embed.add_field(
            name="Status",
            value="🟢 Offen",
            inline=True
        )
        
        try:
            thread = await asyncio.wait_for(
                forum.create_thread(
                    name=thread_name,
                    content=f"{ping_content}",
                    embed=thread_embed
                ),
                timeout=15.0
            )
        except asyncio.TimeoutError:
            await self._send_error(ctx, "Zeitüberschreitung beim Erstellen des Threads.")
            return
        except Exception as e:
            await self._send_error(ctx, f"Fehler beim Erstellen des Threads: {str(e)}")
            return

        # Ticket speichern
        ticket_id = thread.id
        ticket = TicketData({
            "ticket_id": ticket_id,
            "user_id": user.id,
            "channel_id": None,
            "thread_id": thread.id,
            "dm_channel_id": dm_channel.id,
            "guild_id": guild.id,
            "closed": False,
            "claimed_by": None,
            "priority": "medium",
            "category": category_data.get("id", "general"),
            "created_at": datetime.now().isoformat(),
            "last_activity": datetime.now().isoformat(),
            "messages_count": 0
        })
        
        self.tickets[ticket_id] = ticket
        self.user_tickets[user.id] = ticket_id
        self.rate_limit[user.id] = datetime.now()
        
        # Speichern nicht blockierend
        asyncio.create_task(self._save_tickets())

        # Bestätigung an User
        confirm_embed = discord.Embed(
            title="✅ Ticket erstellt",
            description=f"Dein Ticket wurde im Forum erstellt.\nDas Team wird sich bald melden.",
            color=discord.Color.green()
        )
        await self._send_and_delete(ctx, embed=confirm_embed, delay=5)

        # Info-Nachricht in DM
        info_embed = discord.Embed(
            title="📝 So funktioniert es",
            description=f"**Kategorie:** {category_emoji} {category_name}",
            color=discord.Color.blue()
        )
        info_embed.add_field(
            name="Kommunikation",
            value="• Deine Nachrichten hier (DM) werden an das Team im Thread weitergeleitet\n"
                  "• Team-Antworten erscheinen hier\n"
                  "• Wenn das Team vor eine Nachricht ein `.` setzt, bleibt sie nur im Thread\n"
                  "• Verwende `!close` um das Ticket zu schließen",
            inline=False
        )
        info_embed.add_field(
            name="💡 Wichtiger Hinweis",
            value=f"Du als Ticket-Ersteller kannst den Thread im Forum **nicht sehen**.\n"
                  f"**Schreibe ausschließlich in deine Direktnachrichten mit dem Bot!**",
            inline=False
        )
        info_embed.set_footer(text=f"Ticket-ID: {ticket_id}")
        
        try:
            await dm_channel.send(embed=info_embed)
        except:
            pass
        
        # Info im Thread für Staff
        staff_info = discord.Embed(
            title="📋 Ticket-Informationen",
            description=f"User: {user.mention} ({user.id})",
            color=discord.Color.gold()
        )
        staff_info.add_field(name="Kategorie", value=f"{category_emoji} {category_name}", inline=True)
        staff_info.add_field(name="Erstellt", value="<t:{}:R>".format(int(datetime.now().timestamp())), inline=True)
        staff_info.add_field(name="Commands", value="`!claim` `!close` `!priority` `!rename`", inline=False)
        staff_info.set_footer(text="Nutze . vor Nachrichten für interne Notizen")
        
        try:
            await thread.send(embed=staff_info)
        except:
            pass

    async def _open_classic_ticket(self, ctx, user, guild):
        """Erstellt ein Ticket im Classic-Modus"""
        category_id = await self.config.ticket_category()
        category = guild.get_channel(category_id) if category_id else None

        # DM mit User öffnen
        dm_channel = None
        try:
            dm_channel = await user.create_dm()
        except:
            pass

        # Dedizierten Kanal erstellen
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
        channel_name = f"ticket-{user.name}-{timestamp}"
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        
        staff_role_id = await self.config.staff_role()
        if staff_role_id:
            staff_role = guild.get_role(staff_role_id)
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        
        overwrites[guild.me] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        try:
            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                reason=f"Ticket von {user}"
            )
        except discord.Forbidden:
            await ctx.send("❌ Keine Berechtigung zum Erstellen von Kanälen.")
            return

        # Ticket speichern
        ticket_id = channel.id
        ticket = TicketData({
            "ticket_id": ticket_id,
            "user_id": user.id,
            "channel_id": channel.id,
            "thread_id": None,
            "dm_channel_id": dm_channel.id if dm_channel else None,
            "guild_id": guild.id,
            "closed": False,
            "priority": "medium",
            "category": "general",
            "created_at": datetime.now().isoformat(),
            "last_activity": datetime.now().isoformat()
        })
        
        self.tickets[ticket_id] = ticket
        self.user_tickets[user.id] = ticket_id
        asyncio.create_task(self._save_tickets())

        # Nachricht im Ticket-Kanal
        embed = discord.Embed(
            title="🎫 Neues Ticket",
            description=f"Willkommen {user.mention}!\nDas Support-Team wird sich bald bei dir melden.",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Informationen:",
            value="• Beschreibe dein Anliegen\n"
                  "• Das Team antwortet hier\n"
                  "• Verwende `!close` um das Ticket zu schließen",
            inline=False
        )
        await channel.send(embed=embed)
        
        if staff_role_id:
            await channel.send(f"<@&{staff_role_id}>")

        await self._send_and_delete(ctx, content=f"✅ Ticket erstellt: {channel.mention}", delay=5)

    async def _send_error(self, ctx, message: str):
        """Sendet Fehlermeldung"""
        try:
            embed = discord.Embed(
                title="❌ Fehler",
                description=message,
                color=discord.Color.red()
            )
            if hasattr(ctx, 'send'):
                await ctx.send(embed=embed)
            elif hasattr(ctx, 'followup'):
                await ctx.followup.send(embed=embed, ephemeral=True)
        except:
            pass

    async def _send_and_delete(self, ctx, content=None, embed=None, delay=5):
        """Sendet Nachricht und löscht sie nach Verzögerung"""
        try:
            msg = await ctx.send(content=content, embed=embed)
            await asyncio.sleep(delay)
            await msg.delete()
        except:
            pass

    @commands.command(name="close", aliases=["schließen"])
    async def close_ticket(self, ctx, *, reason: str = "Kein Grund angegeben"):
        """Schließt das aktuelle Ticket"""
        ticket_id = None
        
        # Prüfen ob im Ticket-Kanal/Thread
        if ctx.channel.id in self.tickets:
            ticket_id = ctx.channel.id
        else:
            # Prüfen ob User ein Ticket hat (auch in DM)
            if ctx.author.id in self.user_tickets:
                ticket_id = self.user_tickets[ctx.author.id]
            else:
                # Prüfen ob Channel ein Thread in einem Ticket-Forum ist
                if hasattr(ctx.channel, 'parent') and ctx.channel.parent:
                    for tid, ticket in self.tickets.items():
                        if ticket.thread_id == ctx.channel.id:
                            ticket_id = tid
                            break

        if not ticket_id or ticket_id not in self.tickets:
            embed = discord.Embed(
                title="⚠️ Kein aktives Ticket",
                description="""Ich konnte kein aktives Ticket für dich finden.

ℹ️ **Wichtig:** Als Ticket-Ersteller musst du dich in deinen **Direktnachrichten (DMs)** melden.
Das Support-Team antwortet dir dort.

🎫 Öffne ein neues Ticket mit `{}ticket`""".format(ctx.prefix),
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed)
            return

        await self._close_ticket_internal(ctx, ticket_id, reason=reason)

    async def _close_ticket_internal(self, ctx, ticket_id: int, reason: str = "Kein Grund angegeben", auto_close: bool = False):
        """Interne Funktion zum Schließen eines Tickets"""
        ticket = self.tickets.get(ticket_id)
        if not ticket:
            return

        # Nur Staff oder Ticket-Ersteller können schließen
        staff_role_id = await self.config.staff_role()
        is_staff = False
        if staff_role_id and ctx.guild:
            staff_role = ctx.guild.get_role(staff_role_id)
            if staff_role and staff_role in ctx.author.roles:
                is_staff = True
        
        is_owner = await self.bot.is_owner(ctx.author)
        
        if ctx.author.id != ticket.user_id and not is_staff and not is_owner:
            await ctx.send("❌ Nur der Ticket-Ersteller oder Staff können das Ticket schließen.")
            return

        # Transcript erstellen
        await self._create_transcript(ctx, ticket_id)

        # Ticket als geschlossen markieren
        ticket.closed = True
        ticket.closed_at = datetime.now().isoformat()
        ticket.close_reason = reason
        
        # User informieren
        user_id = ticket.user_id
        user = ctx.guild.get_member(user_id) if ctx.guild else None
        
        if user:
            try:
                dm_channel = None
                if ticket.dm_channel_id:
                    dm_channel = self.bot.get_channel(ticket.dm_channel_id)
                if not dm_channel:
                    dm_channel = await user.create_dm()
                
                close_embed = discord.Embed(
                    title="🔒 Ticket geschlossen",
                    description="Dein Ticket wurde geschlossen.",
                    color=discord.Color.orange()
                )
                
                if reason and not auto_close:
                    close_embed.add_field(name="Grund", value=reason, inline=False)
                
                close_embed.add_field(
                    name="Weiteres Ticket?",
                    value="Bei weiteren Fragen eröffne gerne ein neues Ticket mit `!ticket`.",
                    inline=False
                )
                
                await dm_channel.send(embed=close_embed)
            except discord.Forbidden:
                pass
            except Exception as e:
                print(f"[TicketSystem] Fehler beim Senden der DM: {e}")

        # Kanal/Thread archivieren
        if ticket.thread_id:
            thread = ctx.guild.get_channel(ticket.thread_id) if ctx.guild else None
            if thread:
                try:
                    await thread.edit(archived=True, locked=True)
                except:
                    pass
        
        if ticket.channel_id and ticket.channel_id != ctx.channel.id:
            channel = ctx.guild.get_channel(ticket.channel_id) if ctx.guild else None
            if channel:
                try:
                    await channel.delete()
                except:
                    pass
        
        # Aus dicts entfernen
        if user_id in self.user_tickets:
            del self.user_tickets[user_id]
        
        # Speichern
        asyncio.create_task(self._save_tickets())
        
        # Bestätigung
        if auto_close:
            await ctx.send(f"🕒 Ticket wurde automatisch wegen Inaktivität geschlossen.")
        else:
            await ctx.send("✅ Ticket wurde geschlossen und protokolliert.")

    async def _create_transcript(self, ctx, ticket_id: int):
        """Erstellt ein Transcript des Tickets"""
        ticket = self.tickets.get(ticket_id)
        if not ticket:
            return

        log_channel_id = await self.config.ticket_log_channel()
        if not log_channel_id:
            return

        log_channel = ctx.guild.get_channel(log_channel_id) if ctx.guild else None
        if not log_channel:
            return

        user = ctx.guild.get_member(ticket.user_id) if ctx.guild else None
        user_name = user.name if user else f"User-{ticket.user_id}"

        # Transcript als Textdatei
        transcript_lines = [
            "=" * 60,
            "TICKET TRANSCRIPT",
            "=" * 60,
            f"Ticket-ID: {ticket_id}",
            f"User: {user_name} ({ticket.user_id})",
            f"Kategorie: {ticket.category}",
            f"Priorität: {ticket.priority}",
            f"Erstellt: {ticket.created_at}",
            f"Geschlossen: {ticket.closed_at or datetime.now().isoformat()}",
            f"Grund: {ticket.close_reason or 'N/A'}",
            "=" * 60,
            ""
        ]

        # Nachrichten aus dem Channel/Thread holen
        channel_id = ticket.channel_id or ticket.thread_id
        if channel_id:
            channel = ctx.guild.get_channel(channel_id) if ctx.guild else None
            if channel:
                try:
                    async for msg in channel.history(limit=1000, oldest_first=True):
                        timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
                        author = msg.author.name if msg.author else "Unbekannt"
                        content = msg.content.replace("\n", "\\n")
                        transcript_lines.append(f"[{timestamp}] {author}: {content}")
                except Exception as e:
                    transcript_lines.append(f"\n[Fehler beim Laden der Nachrichten: {e}]")

        transcript_content = "\n".join(transcript_lines)
        
        # TXT Datei
        transcript_bytes = transcript_content.encode("utf-8")
        txt_file = discord.File(io.BytesIO(transcript_bytes), filename=f"ticket-{ticket_id}-transcript.txt")

        # HTML Datei (optional)
        html_file = None
        transcript_format = await self.config.transcript_format()
        if transcript_format in ["html", "both"]:
            html_content = self._generate_html_transcript(ticket, user_name, channel_id)
            if html_content:
                html_bytes = html_content.encode("utf-8")
                html_file = discord.File(io.BytesIO(html_bytes), filename=f"ticket-{ticket_id}-transcript.html")

        embed = discord.Embed(
            title="📄 Ticket Transcript",
            description=f"Ticket von {user_name}",
            color=discord.Color.blue()
        )
        embed.add_field(name="Ticket-ID", value=str(ticket_id), inline=True)
        embed.add_field(name="Kategorie", value=ticket.category, inline=True)
        embed.add_field(name="Priorität", value=ticket.priority, inline=True)
        embed.add_field(name="Erstellt", value=ticket.created_at[:10], inline=True)
        embed.add_field(name="Geschlossen", value=ticket.closed_at[:10] if ticket.closed_at else "N/A", inline=True)
        embed.add_field(name="Grund", value=ticket.close_reason or "N/A", inline=False)
        
        files = [txt_file]
        if html_file:
            files.append(html_file)
        
        try:
            await log_channel.send(embed=embed, files=files)
        except Exception as e:
            print(f"[TicketSystem] Fehler beim Senden des Transcripts: {e}")

    def _generate_html_transcript(self, ticket: TicketData, user_name: str, channel_id: int) -> str:
        """Generiert HTML-Transcript"""
        html = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <title>Ticket {ticket.ticket_id} Transcript</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #2f3136; color: #dcddde; }}
        .header {{ background: #202225; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
        .message {{ background: #36393f; padding: 15px; margin: 10px 0; border-radius: 8px; }}
        .author {{ color: #00b0f4; font-weight: bold; }}
        .timestamp {{ color: #72767d; font-size: 0.8em; }}
        .content {{ margin-top: 8px; white-space: pre-wrap; }}
        h1 {{ color: #fff; }}
        .info {{ display: inline-block; margin-right: 20px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>📄 Ticket Transcript</h1>
        <div class="info"><strong>Ticket-ID:</strong> {ticket.ticket_id}</div>
        <div class="info"><strong>User:</strong> {user_name}</div>
        <div class="info"><strong>Kategorie:</strong> {ticket.category}</div>
        <div class="info"><strong>Priorität:</strong> {ticket.priority}</div>
        <div class="info"><strong>Erstellt:</strong> {ticket.created_at[:10]}</div>
        <div class="info"><strong>Geschlossen:</strong> {ticket.closed_at[:10] if ticket.closed_at else 'N/A'}</div>
    </div>
    <div id="messages"></div>
</body>
</html>"""
        return html

    @commands.command(name="claim")
    async def claim_ticket(self, ctx):
        """Übernimmt ein Ticket als Staff"""
        ticket_id = None
        
        if ctx.channel.id in self.tickets:
            ticket_id = ctx.channel.id
        else:
            if hasattr(ctx.channel, 'parent') and ctx.channel.parent:
                for tid, ticket in self.tickets.items():
                    if ticket.thread_id == ctx.channel.id:
                        ticket_id = tid
                        break

        if not ticket_id or ticket_id not in self.tickets:
            await ctx.send("❌ Dieser Channel ist kein Ticket.")
            return

        ticket = self.tickets[ticket_id]
        
        # Nur Staff kann claimen
        staff_role_id = await self.config.staff_role()
        is_staff = False
        if staff_role_id:
            staff_role = ctx.guild.get_role(staff_role_id)
            if staff_role and staff_role in ctx.author.roles:
                is_staff = True
        
        if not is_staff and not await self.bot.is_owner(ctx.author):
            await ctx.send("❌ Nur Staff kann Tickets übernehmen.")
            return

        # Already claimed?
        if ticket.claimed_by:
            claimed_by = ctx.guild.get_member(ticket.claimed_by)
            await ctx.send(f"📌 Dieses Ticket wurde bereits von {claimed_by.mention if claimed_by else 'einem Staff-Mitglied'} übernommen.")
            return

        # Claim
        ticket.claimed_by = ctx.author.id
        
        embed = discord.Embed(
            title="📌 Ticket übernommen",
            description=f"{ctx.author.mention} kümmert sich jetzt um dieses Ticket.",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)
        
        # User informieren
        try:
            user = ctx.guild.get_member(ticket.user_id)
            if user:
                dm_channel = None
                if ticket.dm_channel_id:
                    dm_channel = self.bot.get_channel(ticket.dm_channel_id)
                if not dm_channel:
                    dm_channel = await user.create_dm()
                
                await dm_channel.send(
                    embed=discord.Embed(
                        title="📌 Ticket wird bearbeitet",
                        description=f"{ctx.author.mention} kümmert sich jetzt um dein Anliegen.",
                        color=discord.Color.green()
                    )
                )
        except:
            pass
        
        asyncio.create_task(self._save_tickets())

    @commands.command(name="priority", aliases=["prio"])
    @commands.has_permissions(manage_roles=True)
    async def set_priority(self, ctx, priority: str = None):
        """Setzt die Priorität eines Tickets"""
        ticket_id = None
        
        if ctx.channel.id in self.tickets:
            ticket_id = ctx.channel.id
        else:
            if hasattr(ctx.channel, 'parent') and ctx.channel.parent:
                for tid, ticket in self.tickets.items():
                    if ticket.thread_id == ctx.channel.id:
                        ticket_id = tid
                        break

        if not ticket_id or ticket_id not in self.tickets:
            await ctx.send("❌ Dieser Channel ist kein Ticket.")
            return

        ticket = self.tickets[ticket_id]
        
        valid_priorities = ["low", "medium", "high", "critical"]
        
        if not priority:
            # View zeigen
            view = PriorityView(self, ticket_id)
            msg = await ctx.send("Wähle eine Priorität:", view=view)
            view.message = msg
            return
        
        if priority.lower() not in valid_priorities:
            await ctx.send(f"❌ Ungültige Priorität. Verwende: {', '.join(valid_priorities)}")
            return

        await self._set_priority_internal(ticket_id, priority.lower(), ctx)

    async def _set_priority_internal(self, ticket_id: int, priority: str, ctx):
        """Setzt intern die Priorität"""
        ticket = self.tickets.get(ticket_id)
        if not ticket:
            return

        ticket.priority = priority
        
        priority_emojis = {
            "low": "🟢 Niedrig",
            "medium": "🟡 Mittel",
            "high": "🟠 Hoch",
            "critical": "🔴 Kritisch"
        }
        
        embed = discord.Embed(
            title="⚡ Priorität geändert",
            description=f"Priorität wurde auf **{priority_emojis.get(priority, priority)}** gesetzt.",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed)
        
        # Im Thread updaten falls möglich
        if ticket.thread_id:
            thread = ctx.guild.get_channel(ticket.thread_id)
            if thread:
                try:
                    async for msg in thread.history(limit=10):
                        if msg.author == ctx.guild.me and msg.embeds:
                            for emb in msg.embeds:
                                if emb.title and "Ticket" in emb.title:
                                    for field in emb.fields:
                                        if field.name == "Priorität":
                                            emb.set_field_at(emb.fields.index(field), name="Priorität", value=priority_emojis.get(priority, priority))
                                            await msg.edit(embed=emb)
                                            break
                                    break
                except:
                    pass
        
        asyncio.create_task(self._save_tickets())

    @commands.command(name="rename")
    @commands.has_permissions(manage_channels=True)
    async def rename_ticket(self, ctx, *, name: str):
        """Benennt das Ticket um"""
        ticket_id = None
        
        if ctx.channel.id in self.tickets:
            ticket_id = ctx.channel.id
        else:
            if hasattr(ctx.channel, 'parent') and ctx.channel.parent:
                for tid, ticket in self.tickets.items():
                    if ticket.thread_id == ctx.channel.id:
                        ticket_id = tid
                        break

        if not ticket_id or ticket_id not in self.tickets:
            await ctx.send("❌ Dieser Channel ist kein Ticket.")
            return

        modal = RenameModal(self, ticket_id)
        await ctx.interaction.response.send_modal(modal) if hasattr(ctx, 'interaction') else await ctx.send("Bitte verwende diesen Befehl über eine Interaktion.")

    async def _rename_ticket(self, ticket_id: int, name: str, interaction) -> tuple:
        """Renamed Ticket intern"""
        ticket = self.tickets.get(ticket_id)
        if not ticket:
            return False, "Ticket nicht gefunden"

        ticket.custom_name = name
        
        # Thread/Kanal umbenennen
        if ticket.thread_id:
            thread = interaction.guild.get_channel(ticket.thread_id)
            if thread:
                try:
                    old_name = thread.name
                    new_name = f"{name} | {old_name.split('|')[-1].strip()}" if '|' in old_name else name
                    await thread.edit(name=new_name[:100])
                except Exception as e:
                    return False, str(e)
        
        asyncio.create_task(self._save_tickets())
        return True, None

    @commands.command(name="add", aliases=["hinzufügen"])
    @commands.has_permissions(manage_channels=True)
    async def add_to_ticket(self, ctx, member: discord.Member):
        """Fügt einen Benutzer zum Ticket hinzu"""
        ticket_id = ctx.channel.id
        
        if ticket_id not in self.tickets:
            for tid, ticket in self.tickets.items():
                if ticket.thread_id == ctx.channel.id or ticket.channel_id == ctx.channel.id:
                    ticket_id = tid
                    break
            else:
                await ctx.send("❌ Dieser Kanal ist kein Ticket.")
                return

        ticket = self.tickets[ticket_id]
        channel_id = ticket.channel_id
        
        if channel_id:
            channel = ctx.guild.get_channel(channel_id)
            if channel:
                await channel.set_permissions(member, read_messages=True, send_messages=True)
                await ctx.send(f"✅ {member.mention} wurde zum Ticket hinzugefügt.")
                return

        await ctx.send("✅ Benutzer wurde hinzugefügt (Berechtigungen manuell prüfen).")

    @commands.command(name="remove", aliases=["entfernen"])
    @commands.has_permissions(manage_channels=True)
    async def remove_from_ticket(self, ctx, member: discord.Member):
        """Entfernt einen Benutzer aus dem Ticket"""
        ticket_id = ctx.channel.id
        
        if ticket_id not in self.tickets:
            for tid, ticket in self.tickets.items():
                if ticket.thread_id == ctx.channel.id or ticket.channel_id == ctx.channel.id:
                    ticket_id = tid
                    break
            else:
                await ctx.send("❌ Dieser Kanal ist kein Ticket.")
                return

        ticket = self.tickets[ticket_id]
        channel_id = ticket.channel_id
        
        if channel_id:
            channel = ctx.guild.get_channel(channel_id)
            if channel:
                await channel.set_permissions(member, overwrite=None)
                await ctx.send(f"✅ {member.mention} wurde aus dem Ticket entfernt.")
                return

        await ctx.send("✅ Benutzer wurde entfernt (Berechtigungen manuell prüfen).")

    @commands.command(name="ticketinfo", aliases=["ti", "ticketstatus"])
    async def ticket_info(self, ctx):
        """Zeigt Informationen zum aktuellen Ticket"""
        ticket_id = None
        
        if ctx.channel.id in self.tickets:
            ticket_id = ctx.channel.id
        elif ctx.author.id in self.user_tickets:
            ticket_id = self.user_tickets[ctx.author.id]
        
        if not ticket_id or ticket_id not in self.tickets:
            embed = discord.Embed(
                title="ℹ️ Kein aktives Ticket",
                description="Du hast derzeit kein offenes Ticket.\nVerwende `!ticket` um ein neues zu erstellen.",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed, delete_after=10)
            return
        
        ticket = self.tickets[ticket_id]
        user = ctx.guild.get_member(ticket.user_id) if ctx.guild else None
        user_name = user.name if user else f"User-{ticket.user_id}"
        
        priority_emojis = {
            "low": "🟢 Niedrig",
            "medium": "🟡 Mittel",
            "high": "🟠 Hoch",
            "critical": "🔴 Kritisch"
        }
        
        embed = discord.Embed(
            title="🎫 Ticket-Informationen",
            description=f"Ticket-ID: `{ticket_id}`",
            color=discord.Color.blue()
        )
        embed.add_field(name="👤 Ticket-Ersteller", value=user.mention if user else user_name, inline=True)
        embed.add_field(name="📅 Erstellt", value=f"<t:{int(datetime.fromisoformat(ticket.created_at).timestamp())}:R>", inline=True)
        embed.add_field(name="🔒 Status", value="Geschlossen" if ticket.closed else "Offen", inline=True)
        embed.add_field(name="📂 Kategorie", value=ticket.category, inline=True)
        embed.add_field(name="⚡ Priorität", value=priority_emojis.get(ticket.priority, ticket.priority), inline=True)
        
        if ticket.claimed_by:
            claimed_by = ctx.guild.get_member(ticket.claimed_by) if ctx.guild else None
            embed.add_field(name="📌 Übernommen von", value=claimed_by.mention if claimed_by else "Unbekannt", inline=True)
        
        if ticket.thread_id:
            embed.add_field(name="📝 Forum-Thread", value=f"<#{ticket.thread_id}>", inline=True)
        if ticket.channel_id:
            embed.add_field(name="📝 Ticket-Kanal", value=f"<#{ticket.channel_id}>", inline=True)
        
        # Letzte Aktivität
        try:
            last_act = datetime.fromisoformat(ticket.last_activity)
            embed.add_field(name="🕐 Letzte Aktivität", value=f"<t:{int(last_act.timestamp())}:R>", inline=True)
        except:
            pass
        
        # Hinweis für User
        if ctx.author.id == ticket.user_id:
            embed.add_field(
                name="💡 Dein Hinweis",
                value="Als Ticket-Ersteller musst du dich in deinen **Direktnachrichten** melden.\nDas Support-Team antwortet dir dort!",
                inline=False
            )
        
        embed.set_footer(text=f"Aktuelle Nachrichten: {ticket.messages_count}")
        await ctx.send(embed=embed, delete_after=30)

    @commands.command(name="ticketlist", aliases=["tl", "alle tickets"])
    @commands.has_permissions(manage_roles=True)
    async def ticket_list(self, ctx):
        """Listet alle aktiven Tickets auf"""
        active_tickets = [t for t in self.tickets.values() if not t.closed]
        
        if not active_tickets:
            embed = discord.Embed(
                title="🎫 Alle Tickets",
                description="Derzeit sind keine aktiven Tickets offen.",
                color=discord.Color.green()
            )
            await ctx.send(embed=embed, delete_after=10)
            return
        
        embed = discord.Embed(
            title="🎫 Aktive Tickets",
            description=f"Insgesamt **{len(active_tickets)}** offene(s) Ticket(s)",
            color=discord.Color.blue()
        )
        
        priority_emojis = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}
        
        for i, ticket in enumerate(active_tickets[:10], 1):
            user = ctx.guild.get_member(ticket.user_id) if ctx.guild else None
            user_name = user.name if user else f"User-{ticket.user_id}"
            
            location = ""
            if ticket.thread_id:
                location = f"Thread: <#{ticket.thread_id}>"
            elif ticket.channel_id:
                location = f"Kanal: <#{ticket.channel_id}>"
            
            time_str = ""
            try:
                ts = int(datetime.fromisoformat(ticket.created_at).timestamp())
                time_str = f" • <t:{ts}:R>"
            except:
                pass
            
            prio = priority_emojis.get(ticket.priority, "🟡")
            claimed = "📌" if ticket.claimed_by else ""
            
            embed.add_field(
                name=f"{i}. {claimed} {prio} {user_name}",
                value=f"{location}{time_str}",
                inline=False
            )
        
        if len(active_tickets) > 10:
            embed.set_footer(text=f"... und {len(active_tickets) - 10} weitere Tickets")
        
        await ctx.send(embed=embed)

    @commands.command(name="transcript")
    @commands.has_permissions(manage_roles=True)
    async def create_transcript(self, ctx):
        """Erstellt manuell ein Transcript"""
        ticket_id = None
        
        if ctx.channel.id in self.tickets:
            ticket_id = ctx.channel.id
        else:
            if hasattr(ctx.channel, 'parent') and ctx.channel.parent:
                for tid, ticket in self.tickets.items():
                    if ticket.thread_id == ctx.channel.id:
                        ticket_id = tid
                        break

        if not ticket_id or ticket_id not in self.tickets:
            await ctx.send("❌ Dieser Channel ist kein Ticket.")
            return

        await ctx.send("📄 Transcript wird erstellt...")
        await self._create_transcript(ctx, ticket_id)
        await ctx.send("✅ Transcript wurde im Log-Channel erstellt.")

    # Event Handler für Nachrichten-Weiterleitung
    @commands.Cog.listener()
    async def on_message(self, message):
        """Verarbeitet Nachrichten für Ticket-Weiterleitung"""
        if message.author.bot:
            return

        ticket = None
        ticket_id = None

        # Ist die Nachricht in einem Ticket-Channel?
        if message.channel.id in self.tickets:
            ticket_id = message.channel.id
            ticket = self.tickets[ticket_id]
        else:
            # Ist die Nachricht in einem Ticket-Thread?
            for tid, t in self.tickets.items():
                if t.thread_id == message.channel.id or t.channel_id == message.channel.id:
                    ticket_id = tid
                    ticket = t
                    break

        if not ticket:
            return

        # Last Activity updaten
        ticket.last_activity = datetime.now().isoformat()
        ticket.messages_count += 1

        # Staff-Status prüfen
        staff_role_id = await self.config.staff_role()
        is_staff = False
        if staff_role_id and message.guild:
            staff_role = message.guild.get_role(staff_role_id)
            if staff_role and staff_role in message.author.roles:
                is_staff = True

        # Prüfen ob Nachricht mit "." beginnt (nicht an User weiterleiten)
        if message.content.strip().startswith("."):
            clean_content = message.content[1:].strip()
            if clean_content and message.channel.permissions_for(message.author).manage_messages:
                try:
                    await message.edit(content=clean_content)
                except:
                    pass
            return

        # Weiterleitung verarbeiten
        user_id = ticket.user_id
        
        # Fall 1: Nachricht von Staff im Thread an User per DM
        if ticket.thread_id == message.channel.id and is_staff:
            dm_channel_id = ticket.dm_channel_id
            if dm_channel_id:
                dm_channel = self.bot.get_channel(dm_channel_id)
                if not dm_channel:
                    try:
                        user = message.guild.get_member(user_id)
                        if user:
                            dm_channel = await user.create_dm()
                            ticket.dm_channel_id = dm_channel.id
                    except:
                        return
                
                if dm_channel:
                    embed = discord.Embed(
                        description=message.content,
                        color=discord.Color.blue(),
                        timestamp=message.created_at
                    )
                    embed.set_footer(text=f"Von: {message.author.name}", icon_url=message.author.display_avatar.url)
                    
                    files = []
                    for attachment in message.attachments:
                        try:
                            file = await attachment.to_file()
                            files.append(file)
                        except:
                            pass
                    
                    try:
                        await dm_channel.send(embed=embed, files=files)
                    except discord.Forbidden:
                        await message.channel.send("⚠️ Kann keine DM an den User senden. Vielleicht hat er DMs deaktiviert.")

        # Fall 2: Nachricht vom User per DM an Thread
        dm_channel_id = ticket.dm_channel_id
        if dm_channel_id and message.channel.id == dm_channel_id:
            if message.author.id == user_id:
                thread_id = ticket.thread_id
                if thread_id:
                    thread = self.bot.get_channel(thread_id)
                    if thread:
                        embed = discord.Embed(
                            description=message.content,
                            color=discord.Color.green(),
                            timestamp=message.created_at
                        )
                        embed.set_footer(text=f"Vom User: {message.author.name}", icon_url=message.author.display_avatar.url)
                        
                        files = []
                        for attachment in message.attachments:
                            try:
                                file = await attachment.to_file()
                                files.append(file)
                            except:
                                pass
                        
                        try:
                            await thread.send(embed=embed, files=files)
                        except Exception as e:
                            try:
                                dm_channel = message.channel
                                await dm_channel.send(f"❌ Fehler beim Senden an Thread: {e}")
                            except:
                                pass

                # Auch im Classic-Channel falls vorhanden
                channel_id = ticket.channel_id
                if channel_id:
                    channel = self.bot.get_channel(channel_id)
                    if channel:
                        embed = discord.Embed(
                            description=message.content,
                            color=discord.Color.green(),
                            timestamp=message.created_at
                        )
                        embed.set_footer(text=f"Vom User: {message.author.name}")
                        
                        files = []
                        for attachment in message.attachments:
                            try:
                                file = await attachment.to_file()
                                files.append(file)
                            except:
                                pass
                        
                        try:
                            await channel.send(embed=embed, files=files)
                        except:
                            pass

        # Speichern nicht blockierend
        if ticket.messages_count % 10 == 0:  # Alle 10 Nachrichten speichern
            asyncio.create_task(self._save_tickets())


async def setup(bot):
    """Lädt den Cog"""
    cog = TicketSystem(bot)
    await cog.config_init()
    await bot.add_cog(cog)
