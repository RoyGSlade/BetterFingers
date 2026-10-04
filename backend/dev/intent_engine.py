import difflib
import logging
from enum import Enum

from log_redaction import redact_user_text

class IntentState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PLANNING = "planning"
    EXECUTING = "executing"

class IntentEngine:
    def __init__(self):
        self.state = IntentState.IDLE
        self.context = {} # Store current plan draft, project ID, etc.
    
    def set_state(self, new_state: IntentState):
        logging.info(f"IntentEngine: Switching state {self.state.value} -> {new_state.value}")
        self.state = new_state
        return self.state.value

    def get_state(self):
        return self.state.value

    def process_input(self, text: str):
        """
        Main logic for routing input based on State.
        """
        logging.info(f"IntentEngine: Processing input in state {self.state.value}: {redact_user_text(text)}")
        
        if self.state == IntentState.PLANNING:
            return self._handle_planning(text)
        elif self.state == IntentState.EXECUTING:
            return self._handle_executing(text)
        else:
            return {"action": "none", "response": "I'm listening."}

    def _handle_planning(self, text):
        # MOCK: In real impl, this calls LLM to update the draft plan
        # For now, return a mock action
        return {
            "action": "update_draft",
            "response": f"I heard '{text}'. Updating the plan...",
            "draft_update": {"note": text}
        }

    def _handle_executing(self, text):
        # MOCK: Check for scope creep
        return {
            "action": "check_scope",
            "response": f"Checking if '{text}' fits the current plan..."
        }

    def match_command(self, text: str, commands: list, threshold: float = 0.8):
        """
        Fuzzy match text against a list of commands.
        Returns the best match if score >= threshold, else None.
        """
        text = text.lower().strip()
        matches = difflib.get_close_matches(text, commands, n=1, cutoff=threshold)
        if matches:
            return matches[0]
        return None

# Global Instance
intent_engine = IntentEngine()
