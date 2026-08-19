"""Pull stand -> aisle numbers out of the Beervana venue map.

The map is an Illustrator PDF, so the labels are real vector text with
coordinates. We find the "AISLE n" markers, merge the wrapped label lines back
together, then assign each exhibitor from the beer list to its nearest marker.
"""
import re, json, os, math, csv, difflib, html, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
PDF = os.path.join(HERE, 'beervana_2026_map_v3.pdf')
BBOX = os.path.join(HERE, 'map-bbox.xml')

if not os.path.exists(BBOX):
    subprocess.run(['pdftotext', '-bbox-layout', PDF, BBOX], check=True)
xml = open(BBOX, encoding='utf8').read()

lines = []
for xa, ya, xb, yb, body in re.findall(
        r'<line xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</line>',
        xml, re.S):
    words = re.findall(r'<word[^>]*>(.*?)</word>', body)
    text = html.unescape(' '.join(words)).strip()
    if text:
        lines.append({'x0': float(xa), 'x1': float(xb),
                      'x': (float(xa) + float(xb)) / 2,
                      'y': (float(ya) + float(yb)) / 2,
                      'h': float(yb) - float(ya), 'text': text})


def is_aisle_word(t):
    u = t.upper().replace(' ', '')
    return u == 'AISLE'


# --- aisle markers: the word, plus the number sitting just below it ---------
aisles = []
for ln in lines:
    if not is_aisle_word(ln['text']):
        continue
    best, bd = None, 1e9
    for other in lines:
        if not re.fullmatch(r'\d{1,2}', other['text']):
            continue
        dy, dx = other['y'] - ln['y'], abs(other['x'] - ln['x'])
        if -5 < dy < 60 and dx < 45 and dy + dx < bd:
            best, bd = other, dy + dx
    if best:
        aisles.append({'n': int(best['text']), 'x': ln['x'], 'y': ln['y']})

seen, uniq = set(), []
for a in sorted(aisles, key=lambda a: a['n']):
    if a['n'] not in seen:
        seen.add(a['n'])
        uniq.append(a)
aisles = uniq

# --- merge wrapped labels ("Brothers" + "Beer" -> "Brothers Beer") ----------
cand = [l for l in lines
        if not is_aisle_word(l['text']) and not re.fullmatch(r'\d{1,2}', l['text'])]
cand.sort(key=lambda l: (round(l['y']), l['x']))

# Each line is a candidate in its own right. Wrapped names are handled by also
# offering tightly-stacked runs of 2-3 lines as candidates. Chaining greedily
# down a column globs separate stands together, so runs are capped and must be
# closely left-aligned.
merged = []
for i, a in enumerate(cand):
    merged.append({'text': a['text'].strip(' :'), 'x': a['x'], 'y': a['y']})
    run = [a]
    for b in cand[i + 1:]:
        last = run[-1]
        if 0 < b['y'] - last['y'] < last['h'] * 1.6 and abs(b['x0'] - last['x0']) < 12:
            run.append(b)
            merged.append({
                'text': re.sub(r'\s+', ' ', ' '.join(g['text'] for g in run)).strip(' :'),
                'x': sum(g['x'] for g in run) / len(run),
                'y': sum(g['y'] for g in run) / len(run)})
            if len(run) == 3:
                break
        else:
            break


# The markers ring the concourse and the stands line the outside of it, so
# straight-line distance misleads: on the left edge the horizontal gap to every
# marker is a large constant that swamps the vertical difference, and the stands
# sit at a wider radius than the markers so angles distort too. Compare along
# the edge the stand is on instead - vertically down the sides, horizontally
# across the top and bottom.
CX = sum(a['x'] for a in aisles) / len(aisles)
CY = sum(a['y'] for a in aisles) / len(aisles)
SPAN_X = max(a['x'] for a in aisles) - min(a['x'] for a in aisles)
SPAN_Y = max(a['y'] for a in aisles) - min(a['y'] for a in aisles)


def on_side_edge(x, y):
    """True if this point sits on a left/right edge rather than top/bottom."""
    return abs(x - CX) / SPAN_X > abs(y - CY) / SPAN_Y


def nearest_aisle(x, y):
    side = on_side_edge(x, y)
    best, bd = None, 1e9
    for a in aisles:
        # Only consider markers on the same edge, so a stand low on the left
        # cannot grab a marker across on the right.
        if on_side_edge(a['x'], a['y']) != side:
            continue
        if side and (a['x'] - CX) * (x - CX) < 0:
            continue
        if not side and (a['y'] - CY) * (y - CY) < 0:
            continue
        d = abs(a['y'] - y) if side else abs(a['x'] - x)
        if d < bd:
            best, bd = a, d
    if best is None:                       # corner cases: fall back to distance
        for a in aisles:
            d = math.hypot(a['x'] - x, a['y'] - y)
            if d < bd:
                best, bd = a, d
    return (best['n'] if best else None), round(bd)


# --- match the beer list's exhibitors onto those labels ---------------------
def norm(s):
    s = s.lower()
    s = re.sub(r'\b(brewing|brewery|breweries|brewers|beer|beers|co|company|'
               r'ltd|limited|taproom|the|nz)\b', ' ', s)
    return re.sub(r'[^a-z0-9]', '', s)


exhibitors = sorted({r['EXHIBITOR'].strip()
                     for r in csv.DictReader(
                         open(os.path.join(HERE, 'beervana-2026-beer-list.csv'),
                              encoding='utf-8-sig'))
                     if r.get('BEER NAME') and r.get('EXHIBITOR')})

# The map labels this stand by its initials, which no fuzzy match will reach.
ALIASES = {'New Kids on the Block': 'NKOTB'}

result, misses = {}, []
for ex in exhibitors:
    target = norm(ALIASES.get(ex, ex))
    best, score = None, 0.0
    for m in merged:
        cand_n = norm(m['text'])
        if not cand_n or not target:
            continue
        s = difflib.SequenceMatcher(None, target, cand_n).ratio()
        if target in cand_n or cand_n in target:
            s = max(s, 0.9)
        if s > score:
            best, score = m, s
    if best and score >= 0.72:
        n, d = nearest_aisle(best['x'], best['y'])
        result[ex] = {'aisle': n, 'label': best['text'], 'confidence': round(score, 2)}
    else:
        misses.append((ex, best['text'] if best else '-', round(score, 2)))

print(f"aisle markers : {len(aisles)}  ({min(a['n'] for a in aisles)}-{max(a['n'] for a in aisles)})")
print(f"map labels    : {len(merged)} after merging")
print(f"exhibitors    : {len(exhibitors)}   placed on an aisle: {len(result)} "
      f"({len(result)/len(exhibitors):.0%})")
print()
for ex, v in sorted(result.items(), key=lambda kv: kv[1]['aisle']):
    flag = '' if v['confidence'] >= 0.85 else '  <- check'
    print(f"  aisle {v['aisle']:>2}  {ex[:32]:<32} = {v['label'][:30]:<30}{flag}")
print()
if misses:
    print("not placed:")
    for ex, guess, s in misses:
        print(f"  {ex[:34]:<34} best guess {guess[:28]:<28} ({s})")

json.dump({ex: v['aisle'] for ex, v in result.items()},
          open(os.path.join(HERE, 'stand-aisles.json'), 'w'), indent=1)
