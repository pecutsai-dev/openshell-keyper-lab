"""Separate agent and operator MCP servers plus the real gRPC interceptor."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from pydantic import Field
from typing import Annotated, Any

from .approval_store import ApprovalStore
from .keyper_adapter import load_verifier
from .openshell_bridge import serve_interceptor, submit
from .openshell_policy import PolicyApprovals


def agent_server(approvals, config):
    server = FastMCP("OpenShell policy requests")

    @server.tool(structured_output=True)
    def request_policy_update(operation: dict[str, Any], reason: str) -> dict[str, Any]:
        """Request human review of one version-bound OpenShell addRule operation."""
        return approvals.request(operation, reason)

    @server.tool(structured_output=True)
    def get_policy_approval(request_id: str) -> dict[str, Any]:
        """Inspect the exact operation and its approval state."""
        return approvals.status(request_id)

    @server.tool(structured_output=True, description="Submit the stored approved operation to the configured OpenShell gateway. Accepts only a request ID. Success means gateway acknowledgement, not sandbox policy reload or connectivity.")
    def submit_approved_policy(request_id: str) -> dict[str, Any]:
        """Submit the stored approved operation to the configured OpenShell gateway.

        No caller-supplied operation or approval boolean is accepted. Success
        means gateway acknowledgement, not sandbox policy reload or connectivity.
        """
        return submit(approvals, request_id, config)

    return server


def operator_server(approvals):
    server = FastMCP("PRIVATE operator Keyper decision interface")

    @server.tool(structured_output=True)
    def get_policy_review(request_id: str, approve: Annotated[bool, Field(strict=True)]) -> dict[str, Any]:
        """Review the full operation and obtain the exact Keyper decision challenge."""
        context = approvals.context(request_id, approve)
        return {"record": approvals.status(request_id), "decision_context": asdict(context),
                "challenge": context.challenge, "challenge_version": "openshell-policy-decision-v1"}

    @server.tool(structured_output=True, description="Private operator path: verify an assertion bound to this decision using the configured Keyper adapter. Never connect this endpoint to the requesting agent.")
    def decide_policy_update(request_id: str, approve: Annotated[bool, Field(strict=True)], assertion: str) -> dict[str, Any]:
        """Private operator path: verify a Keyper assertion bound to this decision.

        Assertion verification is supplied by an operator-configured Keyper adapter.
        This endpoint must never be connected to the requesting agent.
        """
        return approvals.decide(request_id, assertion, approve)

    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=["agent", "operator", "interceptor"])
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--db", required=True)
    parser.add_argument("--keyper-verifier", help="Trusted Python module:factory implementing verify_decision")
    parser.add_argument("--local-mock-keyper", action="store_true")
    parser.add_argument("--listen", default="unix:/tmp/approval-lab/interceptor.sock")
    parser.add_argument("--local-insecure", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    approvals = PolicyApprovals(ApprovalStore(args.db), load_verifier(
        args.keyper_verifier, local_mock=args.local_mock_keyper),
        gateway_id=config["gateway_id"], principal=config["principal"])
    if args.role == "agent":
        agent_server(approvals, config).run(transport="stdio")
    elif args.role == "operator":
        operator_server(approvals).run(transport="stdio")
    else:
        server = serve_interceptor(approvals, args.listen, local_insecure=args.local_insecure)
        try:
            server.wait_for_termination()
        except KeyboardInterrupt:
            server.stop(2).wait()


if __name__ == "__main__":
    main()
