function toast(msg,type='info',duration=3000){const c=document.getElementById('toastContainer');if(!c)return;const t=document.createElement('div');t.className=`toast ${type}`;t.textContent=msg;c.appendChild(t);setTimeout(()=>{t.style.animation='toast-in .3s ease reverse';setTimeout(()=>t.remove(),300)},duration)}
function getLS(key,def=null){try{const v=localStorage.getItem(key);return v?JSON.parse(v):def}catch{return def}}
function setLS(key,val){try{localStorage.setItem(key,JSON.stringify(val))}catch{}}
const hamburger=document.getElementById('hamburger');
const mobileNav=document.getElementById('mobileNav');
const overlay=document.getElementById('overlay');
const navClose=document.getElementById('navClose');
if(hamburger)hamburger.addEventListener('click',()=>{mobileNav.classList.add('open');overlay.classList.add('show')});
if(navClose)navClose.addEventListener('click',closeMenu);
if(overlay)overlay.addEventListener('click',closeMenu);
function closeMenu(){mobileNav&&mobileNav.classList.remove('open');overlay&&overlay.classList.remove('show')}
const btt=document.getElementById('backToTop');
if(btt){window.addEventListener('scroll',()=>{btt.classList.toggle('show',window.scrollY>400)});btt.addEventListener('click',()=>window.scrollTo({top:0,behavior:'smooth'}))}
const navSearch=document.getElementById('navSearch');
const searchDropdown=document.getElementById('searchDropdown');
let searchTimer;
if(navSearch){
  navSearch.addEventListener('input',()=>{clearTimeout(searchTimer);const q=navSearch.value.trim();if(!q){searchDropdown.classList.remove('show');return}searchTimer=setTimeout(()=>fetchSearch(q),280)});
  navSearch.addEventListener('keydown',e=>{if(e.key==='Enter'){const q=navSearch.value.trim();if(q)location.href=`/search?q=${encodeURIComponent(q)}`}if(e.key==='Escape')searchDropdown.classList.remove('show')});
  document.addEventListener('click',e=>{if(!navSearch.contains(e.target)&&!searchDropdown.contains(e.target))searchDropdown.classList.remove('show')});
}
async function fetchSearch(q){try{const r=await fetch(`/api/search?q=${encodeURIComponent(q)}&limit=6`);const data=await r.json();renderSearchDropdown(data.novels||[],q)}catch{}}
function renderSearchDropdown(novels,q){if(!searchDropdown)return;if(!novels.length){searchDropdown.classList.remove('show');return}searchDropdown.innerHTML=novels.map(n=>`<div class="search-result-item" onclick="location.href='/novel/${n.slug}'"><img src="${n.cover_url||'/static/img/no-cover.svg'}" alt="" onerror="this.src='/static/img/no-cover.svg'"><div><div class="sri-title">${n.title}</div><div class="sri-meta">${n.author||'Unknown'} · ${n.total_chapters||0} ch</div></div></div>`).join('')+`<div class="search-see-all" onclick="location.href='/search?q=${encodeURIComponent(q)}'">See all results →</div>`;searchDropdown.classList.add('show')}
function novelCard(n){const badge=n.status==='completed'?`<span class="novel-card-badge badge-completed">Done</span>`:'';const rating=n.avg_rating?`<span class="novel-card-rating">★ ${parseFloat(n.avg_rating).toFixed(1)}</span>`:'';return`<div class="novel-card" onclick="location.href='/novel/${n.slug}'"><div class="novel-card-cover"><img src="${n.cover_url||'/static/img/no-cover.svg'}" alt="${n.title}" loading="lazy" onerror="this.src='/static/img/no-cover.svg'">${badge}${rating}<div class="novel-card-overlay"><div class="novel-card-overlay-btn">▶ Read</div></div></div><div class="novel-card-title">${n.title}</div><div class="novel-card-meta">${n.total_chapters?n.total_chapters+' ch':''}</div></div>`}
function featuredItem(n){return`<div class="featured-item" onclick="location.href='/novel/${n.slug}'"><img class="featured-item-cover" src="${n.cover_url||'/static/img/no-cover.svg'}" alt="${n.title}" onerror="this.src='/static/img/no-cover.svg'"><div class="featured-item-info"><div class="fi-title">${n.title}</div><div class="fi-author">${n.author||'Unknown'}</div><div class="fi-desc">${n.description?n.description.substring(0,120)+'...':''}</div><div class="fi-footer"><span class="tag-pill">${n.status==='completed'?'✅ Complete':'🔄 Ongoing'}</span><span class="tag-pill">📖 ${n.total_chapters||0} ch</span></div></div></div>`}
function loadHeroCards(novels){const hf=document.getElementById('heroFeatured');if(!hf||!novels.length)return;hf.innerHTML=novels.slice(0,5).map((n,i)=>`<div class="hero-card" onclick="location.href='/novel/${n.slug}'" ${i===0?'style="grid-row:span 2"':''}><img src="${n.cover_url||'/static/img/no-cover.svg'}" alt="${n.title}" loading="lazy" onerror="this.src='/static/img/no-cover.svg'"><div class="hero-card-overlay"><div class="hero-card-title">${n.title}</div></div></div>`).join('')}
async function loadHomepage(){
  if(!document.getElementById('recentlyUpdated'))return;
  try{
    const[r1,r2,r3,r4,r5,r6]=await Promise.all([fetch('/api/novels?sort=updated&limit=12'),fetch('/api/novels?sort=popular&limit=12'),fetch('/api/novels?sort=rating&limit=5'),fetch('/api/novels?status=completed&sort=rating&limit=12'),fetch('/api/novels?sort=popular&limit=5'),fetch('/api/stats')]);
    const[d1,d2,d3,d4,d5,d6]=await Promise.all([r1.json(),r2.json(),r3.json(),r4.json(),r5.json(),r6.json()]);
    const ru=document.getElementById('recentlyUpdated');if(ru&&d1.novels)ru.innerHTML=d1.novels.map(novelCard).join('');
    const pw=document.getElementById('popularWeek');if(pw&&d2.novels)pw.innerHTML=d2.novels.map(novelCard).join('');
    const ep=document.getElementById('editorsPicks');if(ep&&d3.novels)ep.innerHTML=d3.novels.map(featuredItem).join('');
    const cn=document.getElementById('completedNovels');if(cn&&d4.novels)cn.innerHTML=d4.novels.map(novelCard).join('');
    loadHeroCards(d5.novels||[]);
    const sn=document.getElementById('statNovels');const sc=document.getElementById('statChapters');
    if(sn&&d6.novels)sn.textContent=d6.novels.toLocaleString();
    if(sc&&d6.chapters)sc.textContent=d6.chapters>1000000?(d6.chapters/1000000).toFixed(1)+'M':(d6.chapters/1000).toFixed(0)+'K';
  }catch(e){console.error(e)}
}
function toggleLibrary(novelId){const lib=getLS('library',[]);const btn=document.getElementById('libraryBtn');const idx=lib.indexOf(novelId);if(idx===-1){lib.push(novelId);setLS('library',lib);if(btn){btn.textContent='✓ In Library';btn.classList.add('added')}toast('Added to library!','success');fetch('/api/library',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({novel_id:novelId})}).catch(()=>{})}else{lib.splice(idx,1);setLS('library',lib);if(btn){btn.textContent='+ Add to Library';btn.classList.remove('added')}toast('Removed from library','info')}}
function shareNovel(){const url=window.location.href;if(navigator.share){navigator.share({title:document.title,url}).catch(()=>{})}else{navigator.clipboard.writeText(url).then(()=>toast('Link copied!','success')).catch(()=>toast('Copy link from address bar','info'))}}
function switchTab(btn,tabId){try{document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));btn.classList.add('active');const panel=document.getElementById('tab-'+tabId);if(panel)panel.classList.add('active');if(tabId==='similar'&&window.NOVEL_ID)loadSimilar()}catch(e){console.error('switchTab error:', e)}}
async function loadSimilar(){const el=document.getElementById('similarNovels');if(!el||!window.NOVEL_ID||el.querySelector('.novel-card'))return;try{const r=await fetch(`/api/novels/${NOVEL_ID}/similar?limit=12`);const d=await r.json();el.innerHTML=(d.novels||[]).map(novelCard).join('')||'<div class="empty-state"><div class="empty-state-icon">🔍</div><p>No similar novels found</p></div>'}catch{el.innerHTML='<div class="empty-state"><div class="empty-state-icon">🔍</div><p>Failed to load similar novels</p></div>'}}
function expandDesc(){const dt=document.getElementById('descText');const eb=document.getElementById('expandBtn');if(dt&&eb){dt.classList.remove('clamped');eb.remove()}}
function detectAdblock(){const bait=document.createElement('div');bait.className='adsbygoogle';bait.style.cssText='position:absolute;top:-9999px;left:-9999px;width:1px;height:1px';document.body.appendChild(bait);setTimeout(()=>{const blocked=!bait.offsetHeight;bait.remove();if(blocked){const notice=document.getElementById('adblockNotice');if(notice)notice.classList.add('show')}},100)}
function filterChapters(q){document.querySelectorAll('#chapterList .chapter-item').forEach(item=>{const title=item.querySelector('.ci-title')?.textContent?.toLowerCase()||'';item.style.display=!q||title.includes(q.toLowerCase())?'':'none'})}
let chaptersReversed=false;
function sortChapters(){const list=document.getElementById('chapterList');if(!list)return;Array.from(list.querySelectorAll('.chapter-item')).reverse().forEach(item=>list.appendChild(item));chaptersReversed=!chaptersReversed}
let selectedRating=0;
function setRating(n){selectedRating=n;document.querySelectorAll('.star').forEach((s,i)=>s.classList.toggle('filled',i<n))}
async function submitReview(novelId){const text=document.getElementById('reviewText')?.value?.trim();if(!text){toast('Please write a review','error');return}if(!selectedRating){toast('Please select a rating','error');return}try{const r=await fetch(`/api/novels/${novelId}/reviews`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:text,rating:selectedRating})});if(r.ok){toast('Review posted!','success');document.getElementById('reviewText').value='';setRating(0)}else toast('Sign in to post a review','error')}catch{toast('Sign in to post a review','error')}}
document.addEventListener('DOMContentLoaded',()=>{
  loadHomepage();
  detectAdblock();
  if(window.NOVEL_ID){const lib=getLS('library',[]);const btn=document.getElementById('libraryBtn');if(btn&&lib.includes(NOVEL_ID)){btn.textContent='✓ In Library';btn.classList.add('added')}}
});
