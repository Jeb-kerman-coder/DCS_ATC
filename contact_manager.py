import time
import threading


class ContactManager:

    def __init__(self):

        self.contacts = {}

        self.ownship = {
            "x": None,
            "y": None,
            "z": None,
            "last_update": None
        }

        self.lock = threading.Lock()

    def update(self, contact_data):

        now = time.time()

        with self.lock:

            # =====================================================
            # OWN SHIP
            # =====================================================

            ownship = contact_data.get("ownship")

            if ownship:

                self.ownship = {
                    "x": ownship.get("x"),
                    "y": ownship.get("y"),
                    "z": ownship.get("z"),
                    "last_update": now
                }

            # =====================================================
            # CONTACTS
            # =====================================================

            contacts = contact_data.get(
                "contacts",
                []
            )

            current_ids = set()

            for contact in contacts:

                contact_id = contact.get("id")

                if contact_id is None:
                    continue

                current_ids.add(contact_id)

                self.contacts[contact_id] = {

                    "id": contact_id,

                    "type": contact.get("type"),

                    "position": {
                        "x": contact.get("x"),
                        "y": contact.get("y"),
                        "z": contact.get("z")
                    },

                    "distance_known": contact.get(
                        "distance_known",
                        False
                    ),

                    "type_known": contact.get(
                        "type_known",
                        False
                    ),

                    "relationship": contact.get(
                        "relationship",
                        "UNKNOWN"
                    ),

                    "last_update": now
                }

            # =====================================================
            # REMOVE LOST CONTACTS
            # =====================================================

            missing = [
                contact_id
                for contact_id in self.contacts
                if contact_id not in current_ids
            ]

            for contact_id in missing:

                print(
                    f"CONTACT MANAGER: "
                    f"Contact {contact_id} lost"
                )

                del self.contacts[contact_id]

    def get_contacts(self):

        with self.lock:

            return {
                contact_id: contact.copy()
                for contact_id, contact in self.contacts.items()
            }

    def get_contact(self, contact_id):

        with self.lock:

            contact = self.contacts.get(contact_id)

            if contact is None:
                return None

            return contact.copy()

    def get_ownship(self):

        with self.lock:

            return self.ownship.copy()

    def get_nearest_contact(self):

        with self.lock:

            if not self.contacts:
                return None

            own_x = self.ownship.get("x")
            own_z = self.ownship.get("z")

            if own_x is None or own_z is None:
                return None

            nearest = None
            nearest_distance = None

            for contact in self.contacts.values():

                position = contact.get(
                    "position",
                    {}
                )

                x = position.get("x")
                z = position.get("z")

                if x is None or z is None:
                    continue

                distance = (
                    (x - own_x) ** 2 +
                    (z - own_z) ** 2
                )

                if (
                    nearest_distance is None
                    or distance < nearest_distance
                ):

                    nearest = contact.copy()
                    nearest_distance = distance

            return nearest

    def clear(self):

        with self.lock:

            self.contacts.clear()

            self.ownship = {
                "x": None,
                "y": None,
                "z": None,
                "last_update": None
            }