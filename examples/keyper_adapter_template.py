"""Implement this in Keyper's trusted operator integration package.

Configure --keyper-verifier your_package.adapter:create_verifier.
Never attach the private operator MCP to the requesting agent.
"""

from approval_lab.models import ApprovalError


class KeyperVerifier:
    def verify_decision(self, assertion, context):
        # Keyper must verify authenticity using its official SDK/protocol.
        # Validate trust root, issuer, audience, expiry, replay protection and
        # an authenticated binding to context.challenge. It includes request ID,
        # complete operation fingerprint, approval/denial and request expiry.
        # Resolve network_approver from trusted operator authorization policy.
        # Return approval_lab.identity_adapter.Identity(subject, frozenset(roles)).
        # Never merely decode a JWT or accept a caller-supplied role/approved flag.
        raise ApprovalError("keyper_not_implemented")


def create_verifier():
    return KeyperVerifier()
