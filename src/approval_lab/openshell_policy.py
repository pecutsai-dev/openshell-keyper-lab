"""Exact, version-bound UpdateConfig approvals, separate from legacy mock rules."""

from dataclasses import dataclass
import hashlib
import json
import re
import time
from uuid import uuid4

from .approval_store import public_record
from .keyper_adapter import DecisionContext
from .models import ApprovalError, NetworkChange
from .openshell_wire import as_json, message


REFERENCE = "approval-lab.example/request-id"


@dataclass(frozen=True)
class PolicyChange:
    canonical_json: str

    @property
    def fingerprint(self):
        return hashlib.sha256(self.canonical_json.encode()).hexdigest()


def canonical_change(operation, principal, gateway_id):
    # Parse and reserialize the official schema to bind semantic protobuf values.
    raw = message("openshell.v1.UpdateConfigRequest", operation)
    op = as_json(raw)
    annotations = op.get("annotations", {})
    reference = annotations.pop(REFERENCE, None)
    if not annotations:
        op.pop("annotations", None)
    allowed = {"sandbox", "workspaceScope", "expectedResourceVersion", "mergeOperations", "annotations", "requestId"}
    if set(op) - allowed:
        raise ValueError("Only sandbox-scoped incremental network additions are supported")
    if not op.get("sandbox") or not op.get("workspaceScope", {}).get("workspace"):
        raise ValueError("Explicit sandbox and named workspace are required")
    if int(op.get("expectedResourceVersion", "0")) <= 0:
        raise ValueError("Nonzero expectedResourceVersion is required")
    operations = op.get("mergeOperations", [])
    if len(operations) != 1 or set(operations[0]) != {"addRule"}:
        raise ValueError("Exactly one addRule operation is supported")
    add = operations[0]["addRule"]
    rule = add.get("rule", {})
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", add.get("ruleName", "")):
        raise ValueError("Explicit ruleName is required")
    if set(rule) - {"name", "endpoints", "binaries"}:
        raise ValueError("Unsupported rule fields")
    endpoints, binaries = rule.get("endpoints", []), rule.get("binaries", [])
    if len(endpoints) != 1 or len(binaries) != 1:
        raise ValueError("Exactly one endpoint and one binary are required")
    endpoint = endpoints[0]
    if set(endpoint) != {"host", "port", "protocol"} or endpoint["protocol"] != "tcp":
        raise ValueError("Use only an explicit host, port and tcp protocol")
    change = NetworkChange(op["sandbox"], endpoint["host"], endpoint["port"])
    if change.domain != endpoint["host"]:
        raise ValueError("Use a normalized lowercase DNS hostname")
    if set(binaries[0]) != {"path"} or not binaries[0]["path"].startswith("/") or ".." in binaries[0]["path"].split("/"):
        raise ValueError("An explicit absolute Linux binary path is required")
    if not principal or not all(isinstance(k, str) and isinstance(v, str) for k, v in principal.items()):
        raise ValueError("Operator-configured expected gateway principal is required")
    if not isinstance(gateway_id, str) or not gateway_id:
        raise ValueError("An operator-configured gateway identity is required")
    payload = {"kind": "openshell.UpdateConfig.v1", "gateway_id": gateway_id,
               "principal": principal, "operation": op}
    return PolicyChange(json.dumps(payload, sort_keys=True, separators=(",", ":"))), reference


class PolicyApprovals:
    def __init__(self, store, verifier, *, gateway_id, principal, clock=time.time):
        self.store, self.verifier = store, verifier
        self.gateway_id, self.principal, self.clock = gateway_id, principal, clock

    def request(self, operation, reason):
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
            raise ValueError("Reason must contain 1-2000 characters")
        operation = {**operation, "requestId": str(uuid4())}
        change, reference = canonical_change(operation, self.principal, self.gateway_id)
        if reference:
            raise ValueError("Do not supply an approval reference when requesting review")
        request_id, now = str(uuid4()), self.clock()
        self.store.create(request_id, change, reason.strip(), now, now + 300)
        return self.status(request_id)

    def status(self, request_id):
        row = self.store.get(request_id)
        if not row:
            raise ApprovalError("not_found")
        if json.loads(row["change_json"]).get("kind") != "openshell.UpdateConfig.v1":
            raise ApprovalError("wrong_request_kind")
        return public_record(row, self.clock())

    def context(self, request_id, approve):
        if type(approve) is not bool:
            raise ValueError("approve must be a boolean")
        record = self.status(request_id)
        return DecisionContext(request_id, record["fingerprint"], approve, record["expires_at"])

    def decide(self, request_id, assertion, approve):
        context = self.context(request_id, approve)
        try:
            identity = self.verifier.verify_decision(assertion, context)
            if not identity.subject or "network_approver" not in identity.roles:
                raise ApprovalError("approver_not_authorized")
        except ApprovalError as exc:
            self.store.reject_identity(request_id, self.clock(), exc.code)
            raise
        except Exception:
            # Verifier/library errors may contain the raw assertion. Never expose
            # their text through MCP error logging or the audit trail.
            self.store.reject_identity(request_id, self.clock(), "identity_verifier_unavailable")
            raise ApprovalError("identity_verifier_unavailable") from None
        result = self.store.decide(request_id, identity.subject, approve, self.clock)
        if result not in {"approved", "denied"}:
            raise ApprovalError(result)
        return self.status(request_id)

    def consume_operation(self, operation, principal):
        change, reference = canonical_change(operation, principal, self.gateway_id)
        if not reference:
            raise ApprovalError("approval_reference_missing")
        result = self.store.consume(reference, change, self.clock, actor="openshell-interceptor")
        if result != "consumed":
            raise ApprovalError(result)
        return reference

    def approved_operation(self, request_id):
        record = self.status(request_id)
        if record["status"] != "approved" or record["consumed"]:
            raise ApprovalError("approval_not_usable")
        operation = record["change"]["operation"]
        operation.setdefault("annotations", {})[REFERENCE] = request_id
        return operation
