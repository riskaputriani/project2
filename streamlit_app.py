import streamlit as st
import subprocess
import os
import sys
import time
import requests
import signal
import json

# --- KONFIGURASI GLOBAL ---
REPO_URL = "https://github.com/FlareSolverr/FlareSolverr.git"
CLONE_DIR = "./FlareSolverr"
LOG_FILE = "flaresolverr.log"
PORT = 8191
BASE_URL = f"http://localhost:{PORT}/v1"

st.set_page_config(page_title="FlareSolverr Client", layout="wide")
st.title("🔥 FlareSolverr Cloud Client")

# --- SETUP ENVIRONMENT (WAJIB UNTUK STREAMLIT CLOUD) ---
os.environ['CHROME_BIN'] = "/usr/bin/chromium"
os.environ['CHROMIUM_PATH'] = "/usr/bin/chromium"
os.environ['PUPPETEER_EXECUTABLE_PATH'] = "/usr/bin/chromium"
os.environ['UNDETECTED_CHROMEDRIVER_MODE'] = "dist"

# --- FUNGSI MANAJEMEN SERVER ---

def install_and_start():
    # 1. Clone jika belum ada
    if not os.path.exists(CLONE_DIR):
        with st.spinner("Cloning repository..."):
            subprocess.run(["git", "clone", REPO_URL, CLONE_DIR], check=True)
            st.success("Repository cloned.")
    
    # 2. Cek apakah server sudah jalan
    try:
        requests.get(f"http://localhost:{PORT}/health", timeout=1)
        return True # Server sudah aktif
    except requests.exceptions.ConnectionError:
        pass # Server belum aktif, lanjut start

    # 3. Start Server
    log_out = open(LOG_FILE, "w")
    cmd = [
        "xvfb-run", "--auto-servernum", "--server-args='-screen 0 1024x768x24'",
        sys.executable, "src/flaresolverr.py"
    ]
    subprocess.Popen(
        cmd, cwd=CLONE_DIR, stdout=log_out, stderr=log_out,
        env=os.environ.copy(), preexec_fn=os.setsid
    )
    return False

def get_logs():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            return f.read()[-2000:] # Ambil 2000 karakter terakhir
    return "Log kosong."

# --- PROSES STARTUP ---
server_active = install_and_start()

# Tampilkan status server di Sidebar
with st.sidebar:
    st.header("Server Status")
    if st.button("Check Connectivity"):
        try:
            r = requests.get(f"http://localhost:{PORT}/health", timeout=2)
            st.success(f"Online: {r.json()}")
        except:
            st.error("Offline / Starting...")
    
    st.text_area("Server Logs", get_logs(), height=300)
    if st.button("Refresh Logs"):
        st.rerun()

# --- UI UTAMA (CLIENT REQUEST) ---

st.write("### 1. Buat Request")
st.info("Log Anda menunjukkan server sudah '200 OK'. Gunakan form di bawah untuk melihat datanya.")

col1, col2 = st.columns([3, 1])
with col1:
    target_url = st.text_input("Target URL", "https://manhwaclan.com/")
with col2:
    timeout_val = st.number_input("Max Timeout (ms)", value=60000)

if st.button("🚀 KIRIM REQUEST (POST)", type="primary"):
    
    # --- INI ADALAH KODE CLIENT SEPERTI DOKUMENTASI ---
    payload = {
        "cmd": "request.get",
        "url": target_url,
        "maxTimeout": int(timeout_val),
        "session": "test_session_1" # Penting agar cookies tersimpan antar request
    }
    
    headers = {"Content-Type": "application/json"}
    
    st.write("⏳ Sending request to FlareSolverr...")
    
    try:
        # Kita set timeout requests sedikit lebih lama dari maxTimeout FlareSolverr
        response = requests.post(BASE_URL, json=payload, headers=headers, timeout=(timeout_val/1000) + 10)
        
        # --- MENAMPILKAN HASIL ---
        st.divider()
        st.write(f"### Result (HTTP {response.status_code})")

        # Tabulasi agar rapi
        tab1, tab2, tab3, tab4 = st.tabs(["📄 Rendered HTML", "🔍 Full JSON Response", "🍪 Cookies", "⚠️ Raw Text"])

        # Coba parsing JSON
        try:
            json_data = response.json()
            solution = json_data.get('solution', {})
            
            # TAB 1: HTML Visual
            with tab1:
                html_content = solution.get('response', '')
                if html_content:
                    st.success(f"HTML Length: {len(html_content)} characters")
                    # Render iframe preview
                    st.components.v1.html(html_content, height=600, scrolling=True)
                else:
                    st.warning("Field 'response' (HTML) kosong dalam JSON.")

            # TAB 2: Full JSON
            with tab2:
                st.json(json_data)

            # TAB 3: Cookies
            with tab3:
                cookies = solution.get('cookies', [])
                if cookies:
                    st.table(cookies)
                else:
                    st.info("Tidak ada cookies baru.")

        except json.JSONDecodeError:
            st.error("Gagal parsing JSON. Server mungkin mengembalikan error string.")
            with tab4:
                st.code(response.text)

        # TAB 4: Raw Text (Backup)
        with tab4:
            st.text_area("Raw Response Text", response.text, height=200)

    except requests.exceptions.ConnectionError:
        st.error("❌ Gagal koneksi ke localhost:8191. Tunggu sebentar lalu coba lagi (Refresh Log di sidebar untuk cek).")
    except Exception as e:
        st.error(f"❌ Error Terjadi: {e}")