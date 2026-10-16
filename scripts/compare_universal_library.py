"""Compare frozen Universal revisions on the complete, grouped MIDI corpus."""
import argparse
import json
from pathlib import Path
from statistics import mean


def compare(corpus, baseline, experiment):
    old={s['sha256']:s for s in baseline['songs']}
    new={s['sha256']:s for s in experiment['songs']}
    expected={s['sha256'] for s in corpus['songs']}
    if set(old)!=expected or set(new)!=expected:
        raise ValueError('Both runs must cover the complete identical corpus')
    rows=[]
    for song in corpus['songs']:
        sha=song['sha256'];a=old[sha]['metrics'];b=new[sha]['metrics']
        checks={
            'configurationIdentical':a['configurationFingerprint']==b['configurationFingerprint'],
            'backboneTimelineIdentical':a['timelineFingerprint']==b['backboneTimelineFingerprint'],
            'originalPlayedEventsIdentical':b['originalPlayedEventsIdentical'],
            'originalReinforcementsIdentical':b['originalReinforcementsIdentical'],
            'originalArticulationIdentical':b['originalArticulationIdentical'],
            'importantIdsPreserved':set(a['retainedImportantIds'])<=set(b['retainedImportantIds']),
            'drumsIdentical':a['drumFingerprint']==b['drumFingerprint'],
            'noNewDroppedTonalNotes':b['droppedTonal']<=a['droppedTonal'],
            'coverageNondecreasing':b['sourceVoiceDurationCoverage']+1e-6>=a['sourceDurationCoverage'],
            'physicalChecksPass':not any(b[k] for k in
                ('fddAttackViolations','overlaps','mechanicalConflicts'))}
        if not all(checks.values()):raise AssertionError((song['file'],checks))
        keys=('playedTonal','droppedTonal','sourceDurationCoverage','weightedOnsetCoverage',
            'unrepresentedPartWindows','dvdStops','dvdWorkSeconds','dvdLongestContinuousSeconds','planningSeconds')
        before={k:a[k] for k in keys};before['sourceVoiceDurationCoverage']=a['sourceDurationCoverage']
        after={k:b[k] for k in keys};after['sourceVoiceDurationCoverage']=b['sourceVoiceDurationCoverage']
        recovery={k:v for k,v in b['recovery'].items() if k!='backboneTimelineFingerprint'}
        rows.append({'file':song['file'],'sha256':sha,'split':song['split'],
            'before':before,'after':after,'recovery':recovery,'checks':checks})
    summaries={}
    for cohort in ('all','development','holdout'):
        selected=[r for r in rows if cohort=='all' or r['split']==cohort]
        summaries[cohort]={'songs':len(selected),'allChecksPass':all(all(r['checks'].values()) for r in selected),
            'songsWithMoreAttacks':sum(r['after']['playedTonal']>r['before']['playedTonal'] for r in selected),
            'songsWithMoreSourceDuration':sum(r['after']['sourceVoiceDurationCoverage']>r['before']['sourceVoiceDurationCoverage']+1e-6 for r in selected),
            'recoveredAttacks':sum(r['recovery']['recovered'] for r in selected),
            'lateSustainEntries':sum(r['recovery']['lateSustainEntries'] for r in selected),
            'continuations':sum(r['recovery']['continuations'] for r in selected),
            'continuationSeconds':round(sum(r['recovery']['continuationSeconds'] for r in selected),3)}
        for label in ('before','after'):
            summaries[cohort][label]={
                **{k:sum(r[label][k] for r in selected) for k in ('playedTonal','droppedTonal','dvdStops')},
                'meanSourceVoiceDurationCoverage':round(mean(r[label]['sourceVoiceDurationCoverage'] for r in selected),6),
                'dvdWorkSeconds':round(sum(r[label]['dvdWorkSeconds'] for r in selected),3),
                'dvdLongestContinuousSeconds':max(r[label]['dvdLongestContinuousSeconds'] for r in selected)}
    return {'scope':'offline software benchmark; REAL and acoustic/thermal performance untested',
        'baselineRevision':'98bad14','corpusFiles':corpus['files'],'uniqueMidi':corpus['unique'],
        'configurationFingerprint':next(iter(new.values()))['metrics']['configurationFingerprint'],
        'coverageDefinition':'mean per MIDI; union of primary and CONTINUATION clipped to original source gate',
        'summaries':summaries,'songs':rows}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('corpus','baseline','experiment','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();report=compare(*(json.loads(path.read_text()) for path in (a.corpus,a.baseline,a.experiment)))
    a.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report['summaries'],indent=2))
