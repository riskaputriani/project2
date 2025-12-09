import asyncio
import time

import streamlit as st

from cf_bypasser.core.bypasser import CamoufoxBypasser


def run_async(coro):
    """Run an async coroutine using asyncio.run for clean shutdown."""
    return asyncio.run(coro)


@st.cache_resource
def get_bypasser():
    """Cache a single bypasser instance for this Streamlit session."""
    return CamoufoxBypasser(max_retries=5, log=True)


bypasser = get_bypasser()


def collect_cache_stats():
    """Return cache statistics similar to `/cache/stats`."""
    bypasser.cookie_cache.clear_expired()
    cache = bypasser.cookie_cache.cache
    active_entries = sum(1 for record in cache.values() if not record.is_expired())
    total_entries = len(cache)
    expired_entries = total_entries - active_entries
    hostnames = list(cache.keys())
    return {
        "cached_entries": active_entries,
        "expired_entries": expired_entries,
        "total_hostnames": total_entries,
        "hostnames": hostnames,
    }


def clear_cookie_cache():
    """Clear all cached cookies and reset helpers."""
    bypasser.cookie_cache.clear_all()


def summarize_html_response(data: dict, duration_ms: int) -> dict:
    """Build a JSON-friendly payload for HTML results."""
    return {
        "final_url": data.get("url"),
        "user_agent": data.get("user_agent"),
        "cookie_count": len(data.get("cookies", {})),
        "processing_time_ms": duration_ms,
        "status_code": data.get("status_code"),
    }


st.set_page_config(page_title="Cloudflare Bypass Streamlit", layout="wide")
st.title("Cloudflare Bypass for Scraping (Streamlit)")
st.write(
    "This interface exposes the same functionality as the FastAPI server but "
    "runs entirely inside Streamlit. Each section mirrors one of the legacy "
    "endpoints while still reusing Camoufox for Cloudflare bypassing."
)

st.markdown("---")

with st.expander("1. /html endpoint"):
    html_url = st.text_input("Target URL", key="html_url", placeholder="https://protected-site.com")
    html_proxy = st.text_input("Proxy (optional)", key="html_proxy")
    html_bypass = st.checkbox("Force fresh cookie generation", key="html_bypass_cache")
    if st.button("Fetch HTML", key="fetch_html_button"):
        if not html_url:
            st.warning("Please provide a target URL before fetching HTML.")
        else:
            with st.spinner("Generating Cloudflare cookies and fetching HTML..."):
                start = time.perf_counter()
                html_data = run_async(
                    bypasser.get_or_generate_html(
                        html_url,
                        html_proxy if html_proxy else None,
                        bypass_cache=html_bypass,
                    )
                )
                duration = int((time.perf_counter() - start) * 1000)
            if html_data:
                st.success("HTML fetched successfully.")
                st.json(summarize_html_response(html_data, duration))
                st.code(html_data["html"][:4000] + ("...(truncated)" if len(html_data["html"]) > 4000 else ""), language="html")
            else:
                st.error("Failed to bypass Cloudflare and fetch HTML.")

with st.expander("2. /cookies endpoint"):
    cookie_url = st.text_input("Target URL", key="cookie_url", placeholder="https://protected-site.com")
    cookie_proxy = st.text_input("Proxy (optional)", key="cookie_proxy")
    if st.button("Fetch cookies", key="fetch_cookies_button"):
        if not cookie_url:
            st.warning("Please provide a target URL to generate cookies.")
        else:
            with st.spinner("Requesting cookies via Camoufox..."):
                cookie_data = run_async(
                    bypasser.get_or_generate_cookies(
                        cookie_url,
                        cookie_proxy if cookie_proxy else None,
                    )
                )
            if cookie_data:
                st.success("Cookies generated.")
                st.json({"cookies": cookie_data["cookies"], "user_agent": cookie_data["user_agent"]})
            else:
                st.error("Cookie generation failed.")

with st.expander("3. Cache stats & clear"):
    cache_stats_button = st.button("Show cache stats", key="cache_stats_button")
    cache_clear_button = st.button("Clear cache", key="cache_clear_button")
    if cache_stats_button:
        stats = collect_cache_stats()
        st.json(stats)
    if cache_clear_button:
        clear_cookie_cache()
        st.success("Cache cleared successfully.")

with st.expander("4. Browser automation & screenshot"):
    automation_url = st.text_input("Automation target URL", key="automation_url")
    automation_proxy = st.text_input("Proxy (optional)", key="automation_proxy")
    click_selector = st.text_input(
        "Optional CSS selector to click after bypassing CF (e.g. button#submit)",
        key="automation_click_selector",
    )
    wait_selector = st.text_input(
        "Optional CSS selector to wait for after click (leave empty to skip)",
        key="automation_wait_selector",
    )
    automation_bypass_cache = st.checkbox("Force fresh cookies before automation", key="automation_bypass")
    if st.button("Run automation", key="automation_run_button"):
        if not automation_url:
            st.warning("Provide a URL to run automation.")
        else:
            with st.spinner("Launching Camoufox automation..."):
                automation_data = run_async(
                    bypasser.run_automation(
                        automation_url,
                        proxy=automation_proxy if automation_proxy else None,
                        click_selector=click_selector if click_selector else None,
                        wait_selector=wait_selector if wait_selector else None,
                        bypass_cache=automation_bypass_cache,
                    )
                )
            if automation_data:
                st.success("Automation complete.")
                st.json(
                    {
                        "title": automation_data["title"],
                        "url": automation_data["url"],
                        "user_agent": automation_data["user_agent"],
                        "cookies_cached": len(automation_data["cookies"]),
                    }
                )
                st.image(automation_data["screenshot"], caption="Screenshot after bypass", width=700)
            else:
                st.error("Automation run failed after bypass attempt.")
