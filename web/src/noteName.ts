export function noteName(note:number|null){return note===null?'—':['C','C♯','D','D♯','E','F','F♯','G','G♯','A','A♯','B'][note%12]+(Math.floor(note/12)-1)}
