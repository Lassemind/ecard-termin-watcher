# ecard-termin-watcher

Überwacht das Online-Terminreservierungssystem des BMI für die **e-card-Fotoerfassung** (Wien, Registrierungsstellen für Versicherte ohne österreichische Staatsbürgerschaft) und schickt eine E-Mail, sobald neue freie Termine in den nächsten Tagen auftauchen.

## Funktionsweise

- Ein headless Chromium (Playwright) füllt das Formular für jede konfigurierte Stelle aus und liest die angezeigten Termine aus.
- Der letzte Stand liegt in `data/state.json`; gemeldet werden nur *neue* Termine innerhalb von `NOTIFY_WITHIN_DAYS` Tagen.
- Die Mail enthält zusätzlich den frühesten Termin je Stelle.

## Einrichtung

```bash
cp .env.example .env   # Werte eintragen
docker compose up -d --build
docker compose logs -f
```

Abfrageintervall: `POLL_INTERVAL_SECONDS` in `docker-compose.yml` (Standard 900 s).

## Konfiguration (`.env`)

| Variable | Bedeutung |
|---|---|
| `SVNR`, `VORNAME`, `NACHNAME`, `BOOKING_EMAIL` | Angaben für das Buchungsformular |
| `EMAIL_TO` | Empfänger (kommagetrennt) |
| `SMTP_HOST`, `SMTP_PORT`, `MAIL_USER`, `MAIL_PASSWORD`, `SMTP_FROM` | SMTP-Zugang (SSL) |
| `SUBJECT_TAG` | Betreff-Präfix |
| `NOTIFY_WITHIN_DAYS` | Nur Termine innerhalb dieser Tage melden (Standard 7) |

Die Stellen stehen im Dict `STATIONS` in `watcher.py` und lassen sich dort anpassen.

## Datenschutz

Persönliche Daten (Sozialversicherungsnummer, Name, Mail, SMTP-Passwort) stehen ausschließlich in der lokalen `.env`, die per `.gitignore` ausgeschlossen ist. `data/` ist ebenfalls ignoriert.

## Hinweis

Inoffizielles Hilfsprogramm, nicht mit dem BMI verbunden. Das Formular wird nur abgefragt, nie abgeschickt. Bitte ein moderates Intervall verwenden.
