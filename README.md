# GROT Dynamic Ladder Simulator (Choice OpenAPI)

An algorithmic backtesting and replay simulator for the **GROT (Grid Order Tracking)** dynamic ladder scalping strategy, powered by **Choice India OpenAPI**.

---

## Features

- **Choice OpenAPI 2FA integration**: 1-click login using `LoginTOTP` and `GetClientLoginTOTP` auto-retrieval.
- **Dynamic chasing ladder engine**: after every profit square-off, pending entry levels chase the new exit price rather than averaging from entry.
- **Strict risk management**: real-time intraday enforcement of maximum profit (₹), maximum loss (₹), and maximum position caps.
- **Quantitative analytics**: GROT total equity vs one-time buy-and-hold, peak-to-trough drawdown reduction, realised profit locked, peak capital deployed, win rate, and scalps per hour.
- **Interactive dual-chart visualization**: OHLC candlestick canvas with pan/zoom, crosshair, volume and RSI sub-panes, SMA/EMA and SuperTrend overlays, dynamic ladder lines, plus a comparative equity curve.
- **Multi-source data**: 1-min, 3/5/15/30-min, hourly or daily candles straight from Choice OpenAPI, or a local CSV upload.

---

## Project layout

```
index.html          Single-file front end (markup, styles, simulation engine, canvas charts)
server.py           Flask backend: Choice auth, scrip search, historical proxy, secrets bootstrap
api/index.py        Vercel serverless entry point (re-exports the Flask app)
desktop_app.py      Windows desktop launcher (credentials window + local server)
build_exe.bat       Builds dist\GROT Simulator.exe with PyInstaller
tests/
  deep_audit.py     DOM/route/security audit + strategy math checks
  test_simulator.py Ladder engine and API endpoint tests
requirements.txt    Python dependencies
vercel.json         Vercel build & routing config
start_server.bat    Windows launcher
start_server.sh     Linux/macOS launcher
```

---

## Local installation & run

1. **Clone the repository**:
   ```bash
   git clone https://github.com/runFast123/grot_sim_choice.git
   cd grot_sim_choice
   ```

2. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Start the server**:
   - Windows: double-click `start_server.bat`, or run `python server.py`
   - Linux/macOS: `bash start_server.sh`

4. Open `http://localhost:5000`.

5. **Store your Choice credentials once** at `http://localhost:5000/admin/bootstrap`
   (Client ID, API Key, registered mobile number). They are written to `secrets.json`
   beside `server.py` and are never sent to the browser. Then click
   **🔑 Login / Settings → 1-Click Login** in the app.

### Running the checks

```bash
python tests/deep_audit.py
python tests/test_simulator.py
```

`deep_audit.py` verifies that every DOM id referenced by the front-end JavaScript exists,
that the ladder math and zero-division fallbacks hold, that all API routes respond, and
that the static file route does not expose source, secrets, or session files.

---

## Credential handling

Credentials live on the server only. Nothing is stored in the browser.

Resolution order, highest priority first:

1. Environment variables — `CHOICE_VENDOR_ID`, `CHOICE_API_KEY`, `CHOICE_MOBILE`, `CHOICE_BASE_URL`, `CHOICE_SESSION_ID`
2. `secrets.json` written by `/admin/bootstrap`
3. `.choice_session.json` — today's session id, refreshed on each successful login

`secrets.json` and `.choice_session.json` are both gitignored. The static file route
serves front-end assets only and returns 404 for `.py`, `.json`, dotfiles, and logs.

---

## Gold & silver (MCX)

The **GOLD**, **SILVER**, **GOLDM** and **SILVERM** preset chips call `/api/scrip/resolve`,
which picks the nearest non-expired MCX futures contract from Choice's daily scrip master
(each expiry has its own token, so fixed tokens go stale). Selecting one also:

- sets *Qty per lot* to the real P&L multiplier: GOLD ×100 (quoted per 10 g, 1 kg lot),
  SILVER ×30 (per kg, 30 kg lot), GOLDM ×10, SILVERM ×5;
- switches the session window to MCX hours (09:00–23:25) and the cost model to
  **MCX Commodity Futures** (CTT 0.01% sell, txn 0.0021%, stamp 0.002%, GST 18%).

The scrip master is ~22 MB and downloads in the background at start-up; until it finishes
the chips report that the contract list is still loading. Older expiries drop out of the
master once they expire, so very old date ranges may need a CSV upload instead.

---

## Desktop app (Windows .exe)

The same simulator also ships as a single Windows program, `GROT Simulator.exe`, for
people who want it running on their own PC instead of the web app. It runs the
unchanged `server.py` and `index.html` locally, so every calculation is identical.

- **Credentials stay on the PC.** A small window asks for the Client ID (Vendor ID), API
  Key, registered mobile number and gateway, and saves them to
  `%APPDATA%\GROT Simulator\secrets.json`. The daily session and a log file live in the same folder.
- **Requests come from your own IP.** Choice calls go out over the PC's own internet
  connection, so they match the Static IP set on the Choice API key. **Check my IP** shows
  that IP.
- **Local only.** The server listens on `127.0.0.1` (port 5757, or a free port if that one
  is taken) and is not reachable from other machines.
- **Using it.** Click **Open Simulator**, then **🔑 Login / Settings → 1-Click Login**.
  Closing the window stops the simulator.

Build the exe (a clean virtual environment is created in `build\venv`, so only the app's
own dependencies are bundled):

```bat
build_exe.bat
```

The result is `dist\GROT Simulator.exe`. To run the desktop version from source instead:
`python desktop_app.py`.

---

## Vercel deployment

Serverless-ready with the Python runtime (`api/index.py` and `vercel.json`).

Serverless instances have a read-only filesystem, so `/admin/bootstrap` cannot persist
there. Configure credentials in **Project Settings → Environment Variables** instead:

- `CHOICE_VENDOR_ID` — your Choice Client ID (format `M12345`)
- `CHOICE_API_KEY` — your Choice Bearer API key
- `CHOICE_BASE_URL` — `https://finxomne.choiceindia.com` or `https://finx.choiceindia.com`
- `CHOICE_MOBILE` — your registered mobile number

Pushes to `main` deploy automatically.

---

## Troubleshooting Choice 401 "Static IP is blank or invalid / ClientId doesn't exist"

Choice enforces regulatory static-IP checks on protected market data endpoints
(`/api/OpenGraph/ChartData`):

1. **Dual-gateway failover** — if `finxomne.choiceindia.com` rejects with a 401 ClientId
   mismatch, the backend automatically retries on `finx.choiceindia.com` (and vice versa).
2. **Forwarded IP headers** — the proxy forwards your public client IP in `X-Forwarded-For`,
   `X-Real-IP`, and `Client-IP`.
3. **IP configuration** — the login modal shows the IP Choice will see. Log into the Choice
   FinX Developer Portal, edit your API key, and make sure the **Static IP** field matches it
   (or `0.0.0.0` if your account allows it).
