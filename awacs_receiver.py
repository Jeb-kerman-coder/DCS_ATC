import socket
import json
import threading

from contact_manager import ContactManager


HOST = "127.0.0.1"
PORT = 5015


class AWACSReceiver:

    def __init__(self, contact_manager):

        self.contact_manager = contact_manager

        self.running = False
        self.thread = None

        self.sock = None

    def start(self):

        if self.running:
            return

        self.running = True

        self.thread = threading.Thread(
            target=self._receive_loop,
            daemon=True
        )

        self.thread.start()

        print(
            f"AWACS RECEIVER: "
            f"Listening on {HOST}:{PORT}"
        )

    def _receive_loop(self):

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

            self.sock.bind(
                (HOST, PORT)
            )

            self.sock.settimeout(1.0)

            while self.running:

                try:

                    data, address = (
                        self.sock.recvfrom(65535)
                    )

                except socket.timeout:

                    continue

                try:

                    message = data.decode(
                        "utf-8"
                    )

                    contact_data = json.loads(
                        message
                    )

                    self.contact_manager.update(
                        contact_data
                    )

                except Exception as e:

                    print(
                        f"AWACS RECEIVER: "
                        f"Invalid packet: {e}"
                    )

        except Exception as e:

            print(
                f"AWACS RECEIVER ERROR: {e}"
            )

        finally:

            if self.sock:

                self.sock.close()

                self.sock = None

    def stop(self):

        self.running = False

        if self.thread:

            self.thread.join(
                timeout=2
            )

            self.thread = None

        print(
            "AWACS RECEIVER: Stopped"
        )