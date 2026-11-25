# Fixtures

All data in this folder is **synthetic**. No real identities, hosts, credentials or approval records.

## Files

| File | What it represents |
|---|---|
| `req-0031.json` | The original approval: port 443, status `approved` |
| `req-0042-pending.json` | The new request: port 8443, waiting for a decision |
| `req-0042-approved.json` | The same request after a reviewer approved it |
| `req-0042-denied.json` | The same request after a reviewer denied it |
| `req-0042-expired.json` | The same request after its deadline passed with no decision |
| `req-0042-consumed.json` | The same request after its approval was applied once |

`req-0042` points to `req-0031` through `replaces_approval`. The review page loads both files and compares their `verified` fields to find what changed. The difference is computed, never stored.

## Schema

| Field | Meaning |
|---|---|
| `id` | Request identifier |
| `status` | One of the statuses below |
| `replaces_approval` | ID of the earlier approval this request should be compared with, or `null` |
| `verified` | Facts checked by the system: requester, gateway, workspace, sandbox, destination, port, executable, policy version, expiry |
| `untrusted.agent_reason` | Free text written by the agent. **Never a verified fact.** Displayed as plain text only. |
| `decided_by` | (approved / denied / consumed only) Mock operator who made the decision |
| `decided_at` | (approved / denied / consumed only) When the decision was made |

## Statuses

- **pending**: submitted and waiting for a human decision.
- **approved**: a human allowed it, and it has not been applied yet. Approval does not mean the command ran successfully.
- **denied**: a human refused it.
- **expired**: past `expires_at` with no decision.
- **consumed**: approved and already applied once, so it cannot be reused.

## A note on `expires_at`

The lab's mock requests expire five minutes after creation. The times in these fixtures (for example `2026-11-24T17:00:00Z`) are **fixture display data**: a demo approval window chosen so the prototype doesn't expire mid-demo. They aren't real lab timing.
