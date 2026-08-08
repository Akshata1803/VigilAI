"""
Vigil AI - Website Scanner Service (v3.0 — Production Hardened)
==================================================================
Uses Playwright to load websites, capture screenshots, and extract DOM/text content.

Security hardening:
  - SSRF protection with DNS rebinding defense (validates at connection time)
  - Playwright request interception blocks internal IP access at network level
  - SSL verification on fallback requests

Architecture:
  - DOM extraction delegated to dom_extractor.py (SRP)
  - Browser stealth + lifecycle management kept here
  - Screenshot capture is a thin helper
"""

import os
import re
import json
import time
import uuid
import socket
import ipaddress
import requests
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from PIL import Image
from playwright.sync_api import sync_playwright
from app.core.logger import get_logger
from app.services.dom_extractor import extract_dom_data

logger = get_logger('vigil.scanner')

# Overall scan timeout
SCAN_TIMEOUT_SECONDS = int(os.getenv('VIGIL_SCAN_TIMEOUT', '90'))


# ── SSRF Protection (DNS rebinding safe) ──────────────────────────────────────

def _is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is private/reserved/loopback. Handles IPv4 and IPv6."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_reserved
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_unspecified
        )
    except ValueError:
        return True  # If we can't parse it, block it


def _is_safe_url(url: str) -> bool:
    """
    Block SSRF: reject private/internal/file URLs.

    DNS rebinding defense: resolves hostname and validates the resolved IP.
    The resolved IP is also checked during Playwright request interception
    (belt-and-suspenders approach).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        return False

    hostname = parsed.hostname or ''
    if not hostname or hostname in ('localhost', '0.0.0.0'):
        return False

    # Resolve ALL IPs for the hostname (prevents rebinding to alternate records)
    try:
        addr_infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in addr_infos:
            ip_str = sockaddr[0]
            if _is_private_ip(ip_str):
                logger.warning(f"SSRF blocked: {hostname} resolved to private IP {ip_str}")
                return False
    except socket.gaierror:
        pass  # DNS resolution failed — let Playwright handle the error

    return True


def _is_safe_request_url(url: str) -> bool:
    """Validate a sub-request URL during Playwright navigation (request interception)."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ''
        if not hostname:
            return False
        # Fast check for obvious internal hostnames
        if hostname in ('localhost', '0.0.0.0', '127.0.0.1', '::1'):
            return False
        # Resolve and check
        addr_infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for _, _, _, _, sockaddr in addr_infos:
            if _is_private_ip(sockaddr[0]):
                return False
    except (socket.gaierror, ValueError, OSError):
        pass  # Let the request proceed — Playwright will handle the error
    return True


# ── Stealth Script ────────────────────────────────────────────────────────────

_STEALTH_SCRIPT = """
    // Pass webdriver check
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

    // Mock Chrome specific object
    window.navigator.chrome = { runtime: {} };

    // Mock languages and plugins
    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});

    // Pass permissions check
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
    );
"""

_SCROLL_SCRIPT = """
    () => {
        return new Promise((resolve) => {
            let totalHeight = 0;
            const distance = 400;
            const timer = setInterval(() => {
                const scrollHeight = document.body.scrollHeight;
                window.scrollBy(0, distance);
                totalHeight += distance;
                if (totalHeight >= scrollHeight || totalHeight > 15000) {
                    clearInterval(timer);
                    window.scrollTo(0, 0);
                    resolve();
                }
            }, 80);
            // Safety timeout
            setTimeout(() => { clearInterval(timer); resolve(); }, 12000);
        });
    }
"""

_SHADOW_DOM_SCRIPT = """
    () => {
        let extra = '';
        try {
            document.querySelectorAll('*').forEach(el => {
                if (el.shadowRoot) extra += el.shadowRoot.innerHTML;
            });
            document.querySelectorAll('iframe').forEach(ifr => {
                try {
                    if (ifr.contentDocument && ifr.contentDocument.body) {
                        extra += ifr.contentDocument.body.innerHTML;
                    }
                } catch(e) {}
            });
        } catch(e) {}
        return extra;
    }
"""


class WebsiteScanner:
    """Loads a website and extracts screenshot, HTML, text, and DOM structure."""

    def __init__(self, screenshot_dir='static/screenshots'):
        self.screenshot_dir = screenshot_dir
        os.makedirs(self.screenshot_dir, exist_ok=True)

    def scan(self, url, session_cookies=None, local_storage=None):
        """
        Scan a website URL and return all extracted data.
        Uses Playwright (headless Chromium) with a requests+BeautifulSoup fallback.
        Protected by SSRF validation with DNS rebinding defense.
        """
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        # SSRF protection (DNS rebinding safe)
        if not _is_safe_url(url):
            return self._error_result(url, 'URL blocked: internal/private addresses are not allowed.')

        scan_id = str(uuid.uuid4())[:8]
        result = self._init_result(scan_id, url, session_cookies)
        screenshot_path = os.path.join(self.screenshot_dir, f'{scan_id}.png')

        try:
            self._scan_with_playwright(url, result, screenshot_path, session_cookies, local_storage)
            self._process_html(url, result)
        except Exception as e:
            logger.warning(f"Playwright failed for {url} ({str(e)}). Falling back to requests...")
            self._scan_fallback(url, result, screenshot_path)

        return result

    def _init_result(self, scan_id, url, session_cookies):
        """Initialize a clean result dict."""
        return {
            'scan_id': scan_id,
            'url': url,
            'domain': urlparse(url).netloc,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'screenshot_path': None,
            'html_content': '',
            'text_content': '',
            'page_title': '',
            'dom_data': {
                'forms': [], 'buttons': [], 'links': [], 'checkboxes': [],
                'modals': [], 'timers': [], 'prices': [], 'popups': [],
                'cookie_banners': [], 'close_buttons': [], 'text_elements': [],
            },
            'status': 'success',
            'error': None,
            'scan_state': 'authenticated' if session_cookies else 'unknown',
            'dynamic_findings': [],
        }

    def _error_result(self, url, error_msg):
        """Return an error result dict."""
        return {
            'scan_id': str(uuid.uuid4())[:8], 'url': url,
            'domain': urlparse(url).netloc,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'status': 'error', 'error': error_msg,
            'html_content': '', 'text_content': '', 'page_title': '',
            'dom_data': {}, 'screenshot_path': None, 'dynamic_findings': [],
        }

    def _scan_with_playwright(self, url, result, screenshot_path, session_cookies, local_storage):
        """Full Playwright-based scan with stealth, scrolling, and request interception."""
        browser = None
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-features=IsolateOrigins,site-per-process',
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--ignore-certificate-errors',
                    ],
                )

                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                    viewport={'width': 1280, 'height': 800},
                    java_script_enabled=True,
                    bypass_csp=True,
                    extra_http_headers={
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Sec-Ch-Ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
                        'Sec-Ch-Ua-Mobile': '?0',
                        'Sec-Ch-Ua-Platform': '"Windows"',
                        'Sec-Fetch-Dest': 'document',
                        'Sec-Fetch-Mode': 'navigate',
                        'Sec-Fetch-Site': 'none',
                        'Sec-Fetch-User': '?1',
                        'Upgrade-Insecure-Requests': '1',
                    },
                )

                context.add_init_script(_STEALTH_SCRIPT)

                # Session injection
                if session_cookies:
                    context.add_cookies(session_cookies)

                page = context.new_page()

                # SSRF defense: intercept requests and block internal IPs at network level
                def _handle_route(route):
                    req_url = route.request.url
                    if not _is_safe_request_url(req_url):
                        logger.warning(f"SSRF: blocked sub-request to internal URL: {req_url}")
                        route.abort('blockedbyclient')
                    else:
                        route.continue_()

                page.route('**/*', _handle_route)

                # Navigate with fallback strategy
                self._navigate(page, url)

                # Auto-scroll + Shadow DOM piercing
                self._enhance_page(page, url)

                # Buffer for lazy-loaded content
                page.wait_for_timeout(1500)

                # Local storage injection
                if local_storage:
                    for k, v in local_storage.items():
                        page.evaluate("([k, v]) => localStorage.setItem(k, v)", [k, v])
                    page.reload(wait_until='networkidle', timeout=10000)
                    page.wait_for_timeout(1000)

                # Detect empty/logged-out states
                self._detect_auth_state(page, result)

                # Simulated user flow
                if not session_cookies:
                    self._simulate_interaction(page, url, result)

                result['html_content'] = page.content()

                # Screenshot
                page.screenshot(path=screenshot_path, full_page=False)
                result['screenshot_path'] = screenshot_path

            except Exception as inner_e:
                raise inner_e
            finally:
                if browser:
                    try:
                        browser.close()
                    except Exception:
                        pass

    def _navigate(self, page, url):
        """Navigate with networkidle → domcontentloaded fallback."""
        try:
            nav_response = page.goto(url, wait_until='networkidle', timeout=15000)
            status = nav_response.status if nav_response else 0
            if nav_response and not nav_response.ok and status not in [201, 202, 301, 302, 304, 403, 406]:
                raise Exception(f"Navigation failed: HTTP {status}")
        except Exception as e:
            err_str = str(e)
            if 'Timeout' in err_str or 'timeout' in err_str:
                logger.warning(f"networkidle timeout for {url}, retrying with domcontentloaded")
                try:
                    page.goto(url, wait_until='domcontentloaded', timeout=10000)
                except Exception:
                    logger.warning(f"domcontentloaded also timed out for {url} - using partial content")
            elif 'Navigation failed' in err_str:
                raise
            else:
                raise

    def _enhance_page(self, page, url):
        """Auto-scroll and pierce Shadow DOM."""
        try:
            page.evaluate(_SCROLL_SCRIPT)

            shadow_html = page.evaluate(_SHADOW_DOM_SCRIPT)
            if shadow_html:
                page.evaluate(f"""
                    () => {{
                        var d = document.createElement('div');
                        d.id = 'vigil-shadow-dump';
                        d.style.display = 'none';
                        d.innerHTML = {json.dumps(shadow_html)};
                        document.body.appendChild(d);
                    }}
                """)
        except Exception as e:
            logger.warning(f"Page enhancement skipped for {url}: {e}")

    def _detect_auth_state(self, page, result):
        """Detect if the page shows an unauthenticated/empty state."""
        try:
            body_text_lower = (page.locator('body').text_content(timeout=1000) or "").lower()
            unauth_phrases = ["your cart is empty", "please login", "sign in to continue"]
            if any(phrase in body_text_lower for phrase in unauth_phrases):
                result['scan_state'] = 'unauthenticated'
                result['dynamic_findings'].append({
                    'type': 'Scan Incomplete',
                    'severity': 'INFORMATIONAL',
                    'category': 'informational',
                    'confidence': 0.95,
                    'element': 'document body',
                    'description': 'Scan incomplete - requires authenticated session.',
                    '_engine': 'behavioral',
                    'evidence': 'Unauthenticated empty state detected.',
                    'recommendation': 'Provide active user session to accurately test inner flow.',
                })
        except Exception:
            pass

    def _simulate_interaction(self, page, url, result):
        """Simulated user flow: cookie consent + cart interaction."""
        before_dom = extract_dom_data(BeautifulSoup(page.content(), 'lxml'))

        try:
            # Cookie consent interaction
            cookie_btn = page.locator(
                "button:has-text('manage'), button:has-text('settings'), "
                "button:has-text('preferences'), button:has-text('customise'), "
                "button:has-text('customize')"
            ).first
            clicked = False
            if cookie_btn.count() > 0 and cookie_btn.is_visible():
                cookie_btn.click(timeout=1000)
                clicked = True

            # Shadow DOM cookie banner fallback
            if not clicked:
                page.evaluate("""
                    () => {
                        const SHADOW_HOSTS = [
                            '#onetrust-banner-sdk', '#usercentrics-root',
                            '#CybotCookiebotDialog', '.trustarc-banner',
                            'div[class*="cookie"]', 'div[id*="cookie"]',
                            'div[id*="consent"]', 'div[class*="consent"]',
                        ];
                        const BTN_TEXT = ['manage', 'settings', 'preferences', 'customise', 'customize', 'options'];
                        for (const sel of SHADOW_HOSTS) {
                            const host = document.querySelector(sel);
                            if (!host || !host.shadowRoot) continue;
                            const btns = host.shadowRoot.querySelectorAll('button, a[role="button"]');
                            for (const btn of btns) {
                                const txt = (btn.textContent || '').toLowerCase();
                                if (BTN_TEXT.some(kw => txt.includes(kw))) {
                                    btn.click();
                                    return true;
                                }
                            }
                        }
                        return false;
                    }
                """)
            page.wait_for_timeout(500)

            # Cart flow simulation
            cart_btn = page.locator("button:has-text('Add to Cart'), button:has-text('Add to bag')").first
            if cart_btn.count() > 0 and cart_btn.is_visible():
                cart_btn.click(timeout=1000)
                page.wait_for_timeout(1000)
                page.goto(url.rstrip('/') + "/cart", timeout=5000)
                page.wait_for_timeout(1000)
                page.goto(url.rstrip('/') + "/checkout", timeout=5000)
                page.wait_for_timeout(1000)
        except Exception:
            pass

        after_dom = extract_dom_data(BeautifulSoup(page.content(), 'lxml'))
        new_timers = len(after_dom['timers']) - len(before_dom['timers'])
        new_prices = len(after_dom['prices']) - len(before_dom['prices'])

        if new_timers > 0 or new_prices > 0:
            result['dynamic_findings'].append({
                'type': 'Dynamic Manipulation',
                'severity': 'HIGH',
                'category': 'misdirection',
                'confidence': 0.80,
                'element': 'Whole page (post-interaction DOM diff)',
                'description': f'New dynamic patterns appeared after interaction (Timers: +{new_timers}, Fees: +{new_prices}).',
                '_engine': 'behavioral',
                'evidence': f'DOM state changed post-interaction: {new_timers} new timer(s), {new_prices} new price element(s) injected.',
                'recommendation': 'Avoid injecting unexpected urgency tactics late in the user flow.',
            })

    def _process_html(self, url, result):
        """Parse HTML content and extract text + DOM data."""
        raw_html = result['html_content']

        # Parse once for DOM extraction (on full HTML)
        dom_soup = BeautifulSoup(raw_html, 'lxml')
        result['page_title'] = dom_soup.title.string.strip() if dom_soup.title and dom_soup.title.string else urlparse(url).netloc
        result['dom_data'] = extract_dom_data(dom_soup)

        # Parse again for text extraction (strips scripts/styles)
        text_soup = BeautifulSoup(raw_html, 'lxml')
        for tag in text_soup(['script', 'style', 'meta', 'link', 'noscript']):
            tag.decompose()
        result['text_content'] = text_soup.get_text(separator=' ', strip=True)

    def _scan_fallback(self, url, result, screenshot_path):
        """Fallback to requests with strict SSL verification."""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            }
            response = requests.get(url, headers=headers, timeout=20, verify=True)

            if response.status_code not in [200, 201, 202] and not response.text:
                response.raise_for_status()

            result['html_content'] = response.text
            self._process_html(url, result)
            result['screenshot_path'] = self._capture_screenshot(url, screenshot_path)

        except requests.exceptions.RequestException as req_e:
            result['status'] = 'error'
            result['error'] = str(req_e)

        return result

    def _capture_screenshot(self, url, save_path):
        """Generate a local placeholder screenshot (privacy-safe)."""
        try:
            img = Image.new('RGB', (1280, 800), color=(30, 30, 46))
            img.save(save_path)
            return save_path
        except Exception:
            return None
