# GROT Dynamic Ladder Simulator (Choice OpenAPI)

An algorithmic backtesting and replay simulator for the **GROT (Grid Order Tracking)** dynamic ladder scalping strategy, powered by **Choice India OpenAPI**.

---

## 🚀 Features

- **Choice OpenAPI 2FA Integration**: 1-Click login using `LoginTOTP` and `GetClientLoginTOTP` auto-retrieval.
- **Dynamic Chasing Ladder Engine**: After every profit square-off, pending entry levels automatically chase the new exit price rather than averaging from entry.
- **Strict Risk Management**: Real-time intraday enforcement of Maximum Profit (₹), Maximum Loss (₹), and Maximum Position Caps.
- **Advanced Quantitative Analytics**:
  - GROT Total Equity vs One-Time Buy-and-Hold comparison
  - Real-time Drawdown reduction metrics (Peak-to-Trough)
  - Realised Profit Locked & Peak Capital deployed
  - Win Rate & Scalps per hour
- **Interactive Dual-Chart Visualization**: Real-time OHLC candlestick canvas with dynamic price ladder overlays and comparative equity curve.
- **Multi-Source Support**: Fetch direct 1-min, 5-min, or daily historical candles from Choice OpenAPI or upload local CSV datasets.

---

## 🛠️ Local Installation & Run

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
   - On Windows: Double-click `start_server.bat` or run:
     ```bash
     python server.py
     ```
   - On Linux/macOS:
     ```bash
     bash start_server.sh
     ```

4. Open your browser at `http://localhost:5000`.

---

## ☁️ Vercel Deployment

This project is serverless-ready for Vercel with Python runtime (`api/index.py` and `vercel.json`).

### Connecting Choice OpenAPI on Vercel:
Because Vercel serverless functions run across distributed instances, authentication is seamlessly persisted in your browser's `localStorage` and sent with every request.

1. **Option A (In-Browser Login)**:
   - Open your deployed Vercel domain (e.g. `https://your-domain.vercel.app`).
   - Click **🔑 Login / Settings** in the top bar.
   - Enter your **Client ID / Vendor ID**, **API Key**, and **Mobile Number**.
   - Click **⚡ 1-Click Auto Login** or paste your daily **Session ID** and click **💾 Save Session**.

2. **Option B (Vercel Environment Variables)**:
   You can also configure default credentials in your Vercel Project Settings (`Settings` -> `Environment Variables`):
   - `CHOICE_VENDOR_ID` (Your Choice Client ID, e.g. `M09984`)
   - `CHOICE_API_KEY` (Your Choice Bearer API Key)
   - `CHOICE_BASE_URL` (`https://finxomne.choiceindia.com` or `https://finx.choiceindia.com`)
   - `CHOICE_MOBILE` (Your registered mobile number)

---

### Understanding Choice 401 "Static IP is blank or invalid / ClientId doesn't exists":
Choice India OpenAPI enforces regulatory Static IP checks on protected market data endpoints (`/api/OpenGraph/ChartData`):
1. **Direct Browser Mode (Automatic)**:
   The simulator first attempts a direct fetch from your web browser so that requests originate from your computer's exact ISP IP (which matches your declared static IP).
2. **Dual-Gateway Failover**:
   If `https://finxomne.choiceindia.com` rejects with a 401 ClientId mismatch, the backend automatically retries on `https://finx.choiceindia.com` (and vice-versa).
3. **Forwarded IP Headers**:
   The backend proxy forwards your public client IP in standard proxy headers (`X-Forwarded-For`, `X-Real-IP`, `Client-IP`).
4. **IP Configuration in Choice Portal**:
   If Choice still rejects requests, log into the Choice FinX Developer Portal (`finx.choiceindia.com`), edit your API Key, and verify that the **Static IP** field is set to your current public IP (or `0.0.0.0` if allowed).

---

### Updating Your Deployment:
Whenever you push commits to GitHub (`main` branch), Vercel automatically deploys the updated version:
```bash
git add .
git commit -m "Update simulator features"
git push origin main
```
