"""Collectors: free public data sources turned into candidates and voice items.

Each collector fetches through fetch.get (cached, logged), and writes:
  - candidates (numbers code read from the response) -> data/candidates.jsonl
  - voice items (verbatim user text: reviews, comments) -> data/voice.jsonl
  - discovery lists (keywords, competitors) -> data/*.json
A source that is unreachable is logged and skipped; nothing is invented to
fill the gap. Optional sources need an API key (env var) or a pip package and
say so when missing.
"""

import datetime
import html
import os
import re
import statistics
import urllib.parse

from . import candidates, fetch
from .common import IdeaError, Idea, read_json, read_jsonl, write_json, write_jsonl

TODAY = datetime.date.today


def _q(s):
    return urllib.parse.quote(s, safe="")


def _strip(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _cand(source, source_type, claim, value, unit, url, quote, publisher, raw, sha, query, claim_key, date=None,
          criteria=None):
    return {"source": source, "source_type": source_type, "claim": claim, "value": value, "unit": unit,
            "url": url, "quote": quote, "publisher": publisher, "raw_file": raw, "raw_sha256": sha,
            "query": query, "claim_key": claim_key, "date": date or TODAY().isoformat()[:7],
            "criteria": criteria or []}


def _add_voice(idea, items):
    path = idea.p("data", "voice.jsonl")
    rows = read_jsonl(path)
    seen = {(r["source"], r["url"], r["text"][:80]) for r in rows}
    n = max([int(r["id"][1:]) for r in rows] or [0])
    added = 0
    for it in items:
        if not it.get("text"):
            continue
        k = (it["source"], it["url"], it["text"][:80])
        if k in seen:
            continue
        seen.add(k)
        n += 1
        rows.append(dict(it, id="V%03d" % n, status="pending"))
        added += 1
    write_jsonl(path, rows)
    return added


def _merge_list(idea, name, items, key):
    path = idea.p("data", name)
    cur = read_json(path, default={"items": []})
    have = {i[key] for i in cur["items"]}
    for it in items:
        if it[key] not in have:
            cur["items"].append(it)
            have.add(it[key])
    write_json(path, cur)


# ── demand ──────────────────────────────────────────────────────────────────────
def autocomplete(idea, query, lang="en", country="us"):
    """Google and YouTube suggestions: keyword discovery, not volume. No candidates."""
    out = {}
    for name, extra in (("google", ""), ("youtube", "&ds=yt")):
        url = ("https://suggestqueries.google.com/complete/search?client=firefox&hl=%s&gl=%s&q=%s%s"
               % (lang, country, _q(query), extra))
        data, _, _ = fetch.get(idea, "autocomplete", url, query="%s:%s" % (name, query))
        out[name] = data[1] if isinstance(data, list) and len(data) > 1 else []
    path = idea.p("data", "keywords.json")
    cur = read_json(path, default={})
    cur[query] = dict(out, lang=lang, country=country)
    write_json(path, cur)
    return out


def wikipedia(idea, article, lang="en", months=24):
    """Monthly pageviews of a Wikipedia article: average of the last 12 months and the change on the 12 before."""
    end = TODAY().replace(day=1) - datetime.timedelta(days=1)
    start = (end.replace(day=1) - datetime.timedelta(days=31 * (months - 1))).replace(day=1)
    art = _q(article.replace(" ", "_"))
    url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/%s.wikipedia/all-access/user/%s/monthly/%s/%s"
           % (lang, art, start.strftime("%Y%m%d00"), end.strftime("%Y%m%d00")))
    data, raw, sha = fetch.get(idea, "wikipedia", url, query="%s:%s" % (lang, article))
    views = [int(i["views"]) for i in data.get("items", [])]
    if not views:
        raise IdeaError("no pageviews for %s.wikipedia %r (check the exact article title)" % (lang, article))
    last = views[-12:]
    human = "https://pageviews.wmcloud.org/?project=%s.wikipedia.org&pages=%s&range=last-year" % (lang, art)
    avg = round(sum(last) / float(len(last)))
    out = [_cand("wikipedia", "measured_data",
                 "Average monthly pageviews of the %s Wikipedia article '%s' over the last %d months" % (lang, article, len(last)),
                 avg, "views/month", human, "monthly views (last %d): %s" % (len(last), ", ".join(map(str, last))),
                 "Wikimedia Foundation", raw, sha, article, "wiki_views:%s:%s" % (lang, article), criteria=["demand"])]
    if len(views) >= 24:
        prev = views[-24:-12]
        change = round((sum(last) - sum(prev)) / float(sum(prev)), 3) if sum(prev) else None
        if change is not None:
            out.append(_cand("wikipedia", "measured_data",
                             "Change in pageviews of the %s Wikipedia article '%s', last 12 months vs the 12 before" % (lang, article),
                             change, "fraction", human,
                             "last 12 months total %d, previous 12 months total %d" % (sum(last), sum(prev)),
                             "Wikimedia Foundation", raw, sha, article, "wiki_trend:%s:%s" % (lang, article),
                             criteria=["demand"]))
    return candidates.add(idea, out)


def trends(idea, keywords, geo="", timeframe="today 5-y"):
    """Google Trends via the optional trendspy package: growth of each keyword and their relative sizes."""
    try:
        from trendspy import Trends
    except ImportError:
        fetch.log_skip(idea, "trends", ",".join(keywords), "pip install trendspy to enable Google Trends")
        raise IdeaError("Google Trends needs the optional package: pip install trendspy")
    if not 1 <= len(keywords) <= 5:
        raise IdeaError("Google Trends compares 1 to 5 keywords at a time")
    try:
        df = Trends(request_delay=2.0).interest_over_time(keywords, timeframe=timeframe, geo=geo)
    except Exception as e:  # quota, blocked, changed endpoint
        fetch.log_error(idea, "trends", ",".join(keywords), e)
        raise IdeaError("Google Trends failed: %s" % str(e)[:160])
    series = {c: [float(v) for v in df[c].tolist()] for c in df.columns if c in keywords}
    dates = [str(d)[:10] for d in df.index]
    raw, sha = fetch.store_raw(idea, "trends", "%s|%s|%s" % (",".join(keywords), geo, timeframe),
                               {"dates": dates, "series": series, "geo": geo, "timeframe": timeframe})
    human = "https://trends.google.com/trends/explore?date=%s&geo=%s&q=%s" % (
        _q(timeframe), geo, ",".join(_q(k) for k in keywords))
    out = []
    per_year = max(1, len(dates) // 5) if timeframe == "today 5-y" else max(1, len(dates) // 4)
    for k, vals in series.items():
        if len(vals) < 2 * per_year:
            continue
        first, last = vals[:per_year], vals[-per_year:]
        f, l = statistics.mean(first), statistics.mean(last)
        out.append(_cand("trends", "measured_index",
                         "Google Trends interest in '%s' (%s), average of the last year vs the first year of %s" % (
                             k, geo or "worldwide", timeframe), round((l - f) / f, 3) if f else None, "fraction",
                         human, "first-year mean %.1f, last-year mean %.1f (index 0-100, relative)" % (f, l),
                         "Google Trends", raw, sha, k, "trends_growth:%s:%s" % (geo, k), criteria=["demand"]))
        out.append(_cand("trends", "measured_index",
                         "Google Trends average interest in '%s' (%s) over %s, relative to the other keywords compared (%s)" % (
                             k, geo or "worldwide", timeframe, ", ".join(keywords)), round(statistics.mean(vals), 1),
                         "index 0-100", human, "mean of %d points" % len(vals), "Google Trends", raw, sha, k,
                         "trends_level:%s:%s" % (geo, ",".join(sorted(keywords))), criteria=["demand"]))
    return candidates.add(idea, [c for c in out if c["value"] is not None])


# ── competitors ─────────────────────────────────────────────────────────────────
def itunes(idea, term, country="us", limit=15):
    """Apple App Store search: apps, prices, rating counts (a traction proxy)."""
    url = "https://itunes.apple.com/search?term=%s&country=%s&entity=software&limit=%d" % (_q(term), country, limit)
    data, raw, sha = fetch.get(idea, "itunes", url, query="%s:%s" % (country, term))
    out, comps = [], []
    for a in data.get("results", []):
        name, link = a.get("trackName"), a.get("trackViewUrl")
        comps.append({"key": "ios:%s" % a.get("trackId"), "name": name, "url": link, "seller": a.get("sellerName"),
                      "price": a.get("price"), "currency": a.get("currency"), "store": "ios", "country": country,
                      "rating": a.get("averageUserRating"), "rating_count": a.get("userRatingCount"),
                      "genre": a.get("primaryGenreName"), "released": (a.get("releaseDate") or "")[:10]})
        if a.get("userRatingCount") is not None:
            out.append(_cand("itunes", "app_store", "App Store (%s) rating count of '%s' by %s" % (
                country.upper(), name, a.get("sellerName")), int(a["userRatingCount"]), "ratings", link,
                "userRatingCount: %s, averageUserRating: %s" % (a["userRatingCount"], a.get("averageUserRating")),
                "Apple App Store", raw, sha, term, "ios_ratings:%s:%s" % (country, a.get("trackId")),
                criteria=["competition", "demand"]))
        if a.get("price") is not None:
            out.append(_cand("itunes", "app_store", "App Store (%s) upfront price of '%s'" % (country.upper(), name),
                             float(a["price"]), a.get("currency", ""), link,
                             "price: %s %s" % (a["price"], a.get("currency", "")), "Apple App Store", raw, sha, term,
                             "ios_price:%s:%s" % (country, a.get("trackId")), criteria=["willingness_to_pay"]))
    _merge_list(idea, "competitors.json", comps, "key")
    return candidates.add(idea, out)


def appreviews(idea, app_id, country="us", pages=2):
    """Recent App Store reviews (verbatim) of one app, into the voice corpus."""
    items = []
    for p in range(1, pages + 1):
        url = "https://itunes.apple.com/%s/rss/customerreviews/page=%d/id=%s/sortby=mostrecent/json" % (country, p, app_id)
        data, raw, sha = fetch.get(idea, "appreviews", url, query="%s:%s:p%d" % (country, app_id, p))
        entries = (data.get("feed") or {}).get("entry") or []
        if isinstance(entries, dict):
            entries = [entries]
        for e in entries:
            if "im:rating" not in e:
                continue
            title = (e.get("title") or {}).get("label", "")
            body = (e.get("content") or {}).get("label", "")
            items.append({"source": "appreviews", "source_type": "review_platform", "publisher": "Apple App Store",
                          "url": "https://apps.apple.com/%s/app/id%s?see-all=reviews" % (country, app_id),
                          "about": "ios:%s" % app_id, "rating": int(e["im:rating"]["label"]),
                          "date": (e.get("updated") or {}).get("label", "")[:10],
                          "text": ("%s. %s" % (title, body)).strip(), "raw_file": raw, "raw_sha256": sha})
    return _add_voice(idea, items)


def gplay(idea, term, country="us", lang="en", n=15, review_apps=0):
    """Google Play search (optional package google-play-scraper): install buckets and scores; with review_apps=N,
    the 1-3 star reviews of the first N apps go into the voice corpus."""
    try:
        from google_play_scraper import Sort, reviews as gp_reviews, search as gp_search
    except ImportError:
        fetch.log_skip(idea, "gplay", term, "pip install google-play-scraper to enable Google Play")
        raise IdeaError("Google Play needs the optional package: pip install google-play-scraper")
    try:
        res = gp_search(term, n_hits=n, lang=lang, country=country)
    except Exception as e:
        fetch.log_error(idea, "gplay", term, e)
        raise IdeaError("Google Play search failed: %s" % str(e)[:160])
    keep = [{k: r.get(k) for k in ("appId", "title", "developer", "score", "installs", "price", "free", "currency", "genre")}
            for r in res]
    raw, sha = fetch.store_raw(idea, "gplay", "%s:%s:%s" % (country, lang, term), keep)
    out, comps = [], []
    for r in keep:
        link = "https://play.google.com/store/apps/details?id=%s&hl=%s&gl=%s" % (r["appId"], lang, country)
        comps.append({"key": "android:%s" % r["appId"], "name": r["title"], "url": link, "seller": r["developer"],
                      "price": r["price"], "currency": r["currency"], "store": "android", "country": country,
                      "rating": r["score"], "installs": r["installs"], "genre": r["genre"]})
        m = re.match(r"^([\d,.]+)\+?$", str(r.get("installs") or "").strip())
        if m:
            inst = int(re.sub(r"[,.]", "", m.group(1)))
            out.append(_cand("gplay", "app_store", "Google Play (%s) install bucket of '%s' by %s (lower bound)" % (
                country.upper(), r["title"], r["developer"]), inst, "installs", link, "installs: %s" % r["installs"],
                "Google Play", raw, sha, term, "android_installs:%s:%s" % (country, r["appId"]),
                criteria=["competition", "demand"]))
    _merge_list(idea, "competitors.json", comps, "key")
    added = candidates.add(idea, out)
    for r in keep[:review_apps]:
        items = []
        for star in (1, 2, 3):
            try:
                revs, _ = gp_reviews(r["appId"], lang=lang, country=country, sort=Sort.NEWEST, count=40,
                                     filter_score_with=star)
            except Exception as e:
                fetch.log_error(idea, "gplay-reviews", r["appId"], e)
                continue
            for v in revs:
                items.append({"source": "gplay-reviews", "source_type": "review_platform", "publisher": "Google Play",
                              "url": "https://play.google.com/store/apps/details?id=%s&showAllReviews=true" % r["appId"],
                              "about": "android:%s" % r["appId"], "rating": int(v.get("score") or star),
                              "date": str(v.get("at") or "")[:10], "text": (v.get("content") or "").strip()})
        if items:
            rraw, rsha = fetch.store_raw(idea, "gplay-reviews", "%s:%s" % (country, r["appId"]), items)
            for it in items:
                it.update(raw_file=rraw, raw_sha256=rsha)
            _add_voice(idea, items)
    return added


def hn(idea, query, months=24, comments=True):
    """Hacker News (Algolia): how often a topic comes up, top stories, and comments for the voice corpus."""
    since = int((datetime.datetime.now() - datetime.timedelta(days=30 * months)).timestamp())
    url = ("https://hn.algolia.com/api/v1/search?query=%s&tags=story&numericFilters=created_at_i>%d&hitsPerPage=30"
           % (_q(query), since))
    data, raw, sha = fetch.get(idea, "hn", url, query="stories:%s" % query)
    human = "https://hn.algolia.com/?dateRange=custom&query=%s&type=story" % _q(query)
    out = [_cand("hn", "measured_data", "Hacker News stories matching '%s' in the last %d months" % (query, months),
                 int(data.get("nbHits", 0)), "stories", human, "nbHits: %s" % data.get("nbHits", 0),
                 "Hacker News (Algolia search)", raw, sha, query, "hn_stories:%s:%d" % (query, months),
                 criteria=["demand"])]
    for h in data.get("hits", [])[:10]:
        if (h.get("points") or 0) < 20:
            continue
        link = "https://news.ycombinator.com/item?id=%s" % h["objectID"]
        out.append(_cand("hn", "measured_data", "Hacker News points of the story '%s'" % h.get("title"),
                         int(h.get("points") or 0), "points", link,
                         "points: %s, comments: %s" % (h.get("points"), h.get("num_comments")),
                         "Hacker News", raw, sha, query, "hn_points:%s" % h["objectID"],
                         date=(h.get("created_at") or "")[:7], criteria=["demand", "competition"]))
    added = candidates.add(idea, out)
    if comments:
        curl = ("https://hn.algolia.com/api/v1/search?query=%s&tags=comment&numericFilters=created_at_i>%d&hitsPerPage=40"
                % (_q(query), since))
        cdata, craw, csha = fetch.get(idea, "hn", curl, query="comments:%s" % query)
        items = [{"source": "hn-comments", "source_type": "forum", "publisher": "Hacker News",
                  "url": "https://news.ycombinator.com/item?id=%s" % c["objectID"],
                  "about": c.get("story_title") or "", "rating": None, "date": (c.get("created_at") or "")[:10],
                  "text": _strip(c.get("comment_text"))[:1200], "raw_file": craw, "raw_sha256": csha}
                 for c in cdata.get("hits", [])]
        _add_voice(idea, items)
    return added


def github(idea, query, limit=10):
    """GitHub repositories: how many exist for a topic, and the most starred (open-source competitors)."""
    url = "https://api.github.com/search/repositories?q=%s&sort=stars&order=desc&per_page=%d" % (_q(query), limit)
    headers = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer %s" % os.environ["GITHUB_TOKEN"]
    data, raw, sha = fetch.get(idea, "github", url, query=query, headers=headers)
    human = "https://github.com/search?q=%s&type=repositories&s=stars" % _q(query)
    out = [_cand("github", "measured_data", "GitHub repositories matching '%s'" % query, int(data.get("total_count", 0)),
                 "repositories", human, "total_count: %s" % data.get("total_count", 0), "GitHub", raw, sha, query,
                 "gh_repos:%s" % query, criteria=["competition", "feasibility"])]
    comps = []
    for r in data.get("items", []):
        out.append(_cand("github", "measured_data", "GitHub stars of %s (%s)" % (r["full_name"], (r.get("description") or "")[:80]),
                         int(r.get("stargazers_count", 0)), "stars", r["html_url"],
                         "stargazers_count: %s, pushed_at: %s" % (r.get("stargazers_count"), r.get("pushed_at")),
                         "GitHub", raw, sha, query, "gh_stars:%s" % r["full_name"],
                         date=(r.get("pushed_at") or "")[:7], criteria=["competition"]))
        comps.append({"key": "github:%s" % r["full_name"], "name": r["full_name"], "url": r["html_url"],
                      "store": "github", "stars": r.get("stargazers_count"), "pushed_at": r.get("pushed_at")})
    _merge_list(idea, "competitors.json", comps, "key")
    return candidates.add(idea, out)


def stackexchange(idea, query, site="stackoverflow"):
    """Stack Exchange: number of questions on a topic and the top ones (technical pain points)."""
    key = os.environ.get("STACKEXCHANGE_KEY")
    base = "https://api.stackexchange.com/2.3/search/advanced?order=desc&sort=votes&q=%s&site=%s" % (_q(query), site)
    if key:
        base += "&key=%s" % key
    data, raw, sha = fetch.get(idea, "stackexchange", base + "&filter=total", query="total:%s:%s" % (site, query))
    human = "https://%s.com/search?q=%s" % (site, _q(query))
    out = [_cand("stackexchange", "measured_data", "Questions on %s matching '%s'" % (site, query),
                 int(data.get("total", 0)), "questions", human, "total: %s" % data.get("total", 0),
                 "Stack Exchange", raw, sha, query, "se_total:%s:%s" % (site, query), criteria=["problem", "demand"])]
    idata, iraw, isha = fetch.get(idea, "stackexchange", base + "&pagesize=20", query="items:%s:%s" % (site, query))
    items = [{"source": "stackexchange", "source_type": "forum", "publisher": "Stack Exchange (%s)" % site,
              "url": q.get("link"), "about": site, "rating": None,
              "date": datetime.datetime.fromtimestamp(q.get("creation_date", 0), datetime.timezone.utc).strftime("%Y-%m-%d"),
              "text": "%s (score %s, %s views)" % (_strip(q.get("title")), q.get("score"), q.get("view_count")),
              "raw_file": iraw, "raw_sha256": isha} for q in idata.get("items", [])]
    _add_voice(idea, items)
    return candidates.add(idea, out)


def domain(idea, name):
    """A competitor's domain: registration date (RDAP) and Tranco popularity rank."""
    out = []
    try:
        data, raw, sha = fetch.get(idea, "rdap", "https://rdap.org/domain/%s" % name, query=name)
        reg = next((e["eventDate"] for e in data.get("events", []) if e.get("eventAction") == "registration"), None)
        if reg:
            age = round((TODAY() - datetime.date.fromisoformat(reg[:10])).days / 365.25, 1)
            out.append(_cand("rdap", "measured_data", "Age in years of the domain %s (registered %s)" % (name, reg[:10]),
                             age, "years", "https://rdap.org/domain/%s" % name, "registration: %s" % reg,
                             "RDAP registry", raw, sha, name, "domain_age:%s" % name, criteria=["competition"]))
    except fetch.FetchError:
        pass
    try:
        data, raw, sha = fetch.get(idea, "tranco", "https://tranco-list.eu/api/ranks/domain/%s" % name, query=name)
        ranks = data.get("ranks") or []
        if ranks:
            r = ranks[0]
            out.append(_cand("tranco", "measured_index", "Tranco popularity rank of %s on %s (lower is bigger)" % (name, r["date"]),
                             int(r["rank"]), "rank", "https://tranco-list.eu/query", "rank: %s (%s)" % (r["rank"], r["date"]),
                             "Tranco list", raw, sha, name, "tranco:%s" % name, date=r["date"][:7],
                             criteria=["competition"]))
    except fetch.FetchError:
        pass
    if not out:
        raise IdeaError("no domain data for %s (unreachable, or not a registered domain)" % name)
    return candidates.add(idea, out)


# ── market ──────────────────────────────────────────────────────────────────────
WB_PRESETS = {"population": "SP.POP.TOTL", "internet_users_pct": "IT.NET.USER.ZS",
              "population_15_64_pct": "SP.POP.1564.TO.ZS", "gdp_per_capita_usd": "NY.GDP.PCAP.CD"}


def worldbank(idea, countries, indicator):
    """World Bank indicator, latest value per country (official statistics)."""
    ind = WB_PRESETS.get(indicator, indicator)
    url = "https://api.worldbank.org/v2/country/%s/indicator/%s?format=json&mrnev=1&per_page=300" % (
        ";".join(c.lower() for c in countries), ind)
    data, raw, sha = fetch.get(idea, "worldbank", url, query="%s:%s" % (ind, ",".join(countries)))
    if not isinstance(data, list) or len(data) < 2 or not data[1]:
        raise IdeaError("World Bank returned no data for %s (check indicator and country codes)" % ind)
    out = []
    for row in data[1]:
        if row.get("value") is None:
            continue
        name, iso = row["country"]["value"], row.get("countryiso3code") or row["country"]["id"]
        out.append(_cand("worldbank", "official_stat", "%s, %s (%s)" % (row["indicator"]["value"], name, row["date"]),
                         float(row["value"]), "percent" if ind.endswith(".ZS") else "",
                         "https://data.worldbank.org/indicator/%s?locations=%s" % (ind, row["country"]["id"]),
                         "%s %s: %s" % (iso, row["date"], row["value"]), "World Bank", raw, sha, ind,
                         "wb:%s:%s" % (ind, iso), date=row["date"], criteria=["market"]))
    return candidates.add(idea, out)


def jsonstat_rows(data, limit=None):
    """Decode a JSON-stat 2.0 dataset into rows of {dim: label, ..., value}."""
    ids, sizes = data["id"], data["size"]
    dims = data["dimension"]
    pos_to_code = []
    for d in ids:
        idx = dims[d]["category"]["index"]
        if isinstance(idx, list):
            idx = {c: i for i, c in enumerate(idx)}
        labels = dims[d]["category"].get("label", {})
        inv = {v: (k, labels.get(k, k)) for k, v in idx.items()}
        pos_to_code.append(inv)
    values = data.get("value", {})
    if isinstance(values, list):
        values = {str(i): v for i, v in enumerate(values) if v is not None}
    rows = []
    for flat, v in sorted(values.items(), key=lambda kv: int(kv[0])):
        n, coords = int(flat), []
        for size in reversed(sizes):
            coords.append(n % size)
            n //= size
        coords.reverse()
        row = {"value": v}
        for d, inv, c in zip(ids, pos_to_code, coords):
            row[d] = inv[c][0]
            row[d + "_label"] = inv[c][1]
        rows.append(row)
        if limit and len(rows) >= limit:
            break
    return rows


def eurostat(idea, dataset, filters, unit_label=""):
    """Eurostat dataset (JSON-stat) with filters, e.g. {"geo": ["IT","DE"], "nace_r2": ["M"], "size_emp": ["TOTAL"]}."""
    qs = [("format", "JSON"), ("lang", "EN")]
    for k, vs in sorted(filters.items()):
        for v in (vs if isinstance(vs, list) else [vs]):
            qs.append((k, v))
    url = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/%s?%s" % (dataset, urllib.parse.urlencode(qs))
    data, raw, sha = fetch.get(idea, "eurostat", url, query="%s %s" % (dataset, filters))
    if "error" in data:
        raise IdeaError("Eurostat: %s" % data["error"])
    rows = jsonstat_rows(data, limit=60)
    if not rows:
        raise IdeaError("Eurostat returned no values for %s with %s (check the codes)" % (dataset, filters))
    title = data.get("label", dataset)
    vary = [d for d in data["id"] if len(data["dimension"][d]["category"]["index"]) > 1]
    out = []
    for r in rows:
        desc = ", ".join("%s" % r[d + "_label"] for d in data["id"] if d not in ("freq",))
        key = ":".join(str(r[d]) for d in data["id"])
        out.append(_cand("eurostat", "official_stat", "%s: %s" % (title, desc), float(r["value"]), unit_label,
                         "https://ec.europa.eu/eurostat/databrowser/view/%s/default/table" % dataset,
                         "%s = %s" % (", ".join("%s=%s" % (d, r[d]) for d in data["id"]), r["value"]),
                         "Eurostat", raw, sha, dataset, "eurostat:%s:%s" % (dataset, key),
                         date=str(r.get("time", ""))[:7] or None, criteria=["market"]))
    if len(rows) >= 60:
        fetch.log_error(idea, "eurostat", dataset, "more than 60 values: only the first 60 kept, narrow the filters (%s)"
                        % ", ".join(vary))
    return candidates.add(idea, out)


def youtube(idea, query, months=24):
    """YouTube (needs YOUTUBE_API_KEY): view counts of the top videos on a topic, and their comments as voice."""
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        fetch.log_skip(idea, "youtube", query, "set YOUTUBE_API_KEY (free, Google Cloud console) to enable YouTube")
        raise IdeaError("YouTube needs a free API key in the env var YOUTUBE_API_KEY")
    after = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30 * months)).strftime("%Y-%m-%dT00:00:00Z")
    s, _, _ = fetch.get(idea, "youtube", "https://www.googleapis.com/youtube/v3/search?part=snippet&type=video&order=viewCount"
                        "&maxResults=10&q=%s&publishedAfter=%s&key=%s" % (_q(query), after, key), query="search:%s" % query)
    ids = [i["id"]["videoId"] for i in s.get("items", []) if i.get("id", {}).get("videoId")]
    if not ids:
        return []
    v, raw, sha = fetch.get(idea, "youtube", "https://www.googleapis.com/youtube/v3/videos?part=statistics,snippet&id=%s&key=%s"
                            % (",".join(ids), key), query="videos:%s" % query)
    out = []
    for it in v.get("items", []):
        st, sn = it.get("statistics", {}), it.get("snippet", {})
        link = "https://www.youtube.com/watch?v=%s" % it["id"]
        out.append(_cand("youtube", "measured_data", "YouTube views of '%s' (%s, %s)" % (
            sn.get("title"), sn.get("channelTitle"), (sn.get("publishedAt") or "")[:10]), int(st.get("viewCount", 0)),
            "views", link, "viewCount: %s, commentCount: %s" % (st.get("viewCount"), st.get("commentCount")),
            "YouTube", raw, sha, query, "yt_views:%s" % it["id"], date=(sn.get("publishedAt") or "")[:7],
            criteria=["demand"]))
    for vid in ids[:3]:
        try:
            c, craw, csha = fetch.get(idea, "youtube", "https://www.googleapis.com/youtube/v3/commentThreads?part=snippet"
                                      "&maxResults=50&order=relevance&videoId=%s&key=%s" % (vid, key), query="comments:%s" % vid)
        except fetch.FetchError:
            continue
        items = []
        for t in c.get("items", []):
            top = t["snippet"]["topLevelComment"]["snippet"]
            items.append({"source": "youtube-comments", "source_type": "forum", "publisher": "YouTube",
                          "url": "https://www.youtube.com/watch?v=%s&lc=%s" % (vid, t["id"]), "about": vid,
                          "rating": None, "date": (top.get("publishedAt") or "")[:10],
                          "text": _strip(top.get("textOriginal") or top.get("textDisplay"))[:1200],
                          "raw_file": craw, "raw_sha256": csha})
        _add_voice(idea, items)
    return candidates.add(idea, out)


SOURCES = {
    "autocomplete": "keyword discovery (Google, YouTube suggestions)",
    "wikipedia": "monthly pageviews of a topic article and their trend",
    "trends": "Google Trends growth and relative size (optional: pip install trendspy)",
    "itunes": "App Store apps, prices and rating counts",
    "appreviews": "App Store reviews of one app (voice)",
    "gplay": "Google Play apps and install buckets (optional: pip install google-play-scraper)",
    "hn": "Hacker News stories and comments",
    "github": "GitHub repositories and stars (optional GITHUB_TOKEN)",
    "stackexchange": "Stack Exchange question counts and titles (optional STACKEXCHANGE_KEY)",
    "domain": "competitor domain age (RDAP) and Tranco rank",
    "worldbank": "World Bank indicators per country",
    "eurostat": "Eurostat datasets (enterprises by sector and size, ICT usage)",
    "youtube": "YouTube views and comments (needs YOUTUBE_API_KEY)",
}
