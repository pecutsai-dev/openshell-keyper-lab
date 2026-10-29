"""Explicitly insecure local test identities, not authentication for deployment."""

from .identity_adapter import Identity
from .models import ApprovalError


class MockIdentity:
    def authenticate(self, credential: str) -> Identity:
        identities = {
            "demo-approver": Identity("demo-approver", frozenset({"network_approver"})),
            "demo-viewer": Identity("demo-viewer", frozenset()),
        }
        if credential not in identities:
            raise ApprovalError("identity_not_verified")
        return identities[credential]
