"""Match the Beervana beer list against Untappd, and score each beer for Mark.

Reads:  beervana-2026-beer-list.csv, untappd-history.json
Writes: data.json (for the app), plus a coverage report on stdout.

Untappd's site search is backed by Algolia with a public, search-only key that
the site itself ships to browsers. We query that directly: no login, no cookies,
no scraping of Untappd's own servers.
"""
import csv, json, re, subprocess, urllib.parse, difflib, os, time, collections

APP = "9WBO4RQ3HO"
KEY = "1d347324d67ec472bb7132c66aead485"
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".algolia-cache.json")

# --------------------------------------------------------------------------
# Algolia access, with an on-disk cache so re-runs cost nothing
# --------------------------------------------------------------------------
cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}


def algolia(reqs):
    """Run Algolia multi-queries. reqs is a list of (cache_key, index, params)."""
    todo = [r for r in reqs if r[0] not in cache]
    for i in range(0, len(todo), 10):
        chunk = todo[i:i + 10]
        payload = {'requests': [{'indexName': ix, 'params': urllib.parse.urlencode(p)}
                                for _, ix, p in chunk]}
        tmp = os.path.join(HERE, '.req.json')
        with open(tmp, 'w') as f:
            json.dump(payload, f)
        out = subprocess.run([
            'curl', '-s', '-X', 'POST',
            '-H', f'X-Algolia-API-Key: {KEY}',
            '-H', f'X-Algolia-Application-Id: {APP}',
            '-H', 'Content-Type: application/json',
            '--data', f'@{tmp}',
            f'https://{APP}-dsn.algolia.net/1/indexes/*/queries'],
            capture_output=True, text=True, check=True)
        d = json.loads(out.stdout)
        if 'results' not in d:
            raise SystemExit(f"Algolia error: {d}")
        for (k, _, _), res in zip(chunk, d['results']):
            cache[k] = res.get('hits', [])
        time.sleep(0.15)          # be polite
    if todo:
        with open(CACHE, 'w') as f:
            json.dump(cache, f)
        os.path.exists(os.path.join(HERE, '.req.json')) and os.remove(os.path.join(HERE, '.req.json'))
    return [cache.get(r[0], []) for r in reqs]


# --------------------------------------------------------------------------
# Name normalisation
# --------------------------------------------------------------------------
STYLE_TAIL = (r'hazy ipa|west coast ipa|nz ipa|new england ipa|double ipa|'
              r'sour ale|pale ale|india pale ale|ipa|apa|xpa|stout|porter|'
              r'lager|pilsner|saison|gose|cider|mead')


def clean_beer(s):
    s = re.sub(r'\([^)]*\)', ' ', s)                       # (Nitro), (X Collab)
    s = re.sub(r'\s+-\s+.*$', ' ', s)                      # " - Oak Barrel Aged"
    s = re.sub(r'\b(vol\.?\s*\d+|nitro|collab(oration)?)\b', ' ', s, flags=re.I)
    s = re.sub(r'[^\w\s&]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def strip_style_tail(s):
    """Drop a trailing style descriptor: 'Sea Fog Hazy IPA' -> 'Sea Fog'."""
    out = re.sub(rf'\s+({STYLE_TAIL})\s*$', '', s, flags=re.I).strip()
    return out if len(out) >= 3 else s


def clean_brewery(s):
    s = re.sub(r'\b(brewing|brewery|breweries|brewers|beer|beers|co|company|'
               r'ltd|limited|nz|by|the)\b', ' ', s, flags=re.I)
    s = re.sub(r'\d+$', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def norm(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def sim(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 0.92
    return difflib.SequenceMatcher(None, a, b).ratio()


# --------------------------------------------------------------------------
# Load inputs
# --------------------------------------------------------------------------
rows = []
with open(os.path.join(HERE, 'beervana-2026-beer-list.csv'), encoding='utf-8-sig') as f:
    for r in csv.DictReader(f):
        r = {k: (v or '').strip() for k, v in r.items() if k}
        if r.get('BEER NAME'):
            rows.append(r)

history = json.load(open(os.path.join(HERE, 'untappd-history.json')))
drunk_bids = {c['bid'] for c in history if c.get('bid')}
drunk_names = {(norm(c['brewery_name']), norm(c['beer_name'])) for c in history}

# --------------------------------------------------------------------------
# Taste profile, derived from the history
# --------------------------------------------------------------------------
def family(type_name):
    return (type_name or '').split(' - ')[0].strip()


fam_count = collections.Counter()
fam_ratings = collections.defaultdict(list)
for c in history:
    f = family(c.get('beer_type'))
    fam_count[f] += 1
    if c.get('rating_score'):
        fam_ratings[f].append(c['rating_score'])

total_checkins = len(history)
overall_avg = sum(c['rating_score'] for c in history if c.get('rating_score')) / \
    sum(1 for c in history if c.get('rating_score'))

# How you rate each brewery you've drunk. This is what separates the unrated
# beers from each other: a new release from a brewery you consistently love is
# a better bet than a new release from one you don't.
brewery_ratings = collections.defaultdict(list)
for c in history:
    if c.get('rating_score'):
        brewery_ratings[norm(c['brewery_name'])].append(c['rating_score'])

profile = {}
for f, n in fam_count.items():
    rs = fam_ratings[f]
    avg = sum(rs) / len(rs) if rs else overall_avg
    share = n / total_checkins
    # Affinity blends "how much you drink it" with "how well you rate it".
    # The rating term is what lets a rare-but-loved family (Barleywine) rank.
    volume = min(share / 0.10, 1.0)                     # 10% share saturates
    quality = max(0.0, min((avg - 3.0) / 1.3, 1.0))     # 3.0 floor, 4.3 ceiling
    confidence = min(n / 40, 1.0)                       # ignore tiny samples
    profile[f] = {
        'checkins': n,
        'avg_rating': round(avg, 2),
        'share': round(share, 4),
        'affinity': round((0.45 * volume + 0.55 * quality) * confidence, 4),
    }

# --------------------------------------------------------------------------
# Pass 1: resolve breweries (try the BREWERY column, then EXHIBITOR)
# --------------------------------------------------------------------------
brewery_names = sorted({r['BREWERY'] for r in rows if r.get('BREWERY')} |
                       {r['EXHIBITOR'] for r in rows if r.get('EXHIBITOR')})
reqs = [(f'brewery::{b}', 'brewery',
         {'query': clean_brewery(b) or b, 'hitsPerPage': 3}) for b in brewery_names]
res = algolia(reqs)

brewery_map = {}
for name, hits in zip(brewery_names, res):
    best, score = None, 0.0
    for h in hits:
        s = sim(clean_brewery(name), clean_brewery(h.get('brewery_name', '')))
        if s > score:
            best, score = h, s
    if best and score >= 0.75:
        brewery_map[name] = {'id': best['brewery_id'], 'name': best['brewery_name']}

# --------------------------------------------------------------------------
# Pass 2: tiered beer lookup
# --------------------------------------------------------------------------
def brewery_for(r):
    return brewery_map.get(r['BREWERY']) or brewery_map.get(r['EXHIBITOR'])


def build_tier(r, tier):
    """Return (cache_key, index, params) or None."""
    bw = brewery_for(r)
    name = clean_beer(r['BEER NAME'])
    if tier == 0 and bw:                       # filtered to the brewery
        return (f"t0::{bw['id']}::{name}", 'beer',
                {'query': name, 'hitsPerPage': 5, 'filters': f"brewery_id={bw['id']}",
                 'removeWordsIfNoResults': 'allOptional'})
    if tier == 1 and bw:                       # same, style suffix stripped
        short = strip_style_tail(name)
        if short == name:
            return None
        return (f"t1::{bw['id']}::{short}", 'beer',
                {'query': short, 'hitsPerPage': 5, 'filters': f"brewery_id={bw['id']}",
                 'removeWordsIfNoResults': 'allOptional'})
    if tier == 2:                              # unfiltered, verify brewery after
        q = f"{r['BREWERY']} {name}"
        return (f"t2::{q}", 'beer',
                {'query': clean_beer(q), 'hitsPerPage': 5,
                 'removeWordsIfNoResults': 'allOptional'})
    return None


def pick(r, hits, require_brewery):
    bw = brewery_for(r)
    tgt = clean_beer(r['BEER NAME'])
    best, score = None, 0.0
    for h in hits:
        if require_brewery:
            ok = sim(r['BREWERY'], h.get('brewery_name', '')) >= 0.7 or \
                 sim(r['EXHIBITOR'], h.get('brewery_name', '')) >= 0.7
            if not ok:
                continue
        elif bw and h.get('brewery_id') != bw['id']:
            continue
        s = max(sim(tgt, h['beer_name']), sim(strip_style_tail(tgt), h['beer_name']))
        if s > score:
            best, score = h, s
    return (best, score) if best and score >= 0.62 else (None, score)


matches = {}
for tier in (0, 1, 2):
    pending = [r for r in rows if id(r) not in matches]
    specs = [(r, build_tier(r, tier)) for r in pending]
    specs = [(r, s) for r, s in specs if s]
    if not specs:
        continue
    hits_list = algolia([s for _, s in specs])
    for (r, _), hits in zip(specs, hits_list):
        best, score = pick(r, hits, require_brewery=(tier == 2))
        if best:
            matches[id(r)] = (best, score, tier)

# --------------------------------------------------------------------------
# Assemble, score, and report
# --------------------------------------------------------------------------
NOT_BEER = re.compile(r'cocktail|gin\b|vodka|rum\b|whisk|tonic|mead|cider|'
                      r'kombucha|seltzer|soda|ginger beer|wine|margarita|'
                      r'lemonade|sangria|slushie|soft serve|mocktail', re.I)

beers = []
for r in rows:
    m = matches.get(id(r))
    hit, score, tier = m if m else (None, 0.0, None)
    sheet_style = r.get('STYLE', '')
    is_beer = not NOT_BEER.search(sheet_style) and \
        (hit.get('parent_style_is_beer', 1) if hit else True)

    b = {
        'exhibitor': r['EXHIBITOR'],
        'brewery': r['BREWERY'],
        'name': r['BEER NAME'],
        'sheet_style': sheet_style,
        'abv': r.get('ABV', ''),
        'notes': r.get('Tasting Notes', ''),
        'is_beer': bool(is_beer),
    }
    if hit:
        b.update({
            'bid': hit['bid'],
            'url': (f"https://untappd.com/b/{hit['beer_slug']}/{hit['bid']}"
                    if hit.get('beer_slug')
                    else f"https://untappd.com/beer/{hit['bid']}"),
            'style': hit.get('type_name', ''),
            'family': family(hit.get('type_name')),
            'rating': hit.get('rating_score') or 0,
            'rating_count': hit.get('rating_count') or 0,
            'label': hit.get('beer_label_hd') or hit.get('beer_label') or '',
            'awards': hit.get('community_awards') or [],
            'match_score': round(score, 2),
            'match_tier': tier,
            'drunk': hit['bid'] in drunk_bids or
                     (norm(hit['brewery_name']), norm(hit['beer_name'])) in drunk_names,
        })
    else:
        b.update({'bid': None, 'url': None, 'style': '', 'family': '',
                  'rating': 0, 'rating_count': 0, 'label': '', 'awards': [],
                  'match_score': 0, 'match_tier': None, 'drunk': False})
    beers.append(b)

# scoring
for b in beers:
    if not b['is_beer']:
        b['score'] = None
        continue
    fam = b['family']
    aff = profile.get(fam, {}).get('affinity', 0.25)
    if not fam:
        aff = 0.3                                   # unmatched: neutral-ish
    # How you rate this brewery, as a deviation from your overall average.
    bw = brewery_ratings.get(norm(b['brewery'])) or \
        brewery_ratings.get(norm(b['exhibitor'])) or []
    if bw:
        bw_avg = sum(bw) / len(bw)
        bw_conf = min(len(bw) / 20, 1.0)
        bw_bias = max(-1.0, min((bw_avg - overall_avg) / 0.4, 1.0)) * bw_conf
    else:
        bw_avg, bw_bias = None, 0.0
    b['brewery_avg'] = round(bw_avg, 2) if bw_avg else None
    b['brewery_n'] = len(bw)

    rating = b['rating']
    n = b['rating_count']
    if n >= 5:
        quality = max(0.0, min((rating - 3.2) / 1.0, 1.0))
        novelty = 0.0
        bw_weight = 0.06        # we have real data; brewery is a nudge only
    else:
        quality = 0.45          # unknown, not bad
        novelty = 0.15          # new beers are the point
        bw_weight = 0.22        # no rating: your brewery history carries it
    award = 0.12 if b['awards'] else 0.0
    b['score'] = round(100 * (0.55 * aff + 0.33 * quality + novelty + award
                              + bw_weight * bw_bias), 1)

with open(os.path.join(HERE, 'data.json'), 'w') as f:
    json.dump({'profile': profile, 'beers': beers,
               'overall_avg': round(overall_avg, 2)}, f)

# ---- report ----
n = len(beers)
matched = [b for b in beers if b['bid']]
real = [b for b in beers if b['is_beer']]
matched_real = [b for b in real if b['bid']]
drunk = [b for b in matched if b['drunk']]
rated = [b for b in matched if b['rating_count'] >= 5]

print(f"beers in list          : {n}   (actual beer: {len(real)}, other drinks: {n-len(real)})")
print(f"matched on Untappd     : {len(matched)} ({len(matched)/n:.0%})"
      f"   of real beer: {len(matched_real)}/{len(real)} ({len(matched_real)/len(real):.0%})")
print(f"  by tier              : " + ", ".join(
    f"t{t}={sum(1 for b in matched if b['match_tier']==t)}" for t in (0, 1, 2)))
print(f"have a rating (>=5)    : {len(rated)} ({len(rated)/len(matched):.0%} of matched)")
print(f"already drunk          : {len(drunk)} ({len(drunk)/len(matched):.0%} of matched)")
print(f"breweries resolved     : {len(brewery_map)}/{len(brewery_names)}")
print()
print("your taste profile (top families by affinity):")
for f, p in sorted(profile.items(), key=lambda kv: -kv[1]['affinity'])[:8]:
    print(f"  {f:<22} affinity {p['affinity']:.2f}  "
          f"({p['checkins']:>4} checkins, avg {p['avg_rating']})")
print()
print("top 15 recommendations (not yet drunk):")
recs = sorted([b for b in real if b['score'] is not None and not b['drunk']],
              key=lambda b: -b['score'])[:15]
for b in recs:
    tag = f"{b['rating']:.2f} ({b['rating_count']})" if b['rating_count'] >= 5 else "unrated/new"
    print(f"  {b['score']:>5}  {b['brewery'][:20]:<20} {b['name'][:32]:<32} "
          f"{(b['style'] or b['sheet_style'])[:24]:<24} {tag}")
