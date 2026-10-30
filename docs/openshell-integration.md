# OpenShell integration: verified boundary and next steps

Update: the optional [OpenShell bridge](openshell-bridge.zh-TW.md) now implements
the gRPC client/interceptor and separate agent/Keyper operator MCP interfaces.
The milestones below describe the original mock and remaining live deployment
questions. The subsequent [real v0.1.6 validation](live-validation.zh-TW.md)
now verifies gateway acknowledgement, runtime policy activation and network access.

2026-10-29: a pinned upstream source probe and local environment check are now
available. See the [verification record and Keyper requirements](integration-verification.zh-TW.md).
Run `uv run --locked python -m approval_lab.openshell_probe` to reproduce the
source-shape checks. Live gateway integration remains unverified.

## Milestone 1: implemented locally

The reference operation is one additive `network.allow` rule, bound to a
sandbox ID, ASCII DNS hostname and TCP port. The lab has no OpenShell dependency,
does not alter its source code, and does not apply a real network policy.

```mermaid
sequenceDiagram
    participant Agent
    participant MCP
    participant Service as Approval service / SQLite
    participant Human as Mock operator CLI
    participant Adapter as Mock policy adapter
    Agent->>MCP: request_network_access(sandbox, domain, port, reason)
    MCP->>Service: Persist exact pending change + expiration
    MCP-->>Agent: request_id, pending
    Human->>Service: Authenticate mock identity + decide
    Agent->>MCP: get_approval_status(request_id)
    MCP-->>Agent: Status only; no authorization capability
    Adapter->>Service: Atomically check and consume exact approval
    Service-->>Adapter: Consumed or rejected
    Adapter-->>Agent: Simulated applied=true only after success
```

MCP intentionally exposes no approve, deny, consume, or policy-update tool.
The policy adapter checks storage directly through the approval service; it
does not accept the agent's report, a prior status response, or a boolean
`approved=true` as authority.

## What the official OpenShell documentation establishes

Reviewed reference: [Gateway Interceptors](https://docs.nvidia.com/openshell/extensibility/gateway-interceptors).

- Interception takes place after gateway authentication.
- `validate` may allow or deny a proposed operation before its handler runs.
- Only explicitly allowed unary mutation RPCs can be intercepted.
- `post_commit` observes a successful response; it cannot block that commit.
- The documented deployment supports `failure_policy = "fail_closed"` and
  operator-controlled `binding_policy = "allowlist"` or `"exact"`.

These interfaces support investigating an external approval checker. They do
not, by themselves, verify a working integration for this repository.

## Milestone 2: integration questions still open

Record an exact OpenShell version and source commit before implementing:

1. Identify the policy-update RPC, confirm it is interceptable, and capture a
   sanitized evaluation payload including available current state.
2. Bind to the final validated mutation, not an earlier patch that another
   interceptor can change. Include the full normalized change, policy revision,
   sandbox, tenant and authenticated requester as needed by the real API.
3. Find a supported channel for an approval reference. Do not assume arbitrary
   request fields or metadata reach the interceptor.
4. Authenticate and authorize gateway-to-approval-service calls. An agent must
   not possess access to the operator decision API or database.
5. Define consume/commit semantics. This lab consumes before a simulated update;
   a failure after consumption burns the approval. The real gateway transaction
   and the SQLite transaction are not one atomic transaction. Decide how retries,
   operation IDs, reservations and post-commit observations work; never restore
   an approval merely because an untrusted caller reports a failed update.
6. Test gateway service outages, timeouts, restarts, RPC binding mistakes,
   modified policy contents and concurrent operations with fail-closed behavior.
7. Verify that alternative policy-update paths cannot bypass the check.

Do not copy a hypothetical RPC name or gateway configuration from this lab;
there is no verified configuration yet.

## Replacing the mock identity adapter with Keyper

`IdentityAdapter.authenticate` is the replacement boundary. A real implementation
must verify a server-trusted assertion and return the verified subject and
operator-authorized roles. It must establish issuer, audience, validity,
challenge/session binding, replay protection and a revocation/reauthentication
policy appropriate to the chosen Keyper interface.

The operator must see the sandbox, canonical target, port, operation and expiry
before deciding. The assertion must be bound to that decision. Request reasons
are agent-supplied text and never grant approval authority.

No Keyper endpoint, token format, assertion validation or deployment has been
verified here. The current mock accepts known local names and provides **no
authentication**. Treat anyone able to run the CLI or edit the database as a
trusted test operator. This is not isolation from a local agent or local attacker.

## Scope limits

The local database is authoritative but not tamper-evident. It contains request
reasons and identities; do not enter credentials or confidential material.
The stdio server has no network listener, tenant authorization, requester identity
verification, request quota or production audit sink. Gateway policy approval
also does not authorize sensitive operations inside an enterprise API.
