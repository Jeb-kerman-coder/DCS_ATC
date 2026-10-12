import json
from pathlib import Path

from app_paths import resource_path


class ProcedureManager:

    def __init__(self, filename=None):
        self.filename = Path(filename) if filename else resource_path(
            "data", "procedures.json"
        )

        with open(self.filename, "r", encoding="utf-8") as f:
            self.procedures = json.load(f)

    def get_procedure(self, controller, request_type):
        controller_data = self.procedures.get(controller, {})

        return controller_data.get(request_type)