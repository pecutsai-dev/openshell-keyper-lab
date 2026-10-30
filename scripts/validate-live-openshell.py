"""Real OpenShell v0.1.6 acceptance test. Run only on a disposable Linux host.

Requires Docker, verified official gateway/sandbox binaries, the official SDK
wheel and this project's openshell extra. Starts and stops its own gateway and
interceptor. No public listener, mock gateway or real Keyper credentials.
"""

import argparse
import ast
import asyncio
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid
import zipfile

import grpc
from google.protobuf import descriptor_pool, descriptor_pb2, message_factory, json_format
from google.protobuf import duration_pb2, timestamp_pb2, struct_pb2
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def sdk_pool(wheel):
    result = descriptor_pool.DescriptorPool()
    for module in (descriptor_pb2, duration_pb2, timestamp_pb2, struct_pb2):
        result.AddSerializedFile(module.DESCRIPTOR.serialized_pb)
    pending = []
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.startswith("openshell/_proto/") and name.endswith("_pb2.py"):
                tree = ast.parse(archive.read(name))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "AddSerializedFile":
                        pending.append(ast.literal_eval(node.args[0]))
    while pending:
        remaining = []
        for data in pending:
            try:
                result.AddSerializedFile(data)
            except TypeError:
                remaining.append(data)
        if len(remaining) == len(pending):
            raise RuntimeError("Official SDK descriptors have unresolved dependencies")
        pending = remaining
    return result


class API:
    def __init__(self, target, wheel):
        self.pool = sdk_pool(wheel)
        self.channel = grpc.insecure_channel(target)

    def cls(self, name):
        return message_factory.GetMessageClass(self.pool.FindMessageTypeByName(name))

    def call(self, method, value, timeout=60):
        descriptor = self.pool.FindServiceByName("openshell.v1.OpenShell").methods_by_name[method]
        request = self.cls(descriptor.input_type.full_name)()
        json_format.ParseDict(value, request, descriptor_pool=self.pool)
        factory = self.channel.unary_stream if descriptor.server_streaming else self.channel.unary_unary
        call = factory("/openshell.v1.OpenShell/" + method,
                       request_serializer=lambda msg: msg.SerializeToString(),
                       response_deserializer=self.cls(descriptor.output_type.full_name).FromString)
        return call(request, timeout=timeout)


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin-dir", required=True, type=Path)
    parser.add_argument("--sdk-wheel", required=True, type=Path)
    parser.add_argument("--workload-image", default="approval-lab-workload:0.1.6")
    parser.add_argument("--supervisor-image", default="approval-lab-supervisor:0.1.6")
    parser.add_argument("--output", type=Path, default=Path(".approval-lab/live-validation"))
    args = parser.parse_args()
    if sys.platform != "linux":
        raise SystemExit("A disposable Linux host is required")
    run = args.output.resolve() / uuid.uuid4().hex[:12]
    run.mkdir(parents=True, mode=0o700)
    def binary(name):
        return str(next(args.bin_dir.resolve().rglob(name)))
    gateway, sandbox_binary = binary("openshell-gateway"), binary("openshell-sandbox")
    gateway_port, health_port = port(), port()
    endpoint = f"127.0.0.1:{gateway_port}"
    name = "mcp-" + uuid.uuid4().hex[:10]
    principal = {"kind": "user", "subject": "unauthenticated-local-dev",
                 "display_name": "Unauthenticated Local Dev", "provider": "local_dev",
                 "roles": "openshell-user,openshell-admin", "scopes": "openshell:all"}
    config = {"gateway_id": "disposable-live-test", "gateway_target": endpoint,
              "local_insecure": True, "principal": principal}
    config_path = run / "bridge.json"
    config_path.write_text(json.dumps(config))
    db_path = run / "approvals.sqlite3"
    # Keep raw gateway diagnostics in this private test directory. The production
    # MCP adapter intentionally exposes only a sanitized gRPC status to agents.
    diagnostic_agent = run / "agent-diagnostic.py"
    diagnostic_agent.write_text(f'''import json
from pathlib import Path
import grpc
import approval_lab.openshell_bridge as bridge
original_rpc = bridge.rpc
def traced_rpc(*args, **kwargs):
    method = original_rpc(*args, **kwargs)
    def call(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except grpc.RpcError as error:
            Path({str(run / 'gateway-error.json')!r}).write_text(json.dumps({{"code": error.code().name, "details": error.details()}}))
            raise
    return call
bridge.rpc = traced_rpc
from approval_lab.openshell_mcp import main
main()
''')
    key = Ed25519PrivateKey.generate()
    (run / "signing.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    (run / "public.pem").write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    (run / "kid").write_text("disposable-live-test")
    socket_path = run / "interceptor.sock"
    toml = f'''[openshell]
version = 2
[openshell.gateway.auth]
allow_unauthenticated_users = true
[openshell.gateway.gateway_jwt]
signing_key_path = "{run / 'signing.pem'}"
public_key_path = "{run / 'public.pem'}"
kid_path = "{run / 'kid'}"
gateway_id = "disposable-live-test"
[[openshell.gateway.interceptors]]
name = "approval-lab"
grpc_endpoint = "unix://{socket_path}"
order = 100
failure_policy = "fail_closed"
binding_policy = "exact"
timeout = "10s"
[[openshell.gateway.interceptors.bindings]]
rpc = "openshell.v1.OpenShell/UpdateConfig"
phases = ["validate"]
[openshell.drivers.docker]
grpc_endpoint = "http://{endpoint}"
supervisor_bin = "{sandbox_binary}"
supervisor_image = "{args.supervisor_image}"
'''
    (run / "gateway.toml").write_text(toml)
    version = subprocess.run([gateway, "--version"], check=True, capture_output=True, text=True).stdout.strip()
    if "0.1.6" not in version:
        raise RuntimeError("This acceptance script requires the verified v0.1.6 gateway")
    report = {"gateway_version": version, "platform": sys.platform,
              "real_gateway": False, "real_keyper": False, "checks": {}, "success": False}
    children, logs = [], []
    api = None
    created = False
    def launch(arguments, log_name):
        log = (run / log_name).open("wb")
        logs.append(log)
        process = subprocess.Popen(arguments, stdout=log, stderr=log)
        children.append(process)
        return process
    def check(label, value):
        report["checks"][label] = value
        print(label + ": " + json.dumps(value), flush=True)
        (run / "report.json").write_text(json.dumps(report, indent=2))
    try:
        interceptor = launch([sys.executable, "-m", "approval_lab.openshell_mcp", "interceptor",
                              "--config", str(config_path), "--db", str(db_path), "--listen", "unix:" + str(socket_path)], "interceptor.log")
        for _ in range(120):
            if socket_path.exists(): break
            if interceptor.poll() is not None: raise RuntimeError("Interceptor exited")
            time.sleep(1)
        process = launch([gateway, "--config", str(run / "gateway.toml"), "--bind-address", "127.0.0.1",
                          "--port", str(gateway_port), "--health-port", str(health_port), "--metrics-port", "0",
                          "--disable-tls", "--compute-driver", "docker",
                          "--db-url", "sqlite://" + str(run / "gateway.db")], "gateway.log")
        api = API(endpoint, args.sdk_wheel)
        for _ in range(600):
            if process.poll() is not None: raise RuntimeError("Gateway exited; inspect gateway.log")
            try:
                api.call("Health", {}, timeout=2)
                break
            except grpc.RpcError: time.sleep(1)
        else: raise RuntimeError("Gateway readiness timed out")
        report["real_gateway"] = True
        check("gateway_started_with_real_interceptor", True)
        policy = {"version": 1, "filesystem": {"includeWorkdir": True,
                  "readOnly": ["/usr", "/lib", "/lib64", "/etc", "/proc", "/dev/urandom"],
                  "readWrite": ["/sandbox", "/tmp", "/dev/null"]},
                  "landlock": {"compatibility": "best_effort"}}
        api.call("CreateSandbox", {"workspaceScope": {"workspace": "default"}, "name": name,
                  "spec": {"template": {"image": args.workload_image},
                           "policy": policy, "command": ["/bin/sleep", "3600"]}}, timeout=600)
        created = True
        request = {"name": name, "workspaceScope": {"workspace": "default"}}
        for _ in range(600):
            current = api.call("GetSandbox", request)
            status = json_format.MessageToDict(current.sandbox.status)
            if "READY" in str(status.get("phase", "")): break
            if "ERROR" in str(status.get("phase", "")): raise RuntimeError("Sandbox entered error: " + str(status))
            time.sleep(1)
        else: raise RuntimeError("Sandbox readiness timed out")
        check("real_sandbox_ready", {"name": name, "status": status})
        operation = {"sandbox": name, "workspaceScope": {"workspace": "default"},
                     "expectedResourceVersion": str(current.sandbox.metadata.resource_version),
                     "mergeOperations": [{"addRule": {"ruleName": "mcp-reviewed-example", "rule": {
                         "endpoints": [{"host": "example.com", "port": 443, "protocol": "tcp"}],
                         "binaries": [{"path": "/usr/bin/curl"}]}}}]}
        try:
            api.call("UpdateConfig", operation)
            raise RuntimeError("Unapproved update was accepted")
        except grpc.RpcError as exc:
            assert exc.code() == grpc.StatusCode.PERMISSION_DENIED
            check("unapproved_direct_rpc_denied", exc.code().name)

        def execute(command, stdin=None):
            output, errors, exit_code = b"", b"", None
            payload = {"sandbox": name, "workspaceScope": {"workspace": "default"},
                       "command": command, "noLoginShell": True, "executionTimeout": "30s"}
            if stdin is not None:
                payload["stdin"] = base64.b64encode(stdin).decode()
            for event in api.call("ExecSandbox", payload, timeout=45):
                kind = event.WhichOneof("payload")
                if kind == "stdout": output += event.stdout.data
                elif kind == "stderr": errors += event.stderr.data
                elif kind == "exit": exit_code = getattr(event, "exit").exit_code
            return {"exit_code": exit_code, "stdout": output.decode(errors="replace"), "stderr": errors.decode(errors="replace")}
        ca = Path("/etc/ssl/certs/ca-certificates.crt").read_bytes()
        result = execute(["/bin/sh", "-c", "cat > /tmp/lab-ca.pem"], stdin=ca)
        assert result["exit_code"] == 0, result
        # OpenShell's TLS inspection CA is generated per runtime. Keep that
        # trust anchor alongside the operator's public roots; never use curl -k.
        result = execute(["/usr/bin/printenv", "SSL_CERT_FILE"])
        assert result["exit_code"] == 0 and result["stdout"].strip(), result
        check("runtime_ca_bundle_path", result["stdout"].strip())
        result = execute(["/bin/sh", "-c", 'cat /tmp/lab-ca.pem "$SSL_CERT_FILE" > /tmp/lab-combined-ca.pem'])
        assert result["exit_code"] == 0, result
        result = execute(["/usr/bin/test", "-x", "/usr/bin/curl"])
        assert result["exit_code"] == 0, "Workload image must contain /usr/bin/curl"
        command = ["/usr/bin/curl", "--cacert", "/tmp/lab-combined-ca.pem", "--connect-timeout", "10", "--max-time", "20", "-fsS", "https://example.com"]
        before = execute(command)
        assert before["exit_code"] != 0, before
        check("network_before_approval", before)
        # OpenShell asynchronously persists denial analysis after the negative
        # probe. Let that observation settle BEFORE creating a review context.
        # Never rewrite the version of an already approved operation.
        last_version, stable_since = None, time.monotonic()
        for _ in range(120):
            current = api.call("GetSandbox", request)
            version = current.sandbox.metadata.resource_version
            if version != last_version:
                last_version, stable_since = version, time.monotonic()
            elif time.monotonic() - stable_since >= 12:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Sandbox resource version did not settle before human review")
        check("review_resource_version_after_observations", last_version)
        operation["expectedResourceVersion"] = str(current.sandbox.metadata.resource_version)

        async def mcp_flow():
            def params(role, extra=()):
                command = [str(diagnostic_agent)] if role == "agent" else ["-m", "approval_lab.openshell_mcp"]
                return StdioServerParameters(command=sys.executable, args=[*command, role,
                    "--config", str(config_path), "--db", str(db_path), *extra])
            async with stdio_client(params("agent")) as (r, w):
                async with ClientSession(r, w) as agent:
                    await agent.initialize()
                    response = await agent.call_tool("request_policy_update", {"operation": operation, "reason": "Live disposable OpenShell acceptance"})
                    assert not response.isError, response
                    request_id = response.structuredContent["request_id"]
                    async with stdio_client(params("operator", ["--local-mock-keyper"])) as (rr, ww):
                        async with ClientSession(rr, ww) as operator:
                            await operator.initialize()
                            result = await operator.call_tool("decide_policy_update", {"request_id": request_id, "approve": True, "assertion": "demo-approver"})
                            assert not result.isError, result
                    result = await agent.call_tool("submit_approved_policy", {"request_id": request_id})
                    assert not result.isError, result
                    check("mcp_to_real_gateway_submission", result.structuredContent)
                    replay = await agent.call_tool("submit_approved_policy", {"request_id": request_id})
                    assert replay.isError, replay
                    check("mcp_replay_rejected", True)
        asyncio.run(mcp_flow())
        for _ in range(120):
            state = api.call("GetSandboxPolicyStatus", {"sandbox": name, "workspaceScope": {"workspace": "default"}})
            if state.active_version >= 2: break
            time.sleep(1)
        else: raise RuntimeError("Runtime did not acknowledge the new policy")
        check("runtime_policy_active_version", state.active_version)
        after = execute(command)
        assert after["exit_code"] == 0 and "Example Domain" in after["stdout"], after
        check("network_after_approval", after)
        other = execute([*command[:-1], "https://www.iana.org"])
        assert other["exit_code"] != 0, other
        check("unapproved_destination_denied", other)
        report["success"] = True
    finally:
        if api:
            if created:
                # Preserve this test sandbox's diagnostics before asynchronous
                # gateway deletion removes the supervisor container.
                try:
                    ids = subprocess.check_output(["docker", "ps", "-aq", "--filter", "label=openshell.ai/sandbox-name=" + name,
                                                   "--filter", "label=openshell.ai/isolation-role=supervisor"], text=True).split()
                    for container in ids:
                        output = subprocess.run(["docker", "logs", "--tail", "150", container], capture_output=True)
                        (run / "supervisor.log").write_bytes(output.stdout + output.stderr)
                except (OSError, subprocess.SubprocessError):
                    pass
                try:
                    api.call("DeleteSandbox", {"name": name, "workspaceScope": {"workspace": "default"}, "allowMissing": True}, timeout=60)
                except Exception: pass
            api.channel.close()
        for child in reversed(children):
            child.terminate()
            try: child.wait(timeout=15)
            except subprocess.TimeoutExpired: child.kill(); child.wait()
        for log in logs: log.close()
        (run / "report.json").write_text(json.dumps(report, indent=2))
        print("Evidence directory: " + str(run), flush=True)


if __name__ == "__main__":
    main()
