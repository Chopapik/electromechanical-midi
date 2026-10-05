import { render, screen, cleanup } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { HardwareStatus } from './HardwareStatus'
import { arduinoStatus } from './TelemetryMonitor'
import type { HardwareState, PlayerState } from '../types'
afterEach(cleanup)
const hardware: HardwareState = { connected:true, homed:false, fddStatus:'error', ready:false, port:'/dev/uno', label:'Uno', error:'FDD: HOME_FAILED', warning:null, log:[] }
test('position error shows connected Arduino and Retry Home', () => {
 render(<HardwareStatus hardware={hardware} ports={[]} onHome={vi.fn()} onReconnect={vi.fn()} />)
 expect(screen.getByText('Arduino connected')).toBeTruthy()
 expect(screen.getByRole('button',{name:'Retry Home'}).hasAttribute('disabled')).toBe(false)
 expect(screen.queryByText('Arduino disconnected')).toBeNull()
})
test('footer distinguishes connected Serial from FDD homing/error', () => {
 expect(arduinoStatus({hardware} as PlayerState)).toBe('Arduino connected · FDD: Error — Retry Home')
 expect(arduinoStatus({hardware:{...hardware,fddStatus:'homing'}} as PlayerState)).toBe('Arduino connected · FDD: Homing…')
 expect(arduinoStatus({hardware:{...hardware,connected:false}} as PlayerState)).toBe('Arduino disconnected')
})
