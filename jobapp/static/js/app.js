'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const debounce = (fn, ms=350) => { let timer; return (...args) => {clearTimeout(timer); timer=setTimeout(()=>fn(...args),ms);}; };
const names = {category:'Kategori',seniority:'Kıdem',workplace:'Çalışma biçimi',location:'Konum',company:'Şirket',skills:'Yetenek',flag:'İlan değerlendirmesi',backend:'Analiz yöntemi',source:'Kaynak',search_term:'Aranan unvan',search_location:'Aranan konum',search:'Arama',semantic:'Anlama göre arama',title:'Unvanda',description:'Açıklamada',company_text:'Şirket adında',phrase:'Tam ifade',exclude:'Hariç kelimeler',exclude_skills:'Hariç yetenekler',skill_mode:'Yetenek koşulu',salary_min:'En az maaş',salary_max:'En çok maaş',currency:'Para birimi',period:'Maaş dönemi',has_salary:'Maaş bilgisi',experience_min:'En az deneyim',experience_max:'En çok deneyim',experience_missing:'Deneyim bilinmiyor',run_id:'Çalışma',task_id:'Arama',discovery:'Bulunma türü',has_description:'Açıklama',has_summary:'Özet',has_embedding:'Eşleştirme verisi',quality:'Ayrıştırma kalitesi',visibility:'Görünürlük',posted_from:'Yayın başlangıcı',posted_to:'Yayın bitişi',posted_missing:'Yayın tarihi bilinmiyor',created_from:'İlk eklenme başlangıcı',created_to:'İlk eklenme bitişi',scraped_from:'Son tarama başlangıcı',scraped_to:'Son tarama bitişi'};
const translations = {Engineering:'Mühendislik / Yazılım',Data:'Veri ve yapay zekâ',Design:'Tasarım',Product:'Ürün',Finance:'Finans',Sales:'Satış',Marketing:'Pazarlama',HR:'İnsan kaynakları',Operations:'Operasyon',Other:'Diğer',Intern:'Stajyer',Junior:'Başlangıç',Mid:'Orta',Senior:'Kıdemli',Lead:'Lider',Manager:'Yönetici',Unknown:'Belirtilmemiş',Remote:'Uzaktan',Hybrid:'Hibrit',Onsite:'Ofiste',Office:'Ofiste',rules:'Hızlı analiz',local:'Yerel yapay zekâ',llm:'Bulut yapay zekâ',claude:'Bulut yapay zekâ',scam:'Şüpheli ilan',ghost:'Aktifliği şüpheli',clean:'İşaretlenmemiş',__missing__:'Belirtilmemiş',queued:'Bekliyor',running:'Çalışıyor',pausing:'Duraklatılıyor',paused:'Duraklatıldı',stopping:'Durduruluyor',stopped:'Durduruldu',cancelling:'İptal ediliyor',cancelled:'İptal edildi',finished:'Tamamlandı',error:'Hata oluştu',active:'Aktif',trash:'Çöp kutusu',all:'Tümü',any:'Herhangi biri',valid:'Geçerli',invalid:'Eksik ayrıştırılan',new:'İlk kez eklenenler',month:'Aylık',year:'Yıllık',hour:'Saatlik'};
const tr = value => translations[value] || value;
const date = value => value ? new Date(/[zZ]|[+]\d\d:\d\d$/.test(value) ? value : value+'Z').toLocaleString('tr-TR',{dateStyle:'medium',timeStyle:'short'}) : 'Belirtilmemiş';
const groupKeys = ['category','seniority','workplace','location','company','skills','flag','backend','source','search_term','search_location'];
const multiKeys = new Set([...groupKeys,'run_id','task_id','exclude_skills']);
let prefs={}; try {prefs=JSON.parse(localStorage.getItem('linko.ui.v2')||'{}');} catch {}
let filters={}, view=prefs.view||'cards', draft=Array.isArray(prefs.draft)?prefs.draft:[], form=prefs.form||{};
const newId=()=>crypto.randomUUID();
draft=draft.map(t=>({...t,id:t.id||newId()}));
let draftRunId=prefs.draftRunId||null, draftSaveChain=Promise.resolve(), draftSaveTimer, queueStarting=false;
let lastJobs=[], total=0, activeTotal=0, pages=0, currentRun=null, historyRuns=[], selectedHistory=new Set(), busy=false;
let listController, facetController, detailController, requestSerial=0, facetSerial=0;
let nav={previous:null,next:null}, currentJob=null, logContext=null, logBefore=null, waitingUntil=0, waitReason='', lastPoll=0;
let activeLogRun=null, sourceState=null;
let editingTask=null;
let reportContext=null;

function readLocation(){
  const query=new URLSearchParams(location.search); filters={};
  if(query.size){for(const [key,value] of query){if(key==='view'){view=value==='list'?'list':'cards';continue;}if(names[key]||['sort','page','per_page'].includes(key)){if(multiKeys.has(key)) (filters[key]??=[]).push(value);else filters[key]=value;}}}
  else filters={...(prefs.filters||{})};
}
function params(){const p=new URLSearchParams();for(const [key,value] of Object.entries(filters)){for(const v of Array.isArray(value)?value:[value]){if(v!==''&&v!=null&&v!==false)p.append(key,String(v));}}return p;}
function persist(push=false){
  form={'kw-input':$('kw-input').value,'loc-input':$('loc-input').value,'limit-input':$('limit-input').value,'unlimited':$('unlimited').checked,'classify-backend':$('classify-backend').value,'use-embeddings':$('use-embeddings').checked,'scrape-mode':$('scrape-mode').value,'refresh-details':$('refresh-details').checked};
  prefs={filters,view,draft,form,draftRunId};try{localStorage.setItem('linko.ui.v2',JSON.stringify(prefs));}catch{}
  const p=params();p.set('view',view);const url=location.pathname+'?'+p;
  if(url!==location.pathname+location.search)history[push?'pushState':'replaceState']({},'',url);
}
function toast(message, action, label='Geri al', error=false){
  const node=document.createElement('div');node.className='toast'+(error?' error':'');node.setAttribute('role',error?'alert':'status');
  const text=document.createElement('div');text.textContent=message;node.append(text);
  if(action){const row=document.createElement('div');row.className='actions';const btn=document.createElement('button');btn.textContent=label;btn.onclick=async()=>{btn.disabled=true;try{await action();node.remove();}catch(e){toast(e.message,null,'',true);btn.disabled=false;}};row.append(btn);node.append(row);}
  const close=document.createElement('button');close.textContent='Kapat';close.className='text-button';close.onclick=()=>node.remove();node.append(close);$('toasts').append(node);
  setTimeout(()=>node.remove(),action?20000:10000);
}
async function api(path,options={}){
  const config={...options};if(config.body&&typeof config.body!=='string'){config.headers={'Content-Type':'application/json',...config.headers};config.body=JSON.stringify(config.body);}
  let response;try{response=await fetch(path,config);}catch(e){if(e.name==='AbortError')throw e;throw new Error('Sunucuya ulaşılamadı. Bağlantıyı kontrol edip tekrar deneyin.');}
  let body;try{body=await response.json();}catch{throw new Error('Sunucudan geçerli yanıt alınamadı. Sayfayı yenileyip tekrar deneyin.');}
  if(!response.ok||body.ok===false)throw new Error(body.error||'İşlem tamamlanamadı. Tekrar deneyin.');return body;
}
function showDialog(id){const dialog=$(id);if(!dialog.open)dialog.showModal();}
function closeDialog(id){$(id).close();}
function confirmAction(message){return new Promise(resolve=>{const dialog=$('confirm-dialog');$('confirm-text').textContent=message;let result=false;const finish=()=>{dialog.removeEventListener('close',finish);resolve(result);};$('confirm-yes').onclick=()=>{result=true;dialog.close();};$('confirm-no').onclick=()=>dialog.close();dialog.addEventListener('close',finish);dialog.showModal();$('confirm-no').focus();});}
function button(action,text,attrs='',cls=''){return `<button data-action="${action}" ${attrs} class="${cls}">${esc(text)}</button>`;}
function badge(text,cls=''){return text?`<span class="badge ${cls}">${esc(text)}</span>`:'';}
function setFilter(key,value,push=true){if(value===''||value==null||Array.isArray(value)&&!value.length)delete filters[key];else filters[key]=value;delete filters.page;syncControls();persist(push);renderChips();loadAll();}
function syncControls(){
  $('search').value=filters.search||'';$('semantic-toggle').checked=filters.semantic==='1';$('sort').value=filters.sort||'recent';$('per-page').value=filters.per_page||'24';
  document.querySelectorAll('[data-filter]').forEach(el=>{const v=filters[el.dataset.filter];if(el.type==='checkbox')el.checked=v==='1';else el.value=el.type==='date'&&v?String(v).slice(0,10):v??(el.dataset.filter==='visibility'?'active':el.dataset.filter==='quality'?'valid':el.dataset.filter==='skill_mode'?'any':'');});
  $('exclude-skills').value=(filters.exclude_skills||[]).join(', ');$('run-filter').value=(filters.run_id||[])[0]||'';
  document.querySelectorAll('[data-facet]').forEach(el=>{el.checked=(filters[el.dataset.facet]||[]).includes(el.value);});
  $('search-scope').textContent=filters.task_id?.length?`Seçili arama kimliği: ${filters.task_id.join(', ')}`:'';
  applyView();
}
function renderChips(){
  const entries=Object.entries(filters).filter(([k,v])=>names[k]&&!['sort','page','per_page'].includes(k)&&!((k==='visibility'&&v==='active')||(k==='quality'&&v==='valid')||(k==='skill_mode'&&v==='any')));
  $('active-filters').innerHTML=entries.flatMap(([key,value])=>(Array.isArray(value)?value:[value]).map(v=>`<button class="filter-chip" data-remove-filter="${esc(key)}" data-value="${esc(v)}" aria-label="${esc(names[key])} filtresini kaldır">${esc(names[key])}: ${esc(v==='1'?'Evet':v==='0'?'Hayır':tr(v))} <span aria-hidden="true">×</span></button>`)).join('');
}
function applyView(){ $('grid').classList.toggle('list-view',view==='list');$('view-cards').setAttribute('aria-pressed',String(view==='cards'));$('view-list').setAttribute('aria-pressed',String(view==='list'));}
function renderJobs(){
  $('grid').innerHTML=lastJobs.map(j=>`<article class="job-card">
    <div><h3><button class="job-open" data-action="job" data-id="${j.id}">${esc(j.title||'Unvan belirtilmemiş')}</button></h3><p class="company">${esc(j.company||'Şirket belirtilmemiş')}</p></div>
    <div><p class="job-meta">${esc(j.location||'Konum belirtilmemiş')}</p><p class="job-meta">${esc(tr(j.workplace_type)||'Çalışma biçimi belirtilmemiş')}</p></div>
    <div><p class="job-meta ${j.salary?'salary':''}">${esc(j.salary||'Maaş belirtilmemiş')}</p><p class="job-meta">${j.experience_years!=null?esc(j.experience_years)+'+ yıl deneyim':'Deneyim belirtilmemiş'}</p><p class="job-meta">Yayın: ${esc(date(j.posted_at))}</p><p class="job-meta">Sisteme eklenme: ${esc(date(j.created_at))}</p></div>
    <div class="badges">${badge(tr(j.category))}${badge(tr(j.seniority))}${j.flag?badge(tr(j.flag),'warn'):''}${j.deleted_at?badge('Çöp kutusunda','deleted'):''}${typeof j.score==='number'?badge('Benzerlik '+Math.round(j.score*100)+'%'):''}</div>
    <div class="tags">${(j.tags||[]).slice(0,6).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div>
    <div class="card-actions">${button('job','İncele',`data-id="${j.id}"`)}${j.deleted_at?button('restore-job','Geri yükle',`data-id="${j.id}"`)+button('purge-job','Kalıcı sil',`data-id="${j.id}"`,'danger'):button('delete-job','Çöp kutusuna taşı',`data-id="${j.id}"`)}</div></article>`).join('');
  $('pager').hidden=pages<=1;const page=Number(filters.page||1);$('page-info').textContent=`${page} / ${pages} sayfa`;$('prev').disabled=page<=1;$('next').disabled=page>=pages;
  $('empty').hidden=lastJobs.length>0;
  if(!lastJobs.length){const trash=filters.visibility==='trash';const initial=!activeTotal&&!trash&&!Object.keys(filters).some(k=>names[k]&&!['visibility','quality'].includes(k));
    $('empty').innerHTML=trash?'<h2>Çöp kutusu boş</h2><p>Silinen ilanlar geri yüklenebilmek için burada tutulur.</p>':initial?'<h2>İlk ilanlarını birlikte bulalım</h2><p>Bir unvan ve konum seçerek ilk taramanı başlat.</p>'+button('new-search','İlk taramamı başlat','','primary'):'<h2>Bu filtrelerle ilan bulunamadı</h2><p>Bir filtreyi kaldırabilir veya aramayı genişletebilirsin.</p>'+button('reset','Filtreleri temizle');
  }
}
async function loadJobs(){
  listController?.abort();listController=new AbortController();const serial=++requestSerial;
  $('list-error').hidden=true;document.querySelector('.results').setAttribute('aria-busy','true');$('count').textContent='İlanlar yükleniyor…';
  try{const data=await api('/api/jobs?'+params(),{signal:listController.signal});if(serial!==requestSerial)return;lastJobs=data.jobs;total=data.total;pages=data.pages;filters.page=String(data.page);renderJobs();$('count').textContent=`${total.toLocaleString('tr-TR')} ilan${data.mode==='fit'?' · Profil benzerliğine göre':data.mode==='semantic'?' · Anlama göre sıralı':''}${data.semantic_fallback?' · Yapay zekâ eşleştirmesi kullanılamadı; standart sonuçlar gösteriliyor.':''}`;persist();}
  catch(e){if(e.name!=='AbortError'&&serial===requestSerial){$('list-error').hidden=false;$('list-error-text').textContent=e.message;$('count').textContent='İlanlar yüklenemedi.';}}
  finally{if(serial===requestSerial)document.querySelector('.results').setAttribute('aria-busy','false');}
}
async function loadFacets(){
  facetController?.abort();facetController=new AbortController();const serial=++facetSerial;
  try{const data=await api('/api/facets?'+params(),{signal:facetController.signal});if(serial!==facetSerial)return;activeTotal=data.active_total;
    for(const key of groupKeys){const box=$('facet-'+key);const query=box.querySelector('.facet-search').value.toLocaleLowerCase('tr');const items=[...(data[key]||[])];for(const value of filters[key]||[])if(!items.some(i=>i.value===value))items.push({value,count:0});
      box.querySelector('.facet-options').innerHTML=items.map(item=>`<label class="check" ${tr(item.value).toLocaleLowerCase('tr').includes(query)?'':'hidden'}><input type="checkbox" data-facet="${key}" value="${esc(item.value)}" ${(filters[key]||[]).includes(item.value)?'checked':''}><span class="facet-name">${esc(tr(item.value))}</span><small>${item.count}</small></label>`).join('')||'<p class="help">Seçenek bulunamadı.</p>';
    }
    $('hint-embed').textContent=`${data.missing_embeddings} ilanın eşleştirme verisi eksik.`;$('hint-classify').textContent=`${data.not_locally_classified} ilan yerel yapay zekâyla işlenmemiş.`;
    if(!lastJobs.length)renderJobs();
  }catch(e){if(e.name!=='AbortError')$('connection').textContent='Filtre sayıları güncellenemedi.';}
}
function loadAll(){loadJobs();loadFacets();}
function resetFilters(){filters={};syncControls();renderChips();persist(true);loadAll();}
const scheduleFilters=debounce((key,value)=>setFilter(key,value));

function descriptionHtml(text){return esc(text||'İlan açıklaması bulunamadı.').split(/\n\s*\n/).map(p=>'<p>'+p+'</p>').join('');}
function safeLink(url){try{const parsed=new URL(url);return ['http:','https:'].includes(parsed.protocol)?parsed.href:null;}catch{return null;}}
async function openJob(id){
  currentJob=Number(id);detailController?.abort();detailController=new AbortController();const signal=detailController.signal;
  $('job-title').textContent='İlan yükleniyor…';$('job-content').innerHTML='';$('previous-job').disabled=true;$('next-job').disabled=true;$('job-position').textContent='';showDialog('job-dialog');$('job-dialog').scrollTop=0;
  try{const [j,n]=await Promise.all([api('/api/jobs/'+id,{signal}),api('/api/jobs/'+id+'/navigation?'+params(),{signal})]);if(currentJob!==Number(id))return;nav=n;$('job-title').textContent=j.title||'İlan detayı';
    const link=safeLink(j.url);$('job-content').innerHTML=`<p class="company">${esc(j.company)}</p><p class="muted">${esc(j.location)} · ${esc(tr(j.workplace_type))}</p><div class="badges">${badge(tr(j.category))}${badge(tr(j.seniority))}${j.flag?badge(tr(j.flag),'warn'):''}${j.deleted_at?badge('Çöp kutusunda','deleted'):''}</div>
      ${j.salary?`<p class="notice salary">${esc(j.salary)}</p>`:''}${j.flag_reason?`<p class="notice">Otomatik değerlendirme: ${esc(j.flag_reason)}</p>`:''}${j.summary?`<p class="notice">${esc(j.summary)}</p>`:''}
      <div class="tags">${(j.tags||[]).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div>
      ${j.about_company?`<section class="job-section"><h3>Şirket hakkında</h3><p>${esc(j.about_company)}</p></section>`:''}${j.offerings?.length?`<section class="job-section"><h3>Sunulan olanaklar</h3><ul>${j.offerings.map(o=>`<li>${esc(o)}</li>`).join('')}</ul></section>`:''}
      <div class="actions job-section">${link?`<a class="button primary" href="${esc(link)}" target="_blank" rel="noopener noreferrer">Kaynakta aç ↗</a>`:''}${button('similar','Benzer ilanları bul',`data-id="${j.id}"`)}${j.deleted_at?button('restore-job','Geri yükle',`data-id="${j.id}"`):button('delete-job','Çöp kutusuna taşı',`data-id="${j.id}"`)}</div>
      <section class="job-section job-desc"><h3>İlan açıklaması</h3>${descriptionHtml(j.formatted_description||j.description)}</section>${j.formatted_description?`<details class="job-section"><summary>Kaynak açıklamayı göster</summary><div class="job-desc">${descriptionHtml(j.description)}</div></details>`:''}
      <section class="job-section"><p class="help">Yayın: ${esc(date(j.posted_at))} · İlk eklenme: ${esc(date(j.created_at))} · Son tarama: ${esc(date(j.scraped_at))}</p><details><summary>Arama ilişkileri (${j.search_ids.length})</summary>${j.discoveries.map(d=>`<p class="id-text">Arama: ${esc(d.search_id)} · ${d.is_new?'İlk kez ekledi':'Bu aramada da bulundu'} · ${esc(date(d.found_at))}</p>`).join('')||'<p class="help">Eski kaydın arama ilişkisi bulunamadı.</p>'}</details></section><div id="similar-results"></div>`;
    $('previous-job').disabled=!n.previous;$('next-job').disabled=!n.next;$('job-position').textContent=`${n.position} / ${n.total} ilan`;
  }catch(e){if(e.name!=='AbortError'){$('job-title').textContent='İlan yüklenemedi';$('job-content').innerHTML=`<p class="notice error">${esc(e.message)}</p>${button('job','Tekrar dene',`data-id="${id}"`)}`;}}
}
async function similar(id){const box=$('similar-results');box.innerHTML='<p class="notice">Benzer ilanlar aranıyor…</p>';const data=await api(`/api/jobs/${id}/similar`);box.innerHTML=data.reason==='no_embedding'?'<p class="notice">Bu ilanın eşleştirme verisi eksik. Tarama panelindeki “Kayıtlı ilanları yeniden işle” bölümünden hazırlayabilirsin.</p>':data.jobs.length?'<h3 class="job-section">Benzer ilanlar</h3>'+data.jobs.map(j=>button('job',`${j.title} · ${j.company}`,`data-id="${j.id}"`)).join(' '):'<p class="notice">Benzer ilan bulunamadı.</p>';}
async function jobAction(id,action){
  if(action==='purge'&&!await confirmAction('Bu ilan tüm arama havuzlarından kalıcı olarak silinecek. Geri alınamaz. Devam edilsin mi?'))return;
  const data=await api('/api/trash/jobs',{method:'POST',body:{ids:[Number(id)],action}});closeDialog('job-dialog');loadAll();
  toast(action==='delete'?'İlan çöp kutusuna taşındı.':action==='restore'?'İlan geri yüklendi.':'İlan kalıcı olarak silindi.',action==='delete'?async()=>{await api('/api/trash/jobs',{method:'POST',body:{ids:data.ids,action:'restore'}});loadAll();}:null);
}
async function trashFiltered(){if(!total){toast('İşlem yapılacak ilan yok.');return;}if(!await confirmAction(`Mevcut filtrelere uyan ${total} ilan çöp kutusuna taşınacak. Devam edilsin mi?`))return;const data=await api('/api/jobs?'+params(),{method:'DELETE'});loadAll();toast(`${data.count} ilan çöp kutusuna taşındı.`,async()=>{await api('/api/trash/jobs',{method:'POST',body:{ids:data.ids,action:'restore'}});loadAll();});}

function renderDraft(){
  $('draft-tasks').innerHTML=draft.map((t,i)=>`<div class="task-row"><label>Unvan<input data-draft="${i}" data-key="keyword" value="${esc(t.keyword)}"></label><div class="field-pair"><label>Konum<input data-draft="${i}" data-key="location" value="${esc(t.location)}"></label><label>Hedef <input data-draft="${i}" data-key="limit" type="number" min="1" step="1" value="${t.limit??''}" placeholder="Limitsiz"></label></div><div class="actions">${button('draft-up','↑ Yukarı',`data-index="${i}" ${i===0?'disabled':''}`)}${button('draft-down','↓ Aşağı',`data-index="${i}" ${i===draft.length-1?'disabled':''}`)}${button('draft-remove','Kaldır',`data-index="${i}"`)}</div></div>`).join('');
  document.querySelectorAll('#draft-tasks .task-row').forEach((row,i)=>{const label=document.createElement('p');label.className='id-text';label.textContent='Görev kimliği: '+draft[i].id;row.prepend(label);});
  $('queue-identity').textContent=draftRunId?'Kuyruk süreç kimliği: '+draftRunId:'Görevler düzenlendiğinde kuyruk sunucuya kaydedilir.';
}
function scheduleDraftSave(){clearTimeout(draftSaveTimer);if(queueStarting)return;draftSaveTimer=setTimeout(()=>saveDraft().catch(e=>{$('task-error').textContent='Kuyruk sunucuya kaydedilemedi: '+e.message;}),600);}
function saveDraft(){
  const tasks=draft.map(t=>({...t})),backend=$('classify-backend').value,embeddings=$('use-embeddings').checked,mode=$('scrape-mode').value,refresh=$('refresh-details').checked;
  draftSaveChain=draftSaveChain.catch(()=>{}).then(async()=>{const data=await api('/api/queue',{method:'POST',body:{run_id:draftRunId,tasks,classify_backend:backend,use_embeddings:embeddings,mode,refresh_details:refresh}});draftRunId=data.run_id;persist();$('queue-identity').textContent=draftRunId?'Kuyruk süreç kimliği: '+draftRunId:'';return draftRunId;});return draftSaveChain;
}
function addTasks(){
  const keywords=$('kw-input').value.split(/[,\n]+/).map(s=>s.trim()).filter(Boolean);const location=$('loc-input').value.trim();const raw=$('limit-input').value;const limit=$('unlimited').checked?null:Number(raw);
  if(!keywords.length||!location||limit!==null&&(!raw||!Number.isInteger(limit)||limit<=0)){$('task-error').textContent='En az bir unvan, konum ve pozitif tam sayı hedefi girin. Limitsiz seçeneğini de kullanabilirsiniz.';return false;}
  $('task-error').textContent='';for(const keyword of keywords)draft.push({id:newId(),keyword,location,limit});$('kw-input').value='';renderDraft();persist();scheduleDraftSave();return true;
}
async function openDrawer(fresh=false){$('new-search-form').hidden=!fresh&&!!currentRun;$('live-run').hidden=fresh||!currentRun;$('drawer-title').textContent=fresh||!currentRun?'Yeni tarama':'Tarama kuyruğu';showDialog('drawer');renderDraft();
  try{const models=await api('/api/ollama/models');$('classify-model').innerHTML='<option value="">Varsayılan model</option>'+models.models.map(m=>`<option>${esc(m)}</option>`).join('');}catch{}
}
async function startScrape(){
  if($('kw-input').value.trim()&&!addTasks())return;if(!draft.length){$('task-error').textContent='Önce kuyruğa en az bir görev ekleyin.';return;}
  for(const t of draft)if(!t.keyword.trim()||!t.location.trim()||t.limit!=null&&(!Number.isInteger(t.limit)||t.limit<1)){$('task-error').textContent='Görevlerdeki unvan, konum ve hedefleri kontrol edin.';return;}
  clearTimeout(draftSaveTimer);queueStarting=true;$('start-scrape').disabled=true;$('task-error').textContent='';
  try{const runId=await saveDraft();await api(`/api/runs/${runId}/resume`,{method:'POST'});activeLogRun=runId;currentRun=await api('/api/runs/'+runId);draft=[];draftRunId=null;persist();renderDraft();$('new-search-form').hidden=true;$('live-run').hidden=false;renderRun();await pollStatus();toast('Tarama kuyruğu başlatıldı. Süreç: '+runId);}
  catch(e){$('task-error').textContent=e.message;}finally{queueStarting=false;renderSource();}
}
function renderSource(){
  const blocked=!!sourceState?.paused;
  $('source-status').hidden=!blocked;$('source-status').textContent=sourceState?.message||'';
  $('acknowledge-source').hidden=!sourceState?.manual_pause;$('acknowledge-source').disabled=!sourceState?.acknowledge_allowed;
  $('start-scrape').disabled=queueStarting||blocked;
  document.querySelectorAll('[data-action="control-resume"]').forEach(el=>el.disabled=blocked);
  $('resume-run').disabled=blocked&&(!currentRun?.kind||currentRun.kind==='scrape');
  if(blocked){$('status-bar').hidden=false;$('status-text').textContent='Kaynak için tarama duraklatıldı';$('status-detail').textContent=sourceState.message;}
  renderWait();
}
function renderWait(){
  const sourceWait=sourceState?.paused;
  const retryWait=!!currentRun?.automatic_resume&&!!currentRun?.next_attempt_at;
  const deadline=sourceWait?sourceState.blocked_until*1000:retryWait?currentRun.next_attempt_at*1000:waitingUntil;
  const remaining=Math.max(0,Math.ceil((deadline-Date.now())/1000));
  $('wait-banner').hidden=!sourceWait&&!retryWait&&!(busy&&remaining>0);
  $('wait-title').textContent=sourceWait?'Kaynak beklemesi · otomatik devam':retryWait?'İşlem yeniden denenecek':'İstekler arasında bekleniyor';
  $('wait-explanation').textContent=sourceWait?sourceState.reason:retryWait?currentRun.status_reason:waitReason;
  $('wait-countdown').textContent=remaining>0?[Math.floor(remaining/3600),Math.floor(remaining%3600/60),remaining%60].map(n=>String(n).padStart(2,'0')).join(':'):'Devam kontrolü…';
  $('wait-next').textContent=sourceWait?`Sonraki erişim: ${new Date(deadline).toLocaleTimeString('tr-TR')} · ${currentRun?.automatic_resume?'Bu çalışma otomatik devam edecek.':'Servis süre dolunca erişime hazır olacak.'}`:'Bekleme tamamlandığında işlem otomatik sürecek.';
  document.querySelectorAll('[data-source-countdown]').forEach(el=>{el.textContent=$('wait-countdown').textContent;});
}
const terminalStatus = status => ['finished','cancelled','stopped'].includes(status);
const activeStatus = status => ['running','pausing','stopping','cancelling'].includes(status);
function duration(seconds){if(seconds==null)return 'Bilinmiyor';seconds=Math.max(0,Math.floor(seconds));const h=Math.floor(seconds/3600),m=Math.floor(seconds%3600/60),sec=seconds%60;return (h?h+' sa ':'')+(m?m+' dk ':'')+sec+' sn';}
function elapsed(item){return item.started_at&&(!terminalStatus(item.status)||item.ended_at)?Math.max(0,((item.ended_at?Date.parse(item.ended_at+'Z'):Date.now())-Date.parse(item.started_at+'Z'))/1000):null;}
function clockHtml(item){if(terminalStatus(item.status)&&!item.ended_at)return 'Bilinmiyor';return `<span data-clock-start="${esc(item.started_at||'')}" data-clock-end="${esc(item.ended_at||'')}">${esc(duration(elapsed(item)))}</span>`;}
function updateQueueClocks(){document.querySelectorAll('[data-clock-start]').forEach(el=>{el.textContent=duration(elapsed({started_at:el.dataset.clockStart,ended_at:el.dataset.clockEnd}));});renderWait();}
function statusBadge(status){return `<span class="state-pill state-${esc(status)}"><span aria-hidden="true">●</span> ${esc(tr(status))}</span>`;}
function metricHtml(stats,count){return `<div class="queue-metrics"><div><strong>${count}</strong><span>Çekilen</span></div><div class="metric-new"><strong>${stats.new||0}</strong><span>Yeni eklenen</span></div><div class="metric-updated"><strong>${stats.updated||0}</strong><span>Güncellenen</span></div><div><strong>${stats.unchanged||0}</strong><span>Değişmeyen</span></div></div>`;}
function reasonHtml(item){const reasons={source_paused:'Kaynak erişimi veya bekleme talebi nedeniyle duraklatıldı.',stopped_by_user:'Kullanıcı tarafından duraklatıldı.',page_fetch_failed:'Arama sayfası alınamadı.',reached_limit:'Hedef ilan sayısına ulaşıldı.',exhausted_results:'Kaynak daha fazla sonuç döndürmedi.',repeated_page:'Kaynak daha önce görülen ilanları tekrar döndürdü.'};const reason=item.status_reason||item.error||reasons[item.stats?.termination_reason];return reason&&item.status!=='running'?`<p class="queue-reason"><strong>${item.status==='error'?'Hata nedeni':item.status==='paused'?'Duraklama nedeni':'Durum açıklaması'}:</strong> ${esc(reason)}</p>`:'';}
function taskControls(run,t){if(run.deleted_at||terminalStatus(run.status)||terminalStatus(t.status)||run.kind&&run.kind!=='scrape')return '';const attr=`data-run="${run.id}" data-task="${t.id}"`;if(t.status==='running'&&run.status==='running')return button('control-pause','Duraklat',attr)+button('control-stop','Sorguyu durdur',attr,'danger');if(t.status==='queued'&&!t.has_started)return button('control-cancel','Başlamadan iptal et',attr);if(['paused','error'].includes(t.status)&&!activeStatus(run.status))return button('control-resume','Devam et',attr,'primary')+button('control-stop','Sorguyu durdur',attr,'danger');return '';}
function taskCard(run,t,editable=false){
  const stats=t.stats||{},count=t.count||0,controls=taskControls(run,t),finite=t.limit!=null;
  const edit=editable&&!terminalStatus(t.status)?button('edit-task','Düzenle',`data-task="${t.id}"`)+button('live-up','↑',`data-task="${t.id}" aria-label="Sorguyu yukarı taşı"`)+button('live-down','↓',`data-task="${t.id}" aria-label="Sorguyu aşağı taşı"`):'';
  return `<article class="task-row queue-task state-${esc(t.status)}" data-task-card="${t.id}"><div class="queue-task-heading"><strong>${esc(t.keyword)}</strong>${statusBadge(t.status)}</div><p class="muted">${esc(t.location)} · ${finite?t.limit+' ilan hedefi':'Limitsiz tarama'}</p>${metricHtml(stats,count)}<div class="queue-timing"><span>Başlangıç <strong>${t.started_at?esc(date(t.started_at)):'Henüz başlamadı / bilinmiyor'}</strong></span><span>Başlangıçtan geçen <strong>${clockHtml(t)}</strong></span></div>${finite?`<progress class="task-progress" max="${Math.max(1,t.limit)}" value="${Math.min(count,t.limit)}" aria-label="İlan hedefine ilerleme"></progress>`:'<p class="help">Sayı hedefi yok. İstediğiniz zaman duraklatabilir veya durdurabilirsiniz.</p>'}${reasonHtml(t)}<p class="help queue-extra">${stats.cache_hits||0} detay önbellekten · ${stats.skipped||0} işleme sırasında atlandı · ${stats.detail_failures||stats.descFailures||0} detay alınamadı</p><div class="actions">${controls}${edit}</div><details class="queue-identity"><summary>Sorgu kimliği</summary><p class="id-text">${esc(t.id)}</p></details></article>`;
}
function renderRun(){
  if(!currentRun)return;const run=currentRun,active=activeStatus(run.status),resumable=['paused','error'].includes(run.status);
  const done=run.tasks.filter(t=>terminalStatus(t.status)).length,collected=run.tasks.reduce((sum,t)=>sum+t.count,0);
  $('live-tasks').innerHTML=run.tasks.map(t=>taskCard(run,t,resumable)).join('');
  $('pause-run').hidden=!active&&!run.automatic_resume;$('pause-run').disabled=run.status!=='running'&&!run.automatic_resume;$('pause-run').textContent=run.automatic_resume?'Otomatik devamı duraklat':'Kuyruğu duraklat';
  $('resume-run').hidden=!resumable;$('stop-run').hidden=!active&&!resumable;$('stop-run').disabled=active&&run.status!=='running';
  $('cancel-run').hidden=run.has_started||run.status!=='queued';
  $('run-summary').hidden=false;
  $('run-summary').className='queue-overview state-'+run.status;
  $('run-summary').innerHTML=`<div class="queue-task-heading"><strong>Tarama özeti</strong>${statusBadge(run.status)}</div>${metricHtml(run.stats,collected)}<div class="queue-timing"><span>İlk başlangıç <strong>${run.started_at?esc(date(run.started_at)):'Henüz başlamadı / bilinmiyor'}</strong></span><span>Başlangıçtan geçen <strong>${clockHtml(run)}</strong></span><span>Kuyruğa eklenme <strong>${esc(date(run.created_at))}</strong></span></div><p class="help">${done}/${run.tasks.length} sorgunun işlemi sona erdi. Geçen süre duraklamaları da içerir.</p>${reasonHtml(run)}<div class="actions">${button('run-results','Toplanan ilanları gör',`data-run="${run.id}"`)}${button('run-report','Süreç raporu',`data-run="${run.id}"`)}</div><details class="queue-identity"><summary>Süreç kimliği</summary><p class="id-text">${run.id}</p></details>`;
  $('status-bar').hidden=false;$('status-bar').className='status-bar state-'+run.status;$('status-text').textContent=`${tr(run.status)} · ${collected} çekilen · ${run.stats.new||0} yeni · ${run.stats.updated||0} güncellenen · ${run.stats.unchanged||0} değişmeyen`;
  const task=run.tasks.find(t=>t.status==='running');$('status-progress').max=Math.max(1,run.tasks.length);$('status-progress').value=done;
  const remaining=Math.ceil((waitingUntil-Date.now())/1000);$('status-detail').textContent=remaining>0&&active?`${waitReason} · ${remaining} saniye`:task?`${task.keyword} · ${task.location} · ${task.limit==null?'Limitsiz tarama':task.count+'/'+task.limit+' ilan'}`:run.status_reason||'Sonuçlar korundu. Ayrıntılar tarama panelinde.';
  renderSource();
  if(run.status==='paused'&&run.automatic_resume&&sourceState?.paused)$('run-summary').insertAdjacentHTML('afterbegin','<div class="queue-wait"><strong>Otomatik devam için kalan</strong><span data-source-countdown></span></div>');
  renderWait();
  if(run.kind&&run.kind!=='scrape'){$('run-summary').innerHTML=`<strong>${esc(tr(run.status))}</strong><p>${run.stats.embedded??run.stats.classified??0} ilan işlendi · ${run.stats.skipped||0} başarısız deneme</p>${reasonHtml(run)}${button('run-report','Süreç raporunu aç',`data-run="${run.id}"`)}`;}
}
async function controlTask(runId,taskId,action){
  if(action==='stop'&&!await confirmAction('Bu sorgu sonuçları korunarak durdurulacak. Aynı sorguya devam edilemez; gerekiyorsa yeni tarama başlatabilirsiniz. Kuyruk çalışıyorsa sonraki sorguya geçer.'))return;
  await api(`/api/runs/${runId}/tasks/${taskId}/${action}`,{method:'POST'});
  currentRun=await api('/api/runs/'+runId);renderRun();await pollStatus();if($('history-dialog').open)await loadHistory();
  if(action==='resume'){closeDialog('history-dialog');await openDrawer();}
}
async function runAction(id,action){
  if(action==='purge'&&!await confirmAction('Arama geçmişi, havuzu ve logları kalıcı olarak silinecek. Ortak ilanlar sistemde kalacak. Devam edilsin mi?'))return;
  if(action==='stop'&&!await confirmAction('Kuyruk sonuçları korunarak durdurulacak. Devam etmek için yeni tarama oluşturmanız gerekir. Durdurulsun mu?'))return;
  if(action==='cancel'&&!await confirmAction('Henüz başlamamış kuyruk iptal edilsin mi?'))return;
  await api(`/api/runs/${id}/${action}`,{method:'POST'});
  if(action==='resume'&&draftRunId===id){draft=[];draftRunId=null;clearTimeout(draftSaveTimer);persist();renderDraft();}
  if(['delete','restore','purge'].includes(action)){await loadHistory();await loadRunOptions();toast(action==='delete'?'Arama geçmişi çöp kutusuna taşındı. İlanlar korundu.':action==='restore'?'Arama geçmişi geri yüklendi.':'Arama geçmişi kalıcı silindi.',action==='delete'?async()=>{await api(`/api/runs/${id}/restore`,{method:'POST'});await loadHistory();loadRunOptions();}:null);}
  else{currentRun=await api('/api/runs/'+id);renderRun();if(action==='resume'){closeDialog('history-dialog');await openDrawer();}await pollStatus();}
}
async function editLive(taskId,action){
  const pending=currentRun.tasks.filter(t=>!terminalStatus(t.status)).map(t=>({...t}));const i=pending.findIndex(t=>t.id===taskId);if(i<0)return;
  if(action==='remove'){if(!await confirmAction('Bu görevi kalan kuyruktan kaldırmak istiyor musunuz? Toplanan ilanlar korunur.'))return;pending.splice(i,1);}else{const other=action==='up'?i-1:i+1;if(other<0||other>=pending.length)return;[pending[i],pending[other]]=[pending[other],pending[i]];}
  await api('/api/runs/'+currentRun.id,{method:'PATCH',body:{tasks:pending}});currentRun=await api('/api/runs/'+currentRun.id);renderRun();
}
function openTaskEditor(taskId){
  const task=currentRun?.tasks.find(t=>t.id===taskId);if(!task)return;editingTask=taskId;
  $('edit-keyword').value=task.keyword;$('edit-location').value=task.location;$('edit-limit').value=task.limit??'';
  $('edit-keyword').disabled=!!task.folder;$('edit-location').disabled=!!task.folder;$('edit-task-error').textContent='';
  $('edit-task-help').textContent=task.folder?'Başlamış görevin unvanı ve konumu korunur. Hedef sayısını değiştirebilirsiniz.':'Bu görev henüz başlamadı; unvanı, konumu ve hedefi değiştirebilirsiniz.';showDialog('task-dialog');
}
async function saveTask(){
  const pending=currentRun.tasks.filter(t=>!terminalStatus(t.status)).map(t=>({...t}));const task=pending.find(t=>t.id===editingTask);if(!task)return;
  const raw=$('edit-limit').value;task.keyword=$('edit-keyword').value.trim();task.location=$('edit-location').value.trim();task.limit=raw===''?null:Number(raw);
  if(!task.keyword||!task.location||task.limit!==null&&(!Number.isInteger(task.limit)||task.limit<1)){$('edit-task-error').textContent='Unvan, konum ve hedef sayısını kontrol edin.';return;}
  try{await api('/api/runs/'+currentRun.id,{method:'PATCH',body:{tasks:pending}});currentRun=await api('/api/runs/'+currentRun.id);renderRun();closeDialog('task-dialog');toast('Görev güncellendi.');}catch(e){$('edit-task-error').textContent=e.message;}
}
async function acknowledgeSource(){try{await api('/api/source/acknowledge',{method:'POST'});await pollStatus();toast('Kaynak duraklatması kaldırıldı. Kuyruğu devam ettirebilirsiniz.');}catch(e){toast(e.message,null,'',true);}}
async function pollStatus(){
  try{const status=await api('/api/scrape/status');busy=status.running;sourceState=status.source_state;renderSource();lastPoll=Date.now();
    if(status.run){currentRun=status.run;activeLogRun=currentRun.id;renderRun();}
    else if(busy){$('status-bar').hidden=false;$('status-text').textContent=status.kind==='embed'?'İlan eşleştirmeleri hazırlanıyor…':'İlanlar analiz ediliyor…';$('status-detail').textContent='Bu işlem kayıtlı ilanlar üzerinde çalışır.';$('status-progress').removeAttribute('value');}
    else if(currentRun&&activeStatus(currentRun.status)){currentRun=await api('/api/runs/'+currentRun.id);renderRun();loadAll();}
    if($('history-dialog').open)loadHistory();
    $('embed-jobs').disabled=busy;$('classify-jobs').disabled=busy;$('stop-maintenance').hidden=!busy||status.kind==='scrape';
  }catch(e){$('connection').textContent='Sunucu bağlantısı bekleniyor…';}
}
function connectEvents(){
  const source=new EventSource('/events');source.onopen=()=>{$('connection').textContent='Canlı bağlantı açık';pollStatus();};source.onerror=()=>{$('connection').textContent='Yeniden bağlanılıyor…';};
  const refreshJobs=debounce(loadAll,1200);const refreshStatus=debounce(pollStatus,300);
  source.onmessage=event=>{let ev;try{ev=JSON.parse(event.data);}catch{return;}const d=ev.data||{};
    if(['waiting','shared_rate_wait'].includes(ev.type)){waitingUntil=Date.now()+d.seconds*1000;waitReason=d.reason;renderWait();refreshStatus();}
    if(ev.type==='job'){waitingUntil=0;refreshJobs();refreshStatus();}
    if(['task_start','task_done','job_progress','run_finished','finished','error','source_paused','task_control'].includes(ev.type)){refreshStatus();}
    if(ev.type==='run_finished'){currentRun=d;renderRun();loadAll();loadRunOptions();if($('history-dialog').open)loadHistory();toast(`Çalışma ${tr(d.status).toLocaleLowerCase('tr')}: ${d.stats.new||0} yeni, ${d.stats.updated||0} güncellenen ilan.`,()=>{showResults('run_id',d.id);},'Sonuçları gör');}
    if(ev.type==='notice'||ev.type==='error'){toast(d.msg||'İşlem tamamlanamadı. Sonuçlar korundu.',()=>openDrawer(),'Ayrıntılar',true);}
    if(ev.type==='log'&&busy&&!currentRun)$('maintenance-status').textContent=localLogMessage(d.msg);
    if(ev.type==='finished'&&!d.run_id){$('maintenance-status').textContent=`İşlem tamamlandı. ${d.embedded??d.classified??0} ilan işlendi, ${d.skipped||0} ilan atlandı.`;loadAll();}
  };
  setInterval(()=>{if(document.visibilityState==='visible'){if(Date.now()-lastPoll>4000)pollStatus();updateQueueClocks();}},1000);
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'){pollStatus();loadAll();}});
}
async function loadRunOptions(){try{const data=await api('/api/runs');$('run-filter').innerHTML='<option value="">Tüm çalışmalar</option>'+data.runs.map(r=>`<option value="${r.id}">${esc(date(r.created_at))} · ${esc(r.tasks.map(t=>t.keyword).join(', '))}</option>`).join('');$('run-filter').value=filters.run_id?.[0]||'';if(!currentRun){const paused=data.runs.find(r=>['paused','error'].includes(r.status));if(paused){currentRun=paused;renderRun();}}}catch{}}

async function openHistory(){showDialog('history-dialog');await loadHistory();}
async function loadHistory(){try{const data=await api('/api/runs'+($('history-trash').checked?'?trash=1':''));historyRuns=data.runs;selectedHistory=new Set([...selectedHistory].filter(id=>historyRuns.some(r=>r.tasks.some(t=>t.id===id))));renderHistory();}catch(e){$('history-list').innerHTML=`<p class="notice error">${esc(e.message)}</p>${button('history','Tekrar dene')}`;}}
function renderHistory(){
  const query=$('history-search').value.toLocaleLowerCase('tr');const visible=historyRuns.filter(r=>(!$('history-status').value||r.status===$('history-status').value)&&JSON.stringify(r).toLocaleLowerCase('tr').includes(query));
  $('history-list').innerHTML=visible.map(r=>`<article class="run-card state-${esc(r.status)}"><div class="run-heading"><div><strong>${esc(date(r.created_at))}</strong> ${statusBadge(r.status)}</div><div class="actions">${!r.deleted_at?button('run-results','Çalışmanın ilanları',`data-run="${r.id}"`)+(['paused','error'].includes(r.status)?button('run-resume','Devam et',`data-run="${r.id}"`):'')+(r.status==='running'?button('run-pause','Kuyruğu duraklat',`data-run="${r.id}"`):'')+(['running','paused','error'].includes(r.status)?button('run-stop','Kuyruğu durdur',`data-run="${r.id}"`,'danger'):'')+(r.status==='queued'&&!r.has_started?button('run-cancel','Başlamadan iptal et',`data-run="${r.id}"`):'')+button('run-restart','Yeniden tara',`data-run="${r.id}"`)+button('run-delete','Çöp kutusuna taşı',`data-run="${r.id}"`):button('run-restore','Geri yükle',`data-run="${r.id}"`)+button('run-purge','Kalıcı sil',`data-run="${r.id}"`,'danger')}</div></div>
    ${metricHtml(r.stats,r.tasks.reduce((n,t)=>n+t.count,0))}<div class="queue-timing"><span>Başlangıç <strong>${r.started_at?esc(date(r.started_at)):'Bilinmiyor / başlamadı'}</strong></span><span>Geçen süre <strong>${clockHtml(r)}</strong></span></div>${reasonHtml(r)}
    ${r.tasks.map(t=>`<div class="history-task"><label class="history-select"><input type="checkbox" data-history-select="${t.id}" ${selectedHistory.has(t.id)?'checked':''}>Sorguyu seç</label>${taskCard(r,t)}<div class="actions">${button('task-results','İlanları gör',`data-task="${t.id}"`)}${button('task-new-results','İlk kez eklenenler',`data-task="${t.id}"`)}${button('task-queue','Kuyruğa ekle',`data-task="${t.id}"`)}${button('task-restart','Yeniden tara',`data-task="${t.id}"`)}${button('task-logs','İşlem kayıtları',`data-task="${t.id}" data-run="${r.id}"`)}${button('task-report','Neden az geldi?',`data-task="${t.id}" data-run="${r.id}"`)}</div></div>`).join('')}</article>`).join('')||'<div class="empty"><h2>Arama geçmişi bulunamadı</h2><p>Aramalar burada görünür.</p></div>';
  $('history-selected-count').textContent=`${selectedHistory.size} görev seçili.`;$('delete-selected').hidden=$('history-trash').checked;
  $('history-list').querySelectorAll('.run-card').forEach((card,i)=>{
    const run=visible[i],identity=document.createElement('p');identity.className='id-text';identity.textContent='Süreç kimliği: '+run.id;card.querySelector('.run-heading').after(identity);
    card.querySelector('.run-heading .actions').insertAdjacentHTML('afterbegin',button('run-report','Süreç raporu',`data-run="${run.id}"`)+button('run-logs','Tüm kayıtlar',`data-run="${run.id}"`)+button('copy-id','Kimliği kopyala',`data-id="${run.id}"`));
    if(run.status==='queued')card.querySelector('.run-heading .actions').insertAdjacentHTML('beforeend',button('run-resume','Kuyruğu başlat',`data-run="${run.id}"`));
    if(run.kind&&run.kind!=='scrape')card.querySelectorAll('[data-history-select]').forEach(el=>el.disabled=true);
    if(run.kind&&run.kind!=='scrape'){card.querySelectorAll('[data-action="run-results"],[data-action="run-restart"],[data-action="task-results"],[data-action="task-new-results"],[data-action="task-queue"],[data-action="task-restart"]').forEach(el=>el.hidden=true);}
  });
}
function findTask(id){return historyRuns.flatMap(r=>r.tasks).find(t=>t.id===id);}
function showResults(key,id,onlyNew=false){filters={ [key]:[id], ...(onlyNew?{discovery:'new'}:{})};syncControls();renderChips();persist(true);loadAll();closeDialog('history-dialog');closeDialog('drawer');$('main').scrollIntoView({block:'start'});}
async function queueTasks(tasks,restart=false){
  if(!tasks.length){toast('Önce en az bir arama seçin.');return;}
  draft.push(...tasks.map(t=>({id:newId(),keyword:t.keyword,location:t.location,limit:t.limit})));renderDraft();persist();if(!restart)scheduleDraftSave();closeDialog('history-dialog');await openDrawer(true);
  if(restart)await startScrape();else toast(`${tasks.length} görev kuyruğa eklendi. Konumları ve limitleri korundu.`);
}
async function historyBatch(action){
  const tasks=historyRuns.filter(r=>!r.kind||r.kind==='scrape').flatMap(r=>r.tasks).filter(t=>action==='all'||selectedHistory.has(t.id));
  if(action==='delete'){const ids=historyRuns.filter(r=>r.tasks.some(t=>selectedHistory.has(t.id))).map(r=>r.id);if(!ids.length){toast('Önce arama seçin.');return;}if(!await confirmAction(`${ids.length} çalışma geçmişi çöp kutusuna taşınacak. Bu çalışmalardaki seçilmemiş görevler de geçmişin parçasıdır; ortak ilanlar silinmez. Devam edilsin mi?`))return;let failures=0;for(const id of ids){try{await api(`/api/runs/${id}/delete`,{method:'POST'});}catch{failures++;}}await loadHistory();loadRunOptions();toast(failures?`${failures} çalışma taşınamadı. Aktif çalışmaları önce duraklatın.`:'Seçilen çalışmalar çöp kutusuna taşındı.',null,'',!!failures);return;}
  await queueTasks(tasks,action==='restart'||action==='all');
}

async function openReport(runId,taskId=null){reportContext={runId,taskId};showDialog('report-dialog');await loadReport();}
async function loadReport(){
  if(!reportContext)return;const {runId,taskId}=reportContext,p=new URLSearchParams();if(taskId)p.set('task_id',taskId);
  $('report-content').innerHTML='<p class="notice">Süreç raporu hazırlanıyor…</p>';
  try{const r=await api(`/api/runs/${runId}/report?`+p),m=r.metrics;
    const metrics=r.kind==='scrape'?[['Gönderilen istek',m.requests],['Kaynakta görülen kart',m.returned_cards],['Çekilen ilan (sayfa toplamı)',m.collected],['Tekrar kart',m.duplicates],['Detay hatası',m.detail_failures],['İşlenmeyen kart',m.not_processed],['Veritabanında ilişkili ilan',m.found_jobs],['İlk kez eklenen',m.new_jobs],['Güncellenen ilişki',m.updated_jobs],['Değişmeyen ilan',m.unchanged_jobs],['Önbellekten alınan detay',m.cache_hits],['Detayı istenen ilan',m.cache_misses],['Kaynak nedeniyle duraklama',m.source_pauses],['Varsayılan listede görünür',m.visible_jobs],['Çöp kutusunda',m.deleted_jobs],['Eksik ayrıştırılan',m.invalid_jobs]]:[['Hedef kayıt',m.target_jobs],['İşlenen kayıt',m.processed_jobs],['İşleme hatası',m.processing_failures]];
    $('report-content').innerHTML=`<p class="id-text">Süreç: ${esc(r.run_id)}${r.search_id?'<br>Görev: '+esc(r.search_id):''}</p><p>${badge(tr(r.status))} · ${esc(date(r.generated_at))}</p><div class="actions"><a class="button" href="/api/runs/${runId}/report?${esc(p.toString())}${p.size?'&amp;':''}download=1" download>Raporu JSON indir</a>${button('run-logs','Tüm süreç kayıtlarını aç',`data-run="${runId}"`)}</div>
      <table class="report-table"><tbody>${metrics.map(([name,value])=>`<tr><th scope="row">${esc(name)}</th><td>${value==null?'Bilinmiyor':esc(value)}</td></tr>`).join('')}</tbody></table>
      <h3>Ne oldu, ne yapılabilir?</h3>${r.findings.map(f=>`<section class="notice ${f.severity==='warning'?'error':''}"><strong>${esc(f.title)}</strong><ul>${f.next_steps.map(s=>`<li>${esc(s)}</li>`).join('')}</ul><details><summary>Dayanak kayıt</summary><pre>${esc(typeof f.evidence==='string'?f.evidence:JSON.stringify(f.evidence,null,2))}</pre></details></section>`).join('')||'<p class="notice">Kayıtlarda belirgin bir sonuç kaybı nedeni görülmüyor. Aktif süreçlerin raporu ilerledikçe güncellenir.</p>'}
      <h3>Görevlerin sonucu</h3>${r.tasks.map(t=>`<div class="task-row"><strong>${esc(t.keyword)}</strong><p>${t.collected} / ${t.target??'Limitsiz'} · ${esc(tr(t.status))}</p><p class="id-text">${esc(t.search_id)}</p><p>Durma nedeni: ${esc(t.termination_reason||'Henüz tamamlanmadı veya eski kayıtta yok')}</p>${t.error?`<p class="field-error">${esc(t.error)}</p>`:''}${button('task-logs','Bu görevin kayıtları',`data-run="${runId}" data-task="${t.search_id}"`)}</div>`).join('')}
      <details class="job-section"><summary>Süreç zaman çizelgesi (${r.timeline.length})</summary>${r.timeline.map(e=>`<div class="log-entry"><small>${esc(date(e.at))} · Kayıt ${e.event_id}</small><p>${esc(e.kind)}</p><pre>${esc(JSON.stringify(e.data,null,2))}</pre></div>`).join('')}</details><div class="help">${r.notes.map(n=>'<p>'+esc(n)+'</p>').join('')}</div>`;
  }catch(e){$('report-content').innerHTML=`<p class="notice error">${esc(e.message)}</p>`;}
}
function localLogMessage(message){
  const replacements=[[/Accountless blocked/g,'Kaynağa erişim sınırlandı'],[/Entire run stopped; no retry or account fallback\./g,'Çalışma durdu; toplanan sonuçlar korundu.'],[/No jobs are missing embeddings\./g,'Tüm ilanların eşleştirme verisi hazır.'],[/Stopped by user\./g,'Kullanıcı tarafından durduruldu.'],[/Local embedding model unreachable.*stopping\./g,'Yerel eşleştirme modeline ulaşılamadı; işlem durdu.'],[/Public job\/page is no longer available\./g,'İlan veya sayfa artık erişilebilir değil.']];
  let text=String(message||'');for(const [pattern,replacement] of replacements)text=text.replace(pattern,replacement);return text;
}
async function openLogs(runId,taskId=null){const t=findTask(taskId)||currentRun?.tasks.find(t=>t.id===taskId);logContext={runId,taskId,folder:t?.folder};logBefore=null;$('log-query').value='';$('legacy-log').hidden=!t?.folder;$('log-kind').value='';$('log-level').value='';$('log-list').innerHTML='';$('download-logs').href=`/api/runs/${runId}/logs/download`;showDialog('log-dialog');await loadLogs();}
async function legacyLog(){if(!logContext?.folder)return;const data=await api('/api/searches/'+encodeURIComponent(logContext.folder)+'/log');$('log-list').innerHTML=`<article class="log-entry"><h3>Kaynak metin kaydı</h3><pre>${esc(data.log)}</pre></article>`;$('older-logs').hidden=true;}
function logSummary(e){const d=e.data;if(e.kind==='page_result')return `Sayfa ${d.page}: ${d.cards_returned} kart döndü · ${d.collected} çekildi · ${d.duplicates} tekrar · ${d.detail_failures} detay alınamadı · ${d.not_processed||0} işlenmedi${d.interrupted?' · Limit veya duraklama nedeniyle kesildi':''}`;
  if(e.kind==='request_started')return `İstek gönderildi · ${d.params?'Arama sayfası':'İlan detayı'}${d.params?' · sıra başlangıcı '+d.params.start:''}`;
  if(e.kind==='request_finished')return `Yanıt ${d.status??'alınamadı'} · ${d.duration_ms} ms${d.params?' · '+d.cards_returned+' ilan kartı':''}${d.error?' · '+d.error:''}`;
  if(e.kind==='job')return `İlan kaydedildi · ${d.title} · ${d.company} · ${d.outcome==='unchanged'?'Değişmedi':d.is_new?'Yeni':'Güncellendi'}`;
  if(e.kind==='task_start')return `Arama başladı · ${d.keyword} · ${d.location}`;
  if(e.kind==='task_done')return `Arama tamamlandı · ${d.count} ilan · ${d.reason||''}`;
  if(e.kind==='source_paused')return d.message;
  if(e.kind==='cache_hit')return `Detay önbellekten alındı · ${d.external_id}`;
  if(e.kind==='cache_miss')return `Detay önbellekte yok, süresi doldu veya yenileme istendi · ${d.external_id}`;
  if(e.kind==='waiting')return `${d.reason} · ${d.seconds} saniye`;
  return localLogMessage(d.msg)||tr(e.kind);
}
async function loadLogs(older=false){if(!logContext)return;const p=new URLSearchParams();if(logContext.taskId)p.set('task_id',logContext.taskId);if($('log-kind').value)p.set('kind',$('log-kind').value);if($('log-level').value)p.set('level',$('log-level').value);if($('log-query').value.trim())p.set('query',$('log-query').value.trim());if(older&&logBefore)p.set('before',logBefore);
  try{const data=await api(`/api/runs/${logContext.runId}/logs?`+p);const html=data.events.map(e=>`<article class="log-entry ${esc(e.level)}"><small>${esc(date(e.ts))} · ${esc(e.kind)} · ${esc(e.level==='error'?'Hata':e.level==='warning'?'Uyarı':'Bilgi')}</small><p>${esc(logSummary(e))}</p><details><summary>Teknik kayıt ve arama kimliği</summary><pre>${esc(JSON.stringify(e,null,2))}</pre></details></article>`).join('')||'<p class="help">Bu seçimde yapılandırılmış kayıt yok. Eski aramaların metin logu havuz klasöründe korunur.</p>';
    if(older)$('log-list').insertAdjacentHTML('beforeend',html);else $('log-list').innerHTML=html;const t=data.totals;$('log-totals').textContent=`Sayfa yanıtları toplamı: ${t.cards_returned} kart · ${t.collected} çekilen · ${t.duplicates} tekrar · ${t.detail_failures} detay hatası · ${t.not_processed||0} işlenmeyen. Tekrarlanan isteklerde aynı ilan birden fazla kart olarak sayılabilir.`;logBefore=data.next_before;$('older-logs').hidden=!logBefore;
  }catch(e){toast(e.message,null,'',true);}
}
async function openProfile(){showDialog('profile-dialog');$('profile-status').textContent='Profil yükleniyor…';try{const p=await api('/api/profile');$('profile-text').value=p.text;$('profile-status').textContent=p.has_embedding?'Profil eşleştirmesi hazır.':p.text?'Profil kayıtlı; eşleştirme için Ollama çalışmalı.':'Deneyimlerini ekleyerek başlayabilirsin.';}catch(e){$('profile-status').textContent=e.message;}}
async function saveProfile(){$('save-profile').disabled=true;$('profile-status').textContent='Kaydediliyor…';try{const data=await api('/api/profile',{method:'POST',body:{text:$('profile-text').value}});$('profile-status').textContent=data.embedded?'Profil kaydedildi, eşleştirme hazır.':'Profil kaydedildi. Eşleştirme hazırlanamadı; Ollama bağlantısını kontrol edin.';loadFacets();}catch(e){$('profile-status').textContent=e.message;}finally{$('save-profile').disabled=false;}}
async function maintenance(kind){try{await api('/api/'+kind,{method:'POST',body:{force:$('force-recompute').checked,backend:'local',model:$('classify-model').value||null}});$('maintenance-status').textContent='İşlem başladı…';await pollStatus();}catch(e){$('maintenance-status').textContent=e.message;}}

async function openService(){
  if(!$('service-dialog').open)showDialog('service-dialog');
  try{const [health,status]=await Promise.all([fetch('/healthz').then(r=>r.json()),api('/api/service/status')]);
    $('service-content').innerHTML=`<div class="queue-metrics"><div><strong>${health.database==='ok'?'Hazır':'Hata'}</strong><span>Veritabanı</span></div><div><strong>${status.supervisor_alive?'Açık':'Kapalı'}</strong><span>Otonom servis</span></div><div><strong>${status.api_key_configured?'Hazır':'Ayarlanmalı'}</strong><span>API anahtarı</span></div></div><p class="notice">${esc(status.source.message)}</p>${status.last_error?`<p class="field-error">${esc(status.last_error)}</p>`:''}<h3>Tekrarlı toplamalar</h3>${status.schedules.map(s=>`<article class="task-row"><strong>${esc(s.keywords.join(', '))}</strong><p>${esc(tr(s.status))} · Tamamlandıktan ${esc(duration(s.repeat_seconds))} sonra tekrar</p><div class="actions">${button('run-logs','İşlem kayıtları',`data-run="${s.run_id}"`)}${button('disable-schedule','Tekrarı kapat',`data-run="${s.run_id}"`,'danger')}</div></article>`).join('')||'<p class="help">Tekrarlı toplama yok. API üzerinden repeat_seconds ile oluşturabilirsiniz.</p>'}`;
  }catch(e){$('service-content').textContent=e.message;}
}

async function dispatch(action,el){
  const id=el.dataset.id,run=el.dataset.run,task=el.dataset.task,index=Number(el.dataset.index);
  if(action==='jobs-home'||action==='trash-home'){document.querySelectorAll('dialog[open]').forEach(d=>d.close());filters=action==='trash-home'?{visibility:'trash'}:{};syncControls();renderChips();persist(true);await loadAll();$('main').scrollIntoView({block:'start'});return;}
  if(action==='logs-home'){const rows=await api('/api/runs');if(!rows.runs.length){toast('Henüz işlem kaydı yok.');return;}return openLogs(currentRun?.id||rows.runs[0].id);}
  if(action==='service-home')return openService();
  if(action==='disable-schedule'){await api(`/api/service/schedules/${run}/stop`,{method:'POST'});toast('Yeni tekrarlar kapatıldı.');return openService();}
  if(action==='maintenance-home'){await openDrawer();document.querySelector('.maintenance').open=true;document.querySelector('.maintenance').scrollIntoView({block:'start'});return;}
  if(action==='new-search')return openDrawer(true);if(action==='queue')return openDrawer();if(action==='history')return openHistory();if(action==='profile')return openProfile();if(action==='reset')return resetFilters();if(action==='job')return openJob(id);if(action==='similar')return similar(id);
  if(action==='copy-id'){await navigator.clipboard.writeText(id);toast('Kimlik kopyalandı: '+id);return;}
  if(action==='run-report'||action==='task-report')return openReport(run,task||null);
  if(action==='run-logs')return openLogs(run);
  if(['delete-job','restore-job','purge-job'].includes(action))return jobAction(id,action.split('-')[0]);
  if(action.startsWith('draft-')){if(action==='draft-remove')draft.splice(index,1);else{const other=index+(action==='draft-up'?-1:1);if(other>=0&&other<draft.length)[draft[index],draft[other]]=[draft[other],draft[index]];}renderDraft();persist();scheduleDraftSave();return;}
  if(action.startsWith('control-'))return controlTask(run,task,action.slice(8));
  if(action.startsWith('live-'))return editLive(task,action.slice(5));
  if(action==='edit-task')return openTaskEditor(task);
  if(['task-results','task-all-results','task-new-results'].includes(action))return showResults('task_id',task,action==='task-new-results');
  if(action==='run-results')return showResults('run_id',run);
  if(action==='task-logs')return openLogs(run,task);
  if(action==='task-queue'||action==='task-restart')return queueTasks([findTask(task)].filter(Boolean),action==='task-restart');
  if(action==='run-restart')return queueTasks(historyRuns.find(r=>r.id===run)?.tasks||[],true);
  if(action.startsWith('run-'))return runAction(run,action.slice(4));
}
document.addEventListener('click',async event=>{
  const close=event.target.closest('[data-close]');if(close){closeDialog(close.dataset.close);return;}
  const chip=event.target.closest('[data-remove-filter]');if(chip){const key=chip.dataset.removeFilter;const value=filters[key];setFilter(key,Array.isArray(value)?value.filter(v=>v!==chip.dataset.value):'');return;}
  const el=event.target.closest('[data-action]');if(!el||el.disabled)return;el.disabled=true;try{await dispatch(el.dataset.action,el);}catch(e){toast(e.message,null,'',true);}finally{el.disabled=false;}
});
document.addEventListener('change',event=>{
  const el=event.target;
  if(el.dataset.facet){const key=el.dataset.facet;const selected=new Set(filters[key]||[]);if(el.checked)selected.add(el.value);else selected.delete(el.value);setFilter(key,[...selected]);}
  else if(el.dataset.filter){setFilter(el.dataset.filter,el.type==='checkbox'?(el.checked?'1':''):el.value);}
  else if(el.dataset.historySelect){if(el.checked)selectedHistory.add(el.dataset.historySelect);else selectedHistory.delete(el.dataset.historySelect);$('history-selected-count').textContent=`${selectedHistory.size} görev seçili.`;}
});
document.addEventListener('input',event=>{
  const el=event.target;if(el.dataset.draft!=null){const t=draft[Number(el.dataset.draft)];t[el.dataset.key]=el.dataset.key==='limit'?(el.value===''?null:Number(el.value)):el.value;persist();scheduleDraftSave();}
  if(el.dataset.filter&&el.tagName==='INPUT'&&el.type!=='checkbox')scheduleFilters(el.dataset.filter,el.value);
  if(el.classList.contains('facet-search')){const query=el.value.toLocaleLowerCase('tr');el.closest('.filter-group').querySelectorAll('.facet-options label').forEach(label=>{label.hidden=!label.textContent.toLocaleLowerCase('tr').includes(query);});}
});
function wire(id,event,fn){$(id).addEventListener(event,async e=>{try{await fn(e);}catch(error){toast(error.message,null,'',true);}});}
function initialize(){
  document.querySelector('header nav').insertAdjacentHTML('beforeend',button('maintenance-home','Bakım / analiz'));
  const queueLabel=document.createElement('p');queueLabel.id='queue-identity';queueLabel.className='id-text';$('draft-tasks').before(queueLabel);
  const reportDialog=document.createElement('dialog');reportDialog.id='report-dialog';reportDialog.className='wide-dialog';reportDialog.setAttribute('aria-labelledby','report-title');reportDialog.innerHTML='<div class="dialog-heading"><h2 id="report-title">Süreç raporu · Neden az geldi?</h2><button data-close="report-dialog" aria-label="Raporu kapat">✕</button></div><button id="refresh-report">Raporu yenile</button><div id="report-content"></div>';document.body.append(reportDialog);
  const logQuery=document.createElement('input');logQuery.id='log-query';logQuery.type='search';logQuery.placeholder='İstek / ilan / deneme kimliği veya mesaj ara';logQuery.setAttribute('aria-label','İşlem kayıtlarında ara');$('log-totals').before(logQuery);
  for(const [value,label] of [['cache_hit','Önbellekten alınan detaylar'],['cache_miss','Detayı yenilenen ilanlar'],['source_paused','Kaynak nedeniyle duraklamalar'],['shared_rate_wait','Ortak istek sırası'],['processing_stage','İşleme aşamaları'],['processing_result','İşleme sonuçları'],['job_skipped','Elenen ilanlar'],['checkpoint_saved','Devam noktaları'],['user_action','Kullanıcı işlemleri'],['run_started','Çalıştırma / deneme kimlikleri'],['task_queued','Kuyruğa alınan görevler']])$('log-kind').add(new Option(label,value));
  $('facet-filters').innerHTML=groupKeys.map((key,i)=>`<details class="filter-group" id="facet-${key}" ${i<3?'open':''}><summary>${names[key]}</summary><input class="facet-search" type="search" placeholder="Seçeneklerde ara…" aria-label="${names[key]} seçeneklerinde ara"><div class="facet-options"></div></details>`).join('');
  $('date-filters').innerHTML=[['posted','Yayın tarihi'],['created','İlk eklenme'],['scraped','Son tarama']].map(([key,label])=>`<fieldset><legend>${label}</legend><div class="field-pair"><label>Başlangıç<input type="date" data-filter="${key}_from"></label><label>Bitiş<input type="date" data-filter="${key}_to"></label></div>${key==='posted'?'<label class="check"><input type="checkbox" data-filter="posted_missing">Yayın tarihi belirtilmemiş</label>':''}</fieldset>`).join('');
  $('content-filters').innerHTML=[['has_description','Açıklama'],['has_summary','Yapay zekâ özeti'],['has_embedding','Eşleştirme verisi']].map(([key,label])=>`<label>${label}<select data-filter="${key}"><option value="">Tümü</option><option value="1">Var</option><option value="0">Yok</option></select></label>`).join('');
  const legacyButton=document.createElement('button');legacyButton.id='legacy-log';legacyButton.textContent='Kaynak metin kaydı';legacyButton.hidden=true;$('download-logs').after(legacyButton);
  $('acknowledge-source').onclick=acknowledgeSource;
  for(const [id,value] of Object.entries(form)){if($(id)){if($(id).type==='checkbox')$(id).checked=!!value;else $(id).value=value;}}
  $('limit-input').disabled=$('unlimited').checked;$('task-error').after($('start-scrape'));readLocation();syncControls();renderChips();renderDraft();
  wire('search','input',debounce(e=>setFilter('search',e.target.value.trim())));wire('semantic-toggle','change',e=>setFilter('semantic',e.target.checked?'1':''));wire('sort','change',e=>setFilter('sort',e.target.value));wire('per-page','change',e=>setFilter('per_page',e.target.value));
  wire('exclude-skills','input',debounce(e=>setFilter('exclude_skills',e.target.value.split(',').map(v=>v.trim()).filter(Boolean))));
  wire('run-filter','change',e=>{delete filters.task_id;setFilter('run_id',e.target.value?[e.target.value]:[]);});
  wire('date-preset','change',e=>{if(e.target.value){const d=new Date();d.setDate(d.getDate()-Number(e.target.value));filters.posted_from=d.toISOString();delete filters.posted_to;delete filters.posted_missing;}else delete filters.posted_from;syncControls();renderChips();persist(true);loadAll();});
  wire('filter-toggle','click',()=>{const open=$('filter-panel').classList.toggle('open');$('filter-toggle').setAttribute('aria-expanded',String(open));});wire('reset-filters','click',resetFilters);wire('retry-jobs','click',loadAll);
  wire('view-cards','click',()=>{view='cards';applyView();persist(true);});wire('view-list','click',()=>{view='list';applyView();persist(true);});
  for(const [id,delta] of [['prev',-1],['next',1]])wire(id,'click',()=>{filters.page=String(Math.max(1,Math.min(pages,Number(filters.page||1)+delta)));persist(true);loadJobs();$('count').scrollIntoView({block:'center'});});
  wire('previous-job','click',()=>nav.previous&&openJob(nav.previous));wire('next-job','click',()=>nav.next&&openJob(nav.next));
  $('job-dialog').addEventListener('close',()=>{detailController?.abort();currentJob=null;});
  wire('add-tasks','click',addTasks);wire('start-scrape','click',startScrape);wire('unlimited','change',()=>{$('limit-input').disabled=$('unlimited').checked;persist();});
  ['kw-input','loc-input','limit-input','classify-backend','use-embeddings','scrape-mode','refresh-details'].forEach(id=>wire(id,'input',()=>{persist();if(draft.length&&['classify-backend','use-embeddings','scrape-mode','refresh-details'].includes(id))scheduleDraftSave();}));
  wire('pause-run','click',()=>currentRun&&runAction(currentRun.id,'pause'));wire('resume-run','click',()=>currentRun&&runAction(currentRun.id,'resume'));wire('stop-run','click',()=>currentRun&&runAction(currentRun.id,'stop'));wire('cancel-run','click',()=>currentRun&&runAction(currentRun.id,'cancel'));wire('live-logs','click',()=>currentRun&&openLogs(currentRun.id));
  wire('history-status','change',renderHistory);wire('history-search','input',renderHistory);wire('history-trash','change',()=>{selectedHistory.clear();loadHistory();});
  wire('history-select-all','click',()=>{const query=$('history-search').value.toLocaleLowerCase('tr');const tasks=historyRuns.filter(r=>JSON.stringify(r).toLocaleLowerCase('tr').includes(query)).flatMap(r=>r.tasks);const all=tasks.every(t=>selectedHistory.has(t.id));for(const t of tasks)if(all)selectedHistory.delete(t.id);else selectedHistory.add(t.id);renderHistory();});
  wire('queue-selected','click',()=>historyBatch('queue'));wire('restart-selected','click',()=>historyBatch('restart'));wire('restart-all','click',()=>historyBatch('all'));wire('delete-selected','click',()=>historyBatch('delete'));
  wire('log-kind','change',()=>loadLogs());wire('log-level','change',()=>loadLogs());wire('refresh-logs','click',()=>loadLogs());wire('older-logs','click',()=>loadLogs(true));
  wire('legacy-log','click',legacyLog);
  wire('refresh-report','click',loadReport);wire('log-query','input',debounce(()=>loadLogs()));
  wire('save-profile','click',saveProfile);wire('embed-jobs','click',()=>maintenance('embed'));wire('classify-jobs','click',()=>maintenance('classify'));wire('stop-maintenance','click',async()=>{await api('/api/scrape/stop',{method:'POST'});$('maintenance-status').textContent='İşlem durduruluyor…';});wire('trash-filtered','click',trashFiltered);
  wire('save-task','click',saveTask);
  document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}}));
  window.addEventListener('popstate',()=>{readLocation();syncControls();renderChips();loadAll();});
  loadAll();loadRunOptions();pollStatus();connectEvents();
}
initialize();
