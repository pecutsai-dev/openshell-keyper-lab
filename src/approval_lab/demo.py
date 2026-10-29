"""Reproducible demo using real MCP stdio and a separate mock operator CLI."""

import asyncio
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def operator(db, *args):
    result = subprocess.run(
        [sys.executable, "-m", "approval_lab.cli", "--db", str(db), *args],
        capture_output=True, text=True,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


async def demo(db):
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "approval_lab.mcp_server", "--db", str(db)]
    )
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as client:
            await client.initialize()
            tools = await client.list_tools()
            print("MCP tools:", ", ".join(tool.name for tool in tools.tools))
            response = await client.call_tool("request_network_access", {
                "sandbox_id": "sandbox-demo", "domain": "api.example.com", "port": 443,
                "reason": "Demonstrate human review for example API access",
            })
            if response.isError:
                raise RuntimeError(str(response.content))
            request_id = response.structuredContent["request_id"]
            assert response.structuredContent["status"] == "pending"
            print("1. MCP request:", request_id, "pending")
            flags = ["--sandbox", "sandbox-demo", "--domain", "api.example.com", "--port", "443"]
            before = operator(db, "apply", request_id, *flags)
            assert before["reason"] == "not_approved"
            print("2. Before approval:", before)
            denied_identity = operator(db, "approve", request_id, "--identity", "demo-viewer")
            assert denied_identity["error"] == "approver_not_authorized"
            print("3. Unauthorized mock identity:", denied_identity)
            accepted = operator(db, "approve", request_id, "--identity", "demo-approver")
            assert accepted["status"] == "approved"
            print("4. Separate operator CLI: approved by", accepted["approver_id"])
            status = await client.call_tool("get_approval_status", {"request_id": request_id})
            assert status.structuredContent["status"] == "approved"
            print("5. MCP status:", status.structuredContent["status"])
            mismatch = operator(db, "apply", request_id, *flags[:-1], "8443")
            assert mismatch["reason"] == "change_mismatch"
            print("6. Different port:", mismatch)
            first = operator(db, "apply", request_id, *flags)
            assert first["applied"]
            print("7. Exact simulated update:", first)
            replay = operator(db, "apply", request_id, *flags)
            assert replay["reason"] == "already_consumed"
            print("8. Replay:", replay)
            print("PASS: no real network rule or OpenShell policy was changed.")


def main():
    with TemporaryDirectory(prefix="approval-lab-") as directory:
        asyncio.run(demo(Path(directory) / "approvals.sqlite3"))


if __name__ == "__main__":
    main()
