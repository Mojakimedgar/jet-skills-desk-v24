"""Analytics dashboards (plan section 9.2).

Three dashboards:
  Research Analytics        total records, content-type breakdown, ingestion trends, most-viewed artefacts
  Career Guidance Analytics high-demand occupation rankings, enrolments by green-economy theme, questionnaire completions
  Learner Pipeline          learners in training, internships and employment, per workstream

Data rules
- Nothing is invented. Where a figure needs partner data (enrolments, learner stages) the dashboard
  shows an empty state until data has been imported or approved by a person.
- Usage counts are aggregate counters only: no IP address, user agent, cookie or answer set is stored.
- Partner data arrives through standard reporting templates (CSV) or from harvested "candidate figures"
  that a person verifies and approves (semi-automated data entry).

Command line:
    python analytics.py templates                       # write the CSV templates
    python analytics.py import learner_pipeline file.csv
    python analytics.py import enrolments file.csv
    python analytics.py candidates                      # figures found by the harvester, awaiting review
    python analytics.py approve ID --workstream GH2 --stage training --period 2026-Q3 --count 120 --org CHIETA
    python analytics.py reject ID
"""
import argparse
import csv
import hashlib
import io
import json
import re
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
AN = DATA / "analytics"
REP = DATA / "reported"
EVENTS_FILE, REGISTRY_FILE = AN / "events.json", AN / "registry.json"
PIPELINE_FILE, ENROL_FILE, CAND_FILE = REP / "learner_pipeline.json", REP / "enrolments.json", REP / "candidates.json"

_LOCK = threading.Lock()
THEMES = ["New energy vehicles", "Green hydrogen", "Renewable energy", "Energy efficiency", "Municipalities", "Coal & just transition", "Gender & inclusion"]
WORKSTREAMS = {"RE": "Renewable Energy", "NEV": "New Energy Vehicles", "GH2": "Green Hydrogen", "MUN": "Municipal skills"}
STAGES = {"training": "In training", "internship": "In internships", "employment": "In employment"}
ENROL_THEMES = ["Renewable energy", "New energy vehicles", "Green hydrogen", "Energy efficiency", "Municipal energy", "Other green economy"]
SDZS = ["", "Mpumalanga", "Northern Cape", "Eastern Cape", "National"]
PERIOD_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2]|Q[1-4])$")
MAX_COUNT, MAX_ROWS = 10_000_000, 5000

PIPELINE_COLUMNS = ["period", "workstream", "stage", "learners", "reporting_organisation", "sdz", "source_name", "source_url", "status"]
ENROL_COLUMNS = ["period", "theme", "enrolments", "qualification", "provider", "reporting_organisation", "source_name", "source_url", "status"]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _read(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


# --------------------------------------------------------------------------
# Repository records (with stable IDs)
# --------------------------------------------------------------------------
def rec_id(rec):
    """Stable ID from title + citation + year (titles alone are not unique in the repository)."""
    key = "|".join((rec.get(k) or "").strip().lower() for k in ("t", "c", "y"))
    return hashlib.sha1(key.encode()).hexdigest()[:10]


def repository():
    recs = _read(DATA / "research_repository.json", [])
    out, seen = [], Counter()
    for r in recs:
        rid = rec_id(r)
        seen[rid] += 1
        out.append(dict(r, id=rid if seen[rid] == 1 else f"{rid}-{seen[rid]}"))
    return out


def sync_registry(recs=None):
    """Remember when each artefact was first seen, so ingestion trends build up over time.

    Artefacts present when tracking starts are the 'baseline' (their original date added is not
    recorded in the repository file). Artefacts added later get the date they first appear."""
    recs = recs if recs is not None else repository()
    with _LOCK:
        reg = _read(REGISTRY_FILE, None)
        if reg is None:
            reg = {"created": today(), "items": {r["id"]: {"first_seen": None} for r in recs}}
        else:
            for r in recs:
                reg["items"].setdefault(r["id"], {"first_seen": today()})
        _write(REGISTRY_FILE, reg)
        return reg


# --------------------------------------------------------------------------
# Usage events (aggregate counters only)
# --------------------------------------------------------------------------
_seen, _hits = {}, defaultdict(list)


def _allow(client, kind, key="", dedupe_hours=6, limit=60):
    now = time.time()
    _hits[client] = [t for t in _hits[client] if now - t < 600]
    if len(_hits[client]) >= limit:
        return False
    _hits[client].append(now)
    if key:
        k = (client, kind, key)
        if now - _seen.get(k, 0) < dedupe_hours * 3600:
            return False
        _seen[k] = now
    if len(_seen) > 20000:
        _seen.clear()
    return True


def _events():
    ev = _read(EVENTS_FILE, None)
    if ev is None:
        ev = {"since": today(), "artefact": {}, "questionnaire": {"total": 0, "by_level": {}, "by_area": {}, "by_route": {}, "top_matches": {}}, "daily": {}}
    return ev


def record_artefact(client, art_id, action):
    """action: 'synopsis' (opened a synopsis) or 'copy' (copied a reference)."""
    if action not in ("synopsis", "copy") or art_id not in {r["id"] for r in repository()}:
        return False
    if not _allow(client, "artefact", f"{art_id}:{action}"):
        return False
    with _LOCK:
        ev = _events()
        a = ev["artefact"].setdefault(art_id, {"synopsis": 0, "copy": 0})
        a[action] += 1
        d = ev["daily"].setdefault(today(), {"artefact": 0, "questionnaire": 0})
        d["artefact"] += 1
        _write(EVENTS_FILE, ev)
    return True


def record_questionnaire(client, answers, results):
    """Count one completed questionnaire. Only counters are kept, never the answer set."""
    if not _allow(client, "questionnaire", limit=30):
        return False
    with _LOCK:
        ev = _events(); q = ev["questionnaire"]
        q["total"] += 1
        for key, field in (("by_level", answers.get("level")), ("by_route", answers.get("route"))):
            if field:
                q[key][field] = q[key].get(field, 0) + 1
        for a in answers.get("areas") or []:
            q["by_area"][a] = q["by_area"].get(a, 0) + 1
        for r in (results or [])[:3]:
            q["top_matches"][r["ofo_code"]] = q["top_matches"].get(r["ofo_code"], 0) + 1
        ev["daily"].setdefault(today(), {"artefact": 0, "questionnaire": 0})["questionnaire"] += 1
        _write(EVENTS_FILE, ev)
    return True


# --------------------------------------------------------------------------
# Reported data (partner templates) and harvested candidates
# --------------------------------------------------------------------------
def period_key(p):
    y, rest = p.split("-")
    return (int(y), int(rest[1]) * 3 if rest.startswith("Q") else int(rest))


def _clean(v, n=200):
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def _url(v):
    v = _clean(v, 500)
    return v if re.match(r"^https?://", v, re.I) else ""


def _parse_rows(text, columns, required):
    if len(text.encode("utf-8", "ignore")) > 1_500_000:
        raise ValueError("The file is larger than 1.5 MB.")
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    heads = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [c for c in required if c not in heads]
    if missing:
        raise ValueError("Missing required column(s): " + ", ".join(missing) + ". Use the standard template.")
    rows = []
    for i, raw in enumerate(reader, start=2):
        if i > MAX_ROWS + 1:
            raise ValueError(f"More than {MAX_ROWS} rows.")
        rows.append((i, {(k or "").strip().lower(): v for k, v in raw.items()}))
    return rows


def _check_period(p, errs, line):
    p = _clean(p, 12).upper()
    if not PERIOD_RE.match(p):
        errs.append(f"Line {line}: period must look like 2026-Q3 or 2026-09.")
        return None
    return p


def _check_count(v, errs, line, label):
    try:
        n = int(str(v).replace(",", "").replace(" ", ""))
    except ValueError:
        errs.append(f"Line {line}: {label} must be a whole number.")
        return None
    if n < 0 or n > MAX_COUNT:
        errs.append(f"Line {line}: {label} is out of range.")
        return None
    return n


def import_pipeline(text):
    rows = _parse_rows(text, PIPELINE_COLUMNS, ["period", "workstream", "stage", "learners", "reporting_organisation", "source_name"])
    good, errs = [], []
    for line, r in rows:
        period = _check_period(r.get("period"), errs, line)
        ws, stage = _clean(r.get("workstream"), 5).upper(), _clean(r.get("stage"), 20).lower()
        n = _check_count(r.get("learners"), errs, line, "learners")
        org, src = _clean(r.get("reporting_organisation")), _clean(r.get("source_name"))
        sdz = _clean(r.get("sdz"), 30)
        if ws not in WORKSTREAMS:
            errs.append(f"Line {line}: workstream must be one of {', '.join(WORKSTREAMS)}.")
        if stage not in STAGES:
            errs.append(f"Line {line}: stage must be one of {', '.join(STAGES)}.")
        if sdz not in SDZS:
            errs.append(f"Line {line}: sdz must be blank or one of {', '.join(s for s in SDZS if s)}.")
        if not org or not src:
            errs.append(f"Line {line}: reporting_organisation and source_name are required.")
        if period and n is not None and ws in WORKSTREAMS and stage in STAGES and org and src and sdz in SDZS:
            good.append({"period": period, "workstream": ws, "stage": stage, "learners": n, "reporting_organisation": org, "sdz": sdz,
                         "source_name": src, "source_url": _url(r.get("source_url")),
                         "status": "verified" if _clean(r.get("status"), 10).lower() == "verified" else "reported", "imported_at": now_iso()})
    return _store(PIPELINE_FILE, good, errs, ("period", "workstream", "stage", "reporting_organisation", "sdz"))


def import_enrolments(text):
    rows = _parse_rows(text, ENROL_COLUMNS, ["period", "theme", "enrolments", "reporting_organisation", "source_name"])
    good, errs = [], []
    for line, r in rows:
        period = _check_period(r.get("period"), errs, line)
        theme = _clean(r.get("theme"), 40)
        n = _check_count(r.get("enrolments"), errs, line, "enrolments")
        org, src = _clean(r.get("reporting_organisation")), _clean(r.get("source_name"))
        match = next((t for t in ENROL_THEMES if t.lower() == theme.lower()), None)
        if not match:
            errs.append(f"Line {line}: theme must be one of {', '.join(ENROL_THEMES)}.")
        if not org or not src:
            errs.append(f"Line {line}: reporting_organisation and source_name are required.")
        if period and n is not None and match and org and src:
            good.append({"period": period, "theme": match, "enrolments": n, "qualification": _clean(r.get("qualification")), "provider": _clean(r.get("provider")),
                         "reporting_organisation": org, "source_name": src, "source_url": _url(r.get("source_url")),
                         "status": "verified" if _clean(r.get("status"), 10).lower() == "verified" else "reported", "imported_at": now_iso()})
    return _store(ENROL_FILE, good, errs, ("period", "theme", "reporting_organisation", "qualification", "provider"))


def _store(path, new, errs, key_fields):
    """Rows with the same key replace earlier ones. Nothing is stored if any row is invalid."""
    if errs:
        return {"imported": 0, "replaced": 0, "errors": errs[:25], "error_count": len(errs)}
    with _LOCK:
        cur = _read(path, [])
        idx = {tuple(r.get(k, "") for k in key_fields): i for i, r in enumerate(cur)}
        replaced = 0
        for r in new:
            k = tuple(r.get(f, "") for f in key_fields)
            if k in idx:
                cur[idx[k]] = r; replaced += 1
            else:
                idx[k] = len(cur); cur.append(r)
        _write(path, cur)
    return {"imported": len(new), "replaced": replaced, "errors": [], "error_count": 0}


def template_csv(kind):
    cols = PIPELINE_COLUMNS if kind == "learner_pipeline" else ENROL_COLUMNS
    return ",".join(cols) + "\n"


# -- harvested candidate figures (for human review) -------------------------
_WS_WORDS = {"RE": r"solar|photovoltaic|\bPV\b|wind|renewable|BESS|battery|transmission|energy efficiency", "NEV": r"electric vehicle|\bNEV|\bEV\b|electromobility|automotive|e-mobility",
             "GH2": r"hydrogen|\bGH2\b", "MUN": r"municipal"}
_NOUNS = r"(learners?|trainees?|students?|participants|beneficiar\w+|graduates?|apprentices?|artisans?|interns?|internships?|learnerships?|bursar\w+|young people|youth|people (?:trained|placed|employed)|jobs?)"
_NUM = re.compile(r"(?<![\w.,])(\d{1,3}(?:[ ,]\d{3})+|\d{2,7})(?![\w.,]?\d)(?!\s*%)")


def extract_candidates(text, src):
    """Find sentences that report a count of learners/interns/graduates/jobs for an energy-transition topic."""
    out = []
    for sent in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text or "")):
        if len(sent) < 25 or len(sent) > 600:
            continue
        for m in _NUM.finditer(sent):
            raw = m.group(1)
            n = int(re.sub(r"[ ,]", "", raw))
            if 1990 <= n <= 2100 and raw.isdigit():       # looks like a year
                continue
            tail = sent[m.end(): m.end() + 70]
            if not re.match(r"\s*(?:\w+\s+){0,4}?" + _NOUNS, tail, re.I):
                continue
            ws = next((c for c, pat in _WS_WORDS.items() if re.search(pat, sent, re.I)), "")
            if not ws and not re.search(r"green|just energy transition|\bJET\b", sent, re.I):
                continue
            low = sent.lower()
            stage = "internship" if "intern" in low else "employment" if re.search(r"employ|placed|absorbed|jobs", low) else "training"
            cid = hashlib.sha1(f"{src['url']}|{sent[:120]}|{n}".encode()).hexdigest()[:12]
            out.append({"id": cid, "number": n, "sentence": sent[:400], "stage_guess": stage, "workstream_guess": ws,
                        "source_id": src["id"], "source_name": src["name"], "url": src["url"], "found_at": now_iso(), "status": "pending"})
            break
    return out


def add_candidates(new):
    with _LOCK:
        cur = _read(CAND_FILE, [])
        have = {c["id"] for c in cur}
        added = [c for c in new if c["id"] not in have]
        if added:
            _write(CAND_FILE, cur + added)
    return len(added)


def candidates(status="pending"):
    return [c for c in _read(CAND_FILE, []) if not status or c["status"] == status]


def decide_candidate(cid, action, fields=None):
    """Approve (turn into a reported learner-pipeline row, validated like any import) or reject a candidate."""
    if action not in ("approve", "reject"):
        raise ValueError("action must be approve or reject")
    c = next((x for x in _read(CAND_FILE, []) if x["id"] == cid), None)
    if c is None:
        raise KeyError("No such candidate")
    res = {"status": "rejected"}
    if action == "approve":
        f = fields or {}
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=PIPELINE_COLUMNS)
        w.writeheader()
        w.writerow({"period": f.get("period", ""), "workstream": f.get("workstream", ""), "stage": f.get("stage", ""), "learners": f.get("learners", ""),
                    "reporting_organisation": f.get("reporting_organisation", ""), "sdz": f.get("sdz", ""),
                    "source_name": c["source_name"], "source_url": c["url"], "status": "reported"})
        res = import_pipeline(buf.getvalue())
        if res["error_count"]:
            raise ValueError("; ".join(res["errors"]))
    with _LOCK:
        cur = _read(CAND_FILE, [])
        item = next(x for x in cur if x["id"] == cid)
        item["status"] = "approved" if action == "approve" else "rejected"
        item["decided_at"] = now_iso()
        _write(CAND_FILE, cur)
    return res


# --------------------------------------------------------------------------
# Dashboards
# --------------------------------------------------------------------------
def _ranked(counter, total=None, top=None):
    total = total if total is not None else sum(counter.values())
    rows = [{"label": k, "count": v, "share": round(v / total * 100, 1) if total else 0} for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))]
    return rows[:top] if top else rows


def research_dashboard():
    recs = repository()
    reg = sync_registry(recs)
    ev = _events()
    by_id = {r["id"]: r for r in recs}
    new_by_month = Counter(v["first_seen"][:7] for cid, v in reg["items"].items() if v["first_seen"] and cid in by_id)
    baseline = sum(1 for cid, v in reg["items"].items() if not v["first_seen"] and cid in by_id)
    run, trend = baseline, []
    for m in sorted(new_by_month):
        run += new_by_month[m]; trend.append({"month": m, "new": new_by_month[m], "cumulative": run})
    views = []
    for aid, c in ev["artefact"].items():
        r = by_id.get(aid)
        if r:
            views.append({"id": aid, "title": r["t"], "group": r.get("g") or "", "year": r.get("y") or "", "synopsis": c["synopsis"], "copy": c["copy"]})
    views.sort(key=lambda v: (-v["synopsis"], -v["copy"], v["title"]))
    years = Counter((r.get("y") or "n.d.") for r in recs)
    try:
        import harvester
        monitored = [s for s in harvester.status() if s["enabled"]]
        harvest = {"sources": len(monitored), "documents": sum(s["documents"] for s in monitored), "ok": sum(1 for s in monitored if s.get("ok")),
                   "last_run": max([s.get("ran_at") or "" for s in monitored] or [""]) or None}
    except Exception:
        harvest = {"sources": 0, "documents": 0, "ok": 0, "last_run": None}
    return {
        "updated": now_iso(), "total": len(recs),
        "with_synopsis": sum(1 for r in recs if r.get("s")), "with_keywords": sum(1 for r in recs if r.get("k")),
        "by_group": _ranked(Counter((r.get("g") or "Other") for r in recs)),
        "by_collection": _ranked(Counter((r.get("col") or "Other") for r in recs)),
        "by_theme": [{"label": t, "count": sum(1 for r in recs if t in (r.get("sec") or []))} for t in THEMES],
        "by_year": [{"label": y, "count": years[y]} for y in sorted((y for y in years if y != "n.d."), key=int)] + ([{"label": "n.d.", "count": years["n.d."]}] if years.get("n.d.") else []),
        "ingestion": {"baseline": baseline, "baseline_note": "Artefacts already in the repository when tracking began. The repository file does not record their original date added (the workplan lists the index as compiled in June 2026).",
                      "tracking_since": reg["created"], "monthly": trend, "total": len(recs)},
        "views": {"tracked_since": ev["since"], "synopsis_total": sum(c["synopsis"] for c in ev["artefact"].values()), "copy_total": sum(c["copy"] for c in ev["artefact"].values()),
                  "top": views[:10]},
        "harvest": harvest,
    }


def _periods(rows):
    periods = sorted({r["period"] for r in rows}, key=period_key)
    return periods


def careers_dashboard():
    import career_service as cs
    qrows = cs.qlfs().get("rows", [])
    cats = {}
    for r in qrows:
        c = cats.setdefault(r["qlfs_code"], {"code": r["qlfs_code"], "label": cs._short(r["qlfs_label"]), "occupations": [], "employed": r["employed"]["SA"], "unemployed": r["unemployed"]["SA"], "mapping": r["mapping_class"]})
        c["occupations"].append(r["name"])
    cats = list(cats.values())
    emp = sorted((c for c in cats if c["employed"]), key=lambda c: -c["employed"])[:10]
    une = sorted((c for c in cats if c["unemployed"]), key=lambda c: -c["unemployed"])[:10]
    occ = cs.occupations()
    nqf = Counter(o["nqf"] for o in occ if o.get("nqf"))
    jet = [o for o in occ if "jet" in o]
    ws_counts = {w: sum(1 for o in jet if w in o["jet"]["workstreams"]) for w in cs.WORKSTREAMS}
    ev = _events(); q = ev["questionnaire"]
    names = {o["ofo_code"]: o["name"] for o in occ}
    daily = [{"date": d, "count": v["questionnaire"]} for d, v in sorted(ev["daily"].items()) if v.get("questionnaire")][-30:]
    labels = {o["value"]: o["label"] for qq in cs.QUESTIONS for o in qq["options"]}
    en = _read(ENROL_FILE, [])
    periods = _periods(en)
    latest = periods[-1] if periods else None
    by_theme = Counter()
    for r in en:
        if r["period"] == latest:
            by_theme[r["theme"]] += r["enrolments"]
    return {
        "updated": now_iso(),
        "rankings": {"employed": emp, "unemployed": une, "source": cs.qlfs().get("source"), "caveats": cs.qlfs().get("caveats", []),
                     "note": "Ranked by size of the QLFS category (Q2 2026). The official high-demand list records inclusion only and gives no graded rating."},
        "high_demand_list": {"total": len(occ), "jet_tagged": len(jet), "by_nqf": [{"label": f"NQF {k}", "count": nqf[k]} for k in sorted(nqf)],
                             "by_workstream": [{"label": cs.WORKSTREAMS[w], "count": n} for w, n in ws_counts.items()],
                             "source": "2024 National List of Occupations in High Demand (Government Gazette 50510)"},
        "questionnaire": {"tracked_since": ev["since"], "total": q["total"], "daily": daily,
                          "by_level": [{"label": labels.get(k, k), "count": v} for k, v in sorted(q["by_level"].items())],
                          "by_area": _ranked(Counter({cs.WORKSTREAMS.get(k, k): v for k, v in q["by_area"].items()})),
                          "by_route": _ranked(Counter({labels.get(k, k): v for k, v in q["by_route"].items()})),
                          "top_matches": [{"label": names.get(k, k), "count": v} for k, v in sorted(q["top_matches"].items(), key=lambda kv: -kv[1])[:10]]},
        "enrolments": {"has_data": bool(en), "periods": periods, "period": latest, "by_theme": [{"label": t, "count": by_theme[t]} for t in ENROL_THEMES if by_theme.get(t)],
                       "sources": sorted({(r["source_name"], r["source_url"], r["reporting_organisation"]) for r in en if r["period"] == latest}),
                       "template": "/api/dashboards/template/enrolments.csv"},
    }


def pipeline_dashboard(period=None):
    rows = _read(PIPELINE_FILE, [])
    periods = _periods(rows)
    period = period if period in periods else (periods[-1] if periods else None)
    sel = [r for r in rows if r["period"] == period]
    grid = {w: {s: 0 for s in STAGES} for w in WORKSTREAMS}
    for r in sel:
        grid[r["workstream"]][r["stage"]] += r["learners"]
    by_ws = [{"code": w, "name": WORKSTREAMS[w], **grid[w], "total": sum(grid[w].values()), "reported": any(r["workstream"] == w for r in sel)} for w in WORKSTREAMS]
    orgs = Counter(r["reporting_organisation"] for r in sel)
    return {
        "updated": now_iso(), "has_data": bool(rows), "periods": periods, "period": period,
        "stages": [{"code": k, "name": v} for k, v in STAGES.items()],
        "by_workstream": by_ws,
        "totals": {s: sum(grid[w][s] for w in WORKSTREAMS) for s in STAGES},
        "sources": [{"organisation": o, "rows": n} for o, n in sorted(orgs.items())],
        "records": [{k: r.get(k, "") for k in ("workstream", "stage", "learners", "reporting_organisation", "sdz", "source_name", "source_url", "status")} for r in sel],
        "coverage": {"workstreams_reporting": sum(1 for b in by_ws if b["reported"]), "of": len(WORKSTREAMS)},
        "template": "/api/dashboards/template/learner_pipeline.csv",
        "pending_candidates": len(candidates()),
        "notes": ["Figures are as reported by each organisation for the selected period. Stages are counts of learners at each stage, not a tracked cohort, so do not divide one stage by another to get a conversion rate.",
                  "Different organisations may count the same learner. Check the source list before summing across organisations.",
                  "Only aggregate counts are stored. No learner names or ID numbers are accepted."],
    }


# --------------------------------------------------------------------------
def _cli():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("templates")
    p = sub.add_parser("import"); p.add_argument("kind", choices=["learner_pipeline", "enrolments"]); p.add_argument("file")
    sub.add_parser("candidates")
    p = sub.add_parser("approve"); p.add_argument("id"); p.add_argument("--workstream", required=True); p.add_argument("--stage", required=True)
    p.add_argument("--period", required=True); p.add_argument("--count", required=True); p.add_argument("--org", required=True); p.add_argument("--sdz", default="")
    p = sub.add_parser("reject"); p.add_argument("id")
    a = ap.parse_args()
    if a.cmd == "templates":
        for k in ("learner_pipeline", "enrolments"):
            (DATA / "templates").mkdir(exist_ok=True); (DATA / "templates" / f"{k}_template.csv").write_text(template_csv(k), encoding="utf-8")
        print("Templates written to data/templates/")
    elif a.cmd == "import":
        res = (import_pipeline if a.kind == "learner_pipeline" else import_enrolments)(Path(a.file).read_text(encoding="utf-8-sig"))
        print(res)
    elif a.cmd == "candidates":
        for c in candidates():
            print(f"[{c['id']}] {c['number']:,} ({c['stage_guess']}, {c['workstream_guess'] or '?'}) {c['source_name']}\n    {c['sentence']}\n    {c['url']}")
    elif a.cmd == "approve":
        print(decide_candidate(a.id, "approve", {"workstream": a.workstream, "stage": a.stage, "period": a.period, "learners": a.count, "reporting_organisation": a.org, "sdz": a.sdz}))
    elif a.cmd == "reject":
        print(decide_candidate(a.id, "reject"))


if __name__ == "__main__":
    _cli()
