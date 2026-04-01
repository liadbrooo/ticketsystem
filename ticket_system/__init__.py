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


class TicketCloseView(View):
    """View für den Schließen-Button (persistent)"""
    
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        self.add_item(TicketCloseButton())


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
        
        # Cache für schnelle DM-Lookups (dm_id -> ticket_data)
        self.dm_cache: Dict[int, Dict[str, Any]] = {}
        # Cache für Thread-Lookups (thread_id -> ticket_data)
        self.thread_cache: Dict[int, Dict[str, Any]] = {}
        
        # Persistent Views registrieren (wird nach cog init aufgerufen)
        # Die View wird später in setup() registriert, wenn cog bereit ist
        
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
                        await ctx.send(
                            f"ℹ️ Du hast bereits ein offenes Ticket: {channel.mention}\n\n"
                            f"**Wichtig:** Antworte in deinen DMs auf dieses Ticket!",
                            ephemeral=True
                        )
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
        
        # Ticket-ID generieren
        current_count = await self.config.guild(guild).ticket_counter()
        new_count = current_count + 1
        await self.config.guild(guild).ticket_counter.set(new_count)
        ticket_id = new_count
        
        # Staff-Rolle VOR dem Senden holen
        staff_role_id = await self.config.guild(guild).staff_role()
        staff_ping = ""
        if staff_role_id:
            staff_role = guild.get_role(staff_role_id)
            if staff_role:
                staff_ping = f" {staff_role.mention}"
        
        # Thread im Forum erstellen - KORREKTE METHODE FÜR ALLE DISCORD.PY VERSIONEN
        try:
            # Forum-Kanäle verwenden create_thread() mit content Parameter
            # Das Ergebnis ist ein ThreadWithMessage Objekt (hat .thread und .message Attribute)
            result = await forum.create_thread(
                name=f"Ticket #{ticket_id} - {ctx.author.name}",
                content=f"User: {ctx.author.mention}\nID: #{ticket_id}\nErstellt: <t:{int(datetime.now().timestamp())}:R>\n\nBitte beschreibe dein Anliegen hier...{staff_ping}",
                applied_tags=[],
                reason=f"Ticket von {ctx.author}"
            )
            
            # Extrahiere den eigentlichen Thread aus dem Ergebnis
            # ThreadWithMessage hat .thread Attribut, direkter Thread hat .id
            if hasattr(result, 'thread') and result.thread is not None:
                thread = result.thread
            elif hasattr(result, 'id'):
                thread = result
            else:
                raise RuntimeError(f"Unerwartetes Rückgabeformat: {type(result)}")
                
        except AttributeError as e:
            # Fallback: Vielleicht ist es ein TextChannel statt ForumChannel
            await ctx.send(f"❌ Der konfigurierte Channel ist kein gültiger Forum-Kanal. Bitte prüfe die Konfiguration mit `!ticketsetup show`")
            return
        except Exception as e:
            await ctx.send(f"❌ Fehler beim Erstellen des Tickets: {type(e).__name__}: {str(e)}")
            return
        
        # DM mit User erstellen
        try:
            dm_channel = await ctx.author.create_dm()
            await dm_channel.send(
                f"🎫 **Dein Ticket #{ticket_id} wurde eröffnet!**\n\n"
                f"**WICHTIG:** Antworte AUSSCHLIESSLICH in dieser Direktnachricht!\n"
                f"Deine Nachrichten werden automatisch an das Support-Team im Thread weitergeleitet.\n"
                f"Schreibe NICHT direkt im Thread - dies ist nur für das Support-Team.\n\n"
                f"Verwende `!close` oder `!schließen` um das Ticket zu schließen."
            )
        except Exception as e:
            await ctx.send("⚠️ Ich konnte dir keine DM senden. Bitte aktiviere DMs von Server-Mitgliedern.", ephemeral=True)
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
        
        # Caches aktualisieren für schnelle Lookups
        if dm_channel:
            self.dm_cache[dm_channel.id] = {"guild_id": guild.id, "ticket_id": ticket_id, **ticket_data}
        self.thread_cache[thread.id] = {"guild_id": guild.id, "ticket_id": ticket_id, **ticket_data}
        
        # Member-Ticket-Zuordnung speichern (neues System)
        member_tickets = await self.config.member(ctx.author).tickets()
        member_tickets.append({"guild_id": guild.id, "ticket_id": ticket_id})
        await self.config.member(ctx.author).tickets.set(member_tickets)
        
        # Bestätigung - NUR für den User sichtbar (ephemeral)
        embed = discord.Embed(
            title="🎫 Ticket erfolgreich erstellt!",
            description=f"Dein Ticket **#{ticket_id}** wurde eröffnet.",
            color=discord.Color.green()
        )
        embed.add_field(
            name="📌 Wichtiger Hinweis",
            value="Du musst jetzt in deinen **Direktnachrichten (DMs)** antworten!\n"
                  "Öffne deine DMs mit dem Bot und schreibe dort dein Anliegen.\n"
                  "Der Thread hier ist nur für das Support-Team sichtbar.",
            inline=False
        )
        embed.set_footer(text="Überprüfe deine DMs!")
        embed.timestamp = datetime.now()
        
        await ctx.send(embed=embed, ephemeral=True)
        
        # Staff-Benachrichtigung im Thread (staff_ping wurde bereits oben gesetzt)
        await thread.send(
            f"🆕 **Neues Ticket #{ticket_id}**\n"
            f"User: {ctx.author.mention}{staff_ping}\n\n"
            f"💡 **WICHTIG für Staff:** \n"
            f"- Der User sieht diesen Thread NICHT und kann hier nicht schreiben!\n"
            f"- Alle Antworten des Users kommen via DM - antworte HIER im Thread\n"
            f"- Deine Nachrichten werden automatisch als DM an den User gesendet\n"
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
        
        # Bestätigung für User - ephemeral damit nur der User es sieht
        await ctx.send(
            f"✅ Dein Ticket wurde erstellt: {channel.mention}\n\n"
            f"**Hinweis:** Du kannst in diesem Channel schreiben und das Team wird dir antworten.",
            ephemeral=True
        )
    
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
                await ctx.send(
                    "❌ Du hast kein aktives Ticket.\n\n"
                    "Verwende `!ticket` um ein neues Ticket zu erstellen.",
                    ephemeral=True
                )
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
        
        # Caches bereinigen
        thread_id = ticket_data.get("thread_id")
        dm_id = ticket_data.get("dm_id")
        if thread_id and thread_id in self.thread_cache:
            del self.thread_cache[thread_id]
        if dm_id and dm_id in self.dm_cache:
            del self.dm_cache[dm_id]
        
        await ctx.send(
            f"✅ **Ticket #{ticket_id} wurde geschlossen.**\n\n"
            f"Das Transcript wurde im Log-Channel gespeichert.\n"
            f"Falls du weitere Hilfe benötigst, erstelle einfach ein neues Ticket mit `!ticket`.",
            ephemeral=True
        )
    
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
        user = message.author  # Dies ist ein User-Objekt, kein Member!
        
        # Erster Versuch: Cache durchsuchen (schnell)
        if message.channel.id in self.dm_cache:
            ticket_data = self.dm_cache[message.channel.id]
            guild = self.bot.get_guild(ticket_data.get("guild_id"))
            if guild:
                thread_id = ticket_data.get("thread_id")
                thread = guild.get_channel(thread_id)
                if thread:
                    await self._forward_dm_to_thread(message, thread, user, ticket_data)
                    return
        
        # Zweiter Versuch: Alle Guilds durchsuchen (falls Cache veraltet)
        for guild in self.bot.guilds:
            async with self.config.guild(guild).open_tickets() as tickets:
                for ticket_id_str, ticket_data in tickets.items():
                    if ticket_data.get("user_id") == user.id and ticket_data.get("dm_id") == message.channel.id:
                        ticket_id = int(ticket_id_str)
                        thread_id = ticket_data.get("thread_id")
                        if thread_id:
                            thread = guild.get_channel(thread_id)
                            if thread:
                                # Cache aktualisieren
                                self.dm_cache[message.channel.id] = ticket_data
                                self.thread_cache[thread_id] = ticket_data
                                await self._forward_dm_to_thread(message, thread, user, ticket_data)
                                return
        
        # Kein Ticket gefunden - User informieren dass er zuerst !ticket verwenden muss
        # WICHTIG: Diese Nachricht sollte nur kommen wenn der User wirklich KEIN Ticket hat
        # und nicht wenn er einfach in seinen DMs schreibt OHNE Ticket
        # Wir prüfen zusätzlich ob der User überhaupt Tickets in der Member-Config hat
        member_tickets = await self.config.member(user).tickets()
        has_any_ticket = len(member_tickets) > 0
        
        if not has_any_ticket:
            # User hat noch nie ein Ticket erstellt - hilfreiche Anleitung
            try:
                await message.channel.send(
                    "⚠️ **Kein aktives Ticket gefunden!**\n\n"
                    "Du hast derzeit kein offenes Ticket auf einem Server.\n"
                    "Bitte gehe auf einen Server und verwende dort `!ticket` um ein neues Ticket zu erstellen.\n\n"
                    "**So funktioniert's:**\n"
                    "1. Gehe auf unseren Discord-Server\n"
                    "2. Schreibe `!ticket` in einen beliebigen Channel\n"
                    "3. Du erhältst eine DM von mir - antworte AUSSCHLIESSLICH dort!\n\n"
                    "**Wichtig:** Nach dem Erstellen eines Tickets wirst du hier in deinen DMs mit dem Support-Team kommunizieren."
                )
            except Exception:
                pass
        else:
            # User hat/hatte Tickets, aber keines ist aktuell aktiv - spezieller Hinweis
            try:
                await message.channel.send(
                    "⚠️ **Kein aktives Ticket gefunden!**\n\n"
                    "Du hast bereits Tickets erstellt, aber derzeit ist keines davon aktiv.\n"
                    "Möglicherweise wurde dein letztes Ticket geschlossen.\n\n"
                    "Bitte erstelle ein neues Ticket mit `!ticket` auf dem Server."
                )
            except Exception:
                pass
    
    async def _forward_dm_to_thread(self, message: discord.Message, thread: discord.Thread, user: discord.User, ticket_data: Dict):
        """Leitet eine DM-Nachricht an den Thread weiter"""
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
        embed.set_footer(text=f"📩 Vom User (Ticket)")
        
        try:
            webhook = await thread.create_webhook(name=user.name, avatar=user.display_avatar.url if user.display_avatar else None)
            await webhook.send(content=content if content else None, embed=embed if not content else None, files=files if files else None, username=user.name)
            await webhook.delete()
        except Exception:
            # Fallback wenn Webhook nicht erstellt werden kann
            try:
                await thread.send(content=f"📨 **Nachricht von {user.name}**:", embed=embed, files=files)
            except Exception as e:
                print(f"Fehler beim Senden an Thread: {e}")
    
    async def _handle_ticket_message(self, message: discord.Message, guild: discord.Guild):
        """Verarbeitet Staff-Nachrichten im Ticket und leitet sie an DM weiter"""
        
        # Erster Versuch: Cache durchsuchen (schnell)
        if message.channel.id in self.thread_cache:
            ticket_data = self.thread_cache[message.channel.id]
            await self._process_and_forward_to_dm(message, ticket_data, guild)
            return
        
        # Zweiter Versuch: Config durchsuchen
        ticket_data = None
        ticket_id = None
        
        async with self.config.guild(guild).open_tickets() as tickets:
            for tid, data in tickets.items():
                channel_id = data.get("channel_id") or data.get("thread_id")
                if channel_id == message.channel.id:
                    ticket_id = int(tid)
                    ticket_data = data
                    # Cache aktualisieren
                    self.thread_cache[channel_id] = data
                    break
        
        if not ticket_data:
            return
        
        await self._process_and_forward_to_dm(message, ticket_data, guild)
    
    async def _process_and_forward_to_dm(self, message: discord.Message, ticket_data: Dict, guild: discord.Guild):
        """Verarbeitet und leitet Nachricht an DM weiter"""
        
        # Prüfen ob Nachricht mit "." beginnt (intern, nicht weiterleiten)
        if message.content.startswith('.'):
            new_content = message.content[1:].lstrip()
            
            if new_content != message.content[1:]:
                try:
                    await message.delete()
                    await message.channel.send(
                        content=new_content,
                        reference=message.reference
                    )
                except Exception:
                    await message.edit(content=new_content)
            return
        
        # Staff-Rolle prüfen
        staff_role_id = await self.config.guild(guild).staff_role()
        is_staff = False
        if staff_role_id:
            staff_role = guild.get_role(staff_role_id)
            if staff_role and staff_role in message.author.roles:
                is_staff = True
        else:
            is_staff = True
        
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
    cog = TicketSystem(bot)
    # Persistent View registrieren, nachdem die Cog erstellt wurde
    bot.add_view(TicketCloseView(cog))
    await bot.add_cog(cog)
