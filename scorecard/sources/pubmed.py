"""PubMed publication count, by name, with a name-collision-risk flag.

PubMed has no NPI field, so author search is name-only (optionally narrowed
by an affiliation term). Common names produce heavily collided counts that
don't mean anything about the specific person you're looking for -- e.g.
"Wang C[author]" matches every C. Wang who has ever published, anywhere.

Rather than pull external surname-frequency tables, this uses a more
directly relevant proxy: the *unfiltered* author-search hit count for
"Lastname Initial[author]" IS the collision risk for that exact query, in
the exact dataset being searched. High unfiltered count -> the affiliation-
filtered count should not be trusted at face value.
"""
import time
import requests

ESEARCH = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi'


def _search(term):
    params = {'db': 'pubmed', 'term': term, 'retmode': 'json', 'retmax': '0'}
    r = requests.get(ESEARCH, params=params, timeout=20)
    r.raise_for_status()
    return int(r.json()['esearchresult']['count'])


def collision_risk(unfiltered_count):
    if unfiltered_count <= 3:
        return 'low'
    elif unfiltered_count <= 15:
        return 'medium'
    return 'high'


def lookup(first_name, last_name, affiliation_terms=('UCSF', 'University of California, San Francisco')):
    """affiliation_terms: OR'd PubMed [affiliation] terms to narrow the
    search to the institution(s) the person is actually associated with.
    Pass an empty tuple to skip affiliation filtering entirely (not
    recommended -- collision risk goes up sharply)."""
    initial = first_name[0]
    author_term = '{} {}[author]'.format(last_name, initial)

    unfiltered_count = _search(author_term)
    time.sleep(0.4)

    if affiliation_terms:
        affil_clause = ' OR '.join('"{}"[affiliation]'.format(t) for t in affiliation_terms)
        affil_term = '({}) AND ({})'.format(author_term, affil_clause)
        filtered_count = _search(affil_term)
        time.sleep(0.4)
    else:
        filtered_count = unfiltered_count

    return {
        'pub_count': filtered_count,
        'unfiltered_count': unfiltered_count,
        'collision_risk': collision_risk(unfiltered_count),
    }


def score(result, cap=5):
    """0-100. Untrusted (high collision risk) results score 0 -- not
    because the person has no publications, but because the number isn't
    reliable enough to reward."""
    if result is None or result['collision_risk'] == 'high':
        return 0.0
    return min(result['pub_count'], cap) / cap * 100
