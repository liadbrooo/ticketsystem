"""
TicketPilot-ähnliches Ticket-System für RedBot

Funktionen:
- Forum Mode: DM mit User + Thread im Forum für Staff
- Classic Mode: Dedizierter Ticket-Kanal
- Nachrichten-Weiterleitung zwischen User (DM) und Staff (Thread/Kanal)
- Prefix "." verhindert Weiterleitung an User
- Transcript beim Schließen des Tickets
- Ticket-Panel mit Button zum Erstellen von Tickets
- Ticket-Info und Ticket-List Befehle
- Verbesserte Fehlermeldungen und Hinweise für User

Befehle:
- !ticket - Öffnet ein neues Ticket
- !close - Schließt das aktuelle Ticket
- !ticketinfo - Zeigt Informationen zum aktuellen Ticket
- !ticketlist - Listet alle aktiven Tickets (nur Staff)
- !add @user - Fügt Benutzer zum Ticket hinzu (Classic Mode)
- !remove @user - Entfernt Benutzer aus dem Ticket (Classic Mode)
- !ticketsetup - Konfiguriert das Ticket-System
"""

import discord
from discord.ext import commands
from typing import Optional, Dict, Any
import asyncio
import json
import io
from datetime import datetime
import redbot.vendored.discord as disc_


class TicketSystem(commands.Cog):
    """TicketPilot-ähnliches Ticket-System"""

    def __init__(self, bot):
        self.bot = bot
        self.tickets: Dict[int, dict] = {}  # ticket_id -> ticket_info
        self.user_tickets: Dict[int, int] = {}  # user_id -> ticket_id
        
    async def config_init(self):
        """Initialisiert die Config für den Cog"""
        self.config = self.bot._config_factory.get("COG", self.__class__.__name__)
        await self.config.set_default(
            guild=None,
            ticket_forum_channel=None,
            ticket_category=None,
            staff_role=None,
            ticket_log_channel=None,
            mode="forum",  # "forum" oder "classic"
            ticket_prefix="TICKET",
            close_prefix="."
        )

    def cog_unload(self):
        """Wird aufgerufen wenn der Cog entladen wird"""
        pass

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
                value="Setzt das Forum-Channel für Tickets (Forum Mode)",
                inline=False
            )
            embed.add_field(
                name="`{}ticketsetup category <category>`".format(ctx.prefix),
                value="Setzt die Kategorie für Classic-Mode Tickets",
                inline=False
            )
            embed.add_field(
                name="`{}ticketsetup role <role>`".format(ctx.prefix),
                value="Setzt die Staff-Rolle für Ticket-Zugriff",
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
                value="Erstellt ein Ticket-Erstellungs-Panel im angegebenen Channel",
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
        """Setzt den Ticket-Modus (forum oder classic)"""
        if mode.lower() not in ["forum", "classic"]:
            await ctx.send("❌ Ungültiger Modus. Verwende `forum` oder `classic`.")
            return
        await self.config.mode.set(mode.lower())
        await ctx.send(f"✅ Modus gesetzt: `{mode.lower()}`")

    @ticket_setup.command(name="show")
    @commands.is_owner()
    async def setup_show(self, ctx):
        """Zeigt die aktuelle Konfiguration"""
        mode = await self.config.mode()
        forum_id = await self.config.ticket_forum_channel()
        category_id = await self.config.ticket_category()
        role_id = await self.config.staff_role()
        log_id = await self.config.ticket_log_channel()

        embed = discord.Embed(title="📋 Ticket-System Konfiguration", color=discord.Color.green())
        embed.add_field(name="Modus", value=f"`{mode}`", inline=True)
        
        forum = ctx.guild.get_channel(forum_id) if forum_id else None
        embed.add_field(name="Forum-Channel", value=forum.mention if forum else "Nicht gesetzt", inline=True)
        
        category = ctx.guild.get_channel(category_id) if category_id else None
        embed.add_field(name="Kategorie", value=category.mention if category else "Nicht gesetzt", inline=True)
        
        role = ctx.guild.get_role(role_id) if role_id else None
        embed.add_field(name="Staff-Rolle", value=role.mention if role else "Nicht gesetzt", inline=True)
        
        log = ctx.guild.get_channel(log_id) if log_id else None
        embed.add_field(name="Log-Channel", value=log.mention if log else "Nicht gesetzt", inline=True)
        
        # Aktive Tickets anzeigen
        active_tickets = sum(1 for t in self.tickets.values() if not t.get("closed", False))
        embed.add_field(name="🎫 Aktive Tickets", value=f"`{active_tickets}`", inline=True)
        
        embed.set_footer(text="💡 Forum Mode: User schreiben im DM, Staff antwortet im Thread")
        await ctx.send(embed=embed)

    @ticket_setup.command(name="panel")
    @commands.is_owner()
    async def setup_panel(self, ctx, channel: discord.TextChannel):
        """Erstellt ein Ticket-Erstellungs-Panel im angegebenen Channel"""
        embed = discord.Embed(
            title="🎫 Support-Ticket erstellen",
            description="Klicke auf den Button unten, um ein Support-Ticket zu öffnen.\n\n"
                        "**Was passiert dann?**\n"
                        "• Ein Ticket wird für dich erstellt\n"
                        "• Du erhältst eine Direktnachricht vom Bot\n"
                        "• Schreibe dein Anliegen in diese DM\n"
                        "• Das Support-Team wird dir im Forum-Thread antworten\n\n"
                        "⚠️ **Wichtig:** Du kannst den Forum-Thread selbst nicht sehen.\n"
                        "Kommuniziere ausschließlich über deine Direktnachrichten!",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="ℹ️ Informationen",
            value="• Beschreibe dein Problem so genau wie möglich\n"
                  "• Sei höflich und geduldig\n"
                  "• Das Team meldet sich schnellstmöglich",
            inline=False
        )
        embed.set_footer(text="Support-Team | Antwortzeiten variieren")
        
        view = discord.ui.View()
        button = discord.ui.Button(
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
        
        # Simuliere einen ticket-Befehl
        user = interaction.user
        guild = interaction.guild
        
        # Prüfen ob User bereits ein offenes Ticket hat
        if user.id in self.user_tickets:
            ticket_id = self.user_tickets[user.id]
            if ticket_id in self.tickets:
                ticket_info = self.tickets[ticket_id]
                if not ticket_info.get("closed", False):
                    thread_id = ticket_info.get("thread_id")
                    channel_id = ticket_info.get("channel_id")
                    
                    if thread_id:
                        await interaction.followup.send(
                            embed=discord.Embed(
                                title="ℹ️ Bereits offenes Ticket",
                                description=f"Du hast bereits ein aktives Ticket: <#{thread_id}>\n\n"
                                            f"**Wichtig:** Du musst dich in deinen **Direktnachrichten (DMs)** melden.\n"
                                            f"Das Support-Team antwortet dir dort.",
                                color=discord.Color.blue()
                            ),
                            ephemeral=True
                        )
                    elif channel_id:
                        await interaction.followup.send(
                            embed=discord.Embed(
                                title="ℹ️ Bereits offenes Ticket",
                                description=f"Du hast bereits ein aktives Ticket: <#{channel_id}>",
                                color=discord.Color.blue()
                            ),
                            ephemeral=True
                        )
                    
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
                    except:
                        pass
                    return
        
        # Neues Ticket erstellen
        ctx_mock = type('obj', (object,), {'guild': guild, 'author': user, 'prefix': '!'})()
        await self._open_forum_ticket(ctx_mock, user, guild)
        
        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ Ticket wurde erstellt!",
                description="Bitte überprüfe deine **Direktnachrichten**.\n"
                            "Das Support-Team wird sich dort bei dir melden.",
                color=discord.Color.green()
            ),
            ephemeral=True
        )

    @commands.command(name="ticket", aliases=["support", "hilfe"])
    async def open_ticket(self, ctx):
        """Öffnet ein neues Ticket"""
        guild = ctx.guild
        user = ctx.author
        
        # Prüfen ob User bereits ein offenes Ticket hat
        if user.id in self.user_tickets:
            ticket_id = self.user_tickets[user.id]
            if ticket_id in self.tickets:
                ticket_info = self.tickets[ticket_id]
                if not ticket_info.get("closed", False):
                    thread_id = ticket_info.get("thread_id")
                    channel_id = ticket_info.get("channel_id")
                    dm_channel_id = ticket_info.get("dm_channel_id")
                    
                    if thread_id:
                        await ctx.send(
                            embed=discord.Embed(
                                title="ℹ️ Bereits offenes Ticket",
                                description=f"Du hast bereits ein aktives Ticket: <#{thread_id}>\n\n"
                                            f"**Wichtig:** Du musst dich in deinen **Direktnachrichten (DMs)** melden.\n"
                                            f"Das Support-Team antwortet dir dort.",
                                color=discord.Color.blue()
                            ),
                            delete_after=10
                        )
                    elif channel_id:
                        await ctx.send(
                            embed=discord.Embed(
                                title="ℹ️ Bereits offenes Ticket",
                                description=f"Du hast bereits ein aktives Ticket: <#{channel_id}>",
                                color=discord.Color.blue()
                            ),
                            delete_after=10
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
                    except:
                        pass
                    return

        mode = await self.config.mode()
        
        if mode == "forum":
            await self._open_forum_ticket(ctx, user, guild)
        else:
            await self._open_classic_ticket(ctx, user, guild)

    async def _open_forum_ticket(self, ctx, user, guild):
        """Erstellt ein Ticket im Forum-Modus"""
        forum_id = await self.config.ticket_forum_channel()
        if not forum_id:
            await ctx.send("❌ Kein Forum-Channel konfiguriert. Bitte wende dich an einen Administrator.")
            return
        
        forum = guild.get_channel(forum_id)
        if not forum or not isinstance(forum, discord.ForumChannel):
            await ctx.send("❌ Forum-Channel nicht gefunden.")
            return

        # DM mit User öffnen
        try:
            dm_channel = await user.create_dm()
            await dm_channel.send(
                embed=discord.Embed(
                    title="🎫 Ticket eröffnet",
                    description="Dein Ticket wurde erfolgreich erstellt. Du kannst hier mit dem Support-Team kommunizieren.",
                    color=discord.Color.green()
                )
            )
        except discord.Forbidden:
            await ctx.send("❌ Ich kann dir keine Direktnachrichten senden. Bitte aktiviere DMs von Server-Mitgliedern.")
            return

        # Thread im Forum erstellen
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        thread_name = f"🎫 {user.name} | {timestamp}"
        
        staff_role_id = await self.config.staff_role()
        content = f"<@&{staff_role_id}>" if staff_role_id else ""
        
        try:
            thread = await forum.create_thread(
                name=thread_name,
                content=f"{content}\nNeues Ticket von {user.mention}",
                applied_tags=thread.applied_tags[:1] if hasattr(thread, 'applied_tags') and thread.applied_tags else []
            )
        except:
            thread = await forum.create_thread(
                name=thread_name,
                content=f"{content}\nNeues Ticket von {user.mention}"
            )

        # Ticket speichern
        ticket_id = thread.id
        self.tickets[ticket_id] = {
            "user_id": user.id,
            "channel_id": None,
            "thread_id": thread.id,
            "dm_channel_id": dm_channel.id,
            "guild_id": guild.id,
            "closed": False,
            "created_at": datetime.now().isoformat(),
            "messages": []
        }
        self.user_tickets[user.id] = ticket_id

        embed = discord.Embed(
            title="✅ Ticket erstellt",
            description=f"Dein Ticket wurde im Forum erstellt.\nDas Team wird sich bald melden.",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed, delete_after=5)

        info_embed = discord.Embed(
            title="📝 Ticket-Informationen",
            description=f"Ticket-ID: `{ticket_id}`\nErstellt: <t:{int(datetime.now().timestamp())}:R>",
            color=discord.Color.blue()
        )
        info_embed.add_field(
            name="So funktioniert es:",
            value="• Deine Nachrichten hier (DM) werden an das Team im Thread weitergeleitet\n"
                  "• Team-Antworten erscheinen hier\n"
                  "• Wenn das Team vor eine Nachricht ein `.` setzt, bleibt sie nur im Thread\n"
                  "• Verwende `!close` um das Ticket zu schließen",
            inline=False
        )
        info_embed.add_field(
            name="💡 Wichtiger Hinweis:",
            value="Du als Ticket-Ersteller kannst den Thread im Forum **nicht sehen**.\n"
                  "**Schreibe ausschließlich in deine Direktnachrichten mit dem Bot!**",
            inline=False
        )
        await dm_channel.send(embed=info_embed)

    async def _open_classic_ticket(self, ctx, user, guild):
        """Erstellt ein Ticket im Classic-Modus (dedizierter Kanal)"""
        category_id = await self.config.ticket_category()
        
        if category_id:
            category = guild.get_channel(category_id)
        else:
            category = None

        # DM mit User öffnen
        try:
            dm_channel = await user.create_dm()
            await dm_channel.send(
                embed=discord.Embed(
                    title="🎫 Ticket eröffnet",
                    description="Dein Ticket wurde erfolgreich erstellt.",
                    color=discord.Color.green()
                )
            )
        except discord.Forbidden:
            pass  # DM optional im Classic-Mode

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
        self.tickets[ticket_id] = {
            "user_id": user.id,
            "channel_id": channel.id,
            "thread_id": None,
            "dm_channel_id": dm_channel.id if not ctx.guild.get_channel(dm_channel.id) else None,
            "guild_id": guild.id,
            "closed": False,
            "created_at": datetime.now().isoformat(),
            "messages": []
        }
        self.user_tickets[user.id] = ticket_id

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

        await ctx.send(f"✅ Ticket erstellt: {channel.mention}", delete_after=5)

    @commands.command(name="close", aliases=["schließen"])
    async def close_ticket(self, ctx):
        """Schließt das aktuelle Ticket"""
        ticket_id = None
        
        # Prüfen ob im Ticket-Kanal/Thread
        if ctx.channel.id in self.tickets:
            ticket_id = ctx.channel.id
        else:
            # Prüfen ob User ein Ticket hat
            if ctx.author.id in self.user_tickets:
                ticket_id = self.user_tickets[ctx.author.id]
            else:
                # Prüfen ob Channel ein Thread in einem Ticket-Forum ist
                if hasattr(ctx.channel, 'parent') and ctx.channel.parent:
                    for tid, info in self.tickets.items():
                        if info.get("thread_id") == ctx.channel.id:
                            ticket_id = tid
                            break

        if not ticket_id or ticket_id not in self.tickets:
            await ctx.send(
                embed=discord.Embed(
                    title="⚠️ Kein aktives Ticket",
                    description="Ich konnte kein aktives Ticket für dich finden.\n\n"
                              "ℹ️ **Wichtig:** Als Ticket-Ersteller musst du dich in deinen **Direktnachrichten (DMs)** melden.\n"
                              "Das Support-Team antwortet dir dort.\n\n"
                              "🎫 Öffne ein neues Ticket mit `{}ticket`".format(ctx.prefix),
                    color=discord.Color.orange()
                )
            )
            return

        ticket_info = self.tickets[ticket_id]
        
        # Nur Staff oder Ticket-Ersteller können schließen
        staff_role_id = await self.config.staff_role()
        is_staff = False
        if staff_role_id:
            staff_role = ctx.guild.get_role(staff_role_id)
            if staff_role and staff_role in ctx.author.roles:
                is_staff = True
        
        if ctx.author.id != ticket_info["user_id"] and not is_staff and not await self.bot.is_owner(ctx.author):
            await ctx.send("❌ Nur der Ticket-Ersteller oder Staff können das Ticket schließen.")
            return

        # Transcript erstellen
        await self._create_transcript(ctx, ticket_id)

        # Ticket als geschlossen markieren
        ticket_info["closed"] = True
        
        # User informieren
        user_id = ticket_info["user_id"]
        user = ctx.guild.get_member(user_id)
        if user:
            try:
                dm_channel = self.bot.get_channel(ticket_info.get("dm_channel_id"))
                if not dm_channel:
                    dm_channel = await user.create_dm()
                await dm_channel.send(
                    embed=discord.Embed(
                        title="🔒 Ticket geschlossen",
                        description="Dein Ticket wurde geschlossen.\nBei weiteren Fragen eröffne gerne ein neues Ticket.",
                        color=discord.Color.orange()
                    )
                )
            except:
                pass

        # Kanal/Thread archivieren/löschen
        channel = ctx.guild.get_channel(ticket_info.get("channel_id"))
        thread = None
        if ticket_info.get("thread_id"):
            thread = ctx.guild.get_channel(ticket_info["thread_id"])
            if thread:
                await thread.edit(archived=True)
        
        if channel and channel != ctx.channel:
            await channel.delete()
        
        # Aus dicts entfernen
        if user_id in self.user_tickets:
            del self.user_tickets[user_id]
        
        await ctx.send("✅ Ticket wurde geschlossen und protokolliert.")

    async def _create_transcript(self, ctx, ticket_id: int):
        """Erstellt ein Transcript des Tickets"""
        ticket_info = self.tickets.get(ticket_id)
        if not ticket_info:
            return

        log_channel_id = await self.config.ticket_log_channel()
        if not log_channel_id:
            return

        log_channel = ctx.guild.get_channel(log_channel_id)
        if not log_channel:
            return

        user_id = ticket_info["user_id"]
        user = ctx.guild.get_member(user_id)
        user_name = user.name if user else f"User-{user_id}"

        # Transcript als Textdatei
        transcript_content = f"=== TICKET TRANSCRIPT ===\n"
        transcript_content += f"Ticket-ID: {ticket_id}\n"
        transcript_content += f"User: {user_name} ({user_id})\n"
        transcript_content += f"Erstellt: {ticket_info.get('created_at', 'Unbekannt')}\n"
        transcript_content += f"Geschlossen: {datetime.now().isoformat()}\n"
        transcript_content += f"{'='*50}\n\n"

        # Nachrichten aus dem Channel/Thread holen
        messages_list = []
        channel_id = ticket_info.get("channel_id") or ticket_info.get("thread_id")
        if channel_id:
            channel = ctx.guild.get_channel(channel_id)
            if channel:
                try:
                    async for msg in channel.history(limit=1000, oldest_first=True):
                        timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
                        author = msg.author.name if msg.author else "Unbekannt"
                        content = msg.content.replace("\n", "\\n")
                        transcript_content += f"[{timestamp}] {author}: {content}\n"
                        
                        # Auch für interne Speicherung
                        messages_list.append({
                            "timestamp": timestamp,
                            "author": author,
                            "author_id": msg.author.id if msg.author else 0,
                            "content": msg.content,
                            "is_staff": staff_role_id and msg.author and any(r.id == staff_role_id for r in msg.author.roles) if (staff_role_id := await self.config.staff_role()) else False
                        })
                except Exception as e:
                    transcript_content += f"\n[Fehler beim Laden der Nachrichten: {e}]\n"

        # Datei erstellen und senden
        transcript_bytes = transcript_content.encode("utf-8")
        file = discord.File(io.BytesIO(transcript_bytes), filename=f"ticket-{ticket_id}-transcript.txt")

        embed = discord.Embed(
            title="📄 Ticket Transcript",
            description=f"Ticket von {user_name} (ID: {ticket_id})",
            color=discord.Color.blue()
        )
        embed.add_field(name="Erstellt", value=ticket_info.get('created_at', 'Unbekannt'), inline=True)
        embed.add_field(name="Geschlossen", value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), inline=True)
        embed.add_field(name="Nachrichten", value=str(len(messages_list)), inline=True)

        await log_channel.send(embed=embed, file=file)

    # Event Handler für Nachrichten-Weiterleitung
    @commands.Cog.listener()
    async def on_message(self, message):
        """Verarbeitet Nachrichten für Ticket-Weiterleitung"""
        if message.author.bot:
            return

        # Prüfen ob Nachricht in einem Ticket-Kanal/Thread
        ticket_id = None
        ticket_info = None

        # Ist die Nachricht in einem Ticket-Channel?
        if message.channel.id in self.tickets:
            ticket_id = message.channel.id
            ticket_info = self.tickets[ticket_id]
        else:
            # Ist die Nachricht in einem Ticket-Thread?
            for tid, info in self.tickets.items():
                if info.get("thread_id") == message.channel.id:
                    ticket_id = tid
                    ticket_info = info
                    break
                if info.get("channel_id") == message.channel.id:
                    ticket_id = tid
                    ticket_info = info
                    break

        if not ticket_info:
            return

        # Nachricht speichern
        if ticket_info.get("messages") is None:
            ticket_info["messages"] = []
        
        staff_role_id = await self.config.staff_role()
        is_staff = False
        if staff_role_id and message.guild:
            staff_role = message.guild.get_role(staff_role_id)
            if staff_role and staff_role in message.author.roles:
                is_staff = True

        ticket_info["messages"].append({
            "timestamp": message.created_at.isoformat(),
            "author": message.author.name,
            "author_id": message.author.id,
            "content": message.content,
            "is_staff": is_staff
        })

        # Prüfen ob Nachricht mit "." beginnt (nicht an User weiterleiten)
        if message.content.strip().startswith("."):
            # Nachricht nur intern behalten
            clean_content = message.content[1:].strip()
            if clean_content:
                # Optional: Nachricht bearbeiten um "." zu entfernen
                try:
                    await message.edit(content=clean_content)
                except:
                    pass
            return

        # Weiterleitung verarbeiten
        user_id = ticket_info["user_id"]
        
        # Fall 1: Nachricht vom User (im Classic-Channel oder Thread)
        if message.author.id == user_id:
            # An Staff im Thread/Channel ist schon sichtbar
            # Optional: Bestätigung an User
            pass

        # Fall 2: Nachricht von Staff im Thread
        if ticket_info.get("thread_id") == message.channel.id:
            if is_staff or await self.bot.is_owner(message.author):
                # An User per DM weiterleiten
                dm_channel_id = ticket_info.get("dm_channel_id")
                if dm_channel_id:
                    dm_channel = self.bot.get_channel(dm_channel_id)
                    if not dm_channel:
                        try:
                            user = message.guild.get_member(user_id)
                            if user:
                                dm_channel = await user.create_dm()
                                ticket_info["dm_channel_id"] = dm_channel.id
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
                        
                        await dm_channel.send(embed=embed, files=files)

        # Fall 3: Nachricht vom User per DM
        dm_channel_id = ticket_info.get("dm_channel_id")
        if dm_channel_id and message.channel.id == dm_channel_id:
            if message.author.id == user_id:
                # An Thread weiterleiten
                thread_id = ticket_info.get("thread_id")
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
                        
                        await thread.send(embed=embed, files=files)

                # Auch im Classic-Channel falls vorhanden
                channel_id = ticket_info.get("channel_id")
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
                        
                        await channel.send(embed=embed, files=files)

    @commands.command(name="add", aliases=["hinzufügen"])
    @commands.has_permissions(manage_channels=True)
    async def add_to_ticket(self, ctx, member: discord.Member):
        """Fügt einen Benutzer zum Ticket hinzu"""
        ticket_id = ctx.channel.id
        
        if ticket_id not in self.tickets:
            # Prüfen ob Thread
            for tid, info in self.tickets.items():
                if info.get("thread_id") == ctx.channel.id or info.get("channel_id") == ctx.channel.id:
                    ticket_id = tid
                    break
            else:
                await ctx.send("❌ Dieser Kanal ist kein Ticket.")
                return

        ticket_info = self.tickets[ticket_id]
        channel_id = ticket_info.get("channel_id")
        
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
            for tid, info in self.tickets.items():
                if info.get("thread_id") == ctx.channel.id or info.get("channel_id") == ctx.channel.id:
                    ticket_id = tid
                    break
            else:
                await ctx.send("❌ Dieser Kanal ist kein Ticket.")
                return

        ticket_info = self.tickets[ticket_id]
        channel_id = ticket_info.get("channel_id")
        
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
        
        # Prüfen ob im Ticket-Kanal/Thread
        if ctx.channel.id in self.tickets:
            ticket_id = ctx.channel.id
        elif ctx.author.id in self.user_tickets:
            ticket_id = self.user_tickets[ctx.author.id]
        
        if not ticket_id or ticket_id not in self.tickets:
            await ctx.send(
                embed=discord.Embed(
                    title="ℹ️ Kein aktives Ticket",
                    description="Du hast derzeit kein offenes Ticket.\nVerwende `!ticket` um ein neues zu erstellen.",
                    color=discord.Color.orange()
                ),
                delete_after=10
            )
            return
        
        ticket_info = self.tickets[ticket_id]
        user_id = ticket_info["user_id"]
        user = ctx.guild.get_member(user_id)
        user_name = user.name if user else f"User-{user_id}"
        
        thread_id = ticket_info.get("thread_id")
        channel_id = ticket_info.get("channel_id")
        
        embed = discord.Embed(
            title="🎫 Ticket-Informationen",
            description=f"Ticket-ID: `{ticket_id}`",
            color=discord.Color.blue()
        )
        embed.add_field(name="👤 Ticket-Ersteller", value=user.mention if user else user_name, inline=True)
        embed.add_field(name="📅 Erstellt am", value=f"<t:{int(datetime.fromisoformat(ticket_info['created_at']).timestamp())}:R>", inline=True)
        embed.add_field(name="🔒 Status", value="Geschlossen" if ticket_info.get("closed", False) else "Offen", inline=True)
        
        if thread_id:
            embed.add_field(name="📝 Forum-Thread", value=f"<#{thread_id}>", inline=True)
        if channel_id:
            embed.add_field(name="📝 Ticket-Kanal", value=f"<#{channel_id}>", inline=True)
        
        message_count = len(ticket_info.get("messages", []))
        embed.add_field(name="💬 Nachrichten", value=f"`{message_count}`", inline=True)
        
        # Hinweis für User
        if ctx.author.id == user_id:
            embed.add_field(
                name="💡 Dein Hinweis",
                value="Als Ticket-Ersteller musst du dich in deinen **Direktnachrichten** melden.\nDas Support-Team antwortet dir dort!",
                inline=False
            )
        
        await ctx.send(embed=embed, delete_after=30)

    @commands.command(name="ticketlist", aliases=["tl", "alle tickets"])
    @commands.has_permissions(manage_roles=True)
    async def ticket_list(self, ctx):
        """Listet alle aktiven Tickets auf (nur für Staff)"""
        active_tickets = [t for t in self.tickets.values() if not t.get("closed", False)]
        
        if not active_tickets:
            await ctx.send(
                embed=discord.Embed(
                    title="🎫 Alle Tickets",
                    description="Derzeit sind keine aktiven Tickets offen.",
                    color=discord.Color.green()
                ),
                delete_after=10
            )
            return
        
        embed = discord.Embed(
            title="🎫 Aktive Tickets",
            description=f"Insgesamt **{len(active_tickets)}** offene(s) Ticket(s)",
            color=discord.Color.blue()
        )
        
        for i, ticket in enumerate(active_tickets[:10], 1):  # Max 10 anzeigen
            user_id = ticket["user_id"]
            user = ctx.guild.get_member(user_id)
            user_name = user.name if user else f"User-{user_id}"
            
            thread_id = ticket.get("thread_id")
            channel_id = ticket.get("channel_id")
            created = ticket.get("created_at", "")
            
            location = ""
            if thread_id:
                location = f"Thread: <#{thread_id}>"
            elif channel_id:
                location = f"Kanal: <#{channel_id}>"
            
            time_str = ""
            if created:
                try:
                    ts = int(datetime.fromisoformat(created).timestamp())
                    time_str = f" • <t:{ts}:R>"
                except:
                    pass
            
            embed.add_field(
                name=f"{i}. {user_name}",
                value=f"{location}{time_str}",
                inline=False
            )
        
        if len(active_tickets) > 10:
            embed.set_footer(text=f"... und {len(active_tickets) - 10} weitere Tickets")
        
        await ctx.send(embed=embed)


async def setup(bot):
    """Lädt den Cog"""
    cog = TicketSystem(bot)
    await cog.config_init()
    await bot.add_cog(cog)
