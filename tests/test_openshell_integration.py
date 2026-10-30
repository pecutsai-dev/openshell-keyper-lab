"""Real MCP stdio and official gRPC wire; gateway peer is a test double."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

import pytest

grpc = pytest.importorskip("grpc")
pytest.importorskip("google.protobuf")

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from approval_lab.approval_store import ApprovalStore
from approval_lab.identity_adapter import Identity
from approval_lab.keyper_adapter import LocalMockKeyper, UnconfiguredKeyper
from approval_lab.models import ApprovalError
from approval_lab.openshell_bridge import INTERCEPTOR, SERVICE, BINDING, register_interceptor, submit, gateway_channel
from approval_lab.openshell_policy import PolicyApprovals, REFERENCE, canonical_change
from approval_lab.openshell_wire import as_json, message, rpc, SCHEMA, pool


def operation():
    return {
        "sandbox": "sandbox-demo", "workspaceScope": {"workspace": "default"},
        "expectedResourceVersion": "1",
        "mergeOperations": [{"addRule": {"ruleName": "approved-api", "rule": {
            "endpoints": [{"host": "api.example.com", "port": 443, "protocol": "tcp"}],
            "binaries": [{"path": "/usr/bin/curl"}],
        }}}],
    }


@pytest.fixture
def approvals(tmp_path):
    return PolicyApprovals(ApprovalStore(tmp_path / "bridge.sqlite3"), LocalMockKeyper(),
                           gateway_id="test-gateway", principal={"kind": "user", "subject": "test-user"})


@pytest.fixture
def wire_gateway(approvals):
    """A protocol peer, NOT an OpenShell runtime or policy enforcement engine."""
    interceptor = grpc.server(ThreadPoolExecutor(max_workers=4))
    register_interceptor(interceptor, approvals)
    interceptor_port = interceptor.add_insecure_port("127.0.0.1:0")
    interceptor.start()
    channel = grpc.insecure_channel(f"127.0.0.1:{interceptor_port}")
    evaluate = rpc(channel, INTERCEPTOR, "Evaluate", "openshell.gateway_interceptor.v1.InterceptorEvaluation",
                   "openshell.gateway_interceptor.v1.InterceptorResult")
    describe = rpc(channel, INTERCEPTOR, "Describe", "openshell.gateway_interceptor.v1.DescribeRequest",
                   "openshell.gateway_interceptor.v1.InterceptorManifest")
    manifest = describe(message("openshell.gateway_interceptor.v1.DescribeRequest", {
        "gateway": {"protocolVersion": {"major": 1}}}), timeout=3)
    assert manifest.bindings[0].selector.rpc == SERVICE + "/UpdateConfig"
    committed = []

    def update(request, context):
        evaluation = message("openshell.gateway_interceptor.v1.InterceptorEvaluation", {
            "bindingId": BINDING, "service": SERVICE, "method": "UpdateConfig",
            "principal": approvals.principal, "validate": {"proposedOperation": as_json(request)},
        })
        result = evaluate(evaluation, timeout=3)
        if not result.allowed:
            context.abort(grpc.StatusCode.PERMISSION_DENIED, result.reason)
        committed.append(as_json(request))
        return message("openshell.v1.UpdateConfigResponse", {"version": 2, "policyHash": "protocol-peer-only"})

    server = grpc.server(ThreadPoolExecutor(max_workers=4))
    request_type = type(message("openshell.v1.UpdateConfigRequest"))
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(SERVICE, {
        "UpdateConfig": grpc.unary_unary_rpc_method_handler(update,
            request_deserializer=request_type.FromString, response_serializer=lambda value: value.SerializeToString())
    }),))
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    config = {"gateway_target": f"127.0.0.1:{port}", "local_insecure": True,
              "gateway_id": approvals.gateway_id, "principal": approvals.principal}
    try:
        yield config, committed, evaluate, describe
    finally:
        server.stop(0).wait()
        channel.close()
        interceptor.stop(0).wait()


def test_mcp_request_keyper_operator_submit_real_grpc_wire(approvals, wire_gateway, tmp_path):
    config, committed, _, _ = wire_gateway
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))

    def params(role, *extra):
        return StdioServerParameters(command=sys.executable, args=["-m", "approval_lab.openshell_mcp", role,
            "--config", str(config_path), "--db", approvals.store.path, *extra])

    async def run():
        async with stdio_client(params("agent")) as (reader, writer):
            async with ClientSession(reader, writer) as agent:
                await agent.initialize()
                names = {tool.name for tool in (await agent.list_tools()).tools}
                assert names == {"request_policy_update", "get_policy_approval", "submit_approved_policy"}
                response = await agent.call_tool("request_policy_update", {"operation": operation(), "reason": "Protocol test"})
                assert not response.isError
                request_id = response.structuredContent["request_id"]
                blocked = await agent.call_tool("submit_approved_policy", {"request_id": request_id})
                assert blocked.isError and not committed
                # The private operator MCP has a separate connection and verifier.
                async with stdio_client(params("operator", "--local-mock-keyper")) as (r, w):
                    async with ClientSession(r, w) as operator:
                        await operator.initialize()
                        review = await operator.call_tool("get_policy_review", {"request_id": request_id, "approve": True})
                        reviewed_operation = review.structuredContent["record"]["change"]["operation"]
                        assert reviewed_operation["mergeOperations"] == operation()["mergeOperations"]
                        assert reviewed_operation["requestId"]
                        assert len(review.structuredContent["challenge"]) == 64
                        decision = await operator.call_tool("decide_policy_update", {
                            "request_id": request_id, "approve": True, "assertion": "demo-approver"})
                        assert not decision.isError
                result = await agent.call_tool("submit_approved_policy", {"request_id": request_id})
                assert not result.isError, result
                assert result.structuredContent["submitted"]
                assert result.structuredContent["runtime_policy_loaded"] is False
                replay = await agent.call_tool("submit_approved_policy", {"request_id": request_id})
                assert replay.isError
    asyncio.run(run())
    assert len(committed) == 1
    assert approvals.store.events(committed[0]["annotations"][REFERENCE])[-1]["actor"] == "openshell-interceptor"


@pytest.mark.parametrize("change", ["port", "binary", "workspace", "version", "principal", "missing-reference"])
def test_gateway_interceptor_rejects_tampering(approvals, wire_gateway, change):
    _, committed, evaluate, _ = wire_gateway
    record = approvals.request(operation(), "Exact mutation")
    approvals.decide(record["request_id"], "demo-approver", True)
    op = approvals.approved_operation(record["request_id"])
    principal = dict(approvals.principal)
    rule = op["mergeOperations"][0]["addRule"]["rule"]
    if change == "port": rule["endpoints"][0]["port"] = 8443
    if change == "binary": rule["binaries"][0]["path"] = "/usr/bin/python"
    if change == "workspace": op["workspaceScope"]["workspace"] = "other"
    if change == "version": op["expectedResourceVersion"] = "2"
    if change == "principal": principal["subject"] = "other"
    if change == "missing-reference": op.pop("annotations")
    result = evaluate(message("openshell.gateway_interceptor.v1.InterceptorEvaluation", {
        "bindingId": BINDING, "service": SERVICE, "method": "UpdateConfig", "principal": principal,
        "validate": {"proposedOperation": op}}), timeout=3)
    assert not result.allowed and not committed
    assert not approvals.status(record["request_id"])["consumed"]


def test_keyper_context_is_bound_to_decision_and_adapter_is_replaceable(approvals):
    record = approvals.request(operation(), "Keyper integration contract")
    yes = approvals.context(record["request_id"], True)
    no = approvals.context(record["request_id"], False)
    assert yes.challenge != no.challenge
    approvals.verifier = UnconfiguredKeyper()
    with pytest.raises(ApprovalError, match="keyper_not_configured"):
        approvals.decide(record["request_id"], "demo-approver", True)

    class BoundVerifier:
        def verify_decision(self, assertion, context):
            if assertion != context.challenge:
                raise ApprovalError("assertion_not_bound")
            return Identity("verified-test-human", frozenset({"network_approver"}))
    approvals.verifier = BoundVerifier()
    with pytest.raises(ApprovalError, match="assertion_not_bound"):
        approvals.decide(record["request_id"], no.challenge, True)
    assert approvals.decide(record["request_id"], yes.challenge, True)["approver_id"] == "verified-test-human"


@pytest.mark.parametrize("field,value", [("global", True), ("expectedResourceVersion", "0"),
    ("settingKey", "unrelated"), ("policy", {}), ("unknown", True)])
def test_scope_rejected_before_human_review(approvals, field, value):
    op = operation()
    op[field] = value
    with pytest.raises(Exception):
        approvals.request(op, "Unsupported scope")


def test_expired_consumption_fails_closed(approvals):
    now = [1000.0]
    approvals.clock = lambda: now[0]
    record = approvals.request(operation(), "Expires")
    approvals.decide(record["request_id"], "demo-approver", True)
    op = approvals.approved_operation(record["request_id"])
    now[0] += 300
    with pytest.raises(ApprovalError, match="expired"):
        approvals.consume_operation(op, approvals.principal)


def test_remote_plaintext_is_rejected():
    with pytest.raises(ValueError, match="loopback"):
        gateway_channel({"gateway_target": "example.com:8080", "local_insecure": True})


def test_incompatible_negotiation_rejected(approvals, wire_gateway):
    _, _, _, describe = wire_gateway
    with pytest.raises(grpc.RpcError) as exc:
        describe(message("openshell.gateway_interceptor.v1.DescribeRequest", {
            "gateway": {"protocolVersion": {"major": 2}}}), timeout=3)
    assert exc.value.code() == grpc.StatusCode.FAILED_PRECONDITION


def test_wire_subset_matches_pinned_official_field_numbers_types_and_cardinality():
    import re
    import approval_lab
    root = Path(approval_lab.__file__).parent / "openshell_proto"
    # Extract balanced message blocks; nested messages/oneof do not truncate them.
    sources = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.proto"))
    sources = re.sub(r"//[^\n]*", "", sources)
    for full_name, fields in SCHEMA.items():
        name = full_name.rsplit(".", 1)[1]
        match = re.search(r"\bmessage\s+" + re.escape(name) + r"\s*\{", sources)
        assert match, full_name
        start, depth, end = match.end(), 1, match.end()
        while depth:
            depth += (sources[end] == "{") - (sources[end] == "}")
            end += 1
        block = sources[start:end - 1]
        for field, number, kind, repeated in fields:
            source_type = "map<string, string>" if kind == "map" else "GatewayInterceptorPhase" if kind == "phase_enum" else kind.rsplit(".", 1)[-1]
            declaration = re.search(r"(?P<repeated>repeated\s+)?(?:[\w]+\.)*" + re.escape(source_type) + r"\s+" + re.escape(field) + r"\s*=\s*(\d+)\b", block)
            assert declaration, (full_name, field, source_type)
            assert int(declaration.group(2)) == number
            assert bool(declaration.group("repeated")) == repeated
    enum = pool().FindEnumTypeByName("openshell.gateway_interceptor.v1.GatewayInterceptorPhase")
    for value in enum.values:
        assert re.search(re.escape(value.name) + r"\s*=\s*" + str(value.number) + r"\s*;", sources)


def test_atomic_interceptor_consumption(approvals):
    record = approvals.request(operation(), "Concurrent mutation")
    approvals.decide(record["request_id"], "demo-approver", True)
    op = approvals.approved_operation(record["request_id"])
    def consume(_):
        try:
            approvals.consume_operation(op, approvals.principal)
            return "allowed"
        except ApprovalError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(consume, range(8)))
    assert results.count("allowed") == 1
    assert results.count("already_consumed") == 7


def test_interceptor_storage_failure_denies(approvals, wire_gateway, monkeypatch):
    _, _, evaluate, _ = wire_gateway
    record = approvals.request(operation(), "Storage failure")
    approvals.decide(record["request_id"], "demo-approver", True)
    op = approvals.approved_operation(record["request_id"])
    def unavailable(*args, **kwargs):
        raise OSError("database unavailable")
    monkeypatch.setattr(approvals.store, "consume", unavailable)
    result = evaluate(message("openshell.gateway_interceptor.v1.InterceptorEvaluation", {
        "bindingId": BINDING, "service": SERVICE, "method": "UpdateConfig", "principal": approvals.principal,
        "validate": {"proposedOperation": op}}), timeout=3)
    assert not result.allowed and result.reason == "approval_service_unavailable"


def test_gateway_failure_after_consumption_does_not_restore_approval(approvals):
    record = approvals.request(operation(), "Gateway failure")
    approvals.decide(record["request_id"], "demo-approver", True)
    def fail(request, context):
        approvals.consume_operation(as_json(request), approvals.principal)
        context.abort(grpc.StatusCode.ABORTED, "simulated version conflict")
    server = grpc.server(ThreadPoolExecutor(max_workers=2))
    cls = type(message("openshell.v1.UpdateConfigRequest"))
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(SERVICE, {
        "UpdateConfig": grpc.unary_unary_rpc_method_handler(fail,
            request_deserializer=cls.FromString, response_serializer=lambda value: value.SerializeToString())}),))
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    try:
        with pytest.raises(ApprovalError, match="gateway_rpc_aborted"):
            submit(approvals, record["request_id"], {"gateway_target": f"127.0.0.1:{port}", "local_insecure": True})
        assert approvals.status(record["request_id"])["consumed"]
    finally:
        server.stop(0).wait()


def test_keyper_verifier_error_does_not_disclose_assertion(approvals):
    record = approvals.request(operation(), "Verifier error")
    class BrokenVerifier:
        def verify_decision(self, assertion, context):
            raise RuntimeError("untrusted error includes " + assertion)
    approvals.verifier = BrokenVerifier()
    secret = "private-assertion-test-marker"
    with pytest.raises(ApprovalError, match="^identity_verifier_unavailable$"):
        approvals.decide(record["request_id"], secret, True)
    assert secret not in json.dumps(approvals.store.events(record["request_id"]))
    assert approvals.status(record["request_id"])["status"] == "pending"


def test_verified_identity_without_approval_role_cannot_decide(approvals):
    record = approvals.request(operation(), "Role check")
    with pytest.raises(ApprovalError, match="approver_not_authorized"):
        approvals.decide(record["request_id"], "demo-viewer", True)
    assert approvals.status(record["request_id"])["status"] == "pending"


def test_published_mcp_schemas_match_runtime(approvals):
    from approval_lab.openshell_mcp import agent_server, operator_server
    root = Path(__file__).resolve().parents[1] / "examples" / "openshell"
    async def check():
        for name, server in [("agent", agent_server(approvals, {})), ("operator", operator_server(approvals))]:
            expected = json.loads((root / f"{name}-tools.schema.json").read_text(encoding="utf-8"))
            actual = [tool.model_dump(mode="json", exclude_none=True) for tool in await server.list_tools()]
            assert actual == expected
    asyncio.run(check())
