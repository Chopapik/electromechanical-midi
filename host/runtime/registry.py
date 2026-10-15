"""The orchestra inventory; calibration values remain in hardware-profiles/."""
import copy
import json
import os
import math
import tempfile
from pathlib import Path
from playback.hardware_profiles import HardwareRegistry
from playback.orchestra import parse_orchestra

DEFAULT = Path(__file__).resolve().parents[2] / 'config/devices.json'

class DeviceRegistry:
    def __init__(self, path=DEFAULT, *, volume_path=None):
        self.volume_path = Path(volume_path or os.getenv('ORCHESTRA_SPEAKER_SETTINGS') or DEFAULT.parents[0]/'.runtime/speaker-volumes.json')
        self.document = json.loads(Path(path).read_text())
        if self.document['schemaVersion'] != 1:
            raise ValueError('Unsupported device registry')
        self.devices = self.document['devices']
        self.by_id = {d['id']: d for d in self.devices}
        lanes = [d['lane'] for d in self.devices]
        if len(self.by_id) != len(self.devices) or len(set(lanes)) != len(lanes):
            raise ValueError('Device IDs and lanes must be unique')
        self.profiles = HardwareRegistry()
        counts = {}
        for d in self.devices:
            family = {'FDD':'fdd','DVD_SLED':'sled','HDD_VCM':'hdd','VHS':'drum','DVD_TRAY':'tray'}[d['type']]
            counts[family] = counts.get(family, 0) + 1
            # Existing allocator uses stable physical ordinals, including disabled devices.
            if d['lane'] != f'{family}:{counts[family]}' or counts[family] > {'fdd':4,'sled':4,'hdd':4,'drum':2,'tray':2}[family]:
                raise ValueError('Registry order must retain existing physical lane IDs')
            self.profile(d['id'])
        if self.volume_path.exists():
            saved = json.loads(self.volume_path.read_text())
            for ident, values in saved.items():
                if ident in self.by_id and self.by_id[ident]['type']=='VHS':
                    for output, key, default in [('VIRTUAL','volume',.6),('REAL','realAmplitude',50)]:
                        value = values.get(key, default)
                        self.validate_volume(ident, output, value)
                        self.by_id[ident][key] = value
                    waveform=values.get('waveform','pulse')
                    self.validate_waveform(ident,waveform)
                    self.by_id[ident]['waveform']=waveform
        self.configuration()  # Validate musical profile references as well.

    def validate_volume(self, ident, output, value):
        if ident not in self.by_id or self.by_id[ident]['type'] != 'VHS':
            raise ValueError('Volume control is only available for PC Speakers')
        if output not in ('REAL','VIRTUAL') or isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
            raise ValueError('Invalid speaker volume')
        maximum = 128 if output=='REAL' else 2.5
        if not 0 <= value <= maximum or (output=='REAL' and int(value)!=value):
            raise ValueError('Speaker volume outside range')

    def set_volume(self, ident, output, value):
        self.validate_volume(ident,output,value)
        key='realAmplitude' if output=='REAL' else 'volume'
        saved={d['id']:{'volume':d.get('volume',.6),'realAmplitude':d.get('realAmplitude',50),'waveform':d.get('waveform','pulse')}
               for d in self.devices if d['type']=='VHS'}
        saved[ident][key]=value
        self.save_speakers(saved)
        self.by_id[ident][key]=value

    def save_speakers(self,saved):
        self.volume_path.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w',dir=self.volume_path.parent,delete=False) as file:
            json.dump(saved,file,indent=2);temporary=Path(file.name)
        try: temporary.replace(self.volume_path)
        finally: temporary.unlink(missing_ok=True)

    def validate_waveform(self,ident,waveform):
        if ident not in self.by_id or self.by_id[ident]['type']!='VHS' or waveform not in ('pulse','sine','triangle','sawtooth'):
            raise ValueError('Invalid speaker waveform')

    def set_waveform(self,ident,waveform):
        self.validate_waveform(ident,waveform)
        saved={d['id']:{'volume':d.get('volume',.6),'realAmplitude':d.get('realAmplitude',50),'waveform':d.get('waveform','pulse')} for d in self.devices if d['type']=='VHS'}
        saved[ident]['waveform']=waveform
        self.save_speakers(saved);self.by_id[ident]['waveform']=waveform

    def profile(self, ident):
        d = self.by_id[ident]
        return self.profiles.effective(d['hardwareProfile'], d['lane']) if d['hardwareProfile'] else None

    def configuration(self):
        devices = []
        for d in self.devices:
            devices.append({k:copy.deepcopy(v) for k,v in d.items() if k not in ('lane','hardwareProfile')})
            # Compatibility field for the retained mechanical allocator, never an output choice.
            devices[-1].update(mode='real', mute=False, solo=False)
        return parse_orchestra({'name':self.document['name'], 'devices':devices,
            'policy':self.document.get('parameters',{}), 'dvdMode':self.document.get('dvdMode','independent'),
            'trayEnabled':any(d['enabled'] and d['type']=='DVD_TRAY' for d in self.devices),
            'idleReinforcement':self.document.get('idleReinforcement',{})})

    def catalog(self):
        result = []
        for d in self.devices:
            p = self.profile(d['id'])
            bands = p.get('allowedBandsHz') if p else None
            interval = p.get('musicalStepRate' if d['type']=='DVD_SLED' else 'musicalHz') if p else None
            bands = bands or ([interval] if interval else [])
            ratio = (p.get('pitchRatio') or 1) if p and d['type']=='DVD_SLED' else 1
            bands = [[max(lo,interval[0])*ratio,min(hi,interval[1])*ratio] if interval else [lo*ratio,hi*ratio] for lo,hi in bands]
            continuous=bool(p and p.get('continuousRotation'))
            if continuous: bands=[]
            result.append({**d, 'bands':bands, 'continuousRotation':continuous, 'reason':None if d['enabled'] and p else 'Brak potwierdzonego profilu lub obecności w registry'})
        return result

class PlanningProfiles:
    """Physical capabilities declared in JSON, independent of connection state."""
    def __init__(self, devices): self.devices = devices
    def present(self, lane):
        return any(d['lane']==lane and d['enabled'] for d in self.devices.devices)
    def profile_for(self, device, lane): return self.devices.profile(device.id)
