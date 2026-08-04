#!/usr/bin/env python3
"""Everyday Ham sponsor media kit generator (Claude Project version).

Self-contained: fetches current stats from the PUBLIC analytics repo
(github.com/jmills06/everyday-ham-analytics, data/latest/*.json, kept
fresh by the repo's own automated collectors), the brand logo from the
same repo's media/ folder, and OFL-licensed fonts from the Google Fonts
GitHub mirror. Renders a three-page sponsor kit PDF styled after
everydayham.com (light Paper palette, Signal Orange accents, Barlow
Condensed + Inter).

Run inside Claude's code environment: python3 build_media_kit.py
Output: everyday-ham-media-kit.pdf (US Letter, 3 pages)

PRINT-SAFE BY DESIGN: the kit may be printed, so there are no full-width
Ink bands or heavy dark coverage. Section rhythm uses Paper / Paper Deep
alternation instead.

BRAND: two palettes (brand guide v1.1). Brand core (#FF7030 orange,
#152333 navy) lives in the logo ONLY and is never repainted. The web
palette below is what the kit uses; Signal Orange #D84E2A is correct and
must not be "fixed" to the logo orange.

On any fetch/parse failure this exits non-zero and produces nothing:
stale kit beats wrong kit. Revenue/AdSense data is never included.

MANUAL INPUTS: podcast geography, monthly download rate and back-catalogue
share come from Buzzsprout dashboard CSV exports (the Buzzsprout API has
no stats endpoints). See MANUAL block below; refresh at each rebuild.
"""
import json, base64, statistics, datetime, pathlib, urllib.request, re

RAW = "https://raw.githubusercontent.com"
REPO = RAW + "/jmills06/everyday-ham-analytics/main"
DATA = REPO + "/data/latest/{}.json"
LOGO_URL = REPO + "/media/Vector%20Pig%20Logo%20no%20tag.png"
FONT_URLS = {
    "BarlowCondensed-Bold.ttf":     RAW + "/google/fonts/main/ofl/barlowcondensed/BarlowCondensed-Bold.ttf",
    "BarlowCondensed-SemiBold.ttf": RAW + "/google/fonts/main/ofl/barlowcondensed/BarlowCondensed-SemiBold.ttf",
    "BarlowCondensed-Medium.ttf":   RAW + "/google/fonts/main/ofl/barlowcondensed/BarlowCondensed-Medium.ttf",
    "Inter.ttf":                    RAW + "/google/fonts/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf",
}
FONTS = pathlib.Path("fonts"); FONTS.mkdir(exist_ok=True)
ASSETS = pathlib.Path("assets"); ASSETS.mkdir(exist_ok=True)
OUT_PDF = pathlib.Path("everyday-ham-media-kit.pdf")

# ---------- MANUAL: Buzzsprout dashboard exports, refresh each rebuild ----------
# Stats > Podcast Overview  -> stats_overview_report.csv
# Stats > Locations         -> stats_locations_report.csv
MANUAL_AS_OF        = "August 2026"
POD_US_PCT          = 87     # locations report, United States share
POD_COUNTRIES       = 90     # locations report, distinct countries
POD_DL_30D          = 2264   # overview report, sum of Last 30 Days
POD_BACKCAT_PCT     = 51     # share of that 30d total from older episodes
# --------------------------------------------------------------------------------

def http_get(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()

for name, url in FONT_URLS.items():
    p = FONTS / name
    if not p.exists():
        p.write_bytes(http_get(url))

LOGO = ASSETS / "pig.png"
if not LOGO.exists():
    LOGO.write_bytes(http_get(LOGO_URL))

# ---------- load data ----------
analytics = json.loads(http_get(DATA.format("analytics")))
youtube   = json.loads(http_get(DATA.format("youtube")))
buzz      = json.loads(http_get(DATA.format("buzzsprout")))

ch  = youtube["channel"]
tot = analytics["totals"]
fmt = lambda n: f"{n:,}"

# ---------- podcast ----------
eps_chrono = sorted(buzz["episodes"], key=lambda e: e["published_at"])
ep_series  = [e["plays"] for e in eps_chrono]
med_first6 = round(statistics.median(ep_series[:6]))
med_last6  = round(statistics.median(ep_series[-6:]))
ep_growth  = round(med_last6 / med_first6, 1)

durs = [e["duration_sec"] for e in eps_chrono if e.get("duration_sec")]
ep_len_min = round(statistics.median(durs) / 60) if durs else 0

_d = [datetime.date.fromisoformat(e["published_at"][:10]) for e in eps_chrono]
ep_gap = round(statistics.median([(_d[i+1] - _d[i]).days for i in range(len(_d) - 1)]))
ep_span_months = round((_d[-1] - _d[0]).days / 30.44)

# ---------- YouTube cadence (long-form only, >=3 min) ----------
def _dur(s):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    h, mi, se = [int(x or 0) for x in m.groups()] if m else (0, 0, 0)
    return h * 3600 + mi * 60 + se

_now = datetime.datetime.now(datetime.timezone.utc)
_vids = [(datetime.datetime.fromisoformat(v["published_at"].replace("Z", "+00:00")), _dur(v["duration"]))
         for v in youtube["videos"]]
lf_30 = sum(1 for d, s in _vids if s >= 180 and (_now - d).days <= 30)
lf_90 = sum(1 for d, s in _vids if s >= 180 and (_now - d).days <= 90)
lf_len = round(statistics.median([s for _, s in _vids if s >= 180]) / 60)

# ---------- discovery ----------
not_sub_pct = round(100 * tot["not_subscribed_views"] /
                    (tot["subscribed_views"] + tot["not_subscribed_views"]))
ts = {t["source"]: t["views"] for t in analytics["traffic_sources"]}
ts_total = sum(ts.values())
def pct(*keys):
    return round(100 * sum(ts.get(k, 0) for k in keys) / ts_total)
src_search    = pct("YT_SEARCH")
src_subs      = pct("SUBSCRIBER", "NOTIFICATION")
src_suggested = pct("RELATED_VIDEO")
src_external  = pct("EXT_URL")
src_other     = 100 - (src_subs + src_search + src_suggested + src_external)

# ---------- YouTube geography + demographics (365d) ----------
geo = analytics.get("geography_365") or []
geo_total = sum(g["views"] for g in geo) or 1
yt_us_pct = round(100 * next((g["views"] for g in geo if g["country"] == "US"), 0) / geo_total)
CODES = {"US": "United States", "GB": "United Kingdom", "CA": "Canada", "DE": "Germany",
         "JP": "Japan", "AU": "Australia", "NL": "Netherlands", "ES": "Spain",
         "PL": "Poland", "IT": "Italy", "FR": "France", "SE": "Sweden", "BR": "Brazil"}
geo_rows = [(CODES.get(g["country"], g["country"]), round(100 * g["views"] / geo_total))
            for g in geo[1:5]]
geo_max = max([p for _, p in geo_rows], default=1)

dem = analytics.get("demographics_365") or []
OLD = ("age45-54", "age55-64", "age65-")
dem_45plus = round(sum(d["viewer_pct"] for d in dem if d["age_group"] in OLD))
_ages = {}
for d in dem:
    _ages[d["age_group"]] = _ages.get(d["age_group"], 0) + d["viewer_pct"]
AGE_LABEL = {"age13-17": "13-17", "age18-24": "18-24", "age25-34": "25-34",
             "age35-44": "35-44", "age45-54": "45-54", "age55-64": "55-64", "age65-": "65+"}
age_rows = [(AGE_LABEL.get(k, k), v) for k, v in sorted(_ages.items()) if v >= 1]
age_max = max([v for _, v in age_rows], default=1)

# ---------- charts ----------
daily = analytics["daily"]
maxv = max(d["views"] for d in daily)
bars, bw, gap, chart_h = "", 8.5, 3.4, 44
for i, d in enumerate(daily):
    h = max(3, round(chart_h * d["views"] / maxv))
    hot = ' class="hot"' if d["views"] == maxv else ""
    bars += f'<rect{hot} x="{i * (bw + gap)}" y="{chart_h - h}" width="{bw}" height="{h}" rx="2"/>'
chart_w = len(daily) * (bw + gap) - gap

_emax, _ebw, _egap, _ech = max(ep_series), 11.0, 4.2, 44
ep_gridline = (_emax // 500) * 500 or (_emax // 100) * 100
ep_gy = round(_ech - _ech * ep_gridline / _emax, 1)
ep_bars = ""
for _i, _v in enumerate(ep_series):
    _h = max(3, round(_ech * _v / _emax))
    _hot = ' class="hot"' if _i >= len(ep_series) - 6 else ""
    ep_bars += f'<rect{_hot} x="{_i * (_ebw + _egap)}" y="{_ech - _h}" width="{_ebw}" height="{_h}" rx="2"/>'
ep_cw = len(ep_series) * (_ebw + _egap) - _egap
ep_bars += (f'<line x1="0" y1="{ep_gy}" x2="{ep_cw}" y2="{ep_gy}" stroke="rgba(27,25,23,.30)" '
            f'stroke-width="0.8" stroke-dasharray="4 4" fill="none"/>')

updated = datetime.datetime.fromisoformat(
    analytics["fetched_at"].replace("Z", "+00:00")).strftime("%B %Y").upper()

_w0 = datetime.date.fromisoformat(daily[0]["date"])
_w1 = datetime.date.fromisoformat(daily[-1]["date"])
window_txt = f'{_w0.day} {_w0.strftime("%B")} to {_w1.day} {_w1.strftime("%B %Y")}'

def font64(name):
    return base64.b64encode((FONTS / name).read_bytes()).decode()

# logo: downscale before embedding so the PDF stays small
try:
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    _im = Image.open(LOGO); _im.thumbnail((520, 520), Image.LANCZOS)
    _p = ASSETS / "pig-small.png"; _im.save(_p, optimize=True)
    logo64 = base64.b64encode(_p.read_bytes()).decode()
except Exception:
    logo64 = base64.b64encode(LOGO.read_bytes()).decode()

html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
@font-face {{ font-family:'Barlow Condensed'; font-weight:700; src:url(data:font/ttf;base64,{font64('BarlowCondensed-Bold.ttf')}) format('truetype'); }}
@font-face {{ font-family:'Barlow Condensed'; font-weight:600; src:url(data:font/ttf;base64,{font64('BarlowCondensed-SemiBold.ttf')}) format('truetype'); }}
@font-face {{ font-family:'Barlow Condensed'; font-weight:500; src:url(data:font/ttf;base64,{font64('BarlowCondensed-Medium.ttf')}) format('truetype'); }}
@font-face {{ font-family:'Inter'; font-weight:100 900; src:url(data:font/ttf;base64,{font64('Inter.ttf')}) format('truetype'); }}

:root {{
  --paper:#F7F3EA; --paper-deep:#EFE8DA; --card:#FFFFFF; --line:rgba(27,25,23,.14);
  --signal:#D84E2A; --signal-dark:#B83D1E; --gold:#E0A52E;
  --text:#2C2925; --text-dim:#6D675E; --navy:#152333; --dim:#A89F92;
}}
* {{ margin:0; padding:0; box-sizing:border-box; -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
body {{ font-family:'Inter',sans-serif; color:var(--text); }}
.page {{ width:8.5in; height:11in; background:var(--paper); padding:.58in .68in .5in; position:relative; overflow:hidden; page-break-after:always; display:flex; flex-direction:column; }}
.page:last-child {{ page-break-after:auto; }}

.kicker {{ font-family:'Barlow Condensed'; font-weight:600; text-transform:uppercase; letter-spacing:.22em; font-size:10.5px; color:var(--signal); margin-bottom:6px; }}
h1 {{ font-family:'Barlow Condensed'; font-weight:700; text-transform:uppercase; font-size:52px; line-height:.96; letter-spacing:.01em; }}
h2 {{ font-family:'Barlow Condensed'; font-weight:700; text-transform:uppercase; font-size:25px; line-height:1.02; margin-bottom:9px; }}
.lede {{ font-size:12.5px; line-height:1.55; color:var(--text-dim); max-width:5.9in; }}

.masthead {{ display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:15px; }}
.brand {{ display:flex; align-items:center; gap:9px; }}
.brand img {{ height:34px; width:auto; }}
.wordmark {{ font-family:'Barlow Condensed'; font-weight:700; text-transform:uppercase; font-size:19px; letter-spacing:.06em; color:var(--navy); line-height:1.05; }}
.wordmark span {{ color:var(--signal); }}
.wordmark .sub {{ font-weight:600; font-size:9px; letter-spacing:.28em; color:var(--text-dim); margin-top:2px; }}
.mast-right {{ font-family:'Barlow Condensed'; font-weight:600; text-transform:uppercase; letter-spacing:.2em; font-size:9.5px; color:var(--text-dim); text-align:right; line-height:1.7; }}

.rule {{ border:0; border-top:1.5px solid var(--line); margin:13px 0; }}

.grid {{ display:grid; gap:12px; }}
.g3 {{ grid-template-columns:1fr 1fr 1fr; }}
.g2 {{ grid-template-columns:1fr 1fr; }}
.g2w {{ grid-template-columns:1.25fr 1fr; }}

.card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:14px 16px; }}
.card.accent {{ border-top:4px solid var(--signal); }}
.stat-num {{ font-family:'Barlow Condensed'; font-weight:700; font-size:36px; line-height:1; color:var(--text); }}
.stat-label {{ font-family:'Barlow Condensed'; font-weight:600; text-transform:uppercase; letter-spacing:.16em; font-size:9.5px; color:var(--signal); margin-bottom:7px; }}
.stat-sub {{ font-size:10px; color:var(--text-dim); margin-top:6px; line-height:1.45; }}

.band {{ background:var(--paper-deep); border-radius:14px; padding:16px 18px; }}

.chips {{ display:flex; flex-wrap:wrap; gap:7px; }}
.chip {{ font-family:'Barlow Condensed'; font-weight:600; text-transform:uppercase; letter-spacing:.1em; font-size:10.5px; background:var(--card); border:1px solid var(--line); border-radius:999px; padding:5px 13px; color:var(--text); white-space:nowrap; }}
.chip b {{ color:var(--signal); font-weight:600; margin-right:4px; }}

ul.tight {{ list-style:none; }}
ul.tight li {{ font-size:11px; line-height:1.5; color:var(--text); padding-left:16px; position:relative; margin-bottom:6px; }}
ul.tight li::before {{ content:"//"; position:absolute; left:0; color:var(--signal); font-family:'Barlow Condensed'; font-weight:600; font-size:10px; top:1.5px; }}
ul.tight b {{ font-weight:600; }}

.callsign {{ color:var(--gold); font-family:'Barlow Condensed'; font-weight:600; letter-spacing:.04em; }}

.srcbar {{ display:flex; height:12px; border-radius:999px; overflow:hidden; margin:10px 0 8px; }}
.legend {{ display:flex; flex-wrap:wrap; gap:4px 14px; font-size:9.5px; color:var(--text-dim); }}
.dot {{ display:inline-block; width:7px; height:7px; border-radius:50%; margin-right:4px; }}

svg rect {{ fill:#E4B9A9; }}
svg rect.hot {{ fill:var(--signal); }}

.geo {{ display:flex; flex-direction:column; gap:5px; margin-top:8px; }}
.geo-row {{ display:flex; align-items:center; gap:8px; font-size:10px; color:var(--text-dim); }}
.geo-row .nm {{ width:88px; flex:none; color:var(--text); }}
.geo-row .tr {{ display:block; flex:1; height:7px; background:var(--paper-deep); border-radius:999px; overflow:hidden; }}
.geo-row .fl {{ display:block; height:7px; background:var(--signal); border-radius:999px; }}
.geo-row .vl {{ width:30px; text-align:right; flex:none; }}

.foot-note {{ font-size:8.5px; color:var(--dim); margin-top:8px; font-style:italic; }}

.footer {{ margin-top:auto; padding-top:13px; border-top:1.5px solid var(--line); display:flex; justify-content:space-between; align-items:center; }}
.foot-sign {{ font-family:'Barlow Condensed'; font-weight:700; text-transform:uppercase; font-size:13px; letter-spacing:.05em; color:var(--text); }}
.foot-sign span {{ color:var(--signal); }}
.foot-meta {{ font-family:'Barlow Condensed'; font-weight:600; text-transform:uppercase; letter-spacing:.18em; font-size:9px; color:var(--text-dim); }}

.pkg-name {{ font-family:'Barlow Condensed'; font-weight:700; text-transform:uppercase; font-size:16px; margin-bottom:4px; }}
.pkg-desc {{ font-size:10.5px; line-height:1.5; color:var(--text-dim); }}
.pkg-spec {{ font-family:'Barlow Condensed'; font-weight:600; text-transform:uppercase; letter-spacing:.12em; font-size:9px; color:var(--signal); margin-top:7px; }}
</style></head><body>
"""

# ============ PAGE 1 ============
html += f"""
<div class="page">
  <div class="masthead">
    <div class="brand">
      <img src="data:image/png;base64,{logo64}" alt="Everyday Ham">
      <div class="wordmark">Everyday Ham<span>.</span><div class="sub">Podcast &amp; YouTube</div></div>
    </div>
    <div class="mast-right">Sponsor Media Kit<br>{updated}</div>
  </div>

  <div class="kicker">Partner With the Show</div>
  <h1>Ham Radio.<br>Real Talk. <span style="color:var(--signal)">No Filter.</span></h1>
  <p class="lede" style="margin-top:16px;">Three Michigan hams talking radio, chasing the hobby wherever it takes us. Weekly videos on YouTube, a monthly podcast, and the occasional special when we can't help ourselves. On the air since 2025, friendly, honest, and never gatekeepy.</p>

  <hr class="rule">

  <div class="kicker" style="margin-top:6px;">By the Numbers</div>
  <div class="grid g3" style="margin-top:6px;">
    <div class="card accent"><div class="stat-label">YouTube Subscribers</div><div class="stat-num">{fmt(ch['subscribers'])}</div><div class="stat-sub">{fmt(ch['videos'])} videos published &middot; {fmt(ch['views'])} lifetime channel views</div></div>
    <div class="card accent"><div class="stat-label">Views / 30 Days</div><div class="stat-num">{fmt(tot['views'])}</div><div class="stat-sub">{fmt(round(tot['watch_hours']))} watch hours &middot; +{tot['subs_net']} net subscribers in the same window</div></div>
    <div class="card accent"><div class="stat-label">Podcast Downloads / 30 Days</div><div class="stat-num">{fmt(POD_DL_30D)}</div><div class="stat-sub">{fmt(buzz['total_downloads'])} lifetime across {buzz['episode_count']} episodes</div></div>
  </div>

  <div class="grid g2" style="margin-top:34px;">
    <div class="card">
      <div class="stat-label">Daily YouTube Views &middot; Last 30 Days</div>
      <svg viewBox="0 0 {chart_w} {chart_h}" width="100%" height="{chart_h}" preserveAspectRatio="none" style="margin-top:6px;">{bars}</svg>
      <div class="stat-sub">Peak day: {fmt(maxv)} views. A steady daily baseline with strong spikes around new-gear coverage.</div>
    </div>
    <div class="card">
      <div class="stat-label">Where Views Come From</div>
      <div class="srcbar">
        <div style="width:{src_subs}%;background:var(--signal);"></div>
        <div style="width:{src_search}%;background:var(--navy);"></div>
        <div style="width:{src_suggested}%;background:var(--gold);"></div>
        <div style="width:{src_external}%;background:#A89F92;"></div>
        <div style="width:{src_other}%;background:#D6CCBC;"></div>
      </div>
      <div class="legend">
        <span><span class="dot" style="background:var(--signal)"></span>Home &amp; Subscriptions Feed {src_subs}%</span>
        <span><span class="dot" style="background:var(--navy)"></span>YouTube Search {src_search}%</span>
        <span><span class="dot" style="background:var(--gold)"></span>Suggested {src_suggested}%</span>
        <span><span class="dot" style="background:#A89F92"></span>External Links {src_external}%</span>
        <span><span class="dot" style="background:#D6CCBC"></span>Other {src_other}%</span>
      </div>
      <div class="stat-sub" style="margin-top:8px;"><b>{not_sub_pct}% of monthly views come from non-subscribers</b>, so your brand reaches new hams discovering us, not just the people already following along.</div>
    </div>
  </div>

  <div class="band" style="margin-top:34px;">
    <div class="kicker" style="margin-bottom:8px;">An Audience That Buys Gear</div>
    <p style="font-size:11px;line-height:1.55;color:var(--text);">Over the last twelve months our viewers arrived searching for products by name: Meshtastic, Wio Tracker L1 Pro, FTDX101MP, ATAS-120A, Icom IC-7300 MK2, Kenwood TM-D750A, Yaesu FTX-1, Icom X-026. These are licensed, active operators researching their next radio, antenna, or accessory, and they trust hands-on takes from operators they know.</p>
    <div class="chips" style="margin-top:10px;">
      <span class="chip"><b>//</b>Gear &amp; Reviews</span><span class="chip"><b>//</b>POTA &amp; Portable Ops</span><span class="chip"><b>//</b>Hamfest Coverage</span><span class="chip"><b>//</b>Digital Modes</span><span class="chip"><b>//</b>Morse Code</span><span class="chip"><b>//</b>Club Life &amp; Field Day</span>
    </div>
  </div>

  <div class="foot-note" style="margin-top:10px;">YouTube figures from YouTube Analytics, {window_txt}, unless a longer window is stated. Podcast figures from Buzzsprout. Nothing here is estimated or projected.</div>

  <div class="footer">
    <div class="foot-sign">Recorded With <span>&hearts;</span> In Michigan</div>
    <div class="foot-meta">Everyday Ham LLC &middot; everydayham.com &middot; Page 1 of 3</div>
  </div>
</div>
"""

_geo_html = "".join(
    f'<div class="geo-row"><span class="nm">{n}</span><span class="tr"><span class="fl" style="width:{max(6, round(100 * p / geo_max))}%"></span></span><span class="vl">{p}%</span></div>'
    for n, p in geo_rows)
_age_html = "".join(
    f'<div class="geo-row"><span class="nm">{n}</span><span class="tr"><span class="fl" style="width:{round(100 * v / age_max)}%"></span></span><span class="vl">{round(v)}%</span></div>'
    for n, v in age_rows)

# ============ PAGE 2 ============
html += f"""
<div class="page">
  <div class="masthead">
    <div class="brand">
      <img src="data:image/png;base64,{logo64}" alt="Everyday Ham">
      <div class="wordmark">Everyday Ham<span>.</span></div>
    </div>
    <div class="mast-right">Sponsor Media Kit &middot; {updated}</div>
  </div>

  <div class="kicker">Who's On The Other End</div>
  <h2>Know Who You're Reaching</h2>
  <div class="grid g2">
    <div class="card">
      <div class="stat-label">YouTube Audience &middot; Last 12 Months</div>
      <div style="display:flex;align-items:baseline;gap:8px;margin-top:4px;">
        <div class="stat-num" style="font-size:30px;">{yt_us_pct}%</div>
        <div style="font-size:10.5px;color:var(--text-dim);">United States</div>
      </div>
      <div class="geo">{_geo_html}</div>
      <div class="stat-sub" style="margin-top:8px;">Top countries after the United States. Based on views with a reported country.</div>
    </div>
    <div class="card">
      <div class="stat-label">Viewer Age &middot; Last 12 Months</div>
      <div style="display:flex;align-items:baseline;gap:8px;margin-top:4px;">
        <div class="stat-num" style="font-size:30px;">{dem_45plus}%</div>
        <div style="font-size:10.5px;color:var(--text-dim);">are 45 or older</div>
      </div>
      <div class="geo">{_age_html}</div>
      <div class="stat-sub" style="margin-top:8px;">Based on signed-in viewers.</div>
    </div>
  </div>

  <div class="grid g2" style="margin-top:12px;">
    <div class="card">
      <div class="stat-label">The Podcast</div>
      <ul class="tight" style="margin-top:4px;">
        <li><b>{POD_US_PCT}% United States</b>, reaching {POD_COUNTRIES} countries and all 50 states</li>
        <li><b>{ep_len_min}-minute episodes</b>, monthly, every {ep_gap} days on average</li>
        <li><b>{POD_BACKCAT_PCT}% of monthly downloads</b> go to episodes published months ago</li>
        <li>Also published as video on Apple Podcasts</li>
      </ul>
      <div class="foot-note">Podcast audience figures as of {MANUAL_AS_OF}.</div>
    </div>
    <div class="card">
      <div class="stat-label">Two Products, Two Jobs</div>
      <p style="font-size:10.5px;line-height:1.55;color:var(--text-dim);margin-top:4px;">YouTube is reach: {fmt(tot['views'])} views a month, most of them from people who don't subscribe yet. The podcast is attention: an hour in someone's ears on the drive to the hamfest or out on a POTA activation.</p>
    </div>
  </div>

  <div class="kicker" style="margin-top:16px;">Still Climbing</div>
  <h2>Momentum</h2>
  <div class="grid g2w">
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:baseline;">
        <div class="stat-label">Podcast Plays Per Episode &middot; All {buzz['episode_count']}</div>
        <div style="font-size:8.5px;color:var(--dim);">dashed line = {fmt(ep_gridline)} plays</div>
      </div>
      <svg viewBox="0 0 {ep_cw} {_ech}" width="100%" height="{_ech}" preserveAspectRatio="none" style="margin-top:6px;">{ep_bars}</svg>
      <div class="stat-sub">Every episode since January 2025, peaking at {fmt(_emax)} plays. Orange bars are our six most recent.</div>
    </div>
    <div class="card">
      <div class="stat-label">The Trend</div>
      <div style="display:flex;gap:16px;margin-top:8px;">
        <div style="flex:1;">
          <div class="stat-num" style="font-size:26px;">{fmt(med_last6)}</div>
          <div class="stat-sub" style="margin-top:4px;">Median plays across our six most recent episodes, up from {fmt(med_first6)} for our first six.</div>
        </div>
        <div style="flex:1;">
          <div class="stat-num" style="font-size:26px;">+{tot['subs_net']}</div>
          <div class="stat-sub" style="margin-top:4px;">Net subscribers in the last 30 days, climbing steadily.</div>
        </div>
      </div>
    </div>
  </div>

  <div class="band" style="margin-top:12px;">
    <div class="kicker" style="margin-bottom:8px;">We Show Up, Every Week</div>
    <p style="font-size:11px;line-height:1.55;color:var(--text);"><b>{lf_30} long-form videos in the last 30 days and {lf_90} in the last 90</b>, at a median of {lf_len} minutes each, plus a {ep_len_min}-minute podcast every month. In {ep_span_months} months we have never gone more than five weeks between episodes. If you are planning a campaign, you can count on the calendar.</p>
  </div>

  <div class="footer">
    <div class="foot-sign">Recorded With <span>&hearts;</span> In Michigan</div>
    <div class="foot-meta">Everyday Ham LLC &middot; everydayham.com &middot; Page 2 of 3</div>
  </div>
</div>
"""

# ============ PAGE 3 ============
html += f"""
<div class="page">
  <div class="masthead">
    <div class="brand">
      <img src="data:image/png;base64,{logo64}" alt="Everyday Ham">
      <div class="wordmark">Everyday Ham<span>.</span></div>
    </div>
    <div class="mast-right">Sponsor Media Kit &middot; {updated}</div>
  </div>

  <div class="kicker">Proof of Reach</div>
  <h2>Coverage That Shows Up First</h2>
  <div class="grid g2">
    <div class="card">
      <div class="stat-label">Flagship Event Coverage</div>
      <ul class="tight" style="margin-top:4px;">
        <li><b>Hamvention 2026 is our biggest search term of the year</b>, and event searches drive a quarter of our search traffic</li>
        <li><b>Hamvention and Hamcation floor coverage</b>, filmed with manufacturer reps on site</li>
        <li><b>Icom ID-5200 hands-on</b> &middot; 10,300+ views</li>
        <li><b>Kenwood TM-D750A first power-on</b> &middot; 9,300+ views</li>
      </ul>
    </div>
    <div class="card">
      <div class="stat-label">Reviews Hams Search For</div>
      <ul class="tight" style="margin-top:4px;">
        <li><b>Meshtastic solar node build</b> &middot; 17,600+ views</li>
        <li><b>Yaesu FTX-1 honest review</b> &middot; 10,600+ views and 138 comments of real owner discussion</li>
        <li><b>Xiegu G7250 first review</b> &middot; 4,900+ views in its first two weeks</li>
        <li>Long shelf life: review content keeps pulling search traffic months after release</li>
      </ul>
    </div>
  </div>

  <hr class="rule">

  <div class="kicker">Ways to Work Together</div>
  <h2>Sponsorship Options</h2>
  <div class="grid g2">
    <div class="card accent"><div class="pkg-name">Host-Read Ads</div><div class="pkg-desc">Spots on the monthly podcast and weekly YouTube videos, read in our own voice. Conversational, not scripted-sounding, because that's the only way our audience would have it.</div><div class="pkg-spec">// 30 or 60 seconds &middot; pre-roll or mid-roll</div></div>
    <div class="card accent"><div class="pkg-name">Product Reviews &amp; Field Tests</div><div class="pkg-desc">Hands-on evaluation on the bench and in the field: POTA activations, Field Day, real operating conditions. We don't lock length or format up front, because the product tells us what the story is.</div><div class="pkg-spec">// Loaned gear returned &middot; no pre-publication approval</div></div>
    <div class="card accent"><div class="pkg-name">Event Coverage Partner</div><div class="pkg-desc">Put your brand on our Hamcation, Hamvention, and Field Day coverage, the highest-reach content we make each year, watched by hams planning their next purchase.</div><div class="pkg-spec">// Hamcation Feb &middot; Hamvention May &middot; Field Day June</div></div>
    <div class="card accent"><div class="pkg-name">Segment &amp; Series Sponsor</div><div class="pkg-desc">Own a recurring segment or a themed series (antenna builds, CW journey, club projects) with naming, logo placement, and verbal credit across podcast and YouTube.</div><div class="pkg-spec">// Naming &middot; logo &middot; verbal credit</div></div>
  </div>
  <p style="font-size:10px;line-height:1.5;color:var(--text-dim);margin-top:9px;">We own what we produce and run it on our own channels. Reuse in your advertising or product pages is a separate conversation, and one we're happy to have. Sponsorship is always disclosed.</p>

  <div class="band" style="margin-top:13px;">
    <div class="grid g2w" style="gap:20px;">
      <div>
        <div class="kicker" style="margin-bottom:6px;">The Hosts</div>
        <p style="font-size:11px;line-height:1.6;">Jim <span class="callsign">N8JRD</span>, event chair &middot; Rory <span class="callsign">W8KNX</span>, technical chair &middot; James <span class="callsign">K8JKU</span>, vice president<br>
        <span style="color:var(--text-dim);">Three friends who love radio, all three officers of club <span class="callsign">W8EDH</span>. POTA activators and unapologetic gear nerds.</span></p>
        <div class="chips" style="margin-top:9px;">
          <span class="chip"><b>//</b>Discord</span><span class="chip"><b>//</b>Instagram</span><span class="chip"><b>//</b>Facebook</span><span class="chip"><b>//</b>TikTok</span>
        </div>
        <p style="font-size:10px;line-height:1.5;color:var(--text-dim);margin-top:7px;">Our community keeps talking between releases, so a sponsored review stays in the conversation long after it publishes.</p>
      </div>
      <div>
        <div class="kicker" style="margin-bottom:6px;">Let's Talk</div>
        <p style="font-size:11px;line-height:1.6;"><b>CQ@everydayham.com</b><br><b>everydayham.com</b></p>
        <p style="font-size:10.5px;line-height:1.55;color:var(--text-dim);margin-top:7px;">Tell us what you have in mind, we'd rather hear your proposal than guess at it. Reach out early for event coverage.</p>
        <p style="font-size:10px;line-height:1.5;color:var(--text-dim);margin-top:6px;">Everyday Ham &middot; 5799 S Main St #1625<br>Clarkston, MI 48347</p>
        <div class="pkg-spec" style="margin-top:7px;">73, The Everyday Ham Crew</div>
      </div>
    </div>
  </div>

  <div class="footer">
    <div class="foot-sign">Recorded With <span>&hearts;</span> In Michigan</div>
    <div class="foot-meta">Everyday Ham LLC &middot; everydayham.com &middot; Page 3 of 3</div>
  </div>
</div>
</body></html>"""

# ---------- render PDF ----------
import tempfile
from playwright.sync_api import sync_playwright

pathlib.Path("debug.html").write_text(html)
with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
    f.write(html)
    tmp_html = pathlib.Path(f.name)

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.goto(tmp_html.as_uri())
    pg.pdf(path=str(OUT_PDF), width="8.5in", height="11in",
           print_background=True, margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
    b.close()
tmp_html.unlink()
print(f"OK media kit: {OUT_PDF.name} ({OUT_PDF.stat().st_size // 1024} KB) | "
      f"subs={ch['subscribers']} views30d={tot['views']} pod30d={POD_DL_30D} "
      f"us={yt_us_pct}% 45plus={dem_45plus}%")
