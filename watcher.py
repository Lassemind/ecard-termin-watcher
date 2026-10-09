#!/usr/bin/env python3
"""Watches the BMI Online-Terminreservierung e-card Foto tool for Vienna
registration stations (non-Austrian citizens) and emails when new slots
appear."""
import json
import os
import re
import smtplib
import ssl
import sys
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText

from playwright.sync_api import sync_playwright

STATE_PATH = os.environ.get("STATE_PATH", "/app/data/state.json")
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "0"))
NOTIFY_WITHIN_DAYS = int(os.environ.get("NOTIFY_WITHIN_DAYS", "7"))

URL = "https://citizen.bmi.gv.at/at.gv.bmi.fnsetvweb-p/etv/public/Terminvereinbarung?locale=de"

SVNR = os.environ["SVNR"]
VORNAME = os.environ["VORNAME"]
NACHNAME = os.environ["NACHNAME"]
BOOKING_EMAIL = os.environ["BOOKING_EMAIL"]

# "Stelle"-Dropdown-Werte fuer Wien, Thema "Ecard - Fotoerfassung",
# Registrierungsstellen fuer Versicherte OHNE oesterreichische Staatsbuergerschaft.
STATIONS = {
    "329": "PK Favoriten (10. Bezirk)",
    "392": "PK Donaustadt (22. Bezirk)",
    "354": "PK Fuenfhaus (14./15. Bezirk)",
    "361": "PK Ottakring (16./17. Bezirk)",
    "295": "PK Josefstadt (7./8./9. Bezirk)",
    "378": "PK Brigittenau (2./20. Bezirk)",
    "276": "BFA Regionaldirektion Wien",
}

SUBJECT_TAG = os.environ.get("SUBJECT_TAG", "[e-card-Termin]")
EMAIL_TO = [a.strip() for a in os.environ["EMAIL_TO"].split(",") if a.strip()]
SMTP_FROM = os.environ.get("SMTP_FROM", EMAIL_TO[0])
SMTP_HOST = os.environ["SMTP_HOST"]
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
MAIL_USER = os.environ["MAIL_USER"]
MAIL_PASSWORD = os.environ["MAIL_PASSWORD"]

SLOT_RE = re.compile(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2}")


def parse_slot(slot_str):
    return datetime.strptime(slot_str, "%d.%m.%Y %H:%M:%S")


def log(msg):
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return {"slots": {}}


def save_state(state):
    tmp_path = STATE_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp_path, STATE_PATH)


def send_mail(recipients, subject, body):
    if not recipients:
        return
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = ", ".join(recipients)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as smtp:
        smtp.login(MAIL_USER, MAIL_PASSWORD)
        smtp.sendmail(SMTP_FROM, recipients, msg.as_string())


def fetch_slots_for_station(page, station_id):
    page.goto(URL, wait_until="networkidle")
    page.wait_for_timeout(1500)

    page.select_option('select[id*="bundesland#terminanfrage"]', "9")  # Wien
    page.wait_for_timeout(2000)

    page.select_option('select[id*="stelle#terminanfrage"]', station_id)
    page.wait_for_timeout(2000)

    page.select_option('select[id*="anzahl#terminanfrage"]', "1")
    page.wait_for_timeout(1500)

    page.fill('input[id*="sozialversicherungsnummer#terminanfrage"]', SVNR)
    page.wait_for_timeout(800)
    page.fill('input[id*="email#terminanfrage"]', BOOKING_EMAIL)
    page.wait_for_timeout(800)
    page.fill('input[id*="nachname#terminanfrage"]', NACHNAME)
    page.wait_for_timeout(800)
    page.fill('input[id*="vorname#terminanfrage"]', VORNAME)
    page.keyboard.press("Tab")
    # Die Felder werden einzeln per AJAX validiert (/api/validate/svn, /api/validate/mail);
    # der Button bleibt bis dahin disabled. Explizit darauf warten statt nur zu schlafen.
    btn = page.get_by_text("Mögliche Termine anzeigen", exact=False)
    btn.wait_for(state="visible", timeout=10000)
    for _ in range(40):  # bis zu 20s auf enabled warten
        if btn.is_enabled():
            break
        page.wait_for_timeout(500)
    btn.click(timeout=15000)
    page.wait_for_timeout(2500)

    body_text = page.inner_text("body")
    return sorted(set(SLOT_RE.findall(body_text)))


def main():
    state = load_state()
    previous = state.get("slots", {})
    current = {}
    new_by_station = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for station_id, name in STATIONS.items():
            try:
                slots = fetch_slots_for_station(page, station_id)
            except Exception as e:
                log(f"{name}: Fehler beim Abrufen: {e}")
                current[station_id] = previous.get(station_id, [])
                continue

            current[station_id] = slots
            prev_slots = set(previous.get(station_id, []))
            new_slots = sorted(set(slots) - prev_slots)
            if new_slots:
                new_by_station[station_id] = new_slots

            earliest = slots[0] if slots else "-"
            log(f"{name}: {len(slots)} Termin(e) gesamt, {len(new_slots)} neu. Fruehester: {earliest}")

        browser.close()

    state["slots"] = current
    save_state(state)

    # Nur neue Termine melden, die innerhalb von NOTIFY_WITHIN_DAYS Tagen liegen.
    cutoff = datetime.now() + timedelta(days=NOTIFY_WITHIN_DAYS)
    soon_by_station = {}
    for station_id, slots in new_by_station.items():
        soon = [s for s in slots if parse_slot(s) <= cutoff]
        if soon:
            soon_by_station[station_id] = soon

    if soon_by_station:
        lines = [
            f"Neue freie Termine fuer die e-card-Fotoregistrierung (Wien) innerhalb der naechsten {NOTIFY_WITHIN_DAYS} Tage:",
            "",
        ]
        for station_id, slots in soon_by_station.items():
            name = STATIONS[station_id]
            for s in slots:
                lines.append(f"- {name}: {s}")
        lines += [
            "",
            "Zur Info, aktueller fruehester Termin je Stelle (unabhaengig vom 7-Tage-Fenster):",
        ]
        for station_id, name in STATIONS.items():
            slots = current.get(station_id, [])
            earliest = slots[0] if slots else "keine im Fenster"
            lines.append(f"- {name}: {earliest}")
        lines += [
            "",
            f"Jetzt buchen: {URL}",
        ]
        body = "\n".join(lines)
        subject = f"{SUBJECT_TAG} Neuer Termin innerhalb der naechsten {NOTIFY_WITHIN_DAYS} Tage"
        try:
            send_mail(EMAIL_TO, subject, body)
            log(f"Benachrichtigung verschickt an {', '.join(EMAIL_TO)}.")
        except Exception as e:
            log(f"Mailversand fehlgeschlagen: {e}")
    elif new_by_station:
        log(f"Neue Termine gefunden, aber alle ausserhalb der {NOTIFY_WITHIN_DAYS}-Tage-Frist - keine Mail.")
    else:
        log("Keine neuen Termine in dieser Runde.")


if __name__ == "__main__":
    if POLL_INTERVAL_SECONDS > 0:
        log(f"Loop-Modus, pruefe alle {POLL_INTERVAL_SECONDS}s.")
        while True:
            try:
                main()
            except Exception as e:
                log(f"Fehler in diesem Durchlauf (Loop laeuft weiter): {e}")
            time.sleep(POLL_INTERVAL_SECONDS)
    else:
        try:
            main()
        except Exception as e:
            log(f"Fataler Fehler: {e}")
            sys.exit(1)
