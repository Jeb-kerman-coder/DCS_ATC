import threading

import ollama

from .prompts import build_system_prompt


class Wingman:
    def __init__(self, state, model="gemma3:12b", keep_alive="60m"):
        self.state = state
        self.model = model
        self.keep_alive = keep_alive

        self.history = []
        self._lock = threading.Lock()

        print(f"WINGMAN: {self.model} ready")

    def reset_history(self):
        with self._lock:
            self.history = []

    def respond(
        self,
        player_message,
        wingman_callsign="Colt 1-2",
        lead_callsign="Colt 1-1"
    ):
        with self._lock:
            return self._respond(
                player_message,
                wingman_callsign,
                lead_callsign
            )

    def _respond(self, player_message, wingman_callsign, lead_callsign):
        context = self.state.get_context()

        prompt = f"""
CURRENT LIVE DCS STATE:

{context}

IMPORTANT:
The CURRENT LIVE DCS STATE above is authoritative.
Use its current aircraft values when answering questions.
Do not use an older value from conversation history when
the live state contains the requested value.

CONVERSATION HISTORY:

{self.history}

PLAYER:
{player_message}

Respond as {wingman_callsign}.
"""

        response = ollama.generate(
            model=self.model,
            prompt=build_system_prompt(wingman_callsign, lead_callsign) + prompt,
            options={
                "temperature": 0.8,
                "num_predict": 100
            },
            think=False,
            keep_alive=self.keep_alive
        )

        text = response.get(
            "response",
            ""
        ).strip()

        text = text.strip('"')

        if not text:
            return None

        self.history.append(
            f"{lead_callsign}: {player_message}"
        )

        self.history.append(
            f"{wingman_callsign}: {text}"
        )

        # Prevent the conversation history growing forever.
        if len(self.history) > 20:
            self.history = self.history[-20:]

        return text