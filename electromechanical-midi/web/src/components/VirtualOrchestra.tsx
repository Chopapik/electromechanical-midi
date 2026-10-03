import { useEffect, useState } from 'react'
import type { ArrangementHardware, DeviceMode, FileMetadata, VirtualConfig, VirtualDevice, VirtualState } from '../types'

const KINDS = ['FDD', 'DVD_SLED', 'STEPPER_FREE', 'VHS', 'HDD_VCM', 'SOLENOID_RESONATOR']
const LABEL: Record<string, string> = {
  FDD: 'FDD', DVD_SLED: 'DVD sled', STEPPER_FREE: 'Free stepper',
  VHS: 'VHS motor', HDD_VCM: 'HDD VCM', SOLENOID_RESONATOR: 'Solenoid + resonator',
}
const MODE_LABEL: Record<DeviceMode, string> = {
  virtual: 'virtual — only simulation + audio preview',
  real: 'real — only physical hardware',
  hybrid: 'hybrid — hardware + preview',
}
const LANE_LABEL: Record<string, string> = {
  fdd: 'FDD (PLAY/STOP)', drum: 'VHS drum (DRUM/DRUMF)', hdd: 'HDD (HIT)',
}

interface Props {
  virtual?: VirtualState
  metadata: FileMetadata | null
  configure: (config: VirtualConfig, enabled: boolean) => void
  arrangementActive?: boolean
  hardware?: ArrangementHardware
}

export function VirtualOrchestra({ virtual, metadata, configure, arrangementActive, hardware }: Props) {
  const [presets, setPresets] = useState<Record<string, VirtualConfig>>({})
  const [selectedPreset, setSelectedPreset] = useState('')
  const [notice, setNotice] = useState('')
  const config = virtual?.config ?? { name: 'Virtual Orchestra', devices: [] }
  const enabled = virtual?.enabled ?? false
  const refresh = () => fetch('/api/virtual/presets').then(r => r.json()).then(data => setPresets(data.presets ?? {})).catch(() => setNotice('Could not load presets'))
  useEffect(() => { refresh() }, [])

  const apply = (devices: VirtualDevice[], active = enabled) => configure({ ...config, devices }, active)
  const add = (type: string) => {
    const count = config.devices.filter(d => d.type === type).length + 1
    const id = globalThis.crypto?.randomUUID?.() ?? `${type}-${Date.now()}`
    apply([...config.devices, {
      id, type, name: `${LABEL[type]} #${count}`, track: metadata?.tracks.find(t => t.noteCount > 0)?.index ?? null,
      role: '', volume: .6, pan: 0, mute: false, solo: false, transpose: 0, gate: 1,
      profile: virtual?.profiles.find(p => p.kind === type)?.id ?? '', mode: 'virtual', overrides: {},
    }], true)  }
  const update = (id: string, patch: Partial<VirtualDevice>) => apply(config.devices.map(d => d.id === id ? { ...d, ...patch } : d))
  const duplicate = (device: VirtualDevice) => {
    const id = globalThis.crypto?.randomUUID?.() ?? `${device.type}-${Date.now()}`
    apply([...config.devices, { ...device, id, name: `${device.name} copy` }])
  }
  const changeParameter = (device: VirtualDevice, key: string, patch: Partial<{ value: number | null; provenance: string; source: string }>) => {
    const original = device.overrides?.[key] ?? { value: null, provenance: 'ESTIMATED', source: '' }
    update(device.id, { overrides: { ...device.overrides, [key]: { ...original, ...patch } } })
  }
  const save = async () => {
    const name = window.prompt('Preset name', config.name)?.trim()
    if (!name) return
    const response = await fetch(`/api/virtual/presets/${encodeURIComponent(name)}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...config, name }),
    })
    if (!response.ok) { setNotice('Could not save preset'); return }
    const data = await response.json()
    setPresets(data.presets)
    setSelectedPreset(name)
    setNotice(`Saved ${name}`)
  }

  return <section className="virtual-orchestra">
    <h2>Virtual Orchestra</h2>
    <label className="virtual-toggle"><input type="checkbox" checked={enabled} onChange={e => configure(config, e.target.checked)} /> Virtual hardware output</label>
    <p className="muted">Host audio preview. Profiles marked UNKNOWN need calibration before predicting a physical build.</p>
    {hardware && <div className="virtual-hardware" role="status">
      <h3>Hardware lanes</h3>
      {hardware.active
        ? <>{Object.entries(hardware.lanes).map(([lane, device]) => <p key={lane} className="hardware-lane">
            <strong>{LANE_LABEL[lane] ?? lane}</strong> ← {device.name}{' '}
            <span className="muted">({device.type})</span>
          </p>)}
          {!hardware.connected && <p className="muted">No Arduino connected — lanes stay queued until you connect.</p>}</>
        : <p className="muted">No device drives physical hardware. Set a device <em>Mode</em> to <code>real</code> or <code>hybrid</code>.</p>}
      {hardware.unmapped.length > 0 && <>
        <p className="import-error">Not wired to hardware ({hardware.unmapped.length}):</p>
        <ul>{hardware.unmapped.map(item => <li key={item.deviceId}>{item.name} — {item.reason === 'LANE_TAKEN'
          ? `lane ${item.lane} already used by ${item.boundTo}` : 'no physical lane for this device type'}</li>)}</ul>
      </>}
    </div>}
    <div className="virtual-toolbar">
      <label>Add device <select aria-label="Add device" value="" onChange={e => { if (e.target.value) add(e.target.value) }}>
        <option value="">ADD DEVICE…</option>{KINDS.map(type => <option key={type} value={type}>{LABEL[type]}</option>)}
      </select></label>
      <button type="button" onClick={save}>Save preset</button>
      <select aria-label="Load preset" value={selectedPreset} onChange={e => {
        const name = e.target.value; setSelectedPreset(name)
        if (presets[name]) configure(presets[name], true)
      }}><option value="">Load preset…</option>{Object.keys(presets).map(name => <option key={name}>{name}</option>)}</select>
    </div>
    {notice && <p role="status">{notice}</p>}
    <div className="virtual-devices">{config.devices.map(device => {
      const profile = virtual?.profiles.find(p => p.id === device.profile)
      return <details key={device.id} className="virtual-device">
        <summary>{device.name} · {LABEL[device.type]}
          <span className={`device-led ${virtual?.activity?.[device.id] ? 'is-active' : ''}`}
            role="img" aria-label={`${device.name}: ${virtual?.activity?.[device.id] ? 'active' : 'idle'}`}
            title={virtual?.activity?.[device.id] ? 'Device active' : 'Device idle'} />
        </summary>
        <div className="virtual-device-controls">
          <label>Name <input value={device.name} onChange={e => update(device.id, { name: e.target.value })} /></label>
          <label>Role <input value={device.role} onChange={e => update(device.id, { role: e.target.value })} /></label>
          <label>Track <select disabled={arrangementActive} value={device.track ?? ''} onChange={e => update(device.id, { track: e.target.value === '' ? null : Number(e.target.value) })}>
            <option value="">None</option>{metadata?.tracks.filter(t => t.noteCount > 0).map(t => <option key={t.index} value={t.index}>{t.label}</option>)}
          </select></label>
          {arrangementActive && <span className="muted">Routing is edited in Arrangement.</span>}
          <label>Volume <input type="range" min="0" max="1" step="0.05" value={device.volume} onChange={e => update(device.id, { volume: Number(e.target.value) })} /></label>
          <label>Pan <input type="range" min="-1" max="1" step="0.1" value={device.pan} onChange={e => update(device.id, { pan: Number(e.target.value) })} /></label>
          <label><input type="checkbox" checked={device.mute} onChange={e => update(device.id, { mute: e.target.checked })} /> Mute</label>
          <label><input type="checkbox" checked={device.solo} onChange={e => update(device.id, { solo: e.target.checked })} /> Solo</label>
          <label>Transpose <input type="number" min="-48" max="48" value={device.transpose} onChange={e => update(device.id, { transpose: Number(e.target.value) })} /></label>
          <label>Gate <input type="number" min="0.1" max="2" step="0.1" value={device.gate} onChange={e => update(device.id, { gate: Number(e.target.value) })} /></label>
          <label>Profile <select value={device.profile} onChange={e => update(device.id, { profile: e.target.value })}>
            {virtual?.profiles.filter(p => p.kind === device.type).map(p => <option key={p.id}>{p.id}</option>)}
          </select></label>
          <label>Mode <select aria-label={`${device.name} mode`} value={device.mode ?? 'virtual'}
            onChange={e => update(device.id, { mode: e.target.value as DeviceMode })}>
            {(Object.keys(MODE_LABEL) as DeviceMode[]).map(mode => <option key={mode} value={mode}>{MODE_LABEL[mode]}</option>)}
          </select></label>
          <button type="button" onClick={() => duplicate(device)}>Duplicate</button>
          <button type="button" onClick={() => apply(config.devices.filter(d => d.id !== device.id))}>Remove</button>
        </div>
        {profile && <details className="virtual-parameters"><summary>Device profile · {profile.id}</summary>
          {Object.entries(profile.parameters).map(([key, base]) => {
            const parameter = device.overrides?.[key] ?? base
            return <div key={key} className="virtual-parameter">
              <label>{key} <input aria-label={`${device.name} ${key}`} type="number" step="any" min="0" disabled={key === 'polyphony'}
                placeholder={base.value === null ? 'unknown' : String(base.value)}
                value={device.overrides?.[key]?.value ?? ''}
                onChange={e => changeParameter(device, key, { value: e.target.value === '' ? null : Number(e.target.value) })} /></label>
              <select aria-label={`${device.name} ${key} provenance`} disabled={key === 'polyphony'} value={parameter.provenance}
                onChange={e => changeParameter(device, key, { provenance: e.target.value })}>
                {['CALIBRATED', 'MEASURED', 'RESEARCHED', 'ESTIMATED', 'UNKNOWN'].map(value => <option key={value}>{value}</option>)}
              </select>
              {device.overrides?.[key] ? <input aria-label={`${device.name} ${key} source`} placeholder="Source or measurement note" value={device.overrides[key].source}
                onChange={e => changeParameter(device, key, { source: e.target.value })} /> : <span className="muted">{base.source}</span>}
            </div>
          })}
        </details>}
      </details>
    })}</div>
    <h3>Simulation Report · full MIDI</h3>
    {Object.entries(virtual?.report ?? {}).length === 0 ? <p className="muted">Add devices and load MIDI to see mechanical constraints.</p> :
      <div className="virtual-reports">{Object.entries(virtual?.report ?? {}).map(([id, r]) => <article key={id}>
        <strong>{r.name}</strong> · accepted {r.accepted} · played {r.played} · dropped {r.dropped} · folded {r.folded} · delayed {r.delayed} · busy {r.busyConflicts}
        {r.type === 'FDD' || r.type === 'DVD_SLED' ? <> · steps {r.steps} · travel {r.travel} · reversals {r.reversals}</> : null}
        {r.type === 'HDD_VCM' ? <> · hits {r.acceptedHits}/{r.requestedHits} · dropped busy {r.droppedWhileBusy} · busy time {r.busyTime.toFixed(2)}s · max density {r.maxDensity.toFixed(1)}/s</> : null}
        {r.type === 'STEPPER_FREE' ? <> · active {r.activeTime.toFixed(2)}s</> : null}
        <div className="muted">{Object.entries(r.reasons).map(([code, count]) => `${code}: ${count}`).join(' · ')}</div>
      </article>)}</div>}
  </section>
}
