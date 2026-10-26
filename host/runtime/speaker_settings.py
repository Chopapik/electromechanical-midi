"""Persistence for the existing speaker preference file, separate from devices."""
import json
import os
import tempfile
from pathlib import Path

DEFAULT_PATH=Path(__file__).resolve().parents[2]/'config/.runtime/speaker-volumes.json'


class SpeakerSettingsStore:
    def __init__(self,path=None):
        self.path=Path(path or os.getenv('ORCHESTRA_SPEAKER_SETTINGS') or DEFAULT_PATH)

    def load(self):
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def save(self,values):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(mode='w',dir=self.path.parent,delete=False) as stream:
                temporary=Path(stream.name)
                json.dump(values,stream,indent=2)
            temporary.replace(self.path)
        finally:
            if temporary is not None:temporary.unlink(missing_ok=True)
