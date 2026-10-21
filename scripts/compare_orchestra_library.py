"""Compare complete, hash-identical eight-FDD library benchmark runs."""
import argparse,json
from pathlib import Path
from statistics import mean

def compare(before,after):
    old={r['file']:r for r in before['songs']};new={r['file']:r for r in after['songs']}
    if len(old)!=before['files'] or len(new)!=after['files'] or set(old)!=set(new):
        raise ValueError('Both runs must cover every identical library path')
    rows=[]
    keys=('playedTonal','droppedTonal','sourceVoiceDurationCoverage','weightedOnsetCoverage',
          'leadCoverage','bassCoverage','unrepresentedPartWindows','playedDrums','hddHits',
          'dvdStops','dvdWorkSeconds','dvdLongestContinuousSeconds','planningSeconds')
    for name in sorted(old):
        a,b=old[name],new[name]
        if a['sha256']!=b['sha256']:raise ValueError('MIDI changed: '+name)
        if 'error' in a or 'error' in b:raise ValueError('Benchmark error: '+name+str((a.get('error'),b.get('error'))))
        a,b=a['metrics'],b['metrics']
        checks={'sameConfiguration':a['configurationFingerprint']==b['configurationFingerprint'],
                'mechanicalLimits':not any(b[k] for k in ('mechanicalConflicts','overlaps','fddAttackViolations','unisonGroupMismatches'))}
        if not all(checks.values()):raise ValueError('Invariant failed: '+str((name,checks)))
        # Counts describe source note identity, never copies made for unison.
        important=lambda m:sum(m['drumClassCoverage'].get(str(n),0) for n in (35,36,37,38,39,40))
        rows.append({'file':name,'sha256':old[name]['sha256'],'before':{k:a[k] for k in keys},
                     'after':{k:b[k] for k in keys},'checks':checks,
                     'kickSnareHitsBefore':important(a),'kickSnareHitsAfter':important(b)})
    summary={'files':len(rows),'uniqueMidi':after['uniqueMidi'],'allPhysicalChecksPass':True,
             'songsWithMoreSourceAttacks':sum(r['after']['playedTonal']>r['before']['playedTonal'] for r in rows),
             'songsWithMoreSourceDuration':sum(r['after']['sourceVoiceDurationCoverage']>r['before']['sourceVoiceDurationCoverage']+1e-6 for r in rows),
             'sourceAttackRegressions':[r['file'] for r in rows if r['after']['playedTonal']<r['before']['playedTonal']],
             'sourceDurationRegressions':[r['file'] for r in rows if r['after']['sourceVoiceDurationCoverage']<r['before']['sourceVoiceDurationCoverage']-1e-6],
             'leadCoverageRegressions':[r['file'] for r in rows if r['after']['leadCoverage']<r['before']['leadCoverage']-1e-6],
             'bassCoverageRegressions':[r['file'] for r in rows if r['after']['bassCoverage']<r['before']['bassCoverage']-1e-6]}
    for label in ('before','after'):
        values=[r[label] for r in rows]
        summary[label]={k:sum(m[k] for m in values) for k in ('playedTonal','droppedTonal','playedDrums','hddHits','dvdStops','unrepresentedPartWindows')}
        summary[label].update(meanSourceVoiceDurationCoverage=mean(m['sourceVoiceDurationCoverage'] for m in values),
                              meanLeadCoverage=mean(m['leadCoverage'] for m in values),
                              meanBassCoverage=mean(m['bassCoverage'] for m in values),
                              kickSnareHits=sum(r['kickSnareHitsBefore' if label=='before' else 'kickSnareHitsAfter'] for r in rows),
                              dvdLongestContinuousSeconds=max(m['dvdLongestContinuousSeconds'] for m in values),
                              dvdWorkSeconds=round(sum(m['dvdWorkSeconds'] for m in values),3),
                              totalPlanningSeconds=round(sum(m['planningSeconds'] for m in values),3),
                              maxPlanningSeconds=max(m['planningSeconds'] for m in values))
    return {'scope':'offline planning and compiled timelines; acoustic and thermal performance unmeasured',
            'summary':summary,'songs':rows}
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('baseline','experiment','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();report=compare(json.loads(a.baseline.read_text()),json.loads(a.experiment.read_text()))
    a.output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(report['summary'],indent=2,ensure_ascii=False))
