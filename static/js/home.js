/* Opening the site link must land on the top of Home, never part-way down at the Careers section. */
(function(){
  if(!document.getElementById('home')||location.hash)return;
  var nav=performance.getEntriesByType&&performance.getEntriesByType('navigation')[0];
  if(nav&&nav.type==='back_forward')return;          // keep the back button behaving normally
  if('scrollRestoration' in history)history.scrollRestoration='manual';
  window.scrollTo(0,0);
  window.addEventListener('pageshow',function(e){if(!e.persisted&&!location.hash)window.scrollTo(0,0)});
})();
/* Friendly touches: scroll reveal, rotating search hints, chat shortcuts, calm motion. */
(function(){
  var reduce=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  // pause SVG (SMIL) animation for people who prefer reduced motion
  if(reduce){document.querySelectorAll('.stage-scene svg').forEach(function(s){try{s.pauseAnimations()}catch(e){}})}
  // reveal on scroll
  var els=[].slice.call(document.querySelectorAll('.reveal'));
  if('IntersectionObserver' in window&&!reduce){
    var io=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target)}})},{rootMargin:'0px 0px -8% 0px'});
    els.forEach(function(el){io.observe(el)});
  }else{els.forEach(function(el){el.classList.add('in')})}
  // rotating placeholder in the career finder
  var q=document.getElementById('finderQ');
  if(q&&!reduce){
    var hints=['Try “solar installer”','Try “electrician”','Try “welder”','Try “chemical engineer”','Try “electric vehicle technician”'];var i=0;
    setInterval(function(){if(document.activeElement===q||q.value)return;i=(i+1)%hints.length;q.setAttribute('placeholder',hints[i])},2600);
  }
  // buttons that open the chat panel (app.js already sends the data-q question)
  document.querySelectorAll('[data-open-chat]').forEach(function(b){b.addEventListener('click',function(){var c=document.getElementById('chat');if(c)c.classList.remove('hidden')})});
  // news: featured story carousel + category filter
  var nf=document.querySelector('[data-news]');
  if(nf){
    var slides=[].slice.call(nf.querySelectorAll('.pf-slide')),dots=nf.querySelector('.pf-dots'),cur=0,timer=null,paused=reduce;
    slides.forEach(function(_,i){var d=document.createElement('button');d.type='button';d.setAttribute('role','tab');d.setAttribute('aria-label','Story '+(i+1));d.addEventListener('click',function(){show(i);stop()});dots.appendChild(d)});
    var tog=nf.querySelector('[data-news-toggle]');
    function show(i){cur=(i+slides.length)%slides.length;slides.forEach(function(s,k){s.classList.toggle('is-active',k===cur);s.setAttribute('aria-hidden',k===cur?'false':'true');[].forEach.call(s.querySelectorAll('a'),function(a){a.tabIndex=k===cur?0:-1})});[].forEach.call(dots.children,function(d,k){d.setAttribute('aria-selected',k===cur?'true':'false')})}
    function play(){if(timer)clearInterval(timer);timer=setInterval(function(){show(cur+1)},7000);paused=false;tog.setAttribute('aria-pressed','false');tog.textContent='❚❚';tog.setAttribute('aria-label','Pause stories')}
    function stop(){if(timer)clearInterval(timer);timer=null;paused=true;tog.setAttribute('aria-pressed','true');tog.textContent='▶';tog.setAttribute('aria-label','Play stories')}
    nf.querySelector('[data-news-prev]').addEventListener('click',function(){show(cur-1);stop()});
    nf.querySelector('[data-news-next]').addEventListener('click',function(){show(cur+1);stop()});
    tog.addEventListener('click',function(){paused?play():stop()});
    nf.addEventListener('mouseenter',function(){if(timer&&!paused){clearInterval(timer);timer=null}});
    nf.addEventListener('mouseleave',function(){if(!paused&&!timer)play()});
    nf.addEventListener('focusin',function(){if(timer){clearInterval(timer);timer=null}});
    show(0);if(reduce)stop();else play();
  }
  var pl=document.querySelector('.pulse-list');
  if(pl){
    var fb=pl.querySelectorAll('.pl-filters button'),items=pl.querySelectorAll('.pl-items li'),empty=pl.querySelector('.pl-empty');
    fb.forEach(function(b){b.addEventListener('click',function(){var c=b.dataset.cat,n=0;fb.forEach(function(x){x.setAttribute('aria-pressed',String(x===b))});items.forEach(function(li){var ok=c==='all'||li.dataset.cat===c;li.hidden=!ok;if(ok)n++});empty.hidden=n>0})});
  }
})();
