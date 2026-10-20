#!/usr/bin/env python3
"""Read-only LXD/panel inventory for review BEFORE any deletion.

No stop, delete, database write, or host configuration commands exist here.
Backups shown are records/files only, not proof that a restore works.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
from datetime import datetime,timezone
from urllib.parse import quote


def lxc(*args):
    result=subprocess.run(['lxc',*args],capture_output=True,text=True,timeout=45)
    if result.returncode:raise RuntimeError('LXD inventory failed: '+result.stderr.strip()[:500])
    return result.stdout


def collect(database):
    remotes=json.loads(lxc('remote','list','--format=json'))
    local=next((name for name,remote in remotes.items() if remote.get('Addr',remote.get('addr','')).startswith('unix:')),None)
    if not local:raise RuntimeError('No local Unix-socket LXD remote found. Inventory stopped without changes.')
    active=lxc('remote','get-default').strip()
    instances=json.loads(lxc('list',local+':','--all-projects','--format=json'))
    rows=[];backup_rows=[]
    with sqlite3.connect('file:'+quote(str(database.resolve()),safe='/')+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        rows=[dict(r) for r in db.execute('SELECT v.id,v.container_name,v.node_id,v.user_id,v.whitelisted,u.username,n.name AS node_name FROM vps v JOIN nodes n ON n.id=v.node_id LEFT JOIN users u ON u.id=v.user_id WHERE n.is_local=1')]
        if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='backups'").fetchone():
            backup_rows=[dict(r) for r in db.execute('SELECT vps_id,name,path,size,status,created_at FROM backups')]
    inventory=[];seen=set()
    for item in instances:
        name=item['name'];project=item.get('project','default')
        matches=[r for r in rows if r['container_name']==name] if project=='default' else []
        owner=matches[0] if len(matches)==1 else None
        if owner:seen.add(owner['id'])
        state=item.get('state') or {};disk=state.get('disk',{})
        used=sum(v.get('usage',0) for v in disk.values() if isinstance(v.get('usage'),int)) if disk else None
        backup_info=[]
        for record in backup_rows:
            if owner and record['vps_id']==owner['id']:
                file=Path(record['path']);backup_info.append({'name':record['name'],'created_at':record['created_at'],'status':record['status'],'recorded_bytes':record['size'],'file_exists_on_panel_host':file.is_file(),'restore_verified':False})
        inventory.append({'project':project,'name':name,'type':item.get('type'),'status':item.get('status'),'storage_used_bytes':used,'storage_pools':sorted({dev['pool'] for dev in item.get('expanded_devices',{}).values() if dev.get('type')=='disk' and dev.get('pool')}),'panel_record':owner,'classification':'protected-panel-instance' if owner and owner['whitelisted'] else 'panel-managed-needs-review' if owner else 'unrelated-or-ambiguous-do-not-delete','lxd_delete_protection':item.get('expanded_config',{}).get('security.protection.delete','false'),'snapshot_count':len(item.get('snapshots',[])),'backups':backup_info,'criticality':'Unknown: owner must verify services before approval'})
    return {'host':socket.gethostname(),'collected_at':datetime.now(timezone.utc).isoformat(),'active_remote':active,'inspected_remote':local,'inspected_address':'unix://','instances':inventory,'panel_records_without_local_instance':[r for r in rows if r['id'] not in seen],'deletion_performed':False,'review_required':'Deleting a guest can permanently destroy its files, snapshots and configuration. Verify export backups and critical services. Approve exact project/name pairs only after reviewing this inventory.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--database',default=str(Path(__file__).resolve().parent/'hvm.db'));args=parser.parse_args()
    try:print(json.dumps(collect(Path(args.database)),indent=2))
    except Exception as exc:raise SystemExit(str(exc))
