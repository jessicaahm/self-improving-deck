from dataclasses import dataclass

@dataclass
class DeckInput:
    content: str = ""
    workflow_id: str = "default"
    delete_all: bool = False   # delete_deck only: also remove the backup snapshot

@dataclass
class DeckOutput:
    status: int
    message: str

@dataclass
class SnapshotResult:
    created: bool
    path: str = ""

@dataclass
class RestoreResult:
    restored: bool
    path: str = ""