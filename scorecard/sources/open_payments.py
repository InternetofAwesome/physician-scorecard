"""CMS Open Payments (Sunshine Act) lookup, by NPI.

Queries the raw per-year "General Payment Data" datasets (2018-2024) on
openpaymentsdata.cms.gov's public DKAN API and buckets results into:

  - benign:     Food and Beverage, Travel and Lodging, Education, Gift,
                Charitable Contribution, Space rental -- routine, required
                to be logged by law even for a single sponsored lunch, not
                meaningful conflict-of-interest signal on their own.
  - concerning: Consulting Fee, Honoraria, compensation for speaking,
                Royalty/License, Ownership/Investment interest, etc. --
                the categories actual conflict-of-interest scrutiny focuses
                on.

Score by the absolute dollar amount of *concerning* payments, not a ratio of
benign-to-concerning -- a ratio is blind to magnitude (a $130 consulting fee
and a $130,000 one both read as "100% concerning" if there's no benign
amount to dilute it).
"""
import requests

YEAR_DATASETS = {
    2018: 'f003634c-c103-568f-876c-73017fa83be0',
    2019: '4e54dd6c-30f8-4f86-86a7-3c109a89528e',
    2020: 'a08c4b30-5cf3-4948-ad40-36f404619019',
    2021: '0380bbeb-aea1-58b6-b708-829f92a48202',
    2022: 'df01c2f8-dc1f-4e79-96cb-8208beaf143c',
    2023: 'fb3a65aa-c901-4a38-a813-b04b00dfa2a9',
    2024: 'e6b17c6a-2534-4207-a4a1-6746a14911ff',
}

BENIGN_CATEGORIES = {
    'Food and Beverage',
    'Travel and Lodging',
    'Education',
    'Gift',
    'Charitable Contribution',
    'Space rental or facility fees',
}
CONCERNING_CATEGORIES = {
    'Consulting Fee',
    'Compensation for services other than consulting, including serving as faculty or as a speaker at a venue other than a continuing education program',
    'Compensation for serving as faculty or as a speaker for a non-accredited and noncertified continuing education program',
    'Compensation for serving as faculty or as a speaker for an accredited or certified continuing education program',
    'Honoraria',
    'Entertainment',
    'Royalty or License',
    'Current or prior ownership or investment interest',
    'Acquisitions',
    'Debt forgiveness',
    'Long term medical supply or device loan',
}


def lookup(npi):
    """Return raw payment rows (year, category, amount) for an NPI across
    all available years. Research payments are intentionally excluded --
    they fund trial infrastructure, routed through the institution, not
    personal income, and including them would muddy the signal."""
    rows = []
    for year, dataset in YEAR_DATASETS.items():
        url = 'https://openpaymentsdata.cms.gov/api/1/datastore/query/{}/0'.format(dataset)
        params = {
            'conditions[0][property]': 'covered_recipient_npi',
            'conditions[0][value]': npi,
            'conditions[0][operator]': '=',
            'results': 'true',
            'properties[0]': 'nature_of_payment_or_transfer_of_value',
            'properties[1]': 'total_amount_of_payment_usdollars',
        }
        r = requests.get(url, params=params, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
        r.raise_for_status()
        for row in r.json().get('results', []):
            rows.append({'year': year, **row})
    return rows


def summarize(rows):
    benign = concerning = other = 0.0
    by_category = {}
    for row in rows:
        cat = row['nature_of_payment_or_transfer_of_value']
        amt = float(row['total_amount_of_payment_usdollars'])
        by_category[cat] = by_category.get(cat, 0) + amt
        if cat in BENIGN_CATEGORIES:
            benign += amt
        elif cat in CONCERNING_CATEGORIES:
            concerning += amt
        else:
            other += amt
    return {
        'total_benign': round(benign, 2),
        'total_concerning': round(concerning, 2),
        'total_other_uncategorized': round(other, 2),
        'categories': by_category,
    }


def score(summary, dollars_per_point=50):
    """0-100, no-record = 100 (clean by definition). Decays by absolute
    concerning-$ magnitude, not by ratio."""
    if summary is None:
        return 100.0
    return max(0.0, 100.0 - summary['total_concerning'] / dollars_per_point)
