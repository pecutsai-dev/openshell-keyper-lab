"""Real OpenShell gRPC client and fail-closed UpdateConfig interceptor."""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import stat

import grpc

from .models import ApprovalError
from .openshell_wire import as_json, message, rpc


INTERCEPTOR = "openshell.gateway_interceptor.v1.GatewayInterceptor"
SERVICE = "openshell.v1.OpenShell"
CAPABILITY = "openshell.gateway-interceptor.contract"
BINDING = "approved-network-addition"


def local_address(target):
    return target.startswith("unix:") or target.rsplit(":", 1)[0] in {"127.0.0.1", "localhost", "[::1]"}


def gateway_channel(config):
    target = config["gateway_target"]
    if target.startswith("unix:"):
        return grpc.insecure_channel(target)
    if config.get("local_insecure"):
        if not local_address(target):
            raise ValueError("Insecure TCP is restricted to loopback development")
        return grpc.insecure_channel(target)
    def read(key):
        return Path(config[key]).read_bytes() if config.get(key) else None
    return grpc.secure_channel(target, grpc.ssl_channel_credentials(
        root_certificates=read("gateway_ca"), private_key=read("client_key"),
        certificate_chain=read("client_cert"),
    ))


def submit(approvals, request_id, config):
    operation = approvals.approved_operation(request_id)
    metadata = []
    if config.get("bearer_env"):
        token = os.environ.get(config["bearer_env"])
        if not token:
            raise ApprovalError("gateway_credential_unavailable")
        metadata = [("authorization", f"Bearer {token}")]
    try:
        with gateway_channel(config) as channel:
            call = rpc(channel, SERVICE, "UpdateConfig", "openshell.v1.UpdateConfigRequest", "openshell.v1.UpdateConfigResponse")
            response = call(message("openshell.v1.UpdateConfigRequest", operation), timeout=10, metadata=metadata)
    except grpc.RpcError as exc:
        # Do not expose gateway error bodies, credentials or restore a consumed approval.
        raise ApprovalError(f"gateway_rpc_{exc.code().name.lower()}") from None
    if not approvals.status(request_id)["consumed"]:
        raise ApprovalError("gateway_returned_without_approval_consumption_check_deployment")
    return {"submitted": True, "gateway_response": as_json(response),
            "runtime_policy_loaded": False, "request_id": request_id}


class Interceptor:
    def __init__(self, approvals):
        self.approvals = approvals

    def describe(self, request, context):
        peer = request.gateway
        if peer.protocol_version.major != 1 or set(peer.required_capabilities) - {CAPABILITY}:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, "Incompatible extension protocol")
        return message("openshell.gateway_interceptor.v1.InterceptorManifest", {
            "name": "approval-lab", "failurePolicy": "fail_closed",
            "extension": {"protocolVersion": {"major": 1}, "implementationName": "approval-lab",
                          "implementationVersion": "0.1.0", "supportedCapabilities": [CAPABILITY]},
            "bindings": [{"id": BINDING, "selector": {"rpc": SERVICE + "/UpdateConfig"},
                          "phases": ["GATEWAY_INTERCEPTOR_PHASE_VALIDATE"], "failurePolicy": "fail_closed"}],
        })

    def evaluate(self, request, context):
        result_type = "openshell.gateway_interceptor.v1.InterceptorResult"
        try:
            if (request.service != SERVICE or request.method != "UpdateConfig" or
                    request.binding_id != BINDING or request.WhichOneof("phase") != "validate"):
                raise ApprovalError("unsupported_evaluation")
            reference = self.approvals.consume_operation(
                as_json(request.validate.proposed_operation), dict(request.principal))
            return message(result_type, {"allowed": True, "logAnnotations": {"approval_request_id": reference}})
        except ApprovalError as exc:
            reason = exc.code
        except ValueError:
            reason = "unsupported_or_invalid_operation"
        except Exception:
            reason = "approval_service_unavailable"
        return message(result_type, {"allowed": False, "statusCode": "PERMISSION_DENIED", "reason": reason})


def register_interceptor(server, approvals):
    implementation = Interceptor(approvals)
    methods = {}
    for name, handler, request_type in (
        ("Describe", implementation.describe, "DescribeRequest"),
        ("Evaluate", implementation.evaluate, "InterceptorEvaluation"),
    ):
        cls = type(message("openshell.gateway_interceptor.v1." + request_type))
        methods[name] = grpc.unary_unary_rpc_method_handler(
            handler, request_deserializer=cls.FromString,
            response_serializer=lambda value: value.SerializeToString())
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(INTERCEPTOR, methods),))


def serve_interceptor(approvals, listen, *, local_insecure=False):
    # Production transport for this milestone is a private, same-host Unix socket.
    # No unauthenticated network listener or pretend gateway JWT verification.
    if listen.startswith("unix:"):
        socket_path = Path(listen.removeprefix("unix:").removeprefix("//"))
        if not socket_path.is_absolute():
            raise ValueError("Unix socket path must be absolute")
        mode = socket_path.parent.stat().st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise ValueError("Unix socket parent must be private (chmod 700)")
    elif not local_insecure or not local_address(listen):
        raise ValueError("Use a private Unix socket, or explicit loopback-only --local-insecure")
    server = grpc.server(ThreadPoolExecutor(max_workers=8), options=[("grpc.max_receive_message_length", 1024 * 1024)])
    register_interceptor(server, approvals)
    if not server.add_insecure_port(listen):
        raise RuntimeError("Cannot bind interceptor")
    server.start()
    return server
