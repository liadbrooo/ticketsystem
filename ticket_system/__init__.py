"""
Ticket System Cog für RedBot - Version 2.0
Ein vollständiges Ticket-System mit Panel-Auswahl, Forum- und Classic-Mode,
DM-Weiterleitung, Staff-Chat und Transcript-Erstellung.
"""

from redbot.core import commands, checks, Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, pagify
import discord
from discord.ext import tasks
from discord.ui import Button, View, Select
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any
import io
import re

class TicketPanelSelect(Select):
    """Auswahlmenü für Ticket-Panels"""
    
    def __init__(self, panels: list):
        options = []
        for panel in panels:
            emoji = panel.get("emoji", "📧")
            options.append(
                discord.SelectOption(
                    label=panel["name"],
                    value=panel["id"],
                    description=panel.get("description", "Support Ticket"),
                    emoji=emoji
                )
            )
        
        super().__init__(
            placeholder="Wähle eine Kategorie für dein Ticket...",
            min_values=1,
            max_values=1,
            options=options
        )
        self.panels = panels
    
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        panel_id = self.values[0]
        panel = next((p for p in self.panels if p["id"] == panel_id), None)
        
        if not panel:
            await interaction.followup.send("❌ Ungültige Kategorie ausgewählt.", ephemeral=True)
            return
        
        # Ticket erstellen
        cog = self.view.cog
        await cog._create_ticket_from_panel(interaction, panel)


class TicketPanelView(View):
    """View für das Ticket-Panel"""
    
    def __init__(self, cog, panels: list):
        super().__init__(timeout=None)
        self.cog = cog
        self.add_item(TicketPanelSelect(panels))


class TicketCloseButton(Button):
    """Button zum Schließen eines Tickets"""
    
    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.danger,
            label="Ticket schließen",
            emoji="🔒",
            custom_id="ticket_close"
        )
    
    async def callback(self, interaction: discord.Interaction):
        cog = self.view.cog
        await cog._close_ticket_command(interaction)


class TicketSystem(commands.Cog):
    """
    🎫 Ticket System - Ein professionelles Support-Ticket-System
    
    Features:
    - Panel-System mit Kategorien (Allgemein, Bug Report, Team, etc.)
    - Forum Mode & Classic Channel Mode
    - DM-Kommunikation mit Usern (Forum Mode)
    - Nachrichten-Weiterleitung zwischen Staff-Thread/Kanal und User-DM
    - Prefix "." verhindert Weiterleitung an User (nur intern)
    - Automatische Transcript-Erstellung beim Schließen
    - Staff-Rollen Management
    - Modernes UI mit Buttons und Select Menus
    - Vollständig auf Deutsch
    """
    
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9876543210, force_registration=True)
        
        default_guild = {
            "forum_channel": None,
            "category_id": None,
            "staff_role": None,
            "log_channel": None,
            "mode": "forum",  # "forum" oder "classic"
            "ticket_counter": 0,
            "open_tickets": {},  # ticket_id -> {user_id, guild_id, channel_id/thread_id, dm_id, panel_id}
            "panels": [  # Standard Panels
                {"id": "general", "name": "Allgemeiner Support", "description": "Für allgemeine Fragen und Hilfe", "emoji": "📧"},
                {"id": "bug", "name": "Bug Report", "description": "Fehler melden", "emoji": "🐛"},
                {"id": "team", "name": "Teamverwaltung", "description": "Anfragen an das Team", "emoji": "👥"},
                {"id": "suggest", "name": "Vorschläge", "description": "Ideen und Vorschläge einreichen", "emoji": "💡"}
            ]
        }
        self.config.register_guild(**default_guild)
        
        # Member-Daten speichern jetzt nur noch die guild_id und ticket_id Kombination
        default_member = {
            "tickets": []  # Liste von {"guild_id": ..., "ticket_id": ...}
        }
        self.config.register_member(**default_member)
        
        # Cache für aktive Tickets
        self.ticket_cache: Dict[int, Dict[str, Any]] = {}
        
        # Persistent Views registrieren
        self.bot.add_view(TicketCloseButton())
        
    async def get_ticket_data(self, guild: discord.Guild, ticket_id: int) -> Optional[Dict]:
        """Holt Ticket-Daten aus Config oder Cache"""
        async with self.config.guild(guild).open_tickets() as tickets:
            if str(ticket_id) in tickets:
                return tickets[str(ticket_id)]
        return None
    
    async def save_ticket_data(self, guild: discord.Guild, ticket_id: int, data: Dict):
        """Speichert Ticket-Daten"""
        async with self.config.guild(guild).open_tickets() as tickets:
            tickets[str(ticket_id)] = data
    
    async def delete_ticket_data(self, guild: discord.Guild, ticket_id: int):
        """Löscht Ticket-Daten"""
        async with self.config.guild(guild).open_tickets() as tickets:
            if str(ticket_id) in tickets:
                del tickets[str(ticket_id)]
    
    async def create_transcript(self, guild: discord.Guild, ticket_id: int, 
                                channel: discord.TextChannel | discord.Thread,
                                user: discord.Member) -> str:
        """Erstellt ein Transcript des gesamten Chats"""
        messages = []
        
        try:
            async for msg in channel.history(limit=None, oldest_first=True):
                timestamp = msg.created_at.strftime("%d.%m.%Y %H:%M:%S")
                author = msg.author.name
                content = msg.content
                
                # Anhänge hinzufügen
                attachments = ""
                if msg.attachments:
                    attachments = ", ".join([a.url for a in msg.attachments])
                    if attachments:
                        content += f"\n[Anhänge: {attachments}]"
                
                # Embeds erwähnen
                if msg.embeds:
                    content += "\n[Enthält Embed(s)]"
                
                messages.append(f"[{timestamp}] {author}: {content}")
        
        except Exception as e:
            messages.append(f"[Fehler beim Laden der Nachrichten: {str(e)}]")
        
        # Header hinzufügen
        header = f"""
═══════════════════════════════════════════════════
🎫 TICKET TRANSCRIPT
═══════════════════════════════════════════════════
Ticket ID: #{ticket_id}
User: {user.name}#{user.discriminator} ({user.id})
Server: {guild.name}
Erstellt: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
Geschlossen: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
═══════════════════════════════════════════════════

"""
        transcript_content = header + "\n".join(messages)
        
        # In Log-Channel hochladen
        log_channel_id = await self.config.guild(guild).log_channel()
        if log_channel_id:
            log_channel = guild.get_channel(log_channel_id)
            if log_channel:
                file = discord.File(
                    io.BytesIO(transcript_content.encode('utf-8')),
                    filename=f"ticket_{ticket_id}_{user.name}.txt"
                )
                try:
                    await log_channel.send(
                        content=f"📄 **Transcript für Ticket #{ticket_id}** (User: {user.mention})",
                        file=file
                    )
                except Exception as e:
                    pass  # Fehler stillschweigend ignorieren oder loggen
        
        return transcript_content
    
    @commands.group(name="ticketsetup", aliases=["ticketset", "ts"])
    @checks.is_owner()
    async def ticketsetup(self, ctx):
        """Konfiguration des Ticket-Systems"""
        pass
    
    @ticketsetup.command(name="forum")
    async def setup_forum(self, ctx, channel: discord.ForumChannel):
        """Setzt den Forum-Channel für Tickets"""
        await self.config.guild(ctx.guild).forum_channel.set(channel.id)
        await ctx.send(f"✅ Forum-Channel wurde auf {channel.mention} gesetzt.")
    
    @ticketsetup.command(name="category")
    async def setup_category(self, ctx, category: discord.CategoryChannel):
        """Setzt die Kategorie für Classic-Mode Tickets"""
        await self.config.guild(ctx.guild).category_id.set(category.id)
        await ctx.send(f"✅ Kategorie wurde auf {category.name} gesetzt.")
    
    @ticketsetup.command(name="role")
    async def setup_role(self, ctx, role: discord.Role):
        """Setzt die Staff-Rolle"""
        await self.config.guild(ctx.guild).staff_role.set(role.id)
        await ctx.send(f"✅ Staff-Rolle wurde auf {role.name} gesetzt.")
    
    @ticketsetup.command(name="log")
    async def setup_log(self, ctx, channel: discord.TextChannel):
        """Setzt den Log-Channel für Transcripts"""
        await self.config.guild(ctx.guild).log_channel.set(channel.id)
        await ctx.send(f"✅ Log-Channel wurde auf {channel.mention} gesetzt.")
    
    @ticketsetup.command(name="mode")
    async def setup_mode(self, ctx, mode: str):
        """Setzt den Ticket-Modus: 'forum' oder 'classic'"""
        if mode.lower() not in ["forum", "classic"]:
            await ctx.send("❌ Ungültiger Modus. Bitte verwende 'forum' oder 'classic'.")
            return
        
        await self.config.guild(ctx.guild).mode.set(mode.lower())
        await ctx.send(f"✅ Ticket-Modus wurde auf '{mode.lower()}' gesetzt.")
    
    @ticketsetup.command(name="show")
    async def setup_show(self, ctx):
        """Zeigt die aktuelle Konfiguration"""
        guild = ctx.guild
        forum_id = await self.config.guild(guild).forum_channel()
        category_id = await self.config.guild(guild).category_id()
        staff_id = await self.config.guild(guild).staff_role()
        log_id = await self.config.guild(guild).log_channel()
        mode = await self.config.guild(guild).mode()
        
        forum = guild.get_channel(forum_id) if forum_id else "Nicht gesetzt"
        category = guild.get_channel(category_id) if category_id else "Nicht gesetzt"
        staff = guild.get_role(staff_id) if staff_id else "Nicht gesetzt"
        log = guild.get_channel(log_id) if log_id else "Nicht gesetzt"
        
        embed = discord.Embed(
            title="🎫 Ticket-System Konfiguration",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Modus", value=f"`{mode}`", inline=True)
        embed.add_field(name="Forum-Channel", value=forum if isinstance(forum, str) else forum.mention, inline=False)
        embed.add_field(name="Kategorie (Classic)", value=category if isinstance(category, str) else category.name, inline=False)
        embed.add_field(name="Staff-Rolle", value=staff if isinstance(staff, str) else staff.mention, inline=False)
        embed.add_field(name="Log-Channel", value=log if isinstance(log, str) else log.mention, inline=False)
        
        await ctx.send(embed=embed)
    
    @commands.command(name="ticket", aliases=["support", "newticket", "ticketöffnen"])
    async def ticket(self, ctx):
        """Öffnet ein neues Support-Ticket"""
        
        # Schutz vor Ausführung in DMs
        if not isinstance(ctx.author, discord.Member) or ctx.guild is None:
            await ctx.send("❌ Dieser Befehl kann nur innerhalb eines Servers verwendet werden.")
            return
            
        guild = ctx.guild
        
        # Prüfen ob User bereits ein offenes Ticket hat (neues System mit tickets-Liste)
        member_tickets = await self.config.member(ctx.author).tickets()
        for ticket_entry in member_tickets:
            if ticket_entry.get("guild_id") == guild.id:
                ticket_data = await self.get_ticket_data(guild, ticket_entry["ticket_id"])
                if ticket_data:
                    channel_id = ticket_data.get("channel_id") or ticket_data.get("thread_id")
                    channel = guild.get_channel(channel_id)
                    if channel:
                        await ctx.send(f"ℹ️ Du hast bereits ein offenes Ticket: {channel.mention}")
                        return
        
        mode = await self.config.guild(guild).mode()
        
        if mode == "forum":
            await self._create_forum_ticket(ctx)
        else:
            await self._create_classic_ticket(ctx)
    
    async def _create_forum_ticket(self, ctx):
        """Erstellt ein Ticket im Forum-Mode"""
        guild = ctx.guild
        forum_id = await self.config.guild(guild).forum_channel()
        
        if not forum_id:
            await ctx.send("❌ Das Ticket-System ist nicht korrekt konfiguriert. Bitte kontaktiere einen Admin.")
            return
        
        forum = guild.get_channel(forum_id)
        if not forum:
            await ctx.send("❌ Der konfigurierte Forum-Channel wurde nicht gefunden.")
            return
        
        # Ticket-ID generieren (Counter sicher inkrementieren ohne async with)
        current_count = await self.config.guild(guild).ticket_counter()
        new_count = current_count + 1
        await self.config.guild(guild).ticket_counter.set(new_count)
        ticket_id = new_count
        
        # Thread im Forum erstellen
        try:
            thread = await forum.create_thread(
                name=f"🎫 Ticket #{ticket_id} - {ctx.author.name}",
                content=f"👤 **User:** {ctx.author.mention}\n🆔 **ID:** #{ticket_id}\n⏰ **Eröffnet:** <t:{int(datetime.now().timestamp())}:R>\n\n📝 **Beschreibung:**\nBitte beschreibe dein Anliegen hier...",
                applied_tags=[],  # Kann bei Bedarf angepasst werden
                reason=f"Ticket von {ctx.author}"
            )
        except Exception as e:
            await ctx.send(f"❌ Fehler beim Erstellen des Tickets: {str(e)}")
            return
        
        # Staff-Rolle hinzufügen (bei Forum-Posts nicht möglich, stattdessen pingen)
        staff_role_id = await self.config.guild(guild).staff_role()
        staff_ping = ""
        if staff_role_id:
            staff_role = guild.get_role(staff_role_id)
            if staff_role:
                staff_ping = f" {staff_role.mention}"
                # add_user funktioniert nicht bei Forum-Posts, wir pingen stattdessen
        
        # DM mit User erstellen
        try:
            dm_channel = await ctx.author.create_dm()
            await dm_channel.send(
                f"🎫 **Dein Ticket #{ticket_id} wurde eröffnet!**\n\n"
                f"Unser Support-Team wird sich bald bei dir melden.\n"
                f"Du kannst hier direkt antworten und deine Nachricht wird an das Team im Thread weitergeleitet.\n\n"
                f"Verwende `!close` oder `!schließen` um das Ticket zu schließen."
            )
        except Exception as e:
            await ctx.send("⚠️ Ich konnte dir keine DM senden. Bitte aktiviere DMs von Server-Mitgliedern.")
            dm_channel = None
        
        # Ticket-Daten speichern (mit guild_id für DM-Lookup)
        ticket_data = {
            "user_id": ctx.author.id,
            "guild_id": guild.id,
            "thread_id": thread.id,
            "dm_id": dm_channel.id if dm_channel else None,
            "created_at": int(datetime.now().timestamp()),
            "mode": "forum"
        }
        await self.save_ticket_data(guild, ticket_id, ticket_data)
        
        # Member-Ticket-Zuordnung speichern (neues System)
        member_tickets = await self.config.member(ctx.author).tickets()
        member_tickets.append({"guild_id": guild.id, "ticket_id": ticket_id})
        await self.config.member(ctx.author).tickets.set(member_tickets)
        
        # Bestätigung
        embed = discord.Embed(
            title="🎫 Ticket eröffnet!",
            description=f"Dein Ticket **#{ticket_id}** wurde erfolgreich erstellt.",
            color=discord.Color.green()
        )
        embed.add_field(name="📍 Thread", value=thread.mention, inline=False)
        embed.add_field(name="💬 DM", value="Aktiviert" if dm_channel else "Nicht verfügbar", inline=True)
        embed.add_field(name="👥 Support", value="Das Team wurde benachrichtigt.", inline=True)
        embed.set_footer(text="Antworte einfach hier oder per DM!")
        embed.timestamp = datetime.now()
        
        await ctx.send(embed=embed, delete_after=10)
        
        # Staff-Benachrichtigung im Thread (staff_ping wurde bereits oben gesetzt)
        await thread.send(
            f"🆕 **Neues Ticket #{ticket_id}**\n"
            f"User: {ctx.author.mention}{staff_ping}\n\n"
            f"💡 **Info:** \n"
            f"- Antworten hier werden als DM an den User gesendet\n"
            f"- Setze ein `.` vor deine Nachricht, um sie nur intern zu behalten\n"
            f"- Verwende `!close` zum Schließen des Tickets"
        )
    
    async def _create_classic_ticket(self, ctx):
        """Erstellt ein Ticket im Classic-Mode"""
        guild = ctx.guild
        category_id = await self.config.guild(guild).category_id()
        
        if not category_id:
            await ctx.send("❌ Das Ticket-System ist nicht korrekt konfiguriert. Bitte kontaktiere einen Admin.")
            return
        
        category = guild.get_channel(category_id)
        if not category:
            await ctx.send("❌ Die konfigurierte Kategorie wurde nicht gefunden.")
            return
        
        # Ticket-ID generieren (Counter sicher inkrementieren ohne async with)
        current_count = await self.config.guild(guild).ticket_counter()
        new_count = current_count + 1
        await self.config.guild(guild).ticket_counter.set(new_count)
        ticket_id = new_count
        
        # Privaten Kanal erstellen
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            ctx.author: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            self.bot.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        # Staff-Rolle hinzufügen
        staff_role_id = await self.config.guild(guild).staff_role()
        if staff_role_id:
            staff_role = guild.get_role(staff_role_id)
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        
        try:
            channel = await guild.create_text_channel(
                name=f"ticket-{ticket_id}-{ctx.author.name}",
                category=category,
                overwrites=overwrites,
                topic=f"Ticket #{ticket_id} | User: {ctx.author.name} | Erstellt: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                reason=f"Ticket von {ctx.author}"
            )
        except Exception as e:
            await ctx.send(f"❌ Fehler beim Erstellen des Tickets: {str(e)}")
            return
        
        # Ticket-Daten speichern (mit guild_id)
        ticket_data = {
            "user_id": ctx.author.id,
            "guild_id": guild.id,
            "channel_id": channel.id,
            "dm_id": None,  # Kein DM im Classic-Mode
            "created_at": int(datetime.now().timestamp()),
            "mode": "classic"
        }
        await self.save_ticket_data(guild, ticket_id, ticket_data)
        
        # Member-Ticket-Zuordnung speichern (neues System)
        member_tickets = await self.config.member(ctx.author).tickets()
        member_tickets.append({"guild_id": guild.id, "ticket_id": ticket_id})
        await self.config.member(ctx.author).tickets.set(member_tickets)
        
        # Begrüßung im Kanal
        embed = discord.Embed(
            title="🎫 Willkommen im Support!",
            description=f"Dein Ticket **#{ticket_id}** wurde eröffnet.",
            color=discord.Color.green()
        )
        embed.add_field(name="👤 User", value=ctx.author.mention, inline=True)
        embed.add_field(name="🆔 ID", value=f"#{ticket_id}", inline=True)
        embed.add_field(name="⏰ Zeit", value=f"<t:{ticket_data['created_at']}:R>", inline=True)
        embed.add_field(
            name="📝 Beschreibung",
            value="Bitte beschreibe dein Anliegen so detailliert wie möglich.\n"
                  "Das Support-Team wird sich schnellstmöglich bei dir melden.",
            inline=False
        )
        embed.set_footer(text="Verwende !close zum Schließen des Tickets")
        embed.timestamp = datetime.now()
        
        await channel.send(content=f"{ctx.author.mention}", embed=embed)
        
        # Staff-Benachrichtigung
        staff_ping = ""
        if staff_role_id:
            staff_role = guild.get_role(staff_role_id)
            if staff_role:
                staff_ping = f" {staff_role.mention}"
        
        await channel.send(
            f"🆕 **Neues Ticket #{ticket_id}**\n"
            f"User: {ctx.author.mention}{staff_ping}\n\n"
            f"💡 **Info:** \n"
            f"- Setze ein `.` vor deine Nachricht, um sie nur intern zu behalten\n"
            f"- Verwende `!close` zum Schließen des Tickets"
        )
        
        # Bestätigung für User
        await ctx.send(f"✅ Dein Ticket wurde erstellt: {channel.mention}", delete_after=10)
    
    @commands.command(name="close", aliases=["schließen", "close ticket"])
    async def close_ticket(self, ctx):
        """Schließt das aktuelle Ticket und erstellt ein Transcript"""
        guild = ctx.guild
        
        # Ticket-ID finden (neues System mit tickets-Liste)
        member_tickets = await self.config.member(ctx.author).tickets()
        ticket_id = None
        ticket_data = None
        
        # Erst prüfen ob User ein Ticket in diesem Guild hat
        for ticket_entry in member_tickets:
            if ticket_entry.get("guild_id") == guild.id:
                ticket_id = ticket_entry["ticket_id"]
                ticket_data = await self.get_ticket_data(guild, ticket_id)
                if ticket_data:
                    break
        
        if not ticket_data:
            # Prüfen ob es ein Staff-Mitglied ist und im Ticket-Kanal
            async with self.config.guild(guild).open_tickets() as tickets:
                for tid, data in tickets.items():
                    channel_id = data.get("channel_id") or data.get("thread_id")
                    if channel_id == ctx.channel.id:
                        ticket_id = int(tid)
                        ticket_data = data
                        break
            
            if not ticket_data:
                await ctx.send("❌ Du hast kein aktives Ticket.")
                return
        
        # Kanal/Thread finden
        channel_id = ticket_data.get("channel_id") or ticket_data.get("thread_id")
        channel = guild.get_channel(channel_id)
        
        if not channel:
            await ctx.send("❌ Der Ticket-Kanal wurde nicht gefunden.")
            await self.delete_ticket_data(guild, ticket_id)
            # Aufräumen der Member-Daten
            if ticket_data.get("user_id"):
                user = guild.get_member(ticket_data["user_id"])
                if user:
                    await self._remove_member_ticket(user, guild.id, ticket_id)
            return
        
        # Transcript erstellen
        user_id = ticket_data.get("user_id")
        user = guild.get_member(user_id) if user_id else ctx.author
        if not user:
            user = ctx.author
        
        await ctx.send("📄 **Erstelle Transcript...**")
        transcript = await self.create_transcript(guild, ticket_id, channel, user)
        
        # Benutzer informieren
        dm_id = ticket_data.get("dm_id")
        if dm_id and user:
            try:
                dm_channel = self.bot.get_channel(dm_id)
                if dm_channel:
                    await dm_channel.send(
                        f"🔒 **Dein Ticket #{ticket_id} wurde geschlossen.**\n\n"
                        f"Vielen Dank für deine Anfrage!\n"
                        f"Falls du weitere Fragen hast, eröffne gerne ein neues Ticket."
                    )
            except Exception:
                pass
        
        # Kanal löschen (Classic) oder archivieren (Forum)
        mode = ticket_data.get("mode", "forum")
        
        if mode == "classic" and isinstance(channel, discord.TextChannel):
            await channel.delete(reason=f"Ticket #{ticket_id} geschlossen")
        elif mode == "forum" and isinstance(channel, discord.Thread):
            await channel.edit(archived=True, locked=True)
            await channel.send("🔒 **Dieses Ticket wurde geschlossen und archiviert.**")
        
        # Daten bereinigen
        await self.delete_ticket_data(guild, ticket_id)
        if user:
            await self._remove_member_ticket(user, guild.id, ticket_id)
        
        await ctx.send(f"✅ **Ticket #{ticket_id} wurde geschlossen.**\nDas Transcript wurde im Log-Channel gespeichert.")
    
    async def _remove_member_ticket(self, member: discord.Member, guild_id: int, ticket_id: int):
        """Entfernt ein Ticket aus der Member-Datenliste"""
        try:
            member_tickets = await self.config.member(member).tickets()
            member_tickets = [t for t in member_tickets if not (t.get("guild_id") == guild_id and t.get("ticket_id") == ticket_id)]
            await self.config.member(member).tickets.set(member_tickets)
        except Exception:
            pass  # Fehler ignorieren, da es nur um Cleanup geht
    
    @commands.command(name="add")
    @commands.has_permissions(manage_channels=True)
    async def add_user(self, ctx, user: discord.Member):
        """Fügt einen Benutzer zum Ticket hinzu"""
        guild = ctx.guild
        
        # Ticket finden
        ticket_data = None
        ticket_id = None
        
        async with self.config.guild(guild).open_tickets() as tickets:
            for tid, data in tickets.items():
                channel_id = data.get("channel_id") or data.get("thread_id")
                if channel_id == ctx.channel.id:
                    ticket_id = int(tid)
                    ticket_data = data
                    break
        
        if not ticket_data:
            await ctx.send("❌ Dies ist kein Ticket-Kanal.")
            return
        
        mode = ticket_data.get("mode", "forum")
        
        if mode == "classic":
            channel = ctx.channel
            if isinstance(channel, discord.TextChannel):
                await channel.set_permissions(user, read_messages=True, send_messages=True)
                await ctx.send(f"✅ {user.mention} wurde zum Ticket hinzugefügt.")
        else:
            # Forum-Thread - add_user funktioniert nur bei öffentlichen Threads
            thread = ctx.channel
            if isinstance(thread, discord.Thread):
                try:
                    await thread.add_user(user)
                    await ctx.send(f"✅ {user.mention} wurde zum Ticket hinzugefügt.")
                except discord.Forbidden:
                    await ctx.send(f"⚠️ {user.mention} kann nicht zum Thread hinzugefügt werden. Dies ist nur bei öffentlichen Threads möglich.")
                except Exception as e:
                    await ctx.send(f"❌ Fehler: {str(e)}")
    
    @commands.command(name="remove")
    @commands.has_permissions(manage_channels=True)
    async def remove_user(self, ctx, user: discord.Member):
        """Entfernt einen Benutzer aus dem Ticket"""
        guild = ctx.guild
        
        # Ticket finden
        ticket_data = None
        
        async with self.config.guild(guild).open_tickets() as tickets:
            for tid, data in tickets.items():
                channel_id = data.get("channel_id") or data.get("thread_id")
                if channel_id == ctx.channel.id:
                    ticket_data = data
                    break
        
        if not ticket_data:
            await ctx.send("❌ Dies ist kein Ticket-Kanal.")
            return
        
        mode = ticket_data.get("mode", "forum")
        
        if mode == "classic":
            channel = ctx.channel
            if isinstance(channel, discord.TextChannel):
                await channel.set_permissions(user, overwrite=None)
                await ctx.send(f"✅ {user.mention} wurde aus dem Ticket entfernt.")
        else:
            # Forum-Thread - User können nicht direkt entfernt werden, nur Info
            await ctx.send(f"ℹ️ Im Forum-Mode können User nicht aus Threads entfernt werden.")
    
    # Message Handler für DM ↔ Channel Weiterleitung
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Verarbeitet Nachrichten für die Ticket-Weiterleitung"""
        
        # Ignoriere Bot-Nachrichten
        if message.author.bot:
            return
        
        # Ignoriere Commands
        if message.content.startswith(('!', '?', '.', '/')):
            # Aber verarbeite Nachrichten die NUR mit "." beginnen (Prefix für interne Nachrichten)
            if message.content.startswith('.') and len(message.content) > 1:
                # Dies ist eine interne Staff-Nachricht, nicht weiterleiten
                # Aber wir müssen prüfen ob es in einem Ticket ist
                pass
            return
        
        guild = message.guild
        
        # Fall 1: Nachricht kommt von User in DM (Forum Mode)
        if isinstance(message.channel, discord.DMChannel):
            await self._handle_dm_message(message)
            return
        
        # Fall 2: Nachricht kommt von Staff in Ticket-Channel/Thread
        if guild:
            await self._handle_ticket_message(message, guild)
    
    async def _handle_dm_message(self, message: discord.Message):
        """Verarbeitet DM-Nachrichten vom User und leitet sie an den Thread weiter"""
        user = message.author
        
        # Aktives Ticket des Users finden (neues System)
        member_tickets = await self.config.member(user).tickets()
        if not member_tickets:
            return
        
        # Durchsuche alle Guilds nach dem passenden Ticket mit dieser DM-ID
        for ticket_entry in member_tickets:
            guild_id = ticket_entry.get("guild_id")
            ticket_id = ticket_entry.get("ticket_id")
            
            # Finde das Guild
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue
            
            ticket_data = await self.get_ticket_data(guild, ticket_id)
            if ticket_data and ticket_data.get("dm_id") == message.channel.id:
                thread_id = ticket_data.get("thread_id")
                if thread_id:
                    thread = guild.get_channel(thread_id)
                    if thread:
                        # Nachricht an Thread weiterleiten
                        content = message.content
                        
                        # Dateien mitsenden
                        files = []
                        for attachment in message.attachments:
                            try:
                                file = await attachment.to_file()
                                files.append(file)
                            except Exception:
                                pass
                        
                        # Embed für Kontext
                        embed = discord.Embed(
                            description=content if content else "[Kein Text]",
                            color=discord.Color.blue(),
                            timestamp=message.created_at
                        )
                        embed.set_author(name=user.name, icon_url=user.display_avatar.url)
                        embed.set_footer(text=f"📩 Vom User (Ticket #{ticket_id})")
                        
                        try:
                            await thread.send(content=f"📨 **Nachricht von {user.name}**:", embed=embed, files=files)
                        except Exception as e:
                            pass
                        return
    
    async def _handle_ticket_message(self, message: discord.Message, guild: discord.Guild):
        """Verarbeitet Staff-Nachrichten im Ticket und leitet sie an DM weiter"""
        
        # Prüfen ob Nachricht in einem Ticket-Kanal/Thread ist
        ticket_data = None
        ticket_id = None
        
        async with self.config.guild(guild).open_tickets() as tickets:
            for tid, data in tickets.items():
                channel_id = data.get("channel_id") or data.get("thread_id")
                if channel_id == message.channel.id:
                    ticket_id = int(tid)
                    ticket_data = data
                    break
        
        if not ticket_data:
            return
        
        # Prüfen ob Nachricht mit "." beginnt (intern, nicht weiterleiten)
        if message.content.startswith('.'):
            # Nachricht bleibt nur im Ticket, wird aber bereinigt gesendet
            # Entferne das "." am Anfang
            new_content = message.content[1:].lstrip()
            
            if new_content != message.content[1:]:  # Wenn sich was geändert hat
                # Lösche originale und sende neue ohne "."
                try:
                    await message.delete()
                    await message.channel.send(
                        content=new_content,
                        reference=message.reference  # Reply beibehalten falls vorhanden
                    )
                except Exception:
                    # Falls löschen nicht klappt, einfach editieren
                    await message.edit(content=new_content)
            
            # Nicht an User weiterleiten - fertig
            return
        
        # Staff-Rolle prüfen (optional, könnte auch jeder im Channel dürfen)
        staff_role_id = await self.config.guild(guild).staff_role()
        is_staff = False
        if staff_role_id:
            staff_role = guild.get_role(staff_role_id)
            if staff_role and staff_role in message.author.roles:
                is_staff = True
        else:
            is_staff = True  # Wenn keine Rolle konfiguriert, alle erlauben
        
        if not is_staff:
            return
        
        # An User-DM weiterleiten
        dm_id = ticket_data.get("dm_id")
        if not dm_id:
            return
        
        dm_channel = self.bot.get_channel(dm_id)
        if not dm_channel:
            return
        
        user_id = ticket_data.get("user_id")
        user = guild.get_member(user_id)
        if not user:
            return
        
        # Nachricht formatieren
        content = message.content
        
        # Dateien mitsenden
        files = []
        for attachment in message.attachments:
            try:
                file = await attachment.to_file()
                files.append(file)
            except Exception:
                pass
        
        # Embed erstellen
        embed = discord.Embed(
            description=content if content else "[Kein Text]",
            color=discord.Color.green(),
            timestamp=message.created_at
        )
        embed.set_author(name=message.author.name, icon_url=message.author.display_avatar.url)
        embed.set_footer(text=f"🎫 Support (Ticket #{ticket_id})")
        
        # Reference/Reply behandeln
        reference = None
        if message.reference and isinstance(message.reference.resolved, discord.Message):
            ref_content = message.reference.resolved.content[:100]
            embed.insert_field_at(
                index=0,
                name="Antwort auf:",
                value=f"{message.reference.resolved.author.name}: {ref_content}",
                inline=False
            )
        
        try:
            await dm_channel.send(
                content=f"💬 **Antwort vom Support-Team**:",
                embed=embed,
                files=files
            )
        except Exception as e:
            # User hat DMs deaktiviert
            try:
                await message.channel.send(
                    f"⚠️ {message.author.mention}, der User hat DMs deaktiviert. "
                    f"Deine Nachricht konnte nicht zugestellt werden.",
                    delete_after=10
                )
            except Exception:
                pass
    
    @commands.command(name="ticketinfo")
    async def ticket_info(self, ctx):
        """Zeigt Informationen zum aktuellen Ticket"""
        guild = ctx.guild
        
        # Ticket finden (neues System)
        ticket_data = None
        ticket_id = None
        
        # Erst prüfen ob User ein aktives Ticket hat
        member_tickets = await self.config.member(ctx.author).tickets()
        for ticket_entry in member_tickets:
            if ticket_entry.get("guild_id") == guild.id:
                ticket_id = ticket_entry["ticket_id"]
                ticket_data = await self.get_ticket_data(guild, ticket_id)
                if ticket_data:
                    break
        
        # Wenn nicht, prüfen ob Channel ein Ticket ist
        if not ticket_data:
            async with self.config.guild(guild).open_tickets() as tickets:
                for tid, data in tickets.items():
                    channel_id = data.get("channel_id") or data.get("thread_id")
                    if channel_id == ctx.channel.id:
                        ticket_id = int(tid)
                        ticket_data = data
                        break
        
        if not ticket_data:
            await ctx.send("❌ Kein aktives Ticket gefunden.")
            return
        
        user_id = ticket_data.get("user_id")
        user = guild.get_member(user_id) if user_id else None
        
        embed = discord.Embed(
            title=f"🎫 Ticket #{ticket_id}",
            color=discord.Color.blue(),
            timestamp=datetime.fromtimestamp(ticket_data.get("created_at", 0))
        )
        
        if user:
            embed.add_field(name="👤 User", value=user.mention, inline=True)
        embed.add_field(name="📍 Modus", value=ticket_data.get("mode", "unknown"), inline=True)
        embed.add_field(name="⏰ Erstellt", value=f"<t:{ticket_data.get('created_at', 0)}:R>", inline=True)
        
        channel_id = ticket_data.get("channel_id") or ticket_data.get("thread_id")
        channel = guild.get_channel(channel_id)
        if channel:
            embed.add_field(name="📍 Channel", value=channel.mention, inline=False)
        
        embed.set_footer(text=f"Ticket ID: {ticket_id}")
        
        await ctx.send(embed=embed)


async def setup(bot: Red):
    """Lädt die Cog"""
    await bot.add_cog(TicketSystem(bot))
