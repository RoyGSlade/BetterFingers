import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


BINDING_STYLES = {"single", "chord", "sequence"}


def normalize_event_token(token: str) -> str:
    if not isinstance(token, str):
        return ""
    token = token.strip().lower()
    token = re.sub(r"\s+", "", token)
    return token


def events_to_expression(style: str, events: List[str]) -> str:
    clean = [normalize_event_token(event) for event in events if normalize_event_token(event)]
    if not clean:
        return ""
    if style == "sequence":
        return " > ".join(clean)
    if style == "chord":
        return " + ".join(clean)
    return clean[0]


def parse_binding_expression(style: str, expression: str) -> List[str]:
    if not expression:
        return []
    style = (style or "single").strip().lower()
    if style == "sequence":
        parts = [p.strip() for p in expression.split(">")]
    elif style == "chord":
        parts = [p.strip() for p in expression.split("+")]
    else:
        parts = [expression.strip()]
    return [normalize_event_token(part) for part in parts if normalize_event_token(part)]


@dataclass
class InputBinding:
    style: str = "single"
    events: List[str] = field(default_factory=lambda: ["button:4"])
    sequence_window_ms: int = 400
    axis_threshold: float = 0.6
    device_scope: str = "any_device"

    def validate(self) -> "InputBinding":
        self.style = (self.style or "single").strip().lower()
        if self.style not in BINDING_STYLES:
            self.style = "single"

        normalized = []
        for event in self.events or []:
            token = normalize_event_token(event)
            if token:
                normalized.append(token)
        self.events = normalized

        if not self.events:
            self.events = ["button:4"]

        try:
            self.sequence_window_ms = int(self.sequence_window_ms)
        except (TypeError, ValueError):
            self.sequence_window_ms = 400
        if self.sequence_window_ms < 100:
            self.sequence_window_ms = 100
        if self.sequence_window_ms > 2000:
            self.sequence_window_ms = 2000

        try:
            self.axis_threshold = float(self.axis_threshold)
        except (TypeError, ValueError):
            self.axis_threshold = 0.6
        if self.axis_threshold < 0.1:
            self.axis_threshold = 0.1
        if self.axis_threshold > 1.0:
            self.axis_threshold = 1.0

        scope = (self.device_scope or "any_device").strip().lower()
        self.device_scope = scope if scope else "any_device"
        return self

    def to_dict(self) -> Dict[str, object]:
        self.validate()
        return {
            "style": self.style,
            "events": list(self.events),
            "sequence_window_ms": self.sequence_window_ms,
            "axis_threshold": self.axis_threshold,
            "device_scope": self.device_scope,
        }

    def to_expression(self) -> str:
        self.validate()
        return events_to_expression(self.style, self.events)

    @classmethod
    def from_dict(
        cls,
        data: Optional[Dict[str, object]],
        default_button: int = 4,
    ) -> "InputBinding":
        if not isinstance(data, dict):
            return cls(events=[f"button:{default_button}"]).validate()

        style = data.get("style", "single")
        events = data.get("events", [])
        if isinstance(events, str):
            events = parse_binding_expression(style, events)
        if not isinstance(events, list):
            events = []

        sequence_window_ms = data.get("sequence_window_ms", 400)
        axis_threshold = data.get("axis_threshold", 0.6)
        device_scope = data.get("device_scope", "any_device")

        return cls(
            style=style,
            events=events,
            sequence_window_ms=sequence_window_ms,
            axis_threshold=axis_threshold,
            device_scope=device_scope,
        ).validate()

    @classmethod
    def from_legacy(
        cls,
        controller_button: object = 4,
        sequence_window_ms: object = 400,
        axis_threshold: object = 0.6,
    ) -> "InputBinding":
        try:
            button = int(controller_button)
        except (TypeError, ValueError):
            button = 4
        return cls(
            style="single",
            events=[f"button:{button}"],
            sequence_window_ms=sequence_window_ms,
            axis_threshold=axis_threshold,
            device_scope="any_device",
        ).validate()

