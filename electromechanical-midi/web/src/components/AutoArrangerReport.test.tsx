import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { AutoArrangerReport } from './AutoArrangerReport'
import type { ArrangementReport } from '../types'

const bucket = (over: Partial<ArrangementReport['tonal']> = {}): ArrangementReport['tonal'] => ({
  kind: 'tonal', requested: 100, played: 80, dropped: 20, onTime: 60,
  reassigned: 30, delayed: 10, arpeggiated: 5, stolen: 3, shortened: 4,
  folded: 2, dropRate: 0.2, meanDelayMs: 12, maxDelayMs: 40,
  retention: 0.8, activeTime: 100, utilization: 0.75, ...over,
})

const report: ArrangementReport = {
  sourceEvents: 150,
  lead: { requested: 40, played: 40, dropped: 0, delayed: 6, preservation: 1 },
  leadDevices: { devices: ['vhs-1'], notes: 40, nonLeadEvents: 0, clean: true },
  tonal: bucket(),
  percussion: bucket({ kind: 'percussion', requested: 50, played: 45, dropped: 5 }),
  devices: [
    { deviceId: 'fdd-1', type: 'FDD', notes: 400, dropped: 10, activeTime: 180, utilization: 0.79 },
    { deviceId: 'hdd-1', type: 'HDD_VCM', notes: 90, dropped: 2, activeTime: 40, utilization: 0.3 },
  ],
  totals: {
    requested: 150, played: 125, dropped: 25, dropRate: 0.1667, retention: 0.8333,
    delayed: 10, arpeggiated: 5, reassigned: 30, voiceSteals: 3, shortened: 4,
    folded: 2, meanDelayMs: 12.5, maxDelayMs: 40,
  },
  duration: 200,
}

afterEach(cleanup)

describe('AutoArrangerReport', () => {
  it('pokazuje metryki ratowania nut i wynik globalny', () => {
    render(<AutoArrangerReport report={report} origin="auto" />)

    expect(screen.getByText('Tonal (FDD + VHS)')).toBeDefined()
    expect(screen.getByText('Percussion (HDD)')).toBeDefined()
    expect(screen.getByText('16.7%')).toBeDefined()      // drop rate
    expect(screen.getByText('auto')).toBeDefined()
    // reassigned pojawia sie i w bucketcie, i w sekcji mechanizmow ratunkowych
    expect(screen.getAllByText('reassigned').length).toBeGreaterThan(0)
    // Dedykowane urzadzenie leadu musi byc widoczne razem z licznikiem naruszen.
    expect(screen.getByText('Lead (dedykowane urzadzenie)')).toBeDefined()
    expect(screen.getByText('non-lead on VHS')).toBeDefined()
    expect(screen.getByText('100.0%')).toBeDefined()
  })

  it('pokazuje zero naruszen rozdzialu rol', () => {
    render(<AutoArrangerReport report={report} origin="auto" />)
    const cell = screen.getByText('non-lead on VHS').nextElementSibling
    expect(cell?.textContent).toBe('0')
    expect(cell?.className).not.toContain('report-bad')
  })

  it('oznacza reczny override i pokazuje wykorzystanie urzadzen', () => {
    render(<AutoArrangerReport report={report} origin="manual" />)

    expect(screen.getByText('manual override')).toBeDefined()
    expect(screen.getByText('fdd-1')).toBeDefined()
    expect(screen.getByText('79.0%')).toBeDefined()
  })

  it('nic nie renderuje bez raportu', () => {
    const { container } = render(<AutoArrangerReport report={null} />)
    expect(container.firstChild).toBeNull()
  })
})
