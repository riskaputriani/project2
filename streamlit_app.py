import streamlit as st
import requests
import subprocess
import os
import time
import tarfile
import psutil
import shutil

# --- Konfigurasi ---
FLARESOLVERR_URL = "https://github.com/FlareSolverr/FlareSolverr/releases/download/v3.4.6/flaresolverr_linux_x64.tar.gz"
EXTRACT_DIR = "flaresolverr_dir"
BINARY_PATH = os.path.join(EXTRACT_DIR, "flaresolverr", "flaresolverr")
API_URL = "http://localhost:8191/v1"

st.set_page_config(page_title="FlareSolverr Streamlit", layout="wide")

# --- Fungsi Utilities ---

def is_process_running(process_name):
    """Mengecek apakah proses sudah berjalan."""
    for proc in psutil.process_iter():
        try:
            if process_name.lower() in proc.name().lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False

def setup_flaresolverr():
    """Download dan Extract FlareSolverr jika belum ada."""
    if not os.path.exists(BINARY_PATH):
        with st.spinner('Mendownload FlareSolverr Binary (Linux x64)...'):
            # Hapus folder lama jika ada sisa corrupt
            if os.path.exists(EXTRACT_DIR):
                shutil.rmtree(EXTRACT_DIR)
            os.makedirs(EXTRACT_DIR)
            
            # Download
            response = requests.get(FLARESOLVERR_URL, stream=True)
            tar_path = "flaresolverr.tar.gz"
            with open(tar_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        f.write(chunk)
            
            # Extract
            st.info("Mengekstrak files...")
            with tarfile.open(tar_path, "r:gz") as tar:
                tar.extractall(path=EXTRACT_DIR)
            
            # Cleanup
            os.remove(tar_path)
            
            # Berikan permission execute
            st.info("Mengatur permissions...")
            os.chmod(BINARY_PATH, 0o755)
            st.success("Setup selesai!")

@st.cache_resource
def start_flaresolverr_server():
    """
    Menjalankan FlareSolverr di background.
    Menggunakan cache_resource agar tidak restart setiap kali ada interaksi UI.
    """
    setup_flaresolverr()
    
    if not is_process_running("flaresolverr"):
        print("Memulai FlareSolverr Server...")
        # Menjalankan binary. Kita set env var agar menggunakan port default 8191
        # LOG_LEVEL info agar tidak terlalu spam di logs
        env = os.environ.copy()
        env["LOG_LEVEL"] = "info"
        env["LOG_HTML"] = "false"
        
        # PENTING: Start process
        proc = subprocess.Popen(
            [BINARY_PATH],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Tunggu sebentar agar server siap
        time.sleep(5)
        return proc
    return None

# --- Main App Logic ---

st.title("🛡️ FlareSolverr di Streamlit Cloud")
st.markdown("""
Aplikasi ini menjalankan **FlareSolverr** di background (Localhost:8191) untuk mem-bypass Cloudflare challenge.
""")

# 1. Start Server
proc = start_flaresolverr_server()

# Cek status server
try:
    health_check = requests.get("http://localhost:8191/")
    status_msg = f"✅ Server Online: {health_check.json()['msg']}"
    st.sidebar.success(status_msg)
except Exception as e:
    st.sidebar.error("❌ Server Offline atau sedang loading...")
    st.sidebar.warning(f"Error: {e}")

st.divider()

# 2. UI Input
col1, col2 = st.columns([3, 1])
with col1:
    target_url = st.text_input("Target URL", "https://www.google.com")
with col2:
    req_method = st.selectbox("Method", ["GET", "POST"])

solve_btn = st.button("🚀 Bypass / Solve", type="primary")

# 3. Action
if solve_btn:
    if not target_url:
        st.warning("Mohon masukkan URL.")
    else:
        payload = {
            "cmd": "request.get" if req_method == "GET" else "request.post",
            "url": target_url,
            "maxTimeout": 60000
        }
        
        st.write(f"Mengirim request ke FlareSolverr...")
        
        try:
            start_time = time.time()
            # Hit API FlareSolverr Lokal
            res = requests.post(API_URL, json=payload, headers={"Content-Type": "application/json"})
            end_time = time.time()
            
            if res.status_code == 200:
                data = res.json()
                st.success(f"Sukses! (Waktu: {round(end_time - start_time, 2)}s)")
                
                # Menampilkan Hasil
                tab1, tab2, tab3 = st.tabs(["Response HTML", "Solution JSON", "Screenshot (Jika ada)"])
                
                with tab1:
                    # Menampilkan HTML dari solution
                    if "solution" in data and "response" in data["solution"]:
                        st.code(data["solution"]["response"][:5000] + "...", language="html")
                    else:
                        st.warning("Tidak ada respon HTML.")

                with tab2:
                    st.json(data)
                    
                with tab3:
                    st.info("Screenshot tidak tersedia dalam mode default request ini.")
                    
            else:
                st.error(f"Gagal. Status Code: {res.status_code}")
                st.text(res.text)
                
        except Exception as e:
            st.error(f"Terjadi kesalahan saat menghubungi FlareSolverr: {e}")

st.divider()
st.markdown("**Catatan:**")
st.caption("* Aplikasi ini akan mendownload binary sekitar 150MB saat pertama kali dijalankan (cold start).")
st.caption("* Pastikan URL target valid.")