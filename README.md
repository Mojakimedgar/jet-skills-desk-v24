# JET Skills Desk Website and Chatbot (Phase 1 + Phase 2)

This project combines the existing standalone Flask chatbot with relevant content from the supplied JET Skills Desk website preview.

## Included
- JET Skills Desk overview, mission, vision, values and mandate.
- JET Implementation Plan 2023–2027 Chapter 9 summary and five flagship interventions.
- Renewable Energy, New Energy Vehicles and Green Hydrogen workstreams, plus the municipal skills reference.
- Skills Development Zones in Mpumalanga, Northern Cape and Eastern Cape.
- Leadership names stated in the source preview and the existing intern profiles/photos.
- Partner links and the SETA directory from the supplied source.
- Research Repository search with collection, type, year, theme filters, synopses, keywords and copy-reference controls.
- Existing chatbot, enquiry form, local enquiry storage and configurable Microsoft 365 email notification.

## Run on Windows / PowerShell
1. Open this folder in VS Code.
2. Create a virtual environment if needed: `py -3.12 -m venv .venv`
3. Activate it: `.\.venv\Scripts\Activate.ps1`
4. Install packages: `python -m pip install -r requirements.txt`
5. Copy `.env.example` to `.env` and configure Microsoft Graph mail settings if approved credentials are available.
6. Start the website: `python app.py`
7. Open `http://127.0.0.1:5000` in a browser.

## API endpoints
- `GET /api/health` — health check.
- `GET /api/resources` — repository records loaded from `data/research_repository.json`.
- `POST /api/chat` — chatbot messages.
- `POST /api/enquiry` — records a visitor enquiry and attempts configured email notification.
- `GET /api/contact` — current project contact details.

## Important notes
- Research records are taken from the supplied HTML preview; the source describes the index as compiled in June 2026 and says full-document links will be added once the documents are hosted.
- The page's preview dates, statistics and programme milestones are reproduced from the supplied source and should be verified by the JET Skills Desk before public production release.
- The website does not invent downloadable research documents; it shows the references and synopses provided in the source index.
- Never commit `.env`, secrets, visitor enquiry records, or a virtual environment to Git.

## OpenAI chatbot (optional)
Add `OPENAI_API_KEY=sk-...` (and optionally `OPENAI_MODEL`) to `.env`, then run `python -m pip install -r requirements.txt` and restart. The chatbot then answers using OpenAI, grounded only in the site's approved content. If the key is missing, rate-limited or OpenAI is unreachable, it automatically falls back to the built-in answers. `GET /api/health` shows `"openai": true` when a key is configured. The key is used only on the server and is never sent to the browser.

#python -m waitress --listen=127.0.0.1:8000 app:app

## Phase 2: Career Guidance and Occupational Handbook
New pages (same header, footer, chat and styling as the home page):
- `/career-guidance`: guided questionnaire, the national list of occupations in high demand (350 occupations, OFO codes, minimum qualification/NQF level), a qualifications finder (filter by NQF level, type, workstream, status, quality partner) and an "external sources" search panel.
- `/occupational-handbook`: draft profiles of 19 priority occupations across Renewable Energy, New Energy Vehicles, Green Hydrogen and municipal skills, with related qualifications.
- The chatbot now answers questions about occupations, OFO codes, NQF levels, SAQA IDs and qualifications, and searches harvested external sources.

### Where the data comes from
| File | Content | Source |
|---|---|---|
| `data/occupations.json` | 350 occupations | 2024 National List of Occupations in High Demand, Government Gazette 50510 (parsed from the gazette). JET workstream tags are indicative drafts. |
| `data/qualifications.json` | 15 qualifications/programmes | Each entry cites its own source (SAQA, QCTO gazette, merSETA, news reports) and states its status. |
| `data/handbook.json` | 19 handbook entries | Draft summaries for workstream-lead review. |
| `data/sources.json` | external sources to harvest | Edit this to add or disable sources. |

The official list records that an occupation is in high demand; it does not give a graded demand rating, so none is shown. Provider/institution filters appear automatically once qualification records contain `providers`.

### Harvesting information from external sources
```
python harvester.py refresh                       # all enabled sources
python harvester.py refresh --source news-sanews --force
python harvester.py status                        # what was read, and what failed
python harvester.py query "solar installer nqf 4" # search what was harvested
python harvester.py saqa 120883                   # live SAQA lookup
python harvester.py add-url https://... --id my-page --name "My page" --type page
python scripts/build_seed.py                      # rebuild occupations/handbook after a refresh
```
- Only domains in `data/sources.json` are contacted; `robots.txt` is respected; requests are rate-limited; private/internal addresses are blocked.
- Official records may be stored in full; news and commercial pages are stored only as short excerpts with a link and the date they were read.
- If a source fails, the previous data is kept and the failure is shown by `python harvester.py status`.
- When DHET publishes the 2026 list of occupations in high demand, change the gazette URL in the `oihd-2024-gazette` source and run a refresh.
- Optional web trigger: set `HARVEST_ADMIN_TOKEN` in `.env`, then `POST /api/harvest/refresh` with header `X-Admin-Token`. Disabled when the token is empty.
- Run the offline tests with `python -m unittest discover -s tests -v`.


## Phase 2 additions: Northern Cape launch and labour-market data
- **Northern Cape SDZ** (launched 19 November 2026): card, launch article, photo slideshow (8 photos), Premier's video, news item and workplan entry, in the same format as Mpumalanga. Photos are in `static/images/nc-launch/` (`nc-launch-01.jpg` to `-08.jpg`; the slideshow handles any number, so add more `<figure class="ss-slide">` items in `templates/index.html`). The video and its poster are in `static/video/`.
- **Labour market data** (no longer a section on the Career Guidance page; it feeds the Career Guidance Analytics dashboard, the chatbot and `/api/careers/labour-market`): QLFS Q2 2026 employment and unemployment for the 57 JET priority occupations, by province, from `data/source/JET_Priority_Occupations_QLFS_Data_version2.xlsx`. Rebuild with `python scripts/build_qlfs.py [workbook.xlsx]` when a new quarter's workbook is ready. The workbook's methodology and cautions are shown beside the table.
- **New harvest sources** (`data/sources.json`): the StatsSA occupational code list (`statssa-occupation-codes`) and the DataFirst QLFS 2026 Q2 `Q42OCCUPATION` code list (`datafirst-qlfs-occupation`). They keep the QLFS category names current.
- The chatbot answers questions such as "How many electricians are employed in the Northern Cape?" from this data, with the same cautions.


## Analytics dashboards (plan section 9.2)
Page: `/dashboards` (menu: Careers & Data). Three dashboards:
- **Research Analytics**: total records, content-type breakdown, ingestion trend, most-viewed artefacts (synopses opened and references copied), and the status of monitored external sources.
- **Career Guidance Analytics**: occupation rankings (QLFS Q2 2026 and the 2024 high-demand list), enrolments by green economy theme, questionnaire completions.
- **Learner Pipeline Analytics**: learners in training, internships and employment per workstream, by reporting period.

**Nothing is invented.** Enrolments and learner-pipeline figures stay empty until partners supply data or someone approves a harvested figure.

**Privacy.** Usage counters are totals only (no IP address, device, cookie or questionnaire answers are stored). Partner data is aggregate counts only; unknown columns such as names or ID numbers are rejected.

**How partner data gets in (the "manual or semi-automated data entry" in 9.2)**
1. Standard templates: `/api/dashboards/template/learner_pipeline.csv` and `/enrolments.csv` (also in `data/templates/`). Share these with SETAs, providers and workstream partners.
2. Import: `python analytics.py import learner_pipeline file.csv` (or `enrolments`), or `POST /api/dashboards/import` with `X-Admin-Token` (needs `HARVEST_ADMIN_TOKEN` in `.env`). An import is all-or-nothing and re-importing the same period/organisation replaces rather than duplicates.
3. Harvested candidates: sources in `data/sources.json` with `"extract_figures": true` (JET PMU quarterly report, NBI JET SEP) are scanned for sentences reporting learner, intern, graduate or job counts. Review them with `python analytics.py candidates`, then `approve` (with workstream, stage, period, count, organisation) or `reject`. Only approved figures reach the dashboard.

**Ingestion trend.** The repository file does not record when each artefact was added, so artefacts present when tracking began form a baseline; new artefacts are dated from the day they first appear. Data lives in `data/analytics/` and `data/reported/` (created on first use; back them up).


## Team photos
Put the original photo in `static/images/` (same file name as before to replace someone) and run **one** command:

    python scripts/whiten_team_backgrounds.py            # every person
    python scripts/whiten_team_backgrounds.py mercy.jpeg # just one

It frames the portrait identically (4:5, same head size), places the person on a pure white background and writes `static/images/team/<name>.jpg`, which is what the site shows. (`make_team_portraits.py` does the same.) The page adds a version number to each photo address, so a replaced photo appears straight away instead of an older cached copy.

For a **new person** or a photo framed very differently, add or adjust their entry in `PEOPLE` (where the face is) in `scripts/make_team_portraits.py`, and, if a cut-out looks wrong, hint shapes in `HINTS` in `scripts/whiten_team_backgrounds.py`. A plain, evenly lit backdrop and a photo taken from slightly further back give the cleanest result.


## Which version is running?
Open `http://localhost:5000/api/health` (or `/api/health` on your site): it shows `"build": "v14"`. The same value is in the page source (`<meta name="build" ...>`). If it shows an older build, you are running an old copy: stop the server (Ctrl+C), unzip the newest zip into a **new** folder, and start it from there. Pages are sent with `Cache-Control: no-cache`, and team photo addresses carry a version number, so replaced pages and photos appear straight away after a normal refresh.

## v15: learner-friendly redesign
- New skin: `static/css/learner.css` (loaded after `style.css`); fonts Outfit + Nunito from Google Fonts.
- Home page rebuilt: animated hero with career search, learner / student / lecturer cards, energy-path tiles, 3-step pathway, Skills Development Zones, light-themed Library, team, partners and the existing About / Mandate / Plan sections.
- `static/js/home.js`: scroll reveal, rotating search hints, chat shortcuts, reduced-motion support.
- `/career-guidance?q=solar` opens the occupations list pre-searched (used by the hero search).
- All ids, scripts, data and API routes are unchanged.

## v23
- Team photos: white backgrounds removed (transparent WebP cut-outs in static/images/team/) with soft colour backdrops. The original JPGs are kept in the same folder.
