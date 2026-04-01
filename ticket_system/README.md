# 🎫 Ticket System für RedBot

Ein professionelles, modernes Ticket-System mit Panel-Auswahl, DM-Weiterleitung und Transcript-Funktion.

## ✨ Features

### 📋 Panel-System
- **Vorgefertigte Kategorien**: Allgemeiner Support, Bug Report, Teamverwaltung, Vorschläge
- **Individuelle Panels**: Eigene Kategorien mit `!ticketsetup panel add` erstellen
- **Moderne UI**: Select-Menü zur Kategorie-Auswahl

### 🔄 Zwei Betriebsmodi
1. **Forum Mode** (Standard)
   - Erstellt Forum-Thread für Staff
   - Private DM mit User
   - Nachrichten werden zwischen Thread und DM weitergeleitet
   - **User kommunizieren AUSSCHLIESSLICH in ihren DMs!**

2. **Classic Mode**
   - Erstellt privaten Textkanal
   - Nur User und Staff haben Zugriff

### 💬 Nachrichten-Weiterleitung
- **Staff antwortet im Thread/Kanal** → wird an User-DM gesendet (Forum Mode)
- **Prefix "."**: Setze `.` vor eine Nachricht → bleibt nur intern, wird NICHT an User gesendet
- **Dateianhänge**: Werden automatisch mit weitergeleitet

### 🔒 Ticket schließen
- **Button**: Klick auf "🔒 Ticket schließen" Button
- **Befehl**: `!close` oder `!schließen`
- **Transcript**: Gesamter Chat wird als `.txt`-Datei im Log-Channel gespeichert
- **Benachrichtigung**: User erhält DM über Schließung

## 📥 Installation

1. Ordner `ticket_system` in den Cogs-Ordner deines Redbots kopieren
2. Cog laden: `[p]load ticket_system`

## ⚙️ Einrichtung

```bash
# Basis-Konfiguration
[p]ticketsetup forum #forum-channel      # Forum-Channel setzen (für Forum Mode)
[p]ticketsetup category <Kategorie>       # Kategorie setzen (für Classic Mode)
[p]ticketsetup role @Staff                # Staff-Rolle festlegen
[p]ticketsetup log #log-channel           # Channel für Transcripts
[p]ticketsetup mode forum                 # oder "classic"

# Konfiguration anzeigen
[p]ticketsetup show

# Panel-Verwaltung
[p]ticketsetup panel list                 # Alle Panels anzeigen
[p]ticketsetup panel add <id> <Name>      # Neues Panel erstellen
[p]ticketsetup panel remove <id>          # Panel entfernen
```

## 📖 Verwendung

### Für Benutzer
| Befehl | Beschreibung |
|--------|--------------|
| `!ticket`, `!support`, `!newticket` | Öffnet Ticket mit Kategorie-Auswahl |
| `!close`, `!schließen` | Schließt das eigene Ticket |
| `!ticketinfo` | Zeigt Informationen zum aktuellen Ticket |

**WICHTIG für Forum Mode:**
- Nach dem Erstellen eines Tickets erhältst du eine DM vom Bot
- **Antworte AUSSCHLIESSLICH in dieser DM** - deine Nachrichten werden an das Support-Team weitergeleitet
- Du kannst den Forum-Thread selbst NICHT sehen oder darin schreiben
- Das Support-Team antwortet dir ebenfalls per DM

### Für Staff
| Aktion | Beschreibung |
|--------|--------------|
| Im Thread antworten | Nachricht wird an User (DM) weitergeleitet |
| `.Nachricht` | Mit Punkt-Präfix: Nur intern, nicht an User |
| `!add @User` | Benutzer zum Ticket hinzufügen (Classic Mode) |
| `!remove @User` | Benutzer aus Ticket entfernen (Classic Mode) |
| Auf 🔒 klicken | Ticket über Button schließen |

## 🔧 Standard-Panels

| ID | Name | Emoji | Beschreibung |
|----|------|-------|--------------|
| `general` | Allgemeiner Support | 📧 | Für allgemeine Fragen und Hilfe |
| `bug` | Bug Report | 🐛 | Fehler melden |
| `team` | Teamverwaltung | 👥 | Anfragen an das Team |
| `suggest` | Vorschläge | 💡 | Ideen und Vorschläge einreichen |

## 💡 Tipps

- **Interne Notizen**: Verwende `.` am Anfang einer Nachricht für interne Absprachen im Team
- **Berechtigungen**: Stelle sicher, dass der Bot Berechtigungen hat, Channels/Threads zu erstellen
- **DMs**: User müssen DMs vom Server erlaubt haben für die Weiterleitung
- **Logs**: Richte einen Log-Channel ein, um alle Transcripts zu speichern
- **User-Hinweis**: Weise User darauf hin, dass sie NUR in ihren DMs antworten sollen

## ❓ Support

Bei Problemen prüfe:
1. Ist der Cog geladen? `[p]loadedcogs`
2. Ist die Konfiguration vollständig? `[p]ticketsetup show`
3. Hat der Bot alle notwendigen Berechtigungen?
4. Haben die User DMs aktiviert?

## 🆘 Häufige Probleme

### User schreibt in DM aber nichts passiert
- Prüfe ob der User ein aktives Ticket hat (`!ticketinfo`)
- Der Bot muss Mitglied des Servers sein wo das Ticket erstellt wurde

### "Kein aktives Ticket gefunden" Meldung
- Diese Meldung erscheint wenn ein User in die DM des Bots schreibt OHNE zuvor ein Ticket erstellt zu haben
- Lösung: User muss auf einem Server `!ticket` verwenden

### Staff-Nachrichten kommen nicht beim User an
- Prüfe ob der User DMs von Server-Mitgliedern erlaubt hat
- Der Bot braucht die Berechtigung "Nachrichten senden" in der DM
