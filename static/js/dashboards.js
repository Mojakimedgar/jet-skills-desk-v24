(function(){'use strict';
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=n=>Number(n||0).toLocaleString('en-ZA').replace(/\u00a0/g,' ');
const get=u=>fetch(u).then(r=>{if(!r.ok)throw new Error(r.status);return r.json()});
const safeUrl=u=>/^https?:\/\//i.test(u)?esc(u):'#';
const kpi=(v,l,note)=>`<div class="kpi"><strong>${esc(v)}</strong><span>${esc(l)}</span>${note?`<small>${esc(note)}</small>`:''}</div>`;
const empty=t=>`<p class="dash-empty">${esc(t)}</p>`;
/* horizontal bars: rows [{label,count}], optional second line */
function bars(rows,opt={}){
  if(!rows||!rows.length)return empty(opt.empty||'No data yet.');
  const max=Math.max(1,...rows.map(r=>r.count));
  return rows.map(r=>`<div class="bar-row"><span class="bar-label">${esc(r.label)}${r.sub?`<small>${esc(r.sub)}</small>`:''}</span><span class="bar-track" role="img" aria-label="${esc(r.label)}: ${num(r.count)}"><i style="width:${Math.max(1.5,r.count/max*100)}%"></i></span><span class="bar-val">${num(r.count)}${opt.pct&&r.share!=null?` <small>${r.share}%</small>`:''}</span></div>`).join('');
}
/* vertical columns */
function cols(rows,opt={}){
  if(!rows||!rows.length)return empty(opt.empty||'No data yet.');
  const max=Math.max(1,...rows.map(r=>r.count));
  const short=l=>opt.short&&/^\d{4}$/.test(l)?'\u2019'+l.slice(2):l;
  return `<div class="col-chart" role="list">${rows.map(r=>`<div class="col" role="listitem" title="${esc(r.label)}: ${num(r.count)}"><span class="col-val">${num(r.count)}</span><i style="height:${Math.max(2,r.count/max*100)}%"></i><span class="col-lab">${esc(short(r.label))}</span></div>`).join('')}</div>`;
}

/* ---------- 1. Research ---------- */
get('/api/dashboards/research').then(d=>{
  $('rKpis').innerHTML=kpi(num(d.total),'records in the repository')+kpi(d.by_group.length,'content types')+kpi(Math.round(d.with_synopsis/d.total*100)+'%','have a synopsis')+kpi(num(d.views.synopsis_total),'synopses opened',`since ${d.views.tracked_since}`);
  $('rGroups').innerHTML=bars(d.by_group,{pct:true});
  $('rThemes').innerHTML=bars(d.by_theme);
  $('rYears').innerHTML=cols(d.by_year,{short:true});
  const ing=d.ingestion,m=ing.monthly;
  $('rIngest').innerHTML=`<div class="ingest-base"><strong>${num(ing.baseline)}</strong><span>artefacts in the repository when tracking began (${esc(ing.tracking_since)})</span></div>`+(m.length?cols(m.map(x=>({label:x.month,count:x.new})))+`<p class="dash-sub">Artefacts added each month since tracking began. ${num(ing.total)} in total.</p>`:`<p class="dash-sub">No artefacts have been added since tracking began. Later additions will appear here month by month.</p>`)+`<p class="dash-sub">${esc(ing.baseline_note)}</p>`;
  $('rViewsNote').textContent=`Ranked by synopses opened. Counting began ${d.views.tracked_since}; ${num(d.views.copy_total)} reference${d.views.copy_total===1?' has':'s have'} been copied.`;
  $('rViews').innerHTML=d.views.top.length?d.views.top.map(v=>`<li><span class="rank-t">${esc(v.title)}<small>${esc(v.group)}${v.year?' · '+esc(v.year):''}</small></span><span class="rank-n">${num(v.synopsis)} <small>opened</small> · ${num(v.copy)} <small>copied</small></span></li>`).join(''):empty('No views recorded yet. Counts start when visitors open a synopsis in the Research Repository.');
  const h=d.harvest;$('rHarvest').textContent=h.sources?`${h.sources} sources are monitored (${h.ok} read successfully on the last run), holding ${num(h.documents)} documents with their original links.${h.last_run?' Last run: '+h.last_run.slice(0,10)+'.':' The harvester has not been run yet.'}`:'The harvester has not been run yet.';
}).catch(()=>{$('rKpis').innerHTML=empty('The research dashboard could not be loaded. Please refresh the page.')});

/* ---------- 2. Career guidance ---------- */
get('/api/dashboards/career-guidance').then(d=>{
  const q=d.questionnaire,e=d.enrolments,r=d.rankings;
  $('cKpis').innerHTML=kpi(num(d.high_demand_list.total),'occupations on the 2024 high-demand list')+kpi(num(d.high_demand_list.jet_tagged),'linked to JET workstreams')+kpi(num(q.total),'questionnaires completed',`since ${q.tracked_since}`)+kpi(e.has_data?num(e.by_theme.reduce((a,b)=>a+b.count,0)):'No data yet','enrolments reported',e.period?`period ${e.period}`:'');
  const rank=a=>a.map(c=>({label:c.label,count:c.count,sub:`${c.occupations.slice(0,3).join(', ')}${c.occupations.length>3?' and '+(c.occupations.length-3)+' more':''} · QLFS ${c.code}`}));
  $('cEmployed').innerHTML=bars(rank(r.employed.map(c=>({...c,count:c.employed}))));
  $('cUnemployed').innerHTML=bars(rank(r.unemployed.map(c=>({...c,count:c.unemployed}))));
  $('cNqf').innerHTML=cols(d.high_demand_list.by_nqf);
  $('cNqfNote').textContent=`All ${d.high_demand_list.total} occupations on the list, by the NQF level of their minimum qualification. Source: ${d.high_demand_list.source}.`;
  $('cWs').innerHTML=bars(d.high_demand_list.by_workstream);
  $('cEnrol').innerHTML=e.has_data?bars(e.by_theme)+`<p class="dash-sub">Period ${esc(e.period)}. Sources: ${e.sources.map(s=>s[1]?`<a href="${safeUrl(s[1])}" target="_blank" rel="noopener noreferrer">${esc(s[0])}</a>`:esc(s[0])).join('; ')}.</p>`:empty('No enrolment figures have been loaded yet.')+`<p class="dash-sub">Enrolments come from SETAs and training providers under data-sharing arrangements. Partners can report them with the <a href="${esc(e.template)}">standard enrolment template (CSV)</a>.</p>`;
  $('cQDaily').innerHTML=q.total?(q.daily.length>=3?cols(q.daily.map(x=>({label:x.date.slice(5),count:x.count}))):`<ul class="src-list">${q.daily.map(x=>`<li>${esc(x.date)}: <b>${num(x.count)}</b> completed</li>`).join('')}</ul>`)+`<p class="dash-sub">Completions per day, last 30 days with activity. Counting began ${esc(q.tracked_since)}.</p>`:empty('No questionnaires completed yet.');
  $('cQLevel').innerHTML=bars(q.by_level,{empty:'No data yet.'});
  $('cQArea').innerHTML=bars(q.by_area,{pct:true,empty:'No data yet.'});
  $('cQTop').innerHTML=bars(q.top_matches,{empty:'No data yet.'});
  $('cCaveats').innerHTML=r.caveats.concat([r.note]).map(c=>`<li>${esc(c)}</li>`).join('');
}).catch(()=>{$('cKpis').innerHTML=empty('The career guidance dashboard could not be loaded. Please refresh the page.')});

/* ---------- 3. Learner pipeline ---------- */
let period='';
function drawPipeline(d){
  const sel=$('pPeriod');
  if(d.periods.length){sel.disabled=false;sel.innerHTML=d.periods.slice().reverse().map(p=>`<option value="${esc(p)}"${p===d.period?' selected':''}>${esc(p)}</option>`).join('')}
  $('pLegend').innerHTML=d.stages.map(s=>`<span class="lg lg-${esc(s.code)}"><i></i>${esc(s.name)}</span>`).join('');
  $('pNotes').innerHTML=d.notes.map(n=>`<li>${esc(n)}</li>`).join('');
  if(!d.has_data){
    $('pKpis').innerHTML=kpi('No data yet','learners reported');
    $('pBars').innerHTML=empty('No learner pipeline data has been loaded yet. This view fills in once SETAs, providers and workstream partners report using the standard template, or once figures found by the harvester have been checked and approved.');
    $('pSources').innerHTML=d.pending_candidates?`<p class="dash-sub">${d.pending_candidates} candidate figures found in public reports are waiting for review.</p>`:empty('No reporting organisations yet.');return}
  $('pKpis').innerHTML=d.stages.map(s=>kpi(num(d.totals[s.code]),s.name.toLowerCase().replace('in ','learners in '))).join('')+kpi(`${d.coverage.workstreams_reporting} of ${d.coverage.of}`,'workstreams reporting');
  const max=Math.max(1,...d.by_workstream.map(w=>w.total));
  $('pBars').innerHTML=d.by_workstream.map(w=>`<div class="stack-row"><span class="bar-label">${esc(w.name)}${w.reported?'':'<small>No data reported</small>'}</span><span class="stack" role="img" aria-label="${esc(w.name)}: ${d.stages.map(s=>num(w[s.code])+' '+s.name.toLowerCase()).join(', ')}" style="width:${Math.max(w.total?4:0,w.total/max*100)}%">${d.stages.map(s=>w[s.code]?`<i class="seg seg-${esc(s.code)}" style="flex:${w[s.code]}" title="${esc(s.name)}: ${num(w[s.code])}"></i>`:'').join('')}</span><span class="bar-val">${num(w.total)}</span></div>${w.reported?`<div class="stack-detail">${d.stages.map(s=>`<span>${esc(s.name)}: <b>${num(w[s.code])}</b></span>`).join('')}</div>`:''}`).join('');
  $('pSources').innerHTML=`<ul class="src-list">${d.sources.map(s=>`<li>${esc(s.organisation)} <small>${s.rows} row${s.rows>1?'s':''}</small></li>`).join('')}</ul>`+`<details><summary>Show the reported rows</summary><div class="p2-table-wrap"><table class="p2-table"><thead><tr><th>Workstream</th><th>Stage</th><th>Learners</th><th>Organisation</th><th>Source</th></tr></thead><tbody>${d.records.map(r=>`<tr><td>${esc(r.workstream)}</td><td>${esc(r.stage)}</td><td>${num(r.learners)}</td><td>${esc(r.reporting_organisation)}${r.sdz?' <small>('+esc(r.sdz)+')</small>':''}</td><td>${r.source_url?`<a href="${safeUrl(r.source_url)}" target="_blank" rel="noopener noreferrer">${esc(r.source_name)}</a>`:esc(r.source_name)}</td></tr>`).join('')}</tbody></table></div></details>`;
}
const loadPipeline=()=>get('/api/dashboards/learner-pipeline'+(period?'?period='+encodeURIComponent(period):'')).then(drawPipeline).catch(()=>{$('pBars').innerHTML=empty('The learner pipeline dashboard could not be loaded. Please refresh the page.')});
$('pPeriod').addEventListener('change',e=>{period=e.target.value;loadPipeline()});
loadPipeline();
})();
