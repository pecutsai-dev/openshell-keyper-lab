"""Keyper seam: the host verifies an assertion against an exact decision context."""

from dataclasses import dataclass, asdict
import hashlib
import importlib
import json
from typing import Protocol

from .identity_adapter import Identity
from .models import ApprovalError
from .mock_identity import MockIdentity


@dataclass(frozen=True)
class DecisionContext:
    request_id: str
    fingerprint: str
    approve: bool
    expires_at: float

    @property
    def challenge(self):
        payload = {"purpose": "openshell-policy-decision-v1", **asdict(self)}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class KeyperVerifier(Protocol):
    def verify_decision(self, assertion: str, context: DecisionContext) -> Identity:
        """Verify issuer/audience/expiry, context.challenge binding and trusted roles.

        Raise ApprovalError on invalid, replayed or unbound evidence. Never return
        roles copied from an unverified assertion. Assertion must not be logged.
        """
        ...


class UnconfiguredKeyper:
    def verify_decision(self, assertion, context):
        raise ApprovalError("keyper_not_configured")


class LocalMockKeyper:
    """No real assertion verification. Explicit local development opt-in only."""
    def verify_decision(self, assertion, context):
        return MockIdentity().authenticate(assertion)


def load_verifier(factory=None, *, local_mock=False):
    if factory and local_mock:
        raise ValueError("Choose a real verifier or local mock, not both")
    if local_mock:
        return LocalMockKeyper()
    if not factory:
        return UnconfiguredKeyper()
    module, name = factory.split(":", 1)
    # Factory is trusted operator configuration, never an MCP argument.
    verifier = getattr(importlib.import_module(module), name)()
    if not callable(getattr(verifier, "verify_decision", None)):
        raise ValueError("Keyper verifier must implement verify_decision")
    return verifier
