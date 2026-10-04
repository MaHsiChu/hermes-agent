# Hermes Mobile

Chinese-first React PWA for the Remote Sessions relay. This is a separate workspace;
it continues existing PC sessions and does not create or impersonate a native session.
The wire contract is [`docs/remote-control/PROTOCOL.md`](../../docs/remote-control/PROTOCOL.md).

## Run

From the repository root, with the repository's supported Node/npm versions:

```sh
npm install
npm run dev --workspace apps/mobile
npm run typecheck --workspace apps/mobile
npm test --workspace apps/mobile
npm run build --workspace apps/mobile
```

Development listens on `127.0.0.1:5174`, forwarding `/api/remote` and `/auth` to
`http://127.0.0.1:8787`. `RELAY_TARGET` can select another local relay. Configure
the relay's public URL and registered OIDC callback to the **browser-facing origin**;
Origin validation is deliberately not bypassed. For deployment, set the relay's
`static_dir` to this workspace's `dist` directory and serve everything from the same
HTTPS origin. The relay must have a real OIDC provider configured before login works.
There is no development login route in this app.

The installable manifest uses a scalable icon. The versioned service worker caches
only the generic static shell and fingerprinted JS/CSS. It never caches `/auth`, API
responses, attachments, or a rendered user-specific page. On an offline cold start,
the shell can load but history requires authentication and access to the relay.
While the page remains open, already loaded history stays visible. A disconnected PC
can still have relay-cached history; this is distinct from phone network connectivity.

## Behavior

- Newest history page loads first, displayed chronologically and positioned at the
  most recent message. “加载更早消息” prepends older pages while preserving the reading
  position. Message IDs and revisions, including tombstones, determine identity.
- Source/profile/status/device/archive filters apply on the server before pagination.
- Every execution action is capability-gated. Send, queue and steer remain distinct.
  Stop is a request; backend acceptance is not execution completion.
- Drafts and one unresolved immutable command envelope persist per account in browser
  storage. Edits made while sending are retained. Reconnect never sends a draft.
  Explicit retry first queries the receipt and reuses the original ID and payload only
  when the relay returns 404. `delivery_uncertain` requires review in the original PC
  session and is never automatically resubmitted.
  A confirmed receipt is archived when the user explicitly starts another operation;
  up to ten recent receipts remain inspectable. An acknowledged send therefore does
  not block answering a new clarification or approval.
- Account changes/logout abort old requests, close subscriptions, clear in-memory history
  and all account-scoped drafts/commands. Only public static assets remain cached.
- Pairing preserves its opaque ID through the OIDC callback and requires explicit source
  checkboxes plus the PC's code. Device credentials never enter mobile JavaScript.
- HTML is sanitized, remote Markdown images are removed, and images are fetched only by
  an authorized opaque attachment ID scoped to the current session.

## Tests and limits

Vitest exercises revision/tombstone merging, in-flight draft edits, receipt-before-retry,
account-switch races, native fetch invocation, event gaps/deduplication/bounded coalescing,
stale approvals, safe rendering and reading-position restoration.

`npm run test:browser --workspace apps/mobile` contains Playwright scenarios using a
**disposable real relay** on loopback ports 8791/8792, RSA-signed test OIDC, PKCE, server
cookies and real Bridge WebSockets. It requires the repository Python virtual environment
with Remote Sessions dependencies, a built `dist`, and Playwright Chromium. Set
`REMOTE_TEST_PYTHON` to override the detected Python path. Test-only PC execution is
synthetic. These are not Keycloak deployment, personal-account or real-model E2E tests.
The fixture must never be deployed publicly. During Codex sessions requiring CUA-only
browser interaction, keep these tests as source and use the approved CUA verification.

Browser tests cover 360px layout, complete long outputs and older pages, tombstones,
expired approvals, offline drafts/reconnect, ambiguous POST receipt recovery, tenant
switch/logout, and explicit pairing consent after signed login.

The relay currently runs one worker. Native adapter capabilities determine which controls
are usable; unavailable Codex/Claude operations are not simulated. Mobile does not promise
execution or approval support merely because a Bridge is connected.
