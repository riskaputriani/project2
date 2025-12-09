import asyncio
import importlib
import importlib.machinery
import importlib.util
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional
from urllib.parse import urlparse

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parent
MODULE_ROOT = ROOT_DIR / 'CloudflareBypassForScraping'
if str(MODULE_ROOT) not in sys.path:
    sys.path.append(str(MODULE_ROOT))

BROWSERFORGE_DATA_ROOT = ROOT_DIR / 'browserforge_data'
HEADERS_PACKAGE_DIR = BROWSERFORGE_DATA_ROOT / 'headers'
FINGERPRINTS_PACKAGE_DIR = BROWSERFORGE_DATA_ROOT / 'fingerprints'
HEADERS_DATA_DIR = HEADERS_PACKAGE_DIR / 'data'
FINGERPRINTS_DATA_DIR = FINGERPRINTS_PACKAGE_DIR / 'data'
HEADERS_DATA_DIR.mkdir(parents=True, exist_ok=True)
FINGERPRINTS_DATA_DIR.mkdir(parents=True, exist_ok=True)

import browserforge.download as bf_download

bf_download.DATA_DIRS['headers'] = HEADERS_DATA_DIR
bf_download.DATA_DIRS['fingerprints'] = FINGERPRINTS_DATA_DIR

PLAYWRIGHT_CAPTCHA_ADDON_ROOT = ROOT_DIR / 'playwright_captcha_addon'


def _load_local_playwright_add_init_script() -> None:
    """Point the Camoufox addon writer at workspace storage."""
    module_name = 'playwright_captcha.utils.camoufox_add_init_script.add_init_script'
    module_path = PLAYWRIGHT_CAPTCHA_ADDON_ROOT / 'local_add_init_script.py'

    if not module_path.exists():
        return

    pkg_name = module_name.rsplit('.', 1)[0]
    try:
        importlib.import_module(pkg_name)
    except ImportError:
        pass

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if not spec or not spec.loader:
        return

    module = importlib.util.module_from_spec(spec)
    module.__package__ = pkg_name
    sys.modules[module_name] = module
    spec.loader.exec_module(module)


_load_local_playwright_add_init_script()


def _ensure_browserforge_package() -> None:
    spec = importlib.util.find_spec('browserforge')
    search_locations = list(spec.submodule_search_locations or []) if spec else []
    pkg = sys.modules.get('browserforge')
    if pkg is None:
        pkg_spec = importlib.machinery.ModuleSpec('browserforge', loader=None, is_package=True)
        pkg = importlib.util.module_from_spec(pkg_spec)
        pkg.__path__ = []
        sys.modules['browserforge'] = pkg
    current_paths = list(getattr(pkg, '__path__', []))
    for location in search_locations:
        if location and location not in current_paths:
            current_paths.append(location)
    local_root = str(BROWSERFORGE_DATA_ROOT)
    if local_root not in current_paths:
        current_paths.insert(0, local_root)
    pkg.__path__ = current_paths


def _load_local_package(package_name: str, package_dir: Path) -> None:
    init_file = package_dir / '__init__.py'
    if not init_file.exists():
        return
    sys.modules.pop(package_name, None)
    spec = importlib.util.spec_from_file_location(package_name, init_file)
    if not spec or not spec.loader:
        return
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(init_file)
    module.__package__ = package_name
    module.__path__ = [str(package_dir)]
    sys.modules[package_name] = module
    spec.loader.exec_module(module)


def _prepare_browserforge_local_modules() -> None:
    _ensure_browserforge_package()
    _load_local_package('browserforge.headers', HEADERS_PACKAGE_DIR)
    _load_local_package('browserforge.fingerprints', FINGERPRINTS_PACKAGE_DIR)


_prepare_browserforge_local_modules()

from cf_bypasser.core.bypasser import CamoufoxBypasser


DEFAULT_RETRIES = 5
CACHE_FILE = ROOT_DIR / 'cf_cookie_cache.json'

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(name)s - %(message)s',
    datefmt='%H:%M:%S',
)


def run_async(coro: Awaitable[Any]) -> Any:
    return asyncio.run(coro)


@st.cache_resource(show_spinner=False)
def get_cached_bypasser() -> CamoufoxBypasser:
    return CamoufoxBypasser(max_retries=DEFAULT_RETRIES, log=True, cache_file=str(CACHE_FILE))


def _get_bypasser_for_retries(retries: int) -> CamoufoxBypasser:
    if retries == DEFAULT_RETRIES:
        return get_cached_bypasser()
    return CamoufoxBypasser(max_retries=retries, log=True, cache_file=str(CACHE_FILE))


def is_safe_url(url: str) -> bool:
    try:
        parsed_url = urlparse(url)
        ip_pattern = re.compile(
            r'^(127\.0\.0\.1|localhost|0\.0\.0\.0|::1|10\.\d+\.\d+\.\d+|172\.1[6-9]\.\d+\.\d+|172\.2[0-9]\.\d+\.\d+|172\.3[0-1]\.\d+\.\d+|192\.168\.\d+\.\d+)$'
        )
        hostname = parsed_url.hostname
        if (hostname and ip_pattern.match(hostname)) or parsed_url.scheme == 'file':
            return False
        return True
    except Exception:
        return False


def _validate_url(value: str) -> str:
    cleaned = (value or '').strip()
    if not cleaned:
        raise ValueError('Please enter a target URL.')
    if not is_safe_url(cleaned):
        raise ValueError('Invalid or unsafe URL; localhost and private IP ranges are not allowed.')
    return cleaned


def _validate_proxy(proxy: Optional[str]) -> Optional[str]:
    if not proxy:
        return None
    normalized = proxy.strip()
    if not normalized:
        return None
    allowed = ('http://', 'https://', 'socks4://', 'socks5://')
    lowered = normalized.lower()
    if not any(lowered.startswith(prefix) for prefix in allowed):
        raise ValueError('Proxy must start with http://, https://, socks4://, or socks5://')
    return normalized


async def _async_get_cookies(url: str, proxy: Optional[str], retries: int) -> Dict[str, Any]:
    bypasser = _get_bypasser_for_retries(retries)
    result = await bypasser.get_or_generate_cookies(url, proxy)
    if not result:
        raise RuntimeError('Cloudflare bypass did not return any cookies.')
    return result


async def _async_get_html(url: str, proxy: Optional[str], bypass_cache: bool, retries: int) -> Dict[str, Any]:
    bypasser = _get_bypasser_for_retries(retries)
    result = await bypasser.get_or_generate_html(url, proxy, bypass_cache=bypass_cache)
    if not result:
        raise RuntimeError('Cloudflare bypass failed to produce HTML.')
    return result


def fetch_cookies(url: str, proxy: Optional[str], retries: int) -> Dict[str, Any]:
    start = time.time()
    data = run_async(_async_get_cookies(url, proxy, retries))
    elapsed = int((time.time() - start) * 1000)
    cookies = data.get('cookies') or {}
    return {
        'cookies': cookies,
        'user_agent': data.get('user_agent'),
        'processing_time_ms': elapsed,
        'cf_cookie_names': [name for name in cookies if name.startswith(('cf_', '__cf'))],
    }


def fetch_html(url: str, proxy: Optional[str], retries: int, bypass_cache: bool) -> Dict[str, Any]:
    start = time.time()
    data = run_async(_async_get_html(url, proxy, bypass_cache, retries))
    elapsed = int((time.time() - start) * 1000)
    cookies = data.get('cookies') or {}
    return {
        'html': data.get('html', ''),
        'final_url': data.get('url'),
        'user_agent': data.get('user_agent'),
        'status_code': data.get('status_code', 200),
        'cookies': cookies,
        'cookie_count': len(cookies),
        'cf_cookie_names': [name for name in cookies if name.startswith(('cf_', '__cf'))],
        'processing_time_ms': elapsed,
    }


def get_cache_stats() -> Dict[str, Any]:
    bypasser = get_cached_bypasser()
    cache = bypasser.cookie_cache.cache
    total_entries = len(cache)
    active_entries = sum(1 for entry in cache.values() if not entry.is_expired())
    expired_entries = total_entries - active_entries
    return {
        'cached_entries': active_entries,
        'expired_entries': expired_entries,
        'total_hostnames': total_entries,
        'hostnames': list(cache.keys()),
    }


def clear_cache() -> Dict[str, Any]:
    bypasser = get_cached_bypasser()
    entries = len(bypasser.cookie_cache.cache)
    bypasser.cookie_cache.clear_all()
    return {
        'status': 'success',
        'message': f'Cache cleared ({entries} entries removed).',
        'entries_removed': entries,
    }


def is_cloudflare_challenge(title: str, html: str) -> bool:
    title_lower = (title or '').lower().strip()
    html_lower = (html or '').lower()
    return (
        'just a moment' in title_lower
        or '<title>just a moment' in html_lower
        or 'please complete the captcha' in html_lower
    )


async def automation_flow(
    url: str,
    proxy: Optional[str],
    log_fn: Callable[[str], None],
    progress_fn: Callable[[float], None],
) -> Dict[str, Any]:
    total_steps = 4
    progress_counter = 0

    def mark_step(message: str) -> None:
        nonlocal progress_counter
        log_fn(message)
        if progress_counter < total_steps:
            progress_counter += 1
            progress_fn(min(progress_counter / total_steps, 1.0))

    def finalize_progress() -> None:
        nonlocal progress_counter
        progress_counter = total_steps
        progress_fn(1.0)

    bypasser = CamoufoxBypasser(max_retries=DEFAULT_RETRIES, log=True)
    cam1 = browser1 = context1 = page1 = None
    cam2 = browser2 = context2 = page2 = None

    class StreamlitLogHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                log_fn(f"{record.levelname}: {record.getMessage()}")
            except RuntimeError:
                pass

    handler = StreamlitLogHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    try:
        mark_step('Launching browser for initial inspection')
        cam1, browser1, context1, page1 = await bypasser.setup_browser(proxy=proxy, lang='en-US')
        await page1.goto(url, wait_until='domcontentloaded', timeout=20000)
        await asyncio.sleep(2)
        title = await page1.title()
        html = await page1.content()
        if not is_cloudflare_challenge(title, html):
            mark_step('No Cloudflare challenge detected')
            mark_step('Capturing screenshot for clean page')
            screenshot = await page1.screenshot(full_page=True)
            finalize_progress()
            return {
                'success': True,
                'title': title,
                'final_url': page1.url,
                'cloudflare_detected': False,
                'screenshot': screenshot,
                'message': 'Reached the page without a challenge.',
            }
        mark_step('Cloudflare challenge detected; requesting cookies')
        try:
            cookie_payload = await _async_get_cookies(url, proxy, DEFAULT_RETRIES)
        except Exception as exc:
            finalize_progress()
            return {
                'success': False,
                'message': f'Cookie retrieval failed: {exc}',
                'cloudflare_detected': True,
            }
        mark_step('Injecting cookies and reloading with bypassed UA')
        cam2, browser2, context2, page2 = await bypasser.setup_browser(
            proxy=proxy, lang='en-US', user_agent=cookie_payload.get('user_agent')
        )
        cookie_list = [
            {'name': name, 'value': value, 'url': url}
            for name, value in cookie_payload.get('cookies', {}).items()
        ]
        if cookie_list:
            await context2.add_cookies(cookie_list)
        await page2.goto(url, wait_until='domcontentloaded', timeout=20000)
        await asyncio.sleep(2)
        final_title = await page2.title()
        final_html = await page2.content()
        if is_cloudflare_challenge(final_title, final_html):
            finalize_progress()
            return {
                'success': False,
                'message': 'Cloudflare challenge still present after injecting cookies.',
                'cloudflare_detected': True,
            }
        mark_step('Capturing screenshot after bypass')
        screenshot = await page2.screenshot(full_page=True)
        finalize_progress()
        return {
            'success': True,
            'title': final_title,
            'final_url': page2.url,
            'cloudflare_detected': True,
            'screenshot': screenshot,
            'message': 'Cloudflare bypass succeeded after cookie injection.',
        }
    except Exception as exc:
        finalize_progress()
        return {
            'success': False,
            'message': f'Automation failed: {exc}',
            'cloudflare_detected': True,
        }
    finally:
        root_logger.removeHandler(handler)
        await bypasser.cleanup_browser(cam1, browser1, context1, page1)
        await bypasser.cleanup_browser(cam2, browser2, context2, page2)


st.set_page_config(page_title='Cloudflare Bypass Streamlit', layout='wide')
st.title('Cloudflare Bypass For Scraping (Streamlit)')
st.write(
    'This Streamlit surface replaces the legacy FastAPI interfaces while giving you the same HTML/cookie/cache flows plus a live automation view powered by Camoufox.'
)

st.markdown('---')

with st.expander('1. /html endpoint'):
    html_url = st.text_input('Target URL for HTML', key='html_url', placeholder='https://protected.example')
    html_proxy = st.text_input('Proxy (optional)', key='html_proxy')
    html_retries = st.number_input('Retries', key='html_retries', min_value=1, max_value=10, value=DEFAULT_RETRIES)
    html_force = st.checkbox('Force fresh cookies (bypass cache)', key='html_force_bypass')
    html_status = st.empty()
    html_summary = st.empty()
    html_preview = st.empty()

    if st.button('Fetch HTML', key='fetch_html_button'):
        try:
            target = _validate_url(html_url)
            proxy = _validate_proxy(html_proxy)
            html_status.info('/html call in progress...')
            result = fetch_html(target, proxy, html_retries, html_force)
        except ValueError as exc:
            html_status.warning(str(exc))
            html_summary.empty()
            html_preview.empty()
        except Exception as exc:
            html_status.error(f'/html request failed: {exc}')
            html_summary.empty()
            html_preview.empty()
        else:
            html_status.success('HTML fetched successfully.')
            html_summary.json({
                'status_code': result['status_code'],
                'final_url': result['final_url'],
                'processing_time_ms': result['processing_time_ms'],
                'cookie_count': result['cookie_count'],
                'cloudflare_cookies': result['cf_cookie_names'],
            })
            snippet = result.get('html', '')
            if snippet:
                truncated = snippet[:4000]
                suffix = '' if len(snippet) <= 4000 else '...(truncated)'
                html_preview.code(truncated + suffix, language='html')
            else:
                html_preview.info('No HTML payload returned.')

with st.expander('2. /cookies endpoint'):
    cookie_url = st.text_input('Target URL for cookies', key='cookie_url', placeholder='https://protected.example')
    cookie_proxy = st.text_input('Proxy (optional)', key='cookie_proxy')
    cookie_status = st.empty()
    cookie_output = st.empty()

    if st.button('Fetch cookies', key='fetch_cookies_button'):
        try:
            target = _validate_url(cookie_url)
            proxy = _validate_proxy(cookie_proxy)
            cookie_status.info('/cookies call in progress...')
            data = fetch_cookies(target, proxy, DEFAULT_RETRIES)
        except ValueError as exc:
            cookie_status.warning(str(exc))
            cookie_output.empty()
        except Exception as exc:
            cookie_status.error(f'/cookies request failed: {exc}')
            cookie_output.empty()
        else:
            cookie_status.success('Cookies retrieved.')
            cookie_output.json({
                'cookie_count': len(data['cookies']),
                'cloudflare_cookies': data['cf_cookie_names'],
                'user_agent': data['user_agent'],
                'processing_time_ms': data['processing_time_ms'],
            })

with st.expander('3. Cache stats & clear'):
    stats_result = st.empty()
    clear_result = st.empty()
    col_stats, col_clear = st.columns(2)

    if col_stats.button('Show cache stats', key='cache_stats_button'):
        try:
            stats = get_cache_stats()
        except Exception as exc:
            stats_result.error(f'Cache stats failed: {exc}')
        else:
            stats_result.success('Cache stats')
            stats_result.json(stats)
    if col_clear.button('Clear cache', key='cache_clear_button'):
        try:
            payload = clear_cache()
        except Exception as exc:
            clear_result.error(f'Cache clear failed: {exc}')
        else:
            clear_result.success(payload['message'])
            clear_result.json(payload)

with st.expander('4. Browser automation & screenshot'):
    automation_url = st.text_input('Automation target URL', key='automation_url')
    automation_proxy = st.text_input('Proxy (optional)', key='automation_proxy')
    automation_status = st.empty()
    automation_log = st.empty()
    automation_progress = st.progress(0.0)
    automation_output = st.empty()
    automation_screenshot = st.empty()

    if st.button('Run automation', key='automation_run_button'):
        automation_status.info('Preparing automation...')
        automation_log.text('Automation log will appear here...')
        log_messages = []

        def append_log(entry: str) -> None:
            log_messages.append(entry)
            automation_log.info('\\n'.join(log_messages))

        automation_progress.progress(0.0)
        automation_output.empty()
        automation_screenshot.empty()

        try:
            target = _validate_url(automation_url)
            proxy = _validate_proxy(automation_proxy)
        except ValueError as exc:
            automation_status.warning(str(exc))
        else:
            automation_status.info('Running automation flow...')
            try:
                result = run_async(
                    automation_flow(
                        target,
                        proxy,
                        log_fn=append_log,
                        progress_fn=automation_progress.progress,
                    )
                )
            except Exception as exc:
                automation_status.error(f'Automation crashed: {exc}')
            else:
                if result.get('success'):
                    automation_status.success(result.get('message'))
                    automation_output.json(
                        {
                            'title': result.get('title'),
                            'final_url': result.get('final_url'),
                            'cloudflare_challenge': result.get('cloudflare_detected'),
                        }
                    )
                    screenshot_data = result.get('screenshot')
                    if screenshot_data:
                        automation_screenshot.image(
                            screenshot_data,
                            caption='Screenshot after automation',
                            width=700,
                        )
                else:
                    automation_status.error(result.get('message'))
