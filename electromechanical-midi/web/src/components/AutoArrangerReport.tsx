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
        <Bucket title="Tonal (FDD + VHS)" bucket={report.tonal} />
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
