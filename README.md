# OpenShell–Keyper Integration Lab

Exploring human approval for OpenShell sandbox network policy changes,
with Keyper used to verify the approver's identity.

## Status

Early feasibility exploration. No working integration has been verified.
This is an independent experiment and does not imply NVIDIA endorsement
or an official partnership.

## Goal

Evaluate whether a sandbox network policy change can be allowed only
after an authorized person verifies their identity through Keyper
and approves the specific change.

## Proposed workflow

1. An operator requests a network policy change for a sandbox.
2. An approver verifies their identity through Keyper.
3. An integration service records approval for that specific change.
4. An OpenShell extension checks the approval before allowing the change.
5. The system records the decision for audit purposes.

The exact OpenShell operation and extension point remain to be verified.

## Responsibilities

- Keyper: verify the approver's identity.
- Integration service: check approval authority and bind approval to
  the sandbox, exact change, expiration time, and one-time use.
- OpenShell: enforce the policy through its supported interfaces.

Identity verification alone does not constitute approval.

## First milestone

Use a mock approval service to validate the OpenShell integration point.
Connect Keyper after both interfaces have been confirmed.

## Acceptance criteria

- A valid approval permits the exact requested change.
- Missing or expired approval is rejected.
- Approval for a different sandbox or change is rejected.
- Reusing an approval is rejected.
- Approval service failure prevents the protected change.
- Decisions are recorded without credentials or secrets.

## Open questions

- Which OpenShell API updates the relevant network policy?
- Can a supported extension validate that operation before it commits?
- Which Keyper interface supports this verification flow?
- How will approver permissions and approval records be validated?

## References

- OpenShell: https://github.com/NVIDIA/OpenShell
- Gateway Interceptors:
  https://docs.nvidia.com/openshell/extensibility/gateway-interceptors
- Contribution guidelines:
  https://github.com/NVIDIA/OpenShell/blob/main/CONTRIBUTING.md
