"""Career Guidance and Occupational Handbook logic (Phase 2).

Data layers (all carry their source):
  data/occupations.json    official 2024 high-demand list + indicative JET workstream tags
  data/qualifications.json JET-relevant qualifications, each with a cited source and status
  data/handbook.json       draft handbook entries for priority JET occupations
  data/harvested/*.json    fresher values pulled by harvester.py, overlaid when present
"""
import json
import re
from pathlib import Path

import harvester

DATA = Path(__file__).parent / "data"

WORKSTREAMS = {"RE": "Renewable Energy", "NEV": "New Energy Vehicles", "GH2": "Green Hydrogen", "MUN": "Municipal skills"}
STATUS_LABELS = {
    "registered": "Registered on the NQF",
    "approved": "Approved by QCTO, awaiting accredited providers",
    "in_development": "In development",
    "draft": "Draft proposal",
    "check": "Confirm status with SAQA or QCTO",
}
NQF_LADDER = [
    (1, "General Certificate"), (2, "Elementary Certificate"), (3, "Intermediate Certificate"),
    (4, "National Certificate (matric / occupational certificate)"), (5, "Higher Certificate"),
    (6, "Diploma or Advanced Certificate"), (7, "Bachelor's Degree or Advanced Diploma"),
    (8, "Honours Degree, Postgraduate Diploma or Bachelor's Degree"), (9, "Master's Degree"), (10, "Doctoral Degree"),
]
VERIFY_LINKS = [
    {"label": "SAQA: search registered qualifications", "url": "https://regqs.saqa.org.za/"},
    {"label": "QCTO: occupational qualifications and accredited providers", "url": "https://www.qcto.org.za"},
    {"label": "Khetha: career information for learners", "url": "https://www.careerhelp.org.za"},
    {"label": "National Open Learning System", "url": "https://nols.gov.za"},
    {"label": "2024 National List of Occupations in High Demand (gazette)", "url": "https://www.gov.za/sites/default/files/gcis_document/202404/50510gen2414.pdf"},
    {"label": "Statistics South Africa: occupational code list", "url": "https://www.statssa.gov.za/?page_id=4528"},
    {"label": "DataFirst: QLFS 2026 Q2 occupation codes (Q42OCCUPATION)", "url": "https://www.datafirst.uct.ac.za/dataportal/index.php/catalog/1247/variable/F1/V75?name=Q42OCCUPATION"},
    {"label": "LMI: hydrogen economy skills report", "url": "https://lmi-research.org.za/publication/identification-of-skills-needed-for-the-hydrogen-economy"},
]

_cache = {}


def _load(path, default):
    """Read a JSON file, re-reading only when it changes."""
    try:
        mtime = Path(path).stat().st_mtime
    except OSError:
        return default
    hit = _cache.get(str(path))
    if hit and hit[0] == mtime:
        return hit[1]
    value = harvester._read_json(path, default)
    _cache[str(path)] = (mtime, value)
    return value


# --------------------------------------------------------------------------
# Datasets (seed + harvested overlay)
# --------------------------------------------------------------------------
def occupations():
    base = _load(DATA / "occupations.json", {})
    rows = {o["ofo_code"]: dict(o) for o in base.get("occupations", [])}
    fresh = _load(harvester.OIHD_FILE, {})
    for o in fresh.get("occupations", []):
        cur = rows.get(o["ofo_code"], {"ofo_code": o["ofo_code"], "in_oihd_2024": True})
        cur.update({k: o[k] for k in ("ofo_version", "name", "major_group", "qualification", "nqf", "essa_outlier")})
        cur["source"] = {"name": fresh.get("source_name"), "url": fresh.get("source_url"), "retrieved_at": fresh.get("retrieved_at")}
        rows[o["ofo_code"]] = cur
    return list(rows.values())


def qualifications():
    base = _load(DATA / "qualifications.json", {})
    out = [dict(q) for q in base.get("qualifications", [])]
    saqa = {r["saqa_id"]: r for r in _load(harvester.SAQA_FILE, {}).get("records", []) if r.get("saqa_id")}
    for q in out:
        rec = saqa.get(q.get("saqa_id") or "")
        if rec:
            for k in ("nqf", "credits", "quality_partner"):
                if rec.get(k) is not None:
                    q[k] = rec[k]
            q["verified_on"] = (rec.get("retrieved_at") or q["verified_on"])[:10]
            q["verified_by"] = "SAQA record read by the harvester"
        q["status_label"] = STATUS_LABELS.get(q["status"], q["status"])
        q["workstream_names"] = [WORKSTREAMS[w] for w in q.get("workstreams", []) if w in WORKSTREAMS]
    return out


def _tokens_match(text, q):
    toks = harvester.tokens(q)
    hay = set(harvester.tokens(text))
    return all(t in hay or any(h.startswith(t) for h in hay) for t in toks)


def search_occupations(q="", ws="", nqf=None, jet_only=False, limit=40, offset=0):
    rows = occupations()
    out = []
    for o in rows:
        if jet_only and "jet" not in o:
            continue
        if ws and ws not in o.get("jet", {}).get("workstreams", []):
            continue
        if nqf is not None and o.get("nqf") != nqf:
            continue
        if q and not _tokens_match(f"{o['name']} {o['ofo_code']} {o.get('qualification', '')} {o.get('major_group', '')}", q):
            continue
        out.append(o)
    out.sort(key=lambda o: (0 if "jet" in o else 1, 0 if o.get("jet", {}).get("relevance") == "core" else 1, o["name"]))
    return {"total": len(out), "items": out[offset:offset + limit]}


def search_qualifications(q="", nqf=None, qtype="", ws="", status="", partner="", provider=""):
    out = []
    for x in qualifications():
        if nqf is not None and x.get("nqf") != nqf:
            continue
        if qtype and x["type"] != qtype:
            continue
        if ws and ws not in x.get("workstreams", []):
            continue
        if status and x["status"] != status:
            continue
        if partner and (x.get("quality_partner") or "").split(" (")[0] != partner:
            continue
        if provider and provider not in x.get("providers", []):
            continue
        if q and not _tokens_match(f"{x['title']} {x.get('saqa_id') or ''} {x.get('quality_partner') or ''} {x['status_note']}", q):
            continue
        out.append(x)
    order = {"registered": 0, "approved": 1, "check": 2, "in_development": 3, "draft": 4}
    out.sort(key=lambda x: (order.get(x["status"], 9), x.get("nqf") or 99, x["title"]))
    return {"total": len(out), "items": out}


def facets():
    quals = qualifications()
    occ = occupations()
    providers = sorted({p for q in quals for p in q.get("providers", [])})
    return {
        "workstreams": [{"code": k, "name": v, "occupations": sum(1 for o in occ if k in o.get("jet", {}).get("workstreams", [])),
                         "qualifications": sum(1 for q in quals if k in q.get("workstreams", []))} for k, v in WORKSTREAMS.items()],
        "nqf_levels": [{"level": n, "name": name} for n, name in NQF_LADDER],
        "qualification_types": sorted({q["type"] for q in quals}),
        "quality_partners": sorted({(q.get("quality_partner") or "").split(" (")[0] for q in quals if q.get("quality_partner")}),
        "statuses": [{"code": k, "name": v} for k, v in STATUS_LABELS.items() if any(q["status"] == k for q in quals)],
        "providers": providers,  # empty until accredited-provider data is added or harvested
        "counts": {"occupations": len(occ), "jet_occupations": sum(1 for o in occ if "jet" in o), "qualifications": len(quals)},
        "occupations_origin": _load(DATA / "occupations.json", {}).get("origin"),
        "note": _load(DATA / "occupations.json", {}).get("note"),
        "qualifications_note": _load(DATA / "qualifications.json", {}).get("note"),
        "verify_links": VERIFY_LINKS,
        "provinces": qlfs().get("provinces", []), "labour_source": qlfs().get("source"),
    }


def handbook():
    by_code = {o["ofo_code"]: o for o in occupations()}
    quals = qualifications()
    entries = []
    for e in _load(DATA / "handbook.json", {}).get("entries", []):
        o = by_code.get(e["ofo_code"], {})
        e = dict(e)
        e.update(qualification=o.get("qualification"), nqf=o.get("nqf"), essa_outlier=o.get("essa_outlier", False),
                 ofo_version=o.get("ofo_version"), major_group=o.get("major_group"),
                 workstream_names=[WORKSTREAMS[w] for w in e["workstreams"]],
                 related_qualifications=[{"id": q["id"], "title": q["title"], "nqf": q.get("nqf"), "status": q["status"],
                                          "status_label": q["status_label"], "url": q["source_url"]}
                                         for q in quals if e["ofo_code"] in q.get("ofo_codes", [])])
        entries.append(e)
    entries.sort(key=lambda e: (e["workstreams"][0] if len(e["workstreams"]) == 1 else "ZZ", e["name"]))
    return entries



# --------------------------------------------------------------------------
# Labour-market data (QLFS Q2 2026, from the JET priority-occupations workbook)
# --------------------------------------------------------------------------
_PROV_ALIASES = {"western cape": "WC", "eastern cape": "EC", "northern cape": "NC", "free state": "FS", "kwazulu-natal": "KZN",
                 "kwazulu natal": "KZN", "kzn": "KZN", "north west": "NW", "gauteng": "GP", "mpumalanga": "MP", "limpopo": "LP",
                 "south africa": "SA", "nationally": "SA", "national": "SA"}


def _short(label):
    """Shorten a QLFS label at the first comma that follows a reasonably long first part."""
    i = label.find(", ", 25)
    return label[:i] if i > 0 else label


def qlfs():
    d = _load(DATA / "qlfs.json", {})
    groups = {g["code"]: g["label"] for g in _load(harvester.QLFS_GROUPS_FILE, {}).get("groups", [])}
    if groups:  # fresher official group names, when the harvester has read the StatsSA list
        d = dict(d, rows=[dict(r, group_label=groups.get(r["group_code"], r["group_label"])) for r in d.get("rows", [])])
    return d


def _prov_name(code):
    return next((p["name"] for p in qlfs().get("provinces", []) if p["code"] == code), code)


def labour_market(q="", province="SA", mapping="", sort="employed"):
    d = qlfs()
    if province not in {p["code"] for p in d.get("provinces", [])}:
        province = "SA"
    hb = {e["ofo_code"] for e in _load(DATA / "handbook.json", {}).get("entries", [])}
    items = []
    for r in d.get("rows", []):
        if mapping in ("exact", "proxy") and r["mapping_class"] != mapping:
            continue
        if q and not _tokens_match(f"{r['name']} {r['qlfs_label']} {r['qlfs_code']} {r['group_label']}", q):
            continue
        items.append({"name": r["name"], "qlfs_code": r["qlfs_code"], "qlfs_label": r["qlfs_label"], "mapping": r["mapping"],
                      "mapping_class": r["mapping_class"], "group_label": r["group_label"], "ofo_code": r["ofo_code"],
                      "in_handbook": r["ofo_code"] in hb, "shares_category_with": r["shares_category_with"],
                      "employed": r["employed"][province], "unemployed": r["unemployed"][province]})
    key = {"unemployed": lambda x: (-x["unemployed"], x["name"]), "name": lambda x: (x["name"],)}.get(sort, lambda x: (-x["employed"], x["name"]))
    items.sort(key=key)
    return {"province": province, "province_name": _prov_name(province), "total": len(items), "items": items,
            "provinces": d.get("provinces", []), "source": d.get("source"), "methodology": d.get("methodology", []), "caveats": d.get("caveats", [])}


def _phrases(row):
    import re as _re
    base = _re.sub(r"\s*\(.*?\)", "", row["name"]).lower()
    return {base, *[x.strip() for x in base.split("/") if len(x.strip()) >= 5]}


def _labour_reply(message):
    low = message.lower()
    prov = next((c for a, c in sorted(_PROV_ALIASES.items(), key=lambda kv: -len(kv[0])) if re.search(r"\b" + re.escape(a) + r"\b", low)), "SA")
    rows = qlfs().get("rows", [])
    hit, best = None, 0
    for r in rows:
        for ph in _phrases(r):
            if re.search(r"\b" + re.escape(ph) + r"s?\b", low) and len(ph) > best:
                hit, best = r, len(ph)
    pname = _prov_name(prov)
    tail = " Source: Statistics South Africa QLFS Q2 2026 (JET priority-occupations workbook). Employment is by current occupation; unemployment is by previous occupation. Details and cautions: /dashboards"
    if hit:
        e, u = hit["employed"][prov], hit["unemployed"][prov]
        where = "nationally" if prov == "SA" else f"in {pname}"
        parts = [f"{hit['name']} (QLFS category {hit['qlfs_code']}, {hit['qlfs_label']}; {hit['mapping'].lower()} match), {where}:"]
        parts.append(f"{e:,} employed." if e else "no employment figure is reported (this can mean too few survey respondents, not that nobody works in it).")
        parts.append(f"{u:,} unemployed people had previously worked in this category." if u else "no unemployed figure is reported.")
        if hit["shares_category_with"]:
            parts.append("This category is shared with " + ", ".join(hit["shares_category_with"]) + ", so do not add them together.")
        if hit["mapping_class"] == "proxy":
            parts.append("This is a closest/proxy match and should be reviewed before formal demand estimates.")
        return {"reply": " ".join(parts) + tail, "confidence": "high"}
    if prov != "SA" or re.search(r"labour market|labor market|qlfs|employment", low):
        seen, top = set(), []
        for r in sorted(rows, key=lambda r: -r["employed"][prov]):
            if r["qlfs_code"] in seen or not r["employed"][prov]:
                continue
            seen.add(r["qlfs_code"]); top.append(f"{_short(r['qlfs_label'])} ({r['qlfs_code']}): {r['employed'][prov]:,}")
            if len(top) == 5:
                break
        if top:
            where = "nationally" if prov == "SA" else f"in {pname}"
            return {"reply": f"Largest priority-occupation categories by employment {where} (QLFS Q2 2026): " + "; ".join(top) + "." + tail, "confidence": "high"}
    return None

# --------------------------------------------------------------------------
# Guided career questionnaire
# --------------------------------------------------------------------------
QUESTIONS = [
    {"id": "level", "type": "single", "label": "What is your highest completed qualification?", "options": [
        {"value": "3", "label": "Grade 9 to 11, or NQF Level 3 or below"},
        {"value": "4", "label": "Matric (NSC) or NQF Level 4"},
        {"value": "5", "label": "Higher Certificate (NQF Level 5)"},
        {"value": "6", "label": "Diploma or Advanced Certificate (NQF Level 6)"},
        {"value": "7", "label": "Bachelor's degree or Advanced Diploma (NQF Level 7)"},
        {"value": "8", "label": "Honours, Postgraduate Diploma or higher (NQF Level 8+)"}]},
    {"id": "areas", "type": "multi", "label": "Which parts of the energy transition interest you?", "options": [
        {"value": "RE", "label": "Solar, wind and electricity networks"},
        {"value": "NEV", "label": "Electric and hybrid vehicles"},
        {"value": "GH2", "label": "Green hydrogen and process plants"},
        {"value": "MUN", "label": "Local government and municipal services"}]},
    {"id": "enjoy", "type": "multi", "label": "What do you enjoy doing?", "options": [
        {"value": "hands_on", "label": "Working with my hands and tools"},
        {"value": "electrical", "label": "Electrical and electronic systems"},
        {"value": "mechanical", "label": "Machines and mechanical systems"},
        {"value": "chemical", "label": "Chemistry, laboratories and process plants"},
        {"value": "analytical", "label": "Maths, analysis and design"},
        {"value": "outdoors", "label": "Working outdoors or on site"},
        {"value": "people", "label": "Training, helping or managing people"},
        {"value": "planning", "label": "Planning, policy and organising"}]},
    {"id": "route", "type": "single", "label": "Which study route suits you best?", "options": [
        {"value": "trade", "label": "Artisan or trade (learnership, apprenticeship)"},
        {"value": "tvet", "label": "TVET college or occupational qualification"},
        {"value": "university", "label": "University of technology or university"},
        {"value": "any", "label": "I am open to any route"}]},
]
_VALID = {q["id"]: {o["value"] for o in q["options"]} for q in QUESTIONS}


def clean_answers(raw):
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for q in QUESTIONS:
        v = raw.get(q["id"])
        if q["type"] == "multi":
            v = [x for x in (v if isinstance(v, list) else []) if x in _VALID[q["id"]]][:8]
        else:
            v = v if isinstance(v, str) and v in _VALID[q["id"]] else None
        out[q["id"]] = v
    return out


def match(raw_answers, limit=8):
    a = clean_answers(raw_answers)
    if not a["level"]:
        return {"error": "Please tell us your highest completed qualification."}
    level = int(a["level"])
    labels = {o["value"]: o["label"] for q in QUESTIONS if q["id"] == "enjoy" for o in q["options"]}
    quals = qualifications()
    results = []
    for o in occupations():
        jet = o.get("jet")
        if not jet or o.get("nqf") is None:
            continue
        score, why = 0, []
        ws = [w for w in a["areas"] if w in jet["workstreams"]]
        if ws:
            score += min(6, 3 * len(ws))
            why.append("Works in " + " and ".join(WORKSTREAMS[w] for w in ws))
            if len(jet["workstreams"]) == 1:  # dedicated to the area you chose, rather than a generalist trade
                score += 1
        fit = [i for i in a["enjoy"] if i in jet["interests"]]
        if fit:
            score += 2 * len(fit)
            why.append("Fits what you enjoy: " + ", ".join(labels[i].lower() for i in fit))
        route, n = a["route"], o["nqf"]
        if (route == "trade" and n <= 4) or (route == "tvet" and 4 <= n <= 6) or (route == "university" and n >= 6):
            score += 2
            why.append("Matches your preferred study route")
        if score == 0:
            continue
        if jet["relevance"] == "core":
            score += 1
        gap = n - level
        if gap <= 0:
            score += 2
            reach = "You may already meet the usual minimum qualification"
        elif gap == 1:
            score += 1
            reach = "One qualification level above your current level"
        elif gap == 2:
            reach = "Two levels above your current level"
        else:
            score -= 1
            reach = "A longer pathway: several levels above your current level"
        results.append({
            "ofo_code": o["ofo_code"], "name": o["name"], "nqf": n, "qualification": o["qualification"],
            "workstreams": [WORKSTREAMS[w] for w in jet["workstreams"]], "reach": reach, "reasons": why, "score": score,
            "essa_note": "The 2024 list flags many registered unemployed work-seekers for this occupation, so check local demand." if o.get("essa_outlier") else None,
            "qualifications": [{"title": q["title"], "nqf": q.get("nqf"), "status_label": q["status_label"], "url": q["source_url"]}
                               for q in quals if o["ofo_code"] in q.get("ofo_codes", [])],
            "in_handbook": o["ofo_code"] in {e["ofo_code"] for e in _load(DATA / "handbook.json", {}).get("entries", [])},
        })
    results.sort(key=lambda r: (-r["score"], r["nqf"], r["name"]))
    return {"answers": a, "results": results[:limit],
            "disclaimer": "This is a guidance tool, not an assessment or a job offer. Minimum qualifications are sign-posts used for skills planning, not entry requirements. Speak to a career counsellor and confirm qualifications and accredited providers with SAQA or the QCTO."}


# --------------------------------------------------------------------------
# Chatbot retrieval
# --------------------------------------------------------------------------
_WS_WORDS = {"solar": "RE", "wind": "RE", "renewable": "RE", "vehicle": "NEV", "ev": "NEV", "electromobility": "NEV",
             "hydrogen": "GH2", "h2": "GH2", "municipal": "MUN", "municipality": "MUN"}
_CAREER_INTENT = re.compile(r"\b(career|careers|occupation|occupations|job|jobs|qualification|qualifications|course|courses|study|studying|train|training|learnership|apprentice\w*|artisan|nqf|ofo|saqa|qcto|high demand|in demand|become|handbook)\b", re.I)


def _fmt_qual(q):
    bits = [q["title"]]
    if q.get("nqf"):
        bits.append(f"NQF {q['nqf']}")
    if q.get("credits"):
        bits.append(f"{q['credits']} credits")
    bits.append(q["status_label"])
    return " | ".join(bits)


def _occupation_reply(o):
    quals = [q for q in qualifications() if o["ofo_code"] in q.get("ofo_codes", [])]
    entry = next((e for e in handbook() if e["ofo_code"] == o["ofo_code"]), None)
    lines = [f"{o['name']} (OFO {o['ofo_version']}-{o['ofo_code']}): the 2024 national list of occupations in high demand associates it with {o['qualification']}."]
    if entry:
        lines.append(entry["summary"])
    if o.get("jet"):
        lines.append("Related JET workstreams: " + ", ".join(WORKSTREAMS[w] for w in o["jet"]["workstreams"]) + " (indicative mapping).")
    if quals:
        lines.append("Related qualifications: " + "; ".join(_fmt_qual(q) for q in quals) + ".")
    if o.get("essa_outlier"):
        lines.append("Note: the list flags many registered unemployed work-seekers in this occupation, so check local demand.")
    row = next((r for r in qlfs().get("rows", []) if r["ofo_code"] == o["ofo_code"]), None)
    if row:
        lines.append(f"Labour market (QLFS Q2 2026, {row['mapping'].lower()} match to '{_short(row['qlfs_label'])}'): about {row['employed']['SA']:,} employed and {row['unemployed']['SA']:,} unemployed (previous occupation) nationally. Ask me about a province, or see /dashboards")
    lines.append("Minimum qualifications are sign-posts for skills planning, not employment requirements. Source: " + o["source"]["url"])
    return "\n".join(lines)


def chat_answer(message):
    """Return {reply, confidence, context} for career/qualification questions, or None.

    confidence 'high': a specific record matched; the reply is deterministic.
    confidence 'low' : only general matches; the caller may let the AI phrase the context.
    """
    text = message.strip()
    low = text.lower()

    # 1. SAQA ID
    m = re.search(r"\bsaqa(?:\s*(?:id|qual\w*|number|no\.?))?\s*#?\s*(\d{4,7})\b", low)
    if m:
        sid = m.group(1)
        for q in qualifications():
            if sid in [q.get("saqa_id")] + q.get("also_saqa_ids", []):
                return {"reply": f"SAQA {sid}: {_fmt_qual(q)}.\n{q['status_note']}\nSource: {q['source_url']} (checked {q['verified_on']}). Confirm accredited providers with the QCTO before enrolling.", "confidence": "high"}
        try:
            rec = harvester.lookup_saqa(sid)
            bits = [f"SAQA {sid}: {rec['title']}"] + [x for x in (f"NQF Level {rec['nqf']}" if rec["nqf"] else None, f"{rec['credits']} credits" if rec["credits"] else None, rec["quality_partner"]) if x]
            return {"reply": " | ".join(bits) + (f"\n{rec['purpose']}" if rec.get("purpose") else "") + f"\nRead live from SAQA on {rec['retrieved_at'][:10]}: {rec['url']}", "confidence": "high"}
        except Exception:
            return {"reply": f"I could not read SAQA record {sid} right now. You can look it up at https://regqs.saqa.org.za/ .", "confidence": "high"}

    # 2. OFO code
    m = re.search(r"\b(?:ofo\s*)?(?:20\d\d-)?(\d{6})\b", low)
    if m and ("ofo" in low or "occupation" in low or "code" in low):
        o = next((x for x in occupations() if x["ofo_code"] == m.group(1)), None)
        if o:
            return {"reply": _occupation_reply(o), "confidence": "high"}

    # 3. NQF level question
    m = re.search(r"\bnqf\s*(?:level)?\s*(\d{1,2})\b", low)
    if m and 1 <= int(m.group(1)) <= 10 and not re.search(r"\bsaqa\b", low):
        n = int(m.group(1))
        name = dict(NQF_LADDER)[n]
        jets = [o for o in occupations() if o.get("nqf") == n and "jet" in o]
        quals = [q for q in qualifications() if q.get("nqf") == n]
        parts = [f"NQF Level {n} corresponds to: {name}."]
        if jets:
            parts.append("JET-related occupations in the 2024 high-demand list at this level include " + ", ".join(o["name"] for o in jets[:8]) + ".")
        if quals:
            parts.append("Qualifications we list at this level: " + "; ".join(q["title"] for q in quals[:6]) + ".")
        parts.append("Browse more on the Career Guidance page: /career-guidance")
        return {"reply": "\n".join(parts), "confidence": "high"}

    # 3b. Labour-market questions (employment / unemployment / provinces)
    if re.search(r"\b(employ\w*|unemploy\w*|labour market|labor market|qlfs|how many|jobs? in|workers? in)\b", low):
        lm = _labour_reply(text)
        if lm:
            return lm

    # 4. Named occupation (longest name contained in the message)
    names = sorted((o for o in occupations() if len(o["name"]) >= 5), key=lambda o: -len(o["name"]))
    for o in names:
        if re.search(r"\b" + re.escape(o["name"].lower()) + r"s?\b", low):
            return {"reply": _occupation_reply(o), "confidence": "high"}

    # 5. Qualification / course questions by topic
    careerish = bool(_CAREER_INTENT.search(low))
    ws = {code for word, code in _WS_WORDS.items() if re.search(r"\b" + word + r"\b", low)}
    if careerish and ws:
        found = [q for q in qualifications() if ws & set(q.get("workstreams", []))]
        if re.search(r"\b(qualification|qualifications|course|courses|study|train|training|learnership)\b", low) and found:
            lines = [f"- {_fmt_qual(q)}" for q in found[:8]]
            return {"reply": "Qualifications and programmes we list for " + ", ".join(WORKSTREAMS[w] for w in sorted(ws)) + ":\n" + "\n".join(lines)
                    + "\nStatuses come from the cited sources. Confirm accredited providers with the QCTO. Full list: /career-guidance", "confidence": "high"}

    # 6. High-demand / handbook / guidance pointers
    if re.search(r"high demand|in demand|scarce|oihd", low):
        core = [o["name"] for o in occupations() if o.get("jet", {}).get("relevance") == "core"][:8]
        return {"reply": "The Department of Higher Education and Training publishes a national list of Occupations in High Demand. The 2024 list names 350 occupations, each with an OFO code and the minimum qualification usually associated with it. "
                         "JET-relevant examples: " + ", ".join(core) + ". It is not a scarce-skills list and does not give a graded rating. Browse it at /career-guidance", "confidence": "high"}
    if re.search(r"\bhandbook\b", low):
        return {"reply": "The Occupational Handbook page profiles priority JET occupations, with qualification levels and related qualifications: /occupational-handbook", "confidence": "high"}
    if re.search(r"career (guidance|advice|path|test|questionnaire)|which career|what career|what should i study", low):
        return {"reply": "Try the guided career questionnaire on the Career Guidance page (/career-guidance). It matches your qualification level, interests and study route to JET-related occupations and shows the qualifications linked to each.", "confidence": "high"}

    # 7. Harvested external sources
    if careerish or ws:
        hits = harvester.search_corpus(text, limit=3)
        hits = [h for h in hits if h["score"] >= 3.0]
        if hits:
            ctx = "\n".join(f"- {h['title']} ({h['source']}, retrieved {h['retrieved_at'][:10]}): {h['snippet']} [{h['url']}]" for h in hits)
            reply = "Here is what I found in the external sources the Desk monitors:\n" + ctx + "\nPlease check the original sources before relying on this."
            return {"reply": reply, "confidence": "low", "context": ctx}
    return None
