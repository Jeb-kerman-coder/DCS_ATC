import json
import socket
import threading
import time

EVENT_HOST = "127.0.0.1"
EVENT_PORT = 5018


class DCSEventListener:
    """
    Receives the events the Lua bridge sends on its own (weapon shots,
    takeoff/landing, kills, radar contacts) and hands each one to
    on_event(dict) on a background thread.

    keepalive() is called every few seconds; main.py uses it to re-send
    the "watch this aircraft" request, so callouts survive a mission
    restart in DCS.
    """

    def __init__(
        self,
        on_event,
        keepalive=None,
        keepalive_interval=15,
        host=EVENT_HOST,
        port=EVENT_PORT
    ):

        self.on_event = on_event
        self.keepalive = keepalive
        self.keepalive_interval = keepalive_interval
        self.addr = (host, port)

        self.sock = None
        self.thread = None
        self.running = False

    def start(self):

        try:

            self.sock = socket.socket(
                socket.AF_INET,
                socket.SOCK_DGRAM
            )

            self.sock.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_REUSEADDR,
                1
            )

            self.sock.bind(self.addr)
            self.sock.settimeout(0.5)

        except OSError as exc:

            print(
                f"DCS EVENTS: could not listen on "
                f"{self.addr[0]}:{self.addr[1]} ({exc}); "
                f"automatic callouts disabled"
            )

            self.sock = None

            return False

        self.running = True

        self.thread = threading.Thread(
            target=self._loop,
            name="dcs-events",
            daemon=True
        )

        self.thread.start()

        print(
            f"DCS EVENTS: Listening on "
            f"{self.addr[0]}:{self.addr[1]}"
        )

        return True

    def stop(self):

        self.running = False

        if self.thread:
            self.thread.join(timeout=1.5)

        if self.sock:

            try:
                self.sock.close()
            except OSError:
                pass

            self.sock = None

    def _loop(self):

        next_keepalive = 0

        while self.running:

            now = time.time()

            if self.keepalive and now >= next_keepalive:

                next_keepalive = now + self.keepalive_interval

                try:
                    self.keepalive()
                except Exception as exc:
                    print(f"DCS EVENTS: keepalive failed: {exc}")

            try:
                data, _ = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                event = json.loads(data.decode("utf-8", "replace"))
            except ValueError:
                continue

            if not isinstance(event, dict):
                continue

            try:
                self.on_event(event)
            except Exception as exc:
                print(f"DCS EVENTS: callout failed: {exc}")