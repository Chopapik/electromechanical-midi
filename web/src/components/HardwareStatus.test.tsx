import { render, screen, cleanup, fireEvent } from '@testing-library/react'
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

const ports = [
 { device: '/dev/cu.Bluetooth-Incoming-Port', label: 'Serial', usbId: '', score: 5 },
 { device: '/dev/cu.usbserial-esp32', label: 'CP2102', usbId: '10c4:ea60', score: 105 },
]
test('ambiguous ports require explicit selection and connect with selected device', () => {
 const connect = vi.fn(); const refresh = vi.fn()
 render(<HardwareStatus hardware={{...hardware, connected:false, port:null}} ports={ports}
   onHome={vi.fn()} onReconnect={connect} onRefreshPorts={refresh} />)
 const select=screen.getByRole('combobox',{name:'Port szeregowy'})
 expect((select as HTMLSelectElement).value).toBe('')
 expect(screen.getByRole('button',{name:'Połącz'}).hasAttribute('disabled')).toBe(true)
 fireEvent.change(select,{target:{value:ports[1].device}})
 expect(connect).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('button',{name:'Połącz'}))
 expect(connect).toHaveBeenCalledWith(ports[1].device)
 fireEvent.click(screen.getByRole('button',{name:'Odśwież porty'}))
 expect(refresh).toHaveBeenCalledOnce()
})
test('single device is selectable; absent ports show empty state', () => {
 const {rerender}=render(<HardwareStatus hardware={null} ports={ports.slice(1)} onHome={vi.fn()} onReconnect={vi.fn()} />)
 expect(screen.getByRole('combobox',{name:'Port szeregowy'}).hasAttribute('disabled')).toBe(false)
 rerender(<HardwareStatus hardware={null} ports={[]} onHome={vi.fn()} onReconnect={vi.fn()} />)
 expect(screen.getByText('Brak wykrytych portów')).toBeTruthy()
 expect(screen.getByRole('combobox',{name:'Port szeregowy'}).hasAttribute('disabled')).toBe(true)
})
