"""Rebuild data/occupations.json and data/handbook.json.

Occupation facts (OFO code, name, minimum qualification, NQF level, ESSA flag) come
from the 2024 National List of Occupations in High Demand (Government Gazette 50510),
parsed from tests/fixtures/oihd_2024_table.txt or, after `python harvester.py refresh`,
from data/harvested/oihd.json.

The JET workstream tags, interest tags and handbook summaries below are the Desk's
editorial layer. They are INDICATIVE and marked as drafts for workstream-lead review.
Run:  python scripts/build_seed.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import harvester  # noqa: E402

GAZETTE = {
    "name": "2024 National List of Occupations in High Demand (Government Gazette 50510)",
    "url": "https://www.gov.za/sites/default/files/gcis_document/202404/50510gen2414.pdf",
    "published": "2024-04-16",
}

# code: (workstreams, relevance, interests)   RE / NEV / GH2 / MUN
J = {
 "642602": (["RE"], "core", ["hands_on", "electrical", "outdoors"]),
 "671101": (["RE", "NEV", "GH2", "MUN"], "core", ["hands_on", "electrical"]),
 "672107": (["RE"], "supporting", ["hands_on", "electrical"]),
 "671301": (["RE", "MUN"], "core", ["hands_on", "electrical", "outdoors"]),
 "671102": (["RE", "MUN"], "supporting", ["electrical", "planning"]),
 "215101": (["RE", "NEV", "GH2"], "core", ["analytical", "electrical"]),
 "215103": (["RE"], "core", ["analytical", "electrical"]),
 "215104": (["RE"], "core", ["analytical", "electrical"]),
 "311301": (["RE", "MUN"], "core", ["electrical", "hands_on", "analytical"]),
 "311303": (["RE", "MUN"], "core", ["analytical", "electrical", "planning"]),
 "215201": (["NEV"], "supporting", ["analytical", "electrical"]),
 "311401": (["NEV", "RE"], "supporting", ["electrical", "analytical"]),
 "672104": (["NEV"], "supporting", ["electrical", "hands_on"]),
 "672105": (["RE", "GH2"], "supporting", ["electrical", "hands_on", "chemical"]),
 "671203": (["NEV", "GH2"], "supporting", ["electrical", "mechanical", "hands_on"]),
 "121909": (["RE", "GH2", "MUN"], "supporting", ["planning", "people"]),
 "134901": (["RE", "GH2", "MUN"], "supporting", ["planning", "outdoors"]),
 "213302": (["RE", "GH2"], "supporting", ["analytical", "outdoors"]),
 "214301": (["RE", "GH2"], "supporting", ["analytical", "chemical"]),
 "121905": (["RE", "NEV", "GH2", "MUN"], "supporting", ["planning", "people"]),
 "242302": (["RE", "NEV", "GH2", "MUN"], "supporting", ["people", "planning"]),
 "226302": (["RE", "NEV", "GH2", "MUN"], "supporting", ["planning", "outdoors"]),
 "121206": (["RE", "NEV", "GH2", "MUN"], "supporting", ["planning", "people"]),
 "214401": (["NEV", "GH2", "RE"], "supporting", ["analytical", "mechanical"]),
 "214501": (["GH2"], "core", ["analytical", "chemical"]),
 "311101": (["GH2"], "supporting", ["chemical", "analytical", "hands_on"]),
 "211301": (["GH2"], "supporting", ["chemical", "analytical"]),
 "642607": (["GH2"], "core", ["hands_on", "mechanical"]),
 "651202": (["GH2", "RE", "NEV"], "supporting", ["hands_on", "mechanical"]),
 "651302": (["GH2"], "supporting", ["hands_on", "mechanical"]),
 "652302": (["NEV", "GH2"], "supporting", ["hands_on", "mechanical"]),
 "653303": (["GH2", "RE"], "supporting", ["hands_on", "mechanical"]),
 "311501": (["NEV", "GH2"], "supporting", ["mechanical", "analytical"]),
 "733204": (["GH2"], "supporting", ["outdoors", "hands_on"]),
 "653101": (["NEV"], "core", ["hands_on", "mechanical"]),
 "653109": (["NEV"], "supporting", ["hands_on", "mechanical"]),
 "671208": (["NEV"], "core", ["electrical", "hands_on"]),
 "311904": (["NEV"], "supporting", ["hands_on", "analytical"]),
 "214201": (["RE", "MUN"], "supporting", ["analytical", "outdoors", "planning"]),
 "132301": (["RE"], "supporting", ["planning", "people", "outdoors"]),
 "312202": (["RE", "GH2"], "supporting", ["planning", "mechanical"]),
 "216401": (["MUN"], "supporting", ["planning", "analytical"]),
 "121301": (["MUN"], "supporting", ["planning"]),
 "242202": (["MUN"], "supporting", ["planning", "analytical"]),
 "121903": (["MUN"], "supporting", ["planning"]),
}

# Handbook: code -> (plain-English summary, summary source, JET context)
DRAFT = "JET Skills Desk draft: for workstream-lead review"
H = {
 "642602": ("Plans and installs solar photovoltaic (PV) systems to meet customer needs, making sure installations meet regulatory and quality standards.", "SAQA 120883 purpose statement (paraphrased)", "Solar installation is a front-line skill for the Renewable Energy workstream."),
 "671101": ("Installs, tests, maintains and repairs electrical wiring, equipment and systems in buildings and industry.", DRAFT, "Electricians are needed across solar, charging, hydrogen plant and municipal work, so they appear in all four workstreams."),
 "671301": ("Builds and maintains overhead and underground power lines and related network equipment.", DRAFT, "Grid and transmission capacity supports renewable energy growth, including in Mpumalanga."),
 "311303": ("Assesses how energy is used in buildings and facilities and helps reduce consumption through audits and technical measures.", "QCTO qualification title: Energy Efficiency Technician (Energy Audit Technician)", "Energy efficiency is a cross-cutting transition skill for industry and municipalities."),
 "215104": ("Applies engineering knowledge at technologist level to design, test and improve energy systems.", DRAFT, "Technologist-level skills link plant, grid and renewable energy projects."),
 "215103": ("Designs and oversees energy systems and projects, including generation, efficiency and use of energy.", DRAFT, "Energy engineers shape renewable energy project design."),
 "215101": ("Designs, develops and oversees electrical systems and equipment, from generation and networks to industrial installations.", DRAFT, "A scarce professional skill relevant to renewable energy, EV infrastructure and hydrogen plants. The 2024 list flags a large number of registered unemployed in this occupation, so check local demand."),
 "671208": ("Installs, diagnoses and repairs the electrical and electronic systems of vehicles.", "QCTO qualification title: Transportation Electrician (Automotive Electrician)", "The current route into electric-vehicle electrical work while dedicated electromobility qualifications are developed."),
 "653101": ("Services, diagnoses and repairs motor vehicles and their mechanical systems.", DRAFT, "Motor mechanics will need top-up skills as electric and hybrid vehicles enter the fleet."),
 "671203": ("Installs, maintains and troubleshoots equipment that combines mechanical, electrical and electronic control systems.", DRAFT, "Mechatronics skills support automated manufacturing and plant systems."),
 "672104": ("Fits, tests and repairs electronic equipment and control systems.", DRAFT, "Supports electronic systems in vehicles, charging and power equipment."),
 "214501": ("Designs and optimises chemical and process plants and the processes that run in them.", DRAFT, "Process and chemical engineering underpins green hydrogen production."),
 "642607": ("Fabricates, installs and maintains piping systems for liquids and gases.", DRAFT, "Piping for hydrogen and other gases is central to hydrogen production and storage."),
 "672105": ("Installs, calibrates and maintains the instruments and control equipment used to measure and control industrial processes.", DRAFT, "Instrumentation and control skills support hydrogen plants and renewable energy facilities."),
 "651202": ("Joins metal parts and structures using welding processes.", DRAFT, "Welding is needed in plant construction, structures and equipment manufacturing."),
 "311101": ("Carries out laboratory and process testing to support chemical and related work.", DRAFT, "Supports quality and process monitoring in chemical and hydrogen operations."),
 "733204": ("Drives tankers that transport liquid or gas products by road.", DRAFT, "Hydrogen fuel transporters have been reported as already in short supply."),
 "226302": ("Promotes and monitors safe, healthy and environmentally sound practices in the workplace.", DRAFT, "Safety is critical on solar, grid, battery, hydrogen and vehicle-technology sites."),
 "242302": ("Plans and coordinates skills development in an organisation, including workplace skills plans and training.", DRAFT, "Connects employers with the skills system, which is the Desk's coordination role."),
}


def load_occupations():
    harvested = harvester._read_json(harvester.OIHD_FILE, None)
    if harvested and harvested.get("occupations"):
        return harvested["occupations"], harvested.get("source_url", GAZETTE["url"]), "harvested"
    text = (ROOT / "tests/fixtures/oihd_2024_table.txt").read_text(encoding="utf-8")
    return harvester.parse_oihd_gazette_text(text), GAZETTE["url"], "gazette fixture"


def main():
    occ, url, origin = load_occupations()
    out = []
    for o in occ:
        rec = {
            "ofo_code": o["ofo_code"], "ofo_version": o["ofo_version"], "name": o["name"],
            "major_group": o["major_group"], "qualification": o["qualification"], "nqf": o["nqf"],
            "in_oihd_2024": True, "essa_outlier": o["essa_outlier"],
            "source": {**GAZETTE, "url": url},
        }
        if o["ofo_code"] in J:
            ws, rel, interests = J[o["ofo_code"]]
            rec["jet"] = {"workstreams": ws, "relevance": rel, "interests": interests,
                          "mapping_status": "Indicative, to be confirmed by workstream leads"}
        out.append(rec)
    by = {o["ofo_code"]: o for o in out}
    hb = []
    for code, (summary, src, ctx) in H.items():
        o = by[code]
        hb.append({"ofo_code": code, "name": o["name"], "workstreams": o["jet"]["workstreams"],
                   "summary": summary, "summary_source": src, "jet_context": ctx,
                   "status": "Draft for workstream-lead review"})
    (ROOT / "data/occupations.json").write_text(json.dumps({
        "updated": "2026-11-21", "origin": origin, "count": len(out),
        "note": "Occupation names, OFO codes and minimum qualifications are from the official 2024 list. Minimum qualifications are sign-posts for skills planning, not employment requirements. The list records that an occupation is in high demand; it does not give a graded demand rating.",
        "occupations": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    (ROOT / "data/handbook.json").write_text(json.dumps({"updated": "2026-11-21", "entries": hb}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(out)} occupations ({origin}); {sum(1 for o in out if 'jet' in o)} JET-tagged; {len(hb)} handbook entries")
    missing = [c for c in list(J) + list(H) if c not in by]
    if missing:
        raise SystemExit(f"codes not in the gazette list: {missing}")


if __name__ == "__main__":
    main()
