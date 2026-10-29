"""Separate local operator interface. Its mock identity is never an MCP tool."""

import argparse
import json
import os
import sqlite3

from .approval_service import ApprovalService
from .approval_store import ApprovalStore
from .mock_identity import MockIdentity
from .mock_policy_update import apply_mock_policy_update
from .models import ApprovalError, NetworkChange


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="LOCAL MOCK ONLY: review, approve, deny and simulate updates")
    parser.add_argument("--db", default=os.environ.get("APPROVAL_LAB_DB", ".approval-lab/approvals.sqlite3"))
    commands = parser.add_subparsers(dest="command", required=True)
    request = commands.add_parser("request", help="Create the same request as the MCP tool")
    apply = commands.add_parser("apply", help="Simulate the protected update path")
    for command in (request, apply):
        if command is apply:
            command.add_argument("request_id")
        command.add_argument("--sandbox", required=True)
        command.add_argument("--domain", required=True)
        command.add_argument("--port", required=True, type=int)
    request.add_argument("--reason", required=True)
    for name in ("status", "approve", "deny", "audit"):
        command = commands.add_parser(name)
        command.add_argument("request_id")
        if name in {"approve", "deny"}:
            command.add_argument("--identity", required=True, help="Mock identity: demo-approver or demo-viewer")
    args = parser.parse_args(argv)
    try:
        service = ApprovalService(ApprovalStore(args.db), MockIdentity())
        if args.command == "request":
            result = service.request(NetworkChange(args.sandbox, args.domain, args.port), args.reason)
        elif args.command in {"approve", "deny"}:
            result = service.decide(args.request_id, args.identity, approve=args.command == "approve")
        elif args.command == "status":
            result = service.status(args.request_id)
        elif args.command == "audit":
            result = {"events": service.store.events(args.request_id)}
        else:
            result = apply_mock_policy_update(
                service, args.request_id, NetworkChange(args.sandbox, args.domain, args.port)
            )
    except ApprovalError as exc:
        result = {"error": exc.code}
    except ValueError as exc:
        result = {"error": "invalid_input", "message": str(exc)}
    except (OSError, sqlite3.Error):
        result = {"error": "approval_service_unavailable"}
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 1 if "error" in result or result.get("applied") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
