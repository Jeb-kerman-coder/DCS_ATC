import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np
import ollama

from atc_pipeline import ATCPipeline
from audio_manager import AudioManager
from awacs_receiver import AWACSReceiver
from contact_manager import ContactManager
from core.braa_calculator import BRAACalculator
from dcs.bios import DCSBIOS
import dcs_bios_setup
import dcs_hook
import mission_scripting
from frequency_manager import FrequencyManager
from input_manager import InputManager
from llm_manager import LLMManager
from loadout_parser import LoadoutParser
from procedure_manager import ProcedureManager
from request_parser import RequestParser
from settings_manager import SettingsManager
from speech import NORMAL, URGENT, Speaker
from stt_manager import STTManager
from tts_manager import TTSManager
from wingman.callsigns import format_callsign, friendly_type
from wingman.controller import WingmanController
from wingman.hot_mic import METER_GAIN, HotMic, is_meaningful


# =============================================================
# DCS-BIOS WORKER  (radio frequencies, own heading)
# =============================================================

class DCSWorker(threading.Thread):

    RETRY_SECONDS = 3

    def __init__(self, events, frequencies):

        super().__init__(daemon=True)

        self.events = events
        self.running = True

        self.bios = DCSBIOS()
        self.frequencies = frequencies

        self.last_com1 = None
        self.last_com2 = None

        self._last_error = None

    def get_state(self):

        return self.bios.get_state()

    def run(self):

        # DCS is often started after this app, so keep trying
        # instead of giving up on the first refused connection.
        while self.running:

            try:

                self.bios = DCSBIOS()
                self.bios.connect()

                self._last_error = None

                self.events.put(("status", "DCS-BIOS ONLINE"))

                while self.running:

                    self.bios.update()
                    self._publish_radios(self.bios.get_state())

            except Exception as e:

                # report a given failure once, not every retry
                if self.running and str(e) != self._last_error:
                    self._last_error = str(e)
                    self.events.put(("error", str(e)))

            finally:

                try:
                    self.bios.close()
                except Exception:
                    pass

            for _ in range(self.RETRY_SECONDS * 10):

                if not self.running:
                    return

                time.sleep(0.1)

    def _publish_radios(self, state):

        for key, attr in (("com1", "last_com1"), ("com2", "last_com2")):

            frequency = state.get(f"{key}_frequency")

            if frequency != getattr(self, attr):

                setattr(self, attr, frequency)

                if frequency is not None:

                    self.events.put((
                        key,
                        frequency,
                        self.frequencies.lookup(frequency)
                    ))

    def stop(self):

        self.running = False


# =============================================================
# MAIN WINDOW
# =============================================================

# log sources -> colour group
ATC_SOURCES = {
    "TOWER", "AWACS", "GCI", "ATC", "RADIO", "PTT", "INPUT", "AUDIO",
    "PILOT"
}
WINGMAN_SOURCES = {"WINGMAN", "YOU", "MIC"}


class ATCInterface:

    # Olive-drab / gunmetal "tactical" palette. Text colours all keep
    # roughly 6:1 contrast or better against the panels they sit on.
    BG = "#0c0f0a"          # window
    PANEL = "#151a11"       # panels
    PANEL2 = "#1e251a"      # column headers, raised strips
    INSET = "#090c07"       # entry boxes, log, meter, roster
    BORDER = "#3d4a31"      # 1px panel outlines
    BUTTON = "#2b3523"
    BUTTON_HOVER = "#3c4a30"
    SELECT = "#42562d"
    TEXT = "#dedfc9"        # khaki white
    DIM = "#929d7e"         # labels
    GREEN = "#8fd653"       # active / ok (phosphor)
    SAND = "#dcc57c"        # ATC identity colour (was cyan)
    AMBER = "#f2a62a"       # caution
    RED = "#ea5a45"         # warning

    def __init__(self, root):

        self.root = root

        self.bg = self.BG
        self.panel = self.PANEL
        self.panel2 = self.PANEL2
        self.text = self.TEXT
        self.dim = self.DIM
        self.green = self.GREEN
        self.sand = self.SAND
        self.amber = self.AMBER
        self.red = self.RED

        self.root.title("DCS ATC + Wingman")
        self.root.geometry("1360x900")
        self.root.minsize(1100, 760)

        self.events = queue.Queue()      # DCS-BIOS worker -> GUI
        self.ui_queue = queue.Queue()    # any thread -> GUI

        self.worker = None
        self._closing = False
        self._next_roster_refresh = 0

        # =====================================================
        # CORE SYSTEMS
        # =====================================================

        self.settings = SettingsManager()
        self.frequencies = FrequencyManager(self.settings)
        self.input_manager = InputManager()
        keep_alive = self.settings.get("llm", "keep_alive")

        self.request_parser = RequestParser(
            model=self.settings.get("llm", "atc_model"),
            keep_alive=keep_alive
        )
        self.procedure_manager = ProcedureManager()
        self.audio_manager = AudioManager()
        self.llm_manager = LLMManager(
            model=self.settings.get("llm", "atc_model"),
            keep_alive=keep_alive
        )
        self.tts_manager = TTSManager(self.settings)
        self.stt_manager = STTManager()

        self.audio_manager.device = self.settings.get(
            "audio", "input_device"
        )

        # one speaker for ATC and wingman so they never talk over each other
        self.speaker = Speaker(
            self.tts_manager,
            on_timing=lambda voice, seconds: self.add_log(
                "TIMING", f"{voice} voice generated in {seconds:.1f}s"
            )
        )

        # =====================================================
        # AWACS
        # =====================================================

        self.contact_manager = ContactManager()
        self.loadout_parser = LoadoutParser()
        self.braa_calculator = BRAACalculator()
        self.awacs_receiver = AWACSReceiver(self.contact_manager)

        # =====================================================
        # WINGMAN
        # =====================================================

        self.wingman = WingmanController(
            log=self.add_log,
            speak=self.wingman_speak,
            model=self.settings.get("llm", "wingman_model"),
            keep_alive=keep_alive
        )

        self.hot_mic = HotMic(
            on_utterance=self.on_hot_utterance,
            is_blocked=self.speaker.is_busy,
            device=self.settings.get("audio", "input_device"),
            threshold=self.settings.get("wingman", "mic_threshold")
        )

        self.hot_mic.enabled = bool(
            self.settings.get("wingman", "mic_enabled")
        )

        # =====================================================
        # ATC PIPELINE
        # =====================================================

        self.atc = ATCPipeline(
            request_parser=self.request_parser,
            loadout_parser=self.loadout_parser,
            procedure_manager=self.procedure_manager,
            llm_manager=self.llm_manager,
            contact_manager=self.contact_manager,
            braa_calculator=self.braa_calculator,
            get_heading=self.current_heading,
            get_fallback_ownship=self.telemetry_ownship,
            get_lead=self.lead_identity,
            log=self.add_log
        )

        # =====================================================
        # INPUT CALLBACKS
        # =====================================================

        self.input_manager.on_ptt_down = self.ptt_down
        self.input_manager.on_ptt_up = self.ptt_up
        self.input_manager.on_bind = self.ptt_bound

        # =====================================================
        # UI
        # =====================================================

        self.setup_style()
        self.build_interface()
        self.load_ptt_binding()

        # =====================================================
        # START SYSTEMS
        # =====================================================

        self.input_manager.start()
        self.pump_input_events()

        self.setup_dcs_loader()

        self.start_dcs()
        self.awacs_receiver.start()
        self.wingman.start()

        if self.hot_mic.start():
            self.add_log("MIC", "Hot mic open for the wingman.")
        else:
            self.add_log("MIC", "Could not open the microphone.")

        self.warm_up()

        self.root.after(100, self.process_events)

        self.root.protocol("WM_DELETE_WINDOW", self.close)

    # =========================================================
    # WARM-UP
    # =========================================================

    def warm_up(self):
        """
        Load the voices, Whisper and the Ollama models in the background.
        Without this the FIRST transmission pays for loading ~8 GB of
        model into the GPU, the voice into memory and Whisper's first run,
        and feels like the whole system is broken.
        """

        threading.Thread(target=self._warm_up, daemon=True).start()

    def _warm_up(self):

        started = time.time()

        self.add_log("SYSTEM", "Warming up voices and models...")

        try:
            self.tts_manager.warm_up()
        except Exception as exc:
            print(f"WARM-UP: voice: {exc}")

        try:
            self.stt_manager.transcribe(
                np.zeros(16000, dtype=np.float32), quiet=True, fast=True
            )
        except Exception as exc:
            print(f"WARM-UP: whisper: {exc}")

        keep_alive = self.settings.get("llm", "keep_alive")

        models = {
            self.request_parser.model,
            self.llm_manager.model,
            self.wingman.llm.model,
        }

        for model in models:

            try:

                ollama.generate(
                    model=model,
                    prompt="Reply with OK.",
                    options={"num_predict": 1},
                    think=False,
                    keep_alive=keep_alive
                )

            except Exception as exc:

                print(f"WARM-UP: {model}: {exc}")

                self.add_log("ERROR", f"Could not load {model}: {exc}")

        self.add_log(
            "SYSTEM",
            f"Ready - warm-up took {time.time() - started:.0f}s. "
            f"(The first transmission is slow only until this finishes.)"
        )

    # =========================================================
    # SHARED DATA FOR THE ATC PIPELINE
    # =========================================================

    def current_heading(self):
        """DCS-BIOS heading, or the telemetry bridge's if BIOS has none."""

        if self.worker:

            heading = self.worker.get_state().get("heading_deg")

            if heading is not None:
                return heading

        lead = self.wingman.lead()

        if lead and lead.get("heading_deg") is not None:
            return lead["heading_deg"]

        return None

    def telemetry_ownship(self):

        lead = self.wingman.lead()

        if not lead:
            return None

        position = lead.get("position") or {}

        if position.get("x") is None or position.get("z") is None:
            return None

        return {
            "x": position["x"],
            "y": position.get("y"),
            "z": position["z"]
        }

    def lead_identity(self):
        """(callsign, aircraft) of the human pilot, from DCS itself."""

        lead = self.wingman.lead()

        if not lead:
            return None, None

        return (
            format_callsign(lead.get("callsign") or lead.get("name")),
            friendly_type(lead.get("type"), None)
        )

    # =========================================================
    # THREAD-SAFE GUI ACCESS
    # =========================================================

    def post(self, function, *args):
        """Run function(*args) on the GUI thread."""

        self.ui_queue.put((function, args))

    # =========================================================
    # STYLE
    # =========================================================

    def setup_style(self):

        self.root.configure(bg=self.bg)

        style = ttk.Style()
        style.theme_use("clam")

        style.configure("TFrame", background=self.bg)

        style.configure(
            "Roster.Treeview",
            background=self.INSET,
            fieldbackground=self.INSET,
            foreground=self.text,
            rowheight=26,
            borderwidth=0,
            font=("Consolas", 10)
        )

        style.configure(
            "Roster.Treeview.Heading",
            background=self.panel2,
            foreground=self.dim,
            relief="flat",
            font=("Consolas", 8, "bold")
        )

        style.map(
            "Roster.Treeview",
            background=[("selected", self.SELECT)],
            foreground=[("selected", "#ffffff")]
        )

        style.configure(
            "Roster.Treeview",
            bordercolor=self.BORDER,
            lightcolor=self.BORDER,
            darkcolor=self.BORDER
        )

        style.configure(
            "Dark.Horizontal.TScale",
            background="#7c8a62",
            troughcolor=self.INSET,
            bordercolor=self.BORDER,
            lightcolor="#7c8a62",
            darkcolor="#7c8a62"
        )

        style.configure(
            "Vertical.TScrollbar",
            background=self.BUTTON,
            troughcolor=self.INSET,
            bordercolor=self.BORDER,
            arrowcolor=self.TEXT,
            lightcolor=self.BUTTON,
            darkcolor=self.BUTTON
        )

    # =========================================================
    # SMALL WIDGET HELPERS
    # =========================================================

    def label(self, parent, text, fg=None, size=9, bold=True, mono=False,
              bg=None, **pack):

        font = (
            "Consolas",
            size,
            "bold" if bold else "normal"
        )

        widget = tk.Label(
            parent,
            text=text,
            bg=bg or parent.cget("bg"),
            fg=fg or self.dim,
            font=font
        )

        if pack is not None:
            widget.pack(**pack)

        return widget

    def button(self, parent, text, command, accent=None, **pack):

        widget = tk.Button(
            parent,
            text=text,
            command=command,
            bg=self.BUTTON,
            fg=accent or self.text,
            activebackground=self.BUTTON_HOVER,
            activeforeground=accent or self.text,
            disabledforeground="#5d6850",
            relief="flat",
            bd=0,
            padx=16,
            pady=7,
            font=("Consolas", 9, "bold"),
            cursor="hand2"
        )

        widget.pack(**pack)

        return widget

    def add_borders(self, widget):
        """Outline every top-level panel with a thin olive border."""

        for child in widget.winfo_children():

            if isinstance(child, tk.Frame):

                if (
                    child.cget("bg") in (self.panel, self.panel2)
                    and widget.cget("bg") not in (self.panel, self.panel2)
                ):
                    child.config(
                        highlightthickness=1,
                        highlightbackground=self.BORDER,
                        highlightcolor=self.BORDER
                    )

                self.add_borders(child)

    def style_inputs(self, widget):
        """Swap the default light focus outlines for olive ones."""

        for child in widget.winfo_children():

            if isinstance(child, (tk.Entry, tk.Text)):
                child.config(
                    highlightthickness=1,
                    highlightbackground=self.BORDER,
                    highlightcolor=self.SAND
                )

            elif isinstance(child, tk.Button):
                child.config(
                    highlightthickness=1,
                    highlightbackground=self.BORDER,
                    highlightcolor=self.SAND
                )

            self.style_inputs(child)

    def section(self, parent, title, badge, badge_color):
        """A column header: title on the left, mic badge on the right."""

        frame = tk.Frame(parent, bg=self.panel2)

        self.label(
            frame, title, fg=self.text, size=13,
            side="left", padx=(16, 8), pady=10
        )

        badge_label = tk.Label(
            frame,
            text=badge,
            bg=self.panel2,
            fg=badge_color,
            font=("Consolas", 10, "bold")
        )

        badge_label.pack(side="right", padx=16)

        frame.badge = badge_label

        return frame

    # =========================================================
    # INTERFACE
    # =========================================================

    def build_interface(self):

        # ---------------- header ----------------

        header = tk.Frame(self.root, bg=self.bg)
        header.pack(fill="x", padx=25, pady=(16, 4))

        self.label(
            header, "DCS ATC", fg=self.text, size=22,
            side="left"
        )

        self.label(
            header, "+ WINGMAN", fg=self.green, size=22,
            side="left", padx=(8, 0)
        )

        chips = tk.Frame(header, bg=self.bg)
        chips.pack(side="right")

        self.status_label = self.label(
            chips, "● DCS-BIOS CONNECTING", fg=self.amber, size=10,
            side="left", padx=(0, 18)
        )

        self.bridge_label = self.label(
            chips, "● BRIDGE WAITING", fg=self.amber, size=10,
            side="left"
        )

        # thin rule under the header
        tk.Frame(self.root, bg=self.BORDER, height=2).pack(
            fill="x", padx=25, pady=(6, 0)
        )

        # ---------------- columns ----------------

        body = tk.Frame(self.root, bg=self.bg)
        body.pack(fill="both", expand=True, padx=25, pady=(8, 0))

        body.columnconfigure(0, weight=1, uniform="col")
        body.columnconfigure(1, weight=1, uniform="col")
        body.rowconfigure(0, weight=1)

        left = tk.Frame(body, bg=self.bg)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        right = tk.Frame(body, bg=self.bg)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        self.build_atc_column(left)
        self.build_wingman_column(right)

        # ---------------- shared log ----------------

        self.build_log()

        self.add_borders(self.root)
        self.style_inputs(self.root)

    # ---------------------------------------------------------
    # ATC COLUMN  (cold mic)
    # ---------------------------------------------------------

    def build_atc_column(self, parent):

        head = self.section(
            parent, "ATC / AWACS", "COLD MIC · HOLD PTT", self.sand
        )
        head.pack(fill="x")

        # aircraft
        aircraft = tk.Frame(parent, bg=self.panel2)
        aircraft.pack(fill="x", pady=(8, 0))

        self.label(
            aircraft, "YOU", size=9,
            side="left", padx=(16, 10), pady=12
        )

        self.aircraft_label = self.label(
            aircraft, "WAITING FOR DCS", fg=self.text, size=13, mono=True,
            side="left"
        )

        # radios
        radios = tk.Frame(parent, bg=self.bg)
        radios.pack(fill="x", pady=8)

        radios.columnconfigure(0, weight=1)
        radios.columnconfigure(1, weight=1)

        self.com1_panel = self.create_radio_panel(radios, "COM 1")
        self.com1_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        self.com2_panel = self.create_radio_panel(radios, "COM 2")
        self.com2_panel.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        # active controller
        controller_panel = tk.Frame(parent, bg=self.panel)
        controller_panel.pack(fill="x")

        self.label(
            controller_panel, "ACTIVE CONTROLLER",
            anchor="w", padx=16, pady=(12, 2)
        )

        self.controller_label = self.label(
            controller_panel, "UNKNOWN", fg=self.amber, size=18, mono=True,
            anchor="w", padx=16
        )

        self.station_label = self.label(
            controller_panel, "NO CONTROLLER", size=10, bold=False,
            mono=True, anchor="w", padx=16, pady=(2, 12)
        )

        # channels
        channel_panel = tk.Frame(parent, bg=self.panel)
        channel_panel.pack(fill="x", pady=(8, 0))

        self.label(
            channel_panel, "CHANNELS  (MHz, saved)",
            anchor="w", padx=16, pady=(12, 3)
        )

        self.channel_entries = {}

        for name, title in (("tower", "ATC / TOWER"), ("awacs", "AWACS")):

            row = tk.Frame(channel_panel, bg=self.panel)
            row.pack(fill="x", padx=16, pady=(0, 6))

            self.label(
                row, title, size=9, mono=True,
                side="left", padx=(0, 10)
            )

            entry = tk.Entry(
                row,
                width=10,
                bg=self.INSET,
                fg=self.text,
                insertbackground=self.text,
                relief="flat",
                justify="center",
                font=("Consolas", 12)
            )

            entry.insert(0, f"{self.frequencies.get_channel(name):.3f}")
            entry.pack(side="right", ipady=4)

            entry.bind(
                "<Return>",
                lambda event, n=name: self.apply_channel(n)
            )

            # leaving the box applies it too, so typing then clicking
            # elsewhere is not silently lost
            entry.bind(
                "<FocusOut>",
                lambda event, n=name: self.apply_channel(n, quiet=True)
            )

            self.channel_entries[name] = entry

        self.channel_status = self.label(
            channel_panel, "Type a frequency and press Enter.",
            size=9, bold=False, anchor="w", padx=16, pady=(0, 10)
        )

        # PTT
        ptt_panel = tk.Frame(parent, bg=self.panel)
        ptt_panel.pack(fill="x", pady=(8, 0))

        self.label(
            ptt_panel, "PUSH-TO-TALK  (ATC / AWACS ONLY)",
            anchor="w", padx=16, pady=(12, 3)
        )

        ptt_row = tk.Frame(ptt_panel, bg=self.panel)
        ptt_row.pack(fill="x", padx=16, pady=(0, 12))

        self.ptt_binding_label = self.label(
            ptt_row, "NOT BOUND", fg=self.amber, size=11, mono=True,
            side="left"
        )

        self.ptt_status_label = self.label(
            ptt_row, "● READY", size=10, mono=True,
            side="left", padx=20
        )

        self.bind_button = self.button(
            ptt_row, "BIND PTT", self.start_ptt_binding, side="right"
        )

    def create_radio_panel(self, parent, name):

        panel = tk.Frame(parent, bg=self.panel)

        self.label(panel, name, anchor="w", padx=16, pady=(12, 2))

        panel.frequency_label = self.label(
            panel, "---.--- MHz", fg=self.sand, size=22, mono=True,
            anchor="w", padx=16
        )

        panel.controller_label = self.label(
            panel, "UNKNOWN", fg=self.text, size=12,
            anchor="w", padx=16, pady=(2, 12)
        )

        return panel

    # ---------------------------------------------------------
    # WINGMAN COLUMN  (hot mic)
    # ---------------------------------------------------------

    def build_wingman_column(self, parent):

        head = self.section(
            parent, "WINGMAN", "HOT MIC · JUST TALK", self.green
        )
        head.pack(fill="x")

        self.wingman_badge = head.badge

        # ---------------- roster ----------------

        roster_panel = tk.Frame(parent, bg=self.panel)
        roster_panel.pack(fill="x", pady=(8, 0))

        top = tk.Frame(roster_panel, bg=self.panel)
        top.pack(fill="x", padx=16, pady=(12, 6))

        self.label(
            top, "AVAILABLE AIRCRAFT", side="left"
        )

        self.roster_count = self.label(
            top, "", fg=self.dim, size=9, mono=True, side="right"
        )

        columns = ("callsign", "type", "flight", "alt")

        tree_frame = tk.Frame(roster_panel, bg=self.panel)
        tree_frame.pack(fill="x", padx=16)

        self.roster = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            height=5,
            selectmode="browse",
            style="Roster.Treeview"
        )

        for column, title, width, anchor in (
            ("callsign", "CALLSIGN", 130, "w"),
            ("type", "TYPE", 120, "w"),
            ("flight", "FLIGHT", 110, "w"),
            ("alt", "ALT", 80, "e"),
        ):
            self.roster.heading(column, text=title, anchor=anchor)
            self.roster.column(column, width=width, anchor=anchor)

        scrollbar = ttk.Scrollbar(
            tree_frame, orient="vertical", command=self.roster.yview
        )

        self.roster.configure(yscrollcommand=scrollbar.set)

        self.roster.pack(side="left", fill="x", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.roster.tag_configure("own", foreground=self.green)
        self.roster.tag_configure(
            "assigned", foreground="#ffffff", background="#587a2b"
        )

        self.roster.bind("<Double-1>", lambda event: self.assign_wingman())
        self.roster.bind("<<TreeviewSelect>>", lambda event: self.update_buttons())

        buttons = tk.Frame(roster_panel, bg=self.panel)
        buttons.pack(fill="x", padx=16, pady=(8, 12))

        self.assign_button = self.button(
            buttons, "ASSIGN AS WINGMAN", self.assign_wingman,
            accent=self.green, side="left"
        )

        self.release_button = self.button(
            buttons, "RELEASE", self.release_wingman,
            side="left", padx=(8, 0)
        )

        # ---------------- assigned wingman ----------------

        current = tk.Frame(parent, bg=self.panel)
        current.pack(fill="x", pady=(8, 0))

        self.label(
            current, "ASSIGNED WINGMAN", anchor="w", padx=16, pady=(12, 2)
        )

        self.wingman_label = self.label(
            current, "NONE", fg=self.amber, size=18, mono=True,
            anchor="w", padx=16
        )

        self.wingman_info = self.label(
            current, "Select an aircraft above.", size=10, bold=False,
            mono=True, anchor="w", padx=16, pady=(2, 12)
        )

        # ---------------- microphone ----------------

        mic = tk.Frame(parent, bg=self.panel)
        mic.pack(fill="x", pady=(8, 0))

        mic_top = tk.Frame(mic, bg=self.panel)
        mic_top.pack(fill="x", padx=16, pady=(12, 6))

        self.label(mic_top, "MICROPHONE", side="left")

        self.mic_state_label = self.label(
            mic_top, "● HOT", fg=self.green, size=10, mono=True,
            side="right"
        )

        self.meter = tk.Canvas(
            mic, height=14, bg=self.INSET, highlightthickness=0
        )

        self.meter.pack(fill="x", padx=16)

        self.meter_bar = self.meter.create_rectangle(
            0, 0, 0, 14, fill=self.green, width=0
        )

        self.meter_mark = self.meter.create_line(
            0, 0, 0, 14, fill=self.amber, width=2
        )

        mic_row = tk.Frame(mic, bg=self.panel)
        mic_row.pack(fill="x", padx=16, pady=(8, 12))

        self.mute_button = self.button(
            mic_row, "MUTE MIC", self.toggle_mic, side="left"
        )

        self.require_var = tk.BooleanVar(
            value=bool(self.settings.get("wingman", "require_callsign"))
        )

        tk.Checkbutton(
            mic_row,
            text="Only when addressed",
            variable=self.require_var,
            command=self.save_require_callsign,
            bg=self.panel,
            fg=self.text,
            selectcolor=self.INSET,
            activebackground=self.panel,
            activeforeground=self.text,
            font=("Consolas", 9),
            bd=0,
            highlightthickness=0
        ).pack(side="left", padx=(14, 0))

        self.threshold_var = tk.DoubleVar(
            value=float(self.settings.get("wingman", "mic_threshold"))
        )

        scale = ttk.Scale(
            mic_row,
            from_=0.002,
            to=0.05,
            variable=self.threshold_var,
            command=self.threshold_changed,
            style="Dark.Horizontal.TScale",
            length=140
        )

        scale.pack(side="right")
        scale.bind("<ButtonRelease-1>", lambda event: self.save_threshold())

        self.label(
            mic_row, "THRESHOLD", fg=self.dim, size=8, side="right", padx=8
        )

        # ---------------- type to wingman ----------------

        typing = tk.Frame(parent, bg=self.panel)
        typing.pack(fill="x", pady=(8, 0))

        self.label(
            typing, "TYPE TO WINGMAN  (also /status /reset /clear)",
            anchor="w", padx=16, pady=(12, 3)
        )

        row = tk.Frame(typing, bg=self.panel)
        row.pack(fill="x", padx=16, pady=(0, 12))

        self.entry = tk.Entry(
            row,
            bg=self.INSET,
            fg=self.text,
            insertbackground=self.text,
            relief="flat",
            font=("Consolas", 11)
        )

        self.entry.pack(side="left", fill="x", expand=True, ipady=6)
        self.entry.bind("<Return>", lambda event: self.send_typed())

        self.button(
            row, "SEND", self.send_typed, side="left", padx=(8, 0)
        )

        self.update_buttons()
        self.update_meter_mark()

    # ---------------------------------------------------------
    # LOG
    # ---------------------------------------------------------

    def build_log(self):

        log_frame = tk.Frame(self.root, bg=self.panel)
        log_frame.pack(fill="both", padx=25, pady=(8, 18))

        self.label(
            log_frame, "RADIO LOG", anchor="w", padx=15, pady=(10, 4)
        )

        self.log = tk.Text(
            log_frame,
            height=11,
            bg=self.INSET,
            fg=self.text,
            insertbackground=self.text,
            font=("Consolas", 10),
            relief="flat",
            borderwidth=0,
            wrap="word"
        )

        self.log.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        for tag, color in (
            ("atc", self.sand),
            ("wingman", self.green),
            ("system", self.dim),
            ("dcs", self.amber),
            ("error", self.red),
        ):
            self.log.tag_configure(tag, foreground=color)

        self.log.configure(state="disabled")

    # =========================================================
    # PTT  (cold mic: ATC / AWACS)
    # =========================================================

    def load_ptt_binding(self):

        ptt = self.settings.get_ptt()

        device = ptt.get("device")
        button = ptt.get("button")

        if device is None or button is None:

            self.ptt_binding_label.config(text="NOT BOUND", fg=self.amber)

            return

        device_id = self.find_device_by_name(device)

        if device_id is None:

            self.ptt_binding_label.config(
                text=f"{device} — NOT CONNECTED",
                fg=self.amber
            )

            return

        self.input_manager.set_ptt(device_id, button)

        self.ptt_binding_label.config(
            text=f"{device} — BUTTON {button}",
            fg=self.green
        )

        self.add_log("INPUT", f"PTT loaded: {device} / Button {button}")

    def find_device_by_name(self, name):

        for device in self.input_manager.get_devices():

            if device["name"] == name:
                return device["id"]

        return None

    def start_ptt_binding(self):

        self.bind_button.config(
            text="PRESS BUTTON...",
            state="disabled",
            fg=self.amber
        )

        self.ptt_binding_label.config(
            text="LISTENING FOR BUTTON",
            fg=self.amber
        )

        self.add_log(
            "INPUT",
            "PTT binding active — press a joystick button."
        )

        self.input_manager.start_binding()

    def pump_input_events(self):

        self.input_manager.pump_events()

        if self.input_manager.running and not self._closing:
            self.root.after(10, self.pump_input_events)

    def ptt_bound(self, device_id, button, device_name):

        self.settings.set_ptt(device_name, button)
        self.input_manager.set_ptt(device_id, button)

        self.post(self.finish_ptt_binding, device_name, button)

    def finish_ptt_binding(self, device_name, button):

        self.ptt_binding_label.config(
            text=f"{device_name} — BUTTON {button}",
            fg=self.green
        )

        self.bind_button.config(
            text="BIND PTT",
            state="normal",
            fg=self.text
        )

        self.add_log("INPUT", f"PTT bound to {device_name}, Button {button}")

    def ptt_down(self):

        # you are talking to ATC: the wingman's hot mic must not hear it
        self.hot_mic.ptt_down()

        threading.Thread(
            target=self.tts_manager.play_ptt_burst,
            daemon=True
        ).start()

        self.audio_manager.start_recording()

        self.post(self.show_ptt_down)

    def ptt_up(self):

        filename = self.audio_manager.stop_recording()

        threading.Thread(
            target=self.tts_manager.play_ptt_burst,
            daemon=True
        ).start()

        # the end-of-transmission click comes out of the speakers, so
        # give the hot mic a moment before it listens again
        threading.Timer(0.4, self.hot_mic.ptt_up).start()

        self.post(self.show_ptt_up, filename)

        if filename:

            threading.Thread(
                target=self.transcribe_audio,
                args=(filename,),
                daemon=True
            ).start()

    def show_ptt_down(self):

        self.ptt_status_label.config(text="● TRANSMITTING", fg=self.green)

        self.add_log("PTT", "TRANSMISSION START")

    def show_ptt_up(self, filename=None):

        self.ptt_status_label.config(text="● READY", fg=self.dim)

        self.add_log("PTT", "TRANSMISSION END")

        if filename:
            self.add_log("AUDIO", f"Recording saved: {filename.name}")

    # =========================================================
    # ATC TRANSMISSION  (PTT -> STT -> controller -> speech)
    # =========================================================

    def transcribe_audio(self, filename):

        try:

            stt_started = time.time()

            text = self.stt_manager.transcribe(filename)

            stt_seconds = time.time() - stt_started

            print(f"STT RESULT: {text}")

            if not text:
                self.add_log("ATC", "No speech recognised - nothing sent.")
                return

            self.add_log("PILOT", text)

            state = self.worker.get_state() if self.worker else {}

            if self.settings.get("radio", "default_com") == 2:
                active_com, radio_name = state.get("com2_frequency"), "COM2"
            else:
                active_com, radio_name = state.get("com1_frequency"), "COM1"

            if active_com is None:
                print("ATC: Active radio frequency unavailable.")
                self.add_log("ATC", f"{radio_name} frequency unavailable.")
                return

            controller_info = self.worker.frequencies.lookup(active_com)

            if not controller_info:
                print("ATC: No controller assigned to current frequency.")
                self.add_log(
                    "ATC",
                    f"Nobody on {radio_name} {active_com:.3f}."
                )
                return

            controller = controller_info.get("controller", "UNKNOWN")

            print(f"ATC: {radio_name} {active_com:.3f} -> {controller}")

            llm_started = time.time()

            response = self.atc.respond(controller, active_com, text)

            self.add_log(
                "TIMING",
                f"STT {stt_seconds:.1f}s · LLM (read + reply) "
                f"{time.time() - llm_started:.1f}s"
            )

            if not response:
                return

            print(f"{controller}: {response}")

            self.add_log(controller, response)

            self.speaker.say(response, voice="atc", priority=NORMAL)

        except Exception as e:

            print(f"ATC ERROR: {e}")
            self.add_log("ERROR", f"ATC: {e}")

    # =========================================================
    # WINGMAN  (hot mic)
    # =========================================================

    def wingman_speak(self, text, urgent=False):

        self.speaker.say(
            text,
            voice="wingman",
            priority=URGENT if urgent else NORMAL
        )

    def on_hot_utterance(self, audio):
        """Called on a worker thread with one complete utterance."""

        if not self.wingman.selected_name:
            return                      # nobody to talk to; don't transcribe

        try:

            stt_started = time.time()

            text = self.stt_manager.transcribe(
                audio, quiet=True, fast=True
            )

            stt_seconds = time.time() - stt_started

            print(f"HOT MIC: heard {text!r}")

            if not is_meaningful(text):
                self.add_log("MIC", f"(ignored) {text or '[nothing]'}")
                return

            if (
                self.settings.get("wingman", "require_callsign")
                and not self.wingman.addressed(text)
            ):
                self.add_log("MIC", f"(not addressed) {text}")
                return

            self.wingman.hear(text, stt_seconds=stt_seconds)

        except Exception as exc:

            print(f"HOT MIC ERROR: {exc}")
            self.add_log("ERROR", f"Hot mic: {exc}")

    def send_typed(self):

        text = self.entry.get().strip()

        if not text:
            return

        self.entry.delete(0, "end")

        threading.Thread(
            target=self.wingman.hear,
            args=(text,),
            daemon=True
        ).start()

    def assign_wingman(self):

        selection = self.roster.selection()

        if not selection:
            return

        name = selection[0]

        threading.Thread(
            target=self.wingman.select,
            args=(name,),
            daemon=True
        ).start()

    def release_wingman(self):

        threading.Thread(
            target=self.wingman.release,
            daemon=True
        ).start()

    def toggle_mic(self):

        enabled = not self.hot_mic.enabled

        self.hot_mic.set_enabled(enabled)

        self.settings.set("wingman", "mic_enabled", enabled)

        self.add_log("MIC", "Hot mic ON." if enabled else "Hot mic MUTED.")

    def save_require_callsign(self):

        self.settings.set(
            "wingman",
            "require_callsign",
            bool(self.require_var.get())
        )

    def threshold_changed(self, value):

        self.hot_mic.threshold = float(value)

        self.update_meter_mark()

    def save_threshold(self):

        self.settings.set(
            "wingman",
            "mic_threshold",
            round(float(self.threshold_var.get()), 4)
        )

    # ---------------------------------------------------------
    # live wingman panel
    # ---------------------------------------------------------

    def update_buttons(self):

        assigned = bool(self.wingman.selected_name)

        selection = self.roster.selection()

        self.assign_button.config(
            state="normal" if selection else "disabled"
        )

        self.release_button.config(
            state="normal" if assigned else "disabled"
        )

    def refresh_roster(self):

        candidates = self.wingman.list_candidates()

        lead = self.wingman.lead()
        lead_group = lead.get("group") if lead else None

        # your own flight first
        candidates.sort(
            key=lambda unit: (
                0 if lead_group and unit.get("group") == lead_group else 1,
                unit.get("group", ""),
                unit.get("callsign", "")
            )
        )

        wanted = [unit["name"] for unit in candidates]

        for existing in self.roster.get_children():

            if existing not in wanted:
                self.roster.delete(existing)

        for index, unit in enumerate(candidates):

            own = bool(lead_group and unit.get("group") == lead_group)

            assigned = unit["name"] == self.wingman.selected_name

            values = (
                ("▶ " if assigned else "")
                + format_callsign(unit.get("callsign"), unit.get("name")),
                friendly_type(unit.get("type"), "?"),
                "YOUR FLIGHT" if own else (unit.get("group") or "")[:14],
                f"{unit.get('altitude_ft', 0) / 1000:.1f}k"
            )

            tags = (
                ("assigned",) if assigned
                else ("own",) if own
                else ()
            )

            if self.roster.exists(unit["name"]):

                self.roster.item(unit["name"], values=values, tags=tags)

            else:

                self.roster.insert(
                    "", "end", iid=unit["name"], values=values, tags=tags
                )

            self.roster.move(unit["name"], "", index)

        self.roster_count.config(text=f"{len(candidates)} AI")

        self.update_buttons()

    def refresh_wingman_status(self):

        name = self.wingman.selected_name

        if not name:

            self.wingman_label.config(text="NONE", fg=self.amber)
            self.wingman_info.config(text="Select an aircraft above.")

            return

        unit = self.wingman.selected_unit()

        callsign = (self.wingman.callsign or name).upper()

        if unit is None:

            self.wingman_label.config(text=callsign, fg=self.red)
            self.wingman_info.config(text="● NO SIGNAL — aircraft lost?")

            return

        state = self.wingman.state

        self.wingman_label.config(text=callsign, fg=self.green)

        self.wingman_info.config(
            text=(
                f"{friendly_type(unit.get('type'), '?')}   "
                f"HDG {unit.get('heading_deg', 0):03.0f}   "
                f"ALT {unit.get('altitude_ft', 0):,.0f}   "
                f"SPD {unit.get('speed_kts', 0):.0f}   "
                f"{state.mode}   "
                f"WPN {state.tactical['weapons_status']}"
            )
        )

    MIC_STATES = {
        "hot": ("● HOT — LISTENING", GREEN),
        "speech": ("● HEARING YOU", SAND),
        "ptt": ("● CLOSED — YOU ARE ON PTT", AMBER),
        "busy": ("● CLOSED — RADIO TRAFFIC", AMBER),
        "off": ("● MUTED", RED),
    }

    def refresh_mic(self):

        state = self.hot_mic.state()

        text, color = self.MIC_STATES[state]

        if state in ("hot", "speech") and not self.wingman.selected_name:
            text, color = "● OPEN — NO WINGMAN ASSIGNED", self.dim

        self.mic_state_label.config(text=text, fg=color)

        self.mute_button.config(
            text="UNMUTE MIC" if not self.hot_mic.enabled else "MUTE MIC"
        )

        width = max(1, self.meter.winfo_width())

        level = self.hot_mic.level if state in ("hot", "speech") else 0.0

        self.meter.coords(self.meter_bar, 0, 0, width * level, 14)

        self.meter.itemconfig(
            self.meter_bar,
            fill=self.sand if state == "speech" else self.green
        )

    def update_meter_mark(self):

        width = max(1, self.meter.winfo_width())

        x = min(1.0, self.hot_mic.threshold * METER_GAIN) * width

        self.meter.coords(self.meter_mark, x, 0, x, 14)

    # =========================================================
    # DCS
    # =========================================================

    def setup_dcs_loader(self):
        """Make sure DCS starts the bridge script by itself in every mission."""

        if not self.settings.get("dcs", "auto_install_hook"):
            return

        for level, message in dcs_hook.install():
            self.add_log("DCS", message)

        self.check_mission_scripting()
        self.setup_dcs_bios()

    def setup_dcs_bios(self):
        """The app reads radio frequencies from DCS-BIOS - set it up."""

        if not self.settings.get("dcs", "auto_install_bios"):
            return

        missing = []

        for folder in dcs_hook.variant_folders():

            try:
                state = dcs_bios_setup.status(folder)

                if state == "no_export_line":
                    dcs_bios_setup.ensure_export_line(folder)
                    self.add_log(
                        "DCS",
                        f"Added DCS-BIOS to Export.lua in {folder.name}. "
                        "Restart DCS if it is running."
                    )

                elif state == "missing":
                    missing.append(folder)

            except OSError as exc:
                self.add_log("DCS", f"DCS-BIOS check failed: {exc}")

        if not missing:
            return

        if not messagebox.askyesno(
            "DCS ATC",
            "DCS-BIOS is not installed. DCS ATC needs it to know which "
            "radio frequency you are on.\n\nDownload the latest version "
            "from the official DCS-BIOS GitHub releases and set it up now "
            "(about 8 MB)?\n\n" + "\n".join(str(f) for f in missing)
        ):
            self.settings.set("dcs", "auto_install_bios", False)
            self.add_log(
                "DCS",
                "DCS-BIOS not installed. Set dcs.auto_install_bios to true "
                "in settings.json to be asked again."
            )
            return

        self.add_log("DCS", "Downloading DCS-BIOS...")

        threading.Thread(
            target=self._install_bios, args=(missing,), daemon=True
        ).start()

    def _install_bios(self, folders):

        for folder in folders:

            ok, message = dcs_bios_setup.download_and_install(folder)

            if ok:
                message += " Restart DCS if it is running."

            self.add_log("DCS", message)

    def check_mission_scripting(self):
        """DCS blocks sockets for mission scripts. Comment those lines out
        (and do it again after a DCS update puts them back)."""

        if not self.settings.get("dcs", "auto_fix_mission_scripting"):
            return

        blocked = []

        for result in mission_scripting.check():

            if result["state"] == "fixed":
                self.add_log(
                    "DCS", result["message"] + " Restart DCS if it is running."
                )

            elif result["state"] == "needs_admin":
                blocked.append(result["install"])

            elif result["state"] == "error":
                self.add_log("DCS", result["message"])

        if not blocked:
            return

        names = "\n".join(str(path) for path in blocked)

        if not messagebox.askyesno(
            "DCS ATC",
            "DCS is blocking mission scripts from using sockets, which the "
            "ATC/wingman link needs. This is usually reset by a DCS "
            "update.\n\nAllow DCS ATC to fix it? Windows will ask for "
            "administrator permission.\n\n" + names
        ):
            self.add_log(
                "DCS", "MissionScripting.lua left blocked - the bridge "
                "will not connect until it is fixed."
            )
            return

        args = ["--patch-missionscripting"] + [str(p) for p in blocked]

        if not mission_scripting.run_elevated(args):
            self.add_log("DCS", "Administrator permission was not given.")
            return

        threading.Thread(
            target=self._wait_for_patch, args=(blocked,), daemon=True
        ).start()

    def _wait_for_patch(self, installs):

        for _ in range(60):

            time.sleep(1)

            try:
                if all(
                    mission_scripting.status(p) != "needs_patch"
                    for p in installs
                ):
                    self.add_log(
                        "DCS",
                        "MissionScripting.lua fixed. Restart DCS if it is "
                        "running."
                    )
                    return
            except OSError:
                pass

        self.add_log("DCS", "MissionScripting.lua is still blocked.")

    def start_dcs(self):

        self.add_log("SYSTEM", "Connecting to DCS-BIOS...")

        self.worker = DCSWorker(self.events, self.frequencies)
        self.worker.start()

    # =========================================================
    # EVENT LOOP
    # =========================================================

    def process_events(self):

        # work posted from other threads
        try:
            while True:
                function, args = self.ui_queue.get_nowait()
                function(*args)
        except queue.Empty:
            pass

        # DCS-BIOS
        try:
            while True:
                self.handle_dcs_event(self.events.get_nowait())
        except queue.Empty:
            pass

        self.update_controller()
        self.refresh_mic()
        self.update_meter_mark()

        now = time.time()

        if now >= self._next_roster_refresh:

            self._next_roster_refresh = now + 1.0

            self.refresh_roster()
            self.refresh_wingman_status()
            self.refresh_header()

        if not self._closing:
            self.root.after(60, self.process_events)

    def handle_dcs_event(self, event):

        kind = event[0]

        if kind == "status":

            self.status_label.config(
                text="● DCS-BIOS ONLINE", fg=self.green
            )

            self.add_log("SYSTEM", "DCS-BIOS connection established.")

        elif kind == "com1":

            self.update_radio(self.com1_panel, event[1], event[2])

        elif kind == "com2":

            self.update_radio(self.com2_panel, event[1], event[2])

        elif kind == "error":

            self.status_label.config(
                text="● DCS-BIOS OFFLINE — RETRYING", fg=self.red
            )

            self.add_log("ERROR", f"DCS-BIOS: {event[1]}")

    def refresh_header(self):

        online = self.wingman.bridge_online()

        self.bridge_label.config(
            text="● BRIDGE ONLINE" if online else "● BRIDGE WAITING",
            fg=self.green if online else self.amber
        )

        lead = self.wingman.lead()

        if lead:

            self.aircraft_label.config(
                text=(
                    f"{format_callsign(lead.get('callsign') or lead.get('name'))}"
                    f" · {friendly_type(lead.get('type'), '?')}"
                ).upper()
            )

        else:

            self.aircraft_label.config(
                text="WAITING FOR DCS" if not online else "NO PLAYER AIRCRAFT"
            )

    def update_radio(self, panel, frequency, controller, log=True):

        panel.frequency_label.config(text=f"{frequency:.3f} MHz")

        if controller:

            panel.controller_label.config(
                text=controller["controller"],
                fg=self.green
            )

            if log:
                self.add_log(
                    "RADIO",
                    f"{frequency:.3f} MHz → {controller['controller']} "
                    f"({controller['station']})"
                )

        else:

            panel.controller_label.config(text="UNKNOWN", fg=self.amber)

            if log:
                self.add_log("RADIO", f"{frequency:.3f} MHz → UNKNOWN")

    # ---------------------------------------------------------
    # channel settings
    # ---------------------------------------------------------

    def apply_channel(self, name, quiet=False):

        entry = self.channel_entries[name]

        text = entry.get().strip()

        current = self.frequencies.get_channel(name)

        # nothing typed differently -> just tidy the formatting
        if FrequencyManager.parse(text) == current:

            entry.delete(0, "end")
            entry.insert(0, f"{current:.3f}")

            return

        ok, message, frequency = self.frequencies.set_channel(name, text)

        if ok:

            entry.delete(0, "end")
            entry.insert(0, f"{frequency:.3f}")

            self.channel_status.config(text=message, fg=self.green)
            self.add_log("RADIO", message)

            self.refresh_radio_panels()

        else:

            # put the last good value back
            entry.delete(0, "end")
            entry.insert(0, f"{current:.3f}")

            self.channel_status.config(text=message, fg=self.red)

    def refresh_radio_panels(self):
        """A channel changed: re-identify what is on COM1 / COM2 now."""

        if not self.worker:
            return

        for panel, frequency in (
            (self.com1_panel, self.worker.last_com1),
            (self.com2_panel, self.worker.last_com2)
        ):

            if frequency is not None:

                self.update_radio(
                    panel,
                    frequency,
                    self.frequencies.lookup(frequency),
                    log=False
                )

    def update_controller(self):

        if self.settings.get("radio", "default_com") == 2:
            panel, station = self.com2_panel, "COM2"
        else:
            panel, station = self.com1_panel, "COM1"

        controller = panel.controller_label.cget("text")

        if controller != "UNKNOWN":

            self.controller_label.config(text=controller, fg=self.green)
            self.station_label.config(text=station)

        else:

            self.controller_label.config(text="UNKNOWN", fg=self.amber)
            self.station_label.config(text="NO CONTROLLER")

    # =========================================================
    # LOG  (safe to call from any thread)
    # =========================================================

    def add_log(self, source, message):

        self.ui_queue.put((self._write_log, (source, message)))

    def _write_log(self, source, message):

        if source in ATC_SOURCES or source in ("TOWER", "AWACS", "GCI"):
            tag = "atc"
        elif source in WINGMAN_SOURCES:
            tag = "wingman"
        elif source == "ERROR":
            tag = "error"
        elif source in ("SYSTEM", "TIMING"):
            tag = "system"
        else:
            tag = "dcs"

        self.log.configure(state="normal")

        self.log.insert(
            "end",
            f"[{time.strftime('%H:%M:%S')}] {source:<8} {message}\n",
            tag
        )

        self.log.see("end")

        self.log.configure(state="disabled")

    # =========================================================
    # CLOSE
    # =========================================================

    def close(self):

        self._closing = True

        for step in (
            lambda: self.worker and self.worker.stop(),
            self.hot_mic.stop,
            self.tts_manager.close,
            self.wingman.stop,
            self.awacs_receiver.stop,
            self.input_manager.stop,
            self.audio_manager.close,
            self.audio_manager.delete_recordings,
        ):
            try:
                step()
            except Exception as exc:
                print(f"CLOSE: {exc}")

        self.root.destroy()


def run():

    root = tk.Tk()

    ATCInterface(root)

    root.mainloop()


if __name__ == "__main__":
    run()
