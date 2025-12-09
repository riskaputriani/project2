import os
import tarfile
import time
import subprocess
from pathlib import Path

import requests
import streamlit as st


FLARESOLVERR_VERSION = "v3.4.6"
FLARESOLVERR_TARBALL_URL = (
    f"https://github.com/FlareSolverr/FlareSolverr/releases/download/"
    f"{FLARESOLVERR_VERSION}/flaresolverr_linux_x64.tar.gz"
)
FLARESOLVERR_DIR = Path("flaresolverr_bin")
FLARESOLVERR_BINARY = FLARESOLVERR_DIR / "flaresolverr"
FLARESOLVERR_PORT = 8191
FLARESOLVERR_URL = f"http://localhost:{FLARESOLVERR_PORT}"
HEALTH_ENDPOINT = f"{FLARESOLVERR_URL}/health"
API_ENDPOINT = f"{FLARESOLVERR_URL}/v1"


# -----------------------------
# Helpers: download & run FlareSolverr
# -----------------------------
def download_flaresolverr():
    FLARESOLVERR_DIR.mkdir(exist_ok=True)

    tar_path = FLARESOLVERR_DIR / "flaresolverr_linux_x64.tar.gz"
    if not tar_path.exists():
        st.info("Mengunduh FlareSolverr binary, harap tunggu...")
        with requests.get(FLARESOLVERR_TARBALL_URL, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(tar_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

    # Extract tar.gz
    st.info("Ekstrak FlareSolverr...")
    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(path=FLARESOLVERR_DIR)

    # Jadikan executable
    if FLARESOLVERR_BINARY.exists():
        FLARESOLVERR_BINARY.chmod(0o755)
    else:
        # fallback: coba cari binary di dalam folder
        for p in FLARESOLVERR_DIR.glob("**/flaresolverr"):
            p.chmod(0o755)
            return p

    return FLARESOLVERR_BINARY


def is_flaresolverr_healthy(timeout=3.0):
    try:
        r = requests.get(HEALTH_ENDPOINT, timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def start_flaresolverr():
    """
    Start FlareSolverr sebagai proses background.
    Simpan handle di st.session_state agar tidak spawn berkali-kali.
    """
    # Kalau sudah ada dan masih jalan, skip
    proc = st.session_state.get("flaresolverr_proc")
    if proc is not None and proc.poll() is None:
        return

    binary_path = download_flaresolverr()

    st.info("Menjalankan FlareSolverr server...")

    env = os.environ.copy()
    # Optional: setting env dari docs
    env.setdefault("LOG_LEVEL", "info")
    env.setdefault("HEADLESS", "true")
    # timezone & language bisa diset kalau mau
    # env.setdefault("TZ", "Asia/Singapore")
    # env.setdefault("LANG", "en_US.UTF-8")

    proc = subprocess.Popen(
        [str(binary_path)],
        cwd=str(FLARESOLVERR_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    st.session_state["flaresolverr_proc"] = proc

    # Tunggu sampai /health OK atau timeout
    start_time = time.time()
    while time.time() - start_time < 60:  # max 60 detik
        if proc.poll() is not None:
            st.error("Proses FlareSolverr berhenti secara tiba-tiba.")
            break
        if is_flaresolverr_healthy():
            return
        time.sleep(2)

    if not is_flaresolverr_healthy():
        st.error("Gagal membuat FlareSolverr sehat (/health tidak OK).")


def ensure_flaresolverr_running():
    """
    Dipanggil di awal app. Pastikan FlareSolverr hidup.
    """
    if is_flaresolverr_healthy():
        return

    # Kalau belum sehat, coba start
    start_flaresolverr()


# -----------------------------
# Streamlit UI
# -----------------------------
def main():
    st.set_page_config(
        page_title="FlareSolverr Streamlit Wrapper",
        page_icon="🧩",
        layout="wide",
    )

    st.title("🧩 FlareSolverr Streamlit Runner")
    st.write(
        """
        UI sederhana untuk menjalankan **FlareSolverr** dan mengirim request
        `request.get` sesuai dokumentasi API resminya.\n
        FlareSolverr akan berjalan di `http://localhost:8191`.
        """
    )

    with st.expander("Status FlareSolverr", expanded=True):
        if st.button("🔄 Cek status /health", type="secondary"):
            if is_flaresolverr_healthy():
                st.success("FlareSolverr sehat (/health OK).")
            else:
                st.warning("FlareSolverr belum sehat. Mencoba menjalankan ulang...")
                ensure_flaresolverr_running()
                if is_flaresolverr_healthy():
                    st.success("Sekarang FlareSolverr sudah sehat.")
                else:
                    st.error("FlareSolverr tetap tidak sehat.")

        # Tampilkan status otomatis di bawah
        healthy = is_flaresolverr_healthy()
        if healthy:
            st.success("Status saat ini: FlareSolverr **RUNNING** ✅")
        else:
            st.warning("Status saat ini: FlareSolverr **NOT RUNNING** ❌")

    # Pastikan server jalan (lazy-start)
    ensure_flaresolverr_running()

    st.markdown("---")
    st.subheader("🌐 Kirim URL ke FlareSolverr")

    url = st.text_input(
        "URL target (wajib):",
        placeholder="https://contoh-site-yang-di-protect-cloudflare.com/",
    )

    col1, col2 = st.columns(2)

    with col1:
        max_timeout = st.number_input(
            "maxTimeout (ms)",
            min_value=10_000,
            max_value=300_000,
            value=60_000,
            step=5_000,
            help="Batas waktu pemecahan challenge Cloudflare (default 60000).",
        )

    with col2:
        return_only_cookies = st.checkbox(
            "Hanya kembalikan cookies (returnOnlyCookies)", value=False
        )

    if st.button("🚀 Solve via FlareSolverr", type="primary", use_container_width=True):
        if not url:
            st.error("Mohon isi URL terlebih dahulu.")
        elif not is_flaresolverr_healthy():
            st.error("FlareSolverr belum siap. Coba klik 'Cek status /health' dulu.")
        else:
            with st.spinner("Mengirim request ke FlareSolverr..."):
                try:
                    payload = {
                        "cmd": "request.get",
                        "url": url,
                        "maxTimeout": int(max_timeout),
                    }
                    if return_only_cookies:
                        payload["returnOnlyCookies"] = True

                    headers = {"Content-Type": "application/json"}
                    resp = requests.post(
                        API_ENDPOINT, headers=headers, json=payload, timeout=max_timeout / 1000 + 10
                    )

                    st.write("**Status code FlareSolverr:**", resp.status_code)

                    if resp.status_code != 200:
                        st.error(
                            f"Gagal dari FlareSolverr (HTTP {resp.status_code}):\n\n"
                            f"{resp.text[:4000]}"
                        )
                    else:
                        data = resp.json()
                        st.json(data)

                        # Kalau status ok & ada solution
                        if data.get("status") == "ok":
                            sol = data.get("solution", {})
                            st.success(
                                f"Solution OK (HTTP {sol.get('status')}) "
                                f"untuk URL final: {sol.get('url')}"
                            )

                            with st.expander("Headers", expanded=False):
                                st.json(sol.get("headers", {}))

                            with st.expander("Cookies", expanded=False):
                                st.json(sol.get("cookies", []))

                            with st.expander("User-Agent & Info", expanded=False):
                                st.write("User-Agent:", sol.get("userAgent"))

                            if not return_only_cookies:
                                html_preview = (sol.get("response") or "")[:5000]
                                with st.expander("Preview HTML (trimmed)", expanded=False):
                                    st.code(html_preview, language="html")
                        else:
                            st.warning("Response bukan 'status=ok'. Lihat JSON di atas.")

                except Exception as e:
                    st.exception(e)


if __name__ == "__main__":
    main()
