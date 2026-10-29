"""Trusted-path simulator: never rely on the agent's claimed approval status."""

from typing import Protocol
from dataclasses import asdict

from .models import ApprovalError, NetworkChange


class ApprovalChecker(Protocol):
    def consume(self, request_id: str, change: NetworkChange): ...


def apply_mock_policy_update(service: ApprovalChecker, request_id: str, change: NetworkChange):
    try:
        service.consume(request_id, change)
    except ApprovalError as exc:
        return {"applied": False, "simulated": True, "reason": exc.code}
    except Exception:
        # Service, storage and adapter failures never turn into permission.
        return {"applied": False, "simulated": True, "reason": "approval_service_unavailable"}
    return {"applied": True, "simulated": True, "change": asdict(change)}
