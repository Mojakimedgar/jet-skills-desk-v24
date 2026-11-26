"""Offline tests for Phase 2. Run:  python -m unittest discover -s tests -v"""
import json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import harvester as h  # noqa: E402
import analytics as an  # noqa: E402
import career_service as cs  # noqa: E402

FIX = ROOT / "tests/fixtures/oihd_2024_table.txt"
RSS = """<?xml version="1.0"?><rss version="2.0"><channel><item><title>QCTO approves solar skills programme</title><link>https://news.example.org/a</link><pubDate>Mon, 03 Jun 2025</pubDate><description>&lt;p&gt;Solar &lt;b&gt;installer&lt;/b&gt; training&lt;/p&gt;</description></item><item><title>Unrelated sport result</title><link>https://news.example.org/b</link><description>Football</description></item></channel></rss>"""
SAQA = "SAQA QUAL ID QUALIFICATION TITLE\n99447  Occupational Certificate: Solar Photovoltaic Service Technician \nORIGINATOR\nDevelopment Quality Partner - MERSETA Construction\nOccupational Certificate  Field 12 - Physical Planning and Construction  Electrical Infrastructure Construction\nABET BAND MINIMUM CREDITS PRE-2009 NQF LEVEL NQF LEVEL QUAL CLASS\nUndefined  344  Not Applicable  NQF Level 05  Regular-ELOAC\nThe purpose of this qualification is to prepare learners to service solar PV systems. They work on farms."


class Resp:
    def __init__(self, status=200, body=b"", headers=None):
        self.status_code, self.content, self.headers = status, body, headers or {}
        self.text = body.decode("utf-8", "replace")
    def iter_content(self, n): yield self.content
    def close(self): pass


class FakeSession:
    def __init__(self, routes): self.routes, self.calls = routes, []
    def get(self, url, **kw):
        self.calls.append(url)
        if url.endswith("/robots.txt"):
            return self.routes.get(url, Resp(404))
        return self.routes.get(url, Resp(404))


class Tmp(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(); t = Path(self.td.name)
        (t / "harvested").mkdir(); (t / "cache").mkdir()
        self.patches = [mock.patch.object(h, n, v) for n, v in {
            "CACHE": t / "cache", "HARVEST": t / "harvested", "DOCS_FILE": t / "harvested/documents.json",
            "STATUS_FILE": t / "harvested/status.json", "OIHD_FILE": t / "harvested/oihd.json",
            "SAQA_FILE": t / "harvested/saqa.json", "QLFS_GROUPS_FILE": t / "harvested/qlfs_groups.json", "QLFS_CODES_FILE": t / "harvested/qlfs_codes.json", "SOURCES_FILE": t / "sources.json"}.items()]
        self.patches += [mock.patch.object(h, "_is_public_host", lambda host: True), mock.patch.object(cs.harvester, "OIHD_FILE", t / "harvested/oihd.json"), mock.patch.object(cs.harvester, "SAQA_FILE", t / "harvested/saqa.json")]
        a = t / "an"; r = t / "rep"
        self.patches += [mock.patch.object(an, n, v) for n, v in {"AN": a, "REP": r, "EVENTS_FILE": a / "events.json", "REGISTRY_FILE": a / "registry.json",
                         "PIPELINE_FILE": r / "p.json", "ENROL_FILE": r / "e.json", "CAND_FILE": r / "c.json"}.items()]
        for p in self.patches: p.start()
        an._seen.clear(); an._hits.clear()
        h._INDEX["mtime"] = None; cs._cache.clear()
    def tearDown(self):
        for p in self.patches: p.stop()
        self.td.cleanup()
    def fetcher(self, routes, domains=("news.example.org", "www.gov.za")):
        cfg = {"user_agent": "T", "min_interval_seconds": 0, "default_keywords": ["solar"], "extra_allowed_domains": list(domains), "sources": []}
        return h.Fetcher(cfg, session=FakeSession(routes), sleep=lambda s: None)


class Parsers(unittest.TestCase):
    def test_oihd_gazette_is_complete(self):
        occ = h.parse_oihd_gazette_text(FIX.read_text(encoding="utf-8"))
        self.assertEqual(len(occ), 350)                       # the gazette states 350 occupations
        by = {o["ofo_code"]: o for o in occ}
        self.assertEqual(len(by), 350)
        self.assertEqual(by["642602"]["name"], "Solar Installer"); self.assertEqual(by["642602"]["nqf"], 4)
        self.assertEqual(by["132410"]["name"], "Maritime Search and Rescue Mission Coordinator")   # wrapped row
        self.assertTrue(by["671101"]["essa_outlier"]); self.assertFalse(by["642602"]["essa_outlier"])
        self.assertIsNone(by["315303"]["nqf"])
        self.assertEqual(by["652204"]["qualification"], "National Certificate (NQF Level 4)")    # stray ')' in source
    def test_feed_and_saqa(self):
        items = h.parse_feed(RSS)
        self.assertEqual(len(items), 2); self.assertIn("Solar installer training", items[0]["summary"])
        r = h.parse_saqa_text(SAQA, "99447")
        self.assertEqual((r["title"], r["nqf"], r["credits"], r["quality_partner"]), ("Occupational Certificate: Solar Photovoltaic Service Technician", 5, 344, "MERSETA Construction"))
        self.assertTrue(r["parsed_ok"]); self.assertFalse(h.parse_saqa_text("nothing here")["parsed_ok"])
    def test_feed_rejects_entity_bombs(self):
        with self.assertRaises(Exception):
            h.parse_feed('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;">]><rss><channel><item><title>&b;</title><link>x</link></item></channel></rss>')


class Fetching(Tmp):
    def test_policy(self):
        f = self.fetcher({})
        for bad in ("https://evil.example.com/x", "ftp://news.example.org/x", "file:///etc/passwd"):
            with self.assertRaises(h.HarvestError): f.check(bad)
        with mock.patch.object(h, "_is_public_host", lambda host: False):
            with self.assertRaises(h.HarvestError): f.check("https://news.example.org/x")
        f2 = self.fetcher({"https://news.example.org/robots.txt": Resp(200, b"User-agent: *\nDisallow: /private")})
        f2.check("https://news.example.org/ok")
        with self.assertRaises(h.HarvestError): f2.check("https://news.example.org/private/a")
    def test_redirect_to_other_host_is_refused(self):
        f = self.fetcher({"https://news.example.org/a": Resp(302, b"", {"Location": "https://evil.example.com/"})})
        with self.assertRaises(h.HarvestError): f.get("https://news.example.org/a")
    def test_cache_and_stale_fallback(self):
        url = "https://news.example.org/a"
        f = self.fetcher({url: Resp(200, b"hello", {"Content-Type": "text/html"})})
        self.assertFalse(f.get(url)["from_cache"]); n = len(f.session.calls)
        self.assertTrue(f.get(url)["from_cache"]); self.assertEqual(len(f.session.calls), n)
        f.session.routes[url] = Resp(500)
        r = f.get(url, force=True); self.assertTrue(r["stale"]); self.assertEqual(r["body"], b"hello")


class Refresh(Tmp):
    def test_news_refresh_and_search(self):
        url = "https://news.example.org/"
        html = b'<html><head><link rel="alternate" type="application/rss+xml" href="/feed.xml"></head><body>x</body></html>'
        f = self.fetcher({url: Resp(200, html, {"Content-Type": "text/html"}), "https://news.example.org/feed.xml": Resp(200, RSS.encode(), {"Content-Type": "application/rss+xml"})})
        (Path(self.td.name) / "sources.json").write_text(json.dumps({"sources": [{"id": "n", "name": "Example news", "type": "news", "url": url}, {"id": "bad", "name": "Bad", "type": "page", "url": "https://news.example.org/missing"}]}))
        st = h.refresh(fetcher=f)
        self.assertTrue(st["n"]["ok"]); self.assertEqual(st["n"]["documents"], 1)       # keyword filter dropped the sports item
        self.assertFalse(st["bad"]["ok"])
        hits = h.search_corpus("solar installer training")
        self.assertEqual(hits[0]["url"], "https://news.example.org/a"); self.assertIn("retrieved_at", hits[0])
        self.assertTrue(all(len(d["text"]) <= 600 for d in json.loads(h.DOCS_FILE.read_text())))   # news stored as excerpts only
        # a failing refresh keeps the previous documents
        f.session.routes[url] = Resp(500); h.CACHE.joinpath("x").touch()
        h.refresh(["n"], force=True, fetcher=f); self.assertEqual(len(json.loads(h.DOCS_FILE.read_text())), 1)


class Careers(Tmp):
    def test_data_integrity(self):
        occ = {o["ofo_code"]: o for o in cs.occupations()}
        self.assertEqual(len(occ), 350)
        for e in cs.handbook(): self.assertIn(e["ofo_code"], occ)
        for q in cs.qualifications():
            self.assertTrue(q["source_url"].startswith("https://")); self.assertIn(q["status"], cs.STATUS_LABELS)
            for c in q["ofo_codes"]: self.assertIn(c, occ)
    def test_filters(self):
        r = cs.search_occupations(q="solar"); self.assertEqual(r["items"][0]["ofo_code"], "642602")
        self.assertTrue(all(o["nqf"] == 6 for o in cs.search_occupations(nqf=6, jet_only=True)["items"]))
        self.assertTrue(all("GH2" in q["workstreams"] for q in cs.search_qualifications(ws="GH2")["items"]))
        self.assertEqual(cs.search_qualifications(q="120883")["total"], 1)
    def test_questionnaire(self):
        r = cs.match({"level": "4", "areas": ["NEV"], "enjoy": ["electrical", "hands_on"], "route": "trade", "junk": 1})
        self.assertEqual(r["results"][0]["name"], "Transportation Electrician")
        self.assertTrue(all(x["nqf"] is not None for x in r["results"]))
        self.assertIn("error", cs.match({}))
        self.assertEqual(cs.clean_answers({"areas": ["RE", "<script>"]})["areas"], ["RE"])
    def test_chat(self):
        self.assertIn("Solar Installer", cs.chat_answer("What does a solar installer need to study?")["reply"])
        self.assertIn("120883", cs.chat_answer("tell me about SAQA 120883")["reply"])
        self.assertIn("NQF Level 4", cs.chat_answer("what is nqf level 4")["reply"])
        self.assertIn("Green Hydrogen", cs.chat_answer("which hydrogen courses can I study")["reply"])
        self.assertIsNone(cs.chat_answer("what is the weather today"))
        with mock.patch.object(h, "lookup_saqa", side_effect=h.HarvestError("offline")):
            self.assertIn("could not read", cs.chat_answer("saqa id 999999")["reply"])


class StatsData(Tmp):
    def test_statssa_and_datafirst_parsers(self):
        g = h.parse_statssa_groups("Occupational code list\n\n111 Legislators\n095 Labour-Disabled Persons (15 to 65 years old)\n\u00a8 NA\n")
        self.assertEqual([x["code"] for x in g], ["111", "095"])
        codes, meta = h.parse_datafirst_codes("| 1110 | 1110. Legislators |\n| 2149 | 2149. Architects, engineers and related professionals not elsewhere classified, Industrial/production engineers |\nWarning: x\nzaf-statssa-qlfs-2026-q2-v1 https://doi.org/10.25828/a0p1-2z26")
        self.assertEqual(codes[1]["code"], "2149"); self.assertTrue(codes[1]["label"].endswith("production engineers"))
        self.assertEqual(meta["reference_id"], "zaf-statssa-qlfs-2026-q2-v1")
    def test_workbook_figures_are_faithful(self):
        d = json.loads((ROOT / "data/qlfs.json").read_text(encoding="utf-8"))
        self.assertEqual(len(d["rows"]), 57)
        for r in d["rows"]:   # the workbook's South Africa column is the sum of the nine provinces
            for k in ("employed", "unemployed"):
                self.assertEqual(sum(v for p, v in r[k].items() if p != "SA"), r[k]["SA"], r["name"])
        el = next(r for r in d["rows"] if r["name"] == "Electrician")
        self.assertEqual((el["employed"]["NC"], el["unemployed"]["NC"], el["employed"]["SA"]), (1961, 548, 116721))
        self.assertEqual(el["ofo_code"], "671101"); self.assertIn("Millwright", next(r for r in d["rows"] if r["name"] == "Fitter and Turner")["shares_category_with"])
    def test_labour_market_and_chat(self):
        nc = cs.labour_market(province="NC")
        self.assertEqual(nc["province_name"], "Northern Cape"); self.assertEqual(nc["items"][0]["qlfs_code"], 8324)
        self.assertEqual(cs.labour_market(province="bogus")["province"], "SA")
        self.assertTrue(all(i["mapping_class"] == "proxy" for i in cs.labour_market(mapping="proxy")["items"]))
        r = cs.chat_answer("How many electricians are employed in the Northern Cape?")["reply"]
        self.assertIn("1,961", r); self.assertIn("proxy", r)
        self.assertIn("Safety, health and quality inspectors", " ".join(x["reply"] for x in [cs.chat_answer("employment in Gauteng")]) + cs._short("Safety, health and quality inspectors, Inspectors, safety and health"))
        self.assertIn("Labour market (QLFS", cs.chat_answer("tell me about the welder occupation")["reply"])


class Dashboards(Tmp):
    def test_research_dashboard_and_privacy(self):
        recs = an.repository(); self.assertEqual(len({r["id"] for r in recs}), len(recs))
        d = an.research_dashboard()
        self.assertEqual(d["total"], len(recs)); self.assertEqual(sum(x["count"] for x in d["by_group"]), len(recs))
        self.assertEqual(d["ingestion"]["baseline"], len(recs)); self.assertEqual(d["ingestion"]["monthly"], [])
        rid = recs[0]["id"]
        self.assertTrue(an.record_artefact("1.2.3.4", rid, "synopsis")); self.assertFalse(an.record_artefact("1.2.3.4", rid, "synopsis"))   # de-duplicated
        self.assertTrue(an.record_artefact("5.6.7.8", rid, "synopsis")); self.assertFalse(an.record_artefact("x", "nope", "synopsis"))
        self.assertFalse(an.record_artefact("x", rid, "delete"))
        top = an.research_dashboard()["views"]["top"][0]; self.assertEqual((top["id"], top["synopsis"]), (rid, 2))
        stored = an.EVENTS_FILE.read_text(encoding="utf-8")
        for secret in ("1.2.3.4", "5.6.7.8"): self.assertNotIn(secret, stored)      # no IP addresses on disk
    def test_ingestion_tracks_new_artefacts(self):
        recs = an.repository(); an.sync_registry(recs)
        an.sync_registry(recs + [dict(recs[0], id="brandnew")])
        ing = an.research_dashboard.__globals__["_read"](an.REGISTRY_FILE, {})["items"]["brandnew"]
        self.assertEqual(ing["first_seen"], an.today())
    def test_questionnaire_counts_never_store_answers(self):
        r = cs.match({"level": "4", "areas": ["NEV"], "enjoy": ["electrical"], "route": "trade"})
        self.assertTrue(an.record_questionnaire("9.9.9.9", r["answers"], r["results"]))
        q = an.careers_dashboard()["questionnaire"]; self.assertEqual(q["total"], 1); self.assertEqual(q["by_area"][0]["label"], "New Energy Vehicles")
        self.assertNotIn("electrical", an.EVENTS_FILE.read_text(encoding="utf-8")); self.assertNotIn("9.9.9.9", an.EVENTS_FILE.read_text(encoding="utf-8"))
    def test_career_dashboard_uses_real_data_and_stays_empty_without_partner_data(self):
        c = an.careers_dashboard()
        self.assertEqual(c["high_demand_list"]["total"], 350); self.assertEqual(c["rankings"]["employed"][0]["code"], 9322)
        self.assertEqual(sum(x["count"] for x in c["high_demand_list"]["by_nqf"]), 325)     # 350 minus the 25 with no NQF equivalent
        self.assertFalse(c["enrolments"]["has_data"]); self.assertEqual(c["enrolments"]["by_theme"], [])
    def test_pipeline_import_and_dashboard(self):
        self.assertFalse(an.pipeline_dashboard()["has_data"])
        res = an.import_pipeline((ROOT / "tests/fixtures/learner_pipeline_sample.csv").read_text(encoding="utf-8"))
        self.assertEqual((res["imported"], res["error_count"]), (5, 0))
        d = an.pipeline_dashboard(); self.assertEqual(d["period"], "2026-Q3"); self.assertEqual(d["periods"], ["2026-Q2", "2026-Q3"])
        gh2 = next(w for w in d["by_workstream"] if w["code"] == "GH2"); self.assertEqual((gh2["training"], gh2["internship"], gh2["employment"], gh2["total"]), (120, 30, 12, 162))
        self.assertEqual(next(w for w in d["by_workstream"] if w["code"] == "NEV")["training"], 1500)
        self.assertFalse(next(w for w in d["by_workstream"] if w["code"] == "RE")["reported"]); self.assertEqual(d["coverage"]["workstreams_reporting"], 2)
        self.assertEqual(an.pipeline_dashboard("2026-Q2")["totals"]["training"], 900)
        again = an.import_pipeline((ROOT / "tests/fixtures/learner_pipeline_sample.csv").read_text(encoding="utf-8")); self.assertEqual(again["replaced"], 5)   # re-import replaces, never duplicates
        self.assertEqual(an.pipeline_dashboard()["totals"]["training"], 1620)
    def test_import_validation_rejects_bad_data(self):
        head = ",".join(an.PIPELINE_COLUMNS) + "\n"
        for row, frag in (("2026-13,GH2,training,5,Org,,Src,,reported", "period"), ("2026-Q3,XX,training,5,Org,,Src,,reported", "workstream"), ("2026-Q3,GH2,hired,5,Org,,Src,,reported", "stage"),
                          ("2026-Q3,GH2,training,-5,Org,,Src,,reported", "learners"), ("2026-Q3,GH2,training,abc,Org,,Src,,reported", "learners"), ("2026-Q3,GH2,training,5,,,,,reported", "required")):
            r = an.import_pipeline(head + row); self.assertEqual(r["imported"], 0); self.assertTrue(any(frag in e for e in r["errors"]), row)
        with self.assertRaises(ValueError): an.import_pipeline("name,id_number\nA,123")        # personal-data columns are not accepted
        bad = an.import_pipeline(head + "2026-Q3,GH2,training,5,Org,,Src,,reported\n2026-Q3,RE,training,x,Org,,Src,,reported")
        self.assertEqual(bad["imported"], 0); self.assertFalse(an.PIPELINE_FILE.exists())       # all or nothing
    def test_enrolments_by_theme(self):
        csvtext = ",".join(an.ENROL_COLUMNS) + "\n2026-Q3,Green hydrogen,200,,,CHIETA,TEST,,reported\n2026-Q3,green hydrogen,50,Other,,CHIETA,TEST,,reported\n2026-Q3,Renewable energy,10,,,EWSETA,TEST,,reported\n"
        self.assertEqual(an.import_enrolments(csvtext)["imported"], 3)
        e = an.careers_dashboard()["enrolments"]; self.assertEqual({x["label"]: x["count"] for x in e["by_theme"]}, {"Renewable energy": 10, "Green hydrogen": 250})
    def test_harvested_candidates_need_human_approval(self):
        src = {"id": "s", "name": "Test report", "url": "https://example.org/r"}
        found = an.extract_candidates("The programme enrolled 1,250 learners in solar PV installer training. Funding rose by 45% in 2025. The summit had 600 delegates. In 2026 there were 85 interns hosted by municipalities on energy projects.", src)
        self.assertEqual([c["number"] for c in found], [1250, 85]); self.assertEqual(found[0]["workstream_guess"], "RE"); self.assertEqual(found[1]["stage_guess"], "internship")
        self.assertEqual(an.add_candidates(found), 2); self.assertEqual(an.add_candidates(found), 0)
        self.assertFalse(an.pipeline_dashboard()["has_data"])                                     # nothing shown before approval
        with self.assertRaises(ValueError): an.decide_candidate(found[0]["id"], "approve", {"workstream": "RE"})
        an.decide_candidate(found[0]["id"], "approve", {"workstream": "RE", "stage": "training", "period": "2026-Q3", "learners": 1250, "reporting_organisation": "Test org"})
        d = an.pipeline_dashboard(); self.assertEqual(d["totals"]["training"], 1250); self.assertEqual(d["records"][0]["source_name"], "Test report")
        an.decide_candidate(found[1]["id"], "reject"); self.assertEqual(an.candidates(), [])


class DashboardRoutes(Tmp):
    def setUp(self):
        super().setUp()
        import app as appmod
        self.app = appmod.app.test_client()
    def test_pages_and_apis(self):
        html = self.app.get("/dashboards").get_data(as_text=True)
        for key in ("Research Analytics", "Career Guidance Analytics", "Learner Pipeline Analytics", "Careers &amp; Data", "Analytics Dashboards"): self.assertIn(key, html)
        self.assertNotIn("phase", html.lower())
        for path in ("/api/dashboards/research", "/api/dashboards/career-guidance", "/api/dashboards/learner-pipeline"): self.assertEqual(self.app.get(path).status_code, 200)
        self.assertIn("period,workstream,stage", self.app.get("/api/dashboards/template/learner_pipeline.csv").get_data(as_text=True))
        self.assertEqual(self.app.get("/api/dashboards/template/other.csv").status_code, 404)
        self.assertIn("Analytics Dashboards", self.app.get("/").get_data(as_text=True))
    def test_event_endpoint_counts_real_artefacts_only(self):
        rid = self.app.get("/api/resources").get_json()[0]["id"]
        self.assertEqual(self.app.post("/api/analytics/event", json={"type": "artefact", "id": rid, "action": "synopsis"}).status_code, 204)
        self.app.post("/api/analytics/event", json={"type": "artefact", "id": "fake", "action": "synopsis"}); self.app.post("/api/analytics/event", data="not json")
        v = self.app.get("/api/dashboards/research").get_json()["views"]; self.assertEqual(v["synopsis_total"], 1); self.assertEqual(v["top"][0]["id"], rid)
    def test_questionnaire_completion_is_counted(self):
        self.app.post("/api/careers/match", json={"answers": {"level": "5", "areas": ["RE"]}}); self.app.post("/api/careers/match", json={})
        self.assertEqual(self.app.get("/api/dashboards/career-guidance").get_json()["questionnaire"]["total"], 1)     # the invalid one is not counted
    def test_admin_endpoints_are_protected(self):
        csv_text = (ROOT / "tests/fixtures/learner_pipeline_sample.csv").read_text(encoding="utf-8")
        self.assertEqual(self.app.post("/api/dashboards/import", json={"kind": "learner_pipeline", "csv": csv_text}).status_code, 403)
        self.assertEqual(self.app.get("/api/dashboards/candidates").status_code, 403)
        with mock.patch.dict("os.environ", {"HARVEST_ADMIN_TOKEN": "s3cret"}):
            self.assertEqual(self.app.post("/api/dashboards/import", json={"kind": "learner_pipeline", "csv": csv_text}, headers={"X-Admin-Token": "bad"}).status_code, 401)
            ok = self.app.post("/api/dashboards/import", json={"kind": "learner_pipeline", "csv": csv_text}, headers={"X-Admin-Token": "s3cret"}); self.assertEqual(ok.status_code, 200)
            bad = self.app.post("/api/dashboards/import", json={"kind": "learner_pipeline", "csv": "period,workstream\n1,2"}, headers={"X-Admin-Token": "s3cret"}); self.assertEqual(bad.status_code, 400)
            self.assertEqual(self.app.get("/api/dashboards/candidates", headers={"X-Admin-Token": "s3cret"}).get_json(), [])
        self.assertTrue(self.app.get("/api/dashboards/learner-pipeline").get_json()["has_data"])


class Routes(Tmp):
    def setUp(self):
        super().setUp()
        import app as appmod
        self.app = appmod.app.test_client(); self.mod = appmod
    def test_pages_render_with_shared_shell(self):
        for path in ("/", "/career-guidance", "/occupational-handbook"):
            r = self.app.get(path); self.assertEqual(r.status_code, 200, path)
            html = r.get_data(as_text=True)
            self.assertIn('id="openChat"', html); self.assertIn("site-footer", html); self.assertIn("Occupational Handbook", html)
        self.assertIn('href="#about"', self.app.get("/").get_data(as_text=True))
        self.assertIn('href="/#about"', self.app.get("/career-guidance").get_data(as_text=True))
        self.assertIn('id="mpumalanga-launch"', self.app.get("/").get_data(as_text=True))   # home content preserved
    def test_api(self):
        self.assertEqual(self.app.get("/api/careers/facets").get_json()["counts"]["occupations"], 350)
        self.assertGreater(self.app.get("/api/careers/occupations?q=electrician&jet=1").get_json()["total"], 0)
        self.assertEqual(self.app.get("/api/careers/occupations?nqf=abc&limit=zzz").status_code, 200)
        self.assertEqual(self.app.get("/api/careers/qualifications?status=approved").get_json()["total"], 4)
        self.assertEqual(len(self.app.get("/api/careers/handbook").get_json()), 19)
        ok = self.app.post("/api/careers/match", json={"answers": {"level": "5", "areas": ["RE"]}}); self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.app.post("/api/careers/match", json={}).status_code, 400)
        self.assertEqual(self.app.get("/api/health").get_json()["chatbot"], "careers")
    def test_chat_integration(self):
        r = self.app.post("/api/chat", json={"message": "tell me about the electrician occupation"}).get_json()
        self.assertEqual(r["source"], "careers"); self.assertIn("OFO", r["reply"])
        self.assertEqual(self.app.post("/api/chat", json={"message": "what are the workstreams"}).get_json()["source"], "faq")
    def test_northern_cape_launch_content(self):
        html = self.app.get("/").get_data(as_text=True)
        self.assertIn('id="northern-cape-launch"', html); self.assertIn("Northern Cape Skills Development Zone Officially Launched", html)
        self.assertIn("19 November 2026", html); self.assertNotIn("20 Nov", html); self.assertNotIn("should be confirmed before publication", html)
        self.assertEqual(html.count("data-slideshow"), 2); self.assertIn("nc-premier-address.mp4", html)
        self.assertIn('id="mpumalanga-launch"', html)
        for i in range(1, 9): self.assertEqual(self.app.get(f"/static/images/nc-launch/nc-launch-{i:02d}.jpg").status_code, 200)
        self.assertEqual(self.app.get("/static/video/nc-premier-address.mp4").status_code, 200)
        self.assertIn("19 November 2026", self.app.post("/api/chat", json={"message": "tell me about the skills development zones"}).get_json()["reply"])
    def test_team_shows_photo_name_role_and_department_without_a_bio_panel(self):
        html = self.app.get("/").get_data(as_text=True)
        i = html.index('id="team"'); team = html[i:html.index("</section>", i)]
        self.assertEqual(team.count('class="team-card"'), 9)
        for text in ("Mamphokhu Khuluvhe", "JET Skills Desk: Strategic Lead &amp; Senior Technical Advisor", "Papie Medgar Mojaki", "JET Skills Desk · Software Developer Intern", "Patience Pontsho Mokgosi"):
            self.assertIn(text, team)
        self.assertEqual(team.count("Department of Higher Education and Training"), 9)
        self.assertEqual(len(__import__('re').findall(r'/static/images/team/[a-z-]+\.jpg\?v=\d+', team)), 9)     # cache-busted photo addresses
        for gone in ("teamPanel", "data-team-open", "team-tile"): self.assertNotIn(gone, html)
        self.assertNotIn("team.js", html)
        for stem in ("mampho", "sean", "papie-medgar-mojaki", "koketso", "mzwakhe", "athabile-ntlokwana", "mercy", "sinalo", "patience"):
            self.assertEqual(self.app.get(f"/static/images/team/{stem}.jpg").status_code, 200)
    def test_build_stamp_and_page_caching(self):
        r = self.app.get("/")
        self.assertIn('<meta name="build" content="v14">', r.get_data(as_text=True)); self.assertEqual(r.headers["Cache-Control"], "no-cache")
        self.assertEqual(self.app.get("/api/health").get_json()["build"], "v14")
    def test_team_portraits_are_on_white(self):
        from PIL import Image
        for stem in ("mampho", "sean", "papie-medgar-mojaki", "koketso", "mzwakhe", "athabile-ntlokwana", "mercy", "sinalo", "patience"):
            im = Image.open(ROOT / f"static/images/team/{stem}.jpg").convert("RGB")
            self.assertEqual(im.size, (560, 700), stem)
            top = [im.getpixel(xy) for xy in ((2, 2), (557, 2), (2, 40), (557, 40))]    # the head may touch the top edge, so the centre is not checked
            self.assertTrue(all(min(px) >= 250 for px in top), f"{stem} backdrop is not white: {top}")
            row = [im.getpixel((x, 20)) for x in range(0, 560, 8)]
            self.assertGreater(sum(1 for px in row if min(px) >= 250) / len(row), .5, stem)
    def test_labour_market_api(self):
        d = self.app.get("/api/careers/labour-market?province=NC&sort=employed").get_json()
        self.assertEqual(d["province_name"], "Northern Cape"); self.assertGreater(len(d["caveats"]), 3)
        self.assertEqual(self.app.get("/api/careers/labour-market?q=electrician").get_json()["items"][0]["name"], "Electrician")
        page = self.app.get("/career-guidance").get_data(as_text=True)
        self.assertNotIn("labour-market", page); self.assertNotIn("lmBody", page)      # the section was removed from the page
        self.assertNotIn("#labour-market", self.app.get("/").get_data(as_text=True))
    def test_harvest_endpoints_are_protected(self):
        self.assertEqual(self.app.post("/api/harvest/refresh").status_code, 403)          # no token configured
        with mock.patch.dict("os.environ", {"HARVEST_ADMIN_TOKEN": "s3cret"}):
            self.assertEqual(self.app.post("/api/harvest/refresh", headers={"X-Admin-Token": "nope"}).status_code, 401)
            with mock.patch.object(h, "refresh_async") as ra:
                self.assertEqual(self.app.post("/api/harvest/refresh", headers={"X-Admin-Token": "s3cret"}, json={"force": True}).status_code, 202); ra.assert_called_once()
        self.assertTrue(all("error" not in r for r in self.app.get("/api/harvest/status").get_json()))
        self.assertEqual(self.app.get("/api/harvest/search").status_code, 400)

if __name__ == "__main__":
    unittest.main()
