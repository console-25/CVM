"""Node-local bridge setup and real SSH authentication; no host readdressing."""
import ipaddress
import json
import subprocess

BRIDGE_SCRIPT = r'''
import ipaddress,json,subprocess,sys
name=sys.argv[1]
def run(args):
 p=subprocess.run(['lxc']+args,capture_output=True,text=True,timeout=25)
 if p.returncode: raise RuntimeError('LXD bridge operation failed: '+p.stderr.strip()[:300])
 return p.stdout
instance=json.loads(run(['query','/1.0/instances/'+name]))
nic=instance.get('expanded_devices',{}).get('eth0',{})
bridge=nic.get('network')
if not bridge: raise RuntimeError('Guest eth0 must use an existing managed LXD bridge for Shared IPv4.')
network=json.loads(run(['query','/1.0/networks/'+bridge]))
if not network.get('managed') or network.get('type')!='bridge': raise RuntimeError('Expected an existing managed LXD bridge.')
config=network.get('config',{})
subnet=ipaddress.ip_interface(config.get('ipv4.address','none'))
if subnet.version!=4 or not subnet.ip.is_private: raise RuntimeError('Shared IPv4 bridge needs an existing private IPv4 subnet. No host addresses were changed.')
if config.get('bridge.external_interfaces') or config.get('bridge.mode','standard') != 'standard':
 raise RuntimeError('Refusing to change an externally attached or FAN bridge. Configure provider networking explicitly.')
changes=[]
for key in ('ipv4.dhcp','ipv4.routing','ipv4.nat'):
 if config.get(key)!='true':
  run(['network','set',bridge,key,'true']);changes.append(key)
print(json.dumps({'bridge':bridge,'subnet':str(subnet.network),'changed':changes}))
'''


def prepare_local_bridge(container):
    result=subprocess.run(['python3','-c',BRIDGE_SCRIPT,container],text=True,capture_output=True,timeout=150)
    if result.returncode:
        raise RuntimeError('Shared IPv4 bridge setup failed: '+result.stderr.strip().splitlines()[-1][:350])
    return json.loads(result.stdout)


def verify_local_guest_login(container, password):
    """Probe the running daemon on the guest's LXD-reported IPv4, not sshd -T."""
    import paramiko
    result=subprocess.run(['lxc','query',f'/1.0/instances/{container}/state'],text=True,capture_output=True,timeout=20)
    if result.returncode: raise RuntimeError('Could not read guest network state for SSH verification.')
    state=json.loads(result.stdout)
    addresses=state.get('network',{}).get('eth0',{}).get('addresses',[])
    host=next((a['address'] for a in addresses if a.get('family')=='inet' and a.get('scope')=='global'),None)
    if not host: raise RuntimeError('Guest has no eth0 IPv4 for SSH verification.')
    address=ipaddress.ip_address(host)
    if address.version!=4 or address.is_loopback or address.is_unspecified:
        raise RuntimeError('Guest IPv4 is invalid for SSH verification.')
    return authenticate_ssh(str(address), password)


def authenticate_ssh(host, password, port=22):
    import paramiko
    client=paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host,port=port,username='root',password=password,
            allow_agent=False,look_for_keys=False,timeout=8,banner_timeout=8,auth_timeout=8)
        return client.get_transport().is_authenticated()
    except Exception:
        raise RuntimeError('Live guest SSH password login failed. Inspect the guest SSH service and authentication logs.') from None
    finally:
        client.close()


def repair_bridge_firewall(bridge_info, persist=True):
    """Scoped IPv4 rules only; never flush tables or change global chain policy."""
    import re
    import shutil
    import sys
    from pathlib import Path
    bridge=bridge_info['bridge']
    subnet=str(ipaddress.ip_network(bridge_info['subnet']))
    routes=subprocess.run(['ip','-j','-4','route','show','default'],capture_output=True,text=True,timeout=10,check=True)
    uplink=next((route.get('dev') for route in json.loads(routes.stdout) if route.get('dev') and route.get('dev')!=bridge),None)
    if not uplink or not all(re.fullmatch(r'[A-Za-z0-9_.:-]{1,32}',name) for name in (bridge,uplink)):
        raise RuntimeError('Could not identify the host default-route interface.')
    if not shutil.which('iptables'):
        raise RuntimeError('iptables is unavailable. Inspect the node firewall; no rules were changed.')
    def run(args):
        return subprocess.run(args,text=True,capture_output=True,timeout=15)
    def allow(chain,rule):
        if run(['iptables','-w','5','-C',chain]+rule).returncode:
            result=run(['iptables','-w','5','-I',chain,'1']+rule)
            if result.returncode:raise RuntimeError('Could not install a scoped bridge firewall rule.')
    forward=[['-i',bridge,'-o',uplink,'-s',subnet,'-j','ACCEPT'],
             ['-i',uplink,'-o',bridge,'-d',subnet,'-m','conntrack','--ctstate','ESTABLISHED,RELATED','-j','ACCEPT']]
    chains=['FORWARD']
    if run(['iptables','-w','5','-S','DOCKER-USER']).returncode==0:chains.append('DOCKER-USER')
    for chain in chains:
        for rule in forward:allow(chain,rule)
    for protocol,port in [('udp','67'),('udp','53'),('tcp','53')]:
        allow('INPUT',['-i',bridge,'-p',protocol,'--dport',port,'-j','ACCEPT'])
    result=run(['sysctl','-w','net.ipv4.ip_forward=1'])
    if result.returncode:raise RuntimeError('Could not enable host IPv4 forwarding.')
    if persist:
        root=Path(__file__).resolve().parent
        policy=root/'network_policy.json'
        existing=json.loads(policy.read_text()) if policy.exists() else {'bridges':{}}
        existing['bridges'][bridge]=bridge_info
        policy.write_text(json.dumps(existing,indent=2)+'\n');policy.chmod(0o600)
        Path('/etc/sysctl.d/90-hvm-forwarding.conf').write_text('net.ipv4.ip_forward=1\n')
        if shutil.which('systemctl') and Path('/run/systemd/system').exists():
            # systemd syntax has no shell; quote paths and escape literal percent signs.
            def unit_arg(value):return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
            unit='[Unit]\nDescription=HVM scoped bridge connectivity rules\nAfter=network-online.target snap.lxd.daemon.service docker.service ufw.service firewalld.service\nWants=network-online.target\nBefore=hvm-panel.service\n\n[Service]\nType=oneshot\nExecStart='+unit_arg(sys.executable)+' '+unit_arg(root/'node_network.py')+' --restore-policy\nRemainAfterExit=yes\n\n[Install]\nWantedBy=multi-user.target\n'
            Path('/etc/systemd/system/hvm-network.service').write_text(unit)
            for args in (['systemctl','daemon-reload'],['systemctl','enable','hvm-network.service']):
                result=run(args)
                if result.returncode:raise RuntimeError('Rules applied, but boot persistence could not be enabled.')
    return {'bridge':bridge,'uplink':uplink,'subnet':subnet,'firewall_rules':'applied','persistent':persist}


def host_diagnostics():
    checks={
        'forwarding':['sysctl','net.ipv4.ip_forward'],
        'bridge_networks':['lxc','network','list','--format=json'],
        'forward_rules':['iptables','-S','FORWARD'],
        'docker_rules':['iptables','-S','DOCKER-USER'],
    }
    result={}
    for label,args in checks.items():
        try:
            process=subprocess.run(args,capture_output=True,text=True,timeout=15)
            result[label]=(process.stdout or process.stderr).strip()[:6000]
        except Exception:result[label]='unavailable'
    return result


if __name__=='__main__':
    import sys
    from pathlib import Path
    if sys.argv[1:] != ['--restore-policy']:
        raise SystemExit('Use hvmctl.py for diagnostics and guest repair.')
    policy=Path(__file__).resolve().parent/'network_policy.json'
    for info in json.loads(policy.read_text()).get('bridges',{}).values():
        result=subprocess.run(['lxc','query','/1.0/networks/'+info['bridge']],capture_output=True,text=True,timeout=20,check=True)
        network=json.loads(result.stdout)
        subnet=str(ipaddress.ip_interface(network.get('config',{}).get('ipv4.address','none')).network)
        if not network.get('managed') or network.get('type')!='bridge' or subnet!=info['subnet']:
            raise SystemExit('Managed bridge changed; run explicit network repair again.')
        repair_bridge_firewall(info,persist=False)


def verify_local_guest_key_login(container, username):
    """Verify the live key-only daemon with a short-lived probe key, then remove it.

    User private keys never reach the panel. This checks the selected account and
    SSH policy; the user's public key is validated and installed separately.
    """
    import paramiko
    import re
    import shlex
    import uuid
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,62}',container) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}',username):
        raise ValueError('Invalid guest or account name.')
    state=json.loads(subprocess.run(['lxc','query',f'/1.0/instances/{container}/state'],capture_output=True,text=True,timeout=20,check=True).stdout)
    host=next((a['address'] for a in state.get('network',{}).get('eth0',{}).get('addresses',[]) if a.get('family')=='inet' and a.get('scope')=='global'),None)
    if not host:raise RuntimeError('No guest IPv4 for SSH key verification.')
    ipaddress.IPv4Address(host)
    key=paramiko.RSAKey.generate(2048)
    marker='hvm-probe-'+uuid.uuid4().hex
    setup='''set -eu
user=USER_NAME
home=$(getent passwd "$user" | cut -d: -f6)
[ -n "$home" ] && [ -d "$home/.ssh" ] && [ ! -L "$home/.ssh" ] && [ ! -L "$home/.ssh/authorized_keys" ]
umask 077
cat >> "$home/.ssh/authorized_keys"
chown "$user:$(id -gn "$user")" "$home/.ssh/authorized_keys"
chmod 600 "$home/.ssh/authorized_keys"
'''.replace('USER_NAME',shlex.quote(username))
    cleanup='''set -eu
user=USER_NAME
home=$(getent passwd "$user" | cut -d: -f6)
[ -n "$home" ] && [ -d "$home/.ssh" ] && [ ! -L "$home/.ssh" ] && [ ! -L "$home/.ssh/authorized_keys" ]
sed -i '/ MARKER$/d' "$home/.ssh/authorized_keys"
'''.replace('USER_NAME',shlex.quote(username)).replace('MARKER',marker)
    client=paramiko.SSHClient();client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        subprocess.run(['lxc','exec',container,'--','sh','-c',setup],input='\n'+key.get_name()+' '+key.get_base64()+' '+marker+'\n',capture_output=True,text=True,check=True,timeout=20)
        client.connect(host,username=username,pkey=key,allow_agent=False,look_for_keys=False,timeout=8,banner_timeout=8,auth_timeout=8)
        return client.get_transport().is_authenticated()
    except Exception:
        raise RuntimeError('Live guest SSH key authentication failed.') from None
    finally:
        client.close()
        result=subprocess.run(['lxc','exec',container,'--','sh','-c',cleanup],capture_output=True,text=True,timeout=20)
        if result.returncode:raise RuntimeError('SSH probe key cleanup failed; inspect guest authorized_keys before retrying.')
