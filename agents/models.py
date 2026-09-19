from dataclasses import dataclass

@dataclass
class DeckInput:
    content: str
    workflow_id: str = "default"

@dataclass
class DeckOutput:
    status: int
    message: str