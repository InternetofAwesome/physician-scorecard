"""RateMDs discovery + profile scraping.

ratemds.com sits behind Cloudflare Turnstile, which a real Playwright
browser passes without solving anything -- but only on the first navigation
of a fresh browser context; a second navigation reusing the same context
shortly after often gets blocked (session/behavioral rate limiting). Always
open a new context per request.

Discovery uses RateMDs' own internal search API (the same one their search
box calls). It does not expose NPI, so matches are name+city confirmed only
-- weaker than the NPI-exact match available on HealthGrades/Vitals. Expect
low hit rates for ordinary primary-care doctors; RateMDs skews toward
specialists and elective/cosmetic care.
"""
import time
import random
import json

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'


def _fetch_html(browser, url, timeout_ms=30000, max_attempts=3):
    for attempt in range(1, max_attempts + 1):
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()
        try:
            resp = page.goto(url, timeout=timeout_ms)
            page.wait_for_timeout(2000)
            html = page.content()
            status = resp.status
        finally:
            context.close()
        if status == 200:
            return html
        time.sleep(random.uniform(8, 15))
    raise RuntimeError('Could not fetch page after {} attempts (status {}): {}'.format(max_attempts, status, url))


def _fetch_json(browser, url, timeout_ms=30000, max_attempts=3):
    for attempt in range(1, max_attempts + 1):
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()
        try:
            resp = page.goto(url, timeout=timeout_ms)
            status = resp.status
            body_text = resp.text() if status == 200 else None
        finally:
            context.close()
        if status == 200:
            return json.loads(body_text)
        time.sleep(random.uniform(8, 15))
    raise RuntimeError('Could not fetch JSON after {} attempts (status {}): {}'.format(max_attempts, status, url))


def _name_matches(query_first_last, candidate_full_name):
    q = set(query_first_last.lower().replace('.', '').split())
    c = set(candidate_full_name.lower().replace('.', '').replace(',', '').split())
    return q.issubset(c)


def extract_physician_ld_json(html):
    import re
    for block in re.findall(r'<script[^>]*>(.*?)</script>', html, re.S):
        if '"@context"' not in block:
            continue
        try:
            data = json.loads(block, strict=False)  # tolerate raw newlines in review text
        except json.JSONDecodeError:
            continue
        if data.get('@type') == 'Physician' and 'aggregateRating' in data:
            return data
    return {}


def get_reviews(browser, profile_url):
    first = _fetch_json(browser, '{}?json=true&page=1'.format(profile_url))
    total_pages = first.get('total_pages', 1)
    results = list(first.get('results', []))
    for pg in range(2, total_pages + 1):
        time.sleep(random.uniform(2, 4))
        data = _fetch_json(browser, '{}?json=true&page={}'.format(profile_url, pg))
        results += data.get('results', [])
    return results


def get_profile(browser, profile_url, with_reviews=True):
    """Scrape a known RateMDs profile URL (must end in `/`)."""
    html = _fetch_html(browser, profile_url)
    ld = extract_physician_ld_json(html)
    agg = ld.get('aggregateRating') or {}
    d = {
        'url': profile_url,
        'name': ld.get('name'),
        'ratingValue': agg.get('ratingValue'),
        'ratingCount': agg.get('reviewCount'),
    }
    if with_reviews and d['ratingCount']:
        d['reviews'] = get_reviews(browser, profile_url)
    else:
        d['reviews'] = []
    return d


def find_profile(browser, first_last_name, city, province='ca', country='us', with_reviews=True):
    """Search RateMDs for `first_last_name` in `city`/`province` and return
    the first name+city match, or None. Not NPI-confirmed -- treat matches
    as a weaker signal than HealthGrades/Vitals.
    """
    url = 'https://www.ratemds.com/api/doctor_search/?country={}&province={}&text={}'.format(
        country, province, first_last_name.replace(' ', '%20'))
    data = _fetch_json(browser, url)

    city_norm = city.lower()
    matches = [
        r for r in data.get('results', [])
        if _name_matches(first_last_name, r.get('full_name', ''))
        and (r.get('location') or {}).get('name', '').lower() == city_norm
    ]
    if not matches:
        return None

    slug = matches[0]['slug']
    profile_url = 'https://www.ratemds.com/doctor-ratings/{}'.format(slug)
    if not profile_url.endswith('/'):
        profile_url += '/'
    return get_profile(browser, profile_url, with_reviews=with_reviews)
