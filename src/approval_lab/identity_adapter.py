from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Identity:
    subject: str
    roles: frozenset[str]


class IdentityAdapter(Protocol):
    def authenticate(self, credential: str) -> Identity:
        """Verify an out-of-band credential; never trust an agent-supplied role."""
        ...
