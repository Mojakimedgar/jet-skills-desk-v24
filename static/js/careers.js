(function(){'use strict';
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeUrl=u=>/^https?:\/\//i.test(u)?esc(u):'#';
const get=u=>fetch(u).then(r=>{if(!r.ok)throw new Error(r.status);return r.json()});
const debounce=(f,ms)=>{let t;return(...a)=>{clearTimeout(t);t=setTimeout(()=>f(...a),ms)}};
const opts=(sel,items,toVal,toLabel)=>{items.forEach(i=>{const o=document.createElement('option');o.value=toVal(i);o.textContent=toLabel(i);sel.appendChild(o)})};
let facets=null;

/* ---------- questionnaire ---------- */
get('/api/careers/questionnaire').then(qs=>{
  $('careerQuestions').innerHTML=qs.map(q=>`<fieldset class="p2-q"><legend>${esc(q.label)}${q.type==='multi'?' <small>(choose any)</small>':''}</legend><div class="p2-choices">${q.options.map((o,i)=>`<label class="choice"><input type="${q.type==='multi'?'checkbox':'radio'}" name="${esc(q.id)}" value="${esc(o.value)}"><span>${esc(o.label)}</span></label>`).join('')}</div></fieldset>`).join('');
}).catch(()=>{$('careerQuestions').innerHTML='<p class="note">The questionnaire could not be loaded. Please refresh the page.</p>'});
$('careerForm').addEventListener('submit',async e=>{
  e.preventDefault();const answers={};const f=new FormData($('careerForm'));
  ['areas','enjoy'].forEach(k=>answers[k]=f.getAll(k));['level','route'].forEach(k=>answers[k]=f.get(k));
  const err=$('careerError');err.hidden=true;
  try{
    const r=await fetch('/api/careers/match',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({answers})});const d=await r.json();
    if(!r.ok){err.textContent=d.error||'Something went wrong.';err.hidden=false;return}
    drawResults(d)}catch{err.textContent='The service is unavailable. Please try again later.';err.hidden=false}
});
$('careerReset').addEventListener('click',()=>{$('careerResults').hidden=true;$('careerError').hidden=true});
function drawResults(d){
  const box=$('careerResults');
  if(!d.results.length){box.innerHTML='<p class="note">No close matches yet. Try choosing more interests or work areas.</p>'}
  else box.innerHTML=`<h3>Your matches</h3><ol class="match-list">${d.results.map(r=>`<li class="match-card"><div class="match-head"><h4>${esc(r.name)}</h4><span class="chip">NQF ${esc(r.nqf)}</span></div><p class="match-meta">OFO ${esc(r.ofo_code)} · ${esc(r.workstreams.join(', '))}</p><p class="match-reach">${esc(r.reach)}.</p><p class="match-meta">USUAL MINIMUM: ${esc(r.qualification)}</p><ul class="match-why">${r.reasons.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>${r.essa_note?`<p class="p2-caution">${esc(r.essa_note)}</p>`:''}${r.qualifications.length?`<p class="match-quals"><b>Related qualifications:</b> ${r.qualifications.map(q=>`<a href="${safeUrl(q.url)}" target="_blank" rel="noopener noreferrer">${esc(q.title)}</a> <span class="badge">${esc(q.status_label)}</span>`).join('; ')}</p>`:''}${r.in_handbook?`<a class="text-link" href="/occupational-handbook#occ-${esc(r.ofo_code)}">Read the handbook entry ↗</a>`:''}</li>`).join('')}</ol><p class="note">${esc(d.disclaimer)}</p>`;
  box.hidden=false;box.scrollIntoView({behavior:'smooth',block:'start'});
}

/* ---------- occupations directory ---------- */
const _qp=(new URLSearchParams(location.search).get('q')||'').trim().slice(0,80);
const occ={q:_qp,ws:'',nqf:'',jet:!_qp,offset:0,items:[],total:0};
function occQuery(){const p=new URLSearchParams({limit:'30',offset:String(occ.offset)});if(occ.q)p.set('q',occ.q);if(occ.ws)p.set('ws',occ.ws);if(occ.nqf)p.set('nqf',occ.nqf);if(occ.jet)p.set('jet','1');return '/api/careers/occupations?'+p}
function drawOcc(){
  $('occCount').textContent=occ.total;$('occMore').hidden=occ.items.length>=occ.total;
  $('occResults').innerHTML=occ.items.length?occ.items.map(o=>`<li class="repo-record"><div class="repo-year">${o.nqf?'NQF '+esc(o.nqf):'No NQF'}</div><div class="repo-record-body"><h3>${esc(o.name)}</h3><div class="repo-tags"><span class="chip chip-green">OFO ${esc(o.ofo_code)}</span>${(o.jet?.workstreams||[]).map(w=>`<span class="chip">${esc(wsName(w))}</span>`).join('')}${o.essa_outlier?'<span class="chip">Check local demand</span>':''}</div><p class="repo-citation">Usual minimum qualification: ${esc(o.qualification)}</p>${o.jet?.relevance?`<p class="repo-citation">JET relevance: ${esc(o.jet.relevance)} (indicative)</p>`:''}</div></li>`).join(''):'<li class="repo-empty">No occupations match these filters.</li>';
}
const wsName=c=>(facets?.workstreams.find(w=>w.code===c)||{}).name||c;
async function loadOcc(append){
  try{const d=await get(occQuery());occ.total=d.total;occ.items=append?occ.items.concat(d.items):d.items;drawOcc()}
  catch{$('occResults').innerHTML='<li class="repo-empty">The occupation list could not be loaded. Please refresh the page.</li>'}
}
const occReload=()=>{occ.offset=0;loadOcc(false)};
$('occSearch').addEventListener('input',debounce(e=>{occ.q=e.target.value.trim();occReload()},250));
$('occWs').addEventListener('change',e=>{occ.ws=e.target.value;occReload()});
$('occNqf').addEventListener('change',e=>{occ.nqf=e.target.value;occReload()});
$('occJet').addEventListener('change',e=>{occ.jet=e.target.checked;occReload()});
if(_qp){$('occSearch').value=_qp;$('occJet').checked=false;setTimeout(()=>{const t=document.getElementById('occupations');if(t)t.scrollIntoView({behavior:'smooth',block:'start'})},500)}
$('occMore').addEventListener('click',()=>{occ.offset=occ.items.length;loadOcc(true)});
$('occClear').addEventListener('click',()=>{Object.assign(occ,{q:'',ws:'',nqf:'',jet:true});$('occSearch').value='';$('occWs').value='';$('occNqf').value='';$('occJet').checked=true;occReload()});

/* ---------- qualifications finder ---------- */
const qs={q:'',nqf:'',type:'',ws:'',status:'',partner:'',provider:''};
const qMap={qSearch:'q',qNqf:'nqf',qType:'type',qWs:'ws',qStatus:'status',qPartner:'partner',qProvider:'provider'};
function drawQuals(d){
  $('qCount').textContent=d.total;
  $('qResults').innerHTML=d.items.length?d.items.map(q=>`<article class="qual-card"><div class="qual-top"><span class="badge badge-${esc(q.status)}">${esc(q.status_label)}</span>${q.nqf?`<span class="chip">NQF ${esc(q.nqf)}</span>`:'<span class="chip">NQF level not stated</span>'}</div><h3>${esc(q.title)}</h3><p class="qual-meta">${esc(q.type)}${q.credits?' · '+esc(q.credits)+' credits':''}${q.quality_partner?' · '+esc(q.quality_partner):''}${q.saqa_id?' · SAQA '+esc(q.saqa_id):''}</p><p>${esc(q.status_note)}</p><p class="qual-meta">${q.workstream_names.map(esc).join(', ')}</p><p class="qual-source">Source: <a href="${safeUrl(q.source_url)}" target="_blank" rel="noopener noreferrer">${esc(q.source_name)}</a> · checked ${esc(q.verified_on)}</p></article>`).join(''):'<p class="note">No qualifications match these filters.</p>';
}
async function loadQuals(){
  const p=new URLSearchParams();Object.entries(qs).forEach(([k,v])=>{if(v)p.set(k,v)});
  try{drawQuals(await get('/api/careers/qualifications?'+p))}catch{$('qResults').innerHTML='<p class="note">Qualifications could not be loaded. Please refresh the page.</p>'}
}
Object.entries(qMap).forEach(([id,key])=>$(id).addEventListener(id==='qSearch'?'input':'change',id==='qSearch'?debounce(e=>{qs[key]=e.target.value.trim();loadQuals()},250):e=>{qs[key]=e.target.value;loadQuals()}));
$('qClear').addEventListener('click',()=>{Object.keys(qs).forEach(k=>qs[k]='');Object.keys(qMap).forEach(id=>$(id).value='');loadQuals()});

/* ---------- facets (fills the selects, notes and links) ---------- */
get('/api/careers/facets').then(f=>{
  facets=f;$('occTotal').textContent=f.counts.occupations;
  [ ['occWs'],['qWs'] ].forEach(([id])=>opts($(id),f.workstreams,w=>w.code,w=>w.name));
  [ 'occNqf','qNqf' ].forEach(id=>opts($(id),f.nqf_levels,n=>n.level,n=>`NQF ${n.level}: ${n.name}`));
  opts($('qType'),f.qualification_types,t=>t,t=>t);opts($('qStatus'),f.statuses,s=>s.code,s=>s.name);opts($('qPartner'),f.quality_partners,p=>p,p=>p);
  if(f.providers.length){$('qProviderWrap').hidden=false;opts($('qProvider'),f.providers,p=>p,p=>p)}
  $('occNote').textContent=f.note||'';$('qNote').textContent=f.qualifications_note||'';
  $('verifyLinks').innerHTML=f.verify_links.map(l=>`<li><a href="${safeUrl(l.url)}" target="_blank" rel="noopener noreferrer">${esc(l.label)} <span>↗</span></a></li>`).join('');
  drawOcc();
}).catch(()=>{});
loadOcc(false);loadQuals();


/* ---------- external sources panel (only shown once something has been harvested) ---------- */
get('/api/harvest/status').then(rows=>{const n=rows.reduce((a,r)=>a+(r.documents||0),0);if(n>0){$('external').hidden=false;$('extStatus').textContent=`${n} documents from ${rows.filter(r=>r.documents>0).length} sources.`}}).catch(()=>{});
$('extForm').addEventListener('submit',async e=>{
  e.preventDefault();const q=$('extQ').value.trim();if(!q)return;
  $('extResults').innerHTML='<li class="note">Searching…</li>';
  try{const d=await get('/api/harvest/search?q='+encodeURIComponent(q));
    $('extResults').innerHTML=d.results.length?d.results.map(h=>`<li class="ext-hit"><a href="${safeUrl(h.url)}" target="_blank" rel="noopener noreferrer"><b>${esc(h.title)}</b></a><span class="ext-meta">${esc(h.source)} · read ${esc((h.retrieved_at||'').slice(0,10))}${h.published?' · published '+esc(h.published):''}</span><p>${esc(h.snippet)}</p></li>`).join(''):'<li class="note">Nothing found in the monitored sources for that search.</li>'}
  catch{$('extResults').innerHTML='<li class="note">Search is unavailable right now. Please try again shortly.</li>'}
});
})();
