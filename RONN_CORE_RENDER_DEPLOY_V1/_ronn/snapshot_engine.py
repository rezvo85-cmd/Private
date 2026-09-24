import hashlib
import json
import os
import time
from pathlib import Path

BASE=Path(__file__).resolve().parent
ROOT=BASE/'data'/'snapshots'
ROOT.mkdir(parents=True,exist_ok=True)
MAX_SNAPSHOTS_PER_PROJECT=max(5,min(100,int(os.getenv("RONN_SNAPSHOT_MAX_PER_PROJECT","20") or "20")))


def _safe(value):
    return ''.join(ch if ch.isalnum() or ch in '-_.' else '_' for ch in str(value or 'default'))[:120] or 'default'


def _sha(text):
    return hashlib.sha256((text or '').encode('utf-8',errors='ignore')).hexdigest()


def _prune_folder(folder: Path):
    files=sorted(
        [p for p in folder.glob("*.json") if p.is_file()],
        key=lambda p:p.stat().st_mtime,
        reverse=True,
    )
    removed=0
    for p in files[MAX_SNAPSHOTS_PER_PROJECT:]:
        try:
            p.unlink()
            removed+=1
        except OSError:
            pass
    return removed


def create_snapshot(owner,project_id,files,label='checkpoint'):
    rows=[]
    for f in list(files or [])[:40]:
        name=getattr(f,'name','file') or 'file'
        content=getattr(f,'content','') or ''
        rows.append({'name':name[:220],'sha256':_sha(content),'chars':len(content),'content':content[:120000]})
    stamp=int(time.time()*1000)
    sid=f"{stamp}_{_safe(label)}"
    folder=ROOT/_safe(owner)/_safe(project_id)
    folder.mkdir(parents=True,exist_ok=True)
    payload={'snapshot_id':sid,'owner':owner,'project_id':project_id,'label':label[:120],'created':time.time(),'files':rows}
    path=folder/f'{sid}.json'
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    pruned=_prune_folder(folder)
    return {'snapshot_id':sid,'label':label,'files':len(rows),'path':str(path),'created':payload['created'],'pruned':pruned}


def list_snapshots(owner,project_id,limit=30):
    folder=ROOT/_safe(owner)/_safe(project_id)
    if not folder.exists():return []
    limit=max(1,min(int(limit),MAX_SNAPSHOTS_PER_PROJECT))
    out=[]
    for p in sorted(folder.glob('*.json'),key=lambda x:x.stat().st_mtime,reverse=True)[:limit]:
        try:
            d=json.loads(p.read_text(encoding='utf-8'))
            out.append({'snapshot_id':d.get('snapshot_id'),'label':d.get('label'),'created':d.get('created'),'files':len(d.get('files') or [])})
        except Exception: pass
    return out


def load_snapshot(owner,project_id,snapshot_id):
    p=ROOT/_safe(owner)/_safe(project_id)/f'{_safe(snapshot_id)}.json'
    if not p.exists():return None
    try:return json.loads(p.read_text(encoding='utf-8'))
    except Exception:return None


def compare_snapshot(snapshot,files):
    before={x['name']:x for x in (snapshot or {}).get('files',[])}
    after={getattr(f,'name','file') or 'file':getattr(f,'content','') or '' for f in list(files or [])}
    names=sorted(set(before)|set(after))
    changes=[]
    for name in names:
        b=before.get(name); a=after.get(name)
        if b is None: changes.append({'name':name,'state':'added','before_sha':None,'after_sha':_sha(a)})
        elif a is None: changes.append({'name':name,'state':'removed','before_sha':b.get('sha256'),'after_sha':None})
        else:
            ah=_sha(a)
            if ah!=b.get('sha256'):
                changes.append({'name':name,'state':'modified','before_sha':b.get('sha256'),'after_sha':ah,'before_chars':b.get('chars'),'after_chars':len(a)})
    return {'changed':len(changes),'changes':changes}


def restore_bundle(snapshot):
    if not snapshot:return ''
    parts=['RONN SNAPSHOT RESTORE BUNDLE','This bundle contains the text state captured at the checkpoint.']
    for f in snapshot.get('files',[]):
        parts += ['',f"--- FILE: {f.get('name','file')} ---",f.get('content',''),f"--- END FILE: {f.get('name','file')} ---"]
    return '\n'.join(parts)
