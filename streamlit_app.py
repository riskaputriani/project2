import streamlit as st
import subprocess
import os
import sys
import time
import requests

# Konfigurasi
REPO_URL = "https://github.com/FlareSolverr/FlareSolverr.git"
CLONE_DIR = "./FlareSolverr"
PORT = 8191  # Port default FlareSolverr

st.set_page_config(page_title="FlareSolverr Controller", layout="wide")
st.title("🔥 FlareSolverr on Streamlit Cloud")

# --- Bagian 1: Clone Repository ---
if not os.path.exists(CLONE_DIR):
    with st.status("Cloning FlareSolverr repository...", expanded=True) as status:
        try:
            subprocess.run(["git", "clone", REPO_URL, CLONE_DIR], check=True)
            status.update(label="Repository cloned successfully!", state="complete")
        except subprocess.CalledProcessError as e:
            st.error(f"Failed to clone: {e}")
            st.stop()
else:
    st.info("Repository FlareSolverr sudah ada.")

# --- Bagian 2: Setup Environment ---
# Kita harus memaksa FlareSolverr/Selenium menggunakan Chromium yang diinstal via packages.txt
# Lokasi default chromium di environment Debian/Streamlit biasanya di /usr/bin/chromium
os.environ['CHROME_BIN'] = "/usr/bin/chromium"
os.environ['CHROMIUM_PATH'] = "/usr/bin/chromium"
# Mencegah undetected-chromedriver mendownload chrome baru (karena kita sudah punya)
os.environ['PUPPETEER_EXECUTABLE_PATH'] = "/usr/bin/chromium"

# --- Bagian 3: Menjalankan FlareSolverr ---
# Kita gunakan st.cache_resource agar proses ini hanya jalan sekali (singleton)
# meskipun user merefresh halaman browser.
@st.cache_resource
def start_flaresolverr():
    # Perintah: xvfb-run python src/flaresolverr.py
    # Kita harus menjalankan ini dari dalam folder CLONE_DIR atau menyesuaikan path
    
    cmd = [
        "xvfb-run", 
        "--auto-servernum", 
        "--server-args='-screen 0 1024x768x24'",
        sys.executable, 
        "src/flaresolverr.py"
    ]
    
    # Membuka proses di background
    process = subprocess.Popen(
        cmd,
        cwd=CLONE_DIR,  # Jalankan perintah SEOLAH-OLAH kita berada di folder ./FlareSolverr
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=os.environ.copy() # Teruskan env vars
    )
    
    return process

st.write("---")
st.subheader("Server Status")

if st.button("Start FlareSolverr"):
    proc = start_flaresolverr()
    st.success("Perintah start dikirim!")
    
    # Tunggu sebentar agar server nyala
    time.sleep(5)
    
    # Cek apakah process masih jalan
    if proc.poll() is None:
        st.write("✅ Proses berjalan di background (PID: {})".format(proc.pid))
    else:
        st.error("❌ Proses mati segera setelah dijalankan.")
        stdout, stderr = proc.communicate()
        st.code(stderr, language="bash")

# --- Bagian 4: Test Koneksi ke Localhost ---
st.subheader("Test Connectivity")
if st.button("Check Health (localhost:8191)"):
    try:
        # FlareSolverr berjalan di localhost port 8191
        response = requests.get(f"http://localhost:{PORT}/health", timeout=10)
        st.json(response.json())
    except requests.exceptions.ConnectionError:
        st.error(f"Gagal konek ke localhost:{PORT}. Pastikan server sudah distart.")
    except Exception as e:
        st.error(f"Error: {e}")

# --- Bagian 5: Contoh Penggunaan (Bypass Cloudflare) ---
st.subheader("Test Request (v1)")
target_url = st.text_input("URL Target", "https://www.google.com")
if st.button("Solve Request"):
    payload = {
        "cmd": "request.get",
        "url": target_url,
        "maxTimeout": 60000
    }
    
    try:
        res = requests.post(f"http://localhost:{PORT}/v1", json=payload, headers={"Content-Type": "application/json"})
        st.write("Response Status:", res.status_code)
        if res.status_code == 200:
            data = res.json()
            st.json(data.get('solution', {}).get('headers', {})) # Tampilkan headers saja agar rapi
            st.success("Berhasil mengambil data!")
        else:
            st.write(res.text)
    except Exception as e:
        st.error(str(e))