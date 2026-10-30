"""Wire-compatible subset of the pinned official OpenShell protobuf contract.

Only the deliberately supported messages/fields are described; unknown JSON
fields are rejected. See tests checking names, numbers and types against the
unmodified official sources. No native protoc compiler executes at runtime.
"""

from functools import lru_cache
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory, json_format, struct_pb2


# Field declarations are (name, wire number, type, repeated).
SCHEMA = {
    "openshell.datamodel.v1.WorkspaceSelector": [("workspace", 1, "string", False)],
    "openshell.sandbox.v1.NetworkBinary": [("path", 1, "string", False)],
    "openshell.sandbox.v1.NetworkEndpoint": [("host", 1, "string", False), ("port", 2, "uint32", False), ("protocol", 3, "string", False)],
    "openshell.sandbox.v1.NetworkPolicyRule": [("name", 1, "string", False), ("endpoints", 2, "openshell.sandbox.v1.NetworkEndpoint", True), ("binaries", 3, "openshell.sandbox.v1.NetworkBinary", True)],
    "openshell.v1.AddNetworkRule": [("rule_name", 1, "string", False), ("rule", 2, "openshell.sandbox.v1.NetworkPolicyRule", False)],
    "openshell.v1.PolicyMergeOperation": [("add_rule", 1, "openshell.v1.AddNetworkRule", False)],
    "openshell.v1.UpdateConfigRequest": [("sandbox", 1, "string", False), ("merge_operations", 7, "openshell.v1.PolicyMergeOperation", True), ("expected_resource_version", 8, "uint64", False), ("annotations", 9, "map", False), ("workspace_scope", 10, "openshell.datamodel.v1.WorkspaceSelector", False), ("request_id", 11, "string", False)],
    "openshell.v1.UpdateConfigResponse": [("version", 1, "uint32", False), ("policy_hash", 2, "string", False), ("settings_revision", 3, "uint64", False), ("deleted", 4, "bool", False), ("annotations", 5, "map", False)],
    "openshell.extension.v1.ProtocolVersion": [("major", 1, "uint32", False), ("minor", 2, "uint32", False)],
    "openshell.extension.v1.PeerMetadata": [("protocol_version", 1, "openshell.extension.v1.ProtocolVersion", False), ("implementation_name", 2, "string", False), ("implementation_version", 3, "string", False), ("supported_capabilities", 4, "string", True), ("required_capabilities", 5, "string", True)],
}
PREFIX = "openshell.gateway_interceptor.v1."
SCHEMA.update({PREFIX + name: fields for name, fields in {
    "DescribeRequest": [("gateway", 1, "openshell.extension.v1.PeerMetadata", False)],
    "InterceptorSelector": [("rpc", 1, "string", False), ("service", 2, "string", False), ("method", 3, "string", False)],
    "InterceptorBinding": [("id", 1, "string", False), ("selector", 2, PREFIX + "InterceptorSelector", False), ("phases", 3, "phase_enum", True), ("failure_policy", 4, "string", False)],
    "InterceptorManifest": [("name", 1, "string", False), ("bindings", 2, PREFIX + "InterceptorBinding", True), ("failure_policy", 3, "string", False), ("provider_profiles", 4, "bool", False), ("expected_audience", 5, "string", False), ("extension", 6, "openshell.extension.v1.PeerMetadata", False)],
    "ModifyOperationEvaluation": [("proposed_operation", 1, "google.protobuf.Struct", False)],
    "ValidateEvaluation": [("proposed_operation", 1, "google.protobuf.Struct", False), ("current_state", 2, "google.protobuf.Struct", False)],
    "PostCommitEvaluation": [("committed_response", 1, "google.protobuf.Struct", False)],
    "InterceptorEvaluation": [("interceptor_name", 1, "string", False), ("binding_id", 2, "string", False), ("service", 3, "string", False), ("method", 4, "string", False), ("principal", 5, "map", False), ("modify_operation", 6, PREFIX + "ModifyOperationEvaluation", False), ("validate", 7, PREFIX + "ValidateEvaluation", False), ("post_commit", 8, PREFIX + "PostCommitEvaluation", False)],
    "InterceptorResult": [("allowed", 1, "bool", False), ("reason", 2, "string", False), ("status_code", 3, "string", False), ("log_annotations", 5, "map", False)],
}.items()})


@lru_cache(maxsize=1)
def pool():
    result = descriptor_pool.DescriptorPool()
    result.AddSerializedFile(struct_pb2.DESCRIPTOR.serialized_pb)
    packages = ["openshell.datamodel.v1", "openshell.sandbox.v1", "openshell.v1", "openshell.extension.v1", PREFIX.rstrip(".")]
    scalar = {"string": 9, "bool": 8, "uint32": 13, "uint64": 4}
    for package in packages:
        fd = descriptor_pb2.FileDescriptorProto(name=package + ".proto", package=package, syntax="proto3")
        if package == PREFIX.rstrip("."):
            enum = fd.enum_type.add(name="GatewayInterceptorPhase")
            for name, number in [("UNSPECIFIED", 0), ("MODIFY_OPERATION", 2), ("VALIDATE", 3), ("POST_COMMIT", 4)]:
                enum.value.add(name="GATEWAY_INTERCEPTOR_PHASE_" + name, number=number)
        for full_name, fields in SCHEMA.items():
            if full_name.rsplit(".", 1)[0] != package:
                continue
            descriptor = fd.message_type.add(name=full_name.rsplit(".", 1)[1])
            if full_name == PREFIX + "InterceptorEvaluation":
                descriptor.oneof_decl.add(name="phase")
            for name, number, kind, repeated in fields:
                field = descriptor.field.add(name=name, number=number, label=3 if repeated else 1)
                if name in {"modify_operation", "validate", "post_commit"} and full_name == PREFIX + "InterceptorEvaluation":
                    field.oneof_index = 0
                if kind in scalar:
                    field.type = scalar[kind]
                elif kind == "map":
                    entry_name = ''.join(part.title() for part in name.split('_')) + "Entry"
                    entry = descriptor.nested_type.add(name=entry_name)
                    entry.options.map_entry = True
                    entry.field.add(name="key", number=1, type=9, label=1)
                    entry.field.add(name="value", number=2, type=9, label=1)
                    field.type, field.label, field.type_name = 11, 3, "." + full_name + "." + entry_name
                else:
                    field.type = 14 if kind == "phase_enum" else 11
                    target = PREFIX + "GatewayInterceptorPhase" if kind == "phase_enum" else kind
                    field.type_name = "." + target
                    dependency = "google/protobuf/struct.proto" if target.startswith("google.") else target.rsplit(".", 1)[0] + ".proto"
                    if dependency != fd.name and dependency not in fd.dependency:
                        fd.dependency.append(dependency)
        result.Add(fd)
    return result


def message(name, value=None):
    result = message_factory.GetMessageClass(pool().FindMessageTypeByName(name))()
    if value is not None:
        json_format.ParseDict(value, result, ignore_unknown_fields=False, descriptor_pool=pool())
    return result


def as_json(value):
    return json_format.MessageToDict(value, descriptor_pool=pool())


def rpc(channel, service, method, request_type, response_type):
    return channel.unary_unary(
        f"/{service}/{method}", request_serializer=lambda value: value.SerializeToString(),
        response_deserializer=message_factory.GetMessageClass(pool().FindMessageTypeByName(response_type)).FromString,
    )
