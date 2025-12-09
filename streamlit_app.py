import asyncio
import importlib.machinery
import importlib.util
import logging
import re
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

import streamlit as st
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent
MODULE_ROOT = ROOT_DIR / "CloudflareBypassForScraping"
if str(MODULE_ROOT) not in sys.path:
    sys.path.append(str(MODULE_ROOT))

import browserforge.download as bf_download

BROWSERFORGE_DATA_ROOT = ROOT_DIR / "browserforge_data"
HEADERS_DATA_DIR = BROWSERFORGE_DATA_ROOT / "headers" / "data"
FINGERPRINTS_DATA_DIR = BROWSERFORGE_DATA_ROOT / "fingerprints" / "data"
HEADERS_DATA_DIR.mkdir(parents=True, exist_ok=True)
FINGERPRINTS_DATA_DIR.mkdir(parents=True, exist_ok=True)

bf_download.DATA_DIRS["headers"] = HEADERS_DATA_DIR
bf_download.DATA_DIRS["fingerprints"] = FINGERPRINTS_DATA_DIR


# --- Start of Patching Logic ---
def _patch_browserforge_sources():
    modules_to_patch = {
        "browserforge.headers.generator": HEADERS_DATA_DIR,
        "browserforge.fingerprints.generator": FINGERPRINTS_DATA_DIR,
    }

    for module_name, data_path in modules_to_patch.items():
        try:
            # Manually construct the path to the module file to avoid eager imports
            module_path_parts = module_name.split('.')
            base_spec = importlib.util.find_spec(module_path_parts[0])
            if not base_spec or not base_spec.submodule_search_locations:
                continue

            package_dir = Path(base_spec.submodule_search_locations[0])
            relative_path = Path(*module_path_parts[1:]).with_suffix('.py')
            origin = package_dir / relative_path

            if not origin.exists():
                init_path = (package_dir / Path(*module_path_parts[1:])) / '__init__.py'
                if init_path.exists():
                    origin = init_path
                else:
                    continue

            source_code = origin.read_text(encoding='utf-8')

            # Check if already patched
            if "browserforge_data" in source_code:
                continue

            pattern = r"DATA_DIR: Path = .*"
            replacement = f"DATA_DIR: Path = Path('{data_path.as_posix()}')"

            if re.search(pattern, source_code):
                patched_code = re.sub(pattern, replacement, source_code, count=1)
                origin.write_text(patched_code, encoding='utf-8')
                importlib.invalidate_caches()

                # Unload modules to be safe
                if module_name in sys.modules: del sys.modules[module_name]
                parent = module_name.rpartition('.')[0]
                if parent in sys.modules: del sys.modules[parent]
        except Exception:
            pass

_patch_browserforge_sources()
# --- End of Patching Logic ---


from cf_bypasser.core.bypasser import CamoufoxBypasser
from cf_bypasser.server.app import create_app

try:
    from tqdm import tqdm
except ImportError:
    class _DummyTqdm:
        def __init__(self, total: int = 0, **kwargs):
            self.total = total

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def update(self, n: int = 1):
            pass

    tqdm = _DummyTqdm  # type: ignore


st.set_page_config(page_title="Cloudflare Bypass Streamlit", layout="wide")
st.title("Cloudflare Bypass For Scraping (Streamlit)")
st.write(
    "This interface mirrors the legacy FastAPI endpoints while letting you "
    "observe the automation flow live. Each section calls the internal FastAPI "
    "app through `TestClient`, so you keep compatibility without running Uvicorn."
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)


def run_async(coro: Awaitable[Any]) -> Any:
    """Run an async coroutine cleanly from Streamlit."""
    return asyncio.run(coro)


@st.cache_resource
def get_api_client() -> TestClient:
    """Create the FastAPI TestClient once per session."""
    return TestClient(create_app())


def safe_json(response: Any) -> Dict[str, Any]:
    try:
        return response.json()
    except Exception:
        return {"detail": response.text or "Unknown error"}


def describe_html_response(response: Any) -> Dict[str, Any]:
    """Pull headers into a JSON-friendly summary for `/html`."""
    headers = response.headers
    return {
        "status_code": response.status_code,
        "final_url": headers.get("x-cf-bypasser-final-url"),
        "user_agent": headers.get("x-cf-bypasser-user-agent"),
        "cookie_count": headers.get("x-cf-bypasser-cookies"),
        "processing_time_ms": headers.get("x-processing-time-ms"),
        "content_length": len(response.text or ""),
    }


def is_cloudflare_challenge(title: str, html: str) -> bool:
    """Detect the classic Just a moment interstitial."""
    title_lower = (title or "").lower().strip()
    html_lower = (html or "").lower()
    return (
        "just a moment" in title_lower
        or "<title>just a moment" in html_lower
        or "please complete the captcha" in html_lower
    )


async def automation_flow(
    url: str,
    proxy: Optional[str],
    test_client: TestClient,
    log_fn: Callable[[str], None],
    progress_fn: Callable[[float], None],
) -> Dict[str, Any]:
    """Run the automation logic described in the UI."""

    bypasser = CamoufoxBypasser(max_retries=5, log=True)
    total_steps = 4
    progress_counter = 0

    with tqdm(total=total_steps, desc="Automation flow", leave=False) as tracker:
        def mark_step(message: str) -> None:
            nonlocal progress_counter
            log_fn(message)
            if progress_counter < total_steps:
                progress_counter += 1
                tracker.update(1)
            progress_fn(min(progress_counter / total_steps, 1.0))

        def finalize_progress() -> None:
            nonlocal progress_counter
            remaining = total_steps - progress_counter
            if remaining > 0:
                tracker.update(remaining)
                progress_counter = total_steps
            progress_fn(1.0)

        mark_step("Launching browser for initial inspection")
        cam1 = browser1 = context1 = page1 = None
        try:
            cam1, browser1, context1, page1 = await bypasser.setup_browser(proxy=proxy)
            await page1.goto(url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)
            title = await page1.title()
            html = await page1.content()
            if not is_cloudflare_challenge(title, html):
                mark_step("No Cloudflare challenge detected; skipping cookies")
                mark_step("Skipping cookie injection/reload")
                mark_step("Capturing screenshot for clean page")
                screenshot = await page1.screenshot(full_page=True)
                final_result = {
                    "success": True,
                    "title": title,
                    "final_url": page1.url,
                    "cloudflare_detected": False,
                    "screenshot": screenshot,
                    "message": "Reached the page without challenge.",
                }
                finalize_progress()
                return final_result
            log_fn("Cloudflare interstitial detected; requesting cookies")
        except Exception as exc:  # pylint: disable=broad-except
            finalize_progress()
            return {"success": False, "message": f"Initial navigation failed: {exc}"}
        finally:
            await bypasser.cleanup_browser(cam1, browser1, context1, page1)

        mark_step("Fetching cookies through /cookies endpoint")
        try:
            cookie_response = await asyncio.to_thread(
                lambda: test_client.get("/cookies", params={"url": url, "proxy": proxy})
            )
        except Exception as exc:
            finalize_progress()
            return {"success": False, "message": f"Cookie request raised: {exc}", "cloudflare_detected": True}

        if not cookie_response.ok:
            detail = safe_json(cookie_response).get("detail", "Unknown error")
            finalize_progress()
            return {"success": False, "message": detail, "cloudflare_detected": True}

        cookie_payload = cookie_response.json()
        mark_step("Injecting retrieved cookies and reloading with new user agent")
        cam2 = browser2 = context2 = page2 = None
        try:
            cam2, browser2, context2, page2 = await bypasser.setup_browser(
                proxy=proxy, user_agent=cookie_payload.get("user_agent")
            )
            cookie_list = [
                {"name": name, "value": value, "url": url}
                for name, value in cookie_payload.get("cookies", {}).items()
            ]
            if cookie_list:
                await context2.add_cookies(cookie_list)
            await page2.goto(url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)
            final_title = await page2.title()
            final_html = await page2.content()
            if is_cloudflare_challenge(final_title, final_html):
                finalize_progress()
                return {
                    "success": False,
                    "message": "Cloudflare challenge still present after injecting cookies.",
                    "cloudflare_detected": True,
                }
            mark_step("Capturing screenshot after successful bypass")
            screenshot = await page2.screenshot(full_page=True)
            finalize_progress()
            return {
                "success": True,
                "title": final_title,
                "final_url": page2.url,
                "cloudflare_detected": True,
                "screenshot": screenshot,
                "message": "Cloudflare bypass succeeded after cookie injection.",
            }
        except Exception as exc:  # pylint: disable=broad-except
            finalize_progress()
            return {"success": False, "message": f"Automation browser failed: {exc}", "cloudflare_detected": True}
        finally:
            await bypasser.cleanup_browser(cam2, browser2, context2, page2)


def handle_api_error(response: Any, target: str) -> None:
    """Surface API errors inside the Streamlit UI."""
    error_detail = safe_json(response).get("detail", "Unknown error")
    st.error(f"{target} failed: {error_detail}")


client = get_api_client()

st.markdown("---")

with st.expander("1. /html endpoint"):
    html_url = st.text_input("Target URL for HTML", key="html_url", placeholder="https://protected.example")
    html_proxy = st.text_input("Proxy (optional)", key="html_proxy")
    html_retries = st.number_input("Retries", key="html_retries", min_value=1, max_value=10, value=5)
    html_bypass = st.checkbox("Force fresh cookies (bypass cache)", key="html_force_bypass")
    html_status = st.empty()
    html_result = st.empty()

    if st.button("Fetch HTML", key="fetch_html_button"):
        if not html_url:
            html_status.warning("Please enter a target URL.")
        else:
            html_status.info("Calling /html ...")
            params = {
                "url": html_url,
                "retries": html_retries,
                "bypassCookieCache": str(html_bypass).lower(),
            }
            if html_proxy:
                params["proxy"] = html_proxy
            response = client.get("/html", params=params)
            if response.ok:
                summary = describe_html_response(response)
                html_status.success("HTML fetched.")
                html_result.json(summary)
                snippet = response.text or ""
                html_result.code(snippet[:4000] + ("...(truncated)" if len(snippet) > 4000 else ""), language="html")
            else:
                html_result.empty()
                handle_api_error(response, "/html")

with st.expander("2. /cookies endpoint"):
    cookie_url = st.text_input("Target URL for cookies", key="cookie_url", placeholder="https://protected.example")
    cookie_proxy = st.text_input("Proxy (optional)", key="cookie_proxy")
    cookie_status = st.empty()
    cookie_result = st.empty()

    if st.button("Fetch cookies", key="fetch_cookies_button"):
        if not cookie_url:
            cookie_status.warning("Please enter a URL first.")
        else:
            cookie_status.info("Requesting /cookies ...")
            params = {"url": cookie_url}
            if cookie_proxy:
                params["proxy"] = cookie_proxy
            response = client.get("/cookies", params=params)
            if response.ok:
                cookie_status.success("Cookies received.")
                cookie_result.json(response.json())
            else:
                cookie_result.empty()
                handle_api_error(response, "/cookies")

with st.expander("3. Cache stats & clear"):
    stats_result = st.empty()
    clear_result = st.empty()
    col_stats, col_clear = st.columns(2)
    if col_stats.button("Show cache stats", key="cache_stats_button"):
        stats_result.info("Requesting /cache/stats ...")
        response = client.get("/cache/stats")
        if response.ok:
            stats_result.success("Cache stats")
            stats_result.json(response.json())
        else:
            stats_result.empty()
            handle_api_error(response, "/cache/stats")
    if col_clear.button("Clear cache", key="cache_clear_button"):
        clear_result.info("Requesting /cache/clear ...")
        response = client.post("/cache/clear")
        if response.ok:
            clear_result.success("Cache cleared.")
            clear_result.json(response.json())
        else:
            clear_result.empty()
            handle_api_error(response, "/cache/clear")

with st.expander("4. Browser automation & screenshot"):
    automation_url = st.text_input("Automation target URL", key="automation_url")
    automation_proxy = st.text_input("Proxy (optional)", key="automation_proxy")
    automation_status = st.empty()
    automation_log = st.empty()
    automation_progress = st.progress(0.0)
    automation_output = st.empty()

    if st.button("Run automation", key="automation_run_button"):
        automation_log.text("Preparing automation log...")
        log_lines = []

        def append_log(message: str) -> None:
            log_lines.append(message)
            automation_log.info("\n".join(log_lines))

        automation_progress.progress(0.0)
        automation_output.empty()

        if not automation_url:
            automation_status.warning("Please enter a URL to automate.")
        else:
            automation_status.info("Starting automation...")
            try:
                automation_result = run_async(
                    automation_flow(
                        automation_url,
                        automation_proxy if automation_proxy else None,
                        client,
                        log_fn=append_log,
                        progress_fn=automation_progress.progress,
                    )
                )
            except Exception as exc:  # pylint: disable=broad-except
                automation_status.error(f"Automation crashed: {exc}")
            else:
                if automation_result.get("success"):
                    automation_status.success(automation_result.get("message"))
                    automation_output.json(
                        {
                            "title": automation_result.get("title"),
                            "final_url": automation_result.get("final_url"),
                            "cloudflare_challenge": automation_result.get("cloudflare_detected"),
                        }
                    )
                    screenshot_data = automation_result.get("screenshot")
                    if screenshot_data:
                        st.image(screenshot_data, caption="Screenshot after automation", use_column_width=True)
                else:
                    automation_status.error(automation_result.get("message"))