import {afterEach,it,expect,vi} from 'vitest'
import {cleanup,render,screen,fireEvent} from '@testing-library/react'
import {MuteGroups} from './MuteGroups'
import type {useRuntime} from '../runtime'
afterEach(cleanup)
it('sends a single explicit group request and can unmute a whole bank',()=>{
 const send=vi.fn()
 const app={connected:true,send,pendingActions:[],state:{devices:Array.from({length:8},(_,i)=>({id:`fdd-${i+1}`,type:'FDD',enabled:true})),service:{busy:false},output:{muted:['fdd-1']}}} as unknown as ReturnType<typeof useRuntime>
 const view=render(<MuteGroups app={app}/>)
 fireEvent.click(screen.getByRole('button',{name:'Wycisz FDD 1–4'}))
 expect(send).toHaveBeenCalledOnce()
 expect(send).toHaveBeenCalledWith('mute_group',{deviceIds:['fdd-1','fdd-2','fdd-3','fdd-4'],muted:true})
 app.state!.output.muted=['fdd-1','fdd-2','fdd-3','fdd-4']
 view.rerender(<MuteGroups app={app}/>)
 fireEvent.click(screen.getByRole('button',{name:'Włącz FDD 1–4'}))
 expect(send).toHaveBeenLastCalledWith('mute_group',{deviceIds:['fdd-1','fdd-2','fdd-3','fdd-4'],muted:false})
 expect(screen.getByRole('button',{name:'Wycisz Wszystkie FDD'})).toBeTruthy()
})
