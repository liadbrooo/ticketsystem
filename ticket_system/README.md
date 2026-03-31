# 🎫 Ticket System für RedBot

Ein professionelles Ticket-System ähnlich wie TicketPilot, speziell entwickelt für RedBot.

## ✨ Features

### Modi
- **Forum Mode**: Erstellt einen Forum-Thread + private DM-Konversation mit dem User
- **Classic Mode**: Erstellt einen privaten Textkanal nur für User und Staff

### Kernfunktionen
- 📨 **DM-Weiterleitung**: Nachrichten werden zwischen Thread/Kanal und User-DM weitergeleitet
- 🔒 **Interne Nachrichten**: Setze `.` vor eine Nachricht um sie nur im Team zu behalten
- 📄 **Transcripts**: Automatische Speicherung des gesamten Chats als `.txt`-Datei
- 👥 **Staff-Rollen**: Konfigurierbare Rolle für Team-Zugriff
- 🇩🇪 **Auf Deutsch**: Alle Befehle und Nachrichten auf Deutsch

---

## 📁 Installation

1. Kopiere den Ordner `ticket_system` in deinen RedBot-Cogs-Ordner:
   ```
   [RedBot-Pfad]/cogs/ticket_system/
   ```

2. Lade die Cog mit folgendem Befehl:
   ```
   [p]load ticket_system
   ```

---

## ⚙️ Einrichtung

Führe diese Befehle als Server-Owner aus:

```bash
# Forum-Channel setzen (für Forum Mode)
[p]ticketsetup forum #dein-forum-channel

# Kategorie setzen (für Classic Mode)
[p]ticketsetup category Deine-Kategorie

# Staff-Rolle festlegen
[p]ticketsetup role @Support-Team

# Log-Channel für Transcripts
[p]ticketsetup log #log-channel

# Modus wählen: "forum" oder "classic"
[p]ticketsetup mode forum

# Konfiguration anzeigen
[p]ticketsetup show
```

---

## 📖 Verwendung

### Für User
| Befehl | Beschreibung |
|--------|--------------|
| `!ticket` | Öffnet ein neues Support-Ticket |
| `!support` | Alias für !ticket |
| `!hilfe` | Alias für !ticket |
| `!close` | Schließt das aktuelle Ticket |
| `!schließen` | Alias für !close |

### Für Staff
| Befehl | Beschreibung |
|--------|--------------|
| `.Nachricht` | Sendet eine NUR interne Nachricht (nicht an User) |
| `!add @User` | Fügt Benutzer zum Ticket hinzu |
| `!remove @User` | Entfernt Benutzer aus dem Ticket |
| `!close` | Schließt das Ticket & erstellt Transcript |
| `!ticketinfo` | Zeigt Informationen zum aktuellen Ticket |

---

## 🔄 Funktionsweise

### Forum Mode
1. User öffnet Ticket mit `!ticket`
2. Bot erstellt Forum-Thread + sendet DM an User
3. Staff antwortet im Thread → wird an User-DM weitergeleitet
4. User antwortet per DM → wird im Thread angezeigt
5. Bei `.` Prefix bleibt Nachricht nur im Thread (intern)
6. Beim Schließen wird Transcript im Log-Channel gespeichert

### Classic Mode
1. User öffnet Ticket mit `!ticket`
2. Bot erstellt privaten Kanal (nur User + Staff)
3. Alle kommunizieren im Kanal
4. Bei `.` Prefix bleibt Nachricht nur intern sichtbar
5. Beim Schließen wird Kanal gelöscht + Transcript gespeichert

---

## 💡 Tipps

- **Interne Diskussionen**: Verwende `.Wir sollten das intern besprechen` um nur mit dem Team zu chatten
- **Dateien**: Bilder und Anhänge werden automatisch mitgesendet
- **Transcripts**: Alle geschlossenen Tickets werden im Log-Channel als Datei gespeichert
- **Mehrere Tickets**: Jeder User kann nur ein aktives Ticket gleichzeitig haben

---

## 🛠️ Support

Bei Problemen oder Fragen wende dich an den RedBot-Support oder überprüfe die Logs deines Bots.

**Viel Erfolg mit deinem Ticket-System!** 🎉
