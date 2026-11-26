from flask import Flask, jsonify, render_template, request, url_for
from datetime import datetime, timezone
from pathlib import Path
import hmac
import json
import os
from dotenv import load_dotenv
from email_service import send_enquiry_email
import ai_service
import analytics
import career_service
import harvester

load_dotenv()

app = Flask(__name__)
DATA = Path(__file__).parent / "data"
DATA.mkdir(exist_ok=True)

FAQ = [
    ({"hello","hi","hey","morning","afternoon"}, "Hello. Welcome to the JET Skills Desk. I can help you find your way around this site. Ask me about workstreams, Skills Development Zones, careers and qualifications, the Research Repository, news, contact details or how to reach the team."),
    ({"workstream","workstreams","renewable","vehicle","vehicles","hydrogen","municipality","municipalities"}, "The JET Skills Desk works across three portfolio-aligned Workforce Skills Workstreams: Renewable Energy, New Energy Vehicles and Green Hydrogen, while municipal skills are also covered in Chapter 10 of the JET Implementation Plan. The workstreams map occupations, qualifications and training capacity needed by each value chain."),
    ({"sdz","zone","zones","skills development"}, "The JET Skills Desk works with three Skills Development Zones: Mpumalanga, focused on renewable energy and transmission (officially launched on 29 October 2026 in Nkangala by the Minister of Higher Education and Training, Mr Buti Manamela, and the Premier of Mpumalanga, Mr Mandla Ndlovu); Northern Cape, focused on green hydrogen (officially launched on 19 November 2026, with the Premier, Dr Zamani Saul, highlighting the province's green energy advantage, mineral resources and renewable energy potential, and the Acting Director-General of DHET, Ms Nadia Starr, stressing the alignment of skills development with industrial investment); and Eastern Cape, focused on new energy vehicles (launch date to be announced). Read the launch articles in the Skills Development Zones section."),
    ({"library","repository","resource","resources","document","documents","research"}, "The Research Repository contains research and learning artefacts with references, synopses, keywords, collection, type, theme and year information. You can search the repository and filter results by collection, type, year and theme. The source preview says full-document links will be added once documents are hosted."),
    ({"team","people","staff"}, "The supplied preview names Mamphokhu Khuluvhe, Leadership, JET Skills Desk, DHET, and Sean Fenn, Senior Technical Advisor, JET Skills Desk, DHET. The existing site also has team profiles and photographs for its listed interns."),
    ({"workplan","technical"}, "The preview workplan lists: June 2026, Research Repository index compiled; October 2026, landing page and repository preview; 19 November 2026, Northern Cape Skills Development Zone officially launched; 2026–2027, high-fidelity wireframes and costing; Career Guidance, Occupational Handbook and analytics dashboard pages available in preview; and 2027, subject to funding, further digital tools."),
    ({"news","updates"}, "The Northern Cape Skills Development Zone was officially launched on 19 November 2026, and the Mpumalanga Skills Development Zone on 29 October 2026 in Nkangala. Both launch articles, with photographs (and a video from the Northern Cape launch), are in the Skills Development Zones section. The Research Repository preview went live in October 2026."),
    ({"mission","vision","values"}, "The mission is to mainstream JET skills into the post-school education and training system so skills supply meets demand for a just and sustainable future. The vision is an agile, inclusive and coordinated skills ecosystem. Values listed in the source include sustainability, inclusivity, collaboration, innovation, integrity, empowerment and responsiveness."),
    ({"mandate","responsibilities","responsibility"}, "The Desk coordinates Skills Workstream forums, leads integrated skills planning, connects the three Skills Development Zones, reports progress to the JET National Skills Advisory Forum and JET Skills Steering Committee, liaises with the JET PMU, and curates research and labour-market intelligence."),
    ({"chapter","implementation","flagship"}, "The JET Implementation Plan 2023–2027 has a skills chapter (Chapter 9). The five flagship interventions listed in the source are establishing the skills ecosystem, Skills Development Zones, value-chain skills assessments, government capacity and foundational skills."),
    ({"partner","partners","seta","setas"}, "The Partners section links to DHET, HRDC, QCTO, the JET PMU, the Presidential Climate Commission, career and learning services, energy and research organisations, and the 21 SETAs listed in the supplied preview."),
    ({"instagram","linkedin","facebook","whatsapp","social"}, "You can find JET Skills Desk on Instagram, LinkedIn, Facebook and its WhatsApp Channel using the links in the Contact area and footer."),
    ({"career","careers","occupation","occupations","handbook","nqf","qualification","qualifications","ofo"}, "The site has a Career Guidance page (/career-guidance) with a guided questionnaire, a directory of occupations in high demand and a qualifications finder, and an Occupational Handbook page (/occupational-handbook) for priority JET occupations. Ask me about a specific occupation, an OFO code, an NQF level or a SAQA qualification ID."),
    ({"dashboard","dashboards","analytics","statistics","pipeline","learners","enrolments","enrollments"}, "The Analytics Dashboards page (/dashboards) has three views: Research Analytics (records, content types, ingestion trend, most-viewed artefacts), Career Guidance Analytics (occupation rankings, enrolments by green economy theme, questionnaire completions) and Learner Pipeline Analytics (learners in training, internships and employment per workstream). The learner pipeline and enrolment figures stay empty until SETAs, providers and partners share data; nothing is estimated."),
    ({"contact","email","human","person","agent","help","support"}, "I can record a request for the JET Skills Desk team. Please type: contact me: Your Name | your@email.com | your message"),
]

def bot_reply(message):
    text = message.lower().strip()
    words = set(text.replace('?', ' ').replace(',', ' ').replace('.', ' ').split())
    for keys, reply in FAQ:
        if keys & words or any(k in text for k in keys if ' ' in k):
            return reply, False
    return "I do not have an approved answer for that yet. I can help with the Desk mandate, mission, JET Implementation Plan, workstreams, Skills Development Zones, Research Repository, careers and occupations, qualifications, partners, workplan, news and contacting the team. If you need a person, type: contact me: Your Name | your@email.com | your message", True

BUILD = 'v24'   # shown at /api/health and in the page source (<meta name="build">) so you can tell which copy is running

@app.after_request
def no_stale_pages(resp):
    if resp.mimetype == 'text/html':
        resp.headers['Cache-Control'] = 'no-cache'      # the browser must check for a newer page every time
    return resp

@app.context_processor
def asset_helpers():
    """asset('images/team/x.jpg') -> /static/images/team/x.jpg?v=<file modified time>, so a replaced photo is never served from a stale browser cache."""
    def asset(filename):
        try: version = int((Path(app.static_folder) / filename).stat().st_mtime)
        except OSError: version = 0
        return url_for('static', filename=filename, v=version)
    return {'asset': asset, 'build': BUILD}

@app.get('/')
def home(): return render_template('index.html')

@app.get('/career-guidance')
def career_guidance(): return render_template('career_guidance.html')

@app.get('/occupational-handbook')
def occupational_handbook(): return render_template('occupational_handbook.html')

@app.get('/dashboards')
def dashboards(): return render_template('dashboards.html')

@app.get('/energy-paths')
def energy_paths(): return render_template('energy_paths.html')

@app.get('/near-you')
def near_you(): return render_template('near_you.html')

@app.get('/library')
def library(): return render_template('library.html')

@app.get('/team')
def team(): return render_template('team.html')

@app.get('/partners')
def partners(): return render_template('partners.html')

@app.get('/about')
def about(): return render_template('about.html')

@app.get('/api/resources')
def resources():
    recs = analytics.repository()
    return jsonify(recs) if recs else (jsonify([]), 500)

@app.post('/api/chat')
def chat():
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').strip()
    if not message: return jsonify({'error':'Message is required'}), 400
    if message.lower().startswith('contact me:'):
        raw=message.split(':',1)[1].strip(); parts=[p.strip() for p in raw.split('|')]
        if len(parts) != 3 or '@' not in parts[1]:
            return jsonify({'reply':'Please use: contact me: Your Name | your@email.com | your message'})
        enquiry={'created_at':datetime.now(timezone.utc).isoformat(),'name':parts[0],'email':parts[1],'message':parts[2],'status':'new'}
        with (DATA/'enquiries.jsonl').open('a',encoding='utf-8') as f: f.write(json.dumps(enquiry)+'\n')
        return jsonify({'reply':'Thank you. Your enquiry has been recorded for the JET Skills Desk team. Email notification will be connected when the team mailbox is configured.','escalated':True})
    career = None
    try:
        career = career_service.chat_answer(message)
    except Exception as exc:
        app.logger.warning('Career lookup failed: %s', exc)
    if career and career['confidence'] == 'high':
        return jsonify({'reply':career['reply'],'fallback':False,'source':'careers'})
    if ai_service.enabled() and not ai_service.rate_limited(request.remote_addr or 'unknown'):
        try:
            reply = ai_service.ai_reply(message, data.get('history'), [r for _, r in FAQ], (career or {}).get('context'))
            return jsonify({'reply':reply,'fallback':False,'source':'openai'})
        except Exception as exc:
            app.logger.warning('OpenAI unavailable, using built-in answers: %s', exc)
    if career:
        return jsonify({'reply':career['reply'],'fallback':False,'source':'harvest'})
    reply, fallback=bot_reply(message)
    return jsonify({'reply':reply,'fallback':fallback,'source':'faq'})

@app.post('/api/enquiry')
def enquiry():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip()
    organisation = (data.get('organisation') or '').strip()
    phone = (data.get('phone') or '').strip()
    message = (data.get('message') or '').strip()
    if not name or '@' not in email or not message:
        return jsonify({'error':'Name, a valid email address and message are required.'}), 400
    item = {'created_at':datetime.now(timezone.utc).isoformat(),'name':name,'email':email,'phone':phone,'organisation':organisation,'message':message,'status':'new'}
    with (DATA/'enquiries.jsonl').open('a',encoding='utf-8') as f:
        f.write(json.dumps(item)+'\n')
    try:
        sent, detail = send_enquiry_email(item)
    except Exception as exc:
        sent, detail = False, str(exc)
    return jsonify({'ok':True,'email_sent':sent,'reply':'Thank you. Your enquiry has been recorded and sent to the JET Skills Desk team.' if sent else 'Thank you. Your enquiry has been recorded. Email notification is awaiting Microsoft 365 configuration.','detail':detail})

@app.get('/api/contact')
def contact_details():
    return jsonify({'name':'Papie Mojaki','phone':'0738643876','email':'Mojaki.P@Dhet.gov.za','organisation':'JET Skills Desk'})

# ---- Careers, occupations, qualifications, handbook ---------------------------------------
def _int(name, default=None, lo=None, hi=None):
    try:
        v = int(request.args.get(name, ''))
    except ValueError:
        return default
    return v if (lo is None or v >= lo) and (hi is None or v <= hi) else default

def _q():
    return (request.args.get('q') or '').strip()[:100]

@app.get('/api/careers/facets')
def careers_facets(): return jsonify(career_service.facets())

@app.get('/api/careers/occupations')
def careers_occupations():
    return jsonify(career_service.search_occupations(_q(), request.args.get('ws','')[:4], _int('nqf',None,1,10),
                   request.args.get('jet') == '1', _int('limit',40,1,100), _int('offset',0,0,10000)))

@app.get('/api/careers/qualifications')
def careers_qualifications():
    a = request.args
    return jsonify(career_service.search_qualifications(_q(), _int('nqf',None,1,10), a.get('type','')[:60], a.get('ws','')[:4],
                   a.get('status','')[:20], a.get('partner','')[:40], a.get('provider','')[:80]))

@app.get('/api/careers/labour-market')
def careers_labour_market():
    a = request.args
    return jsonify(career_service.labour_market(_q(), a.get('province','SA')[:4], a.get('mapping','')[:6], a.get('sort','employed')[:10]))

@app.get('/api/careers/handbook')
def careers_handbook(): return jsonify(career_service.handbook())

@app.get('/api/careers/questionnaire')
def careers_questionnaire(): return jsonify(career_service.QUESTIONS)

@app.post('/api/careers/match')
def careers_match():
    result = career_service.match((request.get_json(silent=True) or {}).get('answers'))
    if 'error' not in result:
        try: analytics.record_questionnaire(request.remote_addr or 'unknown', result['answers'], result['results'])
        except Exception as exc: app.logger.warning('Analytics counter failed: %s', exc)
    return jsonify(result), (400 if 'error' in result else 200)

# ---- Analytics dashboards (plan section 9.2) -------------------------------------------------------
@app.get('/api/dashboards/research')
def dash_research(): return jsonify(analytics.research_dashboard())

@app.get('/api/dashboards/career-guidance')
def dash_careers(): return jsonify(analytics.careers_dashboard())

@app.get('/api/dashboards/learner-pipeline')
def dash_pipeline(): return jsonify(analytics.pipeline_dashboard(request.args.get('period','')[:8]))

@app.post('/api/analytics/event')
def analytics_event():
    d = request.get_json(silent=True) or {}
    if d.get('type') == 'artefact':
        analytics.record_artefact(request.remote_addr or 'unknown', str(d.get('id',''))[:20], str(d.get('action',''))[:10])
    return '', 204

@app.get('/api/dashboards/template/<kind>.csv')
def dash_template(kind):
    if kind not in ('learner_pipeline', 'enrolments'): return jsonify({'error':'Unknown template'}), 404
    return analytics.template_csv(kind), 200, {'Content-Type':'text/csv; charset=utf-8','Content-Disposition':f'attachment; filename={kind}_template.csv'}

def _admin_only():
    if not os.getenv('HARVEST_ADMIN_TOKEN','').strip(): return jsonify({'error':'Disabled until HARVEST_ADMIN_TOKEN is set in .env.'}), 403
    if not _is_admin(): return jsonify({'error':'Not authorised.'}), 401
    return None

@app.post('/api/dashboards/import')
def dash_import():
    denied = _admin_only()
    if denied: return denied
    d = request.get_json(silent=True) or {}
    fn = {'learner_pipeline': analytics.import_pipeline, 'enrolments': analytics.import_enrolments}.get(d.get('kind'))
    if not fn: return jsonify({'error':'kind must be learner_pipeline or enrolments'}), 400
    try: res = fn(str(d.get('csv','')))
    except ValueError as exc: return jsonify({'error':str(exc)}), 400
    return jsonify(res), (400 if res['error_count'] else 200)

@app.get('/api/dashboards/candidates')
def dash_candidates():
    denied = _admin_only()
    return denied or jsonify(analytics.candidates())

@app.post('/api/dashboards/candidates/<cid>')
def dash_candidate_decide(cid):
    denied = _admin_only()
    if denied: return denied
    d = request.get_json(silent=True) or {}
    try: return jsonify(analytics.decide_candidate(cid[:20], str(d.get('action','')), d.get('fields')))
    except KeyError: return jsonify({'error':'Unknown candidate'}), 404
    except ValueError as exc: return jsonify({'error':str(exc)}), 400

# ---- External-source harvesting ------------------------------------------------------------
def _is_admin():
    token = os.getenv('HARVEST_ADMIN_TOKEN', '').strip()
    return bool(token) and hmac.compare_digest(request.headers.get('X-Admin-Token', ''), token)

@app.get('/api/harvest/status')
def harvest_status():
    rows = harvester.status()
    if not _is_admin():
        rows = [{k: v for k, v in r.items() if k != 'error'} for r in rows]
    return jsonify(rows)

@app.get('/api/harvest/search')
def harvest_search():
    q = _q()
    if not q: return jsonify({'error':'Provide a search term with ?q='}), 400
    if ai_service.rate_limited(request.remote_addr or 'unknown'): return jsonify({'error':'Too many requests. Please wait a minute.'}), 429
    return jsonify({'query':q,'results':harvester.search_corpus(q, _int('limit',5,1,10))})

@app.post('/api/harvest/refresh')
def harvest_refresh():
    if not os.getenv('HARVEST_ADMIN_TOKEN', '').strip():
        return jsonify({'error':'Refresh is disabled until HARVEST_ADMIN_TOKEN is set in .env.'}), 403
    if not _is_admin(): return jsonify({'error':'Not authorised.'}), 401
    data = request.get_json(silent=True) or {}
    ids = [str(x) for x in data.get('sources', [])][:20] if isinstance(data.get('sources'), list) else None
    harvester.refresh_async(ids, bool(data.get('force')))
    return jsonify({'started':True,'note':'Running in the background. Check /api/harvest/status.'}), 202

@app.get('/api/health')
def health(): return jsonify({'status':'ok','build':BUILD,'chatbot':'careers','openai':ai_service.enabled()})

if __name__ == '__main__':
    app.run(debug=False)
