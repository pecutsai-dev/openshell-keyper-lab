# Approval review prototype (Issue #6)

A clickable prototype of a human review screen for a policy-change request. The scenario: an operator already approved port 443, and the agent now asks for port 8443.

**Result type: mock.** This is not a protocol test or a real OpenShell runtime test.

## Run it

Browsers block pages from loading local files directly, so serve the folder:

```bash
cd prototypes/approval-review
python3 -m http.server 8000
```

Then open <http://localhost:8000>.

## What the reviewer sees

- **Change banner:** "1 change: Port 443 → 8443", computed by comparing the new request with the original approval.
- **Side by side:** the original approval (read-only) on the left and the new request on the right. On narrow screens they stack, with the new request first.
- **Changed fields highlighted** with the old value ("was 443"). The new expiry and policy version always stay visible.
- **Unchanged fields collapsed** under "6 fields unchanged from original approval" (one click to expand).
- **Agent's explanation** in a separate dashed box, labeled unverified. It is rendered as plain text only.
- **Approve and Deny** as real `<button>` elements with equal size and weight. The Approve button states the exact operation (`/usr/bin/curl → api.example.com:8443`, sandbox and deadline), built only from verified fields.
- **All five states** (pending, approved, denied, expired, consumed) can be shown with the demo selector.

## Design choice: reducing approval fatigue

When a request is nearly identical to an approved one, the screen leads with only the difference, so the reviewer doesn't re-read every field to find one changed number.

**Tradeoff:** collapsed fields are easier to skip. To limit that, the page compares every scope field each time it loads. Only exact matches collapse, and any field that differs is always shown and highlighted.

## What's mocked

- All data and identities (see [`fixtures/README.md`](fixtures/README.md)).
- Approve and Deny only change what the page displays. Nothing is sent anywhere, and refreshing resets it.
- No backend, no Keyper connection, no gateway or OpenShell. No shared core modules are changed.
- The demo state selector exists only for the demo. It is not part of a real reviewer screen.

## Accessibility

- Keyboard: Tab reaches the fold-out, Approve, and Deny in order. Enter or Space activates them. After a decision, focus moves to the result.
- Visible focus outline on every interactive element.
- Changes are marked with text ("CHANGED", "was 443"), not color alone.
- Decisions are announced to screen readers.
