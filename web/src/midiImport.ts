import {parseFileList,parseUploadResult,type FileEntry,type MidiLoading} from './contracts'
import type {RuntimeClient} from './runtimeClient'
interface Callbacks {loading:(loading:MidiLoading|null)=>void;files:(files:FileEntry[])=>void;error:(error:string|null)=>void}

/** STOP acknowledgement precedes HTTP import and installing the new plan. */
export class MidiImportProcess {
  private busy=false
  private disposed=false
  private abort=new AbortController()
  constructor(private client:RuntimeClient,private callbacks:Callbacks){}
  async refresh(){
    try{
      const files=parseFileList(await fetch('/api/files').then(r=>r.json()))
      if(!this.disposed)this.callbacks.files(files)
    }catch(error){if(!this.disposed)this.callbacks.error(String(error))}
  }
  async upload(file:File){
    if(this.busy||this.disposed)return
    this.busy=true;this.callbacks.error(null);this.callbacks.loading({name:file.name,stage:'stopping'})
    try{
      await this.client.command('stop')
      if(this.disposed)return
      this.callbacks.loading({name:file.name,stage:'uploading'})
      const data=new FormData();data.append('file',file)
      const response=await fetch('/api/files',{method:'POST',body:data,signal:this.abort.signal})
      const result=await response.json()
      if(!response.ok)throw new Error(result.detail)
      if(this.disposed)return
      this.callbacks.loading({name:file.name,stage:'planning'})
      await this.client.command('set_file',{file:parseUploadResult(result).name})
      await this.refresh()
    }catch(error){if(!this.disposed)this.callbacks.error(String(error))}
    finally{this.busy=false;if(!this.disposed)this.callbacks.loading(null)}
  }
  dispose(){this.disposed=true;this.abort.abort()}
}
