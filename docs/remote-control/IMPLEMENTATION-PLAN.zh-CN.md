# Remote Sessions Implementation Plan

> For agentic workers: use subagent-driven-development with focused implementation and independent review. Keep the status document current; do not stop between authorized tasks.

**Goal:** Restore Hermes locally and build an authenticated mobile remote client for existing PC sessions, including full available history, live execution, approvals, clarification, interruption, and attachments.

**Architecture:** A separately deployed FastAPI relay holds account/device/session copies and durable command receipts. An outbound Python Bridge attaches to the already-running Hermes REST/JSON-RPC backend and optional local Session Hub. A React/TypeScript PWA accesses only the relay. The PC remains execution authority.

**Tech Stack:** Existing Python 3.11/Node 24 workspace; FastAPI, SQLAlchemy (SQLite localhost development and PostgreSQL deployment), Authlib OIDC with Keycloak deployment, React/TypeScript/Vite. Additional packages stay in the remote subsystem, with pinned/bounded declarations and lockfile.

## Global constraints

- Read root AGENTS.md and relevant area instructions; tests run through scripts/run_tests.sh, never bare pytest.
- Preserve byte-stable conversation prompts, role alternation, original session identity and profile ownership. No new model core tools or automatic conversation creation.
- Never expose unrestricted backend RPC or write native databases to inject messages. Device/profile/engine/session ownership is checked at every hop.
- Product login is real OIDC using a mature library; no production development-login bypass, hardcoded user or shared account token.
- User explicitly authorized recovery and implementation. Local reversible setup may proceed; no public exposure without actual server/domain context, no uploading existing sessions until device pairing explicitly names allowed sources.
- All command requests have persistent request_id and payload hashes. Same ID/different payload conflicts. Interrupted dispatch becomes delivery_uncertain and is never blindly retried.
- Keep synchronous command acceptance distinct from execution completion. Offline PC means no new execution; user draft remains local.
- Mobile approval only answers an actual pending request, scoped to the original session; recheck offered choices and expiration. Secret/sudo prompts stay local. First valid dual-client response wins.
- Browser sessions: HttpOnly cookies, CSRF and Origin checks, revocable server-side sessions. Device credentials stored separately, hashed on relay, revocable immediately including sockets. No raw token logs.
- Bounded queues, pagination, incremental event sync, snapshot repair after restart/gap. No full-history retransmit on each token.
- All capabilities report supported/unavailable/unsupported with reasons; Codex/Claude approval and interrupt remain unavailable unless actual adapter supports them.
- The user subsequently requested committing all implementation and handoff changes on codex/remote-sessions. Preserve the worktree and original checkout; pushing and merging are separate actions. Avoid modifying unrelated code.

## Task 1: Restore local application and preserve baseline

Owner: controller. Local setup belongs in ignored .local-runtime and .local-tools; no committed credentials.

- [x] Install locked Python dependencies in original checkout, compatible project-local npm, root npm ci.
- [x] Configure Hub initially with isolated sources; run scripts/run_tests.sh extensions/session-hub and existing frontend logic tests, then build/install plugin to a new explicit Hermes home.
- [x] Build desktop, start it against that checkout/home and verify actual backend health and plugin routes. Provide reusable local launch/stop commands.
- [x] Connect local history sources only after tests; bind Codex only using current authorized App context. Do not send test messages to unrelated conversations.
- [x] Record command output and clear distinction between app launch and real model execution.

## Task 2: Authenticated relay, durable store and PC Bridge

Owner: implementation subagent. Files owned: remote_control/**, tests/remote_control/**, deploy/remote-control/**, docs/remote-control/PROTOCOL.md and AUTH-ADR.md. Do not edit apps/mobile or core unless report proves a required missing generic seam first.

Interfaces must be finalized in PROTOCOL.md before UI task starts:

```text
GET /api/remote/me -> {user:{id,name}|null,csrf_token,login_url}
GET /auth/login ; GET /auth/callback ; POST /auth/logout
GET /api/remote/devices -> {devices:[{id,name,online,last_seen,backends}]}
POST /api/remote/pairings -> {pairing_id,user_code,device_code,verification_uri,expires_in}
POST /api/remote/pairings/{pairing_id}/approve -> {approved:true} (logged-in, CSRF; explicit allowed sources)
POST /api/remote/pairings/{pairing_id}/exchange -> {status,device_id?,device_token?} (device_code; one-time claim)
DELETE /api/remote/devices/{id} -> {revoked:true}
GET /api/remote/sessions?device_id=&engine=&profile=&q=&archived=&cursor=&limit= -> {sessions,next_cursor}
GET /api/remote/sessions/{id} -> {session,online,capabilities,sync,pending_requests}
GET /api/remote/sessions/{id}/messages?cursor=&limit= -> {messages,next_cursor,sync}
POST /api/remote/sessions/{id}/commands -> {request_id,state,...} body {request_id,operation,payload}
GET /api/remote/commands/{request_id} -> {request_id,state,result?,error?}
POST /api/remote/sessions/{id}/attachments -> {id,name,mime,size}
GET /api/remote/sessions/{id}/attachments/{attachment_id} -> bytes (ownership enforced)
WS /api/remote/events (authenticated browser cookie + exact Origin; subscription/session/cursor frames)
WS /api/remote/bridge (Authorization Bearer device_token; distinct protocol)
```

- [x] Create failing behavior tests for tenant/device/source isolation, pairing expiry/claim/revocation, payload idempotency and uncertain dispatch recovery using real temp SQL databases and ASGI/network boundaries.
- [x] Implement focused config/store/auth/routers/protocol modules. Use OIDC code + PKCE, state and nonce via Authlib. Persist web login sessions in DB; no secret token storage in browser JS. API starts fail-closed if auth missing; health/configuration diagnosis still usable.
- [x] Implement pairing CLI with browser verification and explicit backend/profile scope disclosure, consent gate and device token file. Never bind all source directories implicitly.
- [x] Implement Bridge that ONLY connects to configured existing Hermes backend URL/token/profile. Use existing REST list/messages (full pagination and include_compacted) and /api/ws session.resume lazy/omit_messages + events.since. Preserve stored/runtime ID mapping and current source rather than changing client identity. Event readers must not block while awaiting RPC replies.
- [x] Add outbound relay reconnect, stable device identity, durable local receipts and one-writer per session. Reject expired/foreign commands locally. Query receipt before resending; side effects with missing ACK become uncertain.
- [x] Implement send/queue/steer/interrupt/approval/clarify through real gateway contracts. Validate server request choices and ownership using live snapshots. Read actual request cancellation and completion events. Exclude secret values and token-bearing fields from persisted history/events.
- [x] Snapshot initial metadata and recent history first, then complete older pages incrementally with resumable sync. Stable message IDs/revisions and tombstones prevent duplicates/resurrection. Sync all explicitly allowed profiles/backends, including archived sessions. No auto-execution while offline.
- [x] Add Hub adapter using existing local service and readonly normalization. History and send are real capabilities; unavailable approvals/interrupt explain why. Do not fake history or silently fall back to new CLI sessions.
- [x] Transfer attachments by opaque ID with per-session ownership, MIME/size limits and authorized local paths. If a backend cannot handle a type, reject explicitly. No arbitrary remote URL/path fetch endpoint.
- [x] Add executable entry points `python -m remote_control.server --config <yaml>` and `python -m remote_control.bridge --config <yaml>` and pairing subcommand. Behavioral config in YAML; secrets through restricted files/environment references.
- [x] Provide pinned Keycloak/PostgreSQL/Caddy deployment, migrations, backup/restore commands, .env.example without real values and Windows/macOS startup instructions. Local SQLite development remains explicit, not a production PostgreSQL claim.
- [x] Run focused canonical tests, record red/green evidence, write implementation report. Obtain independent spec+quality review and fix findings before next dependent task.

## Task 2B: Bind images to the originating request

The native staging API was verified to share pending images across clients. Even a text-only remote submit can consume desktop staging. Extend the existing generic RPC before declaring remote send/upload safe.

- [x] Add an optional request-owned image list to `prompt.submit`; explicit `[]` must preserve desktop pending images. Validate before turn side effects and reuse existing explicit `image_paths` plumbing.
- [x] Preserve ownership through busy queues, inline/isolated execution and failure cleanup. Retain accepted images needed by native history.
- [x] Advertise support through `gateway.capabilities`, regenerate shared contracts, and require affirmative capability in the Bridge. Old backends must report unavailable instead of silently using shared staging.
- [x] Verify concurrent staging, queue immutability, invalid input and profile isolation using real imports/temp homes, then run canonical covering tests and independent review.

## Task 3: Mobile PWA

Files: apps/mobile/** and only necessary root lock updates. Consume Task 2 PROTOCOL.md exactly; use existing workspace versions and native fetch/WebSocket. After the protocol is fixed, this separate frontend scope may run in parallel with Python backend validation; both must pass review before final integration.

- [x] Create mobile workspace with responsive React/TypeScript application and installable manifest. Login screen, explicit device pairing consent, device list/revoke, session list with source/profile/state filters and pagination, full session transcript and details.
- [x] Transcript renders Markdown/code, tool inputs/results, diffs and attachments; escape untrusted HTML. Long outputs can collapse without discarding text. Preserve stable message IDs and revisions.
- [x] Composer saves per-account/session draft, never auto-sends offline drafts. Operation selector distinguishes queue and steer; supports image attachment. Stable request IDs across uncertain network retry; GET receipt before new send.
- [x] Pending approval/clarify cards show original command/question, allowed choices and stale status; cannot answer expired/unsupported/secret requests. Stop shows requested until execution authority confirms.
- [x] Event subscription recovers snapshots after gaps and browser foregrounding; bounded buffers. PC-offline view shows cached relay history and last sync, disables unsupported actions.
- [x] Use safe-area/keyboard-aware 360px layout, accessible touch targets, localized Chinese status text. Service worker caches static shell only, never authenticated session data. Logout clears all account-scoped browser caches/drafts/subscriptions.
- [x] Add meaningful model and component tests and Playwright browser tests for real relay interactions, offline/reconnect, stale approval, tenant switch, long history and mobile viewport.
- [x] Build/typecheck, run tests, review and address findings.

## Task 4: Real integration and delivery

Owner: controller plus independent final reviewer.

- [x] Start actual relay, OIDC provider, bridge and Hermes backend in isolated runtime; attach two clients to same session.
- [x] Verify history continuity and live request/answer with real gateway imports. If model credentials unavailable, report actual infrastructure E2E separately from model-driven execution and continue all other tests.
- [x] Prove duplicates, lost ACK, restart/reconnect, tenant isolation, revocation and approval competition. Do not mock host OS.
- [x] Verify mobile UI in browser at narrow viewport, desktop actual session continuity through native RPC/REST and Hub routes. Keep safe local services running with clear URLs/start/stop recipe. Native desktop UI automation is unavailable; actual execution/history and plugin routes were checked through their live APIs.
- [x] Final security/quality review of complete diff. Resolve all important findings and rerun covering tests. Final independent verdict: Approved, I1–I6 and M1–M2 closed.
- [x] Update IMPLEMENTATION-STATUS.zh-CN.md with real evidence, commands, URLs, missing external validation (actual phone/remote Mac/public network as applicable). Never mark full M0–M4 completion on mock results.
