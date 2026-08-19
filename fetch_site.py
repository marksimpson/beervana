"""Pull the brewery and beer list from beervana.co.nz.

The spreadsheet turned out to be incomplete - Canyon Brewing is on the map and
on the website but absent from the CSV - so the website is treated as the
authoritative list. Each brewery page is a Next.js page with its beers embedded
in __NEXT_DATA__, so no scraping of rendered HTML is needed.

Writes site-beers.json.
"""
import json, os, re, subprocess, time, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = 'https://beervana.co.nz'
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')
CACHE = os.path.join(HERE, '.site-cache')
os.makedirs(CACHE, exist_ok=True)


def get(url):
    """Fetch a page, caching to disk so re-runs cost nothing."""
    name = re.sub(r'[^a-z0-9]+', '_', url.lower())[-80:] + '.html'
    path = os.path.join(CACHE, name)
    if not os.path.exists(path):
        subprocess.run(['curl', '-sL', '-A', UA, url, '-o', path], check=True)
        time.sleep(0.4)                      # be polite
    return open(path, encoding='utf8', errors='replace').read()


def strip_html(s):
    s = re.sub(r'<[^>]+>', ' ', s)
    s = (s.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
          .replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' '))
    return re.sub(r'\s+', ' ', s).strip()


def next_data(html):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    return json.loads(m.group(1)) if m else None


# --- every brewery page, from the sitemap ---------------------------------
# The sitemap lags the site: canyon-brewing has a live page and is on the venue
# map, but never appears in sitemap-0.xml. Anything found by hand goes here.
EXTRA_SLUGS = ['canyon-brewing']

sitemap = get(f'{SITE}/sitemap-0.xml')
slugs = sorted({m.rsplit('/', 1)[-1]
                for m in re.findall(r'<loc>(.*?)</loc>', sitemap)
                if '/breweries/' in m and not m.rstrip('/').endswith('breweries')}
               | set(EXTRA_SLUGS))

print(f'brewery pages in sitemap: {len(slugs)}')

out = []
for i, slug in enumerate(slugs, 1):
    d = next_data(get(f'{SITE}/breweries/{urllib.parse.quote(slug)}'))
    if not d:
        print(f'  ! {slug}: no page data')
        continue
    init = d.get('props', {}).get('pageProps', {}).get('subscription', {}) \
            .get('initialData', {})
    brewery = init.get('brewery') or {}
    beers = init.get('beers') or []
    name = brewery.get('name')
    if not name:
        print(f'  ! {slug}: no brewery name')
        continue
    for b in beers:
        # beerType is a nested record; styleLabel is a free-text override.
        bt = b.get('beerType') or {}
        style = (b.get('styleLabel') or '').strip() or (bt.get('typeName') or '').strip()
        out.append({
            'brewery': (b.get('displayBrewery') or '').strip() or name.strip(),
            'page_brewery': name.strip(),
            'slug': slug,
            'name': (b.get('name') or '').strip(),
            'abv': b.get('abv'),
            'style': style,
            'notes': strip_html(b.get('description') or ''),
        })
    print(f'  [{i:>2}/{len(slugs)}] {name:<36} {len(beers):>3} beers')

with open(os.path.join(HERE, 'site-beers.json'), 'w') as f:
    json.dump(out, f, indent=1)

print()
print(f'breweries: {len({b["page_brewery"] for b in out})}   beers: {len(out)}')
