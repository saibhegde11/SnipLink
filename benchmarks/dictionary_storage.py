"""An in-memory baseline with the current storage module's interface.

This reconstructs a dictionary version for comparison. It is not a copy of
an earlier project revision. The lock makes the conditional click update
and uniqueness check safe under FastAPI's worker threads.
"""

from threading import RLock


class DictionaryStorage:
    def __init__(self):
        self.links = {}
        self.lock = RLock()

    def initialize_database(self):
        pass

    def save_link(self, short_code, original_url, expires_at=None):
        with self.lock:
            if short_code in self.links:
                raise ValueError("Short Code already exists")
            self.links[short_code] = {
                "short_code": short_code,
                "original_url": original_url,
                "expires_at": expires_at,
                "click_count": 0,
            }
        return short_code

    def find_link_details(self, short_code):
        with self.lock:
            row = self.links.get(short_code)
            if row is None:
                return None
            return {key: row[key] for key in
                    ("short_code", "original_url", "expires_at")}

    def find_link(self, short_code):
        row = self.find_link_details(short_code)
        return None if row is None else row["original_url"]

    def delete_link(self, short_code):
        with self.lock:
            return self.links.pop(short_code, None) is not None

    def count_links(self):
        with self.lock:
            return len(self.links)

    def record_click(self, short_code, expected_url, expected_expires_at):
        with self.lock:
            row = self.links.get(short_code)
            if (row is None or row["original_url"] != expected_url
                    or row["expires_at"] != expected_expires_at):
                return False
            row["click_count"] += 1
            return True

    def get_click_count(self, short_code):
        with self.lock:
            row = self.links.get(short_code)
            return None if row is None else row["click_count"]

    def state(self):
        with self.lock:
            return {"rows": len(self.links),
                    "clicks": sum(row["click_count"] for row in self.links.values())}
