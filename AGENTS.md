# Local application deployment

After implementing changes to the web application, backend, configuration, or
firmware bundled in the application, rebuild and restart the `orchestra`
container with `docker compose up -d --build orchestra` so the user can see the
changes immediately. Verify that the container is healthy and the running
application serves the new version before reporting completion.

# ATX power and ESP32 uploads

Never run a direct `pio run -t upload` (or call `run_firmware` with an upload
port) for ESP32 maintenance. Use the running local application's shared
DeviceService procedure: `.venv/bin/python scripts/safe_upload.py` (or Settings
→ Serwis → Wgraj firmware ESP32), only when the user has authorized flashing.
It requires confirmed ALL STOP and correlated POWER OFF, waits after GPIO19 LOW,
releases BLE, checks USB, builds/uploads, and recovers BLE without POWER ON.
Missing communication or POWER OFF acknowledgement must abort the upload.
Never bypass this barrier by assuming that the ATX rails have discharged.

First installation on firmware without POWER requires a separately authorized
manual bootstrap with ATX physically switched off/disconnected and the ESP32 / SR
power-domain issue reviewed. The normal automatic procedure deliberately refuses
this case; obtain the user's hardware confirmation and a reviewed bootstrap plan
before any exceptional upload. GPIO19 feedback is logical only, not voltage
measurement. Do not turn ATX on or move actuators as part of software verification.
