/**
 * Raport Auto Arrangera: ile nut udalo sie zagrac i czym je uratowano.
 *
 * Najwazniejsza metryka to dropRate - reszta pokazuje, KTORY mechanizm
 * ratunkowy zadzialal (reassignment, delay, voice steal).
 */

import type { ArrangementReport } from '../types'

const percent = (value: number) => `${(value * 100).toFixed(1)}%`

function Bucket({ title, bucket }: { title: string; bucket: ArrangementReport['tonal'] }) {
  if (!bucket.requested) return null

  return (
    <div className="report-bucket">
      <h4>{title}</h4>
      <dl>
        <dt>requested</dt><dd>{bucket.requested}</dd>
        <dt>played</dt><dd>{bucket.played}</dd>
        <dt>on time</dt><dd>{bucket.onTime}</dd>
        <dt>reassigned</dt><dd>{bucket.reassigned}</dd>
        <dt>delayed</dt><dd>{bucket.delayed}</dd>
        <dt>arpeggiated</dt><dd>{bucket.arpeggiated}</dd>
        <dt>stolen</dt><dd>{bucket.stolen}</dd>
        <dt>dropped</dt><dd className={bucket.dropped ? 'report-bad' : ''}>{bucket.dropped}</dd>
        <dt>utilization</dt><dd>{percent(bucket.utilization)}</dd>
      </dl>
    </div>
  )
}

export function AutoArrangerReport({ report, origin }: {
  report: ArrangementReport | null | undefined
  origin?: string | null
}) {
  if (!report) return null

  const { totals } = report

  return (
    <section className="auto-report" aria-label="Auto Arranger report">
      <header className="auto-report-head">
        <h3>Auto Arranger</h3>
        <span className={`pill ${origin === 'manual' ? 'paused' : 'playing'}`}>
          {origin === 'manual' ? 'manual override' : 'auto'}
        </span>
        <span className="muted">
          {report.sourceEvents} source events · played {totals.played} ·
          drop rate <strong className={totals.dropRate > 0.2 ? 'report-bad' : ''}>{percent(totals.dropRate)}</strong>
        </span>
      </header>

      <div className="report-buckets">
        <div className="report-bucket">
          <h4>Lead (dedykowane urzadzenie)</h4>
          <dl>
            <dt>requested</dt><dd>{report.lead.requested}</dd>
            <dt>played</dt><dd>{report.lead.played}</dd>
            <dt>dropped</dt><dd className={report.lead.dropped ? 'report-bad' : ''}>{report.lead.dropped}</dd>
            <dt>preservation</dt><dd>{percent(report.lead.preservation)}</dd>
            <dt>device</dt><dd>{report.leadDevices.devices.join(', ') || '—'}</dd>
            <dt>VHS notes</dt><dd>{report.leadDevices.notes}</dd>
            <dt>non-lead on VHS</dt>
            <dd className={report.leadDevices.nonLeadEvents ? 'report-bad' : ''}>
              {report.leadDevices.nonLeadEvents}
            </dd>
          </dl>
        </div>
        <Bucket title="Tonal (FDD + DVD + VHS)" bucket={report.tonal} />
        <Bucket title="Percussion (HDD)" bucket={report.percussion} />
        <div className="report-bucket">
          <h4>Rescue mechanisms</h4>
          <dl>
            <dt>reassigned</dt><dd>{totals.reassigned}</dd>
            <dt>delayed</dt><dd>{totals.delayed}</dd>
            <dt>arpeggiated</dt><dd>{totals.arpeggiated}</dd>
            <dt>voice steals</dt><dd>{totals.voiceSteals}</dd>
            <dt>shortened</dt><dd>{totals.shortened}</dd>
            <dt>mean delay</dt><dd>{totals.meanDelayMs.toFixed(1)} ms</dd>
            <dt>max delay</dt><dd>{totals.maxDelayMs.toFixed(1)} ms</dd>
          </dl>
        </div>
      </div>

      {!!report.trackClassification?.some(track => track.noteCount > 0 && track.finalRole !== 'PERCUSSION') && <div className="report-bucket">
        <h4>Track classification</h4>
        <div className="track-classifications">{report.trackClassification
          .filter(track => track.noteCount > 0 && track.finalRole !== 'PERCUSSION')
          .map(track => <div key={track.index} className="track-classification">
            <strong>{track.index} — {track.name}</strong>{' · '}{track.finalRole}
            {' · '}{percent(track.confidence)}
            <span className="muted"> · GM {track.gmFamily ?? 'unknown'}
              {' · '}{track.monophonic ? 'monophonic' : 'polyphonic'}
              {' · '}{track.evidence.slice(0, 3).join('; ')}</span>
          </div>)}</div>
      </div>}

      {report.duplicates && report.duplicates.groupsFound > 0 && <div className="report-bucket report-duplicates">
        <h4>Duplicate detection (double-tracking)</h4>
        <p className="muted">
          {report.duplicates.groupsFound} groups · {report.duplicates.tracksCollapsed} tracks collapsed ·
          tonal events {report.duplicates.rawTonalEvents} → {report.duplicates.logicalTonalEvents}
          {' '}(−{report.duplicates.duplicateEventsCollapsed})
        </p>
        <dl>
          <dt>accompaniment demand</dt>
          <dd>{report.duplicates.accompanimentDemandSecondsBefore.toFixed(0)} s →{' '}
            {report.duplicates.accompanimentDemandSecondsAfter.toFixed(0)} s</dd>
          <dt>demand / accompaniment capacity</dt>
          <dd>{report.duplicates.demandCapacityBefore.toFixed(2)} →{' '}
            {report.duplicates.demandCapacityAfter.toFixed(2)}</dd>
        </dl>
        {report.duplicates.groups.map(group => <p key={group.groupId} className="muted">
          {group.tracks.map(track => group.names[String(track)] ?? track).join(' + ')}
          {' '}· confidence {group.confidence.toFixed(3)}
          {group.duplicates.map(track => ` · offset ${(
            group.medianOffsetsMs[String(track)] ?? 0).toFixed(2)} ms [${group.verdicts[String(track)]}]`).join('')}
        </p>)}
      </div>}

      {report.articulation && <div className="report-bucket">
        <h4>FDD mechanical sustain</h4>
        <dl>
          <dt>notes extended</dt><dd>{report.articulation.extended}</dd>
          <dt>mean extension</dt><dd>+{report.articulation.meanExtensionMs.toFixed(0)} ms</dd>
          <dt>max extension</dt><dd>+{report.articulation.maxExtensionMs.toFixed(0)} ms</dd>
          <dt>added sustain</dt><dd>{report.articulation.addedSeconds.toFixed(0)} s</dd>
          <dt>target length</dt><dd>{report.articulation.params.preferredMechanicalSustainMs} ms</dd>
        </dl>
      </div>}

      {report.continuity && <div className="report-bucket">
        <h4>Continuity</h4>
        <dl>
          <dt>silent gaps</dt><dd>{report.continuity.silentGapCount}</dd>
          <dt>audible gaps &gt;150 ms</dt><dd>{report.continuity.longGapCount}</dd>
          <dt>orchestra silent</dt><dd>{report.continuity.orchestraSilentTime.toFixed(1)} s</dd>
          <dt>planned coverage</dt><dd>{percent(report.continuity.plannedCoverage)}</dd>
          {report.continuity.accompanimentContinuity !== undefined && <>
            <dt>accompaniment continuity</dt>
            <dd>{percent(report.continuity.accompanimentContinuity)}</dd>
          </>}
        </dl>
      </div>}

      {report.devices.length > 0 && <table className="report-devices">
        <thead>
          <tr><th>device</th><th>type</th><th>notes</th><th>active</th><th>utilization</th></tr>
        </thead>
        <tbody>
          {report.devices.map(device => <tr key={device.deviceId}>
            <td>{device.deviceId}</td>
            <td>{device.type}</td>
            <td>{device.notes}</td>
            <td>{device.activeTime.toFixed(0)} s</td>
            <td>
              <span className="util-bar" style={{ width: `${Math.min(100, device.utilization * 100)}%` }} />
              {percent(device.utilization)}
            </td>
          </tr>)}
        </tbody>
      </table>}
    </section>
  )
}
