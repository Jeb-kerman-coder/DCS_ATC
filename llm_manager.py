import ollama


class LLMManager:

    def __init__(self, model="gemma3:12b", keep_alive="60m"):

        self.model = model
        self.keep_alive = keep_alive

        print(f"LLM: {self.model} ready (controller replies)")

    def generate_controller_response(
        self,
        controller,
        frequency,
        aircraft,
        callsign,
        pilot_transmission,
        controller_action,
        response_data=None
    ):

        if response_data is None:
            response_data = {}

        prompt = f"""
You are the {controller} controller for a military aviation radio simulation.

Aircraft: {aircraft}
Callsign: {callsign}
Frequency: {frequency:.3f} MHz

Pilot transmission:
{pilot_transmission}

The deterministic procedure engine has already decided what the controller must do.

Controller action:
{controller_action}

Response data:
{response_data}

Your job is ONLY to convert the controller action into one concise,
realistic military aviation radio transmission.

IMPORTANT RULES:

- Do NOT change the controller action.
- Do NOT make procedural decisions.
- Do NOT invent information.
- Do NOT invent runway numbers.
- Do NOT invent frequencies.
- Do NOT invent headings.
- Do NOT invent altitudes.
- Do NOT invent clearances.
- Do NOT add instructions that are not contained in the procedure data.
- Use the callsign when appropriate.
- Use concise military aviation radio phraseology.
- Output ONLY the words that should be transmitted over the radio.
- No explanation.
- No reasoning.
- No analysis.
- No headings.
- No bullet points.
- No quotation marks.
- No markdown.

Controller transmission:
"""

        print("LLM: Sending request to Gemma...")

        response = ollama.generate(
            model=self.model,
            prompt=prompt,
            options={
                "temperature": 0.2,
                "num_predict": 60,
            },
            think=False,
            keep_alive=self.keep_alive
        )

        print("\n===== RAW OLLAMA RESPONSE =====")
        print(response)
        print("===== END RAW RESPONSE =====\n")

        content = response.get(
            "response",
            ""
        ).strip()

        print(
            f"LLM RESPONSE FIELD: {content}"
        )

        return content