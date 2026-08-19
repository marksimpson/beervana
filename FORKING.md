# Forking this for your own Untappd history

Written for whoever is doing the work, human or Claude. It assumes you want the
same app, for the same festival, with your own drinking history baked in instead
of Mark's.

## How much work this is

Not much. The pipeline never had anything person-specific in it — `match.py`
reads whatever check-in history it finds and derives a taste profile from that,
so pointing it at your export is the whole job. Budget about twenty minutes,
most of it waiting for Untappd to email you a file.

The one thing that might stop you is money: the data export is behind Untappd's
paid Insider subscription. Without it you cannot get your history out, and
without your history this fork has no point. A month is enough.

## What you need

- An Untappd account with **Insider** (paid) so you can export your history
- Python 3 and `curl`, both already on macOS
- A GitHub account, for free Pages hosting
- `pdftotext` (`brew install poppler`) — only if you re-run the venue map step,
  which you do not need to

## Steps

### 1. Fork and clone

Fork `marksimpson/beervana` on GitHub, then clone your fork.

### 2. Export your Untappd history

On untappd.com, go to your profile settings and find the data export. Ask for
**JSON**, not CSV. It arrives by email, usually within a few minutes.

Save it in the repo root as exactly:

```
untappd-history.json
```

It should be a JSON array of check-in objects, each with at least `bid`,
`beer_type`, `brewery_name` and `rating_score`. Mark's had 7,982 entries over
14 years and came to 6.4 MB — yours will differ, and a much smaller history
still works, just with a coarser taste profile.

**Check it is ignored by git before you go any further:**

```bash
git check-ignore -v untappd-history.json
```

That must print a match against `.gitignore`. If it prints nothing, stop and fix
it. This file contains every venue you have drunk at, with GPS coordinates and
timestamps. It must never be committed.

### 3. Run the matcher

```bash
python3 match.py
```

It resolves all 344 festival beers against Untappd, works out which ones you
have already checked in, derives your style preferences, and writes `data.json`.
Takes under a minute.

It uses the Algolia search index that backs Untappd's own website, with the
public search-only key the site ships to every browser. No login, no cookies,
nothing touching your account. Responses cache to `.algolia-cache.json`, so a
second run is instant. Be reasonable with it — do not put it in a loop.

Read the report it prints. Expect roughly:

```
matched on Untappd  : 271 (79%)   of real beer: 245/270 (91%)
already drunk       : <this number will be yours>
```

The match rate does not depend on your history, so if it comes out far below 91%
something has gone wrong. The "already drunk" count and the taste profile are
the parts that should look like you. If the top style families are not ones you
recognise as your own drinking, check you exported the right account.

### 4. Put your name on it

One line, near the top of the script block in `index.html`:

```js
const OWNER = 'Mark';
```

Change it to your name. That is the only name in the app.

Do **not** find-and-replace "Mark" across the file. There is a button labelled
"Mark as had it", where "Mark" is the verb. Replacing it gives you "Dave as had
it".

### 5. Deploy

```bash
git add data.json index.html
git commit -m "chore: rebuild for my own Untappd history"
git push
```

Then enable Pages on your fork — Settings, Pages, deploy from `main`, root
folder. It takes a minute or two to build.

Your two URLs are then:

- `https://<you>.github.io/beervana/?mine` — your recommendations. Open this
  once on your phone and Add to Home Screen; it stores the setting and strips
  the parameter, so the device stays in your mode permanently.
- `https://<you>.github.io/beervana/` — plain ratings, for sharing.

## What ends up public

`data.json` ships with the app and is readable by anyone with the URL. From your
history it carries exactly two derived things:

- a `drunk` flag on beers you have checked in — for Mark that was 66 beers
- a `weight` per beer, 0-100, which reverse-engineers to a style ranking
  (his came out Stout 72, IPA 70, Pale Ale 58, Lager 20)

Everything else stays local. No venues, no timestamps, no comments, no photos,
no tagged friends, and none of your individual ratings. Your Untappd profile is
public by default anyway, which makes the drunk flags a subset of what is
already out there under your name.

If that is not acceptable to you, use a private repo — but free GitHub Pages
requires a public one, so you would need a paid plan or a different host.

## Things that will bite you

**The service worker caches aggressively.** It is network-first so it refreshes
when online, but if you are testing changes and not seeing them, bump `CACHE` in
`sw.js` and hard-reload.

**Aisle numbers are approximate.** They come from scraping the venue map PDF,
which is vector art, so the labels have real coordinates. But each label has a
leader line running to a dot somewhere else — up to about 60pt away, against
roughly 70pt aisle spacing. Some stands are one aisle out. Fine for finding your
way, not worth trusting to the metre. `stand-aisles.json` is committed, so you
do not need to re-run `map_aisles.py` unless you want to improve it.

**The entrance is hardcoded.** `const ENTRANCE = 16` in `index.html` orders the
stand list from where you come in. Change it if you enter elsewhere.

**25 beers never matched Untappd.** They show `N/A` and a "Search Untappd"
button rather than a direct link. Most are matching failures rather than genuine
debuts — "Cassels APA" is almost certainly on Untappd under a slightly different
name. Improving `match.py`'s name cleaning would claw some back.

**The rating threshold is 5.** Beers with fewer ratings publish as unrated and
display as "New", on the grounds that 4.8 from two mates is not a signal. It is
in `match.py` if you disagree.

## Using this for a different festival

Harder, and not a fork job. `beervana-2026-beer-list.csv` and the map PDF are
specific to Beervana 2026. You would need an equivalent beer list with exhibitor,
brewery, beer name, ABV and style columns, and `map_aisles.py` assumes a very
particular map: an oval concourse with "AISLE n" text labels and stands around
the outside. Expect to rewrite it.

The matching and scoring in `match.py` would carry over unchanged.
