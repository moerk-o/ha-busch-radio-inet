#!/usr/bin/env python3
"""
Testet PLAY STATION Befehle an das Busch-Jäger iNET Radio.

WICHTIG: Die HA-Integration muss gestoppt/deaktiviert sein,
damit Port 4242 frei ist!

Ablauf:
  1. Holt ALL_STATION_INFO (echte IDs + Namen vom Gerät)
  2. Sendet PLAY STATION:<id> für jede Station
  3. Zeigt Antwort des Geräts

Aufruf:
  python test_play.py              # testet alle Stationen
  python test_play.py 1            # testet nur Station 1
"""

import socket
import sys
import time

RADIO_IP = "192.168.1.179"
SEND_PORT = 4244
RECV_PORT = 4242
TIMEOUT = 3.0


def send_recv(cmd_type: str, param: str, sock_send, sock_recv) -> str | None:
    message = f"COMMAND:{cmd_type}\r\n{param}\r\nID:TEST\r\n\r\n"
    print(f"\n>>> {repr(message)}")
    sock_send.sendto(message.encode(), (RADIO_IP, SEND_PORT))
    try:
        data, addr = sock_recv.recvfrom(4096)
        resp = data.decode("utf-8", errors="replace")
        print(f"<<< {repr(resp)}")
        return resp
    except socket.timeout:
        print("<<< TIMEOUT")
        return None


def send_only(cmd_type: str, param: str, sock_send) -> None:
    """Sendet ohne auf Antwort zu warten (wenn Port 4242 belegt ist)."""
    message = f"COMMAND:{cmd_type}\r\n{param}\r\nID:TEST\r\n\r\n"
    print(f"\n>>> {repr(message)}")
    sock_send.sendto(message.encode(), (RADIO_IP, SEND_PORT))


def main():
    sock_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Versuche Port 4242 zu binden für Antworten
    sock_recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock_recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    can_receive = False
    try:
        sock_recv.bind(("", RECV_PORT))
        sock_recv.settimeout(TIMEOUT)
        can_receive = True
        print(f"Port {RECV_PORT} gebunden – Antworten werden empfangen.")
    except OSError as e:
        print(f"Port {RECV_PORT} nicht verfügbar ({e}).")
        print("Sende-Modus: Befehle werden gesendet, Antworten kommen in HA.")
        print("Beobachte ob das Radio die Station wechselt!")

    try:
        if can_receive:
            # Hole zuerst die echten Stations-IDs vom Gerät
            print("\n" + "=" * 60)
            print("Schritt 1: ALL_STATION_INFO")
            print("=" * 60)
            resp = send_recv("GET", "ALL_STATION_INFO", sock_send, sock_recv)

            if resp:
                # Parse CHANNEL/NAME aus der Antwort
                stations = []
                lines = resp.split("\r\n")
                channels = [l.split(":", 1)[1].strip() for l in lines
                            if l.startswith("CHANNEL:")]
                names = [l.split(":", 1)[1].strip() for l in lines
                         if l.startswith("NAME:")]
                for ch, nm in zip(channels, names):
                    if nm:
                        stations.append((ch, nm))
                        print(f"  Station: CHANNEL={ch!r}  NAME={nm!r}")
            else:
                stations = []

            # Bestimme welche Stationen getestet werden
            if len(sys.argv) > 1:
                test_ids = [sys.argv[1]]
            elif stations:
                test_ids = [ch for ch, _ in stations]
            else:
                test_ids = ["1", "2", "3"]

            print("\n" + "=" * 60)
            print("Schritt 2: PLAY STATION testen")
            print("=" * 60)
            for sid in test_ids:
                time.sleep(1.0)
                print(f"\n--- PLAY STATION:{sid} ---")
                send_recv("PLAY", f"STATION:{sid}", sock_send, sock_recv)

        else:
            # Kein Empfang möglich – nur senden
            if len(sys.argv) > 1:
                sid = sys.argv[1]
            else:
                sid = "1"
            print(f"\n Sende PLAY STATION:{sid} ...")
            send_only("PLAY", f"STATION:{sid}", sock_send)
            print("Befehl gesendet. Wechselt das Radio die Station? (physisch prüfen)")
            print()
            print("Andere Stationen testen:")
            print("  python test_play.py 2")
            print("  python test_play.py 3")

    finally:
        sock_send.close()
        sock_recv.close()


if __name__ == "__main__":
    main()
