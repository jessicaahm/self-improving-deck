from dataclasses import dataclass

@dataclass
class DeckInput:
    content: str

@dataclass
class DeckOutput:
    status: int
    message: str