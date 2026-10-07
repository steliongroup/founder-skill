import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from _load import SKILLS_DIR

LIB = os.path.join(SKILLS_DIR, "idea-lib")
sys.path.insert(0, LIB)

from ideakit import baserates, economics, evidence, intake, prereg, scoring, textmatch, verdict  # noqa: E402
from ideakit.common import Idea, IdeaError, read_json, read_jsonl, write_json  # noqa: E402

SAMPLE = os.path.join(LIB, "examples", "sample-idea")
IK = os.path.join(LIB, "ik.py")


class Text(unittest.TestCase):
    def test_numbers_in_both_locales_and_suffixes(self):
        self.assertTrue(textmatch.contains_number("a share of 3.8% of pages", 0.038))
        self.assertTrue(textmatch.contains_number("a share of 3.8% of pages", 3.8))
        self.assertTrue(textmatch.contains_number("il 3,8% delle pagine", 0.038))
        self.assertTrue(textmatch.contains_number("1,200 freelancers", 1200))
        self.assertTrue(textmatch.contains_number("1.200 freelance", 1200))
        self.assertTrue(textmatch.contains_number("raised $16 million", 16e6))
        self.assertTrue(textmatch.contains_number("15 € per month", 15))
        self.assertFalse(textmatch.contains_number("version 2025a", 2025))
        self.assertFalse(textmatch.contains_number("about 4%", 0.038))

    def test_quotes_survive_markup_and_typography(self):
        page = textmatch.html_to_text("<p>It’s <b>62%</b> of&nbsp;all</p><script>var hidden='secret';</script>")
        self.assertEqual(textmatch.find_quote("It's 62% of all", page), "exact")
        self.assertIsNone(textmatch.find_quote("secret", page))
        page2 = textmatch.normalize("I spend every Friday afternoon chasing clients who haven't paid. 62% of them pay late.")
        self.assertEqual(textmatch.find_quote("I spend every Friday afternoon chasing clients who have not paid", page2),
                         "fuzzy")
        # an edited number inside an otherwise copied sentence must not pass
        page3 = textmatch.normalize("Our survey found that 62% of respondents had at least one invoice paid late in 2025")
        self.assertIsNone(textmatch.find_quote("Our survey found that 71% of respondents had at least one invoice paid late in 2025", page3))
        self.assertIsNone(textmatch.find_quote("an entirely different sentence about pricing", page))


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.d = os.path.join(self.root, "sample-idea")
        shutil.copytree(SAMPLE, self.d)
        self.idea = Idea(self.d)

    def tearDown(self):
        shutil.rmtree(self.root)

    def facts(self):
        with open(os.path.join(self.d, "facts.json"), encoding="utf-8") as fh:
            return json.load(fh)


class Intake(Base):
    def test_sample_sheet_is_clean(self):
        self.assertEqual(intake.lint(self.d), [])

    def test_hype_and_first_person_are_refused(self):
        s = read_json(self.idea.idea)
        s["one_liner"] = "My revolutionary app, the best for everyone."
        write_json(self.idea.idea, s)
        errs = " ".join(intake.lint(self.d))
        for word in ("revolutionary", "best", "everyone", "My"):
            self.assertIn(word, errs)

    def test_italian_articles_are_not_first_person(self):
        self.assertEqual(intake.lint_text("I documenti di tutti i giorni per i genitori"), [])

    def test_private_title_must_not_leak(self):
        s = read_json(self.idea.idea)
        s["solution"] = "Invoice reminder app that sends emails."
        write_json(self.idea.idea, s)
        self.assertTrue(any("private title" in e for e in intake.lint(self.d)))

    def test_claims_are_always_grade_d(self):
        with open(self.idea.claims, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": "C003", "text": "x", "type": "price", "grade": "B"}) + "\n")
        self.assertTrue(any("grade D" in e for e in intake.lint(self.d)))

    def test_new_creates_folder_with_codename(self):
        d, code = intake.new(self.root, "My Great Idea!")
        self.assertTrue(d.endswith("my-great-idea"))
        self.assertRegex(code, r"^IDEA-[0-9A-F]{4}$")
        self.assertEqual(read_json(os.path.join(d, "input", "private.json"))["codename"], code)
        with self.assertRaises(IdeaError):
            intake.new(self.root, "My Great Idea!")


class Prereg(Base):
    def test_freeze_once_then_detect_tampering(self):
        prereg.freeze(self.d, "quick")
        with self.assertRaises(IdeaError):
            prereg.freeze(self.d, "quick")
        reg = read_json(self.idea.prereg)
        reg["rubric"]["verdict_bands"]["go"] = 10
        write_json(self.idea.prereg, reg)
        with self.assertRaises(IdeaError):
            prereg.load(self.d)

    def test_goal_is_frozen_with_the_rubric(self):
        reg = prereg.freeze(self.d, "quick")
        self.assertEqual(reg["goal"], {"metric": "revenue", "month": 24, "value": 3000.0})
        reg = read_json(self.idea.prereg)
        reg["goal"]["value"] = 100
        write_json(self.idea.prereg, reg)
        with self.assertRaises(IdeaError):
            prereg.load(self.d)

    def test_default_goal_from_ideas_config(self):
        os.remove(os.path.join(self.d, "input", "goal.json"))
        write_json(os.path.join(self.root, "config.json"), {"default_goal": {"metric": "profit", "month": 12, "value": 500}})
        self.assertEqual(prereg.freeze(self.d, "quick")["goal"]["metric"], "profit")

    def test_new_run_archives_the_old_one(self):
        prereg.freeze(self.d, "quick")
        prereg.freeze(self.d, "full", new_run=True)
        self.assertEqual(read_json(self.idea.prereg)["mode"], "full")
        self.assertEqual(len(os.listdir(os.path.join(self.d, "runs"))), 1)


class Evidence(Base):
    def test_add_verify_and_grades(self):
        ids = evidence.add(self.idea, self.facts())
        self.assertEqual(ids, ["F001", "F002", "F003"])
        self.assertEqual([evidence.effective_grade(f) for f in evidence.load(self.idea)], ["D", "D", "D"])
        evidence.verify(self.idea, html_dir=os.path.join(self.d, "pages"))
        facts = evidence.load(self.idea)
        self.assertEqual([f["verify_status"] for f in facts], ["ok", "ok", "ok"])
        self.assertEqual([evidence.effective_grade(f) for f in facts], ["B", "A", "C"])

    def test_number_must_be_in_quote_and_quote_on_page(self):
        f = self.facts()[0]
        f["value"] = 0.71
        evidence.add(self.idea, [f])
        evidence.verify(self.idea, html_dir=os.path.join(self.d, "pages"))
        self.assertEqual(evidence.load(self.idea)[0]["verify_status"], "value_not_in_quote")
        g = dict(self.facts()[1], quote="Pro plan: 9 euro per month")
        evidence.add(self.idea, [g])
        evidence.verify(self.idea, ids=["F002"], html_dir=os.path.join(self.d, "pages"))
        self.assertEqual(evidence.load(self.idea)[1]["verify_status"], "quote_not_found")

    def test_unreachable_page_stays_unverified(self):
        evidence.add(self.idea, self.facts()[:1])

        def boom(url):
            raise OSError("network blocked")
        evidence.verify(self.idea, fetch=boom)
        f = evidence.load(self.idea)[0]
        self.assertFalse(f["verified"])
        self.assertTrue(f["verify_status"].startswith("unreachable"))

    def test_stale_source_loses_a_grade(self):
        import datetime
        f = dict(self.facts()[0], date="2019-01")
        evidence.add(self.idea, [f])
        fact = evidence.load(self.idea)[0]
        evidence.verify_fact(fact, html_dir=os.path.join(self.d, "pages"), today=datetime.date(2026, 10, 7))
        self.assertTrue(fact["stale"])
        self.assertEqual(evidence.effective_grade(fact), "C")

    def test_bad_facts_are_refused(self):
        f = self.facts()[0]
        for broken in (dict(f, url="ftp://x"), dict(f, source_type="gossip"), dict(f, value="many"),
                       dict(f, grade="D"), dict(f, grade="A")):
            with self.assertRaises(IdeaError):
                evidence.add(self.idea, [broken])
        evidence.add(self.idea, [dict(f, grade="A", grade_reason="national statistics office survey")])
        with self.assertRaises(IdeaError):
            evidence.add(self.idea, [f])  # duplicate quote from the same url

    def test_triangulation_needs_two_publishers(self):
        a = self.facts()[0]
        b = dict(a, url="https://example.org/other", publisher="Another Institute")
        evidence.add(self.idea, [a, b])
        evidence.verify(self.idea, html_dir=os.path.join(self.d, "pages"))
        t = evidence.triangulation(evidence.load(self.idea))
        self.assertFalse(t["late_payment_share"]["triangulated"])  # second page not saved: unverified
        pages = os.path.join(self.d, "pages")
        shutil.copy(os.path.join(pages, "F001.html"), os.path.join(pages, "F002.html"))
        evidence.verify(self.idea, ids=["F002"], html_dir=pages)
        t = evidence.triangulation(evidence.load(self.idea))
        self.assertTrue(t["late_payment_share"]["triangulated"])


class BaseRates(unittest.TestCase):
    def test_table_is_complete_and_unverified_counts_as_c(self):
        table = baserates.load()
        ids = [r["id"] for r in table["rates"]]
        self.assertEqual(len(ids), len(set(ids)))
        for r in table["rates"]:
            for k in ("metric", "unit", "value", "range", "source", "url", "year", "declared_grade", "match_text"):
                self.assertIn(k, r, r["id"])
            self.assertTrue(r["range"]["low"] <= r["range"]["mode"] <= r["range"]["high"], r["id"])
            if not r.get("verified"):
                self.assertEqual(baserates.grade(r), "C")

    def test_verify_uses_match_text_and_keywords(self):
        tmp = tempfile.mkdtemp()
        try:
            table = baserates.load()
            path = os.path.join(tmp, "baserates.json")
            write_json(path, table)
            with open(os.path.join(tmp, "landing_signup_saas.html"), "w") as fh:
                fh.write("<p>The median SaaS landing page conversion rate is 3.8%.</p>")
            os.environ["IDEAKIT_BASERATES"] = path
            try:
                res = dict(baserates.verify(ids=["landing_signup_saas", "landing_signup_all"], html_dir=tmp,
                                            fetch=lambda u: "<p>nothing here</p>"))
                self.assertEqual(res["landing_signup_saas"], "ok")
                self.assertIn("not on page", res["landing_signup_all"])
                self.assertEqual(baserates.grade(baserates.get("landing_signup_saas")), "B")
            finally:
                del os.environ["IDEAKIT_BASERATES"]
        finally:
            shutil.rmtree(tmp)


class Economics(Base):
    def setUp(self):
        super().setUp()
        prereg.freeze(self.d, "quick")
        evidence.add(self.idea, self.facts())

    def test_deterministic_with_seed_and_clamps_optimism(self):
        a = economics.run(self.d, runs=500, seed=3)
        b = economics.run(self.d, runs=500, seed=3)
        self.assertEqual(a["distribution"], b["distribution"])
        adj = {x["input"]: x for x in a["adjustments"]}
        self.assertIn("visitor_to_signup", adj)  # estimate of 10% above the 8% ceiling of the prior
        self.assertEqual(a["inputs"]["visitor_to_signup"]["mode"], 0.08)
        self.assertTrue(os.path.exists(os.path.join(self.d, "economics.md")))

    def test_key_inputs_must_name_their_base_rate(self):
        a = read_json(self.idea.assumptions)
        del a["inputs"]["monthly_churn"]["prior"]
        write_json(self.idea.assumptions, a)
        with self.assertRaises(IdeaError):
            economics.run(self.d, runs=10)
        a["inputs"]["monthly_churn"]["prior"] = "trial_to_paid_card"  # a prior for a different quantity
        write_json(self.idea.assumptions, a)
        with self.assertRaises(IdeaError):
            economics.run(self.d, runs=10)
        a["model"] = "one_time"  # one-off sales have no churn, so no prior is required
        del a["inputs"]["monthly_churn"]["prior"]
        write_json(self.idea.assumptions, a)
        economics.run(self.d, runs=10)

    def test_optimistic_churn_estimate_is_clamped(self):
        a = read_json(self.idea.assumptions)
        a["inputs"]["monthly_churn"] = {"low": 0.0, "mode": 0.01, "high": 0.02, "source": "estimate",
                                        "prior": "saas_monthly_churn_early"}
        write_json(self.idea.assumptions, a)
        r = economics.run(self.d, runs=50)
        self.assertEqual(r["inputs"]["monthly_churn"], {"low": 0.03, "mode": 0.03, "high": 0.03})

    def test_goal_cannot_be_moved_in_assumptions(self):
        a = read_json(self.idea.assumptions)
        a["goal"] = {"metric": "revenue", "month": 24, "value": 500}
        write_json(self.idea.assumptions, a)
        with self.assertRaises(IdeaError):
            economics.run(self.d, runs=10)

    def test_economics_needs_prereg(self):
        os.remove(self.idea.prereg)
        with self.assertRaises(IdeaError):
            economics.run(self.d, runs=10)

    def test_strong_evidence_is_not_clamped(self):
        a = read_json(self.idea.assumptions)
        a["inputs"]["visitor_to_signup"]["source"] = "fact:F002"  # grade A once verified
        write_json(self.idea.assumptions, a)
        evidence.verify(self.idea, html_dir=os.path.join(self.d, "pages"))
        r = economics.run(self.d, runs=200)
        self.assertEqual(r["inputs"]["visitor_to_signup"]["mode"], 0.1)

    def test_simulation_moves_the_right_way(self):
        x = {k: v["mode"] for k, v in economics.resolve(read_json(self.idea.assumptions), [], baserates.load())[1].items()}
        _, base = economics.simulate("subscription", x, 24)
        _, churny = economics.simulate("subscription", dict(x, monthly_churn=0.2), 24)
        _, pricey = economics.simulate("subscription", dict(x, price=x["price"] * 2), 24)
        self.assertLess(churny["revenue_m24"], base["revenue_m24"])
        self.assertGreater(pricey["revenue_m24"], base["revenue_m24"])
        self.assertAlmostEqual(base["ltv"], base["contribution"] / x["monthly_churn"])
        _, onetime = economics.simulate("one_time", x, 24)
        self.assertAlmostEqual(onetime["ltv"], onetime["contribution"])

    def test_missing_and_bad_inputs_are_refused(self):
        a = read_json(self.idea.assumptions)
        bad = json.loads(json.dumps(a))
        del bad["inputs"]["monthly_churn"]
        bad2 = json.loads(json.dumps(a))
        bad2["inputs"]["signup_to_paid"]["high"] = 4  # 400%, not a fraction
        bad3 = json.loads(json.dumps(a))
        bad3["inputs"]["price"]["source"] = "fact:F999"
        bad4 = json.loads(json.dumps(a))
        bad4["inputs"]["price"]["low"] = 20  # low above mode
        for b in (bad, bad2, bad3, bad4):
            write_json(self.idea.assumptions, b)
            with self.assertRaises(IdeaError):
                economics.run(self.d, runs=10)


class Judge(Base):
    def setUp(self):
        super().setUp()
        prereg.freeze(self.d, "quick")
        evidence.add(self.idea, self.facts())
        evidence.verify(self.idea, html_dir=os.path.join(self.d, "pages"))

    def test_brief_is_blind(self):
        with open(scoring.brief(self.d), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("IDEA-7C2E", text)
        self.assertIn("F001", text)
        for leak in ("Invoice reminder app", "happily pay", "C002", "founder", "unit_economics"):
            self.assertNotIn(leak, text)

    def scores(self, change=None):
        s = read_json(os.path.join(self.d, "judge", "scores.example.json"))
        for row in s:
            if change and row["criterion"] in change:
                row.update(change[row["criterion"]])
        write_json(self.idea.scores, s)

    def test_caps(self):
        self.scores({"demand": {"level": 5, "fact_ids": []},
                     "competition": {"level": 5, "fact_ids": ["F003"]},
                     "willingness_to_pay": {"level": 5, "fact_ids": ["F002"]}})
        rows = {r["criterion"]: r for r in scoring.validate(self.d)}
        self.assertEqual(rows["demand"]["level"], 3)               # nothing cited
        self.assertEqual(rows["competition"]["level"], 3)          # only grade C cited
        self.assertEqual(rows["willingness_to_pay"]["level"], 4)   # one strong source cannot make a 5
        self.assertEqual(rows["problem"]["level"], 4)

    def test_invalid_scores_are_refused(self):
        for change in ({"problem": {"fact_ids": ["F404"]}}, {"problem": {"level": 7}}, {"problem": {"rationale": " "}}):
            self.scores(change)
            with self.assertRaises(IdeaError):
                scoring.validate(self.d)
        s = read_json(os.path.join(self.d, "judge", "scores.example.json"))[1:]
        write_json(self.idea.scores, s)
        with self.assertRaises(IdeaError):
            scoring.validate(self.d)


class Verdict(Base):
    def run_all(self, scores_change=None, assumptions_change=None):
        prereg.freeze(self.d, "quick")
        evidence.add(self.idea, self.facts())
        evidence.verify(self.idea, html_dir=os.path.join(self.d, "pages"))
        if assumptions_change:
            a = read_json(self.idea.assumptions)
            a["inputs"].update(assumptions_change)
            write_json(self.idea.assumptions, a)
        economics.run(self.d, runs=400)
        s = read_json(os.path.join(self.d, "judge", "scores.example.json"))
        for row in s:
            if scores_change and row["criterion"] in scores_change:
                row.update(scores_change[row["criterion"]])
        write_json(self.idea.scores, s)
        return verdict.compute(self.d)

    def test_incomplete_without_judge_or_economics(self):
        prereg.freeze(self.d, "quick")
        r = verdict.compute(self.d)
        self.assertEqual(r["verdict"], "INCOMPLETE")
        self.assertEqual(len(r["missing"]), 2)

    def test_sample_is_pivot_with_medium_confidence(self):
        r = self.run_all()
        self.assertEqual(r["verdict"], "PIVOT")
        self.assertEqual(r["confidence"], "media")
        self.assertEqual(r["weakest_criterion"], "unit_economics")
        self.assertEqual(r["next_experiment"]["id"], "presale")
        with open(os.path.join(self.d, "verdict.md"), encoding="utf-8") as fh:
            md = fh.read()
        self.assertIn("**Verdetto: PIVOT", md)
        self.assertIn("calcolato dal codice", md)

    def test_losing_money_per_customer_kills(self):
        r = self.run_all(assumptions_change={"variable_cost_paying": {"low": 20, "mode": 25, "high": 30, "source": "estimate"}})
        self.assertEqual(r["verdict"], "KILL")
        self.assertIn("negative_contribution", [t["id"] for t in r["triggered"]])

    def test_strong_evidence_against_the_problem_kills(self):
        r = self.run_all({"problem": {"level": 1, "fact_ids": ["F001"]}})
        self.assertEqual(r["verdict"], "KILL")
        self.assertIn("evidence_against", [t["id"] for t in r["triggered"]])

    def test_weak_evidence_against_does_not_kill(self):
        r = self.run_all({"problem": {"level": 1, "fact_ids": ["F003"]}})
        self.assertNotIn("evidence_against", [t["id"] for t in r["triggered"]])

    def test_without_strong_evidence_the_best_is_pivot(self):
        prereg.freeze(self.d, "quick")
        economics.run(self.d, runs=200)  # no facts at all: every input is C or D
        s = [{"criterion": k, "level": 5, "fact_ids": [], "rationale": "optimistic"} for k in
             ("problem", "demand", "market", "competition", "willingness_to_pay", "distribution", "feasibility")]
        write_json(self.idea.scores, s)
        r = verdict.compute(self.d)
        self.assertLessEqual(r["score"], 50)
        self.assertIn(r["verdict"], ("PIVOT", "KILL"))
        self.assertEqual(r["confidence"], "bassa")

    def test_high_score_without_strong_evidence_is_never_go(self):
        r = self.run_all({k: {"level": 5, "fact_ids": []} for k in
                          ("problem", "demand", "market", "competition", "willingness_to_pay", "distribution", "feasibility")})
        self.assertNotEqual(r["verdict"], "GO")
        self.assertIsNotNone(r["score_if_caps_lifted"])
        self.assertGreater(r["score_if_caps_lifted"], r["score"])


class Cli(Base):
    def ik(self, *args, stdin=None):
        p = subprocess.run([sys.executable, IK] + list(args), input=stdin, capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr

    def test_end_to_end(self):
        d = self.d
        self.assertEqual(self.ik("lint", d)[0], 0)
        self.assertEqual(self.ik("prereg", d, "--mode", "quick")[0], 0)
        with open(os.path.join(d, "facts.json")) as fh:
            self.assertEqual(self.ik("evidence", "add", d, stdin=fh.read())[0], 0)
        self.assertEqual(self.ik("evidence", "verify", d, "--html-dir", os.path.join(d, "pages"))[0], 0)
        self.assertEqual(self.ik("econ", d, "--runs", "300")[0], 0)
        self.assertEqual(self.ik("brief", d)[0], 0)
        shutil.copy(os.path.join(d, "judge", "scores.example.json"), os.path.join(d, "judge", "scores.json"))
        code, out = self.ik("verdict", d)
        self.assertEqual(code, 0, out)
        self.assertIn("PIVOT", out)
        code, out = self.ik("status", d)
        self.assertIn("done", out)

    def test_errors_exit_2_with_a_message(self):
        code, out = self.ik("econ", os.path.join(self.root, "nope"))
        self.assertEqual(code, 2)
        self.assertIn("error:", out)


if __name__ == "__main__":
    unittest.main()
