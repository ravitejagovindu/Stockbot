# Connecting the phone app to the laptop (stage 4)

The StockBot Paper app reads the paper account from the BFF running on the laptop, over Tailscale. The app and the BFF are **read-only**: the app only sends GET requests, there is no order button, and no broker key exists anywhere.

## The path

```
phone (StockBot Paper)  --Tailscale (WireGuard, encrypted)-->  laptop 100.125.195.111 : 8765  (bff\run.py, read-only)
```

* Laptop Tailscale IPv4 address: `100.125.195.111`; MagicDNS name: `laptop.tail0118ce.ts.net`. The phone ("Ravi's pixel") is in the same tailnet.
* The BFF binds **only** to that Tailscale address (never to every interface), so it is not reachable from the Wi-Fi network or the internet, only from inside the tailnet.

## The Connection screen

Open it from the top bar (the word "Connection" next to the theme choice). It follows the same design and both themes.

| Control | What it does |
|---|---|
| Server address | Defaults to `http://100.125.195.111:8765`. You may type `100.125.195.111:8765` or the MagicDNS name; `http://` is added. Plain `http` is accepted only for the two Tailscale names below; any other address must be `https`. |
| Token | Masked; paste allowed. Leave it empty to keep the saved token ("Saved. Leave empty to keep it."). |
| Test connection | Saves the address (and the token if you typed one), then calls `/v1/health` and shows one line: "Connected. Data as of 23 Nov 2026.", "The token was not accepted.", "Can't reach your laptop.", "The laptop answered, but the data is not ready yet." |
| Use sample data | On by default. Turn it off to see your laptop's real figures. While it is on, the "SAMPLE DATA" tag shows; with it off the tag disappears. Debug builds also keep the hidden scenario menu (long-press the screen title); picking a scenario turns the sample switch on. |

The address is kept in DataStore. The token is kept **encrypted** (AES-GCM, key in the Android Keystore); the settings file only holds the encrypted text. Neither is ever logged (the app has no log calls, and a test checks that).

## The Job screen (stage 5)

The fifth tab, "Job", answers one question: did tonight's job run? It reads `GET /v1/job` and is read-only: it has no button that starts, retries or stops anything (the only "Retry" is the one in the offline line, which just asks again).

* **Top:** a big state chip (colour, icon and word together, never colour alone): Done, Running, Retrying, No file, Alert, Waiting, Weekend; one plain sentence under it; then Service (on since ..., or off), Next attempt, Data as of, Expected, and whether the data is up to date or behind.
* **Below:** the last 10 days as a strip of small chips (weekday, state icon, day of the month; today on the right), then today's attempts (time, exit code, decision).
* **Refresh and offline** work as on the other screens: pull to refresh, refresh on open and on return; when the laptop cannot be reached the kept copy is shown with "Can't reach your laptop. Showing data from ...".
* **No file** usually means a market holiday: the NSE published nothing and the service stopped after its last attempt of the day. "Alert" is for the cases that need a look (for example a stale lock).
* **Sample data:** the debug build's hidden menu (long-press the title) has a "Job screen" list (Done, Running, Retrying, No file, Alert, Service off) for the sample data; in adb: `--es tab JOB --es jobscenario RETRYING`.
* The BFF must be restarted once after this change before the real Job screen works (see `docs\bff\README.md`); until then the screen shows its calm error with Retry.

## Refresh and offline

* The app asks again when it opens, when it comes back to the front, and on **pull-to-refresh** on every screen.
* Every good answer is kept on the phone (one file per screen, in the app's private storage). When the laptop cannot be reached (after 8 s timeouts and one retry) the app shows the kept copy with a calm line, "Can't reach your laptop. Showing data from 24 Nov, 19:48.", and a Retry button. With nothing kept it shows the usual one-line error with Retry. A wrong token or a "not ready" answer is shown as an error, not hidden behind old data.

## Why plain http is allowed for two names (the network security config)

`app/src/main/res/xml/network_security_config.xml`: everything is HTTPS-only (`base-config cleartextTrafficPermitted="false"`) except two `domain-config` entries, `100.125.195.111` and `laptop.tail0118ce.ts.net` (no subdomains, no wildcards). Plain http is acceptable there because Tailscale already encrypts the link end to end and the address only exists inside the owner's tailnet; running TLS on top would need a certificate for no extra protection. If you move the BFF to another address or name, change this file and `CleartextHosts` in `net/ConnectionStore.kt` together (a unit test checks they agree). The manifest has one permission: `INTERNET`.

## Debug-only set-up from adb (no typing)

In a **debug build only**, `adb shell am start -n com.stockbot.paper/.MainActivity --es server http://100.125.195.111:8765 --es token <token> ` sets the address and token, turns the sample data off, and removes those two extras from the intent at once (they are read once per launch). A release build ignores them. The token then lives encrypted in the app, never in a file you have to type.

## Firewall

No new Windows Firewall rule was needed. Tailscale itself installed two enabled inbound allow rules, both named "Tailscale-In" (profiles Domain and Private, any protocol and port, local address `100.125.195.111` and its IPv6 twin); the Tailscale network adapter is on the Private profile. They already cover TCP 8765 on the Tailscale address, which is the same approach the FInsight dev server on this laptop relies on (it listens on every interface and is reached over Tailscale through the same rules). Nothing about FInsight was changed. If the rules are ever removed, the equivalent single rule (needs an elevated PowerShell) is:

```powershell
New-NetFirewallRule -DisplayName "StockBot BFF (Tailscale)" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -RemoteAddress 100.64.0.0/10 -Profile Private,Domain
```

## Token rotation

1. Stop the BFF (`bff\stop_bff.ps1`).
2. Delete `F:\Projects\Ravi\StockBotData\bff\token.txt`.
3. Create a new one (see `docs\bff\README.md`, "The token") and start the BFF (`bff\start_bff.ps1`).
4. On the phone: Connection screen, paste the new token, Test connection. The old token stops working at once.

## Not built: the evening notification

The brief asked for a WorkManager check between 19:45 and 23:30 IST that posts a local notification when something new appears. WorkManager (`androidx.work`) is not in this laptop's Gradle cache and adding it needs a download, so that part was **stopped and not built**: there is no Notifications switch, and the manifest has neither `POST_NOTIFICATIONS` nor `RECEIVE_BOOT_COMPLETED`. When it is built later: Android may delay periodic checks when battery saver is on, so a notification can arrive late.
