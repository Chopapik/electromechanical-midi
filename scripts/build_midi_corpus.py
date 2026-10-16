"""Read-only MIDI corpus inventory with byte deduplication and grouped holdout."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'host'))
from midi_source import MidiSource


def composition(name):
    """Dataset grouping only; never consulted by the arranger.

    Keep known live/acoustic/alternate versions together. This uses titles for
    experimental leakage prevention, not song-specific orchestration rules.
    """
    name=Path(name).stem.lower()
    name=re.sub(r'^\d{4}-(?:\d{2}-)?radiohead[-_]\d{4}[-_]','radiohead ',name)
    name=re.sub(r'\[[^]]*\]|\([^)]*\)',' ',name)
    name=name.replace('_',' ')
    name=re.sub(r'[- ]\d+$','',name)
    name=re.sub(r'[^a-z0-9]+','',name)
    # Variants without a separator before an artist are normalized as well.
    return name


def build(roots, previous=()):
    hashes=defaultdict(list)
    for root in roots:
        if not Path(root).is_dir():raise FileNotFoundError(root)
        for path in sorted(Path(root).rglob('*')):
            if path.is_file() and path.suffix.lower() in ('.mid','.midi'):
                hashes[hashlib.sha256(path.read_bytes()).hexdigest()].append(path)
    rows=[];errors=[]
    for sha,aliases in sorted(hashes.items(),key=lambda row:str(row[1][0])):
        path=aliases[0]
        try:
            source=MidiSource(path)
            notes=sorted((t.index,n.channel,n.note,round(n.start,6),round(n.duration,6),n.velocity)
                         for t in source.tracks for n in source.notes(t.index))
            musical=hashlib.sha256(json.dumps(notes).encode()).hexdigest()
            # Prefer a numbered Radiohead title to an imported alias filename.
            candidates=sorted(aliases,key=lambda p:(not bool(re.match(r'^\d{4}-',p.name)),str(p)))
            group=composition(candidates[0].name)
            rows.append({'file':path.name,'path':str(path),'sha256':sha,
                'aliases':[str(p) for p in aliases], 'group':group,'musicHash':musical,
                'notes':len(notes),'duration':source.duration})
        except Exception as exc:errors.append({'file':path.name,'sha256':sha,'error':str(exc)})
    # Byte-distinct metadata variants with exactly the same note representation
    # are grouped even if their import filenames differ.
    parent={r['group']:r['group'] for r in rows}
    def root(group):
        while parent[group]!=group:
            parent[group]=parent[parent[group]];group=parent[group]
        return group
    group_for_music={}
    for row in rows:
        other=group_for_music.setdefault(row['musicHash'],row['group'])
        a,b=root(row['group']),root(other)
        parent[max(a,b)]=min(a,b)
    for row in rows:row['group']=root(row['group'])
    previous=set(previous)
    known={r['group'] for r in rows if r['sha256'] in previous}
    for row in rows:
        held=int(hashlib.sha256(row['group'].encode()).hexdigest()[:8],16)%4==0
        row['split']='holdout' if held and row['group'] not in known else 'development'
    return {'files':sum(map(len,hashes.values())),'unique':len(rows),'errors':errors,
        'splits':dict(Counter(r['split'] for r in rows)),'songs':rows}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('roots',type=Path,nargs='+')
    p.add_argument('--previous',type=Path,default=ROOT/'reports/universal-corpus.json')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    previous=[r['sha256'] for r in json.loads(a.previous.read_text())] if a.previous.is_file() else []
    report=build(a.roots,previous)
    a.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='songs'},indent=2))
