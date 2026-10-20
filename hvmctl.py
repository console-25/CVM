#!/usr/bin/env python3
"""Local, data-preserving guest access diagnostics and repair."""
import argparse
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
from dotenv import load_dotenv
from cryptography.fernet import Fernet
from guest_access import GuestAccess, GuestAccessError, configure_key_access
from runtime_config import persistent_secret
from node_network import prepare_local_bridge, verify_local_guest_login, repair_bridge_firewall, host_diagnostics, verify_local_guest_key_login

ROOT = Path(__file__).resolve().parent


def command(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, timeout=kwargs.pop('timeout', 30), **kwargs)
    if result.returncode:
        raise GuestAccessError('LXD operation failed. Check the container, bridge and LXD service locally.')
    return result.stdout


async def operate(args):
    os.chdir(ROOT)
    load_dotenv(ROOT / '.env')
    database = Path(os.environ.get('DATABASE_PATH', 'hvm.db')).resolve()
    if not database.is_file():
        raise GuestAccessError('Panel database not found; run this from the installed panel directory.')
    with sqlite3.connect(f'file:{database}?mode=rw', uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute('SELECT v.*, n.is_local FROM vps v JOIN nodes n ON n.id=v.node_id WHERE v.container_name=?', (args.container,)).fetchall()
        if len(rows) != 1 or not rows[0]['is_local']:
            raise GuestAccessError('Expected one panel-managed VPS on this local node.')
        vps = dict(rows[0])
        info = json.loads(command(['lxc','query',f'/1.0/instances/{args.container}/state']))
        if info.get('status', '').lower() != 'running':
            raise GuestAccessError('Container must already be running. This tool never recreates or deletes it.')
        async def run(script, timeout):
            return await asyncio.to_thread(command, ['lxc','exec',args.container,'--','sh','-c',script], timeout=timeout)
        async def password(value):
            await asyncio.to_thread(command, ['lxc','exec',args.container,'--','chpasswd'], input='root:'+value+'\n', timeout=20)
        async def verify(value):
            return await asyncio.to_thread(verify_local_guest_login,args.container,value)
        async def verify_key(username):
            return await asyncio.to_thread(verify_local_guest_key_login,args.container,username)
        metadata = json.loads(vps.get('metadata') or '{}')
        service = GuestAccess(run, password, verify_login=verify, verify_key=verify_key)
        service.repair_network = metadata.get('network_mode') != 'existing'
        before = await service.diagnostics()
        if args.action == 'doctor':
            print(json.dumps({'container': args.container, 'health':before}, indent=2))
            return
        if not args.network and not args.ssh:
            raise GuestAccessError('Choose --network and/or --ssh for repair.')
        if args.network and not service.repair_network:
            if args.repair_host_firewall or args.enable_bridge_dhcp_nat:
                raise GuestAccessError('Existing profile network mode preserves host and guest configuration. Use provider-specific repair.')
            await service.ensure_network(repair=False)
        if args.network and service.repair_network:
            bridge = await asyncio.to_thread(prepare_local_bridge,args.container)
            print('Managed bridge:',json.dumps(bridge))
            if args.repair_host_firewall:
                print('Host forwarding:',json.dumps(await asyncio.to_thread(repair_bridge_firewall,bridge)))
            await service.ensure_network(repair=True)
        metadata = json.loads(vps.get('metadata') or '{}')
        ssh_state = {}
        if args.ssh and metadata.get('access_policy',{}).get('mode') == 'key':
            policy=metadata['access_policy']
            ssh_state=await configure_key_access(service,policy['username'],policy['public_key'])
        elif args.ssh:
            key = base64.urlsafe_b64encode(hashlib.sha256(('hvm-node-cred::'+persistent_secret()).encode()).digest())
            cipher = Fernet(key)
            value = metadata.get('root_password') or secrets.token_urlsafe(24)
            if value.startswith('fernet:v1:'):
                try:
                    value = cipher.decrypt(value[len('fernet:v1:'):].encode()).decode()
                except Exception:
                    raise GuestAccessError('Cannot decrypt stored password. Restore the panel secret before repair.') from None
            ssh_state = await service.configure_ssh(value)
            metadata['root_password'] = 'fernet:v1:'+cipher.encrypt(value.encode()).decode()
        state = await service.diagnostics()
        if ssh_state.get('ssh_authenticated'):
            state['ssh_authenticated'] = True
        metadata['access_health'] = state
        if state['network_ready'] and state.get('outbound_ready') == 'yes' and state.get('ssh_authenticated'):
            metadata.pop('installation_error', None)
            metadata['installation_progress'] = 100
            metadata['installation_message'] = 'Access repair verified: outbound network and live SSH login ready.'
            db.execute('UPDATE vps SET status=?, metadata=? WHERE id=?', ('running',json.dumps(metadata),vps['id']))
        else:
            db.execute('UPDATE vps SET metadata=? WHERE id=?', (json.dumps(metadata),vps['id']))
        db.commit()
        if args.network and state.get('outbound_ready') != 'yes':
            raise GuestAccessError('Guest settings were repaired, but final outbound verification failed. Inspect node firewall diagnostics.')
        print(json.dumps({'container':args.container,'health':state,'message':'Repair completed. Use the access method selected for this guest.'},indent=2))


async def operate_all(args):
    os.chdir(ROOT)
    load_dotenv(ROOT / '.env')
    database=Path(os.environ.get('DATABASE_PATH','hvm.db')).resolve()
    with sqlite3.connect(f'file:{database}?mode=ro',uri=True) as db:
        names=[row[0] for row in db.execute('SELECT v.container_name FROM vps v JOIN nodes n ON n.id=v.node_id WHERE n.is_local=1')]
    if not names:
        raise GuestAccessError('No local panel-managed guests were found in this database.')
    states={item['name']:item.get('status','').lower() for item in json.loads(command(['lxc','list','--format=json']))}
    failures=[]
    for name in names:
        if states.get(name)!='running':
            print(name+': skipped (not running or absent)')
            continue
        args.container=name
        try:
            await operate(args)
        except Exception as exc:
            failures.append(name)
            print(name+': FAILED: '+str(exc))
    if failures:
        raise GuestAccessError('Repair incomplete for: '+', '.join(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['doctor','repair'])
    selection=parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--container')
    selection.add_argument('--all',action='store_true',help='Process all running panel-managed guests on this local node.')
    parser.add_argument('--network',action='store_true')
    parser.add_argument('--repair-host-firewall',action='store_true',help='Apply and persist bridge-scoped forwarding and DHCP/DNS rules; requires --network.')
    parser.add_argument('--ssh',action='store_true')
    parser.add_argument('--enable-bridge-dhcp-nat',action='store_true',help='Enable DHCP/NAT on the guest’s existing managed IPv4 bridge; affects all guests on that bridge.')
    args = parser.parse_args()
    if args.repair_host_firewall and (args.action != 'repair' or not args.network):
        parser.error('--repair-host-firewall requires repair --network')
    try:
        asyncio.run(operate_all(args) if args.all else operate(args))
    except Exception as exc:
        print('Access operation failed:', str(exc))
        print('Node diagnostics:', json.dumps(host_diagnostics(),indent=2))
        raise SystemExit(1)

if __name__ == '__main__':
    main()
