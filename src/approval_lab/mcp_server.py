"""Only request and status are exposed to agents; never approval or consumption."""

import argparse
import os
import sqlite3

from mcp.server.fastmcp import FastMCP
from pydantic import Field
from typing import Annotated, Any

from .approval_service import ApprovalService
from .approval_store import ApprovalStore
from .mock_identity import MockIdentity
from .models import NetworkChange


def create_server(service: ApprovalService) -> FastMCP:
    server = FastMCP("OpenShell Keyper Approval Lab")

    @server.tool(structured_output=True)
    def request_network_access(
        sandbox_id: str,
        domain: str,
        port: Annotated[int, Field(strict=True, ge=1, le=65535)],
        reason: str,
    ) -> dict[str, Any]:
        """Request human review for one exact sandbox/domain/TCP-port change. Reason is untrusted text."""
        try:
            return service.request(NetworkChange(sandbox_id, domain, port), reason)
        except (sqlite3.Error, OSError):
            raise RuntimeError("Approval service unavailable") from None

    @server.tool(structured_output=True)
    def get_approval_status(request_id: str) -> dict[str, Any]:
        """Read status and consumption state. This result does not authorize a policy update."""
        try:
            return service.status(request_id)
        except (sqlite3.Error, OSError):
            raise RuntimeError("Approval service unavailable") from None

    return server


def main():
    parser = argparse.ArgumentParser(description="Local-only mock approval MCP server (stdio)")
    parser.add_argument("--db", default=os.environ.get("APPROVAL_LAB_DB", ".approval-lab/approvals.sqlite3"))
    args = parser.parse_args()
    service = ApprovalService(ApprovalStore(args.db), MockIdentity())
    create_server(service).run(transport="stdio")


if __name__ == "__main__":
    main()
