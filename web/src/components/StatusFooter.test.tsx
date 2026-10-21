import {afterEach,describe,it,expect,vi} from 'vitest'
import {cleanup,render,screen,within} from '@testing-library/react'
import {MemoryRouter} from 'react-router-dom'
import {StatusFooter} from './StatusFooter'
import type {State,useRuntime} from '../runtime'
afterEach(cleanup)
function app(){return {connected:true,error:null,state:{owner:'lab',error:null,devices:[{id:'fdd-8',name:'FDD 8'}],laboratory:{active:{}},output:{mode:'REAL',connected:true,unknown:false,message:'',muted:[]}} as unknown as State,send:vi.fn()} as unknown as ReturnType<typeof useRuntime>}
function mount(a:ReturnType<typeof useRuntime>){return render(<MemoryRouter><StatusFooter app={a}/></MemoryRouter>)}
describe('Laboratory footer',()=>{
 it('shows homing for the actual laboratory device',()=>{
  const a=app();a.state!.laboratory!.active['fdd-8']={homing:true} as never
  mount(a);expect(screen.getByRole('status').textContent).toContain('Laboratorium · homing FDD 8 · STOP przerywa')
  expect(screen.getByRole('status').textContent).not.toContain('przed utworem')
 })
 it('explains home failure while preserving raw details and STOP uncertainty',()=>{
  const a=app();a.state!.output.unknown=true;a.state!.error='Nieznany stan sprzętu. ERR HOME_FAILED FDD=8'
  mount(a);expect(screen.getByRole('status').textContent).toContain('brak potwierdzenia STOP')
  expect(screen.getByRole('alert').textContent).toContain('FDD 8: nie udało się zaparkować głowicy')
  expect(screen.getByText('Szczegóły techniczne')).toBeTruthy()
  expect(screen.getByText(a.state!.error!)).toBeTruthy()
 })
 it('deduplicates identical errors and keeps them inside the footer',()=>{
  const a=app();a.error=a.state!.error='Profil nie dopuszcza testu'
  mount(a);expect(screen.getAllByRole('alert')).toHaveLength(1)
  expect(within(screen.getByRole('contentinfo')).getAllByText('Profil nie dopuszcza testu')).toHaveLength(1)
 })
 it('explains timeout without claiming a STOP acknowledgement',()=>{
  const a=app();a.state!.error='FDD 8: homing TRACK0 nie został potwierdzony'
  mount(a);expect(screen.getByRole('alert').textContent).toContain('upłynął czas oczekiwania na TRACK0')
  expect(screen.getByRole('alert').textContent).not.toContain('STOP potwierdzony')
 })
 it('clears stale alerts after a fresh successful state and prioritizes disconnect',()=>{
  const a=app();a.error='Błąd testu';const view=mount(a)
  expect(screen.getByRole('alert')).toBeTruthy()
  a.error=null;a.connected=false
  view.rerender(<MemoryRouter><StatusFooter app={a}/></MemoryRouter>)
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.getByRole('status').textContent).toContain('Brak połączenia z aplikacją')
 })
})
