# Physician Scorecard

Aggregates multiple public data sources on a list of doctors (by NPI) into
one weighted, ranked scorecard — built for picking a primary care physician,
but the approach generalizes to any "compare several professionals against
criteria I care about" problem.

## Why this exists

Any single review site has selection bias — angry or thrilled patients post,
typical ones don't, and coverage is wildly uneven (most ordinary doctors have
zero or near-zero reviews on any given platform). Combining several
independent sources, plus a couple of objective non-review signals
(regulatory record, industry payments, publication record), gives a less
noisy picture than trusting one star rating.

This is a personal-decision tool, not a population-scale research scraper —
if you want that, look elsewhere. It assumes you already have a short list of
named candidates (tens, not millions) and want to compare them.

## Disclaimers — read before trusting the output

- **This was built and validated for exactly one search** (primary care
  doctors near one zip code, for one person's stated priorities). It works
  mechanically — the scrapers run, the lookups return real data — but it
  has not been run by anyone else, on any other specialty, or in any other
  city. Treat it as a starting point to adapt, not a finished tool.
- **Whether the final ranking actually identifies a "better" doctor is
  unverified.** This aggregates the signals that are easy to get
  *programmatically* (review counts, regulatory flags, publication counts)
  weighted by self-reported priorities — it is not a clinical-quality
  measure, and nobody has gone back and checked outcomes against the
  ranking. A high score means "scores well on the things you told it to
  weight," not "is a good doctor." Use it to narrow a list, not to skip
  doing your own homework on whoever comes out on top.
- **The scrapers are inherently fragile.** Every site here has changed its
  markup, search mechanism, or anti-bot posture at least once in this
  project's short life so far, and will again. If a module stops returning
  data, that's the most likely explanation — check the live page structure
  before assuming your input data is wrong.
- **Match confidence varies by source** (see table below) — RateMDs and
  PubMed results can be wrong-person matches or noise from common names.
  Don't treat every number in the output CSV as equally trustworthy; the
  table and the collision-risk flag exist specifically so you can tell
  which numbers to lean on.
- **This is an AI-generated repo** — written by an LLM coding agent in a
  single session, working from one person's real search, with that
  person reviewing direction and decisions but not auditing every line.
  It hasn't had the scrutiny a hand-built or team-reviewed tool would.
  Read the code before you trust it with a decision that matters. YMMV.

## Data sources

| Source | What it gives you | Match confidence |
|---|---|---|
| Your own primary source (e.g. a hospital system's provider directory) | Ratings, review recency, scheduling, location — whatever you already have | n/a, you supply it |
| HealthGrades | Rating, review count, board certification, **board-action/malpractice flag** | NPI-exact (scraped page exposes NPI) |
| RateMDs | Rating, full review history (no cap, unlike most sites) | Name + city only — no NPI on this site, weaker match |
| CMS Open Payments | Industry ($) payments, split into routine (meals/travel) vs. concerning (consulting/honoraria/ownership) | NPI-exact, official federal data |
| PubMed | Publication count, with a **collision-risk flag** for common names | Name-only; the flag tells you when *not* to trust the count |

Sites not included: Yelp and ZocDoc are both behind DataDome, which
resisted everything tried (headless Chromium, headed Chromium with a real
GPU via WSLg, a real Chrome profile over CDP). Vitals' own search has no
clean discovery path without risking false-positive name collisions, and
ROI didn't justify chasing it further once RateMDs returned no coverage at
all for an early test population. Google-result scraping for *discovering*
profile URLs is blocked at the IP-reputation level — each site's own
internal search API is used instead (no AI/LLM in the discovery loop at
all, by design).

## Methodology

1. **Disqualify**, don't score, hard requirements (e.g. "doesn't support
   online scheduling," "specialty doesn't fit," "has a formal board
   disciplinary action"). These are binary gates, not inputs to weighting —
   no other strength should be able to outweigh a real disqualifier. Decide
   what your disqualifiers are before you start weighting metrics; it
   keeps the two concerns from getting tangled.
2. **Weight what's left** (0-100 per metric) by how much you actually care,
   not by what's easiest to measure.
3. **Missing data is penalized**, not excluded from the average. A
   candidate with no reviews anywhere scores 0 on review metrics rather
   than having those metrics dropped from their average — deliberate, but
   flip `score.py`'s behavior if you want leniency for thin data instead.
4. **A metric with zero variance across your whole pool doesn't change
   anyone's rank** — if nobody in your list has a Vitals profile, including
   that metric just subtracts a constant from every score. Worth dropping
   it from `weights.json` so the report doesn't imply it's discriminating
   when it isn't.
5. **Watch for magnitude-blindness in ratio-based metrics.** The Open
   Payments score is dollar-magnitude-based specifically because an earlier
   ratio-based version scored a $130 payment identically to a $130,000 one
   (both "100% concerning" with no benign amount to dilute it).

## Usage

```bash
pip install -r requirements.txt
python -m playwright install chromium   # only needed for RateMDs

cp weights.example.json weights.json        # edit weights + years-in-practice buckets to taste
cp candidates.example.csv candidates.csv    # fill in your actual candidate list

python run.py --candidates candidates.csv --weights weights.json --out scorecard.csv
```

### Input data: `candidates.csv`

Required columns: `name, first_name, last_name, npi, city, state`.
Optional columns (include whichever you have): `primary_rating,
primary_review_count, primary_most_recent_review, years_in_practice,
online_scheduling, num_locations`.

**What NPI is and why it matters here:** the National Provider Identifier is
a unique 10-digit number the U.S. government assigns to every licensed
healthcare provider — one person, one number, for life, regardless of how
many practices or specialties they have. It's the join key this whole
pipeline relies on to avoid the central problem of doing this by name alone:
two providers can share a name (or one provider's name can vary across
sites — middle names, suffixes, maiden names), but they can never share an
NPI. HealthGrades and CMS Open Payments both expose NPI directly, which is
what makes those two matches reliable; RateMDs and PubMed don't, which is
exactly why those two carry weaker match confidence in the table above.

Where to get it for your candidates:
- **You probably already have it** if you pulled your candidate list from a
  hospital system's own "find a doctor" page or your insurer's provider
  directory — NPI is commonly displayed or embedded in the page data even
  when not shown in the UI.
- **Free public lookup**: the [NPPES NPI Registry](https://npiregistry.cms.hhs.gov/search)
  is the government's own searchable database of every NPI on record —
  search by name + state to find anyone's.
- A doctor only has one NPI even if they have multiple practice locations
  or specialties, so don't expect a 1:1 mapping between NPI and "office
  location" the way you might with, say, a practice's phone number.

Disqualification (specialty fit, board actions, missing data you've decided
is a deal-breaker) isn't automated in `run.py` — filter `candidates.csv`
yourself before running, since what counts as disqualifying is inherently a
personal call (see Methodology #1).

### Data dictionary: `weights.json`

Every key is a 0-100 weight (how much that metric counts toward the final
`net_score`) except `_years_buckets`, which is configuration, not a weight —
see below. Set a key to `0` (or delete it) to drop that metric from scoring
entirely; per Methodology #4, do this for any source where none of your
candidates have data, so the report doesn't imply it's discriminating when
it isn't.

| Key | What it scores | Fed by | Notes |
|---|---|---|---|
| `primary_rating` | Star rating from your own primary source | `primary_rating` column | 0 if no reviews (`primary_review_count` is 0/blank) |
| `primary_review_count` | Sample size behind that rating | `primary_review_count` column | Capped at 50 reviews = full score; more doesn't add further credit |
| `primary_recency` | How fresh the most recent review is | `primary_most_recent_review` column | Decays to 0 over ~2 years; 0 if no review date at all |
| `years_in_practice` | Experience level | `years_in_practice` column | Direction/shape is entirely yours — see `_years_buckets` below |
| `online_scheduling` | Can patients book online | `online_scheduling` column | Binary: 100 or 0. No in-between |
| `num_locations` | How spread across offices the doctor is | `num_locations` column | 1 location = 100, each additional location -30, floored at 0 |
| `healthgrades` | HealthGrades rating + review count | live lookup (NPI-confirmed) | 0 if no profile found or no reviews on it |
| `healthgrades_board_cert` | Has at least one listed board certification | live lookup | Binary: 100 or 0 |
| `ratemds` | RateMDs rating + review count | live lookup (name+city matched, **not** NPI-confirmed) | 0 if no match found — also the expected case for most ordinary PCPs, see Data Sources table |
| `open_payments` | How clean the CMS Open Payments record is | live lookup (NPI-exact) | 100 = no concerning-category $ at all; decays by *absolute dollar amount* of consulting/honoraria/ownership-type payments, not by ratio (see Methodology #5) |
| `pubmed` | Publication count | live lookup (name-matched) | 0 if `collision_risk` came back `"high"` — an untrustworthy number is treated the same as no data, not rewarded at face value |

`_years_buckets`: not a weight — it's the actual scoring curve for
`years_in_practice`, as a list of `[min_inclusive, max_exclusive, score]`
triples. The example ships with a "rising then falling" curve (peaks at
5-10 years, penalizes both very new and very tenured doctors), because
that's what one person wanted; there's no objectively correct shape here.
Want simple "more experience is always better"? Use a single increasing
ramp instead, e.g. `[[0,40,score-per-year-via-more-buckets]]`, or rewrite
`years_in_practice_score()` in `scorecard/score.py` directly if buckets
don't fit what you want.
