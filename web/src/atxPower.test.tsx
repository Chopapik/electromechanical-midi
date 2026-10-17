import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {MemoryRouter} from 'react-router-dom'
import {SettingsPage} from './SettingsPage'
import type {useRuntime} from './runtime'

afterEach(()=>{cleanup();vi.restoreAllMocks()})
function setup(state='OFF',available=true,busy=false,error:string|null=null){
 const send=vi.fn()
 const app={connected:true,send,firmwareEvents:[],state:{devices:[],output:{mode:'REAL',muted:[]},service:{busy,power:{state,available,operation:busy?'firmware':null,error,measured:false,reason:busy?'DeviceService jest zajęty':null},firmware:{available:false},home:{available:false},reset:{reason:'offline'}}}} as unknown as ReturnType<typeof useRuntime>
 render(<MemoryRouter><SettingsPage app={app}/></MemoryRouter>)
 return send
}
it('requires confirmation for ON, and OFF sends a separate service command',()=>{
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(false),send=setup()
 fireEvent.click(screen.getByRole('button',{name:'Włącz ATX'}));expect(send).not.toHaveBeenCalled()
 confirm.mockReturnValue(true)
 fireEvent.click(screen.getByRole('button',{name:'Włącz ATX'}))
 expect(send).toHaveBeenCalledWith('service',{operation:'power_on',confirmed:true})
 fireEvent.click(screen.getByRole('button',{name:'Wyłącz ATX'}))
 expect(send).toHaveBeenCalledWith('service',{operation:'power_off'})
 expect(screen.getByText('Stan logiczny: OFF')).toBeTruthy()
 expect(screen.getByText(/bez pomiaru napięcia/)).toBeTruthy()
})
it.each(['UNKNOWN','UNAVAILABLE'])('shows %s and disables unavailable controls',state=>{
 const send=setup(state,false)
 expect(screen.getByText(`Stan logiczny: ${state}`)).toBeTruthy()
 expect((screen.getByRole('button',{name:'Włącz ATX'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'Wyłącz ATX'}));expect(send).not.toHaveBeenCalled()
})
it('blocks both controls during firmware work and shows an actionable error',()=>{
 const send=setup('UNKNOWN',false,true,'Brak potwierdzenia POWER OFF')
 expect(screen.getByText('Operacja: Flashowanie firmware')).toBeTruthy()
 expect(screen.getByRole('alert').textContent).toContain('Brak potwierdzenia POWER OFF')
 for(const name of ['Włącz ATX','Wyłącz ATX']){
  expect((screen.getByRole('button',{name}) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('button',{name}))
 }
 expect(send).not.toHaveBeenCalled()
})
it('does not send POWER ON from mounting an ON state',()=>{
 const send=setup('ON')
 expect((screen.getByRole('button',{name:'Włącz ATX'}) as HTMLButtonElement).disabled).toBe(true)
 expect(send).not.toHaveBeenCalled()
})
