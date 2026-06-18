#!/usr/bin/env python3
"""Build a multi-source physician scorecard.

Usage:
    python run.py --candidates candidates.csv --weights weights.json --out scorecard.csv
    python run.py --candidates candidates.csv --weights weights.json --out scorecard.csv \\
        --skip-ratemds --skip-pubmed

See README.md for the candidates.csv / weights.json schema and the
methodology behind each metric.
"""
import argparse
import csv
import json
from datetime import date

from scorecard.sources import healthgrades, open_payments, pubmed
from scorecard import score as scoring


def load_candidates(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def run(candidates, weights, today, use_healthgrades, use_ratemds, use_open_payments, use_pubmed, ratemds_browser=None):
    rows_out = []

    for c in candidates:
        name = c['name']
        npi = c['npi']
        first_last = '{} {}'.format(c['first_name'], c['last_name'])
        city = c.get('city', '')
        state = c.get('state', '')
        print('Processing {} (NPI {})...'.format(name, npi))

        component_scores = {}
        raw = {'name': name, 'npi': npi}

        # --- primary source you already have in hand (optional columns) ---
        primary_rating = float(c['primary_rating']) if c.get('primary_rating') else None
        primary_count = int(c['primary_review_count']) if c.get('primary_review_count') else None
        if primary_rating is not None:
            component_scores['primary_rating'] = (primary_rating / 5) * 100 if primary_count else 0
            component_scores['primary_review_count'] = scoring.capped_linear(primary_count, 50)
            component_scores['primary_recency'] = scoring.recency_score(c.get('primary_most_recent_review'), today)
            raw['primary_rating'] = primary_rating
            raw['primary_review_count'] = primary_count

        if c.get('years_in_practice'):
            years = int(c['years_in_practice'])
            component_scores['years_in_practice'] = scoring.years_in_practice_score(years, weights.get('_years_buckets', []))
            raw['years_in_practice'] = years

        if c.get('online_scheduling'):
            scheduling = c['online_scheduling'].lower() == 'true'
            component_scores['online_scheduling'] = 100 if scheduling else 0
            raw['online_scheduling'] = scheduling

        if c.get('num_locations'):
            n_loc = int(c['num_locations'])
            component_scores['num_locations'] = scoring.num_locations_score(n_loc)
            raw['num_locations'] = n_loc

        # --- HealthGrades ---
        if use_healthgrades:
            try:
                hg = healthgrades.find_profile(first_last, '{}, {}'.format(city, state), npi)
            except Exception as e:
                print('   HealthGrades ERROR:', e)
                hg = None
            if hg:
                component_scores['healthgrades'] = scoring.rating_and_count_score(hg.get('ratingValue'), hg.get('reviewCount'))
                component_scores['healthgrades_board_cert'] = 100 if hg.get('boardCertifications') else 0
                raw['hg_rating'] = hg.get('ratingValue')
                raw['hg_review_count'] = hg.get('reviewCount')
                raw['hg_board_certifications'] = '; '.join(hg.get('boardCertifications') or [])
                raw['hg_has_board_action'] = hg.get('hasBoardAction')
            else:
                component_scores['healthgrades'] = 0
                component_scores['healthgrades_board_cert'] = 0
                raw['hg_has_board_action'] = None

        # --- RateMDs ---
        if use_ratemds:
            try:
                rm = ratemds.find_profile(ratemds_browser, first_last, city)
            except Exception as e:
                print('   RateMDs ERROR:', e)
                rm = None
            if rm:
                component_scores['ratemds'] = scoring.rating_and_count_score(rm.get('ratingValue'), rm.get('ratingCount'))
                raw['ratemds_rating'] = rm.get('ratingValue')
                raw['ratemds_review_count'] = rm.get('ratingCount')
            else:
                component_scores['ratemds'] = 0

        # --- CMS Open Payments ---
        if use_open_payments:
            try:
                op_rows = open_payments.lookup(npi)
                op_summary = open_payments.summarize(op_rows) if op_rows else None
            except Exception as e:
                print('   Open Payments ERROR:', e)
                op_summary = None
            component_scores['open_payments'] = open_payments.score(op_summary)
            raw['op_concerning_dollars'] = op_summary['total_concerning'] if op_summary else 0.0

        # --- PubMed ---
        if use_pubmed:
            try:
                pm = pubmed.lookup(c['first_name'], c['last_name'])
            except Exception as e:
                print('   PubMed ERROR:', e)
                pm = None
            component_scores['pubmed'] = pubmed.score(pm)
            raw['pubmed_count'] = pm['pub_count'] if pm else None
            raw['pubmed_collision_risk'] = pm['collision_risk'] if pm else None

        net_weights = {k: v for k, v in weights.items() if not k.startswith('_')}
        raw['net_score'] = scoring.compute_net_score(component_scores, net_weights)
        rows_out.append(raw)

    rows_out.sort(key=lambda r: -r['net_score'])
    return rows_out


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidates', required=True)
    parser.add_argument('--weights', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--skip-healthgrades', action='store_true')
    parser.add_argument('--skip-ratemds', action='store_true')
    parser.add_argument('--skip-open-payments', action='store_true')
    parser.add_argument('--skip-pubmed', action='store_true')
    args = parser.parse_args()

    candidates = load_candidates(args.candidates)
    weights = json.load(open(args.weights))

    ratemds_browser = None
    if not args.skip_ratemds:
        from playwright.sync_api import sync_playwright
        from scorecard.sources import ratemds
        pw = sync_playwright().start()
        ratemds_browser = pw.chromium.launch(headless=True)

    rows = run(
        candidates, weights, date.today(),
        use_healthgrades=not args.skip_healthgrades,
        use_ratemds=not args.skip_ratemds,
        use_open_payments=not args.skip_open_payments,
        use_pubmed=not args.skip_pubmed,
        ratemds_browser=ratemds_browser,
    )

    if ratemds_browser:
        ratemds_browser.close()
        pw.stop()

    with open(args.out, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print('\nWrote {} ranked candidates to {}'.format(len(rows), args.out))
