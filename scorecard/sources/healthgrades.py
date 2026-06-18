"""HealthGrades discovery + profile scraping.

As of 2026, healthgrades.com is a server-rendered Next.js app. Profile data
lives in <script data-qa-target="markup-*" type="application/ld+json"> blocks
(schema.org structured data) plus plain HTML elements tagged with
data-qa-target=.... It is not behind Cloudflare/DataDome, so plain `requests`
works fine -- no browser automation needed for this site.

Discovery uses HealthGrades' own search page (`usearch`), then confirms the
right result by matching NPI on the candidate's profile page -- this avoids
any name-collision risk since NPI is unique per provider.
"""
import re
import json
import requests
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Encoding': 'gzip,deflate',
}

NO_BOARD_ACTION_TEXT = 'has not received any data indicating a board action exists'


def extract_ld_json_blocks(html):
    blocks = re.findall(
        r'<script data-qa-target="([^"]+)" type="application/ld\+json">(.*?)</script>',
        html, re.S,
    )
    out = {}
    for qa, content in blocks:
        try:
            d = json.loads(content)
        except json.JSONDecodeError:
            continue
        out.setdefault(qa, []).append(d)
    return out


def extract_rsc_scalar(html, field, pattern=r'\\?"{field}\\?":\\?"([^"\\]*)\\?"'):
    # Some scalar fields (npi, age, acceptsNewPatients...) live inside the
    # React Server Components stream, double-escaped (the chunk is a JSON
    # string whose *content* is itself JSON). A direct regex tolerant of
    # that escaping is more robust than reassembling the RSC chunk graph.
    m = re.search(pattern.format(field=re.escape(field)), html)
    return m.group(1) if m else None


def _process_summary(ld_blocks):
    d = {}
    summary = (ld_blocks.get('markup-summary') or [{}])[0]
    d['name'] = summary.get('name')
    d['description'] = summary.get('description')
    d['awards'] = summary.get('award', [])

    agg = summary.get('aggregateRating', {}) or {}
    d['ratingValue'] = agg.get('ratingValue')
    d['reviewCount'] = agg.get('reviewCount')

    reviews = []
    for r in summary.get('review', []) or []:
        reviews.append({
            'body': r.get('reviewBody'),
            'author': (r.get('author') or {}).get('name'),
            'rating': (r.get('reviewRating') or {}).get('ratingValue'),
            'date': r.get('datePublished'),
        })
    d['reviews'] = reviews
    return d


def _process_breadcrumbs(ld_blocks):
    items = []
    for b in ld_blocks.get('markup-breadcrumb') or []:
        item = b.get('itemListElement') or {}
        if item.get('name') is not None:
            items.append((item.get('position', 0), item['name']))
    names = [name for _, name in sorted(items, key=lambda x: x[0])]
    d = {'specialty': None, 'state': None, 'city': None}
    if len(names) >= 1:
        d['specialty'] = names[0]
    if len(names) >= 2:
        d['state'] = names[1]
    if len(names) >= 3:
        d['city'] = names[2]
    return d


def _process_education(ld_blocks):
    return [
        ((b.get('alumni') or {}).get('alumniOf') or {}).get('name')
        for b in ld_blocks.get('markup-alumni-of') or []
        if ((b.get('alumni') or {}).get('alumniOf') or {}).get('name')
    ]


def _process_about_me(soup):
    def grab(qa):
        return [e.get_text(strip=True) for e in soup.find_all(attrs={'data-qa-target': qa})]

    d = {
        'boardCertifications': grab('about-me-cert-name'),
        'boardName': grab('about-me-board-name'),
        'languages': grab('about-me-languages-listitem-text'),
    }
    board_actions_text = grab('board-actions')
    if board_actions_text:
        d['hasBoardAction'] = NO_BOARD_ACTION_TEXT not in board_actions_text[0]
        d['boardActionsText'] = board_actions_text[0]
    else:
        d['hasBoardAction'] = None
        d['boardActionsText'] = None
    return d


def get_profile(url):
    """Scrape a known HealthGrades physician profile URL."""
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    html = r.text

    ld_blocks = extract_ld_json_blocks(html)
    soup = BeautifulSoup(html, 'lxml')

    d = {'url': url}
    d['npi'] = extract_rsc_scalar(html, 'npi')
    accepts = extract_rsc_scalar(html, 'acceptsNewPatients', pattern=r'\\?"{field}\\?":(true|false)')
    d['acceptsNewPatients'] = {'true': True, 'false': False}.get(accepts)
    d.update(_process_summary(ld_blocks))
    d.update(_process_breadcrumbs(ld_blocks))
    d['education'] = _process_education(ld_blocks)
    d.update(_process_about_me(soup))
    return d


def find_profile(first_last_name, city_state, npi):
    """Search HealthGrades for `first_last_name` near `city_state` and return
    the profile dict whose page NPI matches `npi` exactly, or None.

    Use the bare "First Last" name (no middle name) -- HealthGrades' search
    matches poorly against three-token names.
    """
    r = requests.get(
        'https://www.healthgrades.com/usearch',
        headers=HEADERS,
        params={'what': first_last_name, 'where': city_state},
        timeout=20,
    )
    soup = BeautifulSoup(r.text, 'lxml')
    hrefs = list(dict.fromkeys(
        a['href'] for a in soup.find_all('a', href=True) if '/physician/dr-' in a['href']
    ))

    for href in hrefs:
        url = 'https://www.healthgrades.com' + href if href.startswith('/') else href
        try:
            profile = get_profile(url)
        except requests.RequestException:
            continue
        if profile.get('npi') == npi:
            return profile
    return None
