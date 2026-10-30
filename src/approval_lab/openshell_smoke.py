"""Drive both MCP connections against an operator-configured real gateway."""

import argparse
import asyncio
import getpass
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run(args):
    def parameters(role, extra=()):
        return StdioServerParameters(command=sys.executable, args=[
            "-m", "approval_lab.openshell_mcp", role, "--config", str(args.config.resolve()),
            "--db", str(args.db.resolve()), *extra])
    async with stdio_client(parameters("agent")) as (reader, writer):
        async with ClientSession(reader, writer) as agent:
            await agent.initialize()
            response = await agent.call_tool("request_policy_update", {
                "operation": json.loads(args.operation.read_text(encoding="utf-8-sig")),
                "reason": args.reason})
            if response.isError:
                raise RuntimeError(str(response.content))
            record = response.structuredContent
            request_id = record["request_id"]
            print(json.dumps(record, indent=2))
            if not args.submit:
                print("Request created only; no approval or gateway mutation attempted.")
                return
            extra = ["--local-mock-keyper"] if args.local_mock_keyper else ["--keyper-verifier", args.keyper_verifier]
            async with stdio_client(parameters("operator", extra)) as (r, w):
                async with ClientSession(r, w) as operator:
                    await operator.initialize()
                    review = await operator.call_tool("get_policy_review", {"request_id": request_id, "approve": True})
                    if review.isError:
                        raise RuntimeError(str(review.content))
                    print(json.dumps(review.structuredContent, indent=2))
                    assertion = "demo-approver" if args.local_mock_keyper else getpass.getpass("Keyper assertion bound to this challenge: ")
                    decision = await operator.call_tool("decide_policy_update", {
                        "request_id": request_id, "approve": True, "assertion": assertion})
                    if decision.isError:
                        raise RuntimeError(str(decision.content))
            result = await agent.call_tool("submit_approved_policy", {"request_id": request_id})
            if result.isError:
                raise RuntimeError(str(result.content))
            print(json.dumps(result.structuredContent, indent=2))
            print("Gateway acknowledged; verify runtime policy load and network connectivity separately.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--operation", required=True, type=Path)
    parser.add_argument("--reason", default="Minimal OpenShell integration verification")
    parser.add_argument("--submit", action="store_true", help="Actually approve and call the configured gateway")
    verifier = parser.add_mutually_exclusive_group()
    verifier.add_argument("--local-mock-keyper", action="store_true")
    verifier.add_argument("--keyper-verifier")
    args = parser.parse_args()
    if args.submit and not (args.local_mock_keyper or args.keyper_verifier):
        parser.error("--submit needs --keyper-verifier or explicit --local-mock-keyper")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
