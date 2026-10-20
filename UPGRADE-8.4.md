# HVM 8.4 — interface, provisioning and access update

This is a complete source update for the existing HVM panel, not a replacement
for its database. It includes the earlier console and access improvements.
The panel uses port **5001**. No live VPS has been changed or deleted while
preparing this package. This release has not been pushed to GitHub.

## Changes

- Deep navy and electric-blue design, responsive navigation with collapse,
  dashboard, server cards, login, admin overview and shared management styling.
- Lightweight animated gradients and particle network; bounded frame rate and
  particle counts, hidden-tab pause, and reduced-motion/static fallback.
- Live instance status, searchable/filterable/sortable server cards, pagination,
  unavailable states, and administrator-only host CPU/memory/disk/network samples.
  Host charts build from observed samples, not invented history.
- Five-step creation: System, Resources, Network, Access, Review. Server-side
  resource validation, actual selected-node image checks, duplicate-request
  protection and bounded node creation reservations.
- Public-key access preferred, with an explicit generated-password option.
  One OpenSSH public key is accepted; public key comments are stripped. A new
  non-root account is unprivileged: sudo/root access is not granted implicitly.
- Provisioning waits for cloud-init, checks guest IPv4/default route, DNS and
  outbound IPv4 TCP 443, then verifies a live SSH authentication before ready.
  Key mode uses a temporary probe key for the selected account and removes it;
  the user's private key is not needed for provisioning. The selected public
  key is independently validated and installed.
- Repair and reinstall preserve the recorded access and network policies.
  Existing-profile network mode verifies without rewriting its DHCP/NAT setup.
- Console supports manual password or private-key login, retries and secret
  clearing. SSHX, tmate and Shared IPv4 remain available through access options.
  The file manager supports key-only guests using a short-lived internal key.
- CSRF protection for browser writes, bounded process-local rate limits on
  sensitive HTTP requests, deletion verification, and preserved deletion audit.
- New read-only inventory report for reviewing ownership and backups before
  any separately approved container cleanup.

## Important limits

This is tested source, not a claim that every legacy bug is fixed. Live LXD,
provider routing, real image provisioning, external SSH, remote agents and
production HTTPS/Socket.IO still need verification on your host.

**Migration is deliberately disabled.** The old migration routine could create
an empty destination and delete the source without copying its disk. Migration
now returns a clear error. Use a separately reviewed export/import procedure
with verified backups until a real data-preserving migration is implemented.

Use one panel process. Access jobs, terminal sessions and HTTP rate-limit state
are process-local; this update is not a distributed worker system. Existing
legacy pages retain their backend architecture. Dedicated public IPv4 requires
a separate provider-routed address and appropriate host routing; shared/NAT
mode does not turn the host public address into a guest address.

## 1. Transfer from your PC

Download `HVM-8.4-complete.zip`, then run on **your PC**:

```bash
scp -P 22 ~/Downloads/HVM-8.4-complete.zip root@52.77.241.220:/root/
ssh -p 22 root@52.77.241.220
```

Use the main host's SSH credentials/key. Port 25531 was the forwarded SSH port
of the `test` guest; do not upload the panel into that guest. If your main host
uses a private key, add `-i /path/to/your-host-key` to both commands.

## 2. Stop the panel and back it up

On the **main host**, stop its existing panel process. If it runs in a terminal,
press Ctrl+C there. If you use the previously documented service:

```bash
systemctl stop hvm-panel
```

If that unit does not exist, stop the actual panel process through the manager
that started it. Do not start a second panel process on the same database.

Back up the stopped installation. The backup contains private configuration;
keep it private. This backs up panel files, not container disks:

```bash
umask 077
tar --exclude='HVM/.venv' --exclude='HVM/venv' --exclude='HVM/.git' \
  -czf "/root/HVM-before-8.4-$(date +%Y%m%d-%H%M%S).tar.gz" -C /root HVM
```

**Only continue if the backup succeeds.** If `DATABASE_PATH` points outside
`/root/HVM`, also back up that database and any SQLite WAL files while the panel
is stopped. Preserve `.env`, `.hvm-secret`, certificates, uploads, backups and
`network_policy.json`. Losing the original secret can make stored credentials
unreadable. The update ZIP contains none of those runtime files.

## 3. Extract and install Python dependencies

On the main host:

```bash
apt-get update
apt-get install -y unzip python3-venv python3-pip
unzip -o /root/HVM-8.4-complete.zip -d /root
cd /root/HVM
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

The ZIP has a top-level `HVM/` folder, so extract into `/root`, not `/root/HVM`.
It overwrites source files; merge any local source customizations first.
Use the virtual environment; do not install into the system-managed Python.
Do not delete or recreate your Git clone, database or containers to apply it.
If the source folder was previously deleted, restore the original database
and configuration from backup before starting; a fresh database cannot recover
ownership or passwords from existing LXD containers.

## 4. Repair existing running VPSes once

For the managed private bridge shown in your output (`lxdbr0`), run on the host:

```bash
cd /root/HVM
.venv/bin/python hvmctl.py doctor --all
.venv/bin/python hvmctl.py repair --all --network --ssh --repair-host-firewall
lxc list
```

Repair targets running, locally hosted, panel-managed guests. Stopped, missing
and remote guests are skipped. Failures are reported individually. It never
recreates or deletes a guest. To target one guest, use `--container test`
instead of `--all`.

For shared/NAT guests, this enables DHCP, routing and NAT on their existing
managed private bridge and configures guest DHCP. It preserves bridge addresses
and the administrator's LXD firewall setting. Bridge changes affect other guests
using that bridge. `--repair-host-firewall` explicitly enables host forwarding,
adds narrow bridge/subnet/uplink forwarding and DHCP/DNS allowances, and persists
them with `hvm-network.service`. It does not flush firewall rules or change the
host IP. Future local provisioning reapplies this explicitly enrolled policy.

Existing-profile network mode refuses the host-firewall option and preserves
network configuration. Repair it individually without that flag, or use its
provider-specific networking procedure. Upstream security groups or independent
nftables/firewalld chains may still block traffic; failed final checks must be
investigated, not treated as success.

Password mode restores the recorded guest password, generating and storing one
only if absent. Key mode preserves key-only authentication. If encrypted values
cannot be read, restore the original secret rather than resetting it.

## 5. Start on port 5001

For a foreground run:

```bash
cd /root/HVM
PORT=5001 .venv/bin/python hvm.py
```

Keep that terminal open. For an existing `hvm-panel` systemd deployment, ensure
its `WorkingDirectory=/root/HVM`, `ExecStart=/root/HVM/.venv/bin/python /root/HVM/hvm.py`
and `Environment=PORT=5001`, then start that service instead. Do not run both.
If `.env` overrides `PANEL_VERSION`, update it to `8.4-PRO`.

Open your existing panel URL and hard-refresh (Ctrl+Shift+R). Use your HTTPS
reverse proxy for console credentials/private keys; it must forward both
Socket.IO polling and WebSocket traffic under `/socket.io/`. Preserve existing
proxy/auth configuration.

Remote node deployments must also receive this release's `node.py`,
`node_network.py`, `guest_access.py` and `provisioning_policy.py` beside their
existing node files, with their node configuration/keys preserved. Restart the
actual node agent service. Older agents lack the new key-verification endpoint.
The local-node setup in your logs does not need a separate node agent.

## 6. Verify one newly created VPS

1. In Admin → Nodes, set Shared public IPv4 to `52.77.241.220` for this host.
   Allocate ports to the VPS owner. The public address stays on the host.
2. Create one small VPS using Shared IPv4 / NAT and a supported image. Use the
   image check. Select SSH key and paste your **public** key, or explicitly choose
   generated-password access. Wait for actual setup completion.
3. Open its Access diagnostics. IPv4/default route, DNS, outbound connectivity
   and SSH service checks should pass. Check `lxc list` for the private IPv4.
4. Open Shared IPv4 access and use its exact generated host/port/user. For keys,
   add your private-key path to the SSH command, for example:

   ```bash
   ssh -i ~/.ssh/id_ed25519 -p YOUR_MAPPED_PORT YOUR_GUEST_USER@52.77.241.220
   ```

5. Test the browser console with the selected method, including one failed
   attempt followed by a correct retry. Verify files and status updates.
6. Test SSHX/tmate only if needed; install missing tools through the explicit
   option. These require working outbound networking and their external services.

If your host firewall or cloud security group blocks the mapped TCP port, allow
that exact port for your client. `Permission denied (publickey)` means an SSH
server answered but did not accept the attempted authentication; it does not
mean the network port is closed.

## 7. Inventory before the cleanup you requested

Your cleanup instructions require a current inventory, ownership/criticality
review, a backup opportunity and final confirmation of exact instance names.
**No containers have been deleted.** Run this read-only command on the host:

```bash
cd /root/HVM
.venv/bin/python hvm_inventory.py > /root/hvm-inventory.json
cat /root/hvm-inventory.json
```

If you use another database path, pass `--database /actual/path/to/hvm.db`.
Send the report for review. It identifies local projects, panel ownership,
protection, available storage usage, snapshot counts and recorded backup files.
Unknown usage remains unknown; a backup record/file is not proof of a working
restore. Confirm any unrelated/critical services and verify export backups before
approving exact `project/name` pairs. No bulk-delete command is included.

## Verification performed for this release

- 88 Python regression tests: console lifecycle/isolation, live local SSH test
  servers for password and key negotiation, access jobs/routes, networking,
  creation validation/idempotency, CSRF, inventory, deletion and SFTP key cleanup.
- Browser checks on 16 pages at widths 320, 375, 768, 1024, 1440 and 1920:
  no horizontal page overflow or uncaught JavaScript errors; wizard validation,
  sidebar collapse, search, detail tabs, console retry and access-option flows.
- Ambient animation frame bound, hidden-tab pause and reduced-motion checks.
- Python/JavaScript syntax, rendered inline scripts, and archive integrity checks.

Browser/API tests use fixtures and mocked node responses. SSH tests use local
Paramiko servers. They do not replace real LXD/image/provider tests on your VPS.
Test source remains in the working repository; production ZIP excludes test
fixtures, credentials, databases, uploads, logs, screenshots and Git metadata.

## Rollback

Stop the updated panel. Preserve its current database/configuration separately
before restoring the stopped-installation backup to the original path. Restore
code, database and the matching secret together, then restart the original
service. A source rollback does not reverse guest SSH, DHCP, host firewall or
container changes already made by an explicit repair or provisioning operation.
Review those separately; never restore a database over active panel writes.
