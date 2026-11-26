(function(){'use strict';
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeUrl=u=>/^https?:\/\//i.test(u)?esc(u):'#';
const WS={RE:'Renewable Energy',NEV:'New Energy Vehicles',GH2:'Green Hydrogen',MUN:'Municipal skills'};
const st={ws:'',q:'',items:[]};
function draw(){
  const q=st.q.toLowerCase();
  const rows=st.items.filter(e=>(!st.ws||e.workstreams.includes(st.ws))&&(!q||(e.name+' '+e.ofo_code).toLowerCase().includes(q)));
  $('hbCount').textContent=rows.length;
  $('hbGrid').innerHTML=rows.length?rows.map(e=>`<article class="hb-entry" id="occ-${esc(e.ofo_code)}"><div class="hb-top"><span class="badge">Draft</span>${e.nqf?`<span class="chip">NQF ${esc(e.nqf)}</span>`:''}</div><h3>${esc(e.name)}</h3><p class="hb-meta">OFO ${esc(e.ofo_version)}-${esc(e.ofo_code)} · ${e.workstream_names.map(esc).join(', ')}</p><p>${esc(e.summary)}</p><p class="hb-jet"><b>Why it matters for JET:</b> ${esc(e.jet_context)}</p><p class="hb-qual"><b>Usual minimum qualification (2024 list):</b> ${esc(e.qualification)}</p>${e.essa_outlier?'<p class="p2-caution">The 2024 list flags many registered unemployed work-seekers in this occupation. Check local demand.</p>':''}${e.related_qualifications.length?`<div class="hb-quals"><b>Related qualifications</b><ul>${e.related_qualifications.map(q=>`<li><a href="${safeUrl(q.url)}" target="_blank" rel="noopener noreferrer">${esc(q.title)}</a>${q.nqf?' · NQF '+esc(q.nqf):''} <span class="badge badge-${esc(q.status)}">${esc(q.status_label)}</span></li>`).join('')}</ul></div>`:'<p class="hb-qual note">No linked qualification is listed yet. See the qualifications finder.</p>'}<p class="hb-src">Summary source: ${esc(e.summary_source)}</p></article>`).join(''):'<p class="note">No entries match.</p>';
  highlight();
}
function highlight(){const id=location.hash.slice(1);if(!id)return;const el=document.getElementById(id);if(el){el.classList.add('is-target');setTimeout(()=>el.scrollIntoView({block:'center'}),50)}}
function filters(){
  const b=[['','All']].concat(Object.entries(WS));
  $('hbFilters').innerHTML=b.map(([c,l])=>`<button type="button" data-ws="${esc(c)}" aria-pressed="${c===st.ws}">${esc(l)}</button>`).join('');
}
$('hbFilters').addEventListener('click',e=>{const b=e.target.closest('[data-ws]');if(!b)return;st.ws=b.dataset.ws;filters();draw()});
$('hbSearch').addEventListener('input',e=>{st.q=e.target.value.trim();draw()});
filters();
fetch('/api/careers/handbook').then(r=>{if(!r.ok)throw 0;return r.json()}).then(d=>{st.items=d;draw()}).catch(()=>{$('hbGrid').innerHTML='<p class="note">The handbook could not be loaded. Please refresh the page.</p>'});
})();
