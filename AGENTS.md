# Commit descriptions

Every commit must have a concise, descriptive subject and a short body explaining
what changed, why, and which components or behavior are affected. Include relevant
validation results and material limitations, especially whether hardware changes
were tested only offline or in VIRTUAL rather than on physical devices.
Keep the description specific and self-contained so a person or AI can understand
the commit without reading its diff. Avoid vague summaries and exhaustive file lists.

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
For firmware already provisioned with BLE OTA, use the same shared procedure
with `scripts/safe_upload.py --transport ble` (or Settings → Serwis → Wgraj
firmware przez BLE). Never call the raw BLE upload transport directly: it must
run under DeviceService exclusivity after confirmed STOP and POWER OFF. Music
and OTA share a BLE session in mutually exclusive modes. Do not run instruments
to test an upload. Preserve the private OTA signing key in the settings volume;
never log, commit or transmit it over BLE. The firmware contains only its public
verification key. First provisioning still requires the authorized USB procedure.
It requires confirmed ALL STOP and correlated POWER OFF, waits after GPIO19 LOW,
releases BLE, checks USB, builds/uploads, and recovers BLE without POWER ON.
The BLE path retains exclusive ownership of the link, builds the image, verifies
its signed manifest/SHA-256 in the inactive application slot, commits the boot
selection and recovers BLE without POWER ON. It never uploads bootloader or
partition-table changes and never retries an unconfirmed transfer automatically.
Missing communication or POWER OFF acknowledgement must abort the upload.
Never bypass this barrier by assuming that the ATX rails have discharged.

First installation on firmware without POWER requires a separately authorized
manual bootstrap with ATX physically switched off/disconnected and the ESP32 / SR
power-domain issue reviewed. The normal automatic procedure deliberately refuses
this case; obtain the user's hardware confirmation and a reviewed bootstrap plan
before any exceptional upload. GPIO19 feedback is logical only, not voltage
measurement. Do not turn ATX on or move actuators as part of software verification.
