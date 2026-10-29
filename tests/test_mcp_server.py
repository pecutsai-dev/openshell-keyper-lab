import asyncio
import json
import subprocess
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from approval_lab.approval_service import ApprovalService
from approval_lab.approval_store import ApprovalStore
from approval_lab.mock_identity import MockIdentity
from approval_lab.mock_policy_update import apply_mock_policy_update
from approval_lab.models import NetworkChange


def test_real_mcp_stdio_request_operator_approval_and_consumption(tmp_path):
    db = tmp_path / "protocol.sqlite3"

    async def scenario():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "approval_lab.mcp_server", "--db", str(db)],
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                tools = await client.list_tools()
                assert {t.name for t in tools.tools} == {
                    "request_network_access", "get_approval_status"
                }
                result = await client.call_tool("request_network_access", {
                    "sandbox_id": "sandbox-a", "domain": "api.example.com", "port": 443,
                    "reason": "Read the example API",
                })
                assert not result.isError
                record = result.structuredContent
                assert record["status"] == "pending"
                request_id = record["request_id"]
                service = ApprovalService(ApprovalStore(db), MockIdentity())
                change = NetworkChange("sandbox-a", "api.example.com", 443)
                assert not apply_mock_policy_update(service, request_id, change)["applied"]
                # Human path is a separate process, never an MCP approve tool.
                operator = subprocess.run([
                    sys.executable, "-m", "approval_lab.cli", "--db", str(db),
                    "approve", request_id, "--identity", "demo-approver",
                ], capture_output=True, text=True, check=True)
                assert json.loads(operator.stdout)["status"] == "approved"
                status = await client.call_tool("get_approval_status", {"request_id": request_id})
                assert status.structuredContent["status"] == "approved"
                assert not status.structuredContent["consumed"]
                assert apply_mock_policy_update(service, request_id, change)["applied"]
                after = await client.call_tool("get_approval_status", {"request_id": request_id})
                assert after.structuredContent["consumed"]
                assert not apply_mock_policy_update(service, request_id, change)["applied"]
                invalid = await client.call_tool("request_network_access", {
                    "sandbox_id": "sandbox-a", "domain": "api.example.com", "port": True,
                    "reason": "A bool must not be treated as port 1",
                })
                assert invalid.isError
                missing = await client.call_tool("get_approval_status", {"request_id": "missing"})
                assert missing.isError

    asyncio.run(scenario())
