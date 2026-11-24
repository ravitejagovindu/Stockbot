# Android stage 4 report: the phone app connected to the BFF over Tailscale

## Summary

The app now reads the paper account from the BFF over Tailscale, and the BFF is **running** on the laptop for you to use. The real connection worked end to end, but **not from the Pixel 7**: the phone was not connected to adb during this work (see "What did not work"). I proved the app-to-BFF path on the configured Android emulator instead, which reaches the BFF through the laptop's own Tailscale address, and I proved the laptop side with the real token. **One part of the brief was not built:** the evening notification, because WorkManager is not in the Gradle cache (I stopped that part as instructed).

- Branch `android-connect` (pushed, not merged). Only files under `android\`, `docs\android\`, `bff\`, `tests\bff\`, `docs\bff\` changed, plus two rows in `docs\guides\CODEBASE_GUIDE.md`.
- Tailscale: laptop `100.125.195.111`, MagicDNS `laptop.tail0118ce.ts.net`; the phone ("Ravi's pixel", `100.70.125.33`) is online in the same tailnet.
- **BFF running:** pid **12136**, `http://100.125.195.111:8765` (port 8765 was free), started by `bff\start_bff.ps1` in a minimized detached window, log `F:\Projects\Ravi\StockBotData\logs\bff.log`. It binds only to the Tailscale address. **It will not survive a reboot or a Tailscale restart** (start it again with the script; starting it at boot is for a later stage).
- Android: `gradlew test assembleDebug lintDebug --no-daemon` BUILD SUCCESSFUL; 84 JVM tests, 0 failures; lint 0 errors and the same 5 warnings. APK: `F:\Projects\Ravi\StockBotData\android\stockbot-paper-debug.apk`.
- BFF: `py -m pytest tests\bff` 227 passed; guide test only: 11 passed, 1 skipped. The full suite was not run.
- Scheduler service pid **9100** unchanged; nothing in `state\` or `locks\` was created or changed.

## What was built

**Part A, the laptop side**
- Found the Tailscale address and name with the CLI (`tailscale ip -4`, `tailscale status --json`).
- Read how FInsight is reached (read only): its dev server listens on 0.0.0.0:8000 and its backend on port 9000; reachability over Tailscale comes from two enabled inbound allow rules named "Tailscale-In" (profiles Domain and Private, any port, local address = the Tailscale address), and the Tailscale adapter is on the Private profile. **Nothing was changed.**
- `bff\start_bff.ps1` (finds the address and name itself, host = the Tailscale address, allowed hosts = address, MagicDNS name, localhost, 127.0.0.1, refuses a second copy or a busy port, starts `run.py` in a new minimized window with the Python 3.13 path and the main folder as working directory, never touches the token) and `bff\stop_bff.ps1` (stops only the process whose command line is `bff\run.py`). Two rows added to `CODEBASE_GUIDE.md`.
- **Firewall:** no new rule. The existing "Tailscale-In" rules already allow inbound to the Tailscale address on the profile the Tailscale adapter uses, which is an equivalent (broader) rule, and the real connection test confirms TCP 8765 is reachable on it. This shell is not elevated, so a new rule could not have been created anyway; the exact command, should it ever be needed, is in `docs\android\CONNECTION.md`.
- Tests: `tests\bff\test_scripts_and_hosts.py` (static checks of both scripts: never all interfaces, address inside 100.64.0.0/10, no token handling, one `Stop-Process` only; and the Host-header rule for the Tailscale address and name).

**Part B, the app**
- **Manifest:** only `INTERNET`. A network security config: everything https-only except `100.125.195.111` and `laptop.tail0118ce.ts.net` (no subdomains, no wildcards), because Tailscale already encrypts the link. A test checks the XML against the constants in the code and checks that the manifest has exactly that one permission.
- **Connection screen** (opened from the top bar, both themes): server address (default `http://100.125.195.111:8765`), masked token (paste allowed; empty keeps the saved one), "Test connection" (one line: "Connected. Data as of 23 Nov 2026.", "The token was not accepted.", "Can't reach your laptop.", "The laptop answered, but the data is not ready yet."), and the "Use sample data" switch (on by default; debug builds keep the scenario menu). Address in DataStore; token encrypted with an Android Keystore AES-GCM key; neither is ever logged (the app has no log calls and a test checks that).
- **NetworkPaperRepository:** `HttpURLConnection` (no new dependency), 8 s timeouts, `X-Paper-Token`, one retry after a network error, the same contract parser as the mock path, the error body mapped to `ApiException`, apiVersion check, GET only. `isSample` is false for real data, so the "SAMPLE DATA" tag disappears.
- **Offline:** the last good body per screen is kept in app-private storage; when the laptop cannot be reached the app shows it with "Can't reach your laptop. Showing data from 24 Nov, 19:48." and Retry; with nothing kept, the usual one-line error. A wrong token or "not ready" is shown as an error, not hidden behind old data.
- **Refresh:** pull-to-refresh on every screen and a refresh when the app opens and when it comes back to the front.
- **Debug-only intent:** `--es server <url> --es token <token>` sets the connection and turns the sample data off; read once per launch and removed from the intent; release builds ignore it (documented in `docs\android\CONNECTION.md`).
- Tests (JVM): the repository against a real loopback HTTP server for 200, 401, 503, a non-contract 500, another apiVersion, a redirect, one retry then success, timeout, refused connection; the cache fallback and the screen loader's offline state; the connection test lines; the token store (round trip, file holds only encrypted text, undecryptable token reads as none, token never in a `toString`); address rules; the network security config and manifest.

**Not built (as the brief instructs): the evening notification.** WorkManager (`androidx.work`) is not in this laptop's Gradle cache and adding it would need a download, so I stopped that part: no Notifications switch, no `POST_NOTIFICATIONS`, no `RECEIVE_BOOT_COMPLETED`, and no notification decision function. Android may delay periodic checks when battery saver is on, which matters when it is built. (OkHttp 4.12 and `security-crypto` are in the cache but were not needed.)

## Part C results

1. **BFF started with the script** (pid 12136). From the laptop, `GET http://100.125.195.111:8765/v1/health` with the real token returned **200** (status ok, latest sealed date 2026-11-23); without the token 401; a second `start_bff.ps1` was refused ("already running", exit 2); `127.0.0.1:8765` is not served (bound to the Tailscale address only).
2. **The Pixel 7 was not connected:** `adb devices` listed nothing, and the adb mDNS discovery found no wireless-debugging service (a connect to the phone's Tailscale address on port 5555 was refused, which shows the phone is reachable over Tailscale but wireless debugging was not listening). So the install on the Pixel, the on-phone configuration and the on-phone screenshots were **skipped**. The new APK is at the path above; to install it yourself, switch on wireless debugging and run `adb install -r` (see `docs\android\CONNECTION.md`), or copy the APK to the phone and enter the token on the Connection screen.
3. **Stand-in test on the configured AVD** (`Nexus_5X_API_31`, Android 11): installed the APK, set the connection with the debug intent (the token was read from the token file into the command and never printed or saved anywhere else), launched the app. It fetched all four screens from `http://100.125.195.111:8765` (the emulator's traffic goes out through the laptop, so the request really arrives on the Tailscale address; the BFF log shows the requests from 100.125.195.111). The "SAMPLE DATA" tag is gone and the Account screen shows the real figure **₹2,00,000**, since **23 Nov**, 0.0%. "Test connection" showed "Connected. Data as of 23 Nov 2026." This does **not** prove the phone's own Tailscale path; it proves the app, the cleartext rule, the parsing and the BFF. The phone side still needs one try by you.
4. **Screenshots** (`docs\android\screens\stage4\`): `real-today.png`, `real-account.png`, `real-positions.png`, `real-trades.png` (light theme, real data), `connection-light-tested.png` (after Test connection), `connection-dark.png`. None shows the token (the field is masked and says "Saved. Leave empty to keep it.").
5. **BFF left running** (see Summary). Scheduler pid 9100 unchanged; its log shows only the job's own retry attempts (exit 3 at 20:10, the NSE file not yet published; unrelated to this work). `state\` and `locks\` were identical before and after (names, sizes, modification times); the token does not appear in `bff.log`.

## What did not work

- **The Pixel was not reachable by adb** (above), so the install and the on-phone check are outstanding.
- **A real bug found on the emulator that the JVM tests could not catch:** the first build crashed at start because the Android Keystore refuses a caller-supplied IV when encrypting ("Caller-provided IV not permitted"). Fixed (the cipher now makes its own IV) and re-tested on the emulator. The unit tests use a software key, so they cannot see this; the encryption path is only proven on a device.
- One flaky test (a second DataStore on the same file in one process) was reworked to open a copy of the saved file instead.
- The emulator showed no other problems this time.

## Deviations

1. The notification part was not built (WorkManager not cached); no notification permissions were added.
2. No firewall rule was created: an equivalent rule already exists (Tailscale's own), and this shell has no elevation.
3. Screenshots are from the emulator, not the Pixel.
4. The top bar now has a small "Connection" label next to "Theme"; it is hidden while the Connection screen is open. The Connection screen is a fifth screen, as the brief asked.
5. `PaperRepository` now returns a `Loaded<T>` (data plus an optional "offline since" time) so a screen can show the offline line; the mock repository and the tests were updated.
6. `bff\start_bff.ps1` and `stop_bff.ps1` are only on this branch until it is merged: with the folder back on master the BFF keeps running, but to stop it before the merge use `Stop-Process -Id 12136` (or merge first and use the script).

## Left to do

- Install the APK on the Pixel and confirm the phone's own Tailscale connection (then the stage 4 screenshots on the phone).
- The evening notification (needs WorkManager in the Gradle cache, or another approach).
- Start the BFF at boot / on login (today it is started by hand).
- A real holiday calendar (the "Updated N days ago" limit on an unrecorded holiday).
- HTTPS, if wanted (Tailscale already encrypts the link; the cleartext exception covers only the two Tailscale names).
