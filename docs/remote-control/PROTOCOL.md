# Remote Sessions protocol v1

The PWA and relay share one origin. All timestamps are Unix seconds. IDs are opaque strings; never construct native paths from an ID. JSON errors use `{detail: string}` and HTTP 400/401/403/404/409/410/413/415/422/503. An unavailable or foreign resource returns 404. Every authenticated response is `Cache-Control: no-store`. No CORS is enabled.

## Identity and pairing

`GET /api/remote/me` → `{user: {id,name}|null, csrf_token: string|null, login_url: '/auth/login'|null}`. Navigate the browser to login_url. OIDC code + S256 PKCE + nonce/state validation happen server-side; the browser receives only an opaque HttpOnly session cookie. All cookie-authenticated mutations require exact `Origin` and `X-CSRF-Token` from `/me`. `POST /auth/logout` → `{logged_out:true}` revokes the local login and closes its sockets. Clear account-scoped drafts/cache and routing on logout/account change. Logout does not terminate the identity provider's SSO session.

`POST /api/remote/pairings` is the unauthenticated PC initiation endpoint: `{name,sources:[Source]}` → `{pairing_id,user_code,device_code,verification_uri,expires_in}`. `Source = {backend_id,profile,engine:'hermes'|'codex'|'claude'}`. The CLI opens `verification_uri`, currently `/pair?pairing_id=...`. Keep `device_code` on the PC; do not put it in a URL.

`GET /api/remote/pairings/{pairing_id}` requires login and returns `{pairing_id,name,sources,expires_at}`. The pairing page displays the requested sources, asks for the user code shown on the PC, and lets the user explicitly select sources. Do not default to approving every source.

`POST /api/remote/pairings/{id}/approve` body `{user_code,allowed_sources:[Source]}` → `{approved:true}`. Nonempty subset only; CSRF required. `POST /api/remote/pairings/{id}/exchange` body `{device_code}` → `{status:'pending'}` or `{status:'approved',device_id,device_token,allowed_sources}`. Successful exchange is one-time; 409 on replay, 410 on expiry. Lost exchange response requires a new pairing (revoke the unused device). Never expose `device_token` to PWA JavaScript.

`GET /api/remote/devices` → `{devices:[{id,name,online,last_seen,backends:[Source]}]}`. `DELETE /api/remote/devices/{id}` → `{revoked:true}`. Revocation invalidates the credential and active Bridge socket immediately, and disconnects browser sockets so clients discard stale subscriptions. Copies remain stored but become inaccessible through ordinary APIs.

## Sessions and messages

`GET /api/remote/sessions?device_id=&engine=&profile=&q=&status=&archived=exclude|only|include&cursor=&limit=50` → `{sessions:[Session],next_cursor:string|null}`. Max limit 100. `status` optionally selects `idle|starting|waiting|working|streaming|resuming|unknown|completed|failed|interrupted`; SQL filtering happens before pagination. Missing native status matches unknown; never infer running from Bridge presence. Use returned opaque cursors. List ordering is descending updated_at then ID. A live refresh reconciles pages from the start through the already-loaded extent, preserving browsing depth and replacing the continuation cursor after deletions/reordering; an explicit filter change resets that extent.

`Session = {id,device_id,backend_id,profile,engine,native_session_id,title,archived,updated_at,revision,status?,source?,cwd?,online?}`. Extra source metadata may be present. The source locator is `(device_id,backend_id,profile,engine,native_session_id)`; mobile sends ONLY the public `id`.

`GET /api/remote/sessions/{id}` → `{session:Session,online:boolean,capabilities:Capabilities,sync:Sync,pending_requests:[Pending]}`.

`Capabilities` is a map for `history`, `send`, `queue`, `steer`, `interrupt`, `approval`, `clarify`, `attachments`. Each value is `{status:'supported'|'unavailable'|'unsupported',reason?:string}`. Only supported operations are enabled. Backend offline is distinct from Bridge online.

`Sync = {complete?:boolean,last_synced?:number,offset?:number,total?:number,error?:string,catalog_complete?:boolean,epoch?:string}`. Completeness means all available source pages copied, not that deleted/never persisted content can be recovered.

`GET /api/remote/sessions/{id}/messages?cursor=&limit=100&order=oldest` → `{messages:[Message],next_cursor,sync}`; maximum 500. `order=oldest` (default) walks forwards. `order=latest` selects the newest page first, still returns each page in chronological order, and its next_cursor walks to older pages (prepend them). Cursors bind session and direction; mixing either returns400. Keyset boundaries avoid duplicate older rows when new messages arrive. `Message = {id:string,revision:number,ordinal:number,role?:string,content?:string|array,blocks?:array,tool_calls?:array,tool_call_id?:string,timestamp?:number,deleted?:boolean,...}`. Hermes native message fields and Hub normalized blocks are retained, with sensitive fields redacted. Key rows by `(session_id,id)` and replace only with a newer revision; deleted rows are tombstones and remove their previous content. Do not treat message position as identity. Fetch all desired pages; long outputs are not silently truncated.

`Pending = {id,method:'approval'|'clarify',params:{...}}`. Approval params include `request_id`, `command`, `description`, `choices:['once'|'session'|'always'|'deny']`. Clarify has `{question,choices?,multi_select?}` or `{questions:[{qid,question,choices?,multi_select?}],answers?:{qid:string}}`. `answers` are already locked source answers. Other request kinds (sudo/secret/vault) remain local and are never answerable remotely. Re-fetch before displaying a pending card after reconnect; local authority rechecks the request at dispatch time.

## Commands and receipts

`POST /api/remote/sessions/{id}/commands` body `{request_id,operation,payload}` → HTTP 202 `{request_id,state,result?,error?}`. Request ID: 8–128 ASCII letters/digits/underscore/hyphen, preferably UUID. Same ID+same payload returns previous receipt; different payload returns 409. Reuse the ID after a network ambiguity, first querying `GET /api/remote/commands/{request_id}`. A 404 means no relay record. 409 offline does not enqueue anything; keep the draft local.

Operations:

| operation | payload | meaning |
|---|---|---|
| send | `{text,attachment_ids?:string[]}` | continue original session; rejects busy sessions |
| queue | `{text,attachment_ids?:string[]}` | explicitly queue next turn, never convert to steer |
| steer | `{text}` | existing agent steer contract |
| interrupt | `{}` | request stop; ACK is not completion |
| approval | `{pending_request_id,choice}` | respond to the exact still-open source request |
| clarify | `{pending_request_id,answer}` or `{pending_request_id,answers:{qid:string}}` | response to original request; no secrets |

`GET /api/remote/commands/{request_id}` → same receipt. States: `accepted` (relay durable), `dispatched`, `received` (PC durable), `acknowledged` (backend accepted operation, not execution completion), `response_submitted` (clarify has no winner acknowledgement in native wire), `completed`, `failed`, `delivery_uncertain`. `result` may include native `status` or Hub `job_id`. The session's live execution state is authoritative. A lost ACK or crash during side effects becomes delivery_uncertain, never automatic resend. Browser labels must keep acceptance and execution completion separate. Approval resolved=0 is stale/failed. First valid reply wins in the native backend.

## Attachments

`POST /api/remote/sessions/{id}/attachments` multipart field `file` → `{id,name,mime,size}`. CSRF required. Default 8 MiB; supported image formats PNG/JPEG/WebP/GIF are checked by decoded content, max 40 million pixels. At most five opaque attachment IDs per command. `GET /api/remote/sessions/{id}/attachments/{attachment_id}` returns authenticated bytes. The URL is scoped to both account and session. Never pass a local path or remote URL as an upload reference. Unsupported adapter capabilities must disable uploads. Source-local images may be unavailable when outside explicitly authorized attachment roots; show a reason, never fetch an arbitrary path/URL.

Hermes upload capability is available only when Task2B's native atomic image/busy-admission capabilities and upload limits are advertised. Older backends fail closed; Hub uploads remain unsupported. Authorized structured source `file:` image URLs and Hermes persisted whole-line `@image:<local path>` markers (bare or quoted) are exported as `{type:'attachment',kind:'image',id,name,mime,url,status:'available'}` content blocks. Caption text is retained; `[screenshot]` placeholder lines are removed only when an image marker is lifted. Unavailable source images carry `status:'unavailable',reason` without a local path proxy; local paths require explicit attachment_roots authorization. The original native transcript is unchanged.

## Browser events

`WS /api/remote/events` authenticates HttpOnly cookie and exact Origin. Server first sends `{type:'hello',protocol:1,cursor}`; cursor is the highest persisted event sequence for the current account's non-revoked devices and authorized sessions, or0 when empty. Cold start order: receive this barrier, repair detail/history, then send `{type:'subscribe',session_ids:[public IDs],cursor:hello.cursor}` (max32) → `{type:'subscribed',session_ids,cursor}`. Events created during repair have larger sequences and are delivered; old completion events before the barrier are not mistaken for new turns. A client resuming a preserved live projection may use its saved cursor, with gap handling below. Cursor is a relay-global monotonic integer; it conveys no authorization. Normal events: `{type:'event',cursor,session_id,event:{type,payload}}`. Types include `session.updated`, `command.updated` (refetch receipt), and `gateway.event` (native live event envelope). Deduplicate by cursor; preserve native event seq/epoch. A `{type:'gap',cursor,session_ids,reason}` requires replacing snapshots and transcripts before continuing. On foreground/reconnect always fetch `/me`, detail and current messages; never assume an event stream contains all history. Persisted SQL event stream survives relay restarts; native epoch changes trigger Bridge snapshot repair.

Forwarded Hermes `gateway.event` payloads carry `epoch` from the current native `session.events.since` response, the original native `seq`, and native runtime `session_id`. Live frames wait for this connection's verified native epoch; buffered frames from a disconnected reader are discarded before reconnect. When the native epoch or runtime ID differs from the durable watermark, Bridge fetches replay again from seq0 before forwarding. Deduplicate by public session/native runtime session_id/epoch/seq and reset native sequence tracking when epoch or runtime changes. Epoch identifies the backend process, while seq belongs to its runtime session; neither event text nor an invented Bridge epoch identifies a turn.

`session.updated` payload is `{revision,messages_changed:boolean}`. The additive flag is true only when this snapshot transaction actually inserts a message/tombstone or writes a higher message revision. Empty pages and skipped old/equal message revisions yield false, independently of session metadata revision. Clients always refresh detail; true (or a missing flag from an older relay/event) also repairs the already-loaded history range. False does not require rereading history. Native `gateway.event` token/stream events update live rendering and must not trigger a full loaded-history fetch per token; durable session updates and explicit gap/reconnect repair govern transcript reconciliation.

4401 means login required, 4403 authorization revoked/foreign scope, 4409 duplicate device Bridge. Reconnect within five seconds with bounded backoff; do not retry unauthorized sockets indefinitely. No service-worker caching of authenticated responses.

## PC Bridge wire (not a browser API)

`WS /api/remote/bridge` uses Authorization Bearer device credential; browser Origin is rejected. Welcome: `{type:'welcome',device_id,allowed_sources,protocol:1,upload_lease}`. Exactly one Bridge process per credential. The upload lease expires on disconnect/revocation and is replaced on reconnect. Heartbeats every 15 seconds: `{type:'heartbeat',sources:[{source:Source,online:boolean}]}`. 45 seconds without input closes the connection.

Snapshot pages: `{type:'snapshot',request_id,source:Source,session:{native_session_id,revision,title,...,capabilities},messages:[Message],sync:Sync,pending_requests:[Pending]}` → `{type:'snapshot.ack',request_id,session_id,native_session_id}`. Max 500 messages/2 MiB per frame. Session and message revisions are durable PC counters; old pages cannot resurrect newer tombstones.

Bridge splits pages by both count and UTF-8 encoded bytes, including recovered outboxes. An individual large message uses the same envelope and ACK via `POST /api/remote/bridge/snapshot` (64MiB request bound), authenticated by device Bearer plus `X-Remote-Bridge-Lease` from its active WebSocket. The lease preserves single-writer admission. A message above60MiB is explicitly listed in `sync.unavailable_message_ids` with `complete:false` and an error; its original stays on PC and other rows continue. No silent truncation or permanent outbox blockage. This bound is not a guarantee of arbitrary-size transcript completeness.

Commands arrive as `{type:'command',device_id,session_id,native_session_id,source,request_id,digest,operation,payload,expires_at}`. Digest covers canonical JSON `[public_session_id,operation,payload]`. Bridge checks own device, approved configured source, expiry, known native identity and hash, stores receipt BEFORE dispatch, and serializes writes per native session. `{type:'receipt.query',request_id}` → `{type:'receipt.status',request_id,state,digest}` lets reconnect reconcile without sending operations again. Receipt `{type:'receipt',request_id,digest,state,result?,error?}` → `{type:'receipt.ack',request_id}`. Bridge-local durable receipts survive lost acknowledgements.

`{type:'event',session_id,event:nativeEnvelope}` transfers only an already-authorized native session event. Secrets and token-bearing fields are stripped. Errors: `{type:'error',request_id?,error}`. PC downloads already scoped uploads using bearer `GET /api/remote/bridge/attachments/{session_id}/{attachment_id}`; no general file proxy exists.

Deployment runs exactly one relay worker and one Bridge per device; multi-process websocket routing is not implemented. PostgreSQL supports durability, not a claim of multi-worker coordination or tested capacity.

## Source evidence and explicit history repair

Hermes catalog reads advance by the native response's limited page window, not its expanded row count: native pages back-fill off-page pinned sessions. Identities are deduplicated across those pages. Hermes `updated_at` is native `last_active`, falling back to `started_at` then0 for unknown source activity. Relay resync never substitutes its wall clock for source activity; `sync.last_synced` records transfer time separately. Hub ISO timestamps and normalized Codex epoch-millisecond timestamps are converted to Unix seconds before publication.

Completed idle sessions use catalog evidence (source activity, message/tool counts and source location), rather than reading recent history each cycle or restarting full scans every five minutes. Native completion events, replay gaps, runtime/process changes and authoritative sequence rollback request a full reconciliation; scans remain paginated and byte-bounded. Hub uses a bounded `since`/revision/generation probe: unchanged history returns no records; a revision or generation change requests reconciliation. A new catalog identity gets an initial recent page and then all older pages. Reconnect may replay the durable local journal once to recover an interrupted upload; this is distinct from periodic source-history polling.

Some native in-place edits to old Hermes message content do not change `last_active` or message counts and emit no event. Similar edits to legacy rollout bytes without source metadata/revision evidence cannot be detected by an idle reader. Request an explicit audit instead of claiming automatic detection. With Bridge stopped, use its existing config and paired source identity:

```sh
python -m remote_control.bridge --config bridge.yaml repair --backend-id desktop --profile default --engine hermes --session-id ORIGINAL_NATIVE_ID
```

The command takes the same single-writer state lock as `run`, requires a configured and paired source and an already synchronized native session, and journals a repair request without reading or modifying native history. Start Bridge normally to perform that scan. This operation does not dispatch a model turn or retry a command. Repair requests arriving during an existing scan remain pending for another pass.

All live and replayed event envelopes are measured with RelayLink's actual compact UTF-8 JSON serialization. Above1,500,000 bytes, Bridge sends a bounded `history.repair` marker (`payload.reason=oversized_native_event`, `original_type` identifies the omitted event kind) and schedules the full persisted content through bounded snapshots/leased HTTP. The native event body is not truncated into an authoritative message and is not resent as an oversized frame on reconnect. The existing60MiB per-message bound and explicit unavailable-message disclosure still apply.

`gateway.event` carries native `epoch`, `session_id` and `replay_generation` intact, plus `bridge_generation`, an opaque **Bridge repair generation**, not a native epoch. Native `replay_generation` is created with each replay ring, carried on live events and returned atomically with replay events/latest_seq/truncated by `session.events.since`; bounded whole-ring eviction changes it even if the new sequence has already caught up past the old watermark. A changed native ring generation, authoritative replay `latest_seq` rollback or native runtime/process replacement changes Bridge's repair generation. A lower live seq alone triggers a replay check. After reset, Bridge validates subsequent live frames against the native ring to reject delayed old frames. Browser `history.repair`/generation changes clear ephemeral output and repair snapshots; native seq deduplication restarts for the new Bridge generation. Browser memory remains bounded to32 sessions and four retired generations per session. Older native backends without `replay_generation` retain epoch/runtime/observable-rollback repair, but cannot guarantee caught-up whole-ring eviction detection; upgrade the native backend for that guarantee and use explicit history audit when its event identity is unavailable. Delivery receipts remain conservative: an interrupt ACK means the request was delivered; neither an arbitrary `idle` state nor a session-level interruption proves that particular command completed.

## Native Hermes atomic submission seam (Task2B)

Bridge requires native probe flags `request_owned_prompt_images === true` and `prompt_reject_if_busy === true` before remote send/queue. Image upload additionally requires `prompt_image_uploads === true`; older backends report unavailable instead of using shared staging. `prompt.submit` takes `image_inputs:[{filename,content_base64}]`; text-only submits explicitly send `image_inputs:[]`, preserving another client's pending staged images. `reject_if_busy:true` for send rejects a competing desktop turn at native admission; queue uses `reject_if_busy:false` and explicit queued behavior.

Native limits are5 images,25MiB total decoded image bytes and36MiB serialized request params (native WebSocket frame bound384MiB). Decode and image validation finish before admission; filenames are labels, never filesystem paths. Accepted or uncertain-worker image batches are retained for their owning worker; batches known to be unused, canceled or rejected are cleaned up. These native limits are distinct from the relay's per-image8MiB and ingress limits. Capability negotiation controls enablement; Task2B tests and integrated execution evidence remain the release gate.
