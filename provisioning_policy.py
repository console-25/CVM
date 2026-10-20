"""Server-side creation and guest access validation, independent of Flask."""
import base64
import re
import struct


def validate_public_key(value):
    if not isinstance(value,str) or len(value)>12000 or '\n' in value.strip() or '\r' in value or '\0' in value:
        raise ValueError('Paste one OpenSSH public key, not a private key or authorized_keys options.')
    parts=value.strip().split()
    supported={'ssh-ed25519','ssh-rsa','ecdsa-sha2-nistp256','ecdsa-sha2-nistp384','ecdsa-sha2-nistp521'}
    if len(parts)<2 or parts[0] not in supported:
        raise ValueError('Use an Ed25519, RSA (2048+ bit), or ECDSA OpenSSH public key.')
    try:
        import paramiko
        blob=base64.b64decode(parts[1],validate=True)
        key=paramiko.PKey.from_type_string(parts[0],blob)
        if key.get_name()!=parts[0] or (parts[0]=='ssh-rsa' and key.get_bits()<2048):raise ValueError()
    except Exception:
        raise ValueError('The public key is invalid or too weak. Generate an Ed25519 or RSA 2048+ bit key.') from None
    return parts[0]+' '+parts[1]


def validate_access(data):
    mode=data.get('access_mode','password')  # Preserve the existing API contract.
    if mode not in ('key','password'):raise ValueError('Choose SSH key or generated password access.')
    username=data.get('ssh_username','root')
    if not isinstance(username,str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}',username):
        raise ValueError('SSH username must start with a lowercase letter and contain 1–32 letters, digits, underscores or hyphens.')
    if username in {'daemon','bin','sys','sync','games','man','lp','mail','news','uucp','proxy','www-data','backup','list','irc','nobody','sshd','systemd-network','systemd-resolve'}:
        raise ValueError('Choose root or a new personal account name, not a system account.')
    if mode=='password' and username!='root':raise ValueError('Generated password access currently uses root. Choose SSH key access for a personal username.')
    return {'mode':mode,'username':username,'public_key':validate_public_key(data.get('ssh_public_key','')) if mode=='key' else ''}


def validate_creation(data,os_options):
    if not isinstance(data,dict):raise ValueError('Send a JSON configuration object.')
    values={}
    for key,low,high,default in [('user_id',1,2147483647,None),('node_id',1,2147483647,None),('cpu',1,64,2),('ram',1,128,2),('disk',5,2000,20),('expiration_days',0,3650,0),('bandwidth_quota_gb',0,10000,0),('snapshot_limit',0,50,5)]:
        raw=data.get(key,default)
        if isinstance(raw,bool) or not re.fullmatch(r'[0-9]+',str(raw)):
            raise ValueError(f'{key.replace("_"," ").capitalize()} must be a whole number.')
        values[key]=int(raw)
        if not low<=values[key]<=high:raise ValueError(f'{key.replace("_"," ").capitalize()} must be between {low} and {high}.')
    for key in ('kvm_enabled','auto_suspend_enabled'):
        if key in data and not isinstance(data[key],bool):raise ValueError(f'{key} must be true or false.')
    image=data.get('os_version','ubuntu:22.04')
    if image not in {row['value'] for row in os_options}:raise ValueError('Choose a supported operating system image.')
    hostname=data.get('hostname')
    if hostname and (not isinstance(hostname,str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,61}[a-z0-9]|[a-z]',hostname)):
        raise ValueError('Hostname must be 1–63 lowercase letters, digits or hyphens, start with a letter and end with a letter or digit.')
    if data.get('auto_suspend_enabled') and values['expiration_days']==0:raise ValueError('Expiration must be at least one day when enabled.')
    values['access']=validate_access(data)
    return values
