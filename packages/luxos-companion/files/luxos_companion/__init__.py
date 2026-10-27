"""LuxOS Companion - spojeni s telefonem (aplikace LuxOS Companion pro Android) pres Bluetooth RFCOMM.

  wire          ramce protokolu v1 (UTF-8 JSON + LF, nejvys 65 536 bajtu)
  session       jedno spojeni: handshake, ping/pong, necinnost, rozdeleni zprav
  location      posledni cerstva poloha z telefonu (monotonni hodiny + age_ms, 15 s platnost)
  calendar_note calendar.note.create -> VEVENT v ~/.local/share/luxos/calendar/events.ics
  luxai_bridge  luxai.request/cancel -> luxai --remote-session (JSON radky)
  store         schvalene telefony a prepinace (~/.config/luxos/companion.json)
  bluez         profil RFCOMM v BlueZ (ProfileManager1.RegisterProfile, NewConnection)
  service       sluzba relace (systemd --user): D-Bus cz.luxos.Companion1, dotazy na schvaleni
  ui            okno Telefon (LuxOS Companion)

Kontrakt protokolu: docs/luxos/companion.md a PROTOCOL.md aplikace (v1).
"""
SERVICE_UUID = "ad9b7c10-6ce5-4f35-9952-728f760fcb70"
BUS_NAME = "cz.luxos.Companion1"
OBJECT_PATH = "/cz/luxos/Companion1"
INTERFACE = "cz.luxos.Companion1"
VERSION = "1.0.0"
