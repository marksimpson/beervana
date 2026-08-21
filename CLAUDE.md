# Working on this repo

A one-day build for a beer festival on 21 August 2026. Kept simple on purpose:
no framework, no build step, no backend. Read [README.md](README.md) first for
what it does.

## Never commit these

`untappd-history.json` holds every check-in with venue GPS coordinates and
timestamps. `preferences.json` holds opinions about named breweries. Both are
gitignored and must stay that way. Verify with `git check-ignore` rather than
trusting the file is absent.

`data.json` is published to a public GitHub Pages site. Only two things derived
from the history reach it: a `drunk` flag, and the numbers making up the pick
score. No venues, no timestamps, no comments, no individual ratings.

`preferences.json` is the only place reasons are written down, and only the
resulting integer ships. Keep any note in it short and factual - the file
is local, but files move.

## Layout

```
match.py        the build. Reads the CSV + history, matches to Untappd,
                scores, writes data.json. Run it after any input changes.
fetch_site.py   pulls the current beer list off beervana.co.nz into
                site-beers.json. Caches pages to .site-cache/.
map_aisles.py   scrapes aisle numbers off the venue map PDF. Superseded by
                hand-verified numbers - see below.
index.html      the whole app. Inline CSS and JS, no dependencies.
sw.js           service worker. Network first, cache as fallback.
```

Hand-maintained inputs: `aisles-manual.json` (stand to aisle), `beer-bids.json`
(Untappd ids for beers the matcher missed), `preferences.json` (local only).

## Things that will catch you out

### The scoring formula lives in two places

`match.py` computes it, and `weigh()` in `index.html` recomputes it whenever
ratings refresh. If they disagree, the first refresh silently shifts every
score. Change one, change the other, then verify:

```js
DATA.beers.filter((b) => b.is_beer && b.aff != null).filter((b) => Math.abs(weigh(b) - b.weight) > 0.001).length; // must be 0
```

Python's `round()` is half-to-even and JavaScript's `Math.round()` is half-up.
`match.py` uses `math.floor(x * 1000 + 0.5) / 10` to match, and scores off the
already-rounded `aff` and `bwb` it publishes.

### Aisle numbers are hand-checked, not scraped

`map_aisles.py` reads label positions, but every label has a leader line running
to a dot somewhere else - up to 60pt away against roughly 70pt aisle spacing. It
put Behemoth in aisle 35; it is in aisle 1. All 45 stands are now in
`aisles-manual.json`, verified by eye. Do not regenerate them from the scraper.

### Untappd has no usable API

The public API needs a key that is not being issued, and is limited to 100 calls
an hour. Instead, Untappd's site search is backed by Algolia with a search-only
key it ships to every browser. `match.py` queries that: no login, no cookies,
nothing touching anyone's account. Search takes 10 queries a request; the
`/objects` endpoint takes 400 and is exact by `bid`.

Never drive this through the Chrome tools. That is Mark's real browser with his
real Untappd session.

### A cached miss is forever, unless you ask for it back

`.algolia-cache.json` keys on the query, and `algolia()` skips anything already
in it. A beer that found nothing is cached as an empty hit list, which is
indistinguishable from one already answered - so re-running `match.py` when a
brewery has since published the page will not send the query, and the beer stays
missing however many times you run it.

```bash
python3 match.py --retry-misses
```

drops the cached misses and asks again, along with any brewery that never
resolved (that one upgrades its beers from tier 2's unfiltered guesswork to a
filtered search). Matched rows are left alone, so a retry can only add. Read the
`retried misses` block it prints before pushing: those are the loosest matches
in the file and nothing else has reviewed them.

Do not clear the whole cache to achieve this. That re-queries all 376 beers and
can move matches that are already right.

### The scripts re-run themselves in UTF-8 mode

The sheet has macrons and smart quotes, and Untappd returns whatever the brewer
typed. On Windows the locale codepage is cp1252, so a bare `open()` or a
`subprocess.run(text=True)` decodes Algolia's reply as cp1252 and dies - the
reader thread raises, `stdout` comes back `None`, and the traceback you get is
`json.loads(None)` several frames later, pointing nowhere near the cause.

`match.py` and `fetch_site.py` therefore check `sys.flags.utf8_mode` at the top
and, if it is off, restart themselves under `-X utf8`. That has to happen before
the interpreter starts, which is why it cannot just be set in the script.
`BEERVANA_UTF8` is the sentinel that stops it recursing. Both also pass
`encoding='utf-8'` on every `open()` and `subprocess.run`, which is redundant
under UTF-8 mode and kept so the files stay correct if run some other way.

Two things this does not cover, and does not need to: source files are read as
UTF-8 regardless (the `ä` in the Märzen regex is fine), and `data.json` still
lands pure ASCII because `json.dump` escapes non-ASCII by default. Do not "fix"
that second one with `ensure_ascii=False` - the app is fetching it as-is.

### Finding beers without the check-in history

The history is needed to score a beer, not to find one. On a machine without
`untappd-history.json`:

```bash
python3 match.py --find-missing
```

does the lookup only and stops before scoring, writing what it finds into
`beer-bids.json`. It writes nothing to `data.json` - one built without the
history would have no drunk flags and no weights, which is worse than a stale
one. Commit the bids, then run `match.py` normally where the history lives.

It compares against the `url`s already in `data.json` rather than against this
run's own misses, which is what makes it work on a fresh clone: there is no
`.algolia-cache.json` there, so nothing is a repeat and there is nothing to
retry. Ids already in `beer-bids.json` are left alone - hand-picked wins.

### The leaderboard comes from Firebase, not the website

beervana.co.nz sends no CORS headers and `x-frame-options: DENY`, so the page
itself cannot be read or embedded. Its praise counts live in a public Firebase
database at `beers/completed-2026`, keyed by DatoCMS record id, and that does
allow cross-origin reads. The site resolves those ids through an API that only
permits its own origin, so the ids are baked into `data.json` as `dato` instead.

The root path and `/praise` are both denied - only `beers/*` is readable. The
counts there run lower than the website shows, so there is a second counter
behind the denied path. Ordering looks right; the absolute numbers do not match.

### Matching bugs that have already been fixed once

- **A brewery can hold several stands.** One Drop pours from two, and the
  website lists all twelve beers on one page. Matching returns every stand a
  brewery holds; a beer counts as present if it appears at any of them.
- **An exact name match does not end the search.** "Mean Doses" matches its own
  stand exactly and still has a sibling in "Mean Doses Zoltar".
- **Compare brewery names by token, not whole string.** "Scapegrace Gin +
  Thunderdonk Whiskey" and "Scapegrace + Thunderdonk" score too low whole.
- **Deduplicate on raw names.** The site says "APA" where the sheet says
  "Cassels APA". Stripping the brewery prefix needs the word boundaries that
  normalising removes.
- **Tokens under three characters are dropped**, so "One Drop #1" and "One Drop
  #2" reduce to the same two words. Exact matches must win before any fuzzy pass.
- **Use the ABV column over the style text.** A 0% beer written up as a Hazy IPA
  is not one.

`match.py` reports beers appearing at more than one stand. Do not ignore it.

### Caching will show you yesterday's build

Three separate layers had to be fixed:

- The service worker's install-time precache went through the browser's HTTP
  cache, so a new worker installed with old files. It now forces a network fetch.
- Runtime fetches sat on GitHub Pages' ten-minute max-age. Same-origin requests
  now revalidate.
- The app's own first `fetch('data.json')` did the same, before the worker was
  involved. It uses `cache: 'no-cache'`.

Bump `CACHE` in `sw.js` on every deploy.

## Testing

There is no test suite. Verify in a browser against a local server, at an iPhone
viewport, before pushing:

```bash
nohup python3 -m http.server 8807 >/dev/null 2>&1 &
```

Check both modes - `?mine` and the bare URL - and the console for errors. Clear
`localStorage`, unregister the service worker and delete caches afterwards, or
the next test inherits the state.

Deploy is a push to `main`; GitHub Pages builds in a minute or two. Poll
`gh api repos/marksimpson/beervana/pages --jq '.status'` until it reads `built`,
then confirm the live file actually changed rather than assuming.
