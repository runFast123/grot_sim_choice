"""
GROT Simulator - Windows desktop app.

Runs the exact same Flask server (server.py) and front end (index.html) as the
web app, but on this PC only:

  * the server listens on 127.0.0.1, so nothing is reachable from the network;
  * Choice requests leave from this PC's own internet connection, so they come
    from the static IP the Choice API key is bound to;
  * credentials and the daily session are kept in %APPDATA%\\GROT Simulator.

server.py is imported unchanged. This file only points its two storage paths at
the per-user data folder and adds a small window for entering credentials.

Run from source:   python desktop_app.py
Build the .exe:    build_exe.bat
"""
import os
import sys
import json
import socket
import threading
import webbrowser

APP_NAME = "GROT Simulator"
PREFERRED_PORT = 5757
GATEWAYS = (
    ("finxomne.choiceindia.com (default)", "https://finxomne.choiceindia.com"),
    ("finx.choiceindia.com", "https://finx.choiceindia.com"),
)


def data_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


DATA_DIR = data_dir()
LOG_FILE = os.path.join(DATA_DIR, "grot_simulator.log")


def redirect_output_when_windowed():
    """A windowed .exe has no console, so print() and Flask logs go to a file."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 2_000_000:
            os.remove(LOG_FILE)
        log = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
        sys.stdout = log
        sys.stderr = log
    except Exception:
        pass


redirect_output_when_windowed()

import server  # noqa: E402  (must come after the output redirect)

# Point the unchanged server at the per-user data folder, then load from there.
# Credential fields are reset to their environment-variable values first so the
# result is the same whether we run from source or from the bundled .exe.
server.SECRETS_FILE = os.path.join(DATA_DIR, "secrets.json")
server.SESSION_FILE = os.path.join(DATA_DIR, ".choice_session.json")
for _key, _env in (("vendor_id", "CHOICE_VENDOR_ID"), ("api_key", "CHOICE_API_KEY"),
                   ("session_id", "CHOICE_SESSION_ID"), ("access_token", "CHOICE_ACCESS_TOKEN"),
                   ("mobile_no", "CHOICE_MOBILE")):
    server.auth_state[_key] = os.environ.get(_env, "")
server.auth_state["base_url"] = os.environ.get("CHOICE_BASE_URL", server.DEFAULT_BASE_URL)
server.auth_state["logged_in"] = False
server.choice_client = None
server.load_secrets_from_file()
server.load_session_from_file()


def port_is_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            return False  # something is already listening there
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def pick_port():
    if port_is_free(PREFERRED_PORT):
        return PREFERRED_PORT
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LocalServer:
    def __init__(self):
        from werkzeug.serving import make_server
        self.port = pick_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.httpd = make_server("127.0.0.1", self.port, server.app, threaded=True)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        print(f"{APP_NAME} serving on {self.url} (data: {DATA_DIR})")

    def stop(self):
        try:
            self.httpd.shutdown()
        except Exception:
            pass


def read_saved_secrets():
    try:
        with open(server.SECRETS_FILE, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def run_window(local):
    import tkinter as tk
    from tkinter import ttk
    import requests

    root = tk.Tk()
    root.title(APP_NAME)
    root.resizable(False, False)

    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    style.configure("Title.TLabel", font=("Segoe UI Semibold", 15))
    style.configure("Muted.TLabel", foreground="#475569")
    style.configure("Ok.TLabel", foreground="#15803D")
    style.configure("Warn.TLabel", foreground="#B45309")

    frame = ttk.Frame(root, padding=(22, 18, 22, 16))
    frame.grid(sticky="nsew")
    frame.columnconfigure(1, weight=1)

    ttk.Label(frame, text="GROT Dynamic Ladder Simulator", style="Title.TLabel").grid(
        row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(frame, text=f"Running on this PC only at {local.url}", style="Muted.TLabel").grid(
        row=1, column=0, columnspan=3, sticky="w", pady=(2, 14))

    creds = ttk.LabelFrame(frame, text=" Choice credentials ", padding=(14, 10))
    creds.grid(row=2, column=0, columnspan=3, sticky="ew")
    creds.columnconfigure(1, weight=1)

    saved = read_saved_secrets()
    vendor_var = tk.StringVar(value=saved.get("vendor_id", ""))
    key_var = tk.StringVar(value=saved.get("api_key", ""))
    mobile_var = tk.StringVar(value=saved.get("mobile_no", ""))
    saved_base = (saved.get("base_url") or GATEWAYS[0][1]).rstrip("/")
    gateway_var = tk.StringVar(value=next((label for label, url in GATEWAYS if url == saved_base), GATEWAYS[0][0]))

    ttk.Label(creds, text="Client ID (Vendor ID)").grid(row=0, column=0, sticky="w", pady=4)
    vendor_entry = ttk.Entry(creds, textvariable=vendor_var, width=44)
    vendor_entry.grid(row=0, column=1, columnspan=2, sticky="ew", pady=4, padx=(10, 0))

    ttk.Label(creds, text="API Key").grid(row=1, column=0, sticky="w", pady=4)
    key_entry = ttk.Entry(creds, textvariable=key_var, width=36, show="•")
    key_entry.grid(row=1, column=1, sticky="ew", pady=4, padx=(10, 6))

    def toggle_key():
        showing = key_entry.cget("show") == ""
        key_entry.configure(show="•" if showing else "")
        show_btn.configure(text="Show" if showing else "Hide")

    show_btn = ttk.Button(creds, text="Show", width=6, command=toggle_key)
    show_btn.grid(row=1, column=2, sticky="e", pady=4)

    ttk.Label(creds, text="Registered mobile").grid(row=2, column=0, sticky="w", pady=4)
    ttk.Entry(creds, textvariable=mobile_var, width=44).grid(
        row=2, column=1, columnspan=2, sticky="ew", pady=4, padx=(10, 0))

    ttk.Label(creds, text="Gateway").grid(row=3, column=0, sticky="w", pady=4)
    ttk.Combobox(creds, textvariable=gateway_var, state="readonly", width=42,
                 values=[label for label, _ in GATEWAYS]).grid(
        row=3, column=1, columnspan=2, sticky="ew", pady=4, padx=(10, 0))

    ttk.Label(creds, text=f"Saved only on this PC: {DATA_DIR}", style="Muted.TLabel",
              wraplength=440).grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))

    status_var = tk.StringVar()
    status_label = ttk.Label(frame, textvariable=status_var, wraplength=460)
    status_label.grid(row=3, column=0, columnspan=3, sticky="w", pady=(12, 4))

    def set_status(text, kind="Muted"):
        status_var.set(text)
        status_label.configure(style=f"{kind}.TLabel")

    def in_background(work, done):
        def runner():
            try:
                result = work()
                root.after(0, lambda: done(result, None))
            except Exception as exc:  # noqa: BLE001
                root.after(0, lambda err=exc: done(None, err))
        threading.Thread(target=runner, daemon=True).start()

    def save():
        vendor = vendor_var.get().strip()
        api_key = key_var.get().strip()
        mobile = mobile_var.get().strip()
        if not vendor or not api_key or not mobile:
            set_status("Client ID, API Key and mobile number are all required.", "Warn")
            return
        base_url = dict(GATEWAYS).get(gateway_var.get(), GATEWAYS[0][1])
        save_btn.state(["disabled"])
        set_status("Saving…")

        def work():
            # Same route the web app's /admin/bootstrap page uses.
            return requests.post(f"{local.url}/admin/bootstrap", timeout=15, json={
                "vendor_id": vendor, "api_key": api_key,
                "mobile_no": mobile, "base_url": base_url})

        def done(resp, exc):
            save_btn.state(["!disabled"])
            if exc is None and resp is not None and resp.ok:
                set_status("Saved. Click Open Simulator, then \U0001F511 Login / Settings → 1-Click Login.", "Ok")
            else:
                set_status(f"Could not save: {exc or resp.text[:200]}", "Warn")

        in_background(work, done)

    def open_app():
        webbrowser.open(local.url)

    def check_ip():
        ip_btn.state(["disabled"])
        ip_var.set("Checking…")

        def work():
            return requests.get("https://api.ipify.org", timeout=8).text.strip()

        def done(ip, exc):
            ip_btn.state(["!disabled"])
            ip_var.set(f"Your public IP: {ip}" if exc is None else "Could not check the IP right now.")

        in_background(work, done)

    buttons = ttk.Frame(frame)
    buttons.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(6, 0))
    save_btn = ttk.Button(buttons, text="Save credentials", command=save)
    save_btn.pack(side="left")
    ttk.Button(buttons, text="Open Simulator", command=open_app).pack(side="left", padx=8)

    ipbox = ttk.Frame(frame)
    ipbox.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(14, 0))
    ip_var = tk.StringVar(value="Your Choice API key's Static IP must match this PC's public IP.")
    ttk.Label(ipbox, textvariable=ip_var, style="Muted.TLabel", wraplength=340).pack(side="left")
    ip_btn = ttk.Button(ipbox, text="Check my IP", command=check_ip)
    ip_btn.pack(side="right")

    ttk.Label(frame, text="Closing this window stops the simulator.", style="Muted.TLabel").grid(
        row=6, column=0, columnspan=3, sticky="w", pady=(14, 0))

    if saved.get("vendor_id") and saved.get("api_key"):
        set_status("Credentials found on this PC. Opening the simulator in your browser…", "Ok")
        root.after(600, open_app)
    else:
        set_status("First run: enter your Choice credentials and click Save credentials.", "Warn")
        vendor_entry.focus_set()

    def on_close():
        local.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


def main():
    local = LocalServer()
    local.start()
    if "--no-window" in sys.argv:  # headless: serve until Ctrl+C
        print(f"Open {local.url}")
        try:
            local.thread.join()
        except KeyboardInterrupt:
            local.stop()
        return
    run_window(local)


if __name__ == "__main__":
    main()
