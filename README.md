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

Whenever you push commits to GitHub (`main` branch), Vercel automatically deploys the updated version:
```bash
git add .
git commit -m "Update simulator features"
git push origin main
```
