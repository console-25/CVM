"""Guest SSH and DHCP setup with explicit verification and no secret commands."""
import asyncio
import shlex

HEALTH_SCRIPT = r'''
set +e
printf 'ipv4='
ip -o -4 addr show scope global 2>/dev/null | awk '{printf "%s ", $4}'
printf '\nroute='
ip -4 route show default 2>/dev/null | head -1
printf '\n'
if [ -x /usr/sbin/sshd ]; then echo ssh_binary=yes; else echo ssh_binary=no; fi
if [ -x /usr/sbin/sshd ] && /usr/sbin/sshd -t >/dev/null 2>&1; then echo ssh_config=yes; else echo ssh_config=no; fi
if awk 'NR>1 && $2 ~ /:0016$/ && $4 == "0A" {found=1} END {exit !found}' /proc/net/tcp /proc/net/tcp6 2>/dev/null; then echo ssh_listener=yes; else echo ssh_listener=no; fi
if [ -x /usr/sbin/sshd ]; then
 /usr/sbin/sshd -T -C user=root,host=localhost,addr=127.0.0.1 2>/dev/null | awk '$1=="passwordauthentication" {print "password_auth=" $2} $1=="permitrootlogin" {print "root_login=" $2} $1=="pubkeyauthentication" {print "key_auth=" $2} $1=="authenticationmethods" {print "auth_methods=" $2}'
fi
printf 'root_account='
awk -F: '$1=="root" {if ($2=="" || $2 ~ /^[!*]/) print "locked"; else print "set"}' /etc/shadow 2>/dev/null
if [ -s /etc/resolv.conf ]; then echo resolver_config=yes; else echo resolver_config=no; fi
'''

NETWORK_SCRIPT = r'''
set -eu
[ -d /sys/class/net/eth0 ] || { echo 'Guest eth0 is absent; inspect its LXD NIC' >&2; exit 1; }
ip link set eth0 up
backup=$(mktemp -d)
managed=''
success=no
restore() {
 if [ "$success" != yes ] && [ -n "$managed" ]; then
  if [ -f "$backup/original" ]; then cp "$backup/original" "$managed"; else rm -f "$managed"; fi
 fi
 rm -rf "$backup"
}
trap restore EXIT HUP INT TERM
if command -v netplan >/dev/null 2>&1; then
 mkdir -p /etc/netplan
 managed=/etc/netplan/90-hvm-dhcp.yaml
 if [ -f "$managed" ]; then cp "$managed" "$backup/original"; fi
 umask 077
 cat > /etc/netplan/90-hvm-dhcp.yaml <<'EOF'
network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true
      dhcp6: true
      optional: true
EOF
 netplan generate
 timeout 30 netplan apply
elif command -v nmcli >/dev/null 2>&1 && nmcli general status >/dev/null 2>&1; then
 connection=$(nmcli -g GENERAL.CONNECTION device show eth0)
 if [ -n "$connection" ] && [ "$connection" != '--' ]; then
   nmcli connection modify "$connection" ipv4.method auto
   nmcli connection up "$connection"
 else
   nmcli device connect eth0
 fi
elif command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet systemd-networkd; then
 mkdir -p /etc/systemd/network
 managed=/etc/systemd/network/00-hvm-eth0.network
 if [ -f "$managed" ]; then cp "$managed" "$backup/original"; fi
 cat > /etc/systemd/network/00-hvm-eth0.network <<'EOF'
[Match]
Name=eth0
[Network]
DHCP=yes
IPv6AcceptRA=yes
EOF
 networkctl reload
 networkctl reconfigure eth0
 networkctl renew eth0 || true
elif command -v dhclient >/dev/null 2>&1; then
 timeout 30 dhclient -4 -1 eth0
elif command -v udhcpc >/dev/null 2>&1; then
 timeout 30 udhcpc -n -q -i eth0
elif command -v ifup >/dev/null 2>&1; then
 ifdown eth0 2>/dev/null || true
 ifup eth0
else
 echo 'No supported DHCP manager found inside the guest' >&2
 exit 1
fi
success=yes
'''

CONNECTIVITY_SCRIPT = r'''
set +e
dns=no
outbound=no
method=unavailable
for target in archive.ubuntu.com example.com; do
 address=''
 if command -v getent >/dev/null 2>&1; then
  address=$(timeout 8 getent ahostsv4 "$target" 2>/dev/null | awk 'NR==1 {print $1}')
 elif command -v python3 >/dev/null 2>&1; then
  address=$(timeout 8 python3 -c 'import socket,sys; print(socket.gethostbyname(sys.argv[1]))' "$target" 2>/dev/null)
 fi
 [ -n "$address" ] || continue
 case "$address" in *[!0-9.]* ) continue;; esac
 dns=yes
 if command -v bash >/dev/null 2>&1; then
  method=ipv4-tcp443
  if timeout 8 bash -c 'exec 3<>/dev/tcp/$1/443' sh "$address" >/dev/null 2>&1; then outbound=yes; break; fi
 elif command -v python3 >/dev/null 2>&1; then
  method=ipv4-tcp443
  if timeout 8 python3 -c 'import socket,sys; s=socket.create_connection((sys.argv[1],443),6); s.close()' "$address" >/dev/null 2>&1; then outbound=yes; break; fi
 elif command -v nc >/dev/null 2>&1; then
  method=ipv4-tcp443
  if timeout 8 sh -c 'echo | nc -w 6 "$1" 443' sh "$address" >/dev/null 2>&1; then outbound=yes; break; fi
 fi
done
printf 'dns_ready=%s\noutbound_ready=%s\nprobe_method=%s\n' "$dns" "$outbound" "$method"
'''

SSH_RESTART_SCRIPT = r'''
set -eu
/usr/sbin/sshd -t
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
 systemctl disable --now ssh.socket >/dev/null 2>&1 || true
 if systemctl cat ssh.service >/dev/null 2>&1; then systemctl restart ssh.service; else systemctl restart sshd.service; fi
elif command -v rc-service >/dev/null 2>&1; then rc-service sshd restart
else service ssh restart || service sshd restart
fi
'''

INSTALL_SCRIPT = r'''
set -eu
if [ -x /usr/sbin/sshd ]; then exit 0; fi
if command -v apt-get >/dev/null 2>&1; then
 export DEBIAN_FRONTEND=noninteractive
 apt-get -o Acquire::Retries=2 update -qq
 apt-get -o Acquire::Retries=2 install -y -qq openssh-server
elif command -v dnf >/dev/null 2>&1; then
 dnf install -y openssh-server
elif command -v yum >/dev/null 2>&1; then
 yum install -y openssh-server
elif command -v apk >/dev/null 2>&1; then
 apk add --no-cache openssh
else
 echo 'Install OpenSSH using the guest package manager' >&2
 exit 1
fi
[ -x /usr/sbin/sshd ]
'''

SSH_CONFIG_SCRIPT = r'''
set -eu
mkdir -p /run/sshd /etc/ssh/sshd_config.d
chmod 755 /run/sshd
ssh-keygen -A
original=$(mktemp -d)
[ -f /etc/ssh/sshd_config ] || touch /etc/ssh/sshd_config
cp /etc/ssh/sshd_config "$original/main"
if [ -f /etc/ssh/sshd_config.d/00-hvm-access.conf ]; then cp /etc/ssh/sshd_config.d/00-hvm-access.conf "$original/managed"; fi
success=no
rollback() {
 if [ "$success" != yes ] && [ -f "$original/main" ]; then
  cp "$original/main" /etc/ssh/sshd_config
  if [ -f "$original/managed" ]; then cp "$original/managed" /etc/ssh/sshd_config.d/00-hvm-access.conf; else rm -f /etc/ssh/sshd_config.d/00-hvm-access.conf; fi
 fi
 rm -rf "$original"
}
trap rollback EXIT HUP INT TERM
umask 077
cat > /etc/ssh/sshd_config.d/00-hvm-access.conf <<'EOF'
# HVM guest access policy. Existing authorized_keys remain usable.
Port 22
ListenAddress 0.0.0.0
ListenAddress ::
PasswordAuthentication yes
AuthenticationMethods any
PermitRootLogin yes
PubkeyAuthentication yes
KbdInteractiveAuthentication no
PermitEmptyPasswords no
EOF
{
 printf '%s\n' 'Include /etc/ssh/sshd_config.d/00-hvm-access.conf' 'Subsystem sftp internal-sftp'
 awk '!($1=="Include" && $2=="/etc/ssh/sshd_config.d/00-hvm-access.conf") && !($1=="Subsystem" && $2=="sftp") {print}' "$original/main"
} > /etc/ssh/sshd_config
/usr/sbin/sshd -t
started=no
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
 systemctl disable --now ssh.socket >/dev/null 2>&1 || true
 for unit in ssh.service sshd.service; do
  if systemctl enable "$unit" >/dev/null 2>&1 && systemctl restart "$unit"; then started=yes; break; fi
 done
elif command -v rc-service >/dev/null 2>&1; then
 rc-update add sshd default >/dev/null 2>&1 || true
 if rc-service sshd restart; then started=yes; fi
elif command -v service >/dev/null 2>&1; then
 if service ssh restart || service sshd restart; then started=yes; fi
fi
if [ "$started" != yes ]; then echo 'SSH service could not be started' >&2; exit 1; fi
success=yes
'''


class GuestAccessError(RuntimeError):
    pass


def parse_health(output):
    allowed = {'ipv4','route','ssh_binary','ssh_config','ssh_listener','password_auth','root_login','key_auth','root_account','resolver_config','auth_methods','dns_ready','outbound_ready','probe_method'}
    result = {}
    for line in str(output or '').splitlines():
        key, sep, value = line.partition('=')
        if sep and key in allowed:
            result[key] = value.strip()[:500]
    result['ssh_service_ready'] = all(result.get(k) == 'yes' for k in ('ssh_binary','ssh_config','ssh_listener'))
    result['ssh_ready'] = all(result.get(k) == 'yes' for k in ('ssh_binary','ssh_config','ssh_listener','password_auth','root_login'))
    result['ssh_ready'] = result['ssh_ready'] and result.get('auth_methods') in ('any','password')
    result['network_ready'] = bool(result.get('ipv4') and result.get('route'))
    result['checked'] = True
    return result


def validate_password(password):
    if not isinstance(password, str) or not 8 <= len(password) <= 128 or any(ch in password for ch in ('\n','\r','\0')):
        raise ValueError('Use a password of 8–128 characters without line breaks or null characters.')
    return password


class GuestAccess:
    """Callbacks execute only inside one authorized guest; stdin carries passwords."""
    def __init__(self, run_script, set_password, sleep=asyncio.sleep, verify_login=None, verify_key=None):
        self.run = run_script
        self.set_password = set_password
        self.sleep = sleep
        self.verify_login = verify_login
        self.verify_key = verify_key
        self.repair_network = True

    async def health(self):
        return parse_health(await self.run(HEALTH_SCRIPT, 20))

    async def diagnostics(self):
        state = await self.health()
        if state['network_ready']:
            state.update(await self.connectivity())
        return state

    async def connectivity(self):
        state = parse_health(await self.run(CONNECTIVITY_SCRIPT, 60))
        return {key:state.get(key, 'no') for key in ('dns_ready','outbound_ready','probe_method')}

    async def verify_network(self, state):
        state.update(await self.connectivity())
        if state['dns_ready'] != 'yes' or state['outbound_ready'] != 'yes':
            raise GuestAccessError('Guest IPv4 exists but outbound DNS/TCP access failed. Check managed bridge NAT, node forwarding/firewall and upstream access. The container was retained.')
        return state

    async def ensure_network(self, repair=False):
        state = await self.health()
        if state['network_ready']:
            try:
                return await self.verify_network(state)
            except GuestAccessError:
                if not repair:
                    raise
        if repair:
            try:
                await self.run(NETWORK_SCRIPT, 45)
            except Exception:
                raise GuestAccessError('Guest DHCP could not be configured. Check its eth0 NIC and the node bridge DHCP service. The container was retained.') from None
        for _ in range(10):
            await self.sleep(2)
            state = await self.health()
            if state['network_ready']:
                return await self.verify_network(state)
        raise GuestAccessError('Guest has no usable IPv4/default route. Check bridge DHCP/NAT and guest network configuration. The container was retained for repair.')

    async def configure_ssh(self, password):
        validate_password(password)
        try:
            await self.run('if command -v cloud-init >/dev/null 2>&1; then result=0; timeout 90 cloud-init status --wait >/dev/null 2>&1 || result=$?; [ "$result" = 0 ] || [ "$result" = 2 ]; fi', 100)
        except Exception:
            raise GuestAccessError('Guest initialization has not completed successfully. Check cloud-init before retrying SSH setup.') from None
        # Cloud-init may have replaced guest networking while it finished.
        await self.ensure_network(repair=self.repair_network)
        try:
            await self.run(INSTALL_SCRIPT, 300)
        except Exception:
            raise GuestAccessError('OpenSSH installation failed. Check guest IPv4, DNS, outbound access and package repositories. The container was retained.') from None
        try:
            await self.run(SSH_CONFIG_SCRIPT, 60)
        except Exception:
            raise GuestAccessError('SSH configuration or service startup failed. Run access diagnostics before retrying. The container was retained.') from None
        await self.set_password(password)
        # Restart after password/configuration work; verify the live daemon below.
        await self.run(SSH_RESTART_SCRIPT, 60)
        if self.verify_login is None:
            raise GuestAccessError('Live SSH verifier is unavailable; guest access was not marked ready.')
        for _ in range(3):
            state = await self.health()
            if state['ssh_ready'] and state.get('root_account') in ('set','P','PS'):
                try:
                    if await self.verify_login(password):
                        state['ssh_authenticated'] = True
                        return state
                except Exception:
                    pass
            await self.sleep(2)
        raise GuestAccessError('SSH access verification failed: port 22, root account or password-authentication policy is not ready. The container was retained.')


def key_account_script(username, public_key):
    """Public values are validated and quoted. No private keys enter guest scripts."""
    import shlex
    from provisioning_policy import validate_access
    access=validate_access({'access_mode':'key','ssh_username':username,'ssh_public_key':public_key})
    return r'''
set -eu
user=USERNAME
key=PUBLIC_KEY
if ! id "$user" >/dev/null 2>&1; then
 if command -v useradd >/dev/null 2>&1; then useradd -m -s /bin/sh "$user"; else adduser -D -s /bin/sh "$user"; fi
elif [ "$user" != root ] && [ "$(id -u "$user")" -lt 1000 ]; then
 echo 'Refusing to provision a system account' >&2; exit 1
fi
home=$(getent passwd "$user" | cut -d: -f6)
[ -n "$home" ] && [ -d "$home" ] || { echo 'Guest account has no home directory' >&2; exit 1; }
[ ! -L "$home/.ssh" ] && [ ! -L "$home/.ssh/authorized_keys" ] || { echo 'Refusing symlinked key storage' >&2; exit 1; }
umask 077
mkdir -p "$home/.ssh"
touch "$home/.ssh/authorized_keys"
grep -qxF "$key" "$home/.ssh/authorized_keys" || printf '%s\n' "$key" >> "$home/.ssh/authorized_keys"
chmod 700 "$home/.ssh"; chmod 600 "$home/.ssh/authorized_keys"
chown -R "$user:$(id -gn "$user")" "$home/.ssh"
# Locked accounts can be rejected before key authentication on some images.
# Set an unknown random password; SSH password authentication is disabled below.
status=$(passwd -S "$user" 2>/dev/null | awk '{print $2}')
case "$status" in L|LK|NP)
 random=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
 printf '%s:%s\n' "$user" "$random" | chpasswd
 unset random
 ;; esac
'''.replace('USERNAME',shlex.quote(access['username'])).replace('PUBLIC_KEY',shlex.quote(access['public_key']))


async def configure_key_access(service, username, public_key):
    from provisioning_policy import validate_access
    access=validate_access({'access_mode':'key','ssh_username':username,'ssh_public_key':public_key})
    await service.run('if command -v cloud-init >/dev/null 2>&1; then result=0; timeout 90 cloud-init status --wait >/dev/null 2>&1 || result=$?; [ "$result" = 0 ] || [ "$result" = 2 ]; fi',100)
    await service.ensure_network(repair=service.repair_network)
    await service.run(INSTALL_SCRIPT,300)
    await service.run(key_account_script(access['username'],access['public_key']),45)
    config=SSH_CONFIG_SCRIPT.replace('PasswordAuthentication yes','PasswordAuthentication no').replace('AuthenticationMethods any','AuthenticationMethods publickey').replace('PermitRootLogin yes','PermitRootLogin prohibit-password')
    await service.run(config,60)
    if service.verify_key is None:raise GuestAccessError('Live SSH key verifier is unavailable; access was not marked ready.')
    for _ in range(3):
        try:
            if await service.verify_key(username):
                state=await service.health();state.update(ssh_ready=True,ssh_authenticated=True,access_mode='key',ssh_username=username);return state
        except Exception:pass
        await service.sleep(2)
    raise GuestAccessError('SSH key login verification failed. Check account permissions and guest SSH rules. The container was retained.')
