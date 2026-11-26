"""Build data/qlfs.json from the JET priority-occupations QLFS workbook (Q2 2026).

Run:  python scripts/build_qlfs.py [path/to/workbook.xlsx]
The workbook's own Methodology sheet is carried into the output so the website can show
exactly what the figures do and do not mean.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data/source/JET_Priority_Occupations_QLFS_Data_version2.xlsx"

PROVINCES = [("WC", "Western Cape"), ("EC", "Eastern Cape"), ("NC", "Northern Cape"), ("FS", "Free State"),
             ("KZN", "KwaZulu-Natal"), ("NW", "North West"), ("GP", "Gauteng"), ("MP", "Mpumalanga"), ("LP", "Limpopo"), ("SA", "South Africa")]

# 3-digit occupation groups, from the Statistics South Africa "Occupational code list"
# (https://www.statssa.gov.za/?page_id=4528). `python harvester.py refresh` re-reads the full list.
GROUPS = {
    "122": "Production and Operations Managers/Department Managers", "123": "Other Managers/Department Managers",
    "213": "Computing Professionals", "214": "Architects, Engineers and Related Professionals",
    "221": "Life Science Professionals", "241": "Business Professionals", "242": "Legal Professionals",
    "244": "Social Science and Related Professionals", "311": "Natural and Engineering Science Technicians",
    "315": "Safety and Quality Inspectors", "341": "Finance and Sales Associate Professionals",
    "342": "Business Services Agents and Trade Brokers", "713": "Building Finishers and Related Trades Workers",
    "721": "Metal Moulders, Welders, Sheet-Metal Workers, Structural Metal Preparers and Related Trades Workers",
    "723": "Machinery Mechanics and Fitters", "724": "Electrical and Electronic Equipment Mechanics and Fitters",
    "811": "Mining and Mineral Processing Plant Operators", "816": "Power-Production and Related Plant Operators",
    "821": "Metal and Mineral-Products Machine Operators", "832": "Motor Vehicle Drivers and Related Workers",
    "931": "Mining and Construction Labourers", "932": "Manufacturing Labourers",
}


def main():
    wb = openpyxl.load_workbook(SRC, data_only=True)
    mapping = {}
    for r in wb["Mapping"].iter_rows(min_row=2, values_only=True):
        if not isinstance(r[1], (int, float)):  # header and cluster heading rows
            continue
        mapping[r[0].strip()] = {"qlfs_code": int(r[1]), "qlfs_label": (r[3] or "").strip(), "mapping": (r[4] or "").strip()}
    methodology = [{"item": i, "definition": d} for i, d in wb["Methodology"].iter_rows(min_row=2, values_only=True) if i and i != "Item"]
    provs = [p for p, _ in PROVINCES]

    def table(name):
        out = {}
        for r in wb[name].iter_rows(min_row=2, values_only=True):
            if r[0] and isinstance(r[1], (int, float)):
                out[r[0].strip()] = {"code": int(r[1]), **{p: int(v or 0) for p, v in zip(provs, r[2:12])}}
        return out
    emp, unemp = table("Employment"), table("Unemployment")
    assert set(emp) == set(unemp) == set(mapping), "sheets do not list the same occupations"

    ofo = {o["name"].lower(): o["ofo_code"] for o in json.loads((ROOT / "data/occupations.json").read_text(encoding="utf-8"))["occupations"]}
    by_code = defaultdict(list)
    for n, m in mapping.items():
        by_code[m["qlfs_code"]].append(n)
    rows = []
    for n, m in mapping.items():
        assert emp[n]["code"] == m["qlfs_code"] == unemp[n]["code"], n
        code = str(m["qlfs_code"])
        rows.append({
            "name": n, "qlfs_code": m["qlfs_code"], "qlfs_label": m["qlfs_label"], "mapping": m["mapping"],
            "mapping_class": "proxy" if "proxy" in m["mapping"].lower() else "exact",
            "group_code": code[:3], "group_label": GROUPS.get(code[:3], ""),
            "ofo_code": ofo.get(n.lower()), "shares_category_with": [x for x in by_code[m["qlfs_code"]] if x != n],
            "employed": {p: emp[n][p] for p in provs}, "unemployed": {p: unemp[n][p] for p in provs},
        })
    out = {
        "updated": "2026-11-21",
        "source": {
            "dataset": "Quarterly Labour Force Survey 2026, Quarter 2 (ZAF-STATSSA-QLFS-2026-Q2-V1)", "producer": "Statistics South Africa",
            "doi": "https://doi.org/10.25828/a0p1-2z26", "catalog_url": "https://www.datafirst.uct.ac.za/dataportal/index.php/catalog/1247",
            "variable_url": "https://www.datafirst.uct.ac.za/dataportal/index.php/catalog/1247/variable/F1/V75?name=Q42OCCUPATION",
            "code_list_url": "https://www.statssa.gov.za/?page_id=4528", "workbook": SRC.name},
        "methodology": methodology,
        "caveats": [
            "A figure of 0 means no figure is reported for that province in the workbook. The workbook does not say whether it is a true zero or too few survey respondents to estimate, so do not read 0 as 'no workers'.",
            "Several priority occupations share one QLFS category, so they show identical figures. Do not add occupations together: the same people would be counted more than once.",
            "Employment is by current occupation. Unemployment is by previous occupation, so it is not a count of vacancies or of people currently seeking one particular job.",
            "Closest/proxy matches are approximations and, as the workbook notes, should be reviewed before use in formal occupational-demand estimates."],
        "provinces": [{"code": c, "name": n} for c, n in PROVINCES], "rows": rows}
    (ROOT / "data/qlfs.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    linked = sum(1 for r in rows if r["ofo_code"])
    print(f"{len(rows)} occupations; {linked} linked to an OFO code; {sum(1 for r in rows if r['mapping_class']=='proxy')} proxy matches")
    print("Linked:", [r["name"] for r in rows if r["ofo_code"]])


if __name__ == "__main__":
    main()
