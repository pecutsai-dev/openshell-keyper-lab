import time
from uuid import uuid4

from .approval_store import ApprovalStore, public_record
from .identity_adapter import IdentityAdapter
from .models import ApprovalError, NetworkChange


class ApprovalService:
    def __init__(self, store: ApprovalStore, identity: IdentityAdapter, *, ttl_seconds=300, clock=time.time):
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 3600:
            raise ValueError("ttl_seconds must be an operator-configured integer between 1 and 3600")
        self.store, self.identity = store, identity
        self.ttl_seconds, self.clock = ttl_seconds, clock

    def request(self, change: NetworkChange, reason: str):
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
            raise ValueError("reason must contain 1-2000 characters")
        request_id, now = str(uuid4()), self.clock()
        self.store.create(request_id, change, reason.strip(), now, now + self.ttl_seconds)
        return self.status(request_id)

    def status(self, request_id: str):
        row = self.store.get(request_id)
        if row is None:
            raise ApprovalError("not_found")
        return public_record(row, self.clock())

    def decide(self, request_id: str, credential: str, *, approve: bool):
        if type(approve) is not bool:
            raise ValueError("approve must be a boolean")
        try:
            identity = self.identity.authenticate(credential)
            if "network_approver" not in identity.roles:
                raise ApprovalError("approver_not_authorized")
        except ApprovalError as exc:
            self.store.reject_identity(request_id, self.clock(), exc.code)
            raise
        result = self.store.decide(request_id, identity.subject, approve, self.clock)
        if result not in {"approved", "denied"}:
            raise ApprovalError(result)
        return self.status(request_id)

    def consume(self, request_id: str, change: NetworkChange):
        result = self.store.consume(request_id, change, self.clock)
        if result != "consumed":
            raise ApprovalError(result)
