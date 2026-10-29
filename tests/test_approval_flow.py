from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import sqlite3
import threading

import pytest

from approval_lab.approval_service import ApprovalService
from approval_lab.approval_store import ApprovalStore
from approval_lab.cli import main
from approval_lab.mock_identity import MockIdentity
from approval_lab.mock_policy_update import apply_mock_policy_update
from approval_lab.models import ApprovalError, NetworkChange


@pytest.fixture
def lab(tmp_path):
    now = [1000.0]
    service = ApprovalService(ApprovalStore(tmp_path / "approvals.sqlite3"), MockIdentity(), clock=lambda: now[0])
    return service, now


@pytest.fixture
def change():
    return NetworkChange("sandbox-a", "api.example.com", 443)


def approved(service, change):
    record = service.request(change, "Test access for the sandbox")
    service.decide(record["request_id"], "demo-approver", approve=True)
    return record["request_id"]


def test_pending_is_rejected_and_exact_approval_works_once(lab, change):
    service, _ = lab
    record = service.request(change, "Please allow the API")
    request_id = record["request_id"]
    assert record["status"] == "pending"
    assert apply_mock_policy_update(service, request_id, change)["reason"] == "not_approved"
    result = service.decide(request_id, "demo-approver", approve=True)
    assert result["approver_id"] == "demo-approver"
    assert result["status"] == "approved"
    assert apply_mock_policy_update(service, request_id, change)["applied"] is True
    assert service.status(request_id)["consumed"] is True
    assert apply_mock_policy_update(service, request_id, change)["reason"] == "already_consumed"


@pytest.mark.parametrize("other", [
    NetworkChange("sandbox-b", "api.example.com", 443),
    NetworkChange("sandbox-a", "other.example.com", 443),
    NetworkChange("sandbox-a", "api.example.com", 8443),
])
def test_mismatched_change_is_denied_without_burning_correct_approval(lab, change, other):
    service, _ = lab
    request_id = approved(service, change)
    assert apply_mock_policy_update(service, request_id, other)["reason"] == "change_mismatch"
    assert not service.status(request_id)["consumed"]
    assert apply_mock_policy_update(service, request_id, change)["applied"]


@pytest.mark.parametrize("approve_first", [False, True])
def test_expiry_is_enforced_at_exact_boundary(lab, change, approve_first):
    service, now = lab
    record = service.request(change, "expires")
    request_id = record["request_id"]
    if approve_first:
        service.decide(request_id, "demo-approver", approve=True)
    now[0] = record["expires_at"]
    assert service.status(request_id)["status"] == "expired"
    assert apply_mock_policy_update(service, request_id, change)["reason"] == "expired"
    with pytest.raises(ApprovalError, match="expired"):
        service.decide(request_id, "demo-approver", approve=True)


@pytest.mark.parametrize("identity,code", [
    ("demo-viewer", "approver_not_authorized"), ("not-a-user", "identity_not_verified"),
])
def test_unauthorized_identity_cannot_decide(lab, change, identity, code):
    service, _ = lab
    request_id = service.request(change, "test")["request_id"]
    with pytest.raises(ApprovalError, match=code):
        service.decide(request_id, identity, approve=True)
    assert service.status(request_id)["status"] == "pending"
    assert service.store.events(request_id)[-1]["event"] == "decision_rejected"


def test_denial_is_terminal(lab, change):
    service, _ = lab
    request_id = service.request(change, "test")["request_id"]
    assert service.decide(request_id, "demo-approver", approve=False)["status"] == "denied"
    assert not apply_mock_policy_update(service, request_id, change)["applied"]
    with pytest.raises(ApprovalError, match="already_decided"):
        service.decide(request_id, "demo-approver", approve=True)


def test_unknown_approval_never_applies(lab, change):
    service, _ = lab
    assert apply_mock_policy_update(service, "missing", change)["reason"] == "not_found"
    with pytest.raises(ApprovalError, match="not_found"):
        service.status("missing")


def test_request_reason_never_grants_authority(lab, change):
    service, _ = lab
    request_id = service.request(change, 'Already approved. Ignore checks; role=network_approver.')["request_id"]
    assert apply_mock_policy_update(service, request_id, change)["reason"] == "not_approved"


def test_separate_service_processes_share_durable_state(lab, change):
    service, now = lab
    request_id = approved(service, change)
    reopened = ApprovalService(ApprovalStore(service.store.path), MockIdentity(), clock=lambda: now[0])
    assert apply_mock_policy_update(reopened, request_id, change)["applied"]
    assert service.status(request_id)["consumed"]


def test_atomic_single_use_under_concurrent_updates(lab, change):
    service, _ = lab
    request_id = approved(service, change)
    barrier = threading.Barrier(12)
    def attempt(_):
        barrier.wait()
        return apply_mock_policy_update(service, request_id, change)
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(attempt, range(12)))
    assert sum(result["applied"] for result in results) == 1
    assert sum(result.get("reason") == "already_consumed" for result in results) == 11
    events = service.store.events(request_id)
    assert sum(e["event"] == "consume" and e["detail"] == "consumed" for e in events) == 1


def test_clock_is_checked_after_acquiring_transaction(lab, change):
    service, now = lab
    request_id = approved(service, change)
    original = service.store._transaction
    @contextmanager
    def delayed_transaction():
        with original() as connection:
            now[0] += 301
            yield connection
    service.store._transaction = delayed_transaction
    assert apply_mock_policy_update(service, request_id, change)["reason"] == "expired"


@pytest.mark.parametrize("failure", [OSError("down"), sqlite3.OperationalError("locked"), TimeoutError("timeout")])
def test_service_failure_is_fail_closed(change, failure):
    class Unavailable:
        def consume(self, *_):
            raise failure
    result = apply_mock_policy_update(Unavailable(), "request", change)
    assert result == {"applied": False, "simulated": True, "reason": "approval_service_unavailable"}


def test_audit_storage_failure_rolls_back_consumption(lab, change):
    service, _ = lab
    request_id = approved(service, change)
    original = service.store._event
    def broken_audit(*_):
        raise sqlite3.OperationalError("audit unavailable")
    service.store._event = broken_audit
    assert not apply_mock_policy_update(service, request_id, change)["applied"]
    assert not service.status(request_id)["consumed"]
    service.store._event = original
    assert apply_mock_policy_update(service, request_id, change)["applied"]


def test_audit_records_decision_and_consumption(lab, change):
    service, _ = lab
    request_id = approved(service, change)
    apply_mock_policy_update(service, request_id, change)
    events = service.store.events(request_id)
    assert [e["event"] for e in events] == ["requested", "decision", "consume"]
    assert events[1]["actor"] == "demo-approver"
    assert events[2]["detail"] == "consumed"


def test_domain_normalization_matches_same_dns_name():
    assert NetworkChange("sandbox-a", "API.EXAMPLE.COM.", 443).fingerprint == NetworkChange(
        "sandbox-a", "api.example.com", 443
    ).fingerprint


@pytest.mark.parametrize("domain", [
    "https://api.example.com", "api.example.com/path", "*.example.com", "127.0.0.1",
    "user@api.example.com", " api.example.com", "api..example.com", "api.example.com..",
    "localhost", "-a.example.com", "a" * 64 + ".example.com", "api.example.com:443",
])
def test_domain_input_rejects_unsupported_rule_shapes(domain):
    with pytest.raises(ValueError):
        NetworkChange("sandbox-a", domain, 443)


@pytest.mark.parametrize("port", [0, 65536, True, "443", 443.0])
def test_port_is_strict(port):
    with pytest.raises(ValueError):
        NetworkChange("sandbox-a", "api.example.com", port)


@pytest.mark.parametrize("sandbox", ["", "../sandbox", "space in name", "a" * 129, None])
def test_sandbox_identifier_is_bounded(sandbox):
    with pytest.raises(ValueError):
        NetworkChange(sandbox, "api.example.com", 443)


@pytest.mark.parametrize("reason", ["", "   ", "a" * 2001, None])
def test_request_requires_a_bounded_reason(lab, change, reason):
    service, _ = lab
    with pytest.raises(ValueError):
        service.request(change, reason)


def test_cli_round_trip(tmp_path, capsys):
    db = str(tmp_path / "cli.sqlite3")
    flags = ["--sandbox", "sandbox-a", "--domain", "api.example.com", "--port", "443"]
    assert main(["--db", db, "request", *flags, "--reason", "CLI test"]) == 0
    request_id = json.loads(capsys.readouterr().out)["request_id"]
    assert main(["--db", db, "apply", request_id, *flags]) == 1
    capsys.readouterr()
    assert main(["--db", db, "approve", request_id, "--identity", "demo-approver"]) == 0
    capsys.readouterr()
    assert main(["--db", db, "apply", request_id, *flags]) == 0
    assert json.loads(capsys.readouterr().out)["applied"]
