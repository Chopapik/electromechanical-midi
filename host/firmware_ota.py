"""Private per-installation OTA key and reproducible service build inputs."""
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def key_path():
    return Path(os.getenv('ORCHESTRA_OTA_KEY',str(ROOT/'config/.runtime/ble-ota-key')))


def read_key():
    data=key_path().read_bytes()
    if len(data)!=32:raise RuntimeError('Nieprawidłowy prywatny klucz BLE OTA (wymagane 32 bajty)')
    return data


def prepare_build(project):
    """Provision once; retain across rebuilds. Never log or commit this key."""
    path=key_path();path.parent.mkdir(parents=True,exist_ok=True)
    try:
        descriptor=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:pass
    else:
        from ecdsa import SigningKey, NIST256p
        with os.fdopen(descriptor,'wb') as output:output.write(SigningKey.generate(curve=NIST256p).to_string())
    key=read_key()
    from ecdsa import SigningKey, NIST256p
    public=b'\x04'+SigningKey.from_string(key,curve=NIST256p).verifying_key.to_string()
    generated=Path(project)/'.generated';generated.mkdir(exist_ok=True)
    header=generated/'ble_ota_key.h'
    content=('// Private generated input; never commit or publish.\n'
             'constexpr bool keyProvisioned=true;\n'
             'constexpr uint8_t installationPublicKey[65]={'+','.join(str(value) for value in public)+'};\n')
    # Avoid unnecessary recompilation, preserve restrictive permissions.
    if not header.exists() or header.read_text()!=content:
        descriptor=os.open(header,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
        with os.fdopen(descriptor,'w') as output:output.write(content)
    return key


def image_path(project):
    return Path(project)/'.pio/build/esp32/firmware.bin'
