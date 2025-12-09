import streamlit as st
import subprocess
import os
import requests
import time
import tarfile
import shutil

# --- Konfigurasi ---
FLARESOLVERR_URL = "https://github.com/FlareSolverr/FlareSolverr/releases/download/v3.4.6/flaresolverr_linux_x64.tar.gz"
DOWNLOAD_DIR = "flaresolverr_bin"
BINARY_PATH = os.path.join(DOWNLOAD_DIR, "flaresolverr", "flaresolverr") # Sesuaikan path hasil ekstrak
PORT = 8191
BASE_URL = f"http://localhost:{PORT}"

st.set_page_config(page_title="FlareSolverr di Streamlit", layout="wide")

@st.cache_resource
def setup_and_run_flaresolverr():
    """
    Fungsi ini berjalan sekali saja (cached) untuk setup dan start server.
    """
    status_text = st.empty()
    
    # 1. Cek dan Download
    if not os.path.exists(BINARY_PATH):
        status_text.info("Downloading FlareSolverr binary...")
        try:
            if not os.path.exists(DOWNLOAD_DIR):
                os.makedirs(DOWNLOAD_DIR)
            
            # Download file
            response = requests.get(FLARESOLVERR_URL, stream=True)
            tar_path = os.path.join(DOWNLOAD_DIR, "flaresolverr.tar.gz")
            with open(tar_path, "wb") as f:
                f.write(response.content)
            
            status_text.info("Extracting FlareSolverr...")
            # Extract file
            with tarfile.open(tar_path, "r:gz") as tar:
                tar.extractall(path=DOWNLOAD_DIR)
            
            # Berikan izin eksekusi (chmod +x)
            if os.path.exists(BINARY_PATH):
                os.chmod(BINARY_PATH, 0o755)
            else:
                st.error(f"Binary tidak ditemukan di: {BINARY_PATH}. Cek struktur folder hasil ekstrak.")
                return None

        except Exception as e:
            st.error(f"Gagal saat setup: {e}")
            return None
    
    # 2. Jalankan FlareSolverr sebagai Subprocess
    status_text.info("Starting FlareSolverr Service...")
    
    # Kita perlu memberi tahu FlareSolverr di mana Chromium berada (di Streamlit Cloud biasanya di /usr/bin/chromium)
    env = os.environ.copy()
    env["PUPPETEER_EXECUTABLE_PATH"] = "/usr/bin/chromium"
    env["LOG_LEVEL"] = "info"
    env["PORT"] = str(PORT)

    try:
        # Menjalankan binary di background
        process = subprocess.Popen(
            [BINARY_PATH],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Tunggu sebentar agar server nyala
        max_retries = 10
        server_ready = False
        for i in range(max_retries):
            try:
                # Cek health check (biasanya root endpoint mengembalikan JSON)
                r = requests.get(f"{BASE_URL}/", timeout=2)
                if r.status_code == 200:
                    server_ready = True
                    break
            except requests.exceptions.ConnectionError:
                time.sleep(2)
        
        if server_ready:
            status_text.success("FlareSolverr System Ready! ✅")
            return process
        else:
            status_text.error("FlareSolverr gagal start dalam waktu yang ditentukan.")
            # Print logs jika gagal
            stdout, stderr = process.communicate()
            st.code(stdout)
            st.code(stderr)
            return None

    except Exception as e:
        st.error(f"Error launching subprocess: {e}")
        return None

# --- Main App Logic ---

st.title("🛡️ FlareSolverr Cloud Bypass")
st.markdown("Aplikasi ini menjalankan **FlareSolverr v3.4.6** di background untuk memproses URL yang dilindungi.")

# Jalankan Background Process
proc = setup_and_run_flaresolverr()

st.divider()

# Input UI
col1, col2 = st.columns([3, 1])
with col1:
    target_url = st.text_input("Masukkan URL Target", "https://www.google.com")
with col2:
    st.write("") # Spacer
    st.write("")
    btn_scan = st.button("🚀 Bypass / Request", type="primary")

# Logic Tombol
if btn_scan:
    if not proc:
        st.error("Service FlareSolverr tidak berjalan. Coba restart app.")
    else:
        with st.spinner(f"Memproses {target_url} via FlareSolverr..."):
            try:
                # Payload sesuai dokumentasi FlareSolverr
                payload = {
                    "cmd": "request.get",
                    "url": target_url,
                    "maxTimeout": 60000
                }
                
                headers = {"Content-Type": "application/json"}
                
                # Hit API Localhost
                response = requests.post(f"{BASE_URL}/v1", json=payload, headers=headers)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Tampilkan Status
                    st.success(f"Status: {data.get('status')}")
                    
                    # Tampilkan Solusi (Solution)
                    solution = data.get('solution', {})
                    
                    tab1, tab2, tab3 = st.tabs(["Response JSON", "Rendered HTML", "Cookies"])
                    
                    with tab1:
                        st.json(data)
                        
                    with tab2:
                        # Menampilkan HTML source yang sudah dibypass
                        html_content = solution.get('response', 'No content')
                        st.code(html_content, language='html')
                        # Opsional: Render sebagian (hati-hati dengan scripts)
                        st.components.v1.html(html_content, height=400, scrolling=True)
                        
                    with tab3:
                        st.json(solution.get('cookies', []))
                        
                else:
                    st.error(f"Error dari FlareSolverr: {response.status_code}")
                    st.write(response.text)
                    
            except Exception as e:
                st.error(f"Terjadi kesalahan koneksi: {e}")

st.divider()
st.caption("Running on Streamlit Cloud | FlareSolverr v3.4.6 Linux x64")