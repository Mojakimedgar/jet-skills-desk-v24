"""External-source harvester for the JET Skills Desk (Phase 2).

Pulls career, occupation, qualification and skills-news information from the
sources listed in data/sources.json, keeps provenance (URL + retrieval time)
for everything, and makes it searchable for the website and the chatbot.

Design rules
- Only domains listed in data/sources.json are ever contacted (allow-list).
- robots.txt is respected, requests are rate-limited, and private/internal
  addresses are blocked (SSRF protection).
- Official public records (gazettes, SAQA records, research reports) may be
  stored in full; news and commercial pages are stored as short excerpts with
  a link back to the original.
- Nothing is invented: if a source cannot be read, the previous data is kept
  and the failure is recorded in data/harvested/status.json.

Command line (run from the project folder):
    python harvester.py refresh                 # refresh every enabled source
    python harvester.py refresh --source news-sanews --force
    python harvester.py status
    python harvester.py query "solar installer nqf 4"
    python harvester.py saqa 120883             # live SAQA lookup
    python harvester.py add-url https://example.org/page --id my-page --name "My page"
"""
import argparse
import hashlib
import io
import ipaddress
import json
import math
import os
import re
import socket
import threading
import time
import urllib.robotparser
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from defusedxml import ElementTree as SafeET

ROOT = Path(__file__).parent
DATA = ROOT / "data"
HARVEST = DATA / "harvested"
CACHE = DATA / "harvest_cache"
SOURCES_FILE = DATA / "sources.json"
DOCS_FILE = HARVEST / "documents.json"
STATUS_FILE = HARVEST / "status.json"
OIHD_FILE = HARVEST / "oihd.json"
SAQA_FILE = HARVEST / "saqa.json"
QLFS_GROUPS_FILE = HARVEST / "qlfs_groups.json"
QLFS_CODES_FILE = HARVEST / "qlfs_codes.json"

for _d in (HARVEST, CACHE):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except OSError:  # read-only deployments simply run without a harvest store
        pass

_LOCK = threading.Lock()
MAX_BYTES = 25 * 1024 * 1024


class HarvestError(Exception):
    pass


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path, obj):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
def load_config():
    cfg = _read_json(SOURCES_FILE, {})
    cfg.setdefault("user_agent", "JETSkillsDeskBot/1.0")
    cfg.setdefault("min_interval_seconds", 1.5)
    cfg.setdefault("default_keywords", [])
    cfg.setdefault("sources", [])
    return cfg


def allowed_domains(cfg):
    domains = set(d.lower() for d in cfg.get("extra_allowed_domains", []))
    for s in cfg["sources"]:
        for key in ("url", "url_template"):
            if s.get(key):
                host = urlparse(s[key]).hostname
                if host:
                    domains.add(host.lower())
    return domains


# --------------------------------------------------------------------------
# Safe, polite fetching
# --------------------------------------------------------------------------
def _is_public_host(host):
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise HarvestError(f"cannot resolve {host}: {exc}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False
    return True


class Fetcher:
    def __init__(self, cfg=None, session=None, sleep=time.sleep):
        self.cfg = cfg or load_config()
        self.allowed = allowed_domains(self.cfg)
        self.ua = self.cfg["user_agent"]
        contact = self.cfg.get("contact")
        if contact:
            self.ua += f" (+{contact})"
        self.session = session or requests.Session()
        self.min_interval = float(self.cfg["min_interval_seconds"])
        self._last = {}
        self._robots = {}
        self._sleep = sleep

    # -- policy ------------------------------------------------------------
    def check(self, url):
        p = urlparse(url)
        host = (p.hostname or "").lower()
        if p.scheme not in ("http", "https") or not host:
            raise HarvestError(f"unsupported URL: {url}")
        if not any(host == d or host.endswith("." + d) for d in self.allowed):
            raise HarvestError(f"domain not in allow-list: {host}")
        if not _is_public_host(host):
            raise HarvestError(f"refusing non-public address for {host}")
        if not self._robots_ok(p, url):
            raise HarvestError(f"blocked by robots.txt: {url}")

    def _robots_ok(self, p, url):
        base = f"{p.scheme}://{p.netloc}"
        rp = self._robots.get(base)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.session.get(base + "/robots.txt", headers={"User-Agent": self.ua},
                                     timeout=10, allow_redirects=False)
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                elif r.status_code >= 500:
                    rp.disallow_all = True
                else:
                    rp.allow_all = True
            except requests.RequestException:
                rp.disallow_all = True
            self._robots[base] = rp
        return rp.can_fetch(self.ua, url)

    def _throttle(self, host):
        wait = self.min_interval - (time.time() - self._last.get(host, 0))
        if wait > 0:
            self._sleep(wait)
        self._last[host] = time.time()

    # -- fetching ----------------------------------------------------------
    def _request(self, url, headers):
        for _ in range(5):
            self.check(url)
            self._throttle(urlparse(url).hostname)
            r = self.session.get(url, headers=headers, timeout=20, stream=True, allow_redirects=False)
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
                url = urljoin(url, r.headers["Location"])
                r.close()
                continue
            return url, r
        raise HarvestError("too many redirects")

    def get(self, url, ttl_hours=24, force=False):
        """Return {url, final_url, content_type, body(bytes), fetched_at, from_cache, stale}."""
        key = hashlib.sha1(url.encode()).hexdigest()
        meta_path, body_path = CACHE / f"{key}.json", CACHE / f"{key}.bin"
        meta = _read_json(meta_path, None)
        have = meta is not None and body_path.exists()
        if have and not force:
            age_h = (time.time() - meta.get("fetched_ts", 0)) / 3600
            if age_h < ttl_hours:
                return self._cached(meta, body_path, True, False)
        headers = {"User-Agent": self.ua, "Accept": "text/html,application/xhtml+xml,application/xml,application/pdf;q=0.9,*/*;q=0.5"}
        if have and not force:
            if meta.get("etag"):
                headers["If-None-Match"] = meta["etag"]
            if meta.get("last_modified"):
                headers["If-Modified-Since"] = meta["last_modified"]
        try:
            final_url, r = self._request(url, headers)
            if r.status_code == 304 and have:
                meta["fetched_ts"], meta["fetched_at"] = time.time(), now_iso()
                _write_json(meta_path, meta)
                return self._cached(meta, body_path, True, False)
            if r.status_code != 200:
                r.close()
                raise HarvestError(f"HTTP {r.status_code} for {url}")
            body = bytearray()
            for chunk in r.iter_content(65536):
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    r.close()
                    raise HarvestError(f"response too large: {url}")
            meta = {"url": url, "final_url": final_url, "content_type": r.headers.get("Content-Type", ""),
                    "etag": r.headers.get("ETag"), "last_modified": r.headers.get("Last-Modified"),
                    "fetched_ts": time.time(), "fetched_at": now_iso()}
            body_path.write_bytes(bytes(body))
            _write_json(meta_path, meta)
            return self._cached(meta, body_path, False, False)
        except (HarvestError, requests.RequestException) as exc:
            if have:  # fall back to the last good copy rather than losing data
                return self._cached(meta, body_path, True, True)
            raise HarvestError(str(exc))

    @staticmethod
    def _cached(meta, body_path, from_cache, stale):
        out = dict(meta)
        out.update(body=body_path.read_bytes(), from_cache=from_cache, stale=stale)
        return out


def body_text(resp):
    m = re.search(r"charset=([\w-]+)", resp.get("content_type", ""), re.I)
    enc = m.group(1) if m else "utf-8"
    try:
        return resp["body"].decode(enc, "replace")
    except LookupError:
        return resp["body"].decode("utf-8", "replace")


# --------------------------------------------------------------------------
# Extractors
# --------------------------------------------------------------------------
def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def html_to_doc(html, url=""):
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript", "nav", "footer", "header", "form", "svg", "iframe"]):
        t.decompose()
    title = clean(soup.title.get_text()) if soup.title else ""
    h1 = soup.find("h1")
    if h1 and (not title or len(clean(h1.get_text())) > 8):
        title = clean(h1.get_text()) or title
    root = soup.find("main") or soup.find("article") or soup.body or soup
    text = clean(root.get_text(" "))
    return {"title": title or url, "text": text}


def pdf_to_text(data, max_pages=400):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    parts = []
    for i, page in enumerate(reader.pages):
        if i >= max_pages:
            break
        try:
            parts.append(page.extract_text() or "")
        except Exception:  # one unreadable page must not lose the whole document
            parts.append("")
    return "\n".join(parts)


def looks_like_feed(text):
    head = text.lstrip()[:400].lower()
    if head.startswith(("<rss", "<feed")):
        return True
    return head.startswith("<?xml") and any(tag in head for tag in ("<rss", "<feed", "<rdf"))


def discover_feeds(html, base_url):
    soup = BeautifulSoup(html, "lxml")
    out = []
    for link in soup.find_all("link", rel=lambda v: v and "alternate" in v):
        if re.search(r"(rss|atom)\+xml|text/xml|application/xml", link.get("type", ""), re.I) and link.get("href"):
            out.append(urljoin(base_url, link["href"]))
    return list(dict.fromkeys(out))


def parse_feed(xml_text, base_url=""):
    """RSS 2.0 / Atom -> [{title, link, published, summary}]"""
    root = SafeET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    strip = lambda tag: tag.split("}", 1)[-1]
    items = []
    for el in root.iter():
        if strip(el.tag) not in ("item", "entry"):
            continue
        row = {"title": "", "link": "", "published": "", "summary": ""}
        for ch in el:
            name = strip(ch.tag)
            if name == "title":
                row["title"] = clean("".join(ch.itertext()))
            elif name == "link":
                row["link"] = ch.get("href") or clean(ch.text)
            elif name in ("pubDate", "published", "updated", "date") and not row["published"]:
                row["published"] = clean(ch.text)
            elif name in ("description", "summary", "content", "encoded") and not row["summary"]:
                row["summary"] = clean(BeautifulSoup("".join(ch.itertext()), "lxml").get_text(" "))
        if row["title"] and row["link"]:
            row["link"] = urljoin(base_url, row["link"])
            items.append(row)
    return items


def scrape_links(html, base_url, keywords, limit=40):
    """Fallback for sites without a feed: headline-style links that match the keywords."""
    soup = BeautifulSoup(html, "lxml")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        text = clean(a.get_text(" "))
        href = urljoin(base_url, a["href"])
        if len(text) < 25 or len(text) > 220 or href in seen or urlparse(href).scheme not in ("http", "https"):
            continue
        if keywords and not any(k in text.lower() for k in keywords):
            continue
        seen.add(href)
        out.append({"title": text, "link": href, "published": "", "summary": ""})
        if len(out) >= limit:
            break
    return out


# -- OIHD gazette -----------------------------------------------------------
OFO_MAJOR_GROUPS = {
    "1": "Managers", "2": "Professionals", "3": "Technicians and Associate Professionals",
    "4": "Clerical Support Workers", "5": "Service and Sales Workers",
    "6": "Skilled Agricultural, Forestry, Fishery, Craft and Related Trades Workers",
    "7": "Plant and Machine Operators and Assemblers", "8": "Elementary Occupations",
}
_ROW = re.compile(r"^(20\d\d)-(\d{6})\s+(.*)$")
_QUAL_START = re.compile(
    r"\s(?=(?:Bachelor Honours Degree|Bachelor's Degree or Advanced Diploma|Diploma or Advanced Certificate|"
    r"Higher Certificate|National Certificate|Intermediate Certificate|Elementary Certificate|General Certificate|"
    r"Master's Degree|Doctoral Degree|No Formal Qualification Required|Private/Commercial/Airline Pilot's License|"
    r"Professional Driving Permit))")
_NOISE = re.compile(r"(This gazette is also available|STAATSKOERANT|GOVERNMENT GAZETTE|^\d{1,3}$|^6-Digit OFO|^code 6-Digit|^Table \d)", re.I)


def parse_oihd_gazette_text(text):
    """Parse the 'Final list of the National List of Occupations in High Demand' table.

    Returns [{ofo_code, ofo_version, name, qualification, nqf, essa_outlier, major_group}].
    Rows may wrap over several lines and pages; page furniture is ignored.
    """
    rows, cur = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _ROW.match(line)
        if m:
            if cur:
                rows.append(cur)
            cur = {"version": m.group(1), "code": m.group(2), "text": m.group(3)}
        elif _NOISE.search(line):
            if cur:
                rows.append(cur)
                cur = None
        elif cur:
            cur["text"] += " " + line
    if cur:
        rows.append(cur)
    out = []
    for r in rows:
        body = clean(r["text"])
        parts = _QUAL_START.split(body, maxsplit=1)
        if len(parts) != 2:
            continue
        # _QUAL_START has a lookahead only, so split() leaves the qualification text in parts[1]
        name, qual = clean(parts[0]), clean(parts[1])
        outlier = name.endswith("*")
        name = name.rstrip("*").strip()
        n = re.search(r"NQF Level (\d+)", qual)
        out.append({
            "ofo_code": r["code"], "ofo_version": r["version"], "name": name,
            "qualification": re.sub(r"\)\)$", ")", qual), "nqf": int(n.group(1)) if n else None,
            "essa_outlier": outlier, "major_group": OFO_MAJOR_GROUPS.get(r["code"][0], ""),
        })
    return out


# -- SAQA qualification record ---------------------------------------------
def parse_saqa_text(text, saqa_id=None):
    """Best-effort parse of a SAQA qualification page's text. Missing fields stay None."""
    t = re.sub(r"[ \t|]+", " ", text)
    t = re.sub(r"\s*\n\s*", "\n", t)
    rec = {"saqa_id": saqa_id, "title": None, "nqf": None, "credits": None,
           "quality_partner": None, "field": None, "purpose": None}
    m = re.search(r"SAQA QUAL ID\s+QUALIFICATION TITLE\s+(\d+)\s+(.+?)\s+ORIGINATOR", t, re.S)
    if m:
        rec["saqa_id"] = rec["saqa_id"] or m.group(1)
        rec["title"] = clean(m.group(2))
    m = re.search(r"ORIGINATOR\s+(?:Development Quality Partner\s*-\s*)?([^\n]+)", t)
    if m:
        rec["quality_partner"] = clean(m.group(1))
    m = re.search(r"MINIMUM CREDITS.*?QUAL CLASS\s+(.*?)NQF Level\s+0?(\d{1,2})\b", t, re.S)
    if m:
        nums = re.findall(r"\b(\d{1,4})\b", m.group(1))
        rec["credits"] = int(nums[0]) if nums else None
        rec["nqf"] = int(m.group(2))
    m = re.search(r"(Field \d+ - [^\n]+?)(?:\n|$)", t)
    if m:
        rec["field"] = clean(m.group(1))
    m = re.search(r"(The purpose of this (?:qualification|occupational certificate)[^\n]*?\.(?:\s[A-Z][^\n]*?\.)?)", t)
    if m:
        rec["purpose"] = clean(m.group(1))[:600]
    rec["parsed_ok"] = bool(rec["title"])
    return rec



# -- Statistics South Africa occupation groups / DataFirst QLFS occupation codes ---
def parse_statssa_groups(text):
    """'Occupational code list' page -> [{code (3 digits), label}]."""
    out = []
    for line in text.splitlines():
        m = re.match(r"^\s*(\d{3})\s+(\S.*?)\s*$", line)
        if m:
            out.append({"code": m.group(1), "label": m.group(2)})
    return out


def parse_datafirst_codes(text):
    """DataFirst variable page (Q42OCCUPATION) -> [{code (4 digits), label}] plus dataset metadata."""
    flat = re.sub(r"[\s|]+", " ", text)
    rows = re.findall(r"(?<!\d)(\d{4}) \1\. (.+?)(?= \d{4} \d{4}\. | Warning:|$)", flat)
    meta = {}
    m = re.search(r"zaf-[a-z0-9-]+-v\d+", flat, re.I)
    if m:
        meta["reference_id"] = m.group(0)
    m = re.search(r"10\.\d{4,5}/[\w.-]+", flat)
    if m:
        meta["doi"] = "https://doi.org/" + m.group(0)
    return [{"code": c, "label": clean(l)} for c, l in rows], meta

# --------------------------------------------------------------------------
# Source handlers: (source, fetcher, force) -> (documents, summary)
# --------------------------------------------------------------------------
def _doc(src, url, title, text, kind, published="", full=None):
    full = src.get("store_full", False) if full is None else full
    limit = int(src.get("max_chars", 250000)) if full else 600
    text = clean(text)
    return {
        "id": hashlib.sha1(url.encode()).hexdigest()[:12], "source_id": src["id"], "source_name": src["name"],
        "url": url, "title": clean(title)[:300] or url, "kind": kind, "published": published,
        "retrieved_at": now_iso(), "text": text[:limit], "stored": "full" if full else "excerpt",
        "theme": src.get("theme", ""),
    }



def _figures(src, text):
    """Dashboard data (plan 9.2): queue reported learner/intern/graduate counts for a person to verify.
    Nothing reaches the Learner Pipeline dashboard until it is approved (see analytics.py)."""
    if not src.get("extract_figures"):
        return ""
    import analytics
    found = analytics.extract_candidates(text, src)
    return f"; {len(found)} candidate figures found, {analytics.add_candidates(found)} new for review"

def handle_page(src, f, force):
    r = f.get(src["url"], src.get("ttl_hours", 168), force)
    d = html_to_doc(body_text(r), r["final_url"])
    return [_doc(src, src["url"], d["title"], d["text"], "page")], f"{len(d['text'])} characters read" + _figures(src, d["text"])


def handle_pdf(src, f, force):
    r = f.get(src["url"], src.get("ttl_hours", 720), force)
    text = pdf_to_text(r["body"], int(src.get("max_pages", 400)))
    if len(text) < 200:
        raise HarvestError("PDF had no extractable text")
    title = src.get("title") or src["name"]
    return [_doc(src, src["url"], title, text, "report")], f"{len(text)} characters from PDF" + _figures(src, text)


def handle_news(src, f, force):
    r = f.get(src["url"], src.get("ttl_hours", 6), force)
    html = body_text(r)
    kws = [k.lower() for k in src.get("keywords") or f.cfg["default_keywords"]]
    feeds = [r["final_url"]] if looks_like_feed(html) else discover_feeds(html, r["final_url"])
    items, how = [], "feed"
    for fu in feeds[:3]:
        try:
            fr = f.get(fu, src.get("ttl_hours", 6), force)
            items += parse_feed(body_text(fr), fu)
        except Exception:  # a broken feed should not stop the other feeds
            continue
    if not items:
        items, how = scrape_links(html, r["final_url"], kws), "page links"
    elif kws:
        items = [i for i in items if any(k in (i["title"] + " " + i["summary"]).lower() for k in kws)]
    items = items[: int(src.get("max_items", 25))]
    docs = [_doc(src, i["link"], i["title"], i["summary"] or i["title"], "news", i["published"], full=False) for i in items]
    return docs, f"{len(docs)} relevant items via {how}"


def handle_oihd(src, f, force):
    r = f.get(src["url"], src.get("ttl_hours", 720), force)
    occ = parse_oihd_gazette_text(pdf_to_text(r["body"]))
    if len(occ) < int(src.get("expect_min", 250)):
        raise HarvestError(f"only {len(occ)} occupations parsed; gazette layout may have changed")
    _write_json(OIHD_FILE, {"source_id": src["id"], "source_name": src["name"], "source_url": src["url"],
                            "retrieved_at": now_iso(), "count": len(occ), "occupations": occ})
    return [], f"{len(occ)} occupations parsed"


def handle_saqa(src, f, force):
    ids = [str(i) for i in (src.get("ids") or _read_json(DATA / "qualifications.json", {}).get("saqa_ids", []))]
    recs, docs, failed = [], [], []
    for sid in ids[: int(src.get("max_ids", 60))]:
        url = src["url_template"].format(id=sid)
        try:
            r = f.get(url, src.get("ttl_hours", 168), force)
            rec = parse_saqa_text(BeautifulSoup(body_text(r), "lxml").get_text("\n"), sid)
        except Exception as exc:
            failed.append(f"{sid}: {exc}")
            continue
        if rec["parsed_ok"]:
            rec.update(url=url, retrieved_at=now_iso())
            recs.append(rec)
            docs.append(_doc(src, url, f"SAQA {sid}: {rec['title']}",
                             " ".join(str(x) for x in (rec["title"], f"NQF level {rec['nqf']}", f"{rec['credits']} credits",
                                                         rec["quality_partner"], rec["field"], rec["purpose"]) if x),
                             "qualification", full=True))
        else:
            failed.append(f"{sid}: page layout not recognised")
    if recs:
        _write_json(SAQA_FILE, {"retrieved_at": now_iso(), "records": recs})
    return docs, f"{len(recs)} SAQA records read" + (f"; {len(failed)} problems: " + "; ".join(failed[:3]) if failed else "")


def handle_statssa_codes(src, f, force):
    r = f.get(src["url"], src.get("ttl_hours", 720), force)
    groups = parse_statssa_groups(BeautifulSoup(body_text(r), "lxml").get_text("\n"))
    if len(groups) < int(src.get("expect_min", 100)):
        raise HarvestError(f"only {len(groups)} occupation groups parsed; page layout may have changed")
    _write_json(QLFS_GROUPS_FILE, {"source_id": src["id"], "source_name": src["name"], "source_url": src["url"],
                                   "retrieved_at": now_iso(), "count": len(groups), "groups": groups})
    return [], f"{len(groups)} occupation groups read"


def handle_datafirst_codes(src, f, force):
    r = f.get(src["url"], src.get("ttl_hours", 720), force)
    codes, meta = parse_datafirst_codes(BeautifulSoup(body_text(r), "lxml").get_text("\n"))
    if len(codes) < int(src.get("expect_min", 300)):
        raise HarvestError(f"only {len(codes)} occupation codes parsed; page layout may have changed")
    _write_json(QLFS_CODES_FILE, {"source_id": src["id"], "source_name": src["name"], "source_url": src["url"],
                                  "retrieved_at": now_iso(), "count": len(codes), **meta, "codes": codes})
    doc = _doc(src, src["url"], src["name"], f"{src['name']}: {len(codes)} four-digit occupation codes (Q42OCCUPATION) used to classify employed people in the QLFS. " + " ".join(f"{c['code']} {c['label']}." for c in codes), "report", full=True)
    return [doc], f"{len(codes)} occupation codes read"


HANDLERS = {"page": handle_page, "pdf": handle_pdf, "news": handle_news,
            "oihd_gazette": handle_oihd, "saqa_qualifications": handle_saqa,
            "statssa_codes": handle_statssa_codes, "datafirst_codes": handle_datafirst_codes}


# --------------------------------------------------------------------------
# Refresh orchestration
# --------------------------------------------------------------------------
def refresh(source_ids=None, force=False, fetcher=None):
    with _LOCK:
        cfg = load_config()
        f = fetcher or Fetcher(cfg)
        docs = _read_json(DOCS_FILE, [])
        status = _read_json(STATUS_FILE, {})
        for src in cfg["sources"]:
            if not src.get("enabled", True) or (source_ids and src["id"] not in source_ids):
                continue
            try:
                new_docs, summary = HANDLERS[src["type"]](src, f, force)
                docs = [d for d in docs if d["source_id"] != src["id"]] + new_docs
                status[src["id"]] = {"ok": True, "ran_at": now_iso(), "documents": len(new_docs), "summary": summary}
            except Exception as exc:  # keep previous data for this source, record why
                prev = status.get(src["id"], {})
                status[src["id"]] = {"ok": False, "ran_at": now_iso(), "error": str(exc)[:300],
                                     "last_success": prev.get("ran_at") if prev.get("ok") else prev.get("last_success")}
        _write_json(DOCS_FILE, docs)
        _write_json(STATUS_FILE, status)
        _INDEX["mtime"] = None
        return status


def refresh_async(source_ids=None, force=False):
    t = threading.Thread(target=refresh, args=(source_ids, force), daemon=True)
    t.start()
    return t


def status():
    cfg = load_config()
    st = _read_json(STATUS_FILE, {})
    docs = _read_json(DOCS_FILE, [])
    counts = Counter(d["source_id"] for d in docs)
    return [{"id": s["id"], "name": s["name"], "type": s["type"], "enabled": s.get("enabled", True),
             "url": s.get("url") or s.get("url_template"), "documents": counts.get(s["id"], 0),
             **{k: v for k, v in st.get(s["id"], {}).items() if k != "documents"}} for s in cfg["sources"]]


def add_source(url, source_id, name, kind="page", **extra):
    cfg = _read_json(SOURCES_FILE, {"sources": []})
    if any(s["id"] == source_id for s in cfg["sources"]):
        raise HarvestError(f"source id already exists: {source_id}")
    cfg["sources"].append({"id": source_id, "name": name, "type": kind, "url": url, "enabled": True, **extra})
    _write_json(SOURCES_FILE, cfg)


# --------------------------------------------------------------------------
# Search over the harvested corpus (BM25 over text chunks, no extra services)
# --------------------------------------------------------------------------
_STOP = set("a an and are as at be by for from how in is it of on or the to what which with do does can i me my you your about tell".split())
_INDEX = {"mtime": None, "chunks": [], "df": Counter(), "avg": 1.0}


def tokens(s):
    return [t.rstrip("s") if len(t) > 3 else t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in _STOP and len(t) > 1]


def _chunks(text, size=700, step=600):
    text = clean(text)
    if len(text) <= size:
        return [text] if text else []
    return [text[i:i + size] for i in range(0, len(text), step)]


def _build_index():
    try:
        mtime = DOCS_FILE.stat().st_mtime
    except OSError:
        mtime = 0
    if _INDEX["mtime"] == mtime:
        return
    chunks, df = [], Counter()
    for d in _read_json(DOCS_FILE, []):
        for c in _chunks(d.get("text", "")) or [d.get("title", "")]:
            toks = tokens(d.get("title", "") + " " + c)
            chunks.append({"doc": d, "text": c, "tf": Counter(toks), "len": max(len(toks), 1)})
            df.update(set(toks))
    _INDEX.update(mtime=mtime, chunks=chunks, df=df, avg=(sum(c["len"] for c in chunks) / len(chunks)) if chunks else 1.0)


def search_corpus(query, limit=5, kinds=None):
    _build_index()
    q = tokens(query)
    if not q or not _INDEX["chunks"]:
        return []
    n, k1, b = len(_INDEX["chunks"]), 1.4, 0.75
    best = {}
    for ch in _INDEX["chunks"]:
        if kinds and ch["doc"]["kind"] not in kinds:
            continue
        score = 0.0
        for t in q:
            tf = ch["tf"].get(t, 0)
            if tf:
                idf = math.log(1 + (n - _INDEX["df"][t] + 0.5) / (_INDEX["df"][t] + 0.5))
                score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * ch["len"] / _INDEX["avg"]))
        if score > 0:
            did = ch["doc"]["id"]
            if did not in best or score > best[did][0]:
                best[did] = (score, ch)
    hits = sorted(best.values(), key=lambda x: -x[0])[:limit]
    return [{"title": c["doc"]["title"], "url": c["doc"]["url"], "source": c["doc"]["source_name"], "kind": c["doc"]["kind"],
             "published": c["doc"].get("published", ""), "retrieved_at": c["doc"]["retrieved_at"],
             "snippet": c["text"][:320] + ("…" if len(c["text"]) > 320 else ""), "score": round(s, 2)} for s, c in hits]


# --------------------------------------------------------------------------
# On-demand SAQA lookup (used by the chatbot for "SAQA 12345" questions)
# --------------------------------------------------------------------------
def lookup_saqa(saqa_id, fetcher=None):
    saqa_id = re.sub(r"\D", "", str(saqa_id))[:7]
    if not saqa_id:
        raise HarvestError("a numeric SAQA qualification ID is required")
    cfg = load_config()
    src = next((s for s in cfg["sources"] if s["type"] == "saqa_qualifications"), None)
    if not src:
        raise HarvestError("no SAQA source configured")
    url = src["url_template"].format(id=saqa_id)
    r = (fetcher or Fetcher(cfg)).get(url, src.get("ttl_hours", 168))
    rec = parse_saqa_text(BeautifulSoup(body_text(r), "lxml").get_text("\n"), saqa_id)
    if not rec["parsed_ok"]:
        raise HarvestError("SAQA page layout not recognised")
    rec.update(url=url, retrieved_at=r["fetched_at"])
    return rec


# --------------------------------------------------------------------------
def _cli():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("refresh"); p.add_argument("--source", action="append"); p.add_argument("--force", action="store_true")
    sub.add_parser("status")
    p = sub.add_parser("query"); p.add_argument("text"); p.add_argument("--limit", type=int, default=5)
    p = sub.add_parser("saqa"); p.add_argument("id")
    p = sub.add_parser("add-url"); p.add_argument("url"); p.add_argument("--id", required=True); p.add_argument("--name", required=True)
    p.add_argument("--type", default="page", choices=["page", "pdf", "news"])
    a = ap.parse_args()
    if a.cmd == "refresh":
        for sid, st in refresh(a.source, a.force).items():
            print(("OK   " if st["ok"] else "FAIL ") + sid, "-", st.get("summary") or st.get("error"))
    elif a.cmd == "status":
        for s in status():
            print(f"{'on ' if s['enabled'] else 'off'} {s['id']:<28} docs={s['documents']:<4} {s.get('summary') or s.get('error') or 'never run'}")
    elif a.cmd == "query":
        for h in search_corpus(a.text, a.limit):
            print(f"[{h['score']}] {h['title']}\n    {h['url']}  ({h['source']}, retrieved {h['retrieved_at']})\n    {h['snippet']}")
    elif a.cmd == "saqa":
        print(json.dumps(lookup_saqa(a.id), indent=1, ensure_ascii=False))
    elif a.cmd == "add-url":
        add_source(a.url, a.id, a.name, a.type)
        print("Added. Run: python harvester.py refresh --source", a.id)


if __name__ == "__main__":
    try:
        _cli()
    except HarvestError as exc:
        raise SystemExit(f"Harvest error: {exc}")
