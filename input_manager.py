import pygame
import threading
import time


class InputManager:

    def __init__(self):

        pygame.init()
        pygame.joystick.init()

        self.running = False
        self.thread = None

        self.ptt_device = None
        self.ptt_button = None
        self.ptt_pressed = False

        self.binding = False

        self.on_ptt_down = None
        self.on_ptt_up = None
        self.on_bind = None

        self.lock = threading.Lock()

    # ---------------------------------------------------------
    # DEVICES
    # ---------------------------------------------------------

    def get_devices(self):

        devices = []

        for i in range(pygame.joystick.get_count()):

            joystick = pygame.joystick.Joystick(i)

            if not joystick.get_init():
                joystick.init()

            devices.append({
                "id": i,
                "name": joystick.get_name(),
                "buttons": joystick.get_numbuttons()
            })

        return devices

    def pump_events(self):

        pygame.event.get()

    # ---------------------------------------------------------
    # PTT
    # ---------------------------------------------------------

    def set_ptt(self, device_id, button):

        with self.lock:

            self.ptt_device = device_id
            self.ptt_button = button
            self.ptt_pressed = False

    # ---------------------------------------------------------
    # BINDING
    # ---------------------------------------------------------

    def start_binding(self):

        with self.lock:
            self.binding = True

        print("INPUT: Listening for PTT button...")

    def cancel_binding(self):

        with self.lock:
            self.binding = False

    # ---------------------------------------------------------
    # START
    # ---------------------------------------------------------

    def start(self):

        if self.running:
            return

        self.running = True

        self.thread = threading.Thread(
            target=self._loop,
            daemon=True
        )

        self.thread.start()

    # ---------------------------------------------------------
    # STOP
    # ---------------------------------------------------------

    def stop(self):

        self.running = False

        if self.thread:
            self.thread.join(timeout=1)

        pygame.quit()

    # ---------------------------------------------------------
    # MAIN INPUT LOOP
    # ---------------------------------------------------------

    def _loop(self):

        previous_states = {}

        while self.running:

            with self.lock:
                binding = self.binding
                ptt_device = self.ptt_device
                ptt_button = self.ptt_button

            # Check every connected joystick
            for device_id in range(pygame.joystick.get_count()):

                joystick = pygame.joystick.Joystick(device_id)

                if not joystick.get_init():
                    joystick.init()

                button_count = joystick.get_numbuttons()

                for button in range(button_count):

                    current = bool(
                        joystick.get_button(button)
                    )

                    key = (device_id, button)

                    previous = previous_states.get(
                        key,
                        False
                    )

                    # -------------------------------------------------
                    # BUTTON DOWN
                    # -------------------------------------------------

                    if current and not previous:

                        print(
                            f"INPUT: Button DOWN "
                            f"device={device_id} "
                            f"button={button}"
                        )

                        # Currently binding a PTT button
                        if binding:

                            device_name = joystick.get_name()

                            with self.lock:
                                self.binding = False

                            print(
                                f"INPUT: Binding "
                                f"{device_name} "
                                f"button {button}"
                            )

                            if self.on_bind:

                                self.on_bind(
                                    device_id,
                                    button,
                                    device_name
                                )

                            previous_states[key] = current

                            continue

                        # Normal PTT operation
                        if (
                            device_id == ptt_device
                            and button == ptt_button
                        ):

                            if not self.ptt_pressed:

                                self.ptt_pressed = True

                                print(
                                    "INPUT: PTT DOWN"
                                )

                                if self.on_ptt_down:
                                    self.on_ptt_down()

                    # -------------------------------------------------
                    # BUTTON UP
                    # -------------------------------------------------

                    if not current and previous:

                        print(
                            f"INPUT: Button UP "
                            f"device={device_id} "
                            f"button={button}"
                        )

                        if (
                            device_id == ptt_device
                            and button == ptt_button
                        ):

                            if self.ptt_pressed:

                                self.ptt_pressed = False

                                print(
                                    "INPUT: PTT UP"
                                )

                                if self.on_ptt_up:
                                    self.on_ptt_up()

                    previous_states[key] = current

            time.sleep(0.01)