import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { InstrumentLab, type LabState } from './InstrumentLab'
import type { PlayerApi } from '../usePlayer'
afterEach(cleanup)
function player(overrides: Partial<LabState> = {}) {
  return { socketConnected: true, labCommand: vi.fn(), state: { hardware: { connected: true, controllerTarget: 'esp32' }, lab: { enabled:true,state:'idle',device:null,hz:null,duration:3,remaining:0,error:null,confirmed:false,catalog:[
    {id:'sled:1',name:'DVD 1',kind:'sled',available:true,reason:null,bands:[[50,120],[180,190],[270,300],[340,470]]},
    {id:'hdd:1',name:'HDD 1',kind:'hdd',available:true,reason:null,bands:[]},
  ], ...overrides } } } as unknown as PlayerApi
}
describe('Instrument Lab', () => {
  it('enters without autoplay and leaves safely; reentry does not replay', () => {
    const p=player(); const view=render(<InstrumentLab player={p} />)
    expect(p.labCommand).toHaveBeenCalledWith('lab_enter')
    expect(p.labCommand).not.toHaveBeenCalledWith('lab_start',expect.anything())
    view.unmount();expect(p.labCommand).toHaveBeenCalledWith('lab_leave')
    render(<InstrumentLab player={p} />)
    expect(p.labCommand).not.toHaveBeenCalledWith('lab_start',expect.anything())
  })
  it('offers allowed presets and sends explicit 392 Hz / 3 s, then STOP', () => {
    const p=player();render(<InstrumentLab player={p} />)
    expect(screen.queryByRole('button',{name:'220 Hz'})).toBeNull()
    fireEvent.click(screen.getByRole('button',{name:'PLAY'}))
    expect(p.labCommand).toHaveBeenCalledWith('lab_start',expect.objectContaining({device:'sled:1',hz:392,duration:3}))
    fireEvent.click(screen.getByRole('button',{name:'STOP'}))
    expect(p.labCommand).toHaveBeenCalledWith('lab_stop')
  })
  it('HDD has HIT with no tone inputs', () => {
    const p=player();render(<InstrumentLab player={p} />)
    fireEvent.change(screen.getByLabelText('Instrument'),{target:{value:'hdd:1'}})
    expect(screen.queryByLabelText('Częstotliwość')).toBeNull()
    fireEvent.click(screen.getByRole('button',{name:'HIT'}))
    expect(p.labCommand).toHaveBeenCalledWith('lab_start',expect.objectContaining({device:'hdd:1'}))
  })
  it('starting is shown until the backend confirms playback', () => {
    const p=player({state:'starting',device:'sled:1',hz:392,remaining:3})
    render(<InstrumentLab player={p} />)
    expect(screen.getByText(/starting · sled:1/)).toBeDefined()
    expect((screen.getByRole('button',{name:'PLAY'}) as HTMLButtonElement).disabled).toBe(true)
  })
  it('stores rating linked to the completed device and frequency', () => {
    localStorage.clear();const p=player({state:'stopped',device:'sled:1',hz:392,confirmed:true})
    render(<InstrumentLab player={p} />);fireEvent.click(screen.getByRole('button',{name:'RESONANCE'}))
    expect(JSON.parse(localStorage.getItem('instrument-lab-ratings-v1')!)[0]).toMatchObject({device:'sled:1',hz:392,rating:'RESONANCE'})
  })
})
