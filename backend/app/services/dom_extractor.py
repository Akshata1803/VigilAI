"""
Vigil AI — DOM Extractor
==========================
Extracts structured DOM data from BeautifulSoup-parsed HTML for dark pattern analysis.

Separated from scanner.py for:
  - Single Responsibility: extraction logic is independent of browser lifecycle
  - Testability: can be tested against fixture HTML without Playwright
  - Reusability: used by both Playwright and fallback request paths
"""

import re
from bs4 import BeautifulSoup


# Pre-compiled regex for price detection
_CURRENCY_RE = re.compile(r'[\$\€\£\₹\¥]\s*\d|\d+\.\d{2}')


def extract_dom_data(soup: BeautifulSoup) -> dict:
    """
    Extract structured DOM data for dark pattern analysis.

    Args:
        soup: BeautifulSoup instance of the page HTML

    Returns:
        dict with keys: forms, buttons, links, checkboxes, modals,
                        timers, prices, popups, cookie_banners,
                        close_buttons, text_elements
    """
    dom_data = {
        'forms': [],
        'buttons': [],
        'links': [],
        'checkboxes': [],
        'modals': [],
        'timers': [],
        'prices': [],
        'popups': [],
        'cookie_banners': [],
        'close_buttons': [],
        'text_elements': [],
    }

    _extract_forms(soup, dom_data)
    _extract_buttons(soup, dom_data)
    _extract_links(soup, dom_data)
    _extract_checkboxes(soup, dom_data)
    _extract_timers(soup, dom_data)
    _extract_prices(soup, dom_data)
    _extract_text_elements(soup, dom_data)

    return dom_data


def _extract_forms(soup, dom_data):
    """Extract form data including nested inputs."""
    for form in soup.find_all('form'):
        form_data = {
            'action': form.get('action', ''),
            'method': form.get('method', 'get'),
            'inputs': [],
            'text': form.get_text(strip=True)[:500],
        }
        for inp in form.find_all('input'):
            form_data['inputs'].append({
                'type': inp.get('type', 'text'),
                'name': inp.get('name', ''),
                'checked': inp.has_attr('checked'),
                'required': inp.has_attr('required'),
                'value': inp.get('value', ''),
                'placeholder': inp.get('placeholder', ''),
            })
        dom_data['forms'].append(form_data)


def _extract_buttons(soup, dom_data):
    """Extract button and submit input elements."""
    for btn in soup.find_all(['button', 'input']):
        if btn.name == 'input' and btn.get('type') not in ('submit', 'button'):
            continue
        btn_text = btn.get_text(strip=True) or btn.get('value', '')
        if btn_text:
            classes = ' '.join(btn.get('class', []))
            style = btn.get('style', '')
            dom_data['buttons'].append({
                'text': btn_text[:200],
                'classes': classes,
                'style': style,
                'type': btn.get('type', 'button'),
                'id': btn.get('id', ''),
            })


def _extract_links(soup, dom_data):
    """Extract anchor elements with metadata."""
    for link in soup.find_all('a'):
        link_text = link.get_text(strip=True)
        if link_text:
            href = link.get('href', '')
            classes = ' '.join(link.get('class', []))
            style = link.get('style', '')
            dom_data['links'].append({
                'text': link_text[:200],
                'href': href,
                'classes': classes,
                'style': style,
                'font_size_hint': 'small' if any(
                    kw in style.lower() + classes.lower()
                    for kw in ['small', 'tiny', 'xs', 'text-xs', 'fine-print', 'footnote']
                ) else 'normal',
            })


def _extract_checkboxes(soup, dom_data):
    """Extract checkbox inputs with associated labels."""
    for cb in soup.find_all('input', {'type': 'checkbox'}):
        label_text = ''
        label = cb.find_parent('label')
        if label:
            label_text = label.get_text(strip=True)
        elif cb.get('id'):
            label_el = soup.find('label', {'for': cb['id']})
            if label_el:
                label_text = label_el.get_text(strip=True)
        dom_data['checkboxes'].append({
            'checked': cb.has_attr('checked'),
            'name': cb.get('name', ''),
            'label': label_text[:300],
            'id': cb.get('id', ''),
        })


def _extract_timers(soup, dom_data):
    """Extract countdown/timer elements using tight keyword matching."""
    timer_classes = ['countdown', 'timer', 'count-down', 'count_down', 'flip-clock']
    timer_ids = ['countdown', 'timer', 'count-down']
    timer_text_kws = ['expires', 'hurry', 'ends in', 'offer ends', 'deal ends', 'time left']
    timer_data_attrs = [
        'data-countdown', 'data-timer', 'data-end-time', 'data-seconds',
        'data-remaining', 'data-expiry', 'data-deadline', 'data-count',
    ]

    for el in soup.find_all(True):
        classes = ' '.join(el.get('class', [])).lower()
        id_attr = (el.get('id', '') or '').lower()
        el_text = el.get_text(strip=True)[:200]

        class_match = any(kw in classes for kw in timer_classes)
        id_match = any(kw in id_attr for kw in timer_ids)
        text_match = any(kw in el_text.lower() for kw in timer_text_kws)
        data_match = any(el.has_attr(attr) for attr in timer_data_attrs)

        if class_match or id_match or text_match or data_match:
            dom_data['timers'].append({
                'tag': el.name,
                'text': el_text,
                'classes': classes,
                'id': id_attr,
            })


def _extract_prices(soup, dom_data):
    """Extract price elements using class keywords + currency symbol matching."""
    price_class_kws = ['price', 'cost', 'fee', 'charge', 'amount', 'total', 'subtotal', 'tax']

    for el in soup.find_all(True):
        classes = ' '.join(el.get('class', [])).lower()
        id_attr = (el.get('id', '') or '').lower()
        el_text = el.get_text(strip=True)

        class_hit = any(kw in classes or kw in id_attr for kw in price_class_kws)
        has_currency = bool(_CURRENCY_RE.search(el_text))

        if class_hit and has_currency and len(el_text) < 80:
            dom_data['prices'].append({'text': el_text, 'classes': classes})


def _extract_text_elements(soup, dom_data):
    """Extract text-bearing elements for NLP analysis."""
    target_tags = ['p', 'span', 'div', 'label', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'a', 'button']
    for tag in soup.find_all(target_tags):
        text = tag.get_text(strip=True)
        if 5 < len(text) < 500:
            dom_data['text_elements'].append({
                'tag': tag.name,
                'text': text,
                'classes': ' '.join(tag.get('class', [])),
            })
