import streamlit as st
import subprocess
import os
import sys
import time
import requests
import signal

# --- KONFIGURASI ---
REPO_URL = "https://github.com/FlareSolverr/FlareSolverr.git"
CLONE_DIR = "./FlareSolverr"
LOG_FILE = "flaresolverr.log"
PORT = 8191

st.set_page_config(page_title="FlareSolverr Controller", layout="wide")
st.title("🔥 FlareSolverr Cloud Controller")

# --- SETUP ENVIRONMENT VARIABLES ---
# Ini krusial agar Chrome tidak crash di Streamlit Cloud
os.environ['CHROME_BIN'] = "/usr/bin/chromium"
os.environ['CHROMIUM_PATH'] = "/usr/bin/chromium"
os.environ['PUPPETEER_EXECUTABLE_PATH'] = "/usr/bin/chromium"
# Memaksa undetected-chromedriver tidak mendownload patch baru
os.environ['UNDETECTED_CHROMEDRIVER_MODE'] = "dist" 

# --- FUNGSI UTILITIES ---

def install_and_clone():
    """Clone repository jika belum ada."""
    if not os.path.exists(CLONE_DIR):
        with st.status("📥 Cloning FlareSolverr...", expanded=True) as status:
            try:
                subprocess.run(["git", "clone", REPO_URL, CLONE_DIR], check=True)
                status.update(label="✅ Repository cloned!", state="complete")
            except subprocess.CalledProcessError as e:
                st.error(f"Gagal clone: {e}")
                st.stop()
    else:
        st.success("📂 Repository FlareSolverr ditemukan.")

def start_server():
    """Menjalankan FlareSolverr dengan xvfb-run dan logging ke file."""
    # Buka file log untuk menampung output
    log_out = open(LOG_FILE, "w")
    
    # Perintah: xvfb-run python src/flaresolverr.py
    cmd = [
        "xvfb-run", 
        "--auto-servernum", 
        "--server-args='-screen 0 1024x768x24'",
        sys.executable, 
        "src/flaresolverr.py"
    ]
    
    process = subprocess.Popen(
        cmd,
        cwd=CLONE_DIR,
        stdout=log_out,
        stderr=log_out,
        env=os.environ.copy(),
        preexec_fn=os.setsid # Agar bisa di-kill group-nya nanti
    )
    return process

def get_logs():
    """Membaca 50 baris terakhir dari log."""
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()
            return "".join(lines[-50:])
    return "Log file belum ada."

# --- UI LAYOUT ---

# 1. Setup Awal
install_and_clone()

st.divider()

# 2. Kontrol Server
col1, col2 = st.columns(2)

with col1:
    st.subheader("⚙️ Server Control")
    if "server_pid" not in st.session_state:
        st.session_state.server_pid = None

    if st.button("▶️ Start FlareSolverr", type="primary"):
        if st.session_state.server_pid is None:
            proc = start_server()
            st.session_state.server_pid = proc.pid
            st.success(f"Server dimulai dengan PID: {proc.pid}")
            time.sleep(5) # Tunggu booting
            st.rerun()
        else:
            st.warning("Server sudah berjalan (menurut session state).")

    if st.button("⏹️ Stop/Kill Server"):
        if st.session_state.server_pid:
            try:
                os.killpg(os.getpgid(st.session_state.server_pid), signal.SIGTERM)
                st.session_state.server_pid = None
                st.success("Server dimatikan.")
            except Exception as e:
                st.error(f"Gagal kill: {e}")
                st.session_state.server_pid = None
        else:
            st.info("Tidak ada PID tersimpan.")

with col2:
    st.subheader("📊 Status Monitor")
    st.write(f"PID Aktif: `{st.session_state.server_pid}`")
    
    # Cek Health Check
    if st.button("🏥 Check Health (localhost:8191)"):
        try:
            r = requests.get(f"http://localhost:{PORT}/health", timeout=5)
            st.json(r.json())
        except Exception as e:
            st.error(f"Tidak bisa connect: {e}")

# 3. Log Monitor
with st.expander("📜 Lihat Server Log (Debug Error)", expanded=False):
    if st.button("Refresh Log"):
        pass
    st.code(get_logs(), language="bash")

st.divider()

# 4. Testing Area
st.subheader("🚀 Test Request (Bypass)")

url_target = st.text_input("URL Target", "https://www.google.com")
if st.button("Solve Challenge"):
    payload = {
        "cmd": "request.get",
        "url": url_target,
        "maxTimeout": 60000,
        # Tambahkan session agar cookie tersimpan
        "session": "test_session_1" 
    }
    
    with st.spinner("Sedang memproses (bisa memakan waktu 10-20 detik)..."):
        try:
            res = requests.post(
                f"http://localhost:{PORT}/v1", 
                json=payload, 
                headers={"Content-Type": "application/json"},
                timeout=70
            )
            
            st.write(f"**HTTP Status:** {res.status_code}")
            
            # Tampilkan RAW text dulu untuk debug jika JSON kosong
            if res.status_code != 200:
                 st.error("Error dari FlareSolverr:")
                 st.text(res.text)
            
            # Coba parsing JSON
            try:
                json_data = res.json()
                
                # Cek status internal FlareSolverr
                if json_data.get('status') == 'ok':
                    st.success("✅ Berhasil!")
                    st.json(json_data.get('solution', {}).get('headers'))
                    with st.expander("Lihat Full JSON"):
                        st.json(json_data)
                else:
                    st.error(f"❌ FlareSolverr Error: {json_data.get('message')}")
                    st.json(json_data)
                    
            except ValueError:
                st.warning("⚠️ Response bukan JSON valid. Ini raw text-nya:")
                st.code(res.text)
                
        except requests.exceptions.ConnectionError:
            st.error("❌ Gagal koneksi. Pastikan server sudah di-Start di atas.")
        except Exception as e:
            st.error(f"❌ Error request: {e}")