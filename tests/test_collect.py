import json
import os
import shutil
import sys
import tempfile
import types
import unittest

from _load import ROOT, SKILLS_DIR

LIB = os.path.join(SKILLS_DIR, "idea-lib")
sys.path.insert(0, LIB)

from ideakit import candidates, collect, evidence, fetch, market, prereg, scoring, verdict, voice, economics  # noqa: E402
from ideakit.common import Idea, IdeaError, read_json, read_jsonl, write_json  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures", "collect")
SAMPLE = os.path.join(LIB, "examples", "sample-idea")

ROUTES = [  # (substring of the URL, fixture file)
    ("suggestqueries.google.com", "autocomplete.json"),
    ("wikimedia.org/api/rest_v1/metrics/pageviews", "wikipedia.json"),
    ("itunes.apple.com/search", "itunes.json"),
    ("/rss/customerreviews/", "appreviews.json"),
    ("hn.algolia.com/api/v1/search?query=invoice+reminder&tags=story", "hn_stories.json"),
    ("hn.algolia.com/api/v1/search?query=invoice%20reminder&tags=story", "hn_stories.json"),
    ("tags=comment", "hn_comments.json"),
    ("api.github.com/search/repositories", "github.json"),
    ("filter=total", "se_total.json"),
    ("api.stackexchange.com", "se_items.json"),
    ("rdap.org/domain/", "rdap.json"),
    ("tranco-list.eu/api/ranks/domain/", "tranco.json"),
    ("api.worldbank.org", "worldbank.json"),
    ("ec.europa.eu/eurostat", "eurostat.json"),
]


class FakeNet:
    def __init__(self, fail=()):
        self.calls = []
        self.fail = fail

    def __call__(self, url, headers, timeout):
        self.calls.append(url)
        for bad in self.fail:
            if bad in url:
                raise fetch.FetchError("HTTP 403 from test")
        for sub, name in ROUTES:
            if sub in url:
                with open(os.path.join(FIX, name), "rb") as fh:
                    return 200, fh.read()
        raise fetch.FetchError("no fixture for %s" % url)


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.d = os.path.join(self.root, "sample-idea")
        shutil.copytree(SAMPLE, self.d)
        self.idea = Idea(self.d)
        prereg.freeze(self.d, "full")
        self.net = FakeNet()
        self._get, self._sleep = fetch.HTTP_GET, fetch.SLEEP
        fetch.HTTP_GET, fetch.SLEEP = self.net, (lambda s: None)

    def tearDown(self):
        fetch.HTTP_GET, fetch.SLEEP = self._get, self._sleep
        shutil.rmtree(self.root)

    def cands(self):
        return candidates.load(self.idea)


class Fetching(Base):
    def test_cache_and_log_and_no_keys_stored(self):
        url = "https://api.github.com/search/repositories?q=x&key=SECRET123"
        a = fetch.get(self.idea, "github", url, query="x")
        b = fetch.get(self.idea, "github", url, query="x")
        self.assertEqual(len(self.net.calls), 1)  # second call from cache
        self.assertEqual(a[2], b[2])
        raw_dir = os.path.join(self.d, "data", "raw")
        for name in os.listdir(raw_dir):
            with open(os.path.join(raw_dir, name), "rb") as fh:
                self.assertNotIn(b"SECRET123", fh.read())
        with open(os.path.join(self.d, "data", "collect-log.jsonl"), "rb") as fh:
            self.assertNotIn(b"SECRET123", fh.read())

    def test_gzip_is_decoded(self):
        import gzip
        fetch.HTTP_GET = self._get

        class Resp:
            status = 200
            headers = {"Content-Encoding": "gzip"}

            def read(self, n):
                return gzip.compress(b'{"total": 3}')

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        import urllib.request
        orig = urllib.request.urlopen
        urllib.request.urlopen = lambda req, timeout: Resp()
        try:
            status, body = fetch._http_get("https://x.example/", {}, 5)
        finally:
            urllib.request.urlopen = orig
        self.assertEqual(json.loads(body), {"total": 3})


class Collectors(Base):
    def test_wikipedia(self):
        ids = collect.wikipedia(self.idea, "Invoice", "en")
        c = {x["id"]: x for x in self.cands()}
        avg, change = c[ids[0]], c[ids[1]]
        self.assertEqual(avg["value"], round(sum(1000 + 10 * i for i in range(12, 24)) / 12.0))
        self.assertEqual(change["value"], round((sum(1000 + 10 * i for i in range(12, 24)) - sum(1000 + 10 * i for i in range(12)))
                                                / float(sum(1000 + 10 * i for i in range(12))), 3))
        self.assertEqual(avg["source_type"], "measured_data")

    def test_itunes_and_reviews(self):
        ids = collect.itunes(self.idea, "invoice reminder", "it")
        vals = {c["claim"]: c["value"] for c in self.cands()}
        self.assertIn(1834, vals.values())
        self.assertEqual(len(ids), 4)  # rating count and price for 2 apps
        self.assertEqual(len(read_json(self.idea.p("data", "competitors.json"))["items"]), 2)
        n = collect.appreviews(self.idea, "111", "it", pages=1)
        self.assertEqual(n, 2)
        low = voice.listing(self.idea, max_rating=3)
        self.assertEqual(len(low), 1)
        self.assertIn("15 euro a month is too much", low[0]["text"])

    def test_hn_github_stackexchange(self):
        collect.hn(self.idea, "invoice reminder")
        collect.github(self.idea, "invoice reminder")
        collect.stackexchange(self.idea, "invoice reminder")
        vals = {c["claim_key"]: c["value"] for c in self.cands()}
        self.assertEqual(vals["hn_stories:invoice reminder:24"], 37)
        self.assertEqual(vals["hn_points:4001"], 180)
        self.assertNotIn("hn_points:4002", vals)  # under 20 points
        self.assertEqual(vals["gh_repos:invoice reminder"], 64)
        self.assertEqual(vals["se_total:stackoverflow:invoice reminder"], 412)
        texts = [v["text"] for v in voice.load(self.idea)]
        self.assertIn("Chasing clients is the worst part of freelancing.", texts)
        self.assertTrue(any("& it works" in t for t in texts))

    def test_domain_worldbank_eurostat(self):
        collect.domain(self.idea, "chaser.example")
        collect.worldbank(self.idea, ["IT", "DE"], "population")
        collect.eurostat(self.idea, "sbs_sc_ovw", {"geo": ["IT", "DE"], "nace_r2": ["M"]}, "enterprises")
        c = {x["claim_key"]: x for x in self.cands()}
        self.assertEqual(c["tranco:chaser.example"]["value"], 48211)
        self.assertIn("domain_age:chaser.example", c)
        self.assertEqual(c["wb:SP.POP.TOTL:ITA"]["value"], 58900000.0)
        self.assertNotIn("wb:SP.POP.TOTL:DEU", c)  # no value: nothing invented
        it = [x for k, x in c.items() if k.startswith("eurostat:") and ":IT:" in k][0]
        self.assertEqual(it["value"], 701000.0)
        self.assertEqual(it["source_type"], "official_stat")

    def test_jsonstat_decoding_order(self):
        data = read_json(os.path.join(FIX, "eurostat.json"))
        rows = collect.jsonstat_rows(data)
        self.assertEqual([(r["geo"], r["value"]) for r in rows], [("DE", 512000), ("IT", 701000)])

    def test_autocomplete_is_discovery_only(self):
        out = collect.autocomplete(self.idea, "invoice reminder")
        self.assertIn("invoice reminder app", out["google"])
        self.assertEqual(self.cands(), [])

    def test_unreachable_source_is_logged_not_invented(self):
        fetch.HTTP_GET = FakeNet(fail=("api.github.com",))
        with self.assertRaises(IdeaError):
            collect.github(self.idea, "invoice reminder")
        self.assertEqual(self.cands(), [])
        log = fetch.log_entries(self.idea)
        self.assertEqual(log[-1]["status"], "error")

    def test_optional_sources_without_package_or_key(self):
        saved = sys.modules.get("trendspy")
        sys.modules["trendspy"] = None  # makes "import trendspy" fail
        try:
            with self.assertRaises(IdeaError):
                collect.trends(self.idea, ["invoice reminder"])
        finally:
            if saved is None:
                del sys.modules["trendspy"]
            else:
                sys.modules["trendspy"] = saved
        os.environ.pop("YOUTUBE_API_KEY", None)
        with self.assertRaises(IdeaError):
            collect.youtube(self.idea, "invoice reminder")
        self.assertEqual([e["status"] for e in fetch.log_entries(self.idea)], ["skipped", "skipped"])

    def test_trends_with_a_fake_trendspy(self):
        class Col(list):
            def tolist(self):
                return list(self)

        class DF:
            columns = ["invoice reminder", "isPartial"]
            index = ["2021-%02d-01" % (i % 12 + 1) for i in range(60)]

            def __getitem__(self, k):
                return Col([10.0] * 12 + [20.0] * 36 + [30.0] * 12) if k == "invoice reminder" else Col([False] * 60)

        class Trends:
            def __init__(self, **kw):
                pass

            def interest_over_time(self, keywords, timeframe, geo):
                return DF()
        sys.modules["trendspy"] = types.SimpleNamespace(Trends=Trends)
        try:
            collect.trends(self.idea, ["invoice reminder"], "IT")
        finally:
            del sys.modules["trendspy"]
        c = {x["claim_key"]: x for x in self.cands()}
        self.assertEqual(c["trends_growth:IT:invoice reminder"]["value"], 2.0)  # 10 -> 30
        self.assertEqual(c["trends_growth:IT:invoice reminder"]["source_type"], "measured_index")

    def test_gplay_with_a_fake_package(self):
        def search(term, n_hits, lang, country):
            return [{"appId": "com.chaser", "title": "Chaser", "developer": "Chaser Ltd", "score": 4.2,
                     "installs": "100,000+", "price": 0, "free": True, "currency": "EUR", "genre": "Business"}]

        def reviews(app_id, lang, country, sort, count, filter_score_with):
            return [{"content": "Crashes when I add a client (%d)" % filter_score_with, "score": filter_score_with,
                     "at": "2026-09-01"}], None
        sys.modules["google_play_scraper"] = types.SimpleNamespace(Sort=types.SimpleNamespace(NEWEST=2),
                                                                   search=search, reviews=reviews)
        try:
            collect.gplay(self.idea, "invoice reminder", "it", "it", review_apps=1)
        finally:
            del sys.modules["google_play_scraper"]
        c = {x["claim_key"]: x for x in self.cands()}
        self.assertEqual(c["android_installs:it:com.chaser"]["value"], 100000)
        self.assertEqual(len(voice.listing(self.idea, max_rating=3, source="gplay-reviews")), 3)


class Review(Base):
    def test_promote_reject_and_verdict_refuses_pending(self):
        ids = collect.itunes(self.idea, "invoice reminder", "it")
        with self.assertRaises(IdeaError):
            candidates.review(self.idea, reject=[ids[0]])  # no reason
        candidates.review(self.idea, promote=[ids[0]], criteria=["competition"])
        candidates.review(self.idea, reject=ids[1:3], reason="different product category")
        with self.assertRaises(IdeaError):
            candidates.review(self.idea, promote=[ids[0]])  # already decided
        with self.assertRaises(IdeaError):
            verdict.compute(self.d)  # one candidate still pending
        candidates.review(self.idea, reject=[ids[3]], reason="not a competitor")
        facts = evidence.load(self.idea)
        self.assertEqual(len(facts), 1)
        f = facts[0]
        self.assertTrue(f["collected"] and f["verified"])
        self.assertEqual(evidence.effective_grade(f), "A")
        self.assertEqual(f["criteria"], ["competition"])

    def test_tampered_raw_data_loses_verification(self):
        ids = collect.github(self.idea, "invoice reminder")
        candidates.review(self.idea, promote=ids[:1])
        f = evidence.load(self.idea)[0]
        with open(os.path.join(self.d, f["raw_file"]), "ab") as fh:
            fh.write(b" ")
        evidence.verify(self.idea)
        f = evidence.load(self.idea)[0]
        self.assertFalse(f["verified"])
        self.assertEqual(evidence.effective_grade(f), "D")

    def test_voice_themes_and_promote(self):
        collect.hn(self.idea, "invoice reminder")
        collect.appreviews(self.idea, "111", "it", pages=1)
        items = voice.listing(self.idea, max_rating=3)
        tags = {"themes": {"price": "price too high for solo freelancers", "manual_ok": "manual emails are enough"},
                "tags": {v["id"]: [] for v in items}}
        with self.assertRaises(IdeaError):  # nothing tagged yet with known ids: first, a missing item
            write_json(voice.tags_path(self.idea), {"themes": tags["themes"], "tags": {}})
            voice.themes(self.idea)
        price_item = [v for v in items if "too much" in v["text"]][0]
        manual_item = [v for v in items if "polite email" in v["text"]][0]
        tags["tags"][price_item["id"]] = ["price"]
        tags["tags"][manual_item["id"]] = ["manual_ok"]
        write_json(voice.tags_path(self.idea), tags)
        new, snap = voice.themes(self.idea)
        self.assertEqual(snap["counts"], {"price": 1, "manual_ok": 1})
        self.assertEqual(snap["total"], len(items))
        self.assertEqual({c["source_type"] for c in self.cands() if c["source"] == "voice-themes"}, {"aggregator"})
        done = voice.promote(self.idea, [price_item["id"]])
        f = [x for x in evidence.load(self.idea) if x["id"] == done[0][1]][0]
        self.assertEqual(f["quote"], price_item["text"])
        self.assertEqual(evidence.effective_grade(f), "B")


class Market(Base):
    def test_sam_and_required_share(self):
        write_json(self.idea.p("market.json"), {"currency": "EUR", "segments": [
            {"name": "freelancers", "count": 400000, "reachable_share": 0.1, "adoption": 0.25, "price_annual": 144}]})
        r = market.run(self.d, runs=200)
        self.assertAlmostEqual(r["sam"]["p50"], 400000 * 0.1 * 0.25 * 144)
        self.assertAlmostEqual(r["required_share"]["p50"], 3000 * 12 / (400000 * 0.1 * 0.25 * 144))
        self.assertEqual(r["required_share"]["p_under_5pct"], 1.0)
        self.assertFalse(r["all_counts_strong"])
        with open(scoring.brief(self.d), encoding="utf-8") as fh:
            brief = fh.read()
        self.assertIn("Computed indicators", brief)
        self.assertIn("Share of that market needed", brief)

    def test_bad_market_is_refused(self):
        for seg in ({"name": "x", "count": 1, "reachable_share": 2, "adoption": 0.1, "price_annual": 1},
                    {"name": "x", "count": 1, "adoption": 0.1, "price_annual": 1}):
            write_json(self.idea.p("market.json"), {"segments": [seg]})
            with self.assertRaises(IdeaError):
                market.run(self.d, runs=10)


class VerdictSources(Base):
    def test_failed_sources_are_listed_in_the_verdict(self):
        fetch.HTTP_GET = FakeNet(fail=("api.github.com",))
        try:
            collect.github(self.idea, "invoice reminder")
        except IdeaError:
            pass
        with open(os.path.join(self.d, "facts.json")) as fh:
            evidence.add(self.idea, json.load(fh))
        evidence.verify(self.idea, html_dir=os.path.join(self.d, "pages"))
        economics.run(self.d, runs=100)
        write_json(self.idea.scores, read_json(os.path.join(self.d, "judge", "scores.example.json")))
        r = verdict.compute(self.d)
        self.assertEqual(r["sources"]["error"][0]["source"], "github")
        with open(os.path.join(self.d, "verdict.md"), encoding="utf-8") as fh:
            md = fh.read()
        self.assertIn("Fonti non raggiunte", md)


if __name__ == "__main__":
    unittest.main()
