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

## Vercel deployment

Serverless-ready with the Python runtime (`api/index.py` and `vercel.json`).

Serverless instances have a read-only filesystem, so `/admin/bootstrap` cannot persist
there. Configure credentials in **Project Settings → Environment Variables** instead:

- `CHOICE_VENDOR_ID` — your Choice Client ID (e.g. `M09984`)
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
