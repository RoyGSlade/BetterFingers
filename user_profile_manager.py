import json
import os
import logging
import re


def _sanitize_filename(name: str) -> str:
    """Strip characters that are unsafe in Windows/Linux filenames."""
    # Keep only alphanumeric, spaces, hyphens, underscores
    sanitized = re.sub(r'[^\w\s\-]', '', str(name or ''))
    sanitized = sanitized.strip()
    return sanitized or "Default"


class UserProfileManager:
    def __init__(self):
        appdata = os.getenv('APPDATA') or os.path.expanduser('~')
        self.profile_path = os.path.join(appdata, "BetterFingers", "user_profile.json")
        self.profile = self._load_profile()

    def _load_profile(self):
        if os.path.exists(self.profile_path):
            try:
                with open(self.profile_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"Error loading profile: {e}")
                return self._default_profile()
        return self._default_profile()

    def _default_profile(self):
        return {
            "vibe": "neutral", # chaos_goblin, architect, neutral
            "work_style": "balanced", # marathon, sprints, balanced
            "hobbies": "",
            "voice_speed": 1.0,
            "voice_pitch": 1.0
        }

    def save_profile(self, data: dict):
        self.profile.update(data)
        try:
            os.makedirs(os.path.dirname(self.profile_path), exist_ok=True)
            with open(self.profile_path, 'w') as f:
                json.dump(self.profile, f, indent=4)
            logging.info("User Profile saved.")
            return True
        except Exception as e:
            logging.error(f"Error saving profile: {e}")
            return False

    def get_profile(self):
        return self.profile

# Global Instance
profile_manager = UserProfileManager()
