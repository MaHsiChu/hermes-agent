# Remote relay and PC Bridge

For the Mac mini server and iOS/TestFlight development handoff, see [the Chinese delivery brief](../../docs/remote-control/MACMINI-HANDOFF.zh-CN.md). The existing mobile workspace is a PWA; an iOS app target and its authentication integration remain separate development work.

The relay never starts Hermes, Codex, Claude or Session Hub. Start the existing desktop backend and optional configured Hub first. Only explicitly paired backend/profile/engine scopes are synchronized. These files are deployment recipes; Docker/PostgreSQL/public-domain production rollout has not been executed by the implementation tests.

## Local Windows development

From the isolated checkout, create a dedicated remote runtime environment. The relay/Bridge dependency lock is independent of the desktop core pins; installing it into Hermes's `.venv` can trigger desktop dependency repair and damage a running Windows environment with locked DLLs. Keep the desktop on its own core environment:

```powershell
uv venv --python 3.11 C:/private/hermes-remote-venv
uv pip install --no-config --python C:/private/hermes-remote-venv/Scripts/python.exe --require-hashes -r remote_control/requirements.lock
C:/private/hermes-remote-venv/Scripts/python.exe -m remote_control.migrate --config C:/private/server.yaml
C:/private/hermes-remote-venv/Scripts/python.exe -m remote_control.server --config C:/private/server.yaml
```

Copy `server.local.example.yaml` to a private runtime directory and edit absolute database/static paths. Run Keycloak locally on 127.0.0.1:8788 with an independently installed Java runtime; configure realm `hermes-remote`, client `hermes-remote`, exact redirect `http://127.0.0.1:8787/auth/callback`, S256 required. A public PKCE client can omit client_secret for this local setup. No public binding or account credentials are included. The health endpoint works when OIDC is absent, but every protected resource remains closed even with old cookies/device tokens.

Copy `bridge.example.yaml` and specify the exact already-running Hermes URL, its token file, profile and optional Hub scopes. Set development true for loopback HTTP. For mixed deployment (HTTPS relay, loopback backend), development true still requires HTTPS for every non-loopback URL. Store both state and credential files in the user's private application-data directory; on Windows inspect its ACL with `icacls` and use a folder readable only by that account and administrators. POSIX secret readers require mode 0600. No credentials belong in Git or command-line arguments.

```powershell
C:/private/hermes-remote-venv/Scripts/python.exe -m remote_control.bridge --config C:/private/bridge.yaml pair
C:/private/hermes-remote-venv/Scripts/python.exe -m remote_control.bridge --config C:/private/bridge.yaml run
```

Pairing opens the normal browser. Log in, compare the code and select sources explicitly. Nothing is copied until this consent finishes. If the one-time exchange response is lost, revoke the unused device and pair again. A credential file cannot silently be replaced with a different account's binding.

For login startup, use Task Scheduler: program is `C:/private/hermes-remote-venv/Scripts/pythonw.exe`, arguments are `-m remote_control.bridge --config C:/private/bridge.yaml run`, working directory is this checkout, trigger is user logon, and only one instance is allowed. Keep it in the same user context as the existing backend. To stop, end this scheduled task; it does not stop the desktop backend. Bridge holds a file lock to prevent two processes using one journal. The actual Electron backend uses an ephemeral port and freshly minted token on each launch. Update the explicit URL and token reference and restart Bridge after that backend restarts. Credential refresh alone cannot discover a changed port. A copied per-launch URL/token is not a stable desktop endpoint descriptor. Automatic desktop endpoint discovery is absent, so this recipe does not claim unattended recovery across Electron backend restarts.

## macOS startup

Create a dedicated remote venv, separate from the desktop core and any Windows environment:

```sh
uv venv --python 3.11 "$HOME/.local/share/hermes-remote/venv"
uv pip install --no-config --python "$HOME/.local/share/hermes-remote/venv/bin/python" --require-hashes -r remote_control/requirements.lock
```

Keep Bridge configuration/state under a user-owned directory with mode0700 and secret files0600. Create a user LaunchAgent with ProgramArguments `[absolute remote-venv python, -m, remote_control.bridge, --config, absolute bridge.yaml, run]`, WorkingDirectory pointing to checkout, RunAtLoad true, KeepAlive true, and log paths inside the private directory. Load with `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/your.remote.bridge.plist`; unload with `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/your.remote.bridge.plist`. No Mac execution evidence is implied by this recipe.

## Production containers

Edit the three `.example.invalid` hostname references in Caddy, server YAML and realm JSON and the Keycloak hostname in compose. Build the mobile bundle separately before starting containers. Copy `.env.example` to a private `.env` and populate independent random URL-safe secrets; do not use shell history for literal credentials. `docker compose --env-file /private/remote.env -f deploy/remote-control/compose.yaml config` validates wiring but may print expanded secrets: run privately, do not attach its output to tickets.

```sh
docker compose --env-file /private/remote.env -f deploy/remote-control/compose.yaml up -d --build
docker compose --env-file /private/remote.env -f deploy/remote-control/compose.yaml exec relay python -m remote_control.migrate --config /config/server.yaml
```

Only Caddy exposes ports. PostgreSQL and Keycloak HTTP stay on the container network; their proxy headers trust that network boundary. Caddy obtains certificates for the configured real domains. Keep exactly one relay replica/worker. Realm import only creates a missing realm; updates to existing clients must be applied in Keycloak administration. Migrations reject unknown schema versions; future migrations must be explicit upgrades, never delete/recreate existing data.

## Backup and restore

Back up both databases, Caddy volumes and private configuration. Keep backups encrypted/access-restricted. PostgreSQL examples (run from the deploy directory, with the same private env file used above):

```sh
docker compose --env-file /private/remote.env exec -T postgres pg_dump -U postgres -Fc -f /tmp/remote.dump remote
docker compose --env-file /private/remote.env exec -T postgres pg_dump -U postgres -Fc -f /tmp/keycloak.dump keycloak
docker compose --env-file /private/remote.env cp postgres:/tmp/remote.dump /private/backups/remote.dump
docker compose --env-file /private/remote.env cp postgres:/tmp/keycloak.dump /private/backups/keycloak.dump
```

Restore into staging first. The following uses binary-safe `docker compose cp` and restores objects **as their application roles**, rather than leaving tables owned by postgres. These commands assume you are in the deployment directory and the original roles already exist:

```sh
docker compose --env-file /private/remote.env cp /private/backups/remote.dump postgres:/tmp/remote.dump
docker compose --env-file /private/remote.env cp /private/backups/keycloak.dump postgres:/tmp/keycloak.dump
docker compose --env-file /private/remote.env exec -T postgres createdb -U postgres -O remote remote_restore
docker compose --env-file /private/remote.env exec -T postgres createdb -U postgres -O keycloak keycloak_restore
docker compose --env-file /private/remote.env exec -T postgres pg_restore -U postgres --role=remote --no-owner --exit-on-error -d remote_restore /tmp/remote.dump
docker compose --env-file /private/remote.env exec -T postgres pg_restore -U postgres --role=keycloak --no-owner --exit-on-error -d keycloak_restore /tmp/keycloak.dump
docker compose --env-file /private/remote.env exec -T postgres psql -U remote -d remote_restore -c 'SELECT count(*) FROM remote_users; SELECT count(*) FROM remote_sessions;'
docker compose --env-file /private/remote.env exec -T postgres psql -U keycloak -d keycloak_restore -c 'SELECT count(*) FROM realm;'
```

The staging checks use the actual restricted application identities; also run staging relay/Keycloak instances against those databases and verify login before switching production. For final cutover stop relay/Keycloak, preserve the old databases, and point configuration at the verified replacements. Do not use `--clean` on an existing live database without an explicit replacement decision. PowerShell older versions corrupt redirected binary output: create dumps inside the postgres container and use `docker compose cp` in both directions instead. Start Keycloak then relay and reconnect devices; uncertain receipts remain uncertain and are never auto-replayed. These role-correct commands have not been executed against PostgreSQL in this environment; staging validation is a required deployment step.

For SQLite development, stop the relay and copy the database using SQLite's backup API (not just the WAL-active main file). Stop Bridge before backing up its journal and credential file together; restoring one without the other can lose device identity or delivery evidence.

## Current capability boundaries

Hermes text send/queue/steer/interrupt/approval/clarify use existing native session RPCs. UI must distinguish acceptance from completion. Clarify raw response frames have no winner ACK, so responses report `response_submitted`. Queue/interrupt completion is observed in session events, not invented from an HTTP202. No new agent process, native database writes, core tool or synthetic user role is introduced.

Task2B enables Hermes mobile image submission when the native backend advertises request-owned atomic image inputs, busy rejection and image upload limits. Older backends fail closed; Hub image submission remains unsupported. Text-only remote turns send an explicit empty image list to preserve desktop staging. Persisted Hermes `@image:` directive lines (including quoted paths and the native screenshot placeholder) and structured local file-image references are normalized into opaque session-owned attachments. Missing, outside-root or unsupported references show an unavailable reason; source paths outside `attachment_roots`, network file paths and arbitrary remote URLs are never fetched.

Hub uses paginated `sessions` with snapshot IDs, paginated `transcript`, and `app_dispatch` with a stable request key into the original App session. There is no CLI fallback. App availability, approvals and interruption remain truthful limitations; an old Hub without pagination reports incomplete catalog. Hub source disappearance cannot yet reliably distinguish deletion from temporarily unavailable files, so Bridge retains its last copy rather than creating unsafe deletion tombstones. Hermes session deletion requires both a complete catalog and a native detail404.

Data retention/quota policy must be selected before public rollout: schema currently retains copied history, events, receipts and images until operator-managed archival/purge. There is no claim of thousands of users, production PostgreSQL load validation, actual phone rendering, macOS service validation, or China-wide network performance. Follow Task4 acceptance separately.

The hash lock is generated independently of core uv overrides with `uv pip compile --no-config --universal --python-version 3.11 --generate-hashes remote_control/requirements.txt -o remote_control/requirements.lock`. Use `uv pip install --no-config --require-hashes -r remote_control/requirements.lock` in a remote-only venv. Linux x86_64 and macOS arm64 hash-checked resolver dry-runs passed; these are not actual host installs. Stop processes using a Windows venv before upgrading binary packages.

History snapshot outboxes split at500 rows and by encoded byte count. A large individual row uses the same snapshot contract over authenticated HTTP with its active Bridge lease, through the dedicated Caddy request limit. Rows exceeding60MiB remain on PC and are named in explicit incomplete-sync metadata; other rows/sessions continue. Monitor this error before claiming complete copies. Hub history checkpoints restart when native transcript generation changes.

Completed idle histories are not periodically rescanned. Native activity/count changes and completion/replay-gap evidence request reconciliation; Hub uses bounded revision/generation probes. An in-place edit of an old Hermes record may not change its activity/count metadata or emit an event. To audit such a session, stop Bridge, run the following with the same private config and exact already-paired source, then start Bridge normally:

```sh
python -m remote_control.bridge --config /private/bridge.yaml repair --backend-id desktop --profile default --engine hermes --session-id ORIGINAL_NATIVE_ID
```

The command takes Bridge's state lock and only schedules a scan of an already-known authorized identity; it does not change native history or dispatch/retry a model command. Large live/replayed events use an explicit repair marker and the bounded history transfer instead of disconnecting the device. See [source evidence and repair protocol](../../docs/remote-control/PROTOCOL.md#source-evidence-and-explicit-history-repair) for detection limits, native epoch versus Bridge repair generation, and byte bounds.

Guaranteed recovery after native replay-ring eviction requires the backend's additive `replay_generation` contract. Restart an updated native backend and refresh its endpoint/credential configuration if those rotated. Older backends remain compatible but cannot identify an evicted ring whose new sequence already passed the old watermark; their epoch/runtime/observable-rollback checks are best effort, so use the explicit audit or upgrade for this boundary.
