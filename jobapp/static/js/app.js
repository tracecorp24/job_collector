'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const debounce = (fn, ms=350) => { let timer; const pending=(...args)=>{clearTimeout(timer);timer=setTimeout(()=>fn(...args),ms);};pending.cancel=()=>clearTimeout(timer);return pending; };
const names = {category:'Genel kategori',seniority:'Kıdem',workplace:'Çalışma biçimi',location:'Konum',location_text:'Konum',company:'Şirket',skills:'Yetenek',flag:'İlan değerlendirmesi',backend:'Analiz yöntemi',source:'Kaynak',search_term:'Aranan unvan',search_location:'Aranan konum',search:'Arama',semantic:'Anlama göre arama',title:'Unvanda',description:'Açıklamada',company_text:'Şirket adında',phrase:'Tam ifade',exclude:'Hariç kelimeler',exclude_skills:'Hariç yetenekler',skill_mode:'Yetenek koşulu',salary_min:'En az maaş',salary_max:'En çok maaş',currency:'Para birimi',period:'Maaş dönemi',has_salary:'Maaş bilgisi',experience_min:'En az deneyim',experience_max:'En çok deneyim',experience_missing:'Deneyim bilinmiyor',run_id:'Çalışma',task_id:'Arama',discovery:'Bulunma türü',has_description:'Açıklama',has_summary:'Özet',has_embedding:'Eşleştirme verisi',quality:'Ayrıştırma kalitesi',visibility:'Görünürlük',posted_from:'Yayın başlangıcı',posted_to:'Yayın bitişi',posted_missing:'Yayın tarihi bilinmiyor',created_from:'İlk eklenme başlangıcı',created_to:'İlk eklenme bitişi',scraped_from:'Son tarama başlangıcı',scraped_to:'Son tarama bitişi'};
const translations = {Engineering:'Mühendislik / Yazılım',Data:'Veri ve yapay zekâ',Design:'Tasarım',Product:'Ürün',Finance:'Finans',Sales:'Satış',Marketing:'Pazarlama',HR:'İnsan kaynakları',Operations:'Operasyon',Other:'Diğer',Intern:'Stajyer',Junior:'Başlangıç',Mid:'Orta seviye',Senior:'Kıdemli',Lead:'Lider',Manager:'Yönetici',Unknown:'Belirtilmemiş',Remote:'Uzaktan',Hybrid:'Hibrit',Onsite:'Ofiste',Office:'Ofiste',rules:'Hızlı analiz',local:'Yerel yapay zekâ',llm:'Bulut yapay zekâ',claude:'Bulut yapay zekâ',groq:'Groq yapay zekâ',scam:'Şüpheli ilan',ghost:'Aktifliği şüpheli',clean:'İşaretlenmemiş',__missing__:'Belirtilmemiş',queued:'Bekliyor',running:'Çalışıyor',pausing:'Duraklatılıyor',paused:'Duraklatıldı',stopping:'Durduruluyor',stopped:'Durduruldu',cancelling:'İptal ediliyor',cancelled:'İptal edildi',finished:'Tamamlandı',error:'Hata oluştu',active:'Aktif',trash:'Çöp kutusu',all:'Tümü',any:'Herhangi biri',valid:'Geçerli',invalid:'Eksik ayrıştırılan',new:'İlk kez eklenenler',month:'Aylık',year:'Yıllık',hour:'Saatlik'};
names.opportunity_type='Fırsat türü';
Object.assign(translations,{internship:'Staj',graduate:'Yeni mezun programı',job:'İş',unknown:'Türü belirsiz'});
names.country='Ülke';names.city='Şehir';
names.profession_group='Ana meslek grubu';names.profession_subgroup='Meslek alt grubu';
const tr = value => translations[value] || value;
const languageNames = {tr:'Türkçe',en:'İngilizce',other:'Diğer'};
const date = value => value ? new Date(/[zZ]|[+]\d\d:\d\d$/.test(value) ? value : value+'Z').toLocaleString('tr-TR',{dateStyle:'medium',timeStyle:'short'}) : 'Belirtilmemiş';
// Kartlar için kısa tarih: yayın günü (saat bilgisi yok), eklenme gün + saat.
const shortDate = (value, time) => value ? new Date(/[zZ]|[+]\d\d:\d\d$/.test(value) ? value : value+'Z').toLocaleString('tr-TR', time ? {day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'} : {day:'numeric',month:'short',year:'numeric'}) : 'Belirtilmemiş';
const groupKeys = ['opportunity_type','category','seniority','workplace','company','skills','flag','backend','source','search_term','search_location'];
const multiKeys = new Set([...groupKeys,'profession_group','profession_subgroup','run_id','task_id','exclude_skills','city']);
const getSelectedCities = () => { if (!filters.city) return []; return Array.isArray(filters.city) ? filters.city : [filters.city]; };
let prefs={}; try {prefs=JSON.parse(localStorage.getItem('linko.ui.v2')||'{}');} catch {}
let filters={}, view=prefs.view||'cards', draft=Array.isArray(prefs.draft)?prefs.draft:[], form=prefs.form||{};
const newId=()=>crypto.randomUUID();
draft=draft.map(t=>({...t,id:t.id||newId()}));
let groqAvailable=false,professionFacets={},cityOptionsCountry='',locationFacetData={country:[],city:[]},companyFacetData=[];
const getSelectedCompanies = () => { if (!filters.company) return []; return Array.isArray(filters.company) ? filters.company : [filters.company]; };
let draftRunId=prefs.draftRunId||null, draftSaveChain=Promise.resolve(), draftSaveTimer, queueStarting=false;
let lastJobs=[], total=0, activeTotal=0, pages=0, currentRun=null, historyRuns=[], selectedHistory=new Set(), busy=false;
let listController, facetController, detailController, requestSerial=0, facetSerial=0;
let nav={previous:null,next:null}, currentJob=null, logContext=null, logBefore=null, waitingUntil=0, waitReason='', lastPoll=0;
let activeLogRun=null, sourceState=null;
let editingTask=null;
let reportContext=null;
let jobDrawerCloseTimer, jobDrawerReturnFocus;
// "Yeni" = son "Görüldü say" anından sonra sisteme eklenen ilan; açılan ilanlar sönük gösterilir.
let seen={mark:null,ids:[]};try{seen={...seen,...JSON.parse(localStorage.getItem('linko.seen.v1')||'{}')};}catch{}
if(!seen.mark)seen.mark=new Date().toISOString();
const seenIds=new Set(seen.ids);
function saveSeen(){seen.ids=[...seenIds].slice(-3000);try{localStorage.setItem('linko.seen.v1',JSON.stringify(seen));}catch{}}
saveSeen();
function isNewJob(j){return !!j.created_at&&new Date(/[zZ]|[+]\d\d:\d\d$/.test(j.created_at)?j.created_at:j.created_at+'Z')>new Date(seen.mark);}
const expandedFacets=new Set();

function readLocation(){
  const query=new URLSearchParams(location.search); filters={};
  if(query.size){for(const [key,value] of query){if(key==='view'){view=value==='list'?'list':'cards';continue;}if(names[key]||['sort','page','per_page'].includes(key)){if(multiKeys.has(key)) (filters[key]??=[]).push(value);else filters[key]=value;}}}
  else filters={...(prefs.filters||{})};
  delete filters.semantic;
  if(!filters.country)delete filters.city;
}
function params(){
  const p=new URLSearchParams();
  for(const [key,value] of Object.entries(filters)){for(const v of Array.isArray(value)?value:[value]){if(v!==''&&v!=null&&v!==false)p.append(key,String(v));}}
  if((filters.search||'').trim())p.set('semantic','1');
  return p;
}
function persist(push=false){
  form={'kw-input':$('kw-input').value,'loc-input':$('loc-input').value,'limit-input':$('limit-input').value,'unlimited':$('unlimited').checked,'classify-backend':$('classify-backend').value,'use-embeddings':$('use-embeddings').checked,'scrape-mode':$('scrape-mode').value,'refresh-details':$('refresh-details').checked,'collection-opportunity-type':$('collection-opportunity-type').value};
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
function showDialog(id){
  if(id==='job-dialog'){
    const bd=$('jobDrawerBackdrop');
    if(bd){
      clearTimeout(jobDrawerCloseTimer);
      if(bd.classList.contains('hidden'))jobDrawerReturnFocus=document.activeElement;
      bd.classList.remove('hidden');
      requestAnimationFrame(()=>{bd.classList.add('drawer-open');$('closeJobDrawerBtn').focus();});
    }
    return;
  }
  const dialog=$(id);if(dialog&&!dialog.open)dialog.showModal();
}
function closeDialog(id){
  if(id==='job-dialog'){
    const bd=$('jobDrawerBackdrop');
    if(bd&&!bd.classList.contains('hidden')){
      bd.classList.remove('drawer-open');
      clearTimeout(jobDrawerCloseTimer);
      jobDrawerCloseTimer=setTimeout(()=>bd.classList.add('hidden'),260);
      $('job-dialog').dispatchEvent(new Event('close'));
      if(jobDrawerReturnFocus?.isConnected)jobDrawerReturnFocus.focus();
    }
    return;
  }
  const dialog=$(id);if(dialog&&dialog.open)dialog.close();
}
function confirmAction(message){return new Promise(resolve=>{const dialog=$('confirm-dialog');$('confirm-text').textContent=message;let result=false;const finish=()=>{dialog.removeEventListener('close',finish);resolve(result);};$('confirm-yes').onclick=()=>{result=true;dialog.close();};$('confirm-no').onclick=()=>dialog.close();dialog.addEventListener('close',finish);dialog.showModal();$('confirm-no').focus();});}
function button(action,text,attrs='',cls=''){return `<button data-action="${action}" ${attrs} class="${cls}">${esc(text)}</button>`;}
function badge(text,cls=''){return text?`<span class="badge ${cls}">${esc(text)}</span>`:'';}
function setFilter(key,value,push=true){if(value===''||value==null||Array.isArray(value)&&!value.length)delete filters[key];else filters[key]=value;if(key==='country'){delete filters.city;cityOptionsCountry='';}delete filters.page;syncControls();persist(push);renderChips();loadAll();}
function syncControls(){
  if(document.activeElement !== $('search')) $('search').value=filters.search||'';
  $('clearKeywordBtn')?.classList.toggle('hidden', !($('search')?.value || filters.search));
  $('location-country').value=filters.country||'';
  const cities = getSelectedCities();
  $('location-city').value=cities[0]||'';
  $('location-city').hidden=!filters.country;
  $('location-city').disabled=!filters.country||cityOptionsCountry!==filters.country;
  $('sort').value=filters.sort||'recent';
  $('per-page').value=filters.per_page||'24';
  document.querySelectorAll('[data-filter]').forEach(el=>{if(document.activeElement===el)return;const v=filters[el.dataset.filter];if(el.type==='checkbox')el.checked=v==='1';else el.value=el.type==='date'&&v?String(v).slice(0,10):v??(el.dataset.filter==='visibility'?'active':el.dataset.filter==='quality'?'valid':el.dataset.filter==='skill_mode'?'any':'');});
  if(document.activeElement !== $('exclude-skills')) $('exclude-skills').value=(filters.exclude_skills||[]).join(', ');$('run-filter').value=(filters.run_id||[])[0]||'';
  document.querySelectorAll('[data-facet]').forEach(el=>{el.checked=(filters[el.dataset.facet]||[]).includes(el.value);});
  document.querySelectorAll('[data-quick]').forEach(el=>el.setAttribute('aria-pressed',String(quickActive(el.dataset.quick))));$('date-preset').value=String(postedPreset()||'');
  $('search-scope').textContent=filters.task_id?.length?`Seçili arama kimliği: ${filters.task_id.join(', ')}`:'';

  // Hero Şirket Tetikleyici ve Rozet Güncellemesi
  const hcActive = $('heroCompanyActiveText');
  const hcBadge = $('heroCompanyBadge');
  const hcClear = $('clearCompanyBtn');
  const selectedCompanies = getSelectedCompanies();

  if (hcActive) {
    if (selectedCompanies.length === 1) {
      hcActive.textContent = selectedCompanies[0];
      if (hcBadge) { hcBadge.textContent = '1'; hcBadge.classList.remove('hidden'); }
      if (hcClear) hcClear.classList.remove('hidden');
    } else if (selectedCompanies.length === 2) {
      hcActive.textContent = `${selectedCompanies[0]}, ${selectedCompanies[1]}`;
      if (hcBadge) { hcBadge.textContent = '2'; hcBadge.classList.remove('hidden'); }
      if (hcClear) hcClear.classList.remove('hidden');
    } else if (selectedCompanies.length > 2) {
      hcActive.textContent = `${selectedCompanies[0]} (+${selectedCompanies.length - 1})`;
      if (hcBadge) { hcBadge.textContent = `${selectedCompanies.length}`; hcBadge.classList.remove('hidden'); }
      if (hcClear) hcClear.classList.remove('hidden');
    } else {
      hcActive.textContent = 'Şirket seçin (Tümü)';
      if (hcBadge) hcBadge.classList.add('hidden');
      if (hcClear) hcClear.classList.add('hidden');
    }
  }

  const hcFooter = $('heroCompanyFooterSummary');
  if (hcFooter) {
    hcFooter.textContent = selectedCompanies.length ? `${selectedCompanies.length} şirket seçili` : 'Tüm şirketler aktif';
  }
  renderHeroCompanyOptions();

  // Hero Konum Tetikleyici ve Rozet Güncellemesi
  const hlActive = $('heroLocationActiveText') || $('countryCityActiveText');
  const hlBadge = $('heroLocationBadge') || $('countryCityCountBadge');
  const hlClear = $('clearLocationBtn');
  const country = filters.country || '';

  if (hlActive) {
    if (country && cities.length > 0) {
      if (cities.length === 1) {
        hlActive.textContent = `${country} · ${cities[0]}`;
        if (hlBadge) { hlBadge.textContent = '1'; hlBadge.classList.remove('hidden'); }
      } else if (cities.length === 2) {
        hlActive.textContent = `${country} · ${cities[0]}, ${cities[1]}`;
        if (hlBadge) { hlBadge.textContent = '2'; hlBadge.classList.remove('hidden'); }
      } else {
        hlActive.textContent = `${country} · ${cities[0]}, ${cities[1]} (+${cities.length - 2})`;
        if (hlBadge) { hlBadge.textContent = `${cities.length}`; hlBadge.classList.remove('hidden'); }
      }
      if (hlClear) hlClear.classList.remove('hidden');
    } else if (country) {
      hlActive.textContent = `${country} (Tüm Şehirler)`;
      if (hlBadge) { hlBadge.textContent = 'Tümü'; hlBadge.classList.remove('hidden'); }
      if (hlClear) hlClear.classList.remove('hidden');
    } else {
      hlActive.textContent = 'Konum seçin (Tümü)';
      if (hlBadge) hlBadge.classList.add('hidden');
      if (hlClear) hlClear.classList.add('hidden');
    }
  }

  const hlFooter = $('heroLocationFooterSummary');
  if (hlFooter) {
    if (!country) hlFooter.textContent = 'Ülke seçimi bekleniyor';
    else if (cities.length === 0) hlFooter.textContent = `${country} genelindeki tüm şehirler`;
    else hlFooter.textContent = `${country}: ${cities.length} şehir seçili`;
  }

  document.querySelectorAll('.cc-quick-pill').forEach(pill => {
    const isIstanbul = filters.country === 'Türkiye' && cities.includes('İstanbul');
    pill.classList.toggle('!bg-[#0A66C2]', isIstanbul);
    pill.classList.toggle('!text-white', isIstanbul);
    pill.classList.toggle('!border-[#0A66C2]', isIstanbul);
  });

  // Sidebar aktif filtre sayısı rozeti
  const filterCount = Object.keys(filters).filter(k => names[k] && !['sort', 'page', 'per_page'].includes(k) && !((k==='visibility'&&filters[k]==='active')||(k==='quality'&&filters[k]==='valid')||(k==='skill_mode'&&filters[k]==='any'))).length;
  const sbBadge = $('sidebarActiveBadge');
  if (sbBadge) {
    sbBadge.textContent = filterCount;
    sbBadge.classList.toggle('hidden', filterCount === 0);
  }
  const mobBadge = $('mobileFilterCount');
  if (mobBadge) {
    mobBadge.textContent = filterCount;
    mobBadge.classList.toggle('hidden', filterCount === 0);
  }

  applyView();
}
// Uzun seçenek listeleri iç içe kaydırma yerine ilk 6 seçenekle gösterilir; arama yapılınca tümü açılır.
function facetCollapse(box){
  const key=box.id.slice(6),query=box.querySelector('.facet-search').value.trim(),count=box.querySelectorAll('.facet-options label').length,open=expandedFacets.has(key);
  box.querySelector('.facet-options').classList.toggle('collapsed',!open&&!query);
  const more=box.querySelector('.facet-more');more.hidden=count<=6||!!query;more.textContent=open?'Daha az göster':`Tümünü göster (${count})`;
}
function organizeFilterGroups(){
  const sectionFor=selector=>document.querySelector(selector).closest('details.filter-group');
  const skillsSection=sectionFor('#exclude-skills');
  const companyText=document.querySelector('[data-filter="company_text"]').closest('label');
  $('facet-company').append(companyText);
  $('facet-skills').querySelector('summary').textContent='Yetenekler';
  $('facet-skills').append(skillsSection.querySelector('.fields, .filter-body-inner'));
  skillsSection.remove();

  const moveFacet=(key,host)=>{
    const old=$('facet-'+key),section=document.createElement('fieldset');
    section.id=old.id;section.className='facet-block filter-subgroup';
    const legend=document.createElement('legend');legend.textContent=names[key];
    old.querySelector('summary').remove();section.append(legend,...old.childNodes);
    old.remove();host.append(section);
  };
  const experience=sectionFor('[data-filter="experience_min"]');
  experience.querySelector('summary').textContent='Kıdem ve deneyim';
  moveFacet('seniority',experience);
  experience.append(experience.querySelector('.fields, .filter-body-inner'));

  const history=sectionFor('#run-filter');
  history.querySelector('summary').textContent='Arama ve tarama geçmişi';
  for(const key of ['search_term','search_location','source'])moveFacet(key,history);
  moveFacet('backend',$('content-filters').parentElement);
  moveFacet('flag',sectionFor('[data-filter="quality"]'));

  const legacy=document.createElement('details');legacy.className='advanced';
  const summary=document.createElement('summary');summary.textContent='Gelişmiş: genel kategori';
  legacy.append(summary);$('facet-professions').append(legacy);moveFacet('category',legacy);
  sectionFor('[data-filter="title"]').querySelector('summary').textContent='Gelişmiş metin araması';
}
function renderChips(){
  const entries=Object.entries(filters).filter(([k,v])=>names[k]&&!['sort','page','per_page'].includes(k)&&!((k==='visibility'&&v==='active')||(k==='quality'&&v==='valid')||(k==='skill_mode'&&v==='any')));
  $('active-filters').innerHTML=entries.flatMap(([key,value])=>(Array.isArray(value)?value:[value]).map(v=>`<button class="filter-chip" data-remove-filter="${esc(key)}" data-value="${esc(v)}" aria-label="${esc(names[key])} filtresini kaldır">${esc(key==='created_from'&&v===seen.mark?'Son kontrolden beri':names[key])}${key==='created_from'&&v===seen.mark?'':': '+esc(v==='1'?'Evet':v==='0'?'Hayır':/^\d{4}-\d\d-\d\dT/.test(v)?date(v):tr(v))} <span aria-hidden="true">×</span></button>`)).join('');
}
// Hızlı filtreler mevcut filtre anahtarlarını kullanır; yayın tarihi ön ayarı posted_from'dan geri okunur.
function postedPreset(){if(!filters.posted_from||filters.posted_to)return 0;const days=(Date.now()-new Date(filters.posted_from))/86400000;return [1,7,30].find(n=>Math.abs(days-n)<.6)||0;}
function setPostedPreset(days){if(days){const d=new Date();d.setDate(d.getDate()-days);filters.posted_from=d.toISOString();delete filters.posted_to;delete filters.posted_missing;}else delete filters.posted_from;delete filters.page;syncControls();renderChips();persist(true);loadAll();}
function quickActive(key){const [k,v]=key.split(':');return k==='posted'?postedPreset()===Number(v):k==='workplace'?(filters.workplace||[]).includes(v):filters[k]===v;}
function toggleQuick(key){
  const [k,v]=key.split(':'),on=quickActive(key);
  if(k==='posted')return setPostedPreset(on?0:Number(v));
  if(k==='workplace'){const selected=new Set(filters.workplace||[]);if(on)selected.delete(v);else selected.add(v);return setFilter('workplace',[...selected]);}
  setFilter(k,on?'':v);
}
function applyView(){
  $('grid').classList.toggle('list-view',view==='list');
  $('view-cards').setAttribute('aria-pressed',String(view==='cards'));
  $('view-list').setAttribute('aria-pressed',String(view==='list'));
  if(view==='cards'){
    $('view-cards').className='inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition-all bg-white dark:bg-zinc-800 text-[#0A66C2] dark:text-[#70B5F9] shadow-xs cursor-pointer';
    $('view-list').className='inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all text-ink-muted hover:text-slate-900 dark:hover:text-white cursor-pointer';
  } else {
    $('view-cards').className='inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all text-ink-muted hover:text-slate-900 dark:hover:text-white cursor-pointer';
    $('view-list').className='inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition-all bg-white dark:bg-zinc-800 text-[#0A66C2] dark:text-[#70B5F9] shadow-xs cursor-pointer';
  }
}
// Kartta yalnızca bilinen bilgiler gösterilir; "belirtilmemiş" satırları kalabalık yaratır, ayrıntı detay penceresindedir.
function postedAgo(value){
  if(!value)return null;const days=Math.floor((Date.now()-new Date(/[zZ]|[+]\d\d:\d\d$/.test(value)?value:value+'Z'))/86400000);
  return {text:days<=0?'Bugün':days===1?'Dün':days<7?`${days} gün önce`:days<30?`${Math.floor(days/7)} hafta önce`:`${Math.floor(days/30)} ay önce`,fresh:days<=2};
}
const BRAND_HUES = [
  'bg-blue-500/10 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300 border-blue-500/20',
  'bg-purple-500/10 text-purple-700 dark:bg-purple-500/15 dark:text-purple-300 border-purple-500/20',
  'bg-amber-500/10 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300 border-amber-500/20',
  'bg-emerald-500/10 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300 border-emerald-500/20',
  'bg-rose-500/10 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300 border-rose-500/20',
  'bg-cyan-500/10 text-cyan-700 dark:bg-cyan-500/15 dark:text-cyan-300 border-cyan-500/20',
  'bg-indigo-500/10 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300 border-indigo-500/20',
  'bg-teal-500/10 text-teal-700 dark:bg-teal-500/15 dark:text-teal-300 border-teal-500/20'
];
function brandHue(str){
  let hash=0;for(let i=0;i<(str||'').length;i++)hash=(hash<<5)-hash+str.charCodeAt(i);
  return BRAND_HUES[Math.abs(hash)%BRAND_HUES.length];
}
function jobCard(j){
  const posted=postedAgo(j.posted_at), link=safeLink(j.url);
  const isSeen=seenIds.has(j.id);
  const isNew=isNewJob(j)&&!isSeen;
  const initial=(j.company||'?').trim().charAt(0).toLocaleUpperCase('tr');
  const hue=brandHue(j.company||'');
  const parentCat=(j.profession_groups||[])[0]||tr(j.category)||'Genel Meslekler';
  const subCat=(j.profession_subgroups||[])[0]||'';
  const seniority=[j.opportunity_type && j.opportunity_type!=='unknown'?tr(j.opportunity_type):'',j.seniority&&j.seniority!=='Unknown'?tr(j.seniority):''].filter(Boolean).join(' · ');
  const workplace=j.workplace_type?tr(j.workplace_type):'';
  const place=[j.location,workplace].filter(Boolean).join(' · ');

  const isSelected = currentJob ? Number(j.id) === Number(currentJob) : false;

  const hideOrRestore=j.deleted_at
    ? `<button type="button" data-action="restore-job" data-id="${j.id}" class="p-1 rounded-lg text-xs font-semibold text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/10 cursor-pointer" title="Geri yükle">↩</button>`
    : `<button type="button" data-action="delete-job" data-id="${j.id}" class="p-1 rounded-lg text-ink-muted hover:text-rose-600 dark:hover:text-rose-400 hover:bg-rose-500/10 transition-colors cursor-pointer" title="İlanı gizle">✕</button>`;

  return `<article data-job-id="${j.id}" data-id="${j.id}" data-action="job" class="job-card group relative bg-surface-light dark:bg-surface-dark rounded-xl p-4 sm:p-4.5 flex flex-col justify-between overflow-hidden border cursor-pointer transition-all duration-150 ${isSelected ? 'selected-job ring-2 ring-[#0A66C2] border-l-4 border-l-[#0A66C2] bg-blue-50/45 dark:bg-[#0A66C2]/15 shadow-sm' : 'border-black/[0.07] dark:border-white/[0.08] hover:border-[#0A66C2]/50 hover:bg-zinc-50/50 dark:hover:bg-white/[0.02] shadow-2xs'} ${isSeen && !isSelected ? 'seen opacity-85' : ''} ${j.deleted_at ? 'opacity-55 border-dashed border-rose-500/40' : ''}">
    
    <div class="flex items-start gap-3.5 min-w-0">
      <!-- Şirket Logosu / Baş Harfi (LinkedIn kare logo) -->
      <div class="w-12 h-12 rounded-xl border ${hue} flex items-center justify-center font-display font-extrabold text-lg shrink-0 shadow-2xs">
        ${esc(initial)}
      </div>

      <!-- Orta Bilgi Alanı -->
      <div class="min-w-0 flex-1">
        <div class="flex items-start justify-between gap-1.5">
          <h3 class="font-display font-bold text-[15px] leading-snug text-slate-900 dark:text-white group-hover:text-[#0A66C2] dark:group-hover:text-[#70B5F9] transition-colors line-clamp-2">
            <button class="job-open text-left cursor-pointer" data-action="job" data-id="${j.id}">
              ${esc(j.title || 'Unvan belirtilmemiş')}
              <span class="inline-block text-[#0A66C2] dark:text-[#70B5F9] text-xs ml-0.5" title="Onaylı ilan">✓</span>
            </button>
          </h3>
          <div class="flex items-center gap-1 shrink-0">
            ${hideOrRestore}
          </div>
        </div>

        <p class="text-xs font-semibold text-slate-800 dark:text-zinc-200 truncate mt-0.5">
          <button type="button" data-filter-company="${esc(j.company || '')}" class="hover:text-[#0A66C2] dark:hover:text-[#70B5F9] hover:underline cursor-pointer transition-colors text-left" title="${esc(j.company || 'Şirket belirtilmemiş')} ile filtrele">${esc(j.company || 'Şirket belirtilmemiş')}</button>
        </p>

        <p class="text-[11px] text-ink-muted truncate mt-0.5 flex items-center gap-1">
          <svg class="w-3 h-3 text-ink-muted shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15 10.5a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" d="M19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1115 0z"/></svg>
          <span>${esc(place || 'Konum belirtilmemiş')}</span>
        </p>

        <!-- LinkedIn yeşil aktif inceleme şeridi veya durum -->
        <div class="flex items-center gap-1.5 mt-2 text-[11px]">
          ${isNew ? `<span class="inline-flex items-center px-1.5 py-0.2 rounded-full text-[10px] font-bold bg-[#E6F4EA] text-[#057642] dark:bg-[#057642]/30 dark:text-emerald-300">Yeni</span>` : ''}
          <span class="text-emerald-700 dark:text-emerald-400 font-medium flex items-center gap-1 text-[11px]">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
            <span>Başvuranlar aktif inceleniyor</span>
          </span>
          ${typeof j.score==='number'?`<span class="ml-auto inline-flex items-center px-1.5 py-0.2 rounded text-[10px] font-bold bg-amber-500/10 text-amber-700 dark:text-amber-300">%${Math.round(j.score*100)} Uyum</span>`:''}
        </div>

        <!-- Meta alt satır: Gün + Kolay Başvuru -->
        <div class="flex items-center gap-2 mt-2 pt-1.5 text-[11px] text-ink-muted border-t border-black/[0.04] dark:border-white/[0.04]">
          <span class="font-medium">${posted ? esc(posted.text) : 'Tarih belirtilmemiş'}</span>
          <span>·</span>
          <span class="text-[#0A66C2] dark:text-[#70B5F9] font-medium flex items-center gap-1">
            <span class="font-bold">in</span> Kolay Başvuru
          </span>
          ${j.salary ? `<span class="ml-auto font-mono font-bold text-emerald-600 dark:text-emerald-400">${esc(j.salary)}</span>` : ''}
        </div>
      </div>
    </div>
  </article>`;
}
function renderJobs(){
  if(lastJobs.length > 0){
    if(!currentJob || !lastJobs.some(j=>Number(j.id)===Number(currentJob))){
      currentJob = Number(lastJobs[0].id);
    }
  } else {
    currentJob = null;
  }

  $('grid').innerHTML=lastJobs.map(jobCard).join('');
  $('pager').hidden=pages<=1;const page=Number(filters.page||1);$('page-info').textContent=`${page} / ${pages} sayfa`;$('prev').disabled=page<=1;$('next').disabled=page>=pages;
  $('empty').hidden=lastJobs.length>0;

  if(!lastJobs.length){
    const trash=filters.visibility==='trash';
    const initial=!activeTotal&&!trash&&!Object.keys(filters).some(k=>names[k]&&!['visibility','quality'].includes(k));
    $('empty').innerHTML=trash?'<h3 class="font-display font-bold text-base text-slate-900 dark:text-white mb-1">Çöp kutusu boş</h3><p class="text-xs text-ink-secondary dark:text-zinc-400">Silinen ilanlar geri yüklenebilmek için burada tutulur.</p>':initial?'<h3 class="font-display font-bold text-base text-slate-900 dark:text-white mb-1">İlk ilanlarını birlikte bulalım</h3><p class="text-xs text-ink-secondary dark:text-zinc-400 mb-4">Bir unvan ve konum seçerek ilk taramanı başlat.</p>'+button('new-search','İlk taramamı başlat','','px-5 py-2 rounded-xl text-xs font-bold bg-[#0A66C2] text-white hover:bg-[#004182] transition-colors cursor-pointer'):'<h3 class="font-display font-bold text-base text-slate-900 dark:text-white mb-1">Bu filtrelerle ilan bulunamadı</h3><p class="text-xs text-ink-secondary dark:text-zinc-400 max-w-md mx-auto mb-4">Bir filtreyi kaldırabilir veya aramayı genişletebilirsin.</p>'+button('reset','Filtreleri temizle','','px-5 py-2 rounded-xl text-xs font-bold bg-[#0A66C2] text-white hover:bg-[#004182] transition-colors cursor-pointer');

    if($('persistent-job-content')){
      $('persistent-job-content').innerHTML = `
        <div class="p-12 text-center text-ink-muted">
          <p class="text-sm font-medium">Görüntülenecek ilan bulunamadı.</p>
          <p class="text-xs text-ink-secondary mt-1">Filtreleri sıfırlayarak tüm ilanları tekrar görebilirsiniz.</p>
        </div>`;
    }
  } else if (currentJob && window.innerWidth >= 1024) {
    // Automatically load the active job into the persistent detail panel on desktop
    openJob(currentJob, false);
  }
}
async function loadJobs(){
  listController?.abort();listController=new AbortController();const serial=++requestSerial;
  $('list-error').hidden=true;document.querySelector('.results').setAttribute('aria-busy','true');$('count').textContent='İlanlar yükleniyor…';
  try{const data=await api('/api/jobs?'+params(),{signal:listController.signal});if(serial!==requestSerial)return;lastJobs=data.jobs;total=data.total;pages=data.pages;filters.page=String(data.page);renderJobs();$('count').textContent=`${total.toLocaleString('tr-TR')} ilan${data.mode==='semantic'?' · Anlama göre sıralı':''}${data.semantic_fallback?' · Yapay zekâ eşleştirmesi kullanılamadı; standart sonuçlar gösteriliyor.':''}`;const feedCount=$('live-feed-count');if(feedCount)feedCount.textContent=`${total.toLocaleString('tr-TR')} Aktif İlan`;persist();}
  catch(e){if(e.name!=='AbortError'&&serial===requestSerial){$('list-error').hidden=false;$('list-error-text').textContent=e.message;$('count').textContent='İlanlar yüklenemedi.';}}
  finally{if(serial===requestSerial)document.querySelector('.results').setAttribute('aria-busy','false');}
}
async function loadFacets(){
  facetController?.abort();facetController=new AbortController();const serial=++facetSerial;
  try{const data=await api('/api/facets?'+params(),{signal:facetController.signal});if(serial!==facetSerial)return;activeTotal=data.active_total;professionFacets=data;renderProfessionFacets();
    renderLocationFilters(data);
    if(data.company)companyFacetData=data.company;else if(data.companies)companyFacetData=data.companies.map(c=>({value:c,count:0}));
    renderHeroCompanyOptions();
    for(const key of groupKeys){const box=$('facet-'+key);const query=box.querySelector('.facet-search').value.toLocaleLowerCase('tr');const items=[...(data[key]||[])];for(const value of filters[key]||[])if(!items.some(i=>i.value===value))items.push({value,count:0});
      box.querySelector('.facet-options').innerHTML=items.map(item=>`<label class="check" ${tr(item.value).toLocaleLowerCase('tr').includes(query)?'':'hidden'}><input type="checkbox" data-facet="${key}" value="${esc(item.value)}" ${(filters[key]||[]).includes(item.value)?'checked':''}><span class="facet-name">${esc(tr(item.value))}</span><small>${item.count}</small></label>`).join('')||'<p class="help">Seçenek bulunamadı.</p>';facetCollapse(box);
    }
    $('hint-embed').textContent=`${data.missing_embeddings} ilanın eşleştirme verisi eksik.`;$('hint-classify').textContent=`${data.not_locally_classified} ilan yerel yapay zekâyla işlenmemiş.`;
    groqAvailable=!!data.groq_available;$('hint-groq').textContent=groqAvailable?`${data.not_groq_classified} ilan Groq ile analiz edilmemiş.`:'Groq anahtarı tanımlı değil.';$('classify-groq').disabled=busy||!groqAvailable;
    if(!lastJobs.length)renderJobs();
  }catch(e){if(e.name!=='AbortError')$('connection').textContent='Filtre sayıları güncellenemedi.';}
}
function renderLocationFilters(data){
  const country=$('location-country'),city=$('location-city');if(!country||!city)return;
  const actualLocations=items=>(items||[]).filter(item=>item.value&&String(item.value).trim());
  locationFacetData={country:actualLocations(data.country),city:actualLocations(data.city)};
  const selectedCountry=filters.country||'';
  const selectedCities=getSelectedCities();
  cityOptionsCountry=selectedCountry;
  const countryItems=[...locationFacetData.country];
  country.innerHTML='<option value="">Tüm ülkeler</option>'+countryItems.map(item=>`<option value="${esc(item.value)}">${esc(item.value)} (${Number(item.count).toLocaleString('tr-TR')})</option>`).join('');
  country.value=selectedCountry;
  const cityItems=selectedCountry?[...locationFacetData.city]:[];
  city.innerHTML='<option value="">Tüm şehirler</option>'+cityItems.map(item=>`<option value="${esc(item.value)}">${esc(item.value)} (${Number(item.count).toLocaleString('tr-TR')})</option>`).join('');
  city.hidden=!selectedCountry;city.disabled=!selectedCountry;city.value=selectedCountry?(selectedCities[0]||''):'';
  renderHeroLocationOptions();
}
function renderHeroCompanyOptions(){
  const list=$('heroCompanyOptionsList');if(!list)return;
  const selectedCompanies=getSelectedCompanies();
  const selectedSet=new Set(selectedCompanies);
  const query=($('heroCompanyQuickSearch')?.value||'').trim().toLocaleLowerCase('tr');
  const matches=item=>!query||String(item.value).toLocaleLowerCase('tr').includes(query);
  const items=companyFacetData.filter(matches);

  const allBtn=`<div class="flex items-center justify-between px-2 py-1.5 mb-1 bg-subtle-light dark:bg-white/[0.04] rounded-lg">
    <button type="button" data-hero-company-clear class="text-[11px] font-semibold text-[#0A66C2] dark:text-[#70B5F9] hover:underline cursor-pointer">
      ${selectedCompanies.length?'Tüm Şirketleri Temizle':'🌐 Tüm Şirketler (Filtresiz)'}
    </button>
    <span class="text-[10px] font-mono font-medium text-ink-muted">
      ${selectedCompanies.length?`${selectedCompanies.length} seçili`:'Filtresiz'}
    </span>
  </div>`;

  const itemsHtml=items.length?items.map(item=>{
    const isChecked=selectedSet.has(item.value);
    const initial=(item.value||'?').trim().charAt(0).toLocaleUpperCase('tr');
    const hue=brandHue(item.value||'');
    return `<label class="flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs cursor-pointer hover:bg-black/5 dark:hover:bg-white/5 transition-colors select-none group">
      <div class="flex items-center gap-2.5 min-w-0">
        <input type="checkbox" data-hero-company-checkbox value="${esc(item.value)}" ${isChecked?'checked':''} class="w-4 h-4 rounded text-[#0A66C2] focus:ring-[#0A66C2] border-zinc-400 dark:border-zinc-600 bg-white dark:bg-zinc-800 cursor-pointer">
        <span class="w-5 h-5 rounded-md flex items-center justify-center text-[10px] font-bold border shrink-0 ${hue}">${esc(initial)}</span>
        <span class="truncate ${isChecked?'font-bold text-[#0A66C2] dark:text-[#70B5F9]':'text-slate-800 dark:text-zinc-200 group-hover:text-slate-900 dark:group-hover:text-white'}">${esc(item.value)}</span>
      </div>
      <span class="text-[10px] font-mono text-ink-muted shrink-0">${item.count?Number(item.count).toLocaleString('tr-TR'):''}</span>
    </label>`;
  }).join(''):'<p class="px-2.5 py-3 text-xs text-ink-muted">Eşleşen şirket bulunamadı.</p>';

  list.innerHTML=allBtn+itemsHtml;
}

function renderHeroLocationOptions(){
  const list=$('heroLocationOptionsList')||$('countryCityOptionsList');if(!list)return;
  const country=filters.country||'';
  const selectedCities=getSelectedCities();
  const selectedSet=new Set(selectedCities);
  const query=($('heroLocationQuickSearch')?.value||$('countryCityQuickSearch')?.value||'').trim().toLocaleLowerCase('tr');
  const matches=item=>!query||String(item.value).toLocaleLowerCase('tr').includes(query);

  const headerLeft=$('heroLocationHeaderLeft');
  const searchInput=$('heroLocationQuickSearch')||$('countryCityQuickSearch');

  if(!country){
    if(headerLeft)headerLeft.innerHTML='<span class="text-xs font-bold uppercase tracking-wider text-ink-muted">1. Adım: Ülke Seçin</span>';
    if(searchInput)searchInput.placeholder='Ülke ara... (örn. Türkiye)';
    const items=(locationFacetData.country||[]).filter(matches);
    const allBtn=`<button type="button" data-hero-country-option="" class="flex w-full items-center justify-between px-3 py-2 text-left text-xs rounded-lg hover:bg-black/5 dark:hover:bg-white/5 transition-colors cursor-pointer group"><span class="font-semibold text-slate-800 dark:text-zinc-200 group-hover:text-[#0A66C2] dark:group-hover:text-[#70B5F9]">🌐 Tüm Konumlar (Filtresiz)</span></button>`;
    const countriesHtml=items.map(item=>`<button type="button" data-hero-country-option="${esc(item.value)}" class="flex w-full items-center justify-between px-3 py-2 text-left text-xs rounded-lg hover:bg-black/5 dark:hover:bg-white/5 transition-colors cursor-pointer group"><span class="font-medium text-slate-800 dark:text-zinc-200 group-hover:text-[#0A66C2] dark:group-hover:text-[#70B5F9]">${item.value==='Türkiye'?'🇹🇷 ':''}${esc(item.value)}</span><span class="text-[10px] font-mono text-ink-muted">${Number(item.count).toLocaleString('tr-TR')}</span></button>`).join('')||'<p class="px-3 py-3 text-xs text-ink-muted">Eşleşen ülke bulunamadı.</p>';
    list.innerHTML=allBtn+countriesHtml;
    return;
  }

  // Country selected: Step 2 (Checkbox list of cities)
  if(headerLeft)headerLeft.innerHTML=`<div class="flex items-center gap-1.5 min-w-0"><span class="text-xs font-bold text-slate-900 dark:text-white truncate">${country==='Türkiye'?'🇹🇷 ':''}${esc(country)}</span><button type="button" data-hero-change-country class="text-[11px] font-semibold text-[#0A66C2] dark:text-[#70B5F9] hover:underline cursor-pointer shrink-0">Değiştir</button></div>`;
  if(searchInput)searchInput.placeholder=`${country} şehri ara... (örn. İstanbul)`;

  const cities=(locationFacetData.city||[]).filter(matches);
  const actionRow=`<div class="flex items-center justify-between px-2 py-1.5 mb-1 bg-subtle-light dark:bg-white/[0.04] rounded-lg"><button type="button" data-hero-city-select-all class="text-[11px] font-semibold text-[#0A66C2] dark:text-[#70B5F9] hover:underline cursor-pointer">${selectedCities.length?'Tüm Şehirleri Temizle':'Tüm Şehirler'}</button><span class="text-[10px] font-mono font-medium text-ink-muted">${selectedCities.length?`${selectedCities.length} şehir seçili`:'Tümü aktif'}</span></div>`;

  const itemsHtml=cities.length?cities.map(item=>{
    const isChecked=selectedSet.has(item.value);
    return `<label class="flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs cursor-pointer hover:bg-black/5 dark:hover:bg-white/5 transition-colors select-none group"><div class="flex items-center gap-2.5 min-w-0"><input type="checkbox" data-hero-city-checkbox value="${esc(item.value)}" ${isChecked?'checked':''} class="w-4 h-4 rounded text-[#0A66C2] focus:ring-[#0A66C2] border-zinc-400 dark:border-zinc-600 bg-white dark:bg-zinc-800 cursor-pointer"><span class="truncate ${isChecked?'font-bold text-[#0A66C2] dark:text-[#70B5F9]':'text-slate-800 dark:text-zinc-200 group-hover:text-slate-900 dark:group-hover:text-white'}">${esc(item.value)}</span></div><span class="text-[10px] font-mono text-ink-muted shrink-0">${Number(item.count).toLocaleString('tr-TR')}</span></label>`;
  }).join(''):'<p class="px-2.5 py-3 text-xs text-ink-muted">Bu ülkeye ait eşleşen şehir bulunamadı.</p>';

  list.innerHTML=actionRow+itemsHtml;
}
const renderCountryCityOptions=renderHeroLocationOptions;
function renderProfessionFacets(){
  const host=$('profession-tree');if(!host)return;
  const query=($('profession-filter-search')?.value||'').toLocaleLowerCase('tr');
  const roots=professionFacets.profession_tree||{},rootCounts=new Map((professionFacets.profession_group||[]).map(x=>[x.value,x.count]));
  host.innerHTML=Object.entries(roots).map(([group,items])=>{
    const shown=items.filter(item=>!query||group.toLocaleLowerCase('tr').includes(query)||item.value.toLocaleLowerCase('tr').includes(query));
    if(query&&!shown.length)return '';
    const rootChecked=(filters.profession_group||[]).includes(group);
    return `<details class="profession-root" ${query||rootChecked||items.some(x=>(filters.profession_subgroup||[]).includes(x.value))?'open':''}><summary><span>${esc(group)}</span><small>${rootCounts.get(group)||0}</small></summary><div class="profession-children"><label class="check profession-root-choice"><input type="checkbox" data-facet="profession_group" value="${esc(group)}" ${rootChecked?'checked':''}><span>Tüm ana gruptaki ilanlar</span></label>${shown.map(item=>`<label class="check profession-child"><input type="checkbox" data-facet="profession_subgroup" value="${esc(item.value)}" ${(filters.profession_subgroup||[]).includes(item.value)?'checked':''}><span>${esc(item.value)}</span><small>${item.count||0}</small></label>`).join('')}</div></details>`;
  }).join('')||'<p class="help">Eşleşen meslek grubu bulunamadı.</p>';
}
function loadAll(){loadJobs();loadFacets();loadNewCount();}
async function loadNewCount(){
  try{const data=await api('/api/jobs?per_page=1&created_from='+encodeURIComponent(seen.mark));const n=data.total,only=filters.created_from===seen.mark;
    $('new-strip').hidden=!n&&!only;
    $('new-strip-text').innerHTML=n?`<strong>${n.toLocaleString('tr-TR')} yeni ilan</strong> son kontrolünden beri eklendi`:'Son kontrolünden beri yeni ilan yok';
    $('new-only').textContent=only?'Tüm ilanları göster':'Sadece yenileri göster';$('new-only').className=only?'small':'primary small';
  }catch{}
}
function markAllSeen(){if(filters.created_from===seen.mark)delete filters.created_from;seen.mark=new Date().toISOString();saveSeen();syncControls();renderChips();persist(true);loadAll();toast('Tüm ilanlar görüldü sayıldı. Bundan sonra eklenenler “yeni” olarak işaretlenir.');}
function resetFilters(){filters={};const qs=$('heroCompanyQuickSearch');if(qs)qs.value='';syncControls();renderChips();persist(true);loadAll();}
const scheduleFilters=debounce((key,value)=>setFilter(key,value));
function applySearch(){
  const value=$('search').value.trim();
  if((filters.search||'')===value)return;
  if(value)filters.search=value;else delete filters.search;
  delete filters.page;syncControls();persist(true);renderChips();loadAll();
}
const scheduleSearch=debounce(applySearch);
function submitSearch(){scheduleSearch.cancel();applySearch();}

function descriptionHtml(text){return esc(text||'İlan açıklaması bulunamadı.').split(/\n\s*\n/).map(p=>'<p>'+p+'</p>').join('');}
function safeLink(url){try{const parsed=new URL(url);return ['http:','https:'].includes(parsed.protocol)?parsed.href:null;}catch{return null;}}
const translationCache=new Map();
let currentJobTranslated=false;

function renderJobDetailHtml(j, n){
  const link=safeLink(j.url),posted=postedAgo(j.posted_at);
  const initial=(j.company||'?').trim().charAt(0).toLocaleUpperCase('tr');
  const hue=brandHue(j.company||'');
  const parentCat=(j.profession_groups||[])[0]||tr(j.category)||'Genel Meslekler';
  const subCat=(j.profession_subgroups||[])[0]||'';
  const seniority=[j.opportunity_type && j.opportunity_type!=='unknown'?tr(j.opportunity_type):'',j.seniority&&j.seniority!=='Unknown'?tr(j.seniority):''].filter(Boolean).join(' · ');

  return `
    <p class="dev-only id-text text-[11px] text-ink-muted">İlan kimliği: #${esc(j.id)} · Kaynak kimliği: ${esc(j.external_id||'—')}</p>
    
    <!-- LinkedIn tarzı şirket ve başlık alanı -->
    <div class="flex items-start gap-4">
      <div class="w-14 h-14 rounded-2xl border ${hue} flex items-center justify-center font-display font-extrabold text-2xl shrink-0 shadow-sm">
        ${esc(initial)}
      </div>
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2 mb-1">
          <button type="button" data-filter-company="${esc(j.company||'')}" class="text-xs font-semibold text-[#0A66C2] dark:text-[#70B5F9] hover:underline text-left cursor-pointer" title="${esc(j.company || 'Şirket belirtilmemiş')} ile filtrele">${esc(j.company||'Şirket belirtilmemiş')}</button>
          <span class="text-black/20 dark:text-white/20">·</span>
          <span class="text-xs text-ink-muted">${esc(j.location||'Konum belirtilmemiş')}</span>
        </div>
        <h2 id="job-detail-title" class="font-display font-bold text-xl sm:text-2xl text-slate-900 dark:text-white leading-tight flex items-center gap-2" translate="yes">
          <span>${esc(j.title||'Unvan belirtilmemiş')}</span>
          <span class="text-[#0A66C2] dark:text-[#70B5F9] text-base" title="Onaylı ilan">✓</span>
        </h2>
        <div class="flex flex-wrap items-center gap-2 text-xs text-ink-muted mt-1.5">
          <span>${esc(j.location||'Türkiye')}</span>
          <span>·</span>
          <span>${posted?.fresh?'Bugün yayınlandı':(posted?esc(posted.text):'Tarih belirtilmemiş')}</span>
          <span>·</span>
          <span class="text-emerald-600 dark:text-emerald-400 font-medium">100'den fazla başvuru</span>
          ${isNewJob(j)?`<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-[#E6F4EA] text-[#057642]">Yeni</span>`:''}
          ${j.deleted_at?`<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-500/10 text-rose-600 border border-rose-500/20">Çöp kutusunda</span>`:''}
        </div>
      </div>
    </div>

    <!-- LinkedIn yeşil başvuran inceleme şeridi -->
    <div class="flex items-center gap-2 text-xs font-semibold text-emerald-800 dark:text-emerald-300 bg-emerald-500/10 px-3.5 py-2 rounded-xl border border-emerald-500/20 w-fit">
      <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
      <span>Başvuranlar aktif olarak inceleniyor</span>
    </div>

    <!-- LinkedIn tarzı karakteristik hapları (✓ İş yerinde, ✓ Tam Zamanlı) -->
    <div class="flex flex-wrap items-center gap-2">
      <span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-subtle-light dark:bg-white/[0.06] text-slate-800 dark:text-zinc-200 border border-black/5 dark:border-white/5">
        <svg class="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>
        <span>${esc(tr(j.workplace_type||'İş yerinde'))}</span>
      </span>
      <span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-subtle-light dark:bg-white/[0.06] text-slate-800 dark:text-zinc-200 border border-black/5 dark:border-white/5">
        <svg class="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>
        <span>${esc(tr(j.category||'Tam Zamanlı'))}</span>
      </span>
      ${seniority?`<span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-subtle-light dark:bg-white/[0.06] text-slate-800 dark:text-zinc-200 border border-black/5 dark:border-white/5">
        <svg class="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>
        <span>${esc(seniority)}</span>
      </span>`:''}
      ${j.salary?`<span class="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs font-mono font-bold bg-[#E6F4EA] dark:bg-[#057642]/25 text-[#057642] dark:text-emerald-300 border border-[#057642]/20">
        <span>💰 ${esc(j.salary)}</span>
      </span>`:''}
    </div>

    <!-- LinkedIn tarzı aksiyon butonları -->
    <div class="flex flex-wrap items-center gap-2.5 pt-1 border-b border-black/[0.06] dark:border-white/[0.08] pb-5">
      ${link?`<a class="inline-flex items-center gap-2 px-6 py-2.5 rounded-full text-xs font-bold bg-[#0A66C2] hover:bg-[#004182] text-white shadow-xs transition-colors cursor-pointer" href="${esc(link)}" target="_blank" rel="noopener noreferrer">
        <svg class="w-4 h-4 fill-current" viewBox="0 0 24 24"><path d="M19 3a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14m-.5 15.5v-5.3a3.26 3.26 0 0 0-3.26-3.26c-.85 0-1.84.52-2.28 1.3v-1.11h-2.79v8.37h2.79v-4.93c0-.77.62-1.4 1.39-1.4a1.4 1.4 0 0 1 1.4 1.4v4.93h2.75M6.46 10.9v8.37H9.2V10.9H6.46M7.83 6.64c-.95 0-1.69.75-1.69 1.69a1.69 1.69 0 0 0 1.69 1.69c.94 0 1.69-.75 1.69-1.69 0-.94-.75-1.69-1.69-1.69Z"/></svg>
        <span>Kolay Başvuru</span>
        <span>↗</span>
      </a>`:''}
      ${j.deleted_at?button('restore-job','Geri yükle',`data-id="${j.id}"`,'px-5 py-2.5 rounded-full text-xs font-semibold text-emerald-600 hover:bg-emerald-500/10 border border-emerald-500/30'):`<button data-action="delete-job" data-id="${j.id}" class="px-5 py-2.5 rounded-full text-xs font-semibold border border-[#0A66C2] text-[#0A66C2] dark:text-[#70B5F9] hover:bg-[#0A66C2]/10 transition-colors cursor-pointer" title="Çöp kutusuna taşır, geri alınabilir">Kaydet / Gizle</button>`}
      <button id="job-translate-toggle" data-action="toggle-translate" data-id="${j.id}" type="button" class="inline-flex items-center gap-1.5 px-4 py-2.5 rounded-full text-xs font-semibold bg-blue-50 dark:bg-blue-950/40 text-[#0A66C2] dark:text-[#70B5F9] border border-[#0A66C2]/20 hover:bg-[#0A66C2]/10 transition-colors cursor-pointer" title="İlanın başlığını ve açıklamasını Türkçeye çevir">
        <span class="text-sm">🌐</span>
        <span id="job-translate-btn-label">Türkçeye Çevir</span>
      </button>
      ${button('similar','Benzer ilanlar',`data-id="${j.id}"`,'px-4 py-2.5 rounded-full text-xs font-semibold bg-surface-light dark:bg-white/5 border border-black/10 dark:border-white/10 hover:border-[#0A66C2]')}
    </div>

    <!-- LinkedIn tarzı Başvuru & Durum Öğrenme Kutusu -->
    <div class="p-4 rounded-xl bg-[#F8FAFD] dark:bg-white/[0.02] border border-black/[0.06] dark:border-white/[0.06] flex items-center justify-between gap-3">
      <div>
        <h4 class="text-xs font-bold text-slate-900 dark:text-white">Diğer 100 başvurana kıyasla durumunuzu öğrenin</h4>
        <p class="text-[11px] text-ink-muted mt-0.5">Başvuranlara dair özel eşleşme ve pozisyon yeteneklerini analiz edin.</p>
      </div>
      ${typeof j.score==='number'?`<span class="px-3 py-1 rounded-full text-xs font-bold bg-[#E8F3FF] dark:bg-[#0A66C2]/30 text-[#0A66C2] dark:text-[#70B5F9] shrink-0">Eşleşme %${Math.round(j.score*100)}</span>`:''}
    </div>

    ${j.detail_pending?`<div class="notice pending-box p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-700 dark:text-amber-300 text-xs flex items-center justify-between gap-3"><p>İlanın açıklaması sırayla arka planda tamamlanacak.</p><button data-action="fetch-detail" data-id="${j.id}" class="px-3 py-1 rounded-lg text-xs font-bold bg-amber-600 text-white cursor-pointer">Şimdi getir</button></div>`:''}

    ${j.summary?`<div class="space-y-2"><h4 class="font-display font-bold text-xs uppercase tracking-wider text-ink-muted">Pozisyon Özeti ve Sorumluluklar</h4><p id="job-detail-summary" class="text-sm leading-relaxed text-ink-secondary dark:text-zinc-300 bg-subtle-light/40 dark:bg-white/[0.02] p-4 rounded-xl border border-black/5 dark:border-white/5" translate="yes">${esc(j.summary)}</p></div>`:''}

    ${j.flag_reason?`<p class="notice warn p-3 rounded-xl bg-rose-500/10 border border-rose-500/20 text-xs text-rose-700 dark:text-rose-300">Dikkat: ${esc(j.flag_reason)}</p>`:''}

    ${j.tags?.length?`<div class="space-y-2"><h4 class="font-display font-bold text-xs uppercase tracking-wider text-ink-muted">Sınıflandırma ve Yetenek Etiketleri</h4><div class="flex flex-wrap gap-1.5">${j.tags.map(t=>`<span class="px-2.5 py-1 rounded-full text-xs font-mono bg-canvas-light dark:bg-white/5 border border-black/10 dark:border-white/10 text-ink-secondary dark:text-zinc-300">${esc(t)}</span>`).join('')}</div></div>`:''}

    <!-- İş ilanı hakkında -->
    ${j.detail_pending?'':`<div class="space-y-2.5">
      <div class="flex items-center justify-between">
        <h3 class="font-display font-bold text-base text-slate-900 dark:text-white">İş ilanı hakkında</h3>
        <span id="job-translate-badge" class="hidden inline-flex items-center gap-1 px-2.5 py-0.5 rounded-md text-[11px] font-medium bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
          <span>🌐</span><span>Türkçe Çeviri</span>
        </span>
      </div>
      <div id="job-detail-desc" class="job-desc text-sm leading-relaxed text-ink-secondary dark:text-zinc-300 space-y-3.5" translate="yes">
        ${descriptionHtml(j.formatted_description||j.description)}
      </div>
    </div>
    ${j.formatted_description?`<details class="pt-2"><summary class="text-xs font-semibold text-ink-muted cursor-pointer hover:underline">Kaynak açıklamayı göster</summary><div class="job-desc text-xs text-ink-muted pt-2">${descriptionHtml(j.description)}</div></details>`:''}`}

    ${j.offerings?.length?`<div class="space-y-2"><h4 class="font-display font-bold text-xs uppercase tracking-wider text-ink-muted">Sunulan Olanaklar</h4><ul class="list-disc list-inside text-sm text-ink-secondary dark:text-zinc-300 space-y-1">${j.offerings.map(o=>`<li>${esc(o)}</li>`).join('')}</ul></div>`:''}

    ${j.about_company?`<div class="space-y-2"><h4 class="font-display font-bold text-xs uppercase tracking-wider text-ink-muted">Şirket Hakkında</h4><p class="text-sm text-ink-secondary dark:text-zinc-300 leading-relaxed">${esc(j.about_company)}</p></div>`:''}

    ${repairControls(j)}

    <details class="job-section job-meta-more pt-2 text-xs border-t border-black/5 dark:border-white/5"><summary class="font-semibold text-ink-muted cursor-pointer">Kayıt bilgileri</summary><div class="pt-2 space-y-1 text-ink-muted"><p>Yayın: ${esc(date(j.posted_at))} · İlk eklenme: ${esc(date(j.created_at))} · Son tarama: ${esc(date(j.scraped_at))}</p><p>Arama ilişkileri (${j.search_ids.length})</p>${j.discoveries.map(d=>`<p class="id-text font-mono text-[11px]">Arama: ${esc(d.search_id)} · ${d.is_new?'İlk kez ekledi':'Bu aramada da bulundu'} · ${esc(date(d.found_at))}</p>`).join('')||'<p>Eski kaydın arama ilişkisi bulunamadı.</p>'}</div></details>

    <div id="similar-results" class="pt-2"></div>
  `;
}

async function openJob(id, openMobileDrawer = true){
  currentJob=Number(id);detailController?.abort();detailController=new AbortController();const signal=detailController.signal;
  currentJobTranslated=false;

  // Sol listedeki kart seçim vurgusunu güncelle
  document.querySelectorAll('#grid .job-card').forEach(el=>{
    const isThis = el.dataset.id === String(id);
    el.classList.toggle('selected-job', isThis);
    el.classList.toggle('border-l-4', isThis);
    el.classList.toggle('border-l-[#0A66C2]', isThis);
    el.classList.toggle('bg-blue-50/45', isThis);
    el.classList.toggle('dark:bg-[#0A66C2]/15', isThis);
    el.classList.toggle('ring-2', isThis);
    el.classList.toggle('ring-[#0A66C2]', isThis);
  });

  if($('job-category-path'))$('job-category-path').textContent='İlan yükleniyor…';
  if($('job-title'))$('job-title').textContent='İlan yükleniyor…';
  if($('persistent-category-path'))$('persistent-category-path').textContent='İlan yükleniyor…';
  
  const loadingHtml = '<div class="p-12 text-center text-ink-muted"><div class="inline-block w-6 h-6 border-2 border-[#0A66C2] border-t-transparent rounded-full animate-spin mb-2"></div><p class="text-xs">İlan detayları yükleniyor…</p></div>';
  if($('job-content'))$('job-content').innerHTML=loadingHtml;
  if($('persistent-job-content'))$('persistent-job-content').innerHTML=loadingHtml;

  if($('previous-job'))$('previous-job').disabled=true;
  if($('next-job'))$('next-job').disabled=true;
  if($('job-position'))$('job-position').textContent='';
  if($('persistent-prev-job'))$('persistent-prev-job').disabled=true;
  if($('persistent-next-job'))$('persistent-next-job').disabled=true;
  if($('persistent-job-position'))$('persistent-job-position').textContent='';

  if(openMobileDrawer && window.innerWidth < 1024){
    showDialog('job-dialog');
    const panel=$('jobDrawerPanel');if(panel)panel.scrollTop=0;
  }

  try{
    const [j,n]=await Promise.all([api('/api/jobs/'+id,{signal}),api('/api/jobs/'+id+'/navigation?'+params(),{signal})]);
    if(currentJob!==Number(id))return;
    nav=n;
    currentJobTranslated=false;

    seenIds.add(j.id);saveSeen();
    document.querySelector(`.job-card[data-id="${j.id}"]`)?.classList.add('seen');

    const parentCat=(j.profession_groups||[])[0]||tr(j.category)||'Genel Meslekler';
    const subCat=(j.profession_subgroups||[])[0]||'';
    const breadcrumb=parentCat+(subCat?' → '+subCat:'');
    if($('job-category-path'))$('job-category-path').textContent=breadcrumb;
    if($('persistent-category-path'))$('persistent-category-path').textContent=breadcrumb;
    if($('job-title'))$('job-title').textContent=j.title||'İlan detayı';

    const detailHtml = renderJobDetailHtml(j, n);
    if($('job-content'))$('job-content').innerHTML=detailHtml;
    if($('persistent-job-content'))$('persistent-job-content').innerHTML=detailHtml;

    if($('previous-job'))$('previous-job').disabled=!n.previous;
    if($('next-job'))$('next-job').disabled=!n.next;
    if($('job-position'))$('job-position').textContent=`${n.position} / ${n.total} ilan`;

    if($('persistent-prev-job'))$('persistent-prev-job').disabled=!n.previous;
    if($('persistent-next-job'))$('persistent-next-job').disabled=!n.next;
    if($('persistent-job-position'))$('persistent-job-position').textContent=`${n.position} / ${n.total} ilan`;

    const persistentPane = $('persistent-detail-pane');
    if(persistentPane && !openMobileDrawer) persistentPane.scrollTop = 0;
  }catch(e){
    if(e.name!=='AbortError'){
      if($('job-category-path'))$('job-category-path').textContent='Hata';
      if($('job-title'))$('job-title').textContent='İlan yüklenemedi';
      const errHtml = `<div class="notice error p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-xs text-rose-700 dark:text-rose-300"><p>${esc(e.message)}</p><button data-action="job" data-id="${id}" class="mt-2 px-3 py-1 rounded-lg bg-rose-600 text-white font-bold cursor-pointer">Tekrar dene</button></div>`;
      if($('job-content'))$('job-content').innerHTML=errHtml;
      if($('persistent-job-content'))$('persistent-job-content').innerHTML=errHtml;
    }
  }
}

async function toggleJobTranslation(id){
  const btns=document.querySelectorAll('#job-translate-toggle');
  const labels=document.querySelectorAll('#job-translate-btn-label');
  const badges=document.querySelectorAll('#job-translate-badge');
  const titleEls=document.querySelectorAll('#job-detail-title');
  const descEls=document.querySelectorAll('#job-detail-desc');
  const summaryEls=document.querySelectorAll('#job-detail-summary');
  if(!titleEls.length||!descEls.length)return;
  const jobId=Number(id);
  if(currentJobTranslated){
    const orig=translationCache.get(jobId)?.original;
    if(orig){
      titleEls.forEach(el=>el.textContent=orig.title);
      descEls.forEach(el=>el.innerHTML=orig.descHtml);
      if(orig.summary)summaryEls.forEach(el=>el.textContent=orig.summary);
    }
    currentJobTranslated=false;
    labels.forEach(l=>l.textContent='Türkçeye Çevir');
    badges.forEach(b=>b.classList.add('hidden'));
    return;
  }
  if(translationCache.has(jobId)&&translationCache.get(jobId).translated){
    const trans=translationCache.get(jobId).translated;
    titleEls.forEach(el=>el.textContent=trans.title);
    descEls.forEach(el=>el.innerHTML=descriptionHtml(trans.description));
    if(trans.summary)summaryEls.forEach(el=>el.textContent=trans.summary);
    currentJobTranslated=true;
    labels.forEach(l=>l.textContent='Orijinali Göster');
    badges.forEach(b=>b.classList.remove('hidden'));
    return;
  }
  labels.forEach(l=>l.textContent='Çevriliyor…');
  btns.forEach(b=>b.disabled=true);
  try{
    const res=await api('/api/jobs/'+jobId+'/translate',{method:'POST'});
    if(!res||!res.ok)throw new Error(res?.error||'Çeviri tamamlanamadı.');
    translationCache.set(jobId,{
      original:{title:titleEls[0].textContent,descHtml:descEls[0].innerHTML,summary:summaryEls[0]?summaryEls[0].textContent:''},
      translated:res
    });
    titleEls.forEach(el=>el.textContent=res.title);
    descEls.forEach(el=>el.innerHTML=descriptionHtml(res.description));
    if(res.summary)summaryEls.forEach(el=>el.textContent=res.summary);
    currentJobTranslated=true;
    labels.forEach(l=>l.textContent='Orijinali Göster');
    badges.forEach(b=>b.classList.remove('hidden'));
    toast('İlan başlığı ve açıklaması Türkçeye çevrildi.');
  }catch(err){
    toast('Çeviri yapılamadı: '+err.message);
    labels.forEach(l=>l.textContent='Türkçeye Çevir');
  }finally{
    btns.forEach(b=>b.disabled=false);
  }
}

async function similar(id){const box=$('similar-results');box.innerHTML='<p class="notice">Benzer ilanlar aranıyor…</p>';const data=await api(`/api/jobs/${id}/similar`);box.innerHTML=data.reason==='no_embedding'?'<p class="notice">Bu ilanın eşleştirme verisi eksik. Tarama panelindeki “Kayıtlı ilanları yeniden işle” bölümünden hazırlayabilirsin.</p>':data.jobs.length?'<h3 class="job-section">Benzer ilanlar</h3>'+data.jobs.map(j=>button('job',`${j.title} · ${j.company}`,`data-id="${j.id}"`)).join(' '):'<p class="notice">Benzer ilan bulunamadı.</p>';}
async function jobAction(id,action){
  if(action==='purge'&&!await confirmAction('Bu ilan tüm arama havuzlarından kalıcı olarak silinecek. Geri alınamaz. Devam edilsin mi?'))return;
  const data=await api('/api/trash/jobs',{method:'POST',body:{ids:[Number(id)],action}});closeDialog('job-dialog');loadAll();
  toast(action==='delete'?'İlan çöp kutusuna taşındı.':action==='restore'?'İlan geri yüklendi.':'İlan kalıcı olarak silindi.',action==='delete'?async()=>{await api('/api/trash/jobs',{method:'POST',body:{ids:data.ids,action:'restore'}});loadAll();}:null);
}
async function trashFiltered(){if(!total){toast('İşlem yapılacak ilan yok.');return;}if(!await confirmAction(`Mevcut filtrelere uyan ${total} ilan çöp kutusuna taşınacak. Devam edilsin mi?`))return;const data=await api('/api/jobs?'+params(),{method:'DELETE'});loadAll();toast(`${data.count} ilan çöp kutusuna taşındı.`,async()=>{await api('/api/trash/jobs',{method:'POST',body:{ids:data.ids,action:'restore'}});loadAll();});}

function packageGroups(tasks){
  // Ardışık aynı paketli görevleri tek blokta toplar; paketsiz görevler tek başına kalır.
  const groups=[];tasks.forEach((t,i)=>{const last=groups[groups.length-1];if(t.package&&last&&last.name===t.package)last.items.push([t,i]);else groups.push({name:t.package||'',items:[[t,i]]});});return groups;
}
function packageTarget(items){return items.some(([t])=>t.limit==null)?'limitsiz':items.reduce((sum,[t])=>sum+t.limit,0)+' ilan hedefi';}
function packageHead(name,items,extra=''){const places=[...new Set(items.map(([t])=>t.location))].join(', ');return `<div class="package-head"><div><strong>Paket: ${esc(name)}</strong><p class="help">${items.length} alt görev · toplam ${packageTarget(items)} · ${esc(places)}</p></div>${extra}</div>`;}
function draftRow(t,i){return `<div class="task-row"><p class="id-text">Görev kimliği: ${esc(t.id)}</p><label>Unvan<input data-draft="${i}" data-key="keyword" value="${esc(t.keyword)}"></label><div class="field-pair"><label>Konum<input data-draft="${i}" data-key="location" value="${esc(t.location)}"></label><label>Hedef <input data-draft="${i}" data-key="limit" type="number" min="1" step="1" value="${t.limit??''}" placeholder="Limitsiz"></label></div><div class="actions">${button('draft-up','↑ Yukarı',`data-index="${i}" ${i===0?'disabled':''}`)}${button('draft-down','↓ Aşağı',`data-index="${i}" ${i===draft.length-1?'disabled':''}`)}${button('draft-remove','Kaldır',`data-index="${i}"`)}</div></div>`;}
function renderDraft(){
  $('draft-tasks').innerHTML=packageGroups(draft).map(g=>g.name?`<section class="package">${packageHead(g.name,g.items,button('draft-package-remove','Paketi kaldır',`data-index="${g.items[0][1]}" data-count="${g.items.length}"`))}<details><summary>Alt görevleri göster ve düzenle</summary>${g.items.map(([t,i])=>draftRow(t,i)).join('')}</details></section>`:draftRow(...g.items[0])).join('');
  $('queue-identity').textContent=draftRunId?'Kuyruk süreç kimliği: '+draftRunId:'Görevler düzenlendiğinde kuyruk sunucuya kaydedilir.';
}
function scheduleDraftSave(){clearTimeout(draftSaveTimer);if(queueStarting)return;draftSaveTimer=setTimeout(()=>saveDraft().catch(e=>{$('task-error').textContent='Kuyruk sunucuya kaydedilemedi: '+e.message;}),600);}
function saveDraft(){
  const tasks=draft.map(t=>({...t})),backend=$('classify-backend').value,embeddings=$('use-embeddings').checked,mode=$('scrape-mode').value,refresh=$('refresh-details').checked;
  draftSaveChain=draftSaveChain.catch(()=>{}).then(async()=>{const data=await api('/api/queue',{method:'POST',body:{run_id:draftRunId,tasks,classify_backend:backend,use_embeddings:embeddings,mode,refresh_details:refresh,opportunity_type:$('collection-opportunity-type').value}});draftRunId=data.run_id;persist();$('queue-identity').textContent=draftRunId?'Kuyruk süreç kimliği: '+draftRunId:'';return draftRunId;});return draftSaveChain;
}
function addTasks(){
  const keywords=$('kw-input').value.split(/[,\n]+/).map(s=>s.trim()).filter(Boolean);const location=$('loc-input').value.trim();const raw=$('limit-input').value;const limit=$('unlimited').checked?null:Number(raw);
  if(!keywords.length||!location||limit!==null&&(!raw||!Number.isInteger(limit)||limit<=0)){$('task-error').textContent='En az bir unvan, konum ve pozitif tam sayı hedefi girin. Limitsiz seçeneğini de kullanabilirsiniz.';return false;}
  $('task-error').textContent='';const existing=new Set(draft.map(t=>JSON.stringify([t.keyword.trim(),t.location.trim(),t.limit,t.package||''])));let skipped=0;for(const keyword of keywords){const key=JSON.stringify([keyword,location,limit,'']);if(existing.has(key)){skipped++;continue;}existing.add(key);draft.push({id:newId(),keyword,location,limit});}if(skipped)toast(`${skipped} aynı unvan, konum ve hedef zaten kuyrukta.`);$('kw-input').value='';renderDraft();persist();scheduleDraftSave();return true;
}
// Türkçe küçük harfte "AI" → "aı" olur; ı/i farkı tekrar tespitini bozmasın.
const titleKey=t=>t.toLocaleLowerCase('tr').replace(/ı/g,'i').replace(/\s+/g,' ').trim();
function formLimit(){const raw=$('limit-input').value,limit=$('unlimited').checked?null:Number(raw);return limit===null||raw&&Number.isInteger(limit)&&limit>0?{ok:true,limit}:{ok:false};}
async function suggestTitles(){
  const typed=$('kw-input').value.split(/[,\n]+/).map(s=>s.trim()).filter(Boolean);
  if(!typed.length){$('task-error').textContent='Önce çoğaltılacak bir unvan yazın.';return;}
  const field=typed.join(', ').slice(0,120);
  $('task-error').textContent='';$('suggest-titles').disabled=true;$('suggest-titles').textContent='Unvanlar hazırlanıyor…';
  try{const data=await api('/api/title-suggestions',{method:'POST',body:{field,count:5}});
    // Yazılan unvan her zaman listede kalır; yapay zekâ önerileri arkasından gelir.
    const seen=new Set(),titles=[...typed,...data.titles].filter(t=>{const k=titleKey(t);if(seen.has(k))return false;seen.add(k);return true;});
    $('suggest-box').dataset.package=field;$('suggest-legend').textContent=`“${field}” için önerilen unvanlar`;
    $('suggest-list').innerHTML=titles.map(t=>`<label class="check"><input type="checkbox" data-suggest value="${esc(t)}" checked>${esc(t)}</label>`).join('');
    $('suggest-box').hidden=false;updateSuggestCount();$('suggest-box').scrollIntoView({block:'nearest'});}
  catch(e){$('task-error').textContent=e.message;}
  finally{$('suggest-titles').disabled=false;$('suggest-titles').textContent='Yapay zekâ ile 5 ortogonal unvana çoğalt';}
}
function updateSuggestCount(){
  if($('suggest-box').hidden)return;
  const n=document.querySelectorAll('#suggest-list [data-suggest]:checked').length,{ok,limit}=formLimit(),location=$('loc-input').value.trim()||'konum yok';
  $('suggest-summary').textContent=!n?'Hiç unvan seçilmedi.':!ok?'Unvan başına hedef pozitif tam sayı olmalı.':limit===null?`${n} unvan · limitsiz · ${location}`:`${n} unvan × ${limit} ilan = toplam ${n*limit} ilan hedefi · ${location}`;
  $('add-suggested').textContent=n?`${n} unvanlık paketi kuyruğa ekle`:'Paketi kuyruğa ekle';$('add-suggested').disabled=!n||!ok;
}
function closeSuggestions(){$('suggest-box').hidden=true;$('suggest-list').innerHTML='';$('suggest-summary').textContent='';}
function addSuggested(){
  const location=$('loc-input').value.trim(),{ok,limit}=formLimit(),pack=$('suggest-box').dataset.package||'';
  if(!location||!ok){$('task-error').textContent='Konum ve pozitif tam sayı hedef girin. Limitsiz seçeneğini de kullanabilirsiniz.';return false;}
  const picked=[...document.querySelectorAll('#suggest-list [data-suggest]:checked')].map(el=>el.value);
  if(!picked.length){$('task-error').textContent='Pakete en az bir unvan seçin.';return false;}
  const known=new Set(draft.map(t=>titleKey(t.keyword)+'|'+t.location));
  const added=picked.filter(k=>!known.has(titleKey(k)+'|'+location));
  for(const keyword of added)draft.push({id:newId(),keyword,location,limit,package:pack});
  $('task-error').textContent='';$('kw-input').value='';closeSuggestions();
  renderDraft();persist();scheduleDraftSave();
  toast(added.length?`“${pack}” paketi eklendi: ${added.length} alt görev${limit==null?'':' · toplam '+added.length*limit+' ilan hedefi'}.`:'Seçilen unvanlar zaten kuyrukta.');return true;
}
async function openDrawer(){$('new-search-form').hidden=false;$('drawer-title').textContent='Yeni tarama';showDialog('drawer');renderDraft();
  try{const models=await api('/api/ollama/models');$('classify-model').innerHTML='<option value="">Varsayılan model</option>'+models.models.map(m=>`<option>${esc(m)}</option>`).join('');setOllama(true);}catch{setOllama(false);}
}
async function startScrape(){
  if(!$('suggest-box').hidden){if(!addSuggested())return;}else if($('kw-input').value.trim()&&!addTasks())return;if(!draft.length){$('task-error').textContent='Önce kuyruğa en az bir görev ekleyin.';return;}
  for(const t of draft)if(!t.keyword.trim()||!t.location.trim()||t.limit!=null&&(!Number.isInteger(t.limit)||t.limit<1)){$('task-error').textContent='Görevlerdeki unvan, konum ve hedefleri kontrol edin.';return;}
  clearTimeout(draftSaveTimer);queueStarting=true;$('start-scrape').disabled=true;$('task-error').textContent='';
  try{const runId=await saveDraft();const started=await api(`/api/runs/${runId}/resume`,{method:'POST'});draft=[];draftRunId=null;persist();renderDraft();closeDialog('drawer');showTab('queue');
    if(started.scheduled){await pollStatus();toast('Kuyruğa eklendi. Sistem uygun olunca sırayla kendiliğinden başlayacak.');}
    else{activeLogRun=runId;currentRun=await api('/api/runs/'+runId);renderRun();await pollStatus();toast('Tarama kuyruğu başlatıldı.');}}
  catch(e){$('task-error').textContent=e.message;}finally{queueStarting=false;renderSource();}
}
function setOllama(available){
  // Ollama yoksa (ör. VPS) yerel yapay zekâ gerektiren seçenekler seçilemez; hızlı analiz kullanılır.
  const local=$('classify-backend').querySelector('option[value="local"]');local.disabled=!available;local.textContent=available?'Yerel yapay zekâ — Ollama':'Yerel yapay zekâ — Ollama (bu sunucuda kurulu değil)';
  if(!available&&$('classify-backend').value==='local')$('classify-backend').value='rules';
  $('use-embeddings').disabled=!available;if(!available)$('use-embeddings').checked=false;
  for(const id of ['embed-jobs','classify-jobs'])$(id).dataset.ollama=available?'1':'0';
  if(!available){$('embed-jobs').disabled=true;$('classify-jobs').disabled=true;$('maintenance-status').textContent='Ollama bu sunucuda çalışmadığı için yerel yapay zekâ işlemleri kapalı.';}
}
function renderSource(){
  const blocked=!!sourceState?.paused;
  $('source-status').hidden=!blocked;$('source-status').textContent=blocked?sourcePauseExplanation(sourceState):sourceState?.message||'';
  $('acknowledge-source').hidden=!sourceState?.manual_pause;$('acknowledge-source').disabled=!sourceState?.acknowledge_allowed;
  // Sistem meşgulken veya kaynak beklerken kuyruk sıraya alınır; servis uygun olunca başlatır.
  $('start-scrape').disabled=queueStarting;$('start-scrape').textContent=blocked||busy?'Kuyruğa ekle — uygun olunca başlar':'Kuyruğu başlat';
  document.querySelectorAll('[data-action="control-resume"]').forEach(el=>el.disabled=false);
  // Kaynak beklemesi üstteki bekleme şeridinde gösterilir; durum çubuğunda tekrarlanmaz.
  renderWait();
}
function renderWait(){
  const sourceWait=sourceState?.paused;
  const retryWait=!!currentRun?.automatic_resume&&!!currentRun?.next_attempt_at;
  const deadline=sourceWait?sourceState.blocked_until*1000:retryWait?currentRun.next_attempt_at*1000:waitingUntil;
  const remaining=Math.max(0,Math.ceil((deadline-Date.now())/1000));
  $('wait-banner').hidden=!sourceWait&&!retryWait&&!(busy&&remaining>0);
  $('wait-title').textContent=sourceWait?'Kaynak erişimi nedeniyle toplama bekliyor':retryWait?'İşlem yeniden denenecek':'İstekler arasında bekleniyor';
  $('wait-explanation').textContent=sourceWait?sourcePauseExplanation(sourceState):retryWait?currentRun.status_reason:waitReason;
  const interval=sourceState?.effective_interval,maximum=sourceState?.interval_with_jitter_max;
  $('effective-interval').textContent=interval!=null?`Geçerli istek aralığı: ${Number(interval).toFixed(1)}–${Number(maximum??interval).toFixed(1)} saniye. Önceki sınırlandırmalar bu aralığı artırabilir.`:'';
  $('wait-countdown').textContent=remaining>0?[Math.floor(remaining/3600),Math.floor(remaining%3600/60),remaining%60].map(n=>String(n).padStart(2,'0')).join(':'):'Devam kontrolü…';
  $('wait-next').textContent=sourceWait?`Yeniden deneme: ${new Date(deadline).toLocaleString('tr-TR')} · Yeni bir ret gelirse bekleme uzayabilir.`:'Bekleme tamamlandığında işlem otomatik sürecek.';
  document.querySelectorAll('[data-source-countdown]').forEach(el=>{el.textContent=$('wait-countdown').textContent;});
  renderPill();
}
function sourcePauseExplanation(source){
  const response=source.status_code?`Kaynak HTTP ${source.status_code} döndürdü. `:'';
  const reported=source.reported_retry_after_seconds;
  const applied=source.applied_pause_seconds;
  const duration=applied!=null?` Uygulanan mola: ${Math.ceil(applied/60)} dakika.`:'';
  if(source.cooldown_origin==='local_fallback')return response+'Kaynak bekleme süresi bildirmedi; mola uygulamanın artan bekleme kuralıyla hesaplandı.'+duration;
  if(source.cooldown_origin==='retry_after_and_local_policy')return response+`Kaynağın bildirdiği süre: ${reported} saniye. Uygulamanın koruma kuralı daha uzun bekleme gerektiriyor.`+duration;
  if(source.cooldown_origin==='retry_after')return response+`Kaynağın bildirdiği bekleme süresi: ${reported} saniye.`+duration;
  return response+'Bu mola eski sürümden devralındı; sürenin kaynağı eski kayıtta belirtilmemiş. Süre dolunca otomatik yeniden denenecek.';
}
// Üst çubuktaki küçük durum göstergesi; ayrıntı Tarama kuyruğunda.
function renderPill(){
  const pill=$('sys-pill'),waiting=!$('wait-banner').hidden,running=runActive()||busy;
  pill.hidden=!waiting&&!running;pill.dataset.state=waiting?'wait':'run';
  if(waiting)pill.textContent=`Toplama molada · ${$('wait-countdown').textContent}`;
  else if(runActive()){const done=currentRun.tasks.filter(t=>terminalStatus(t.status)).length;pill.textContent=`Yeni ilanlar toplanıyor · ${done}/${currentRun.tasks.length}`;}
  else if(busy)pill.textContent='İlanlar işleniyor…';
  // Menüdeki Kuyruk düğmesinde bekleyen/çalışan kuyruk sayısı
  const open=waitingRuns.length+(currentRun&&!terminalStatus(currentRun.status)?1:0),badge=$('nav-queue-badge');
  badge.hidden=!open;badge.textContent=open;badge.classList.toggle('live',runActive());
}
const terminalStatus = status => ['finished','cancelled','stopped'].includes(status);
const activeStatus = status => ['running','pausing','stopping','cancelling'].includes(status);
function duration(seconds){if(seconds==null)return 'Bilinmiyor';seconds=Math.max(0,Math.floor(seconds));const h=Math.floor(seconds/3600),m=Math.floor(seconds%3600/60),sec=seconds%60;return (h?h+' sa ':'')+(m?m+' dk ':'')+sec+' sn';}
function elapsed(item){return item.started_at&&(!terminalStatus(item.status)||item.ended_at)?Math.max(0,((item.ended_at?Date.parse(item.ended_at+'Z'):Date.now())-Date.parse(item.started_at+'Z'))/1000):null;}
function clockHtml(item){if(terminalStatus(item.status)&&!item.ended_at)return 'Bilinmiyor';return `<span data-clock-start="${esc(item.started_at||'')}" data-clock-end="${esc(item.ended_at||'')}">${esc(duration(elapsed(item)))}</span>`;}
function updateQueueClocks(){document.querySelectorAll('[data-clock-start]').forEach(el=>{el.textContent=duration(elapsed({started_at:el.dataset.clockStart,ended_at:el.dataset.clockEnd}));});renderWait();}
function statusBadge(status){return `<span class="state-pill state-${esc(status)}"><span aria-hidden="true">●</span> ${esc(tr(status))}</span>`;}
function metricHtml(stats,count){return `<div class="queue-metrics"><div><strong>${count}</strong><span>Çekilen</span></div><div class="metric-new"><strong>${stats.new||0}</strong><span>Yeni eklenen</span></div><div class="metric-updated"><strong>${stats.updated||0}</strong><span>Güncellenen</span></div><div><strong>${stats.unchanged||0}</strong><span>Değişmeyen</span></div></div>`;}
function reasonHtml(item){const reasons={source_paused:'Kaynak erişimi veya bekleme talebi nedeniyle duraklatıldı.',stopped_by_user:'Kullanıcı tarafından duraklatıldı.',page_fetch_failed:'Arama sayfası alınamadı.',reached_limit:'Hedef ilan sayısına ulaşıldı.',exhausted_results:'Kaynak daha fazla sonuç döndürmedi.',repeated_page:'Kaynak daha önce görülen ilanları tekrar döndürdü.',no_new_jobs:'Yeni ilan kalmadı (tümü kayıtlı).',low_yield_threshold:'Yeni ilan verimi eşik altına (%20) düştüğü için erken tamamlandı (kota korundu).'};const reason=item.status_reason||item.error||reasons[item.stats?.termination_reason];return reason&&item.status!=='running'?`<p class="queue-reason"><strong>${item.status==='error'?'Hata nedeni':item.status==='paused'?'Duraklama nedeni':'Durum açıklaması'}:</strong> ${esc(reason)}</p>`:'';}
function taskControls(run,t){if(run.deleted_at||terminalStatus(run.status)||terminalStatus(t.status)||run.kind&&run.kind!=='scrape')return '';const attr=`data-run="${run.id}" data-task="${t.id}"`;if(t.status==='running'&&run.status==='running')return button('control-pause','Duraklat',attr)+button('control-stop','Sorguyu durdur',attr,'danger');if(t.status==='queued'&&!t.has_started)return button('control-cancel','Başlamadan iptal et',attr);if(['paused','error'].includes(t.status)&&!activeStatus(run.status))return button('control-resume','Devam et',attr,'primary')+button('control-stop','Sorguyu durdur',attr,'danger');return '';}
// Durum ikonları kuyruk satırlarında ve özet kartında renk dışında ikinci bir ipucu verir.
function stateIcon(status,size=20){
  const key={pausing:'paused',stopping:'stopped',cancelling:'cancelled'}[status]||status;
  const d={running:'<path d="M21 12a9 9 0 1 1-6.2-8.6"/>',queued:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',paused:'<circle cx="12" cy="12" r="9"/><path d="M10 9v6M14 9v6"/>',error:'<path d="M10.3 3.9 2 18a2 2 0 0 0 1.7 3h16.6a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',finished:'<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',stopped:'<circle cx="12" cy="12" r="9"/><rect x="9" y="9" width="6" height="6" rx="1"/>',cancelled:'<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/>'};
  return `<svg class="state-icon${key==='running'?' spin':''}" viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d[key]||d.queued}</svg>`;
}
// Kuyruk özetinde durumu teknik terim yerine düz cümleyle anlatır.
function queueHeadline(run,now){
  if(sourceState?.paused&&!terminalStatus(run.status))return ['Kaynak molası','Kaynak erişimi bir süreliğine sınırladı. Süre dolunca kuyruk kendiliğinden devam eder; bekleme kısaltılmaz.'];
  const n=run.stats.new||0;
  return ({running:['Yeni ilanlar toplanıyor',now?`Şu an “${now.keyword}” aranıyor. Bitince sıradaki sorguya geçilir.`:'Sıradaki sorguya geçiliyor.'],
    pausing:['Duraklatılıyor','Mevcut istek bitince kuyruk duracak.'],stopping:['Durduruluyor','Mevcut istek bitince kuyruk sona erecek.'],cancelling:['İptal ediliyor','Başlamamış sorgular iptal ediliyor.'],
    paused:run.automatic_resume?['Kısa mola','Kuyruk kısa bir beklemeden sonra kendiliğinden devam edecek.']:['Kuyruk duraklatıldı','Hazır olduğunda “Kaldığı yerden devam et” ile sürdürebilirsin.'],
    error:['Bir sorun oluştu','Bazı sorgular tamamlanamadı. Nedeni aşağıda; devam ettirmeyi deneyebilirsin.'],queued:['Başlamayı bekliyor','Sistem uygun olunca kuyruk kendiliğinden başlar.'],
    finished:['Tarama tamamlandı',n?`${n} yeni ilan eklendi. İlanlar sayfasında “yeni” olarak görünür.`:'Bu turda yeni ilan çıkmadı; bilinen ilanlar güncellendi.'],
    stopped:['Tarama durduruldu','Toplanan ilanlar korundu.']})[run.status]||['İptal edildi','Başlamamış sorgular iptal edildi; toplanan ilanlar korundu.'];
}
function taskCard(run,t,editable=false){
  const stats=t.stats||{},count=t.count||0,controls=taskControls(run,t),finite=t.limit!=null;
  const edit=editable&&!terminalStatus(t.status)?button('edit-task','Düzenle',`data-task="${t.id}"`)+button('live-up','↑',`data-task="${t.id}" aria-label="Sorguyu yukarı taşı"`)+button('live-down','↓',`data-task="${t.id}" aria-label="Sorguyu aşağı taşı"`):'';
  const progress=finite?`<progress class="task-progress" max="${Math.max(1,t.limit)}" value="${Math.min(count,t.limit)}" aria-label="İlan hedefine ilerleme"></progress>`:'';
  return `<article class="task-row queue-task state-${esc(t.status)}" data-task-card="${t.id}"><div class="qt-main"><span class="qt-icon">${stateIcon(t.status)}</span><div class="qt-text"><strong>${esc(t.keyword)}</strong><small>${esc(t.location)} · ${finite?t.limit+' ilan hedefi':'Limitsiz'}</small></div><div class="qt-progress">${progress}<small><strong>${count}</strong>${finite?' / '+t.limit:''} ilan · <span class="metric-new">${stats.new||0} yeni</span></small></div>${statusBadge(t.status)}</div>${reasonHtml(t)}${controls||edit?`<div class="actions">${controls}${edit}</div>`:''}<details class="queue-identity qt-more"><summary>Ayrıntılar</summary>${metricHtml(stats,count)}<div class="queue-timing"><span>Başlangıç <strong>${t.started_at?esc(date(t.started_at)):'Henüz başlamadı / bilinmiyor'}</strong></span><span>Başlangıçtan geçen <strong>${clockHtml(t)}</strong></span></div><p class="help queue-extra">${stats.cache_hits||0} detay önbellekten · ${stats.skipped||0} işleme sırasında atlandı · ${stats.detail_failures||stats.descFailures||0} detay alınamadı</p><p class="id-text">Sorgu kimliği: ${esc(t.id)}</p></details></article>`;
}
function renderRun(){
  renderQueueView();if(!currentRun)return;const run=currentRun,active=activeStatus(run.status),resumable=['paused','error'].includes(run.status);
  const done=run.tasks.filter(t=>terminalStatus(t.status)).length,collected=run.tasks.reduce((sum,t)=>sum+t.count,0);
  $('live-tasks').innerHTML=packageGroups(run.tasks).map(g=>g.name?`<section class="package">${packageHead(g.name,g.items,`<span class="help">${g.items.filter(([t])=>terminalStatus(t.status)).length}/${g.items.length} bitti · ${g.items.reduce((sum,[t])=>sum+(t.count||0),0)} çekilen</span>`)}${g.items.map(([t])=>taskCard(run,t,resumable)).join('')}</section>`:taskCard(run,g.items[0][0],resumable)).join('');
  $('pause-run').hidden=!active&&!run.automatic_resume;$('pause-run').disabled=run.status!=='running'&&!run.automatic_resume;$('pause-run').textContent=run.automatic_resume?'Otomatik devamı duraklat':'Kuyruğu duraklat';
  $('resume-run').hidden=!resumable;$('stop-run').hidden=!active&&!resumable;$('stop-run').disabled=active&&run.status!=='running';
  $('cancel-run').hidden=run.has_started||run.status!=='queued';
  $('run-summary').hidden=false;
  $('run-summary').className='queue-overview state-'+run.status;
  const now=run.tasks.find(t=>t.status==='running');
  const [headline,explain]=queueHeadline(run,now);
  $('run-summary').innerHTML=`<div class="queue-hero"><span class="hero-icon">${stateIcon(sourceState?.paused&&!terminalStatus(run.status)?'paused':run.status,28)}</span><div class="hero-text"><h2>${esc(headline)}</h2><p>${esc(explain)}</p></div>${statusBadge(run.status)}</div><p class="queue-line"><span><strong>${done}/${run.tasks.length}</strong> sorgu bitti</span><span><strong>${collected}</strong> çekilen</span><span class="metric-new"><strong>${run.stats.new||0}</strong> yeni</span><span class="metric-updated"><strong>${run.stats.updated||0}</strong> güncellenen</span><span>Süre <strong>${clockHtml(run)}</strong></span></p><progress class="task-progress" max="${Math.max(1,run.tasks.length)}" value="${done}" aria-label="Tamamlanan sorgular"></progress>${now?`<p class="queue-now">Şimdi: <strong>${esc(now.keyword)}</strong> · ${esc(now.location)} · ${now.limit==null?now.count+' ilan (limitsiz)':now.count+'/'+now.limit+' ilan'}</p>`:reasonHtml(run)}${terminalStatus(run.status)&&(run.stats.new||0)?`<div class="actions">${button('run-results','Yeni ilanları gör',`data-run="${run.id}"`,'primary')}</div>`:''}`;
  $('live-details-summary').textContent='Süreç ayrıntıları ve rapor';
  $('run-details').innerHTML=`${metricHtml(run.stats,collected)}<div class="queue-timing"><span>İlk başlangıç <strong>${run.started_at?esc(date(run.started_at)):'Henüz başlamadı / bilinmiyor'}</strong></span><span>Başlangıçtan geçen <strong>${clockHtml(run)}</strong></span><span>Kuyruğa eklenme <strong>${esc(date(run.created_at))}</strong></span></div><div class="actions">${button('run-results','Toplanan ilanları gör',`data-run="${run.id}"`)}${button('run-report','Süreç raporu',`data-run="${run.id}"`)}</div><details class="queue-identity"><summary>Süreç kimliği</summary><p class="id-text">${run.id}</p></details>`;
  $('status-bar').hidden=!!sourceState?.paused&&!activeStatus(run.status);$('status-bar').className='status-bar state-'+run.status;$('status-text').textContent=`${tr(run.status)} · ${collected} çekilen · ${run.stats.new||0} yeni · ${run.stats.updated||0} güncellenen · ${run.stats.unchanged||0} değişmeyen`;
  const task=run.tasks.find(t=>t.status==='running');$('status-progress').max=Math.max(1,run.tasks.length);$('status-progress').value=done;
  const activePackage=(task||run.tasks.find(t=>!terminalStatus(t.status)))?.package||'';const remaining=Math.ceil((waitingUntil-Date.now())/1000);const pkgLabel=activePackage?`Paket: ${activePackage} · `:'';$('status-detail').textContent=remaining>0&&active?`${waitReason} · ${remaining} saniye`:task?`${pkgLabel}${task.keyword} · ${task.location} · ${task.limit==null?'Limitsiz tarama':task.count+'/'+task.limit+' ilan'}`:run.status_reason||'Sonuçlar korundu. Ayrıntılar tarama panelinde.';
  renderSource();
  renderWait();
  if(run.kind&&run.kind!=='scrape'){$('run-details').innerHTML='';$('run-summary').innerHTML=`<strong>${esc(tr(run.status))}</strong><p>${run.stats.embedded??run.stats.classified??0} ilan işlendi · ${run.stats.skipped||0} başarısız deneme</p>${reasonHtml(run)}${button('run-report','Süreç raporunu aç',`data-run="${run.id}"`)}`;}
}
async function controlTask(runId,taskId,action){
  if(action==='stop'&&!await confirmAction('Bu sorgu sonuçları korunarak durdurulacak. Aynı sorguya devam edilemez; gerekiyorsa yeni tarama başlatabilirsiniz. Kuyruk çalışıyorsa sonraki sorguya geçer.'))return;
  await api(`/api/runs/${runId}/tasks/${taskId}/${action}`,{method:'POST'});
  currentRun=await api('/api/runs/'+runId);renderRun();await pollStatus();if($('history-dialog').open)await loadHistory();
  if(action==='resume'){closeDialog('history-dialog');showTab('queue');}
}
async function cancelAll(){
  if(!await confirmAction('Çalışan ve bekleyen tüm taramalar beklemeye alınacak; iş alarmları ve rutin şehir taramaları duraklatılacak. Hiçbiri kendiliğinden başlamaz. Devam edilsin mi?'))return;
  const r=await api('/api/queue/cancel-all',{method:'POST'});
  toast(`${r.paused} tarama beklemeye alındı, ${r.watches_disabled} iş alarmı kapatıldı. Rutin şehir taramaları duraklatıldı.`);
  if(currentRun)currentRun=await api('/api/runs/'+currentRun.id).catch(()=>currentRun);renderRun();await pollStatus();loadWatches().catch(()=>{});
}
async function runAction(id,action){
  if(action==='purge'&&!await confirmAction('Arama geçmişi, havuzu ve logları kalıcı olarak silinecek. Ortak ilanlar sistemde kalacak. Devam edilsin mi?'))return;
  if(action==='stop'&&!await confirmAction('Kuyruk sonuçları korunarak durdurulacak. Devam etmek için yeni tarama oluşturmanız gerekir. Durdurulsun mu?'))return;
  if(action==='cancel'&&!await confirmAction('Henüz başlamamış kuyruk iptal edilsin mi?'))return;
  const result=await api(`/api/runs/${id}/${action}`,{method:'POST'});
  if(action==='resume'&&draftRunId===id){draft=[];draftRunId=null;clearTimeout(draftSaveTimer);persist();renderDraft();}
  if(['delete','restore','purge'].includes(action)){await loadHistory();await loadRunOptions();toast(action==='delete'?'Arama geçmişi çöp kutusuna taşındı. İlanlar korundu.':action==='restore'?'Arama geçmişi geri yüklendi.':'Arama geçmişi kalıcı silindi.',action==='delete'?async()=>{await api(`/api/runs/${id}/restore`,{method:'POST'});await loadHistory();loadRunOptions();}:null);}
  else if(result.scheduled){closeDialog('history-dialog');showTab('queue');await pollStatus();toast('Sıraya alındı. Sistem uygun olunca kendiliğinden devam edecek.');}
  else{currentRun=await api('/api/runs/'+id);renderRun();if(action==='resume'){closeDialog('history-dialog');showTab('queue');}await pollStatus();}
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
let waitingRuns=[],waitingKey='';const openWaiting=new Set();
function renderWaiting(){
  const key=JSON.stringify([waitingRuns,!!sourceState?.paused,busy]);if(key===waitingKey)return;waitingKey=key;
  $('waiting-runs').hidden=!waitingRuns.length;renderQueueView();if(!waitingRuns.length){$('waiting-list').innerHTML='';return;}
  $('waiting-title').textContent=`Sırada bekleyenler (${waitingRuns.length})`;
  $('waiting-help').textContent=`${sourceState?.paused?'Kaynak beklemesi bitince':busy?'Çalışan tarama bitince':'Birazdan'} sırayla kendiliğinden başlar. Bekleme süreleri kısaltılmaz.`;
  $('waiting-list').innerHTML=waitingRuns.map((r,i)=>{
    const names=r.tasks.map(t=>t.keyword),packs=[...new Set(r.tasks.map(t=>t.package).filter(Boolean))],places=[...new Set(r.tasks.map(t=>t.location))].join(', ');
    const title=packs.length?'Paket: '+packs.join(', '):names.slice(0,2).join(', ')+(names.length>2?` +${names.length-2}`:'');
    return `<details class="waiting-run state-${esc(r.status)}" data-waiting="${esc(r.id)}" ${openWaiting.has(r.id)?'open':''}><summary><span class="waiting-order">${i+1}</span><span class="waiting-main"><strong>${esc(title)}</strong><small>${r.tasks.length} sorgu · ${esc(places)}${r.watch?' · İş alarmı':''}${r.status!=='queued'?' · kaldığı yerden devam edecek':''}</small></span></summary>
      <ul class="waiting-tasks">${r.tasks.map(t=>`<li>${esc(t.keyword)} <span class="muted">· ${esc(t.location)} · ${t.limit==null?'Limitsiz':t.limit+' ilan'}</span></li>`).join('')}</ul>
      <div class="actions">${r.status==='queued'?button('waiting-cancel','Başlamadan iptal et',`data-run="${esc(r.id)}"`,'danger'):button('waiting-pause','Otomatik devamı durdur',`data-run="${esc(r.id)}"`)}</div></details>`;}).join('');
}
async function waitingAction(id,action){
  if(action==='cancel'&&!await confirmAction('Sıradaki bu kuyruk başlamadan iptal edilsin mi? Daha önce toplanan ilanlar korunur.'))return;
  try{await api(`/api/runs/${id}/${action==='cancel'?'cancel':'pause'}`,{method:'POST'});toast(action==='cancel'?'Sıradaki kuyruk iptal edildi.':'Otomatik devam durduruldu. Geçmiş aramalardan devam ettirebilirsin.');}
  catch(e){toast(e.message,null,'',true);}
  await pollStatus();
}
async function acknowledgeSource(){try{await api('/api/source/acknowledge',{method:'POST'});await pollStatus();toast('Kaynak duraklatması kaldırıldı. Kuyruğu devam ettirebilirsiniz.');}catch(e){toast(e.message,null,'',true);}}
async function pollStatus(){
  try{const status=await api('/api/scrape/status');busy=status.running;sourceState=status.source_state;waitingRuns=status.waiting||[];renderSource();renderWaiting();renderQueueLayers(status);lastPoll=Date.now();
    if(status.run){currentRun=status.run;activeLogRun=currentRun.id;renderRun();}
    else if(busy){$('status-bar').hidden=false;$('status-text').textContent=status.kind==='repair'?'İlanın eksik alanları tamamlanıyor…':status.kind==='embed'?'İlan eşleştirmeleri hazırlanıyor…':'İlanlar analiz ediliyor…';$('status-detail').textContent='Yeni manuel istekler en yüksek öncelikle kuyruğa alınır.';$('status-progress').removeAttribute('value');}
    else if(currentRun&&activeStatus(currentRun.status)){currentRun=await api('/api/runs/'+currentRun.id);renderRun();}
    if($('history-dialog').open)loadHistory();
    $('embed-jobs').disabled=$('embed-jobs').dataset.ollama==='0';$('classify-jobs').disabled=$('classify-jobs').dataset.ollama==='0';$('stop-maintenance').hidden=!busy||['scrape','repair'].includes(status.kind);$('classify-groq').disabled=!groqAvailable;
  }catch(e){$('connection').textContent='Sunucu bağlantısı bekleniyor…';}
}
let queueLayerStatus=null;
function renderQueueLayers(status){
  queueLayerStatus=status.queue_layers;
  const host=$('completion-queue'),layers=status.queue_layers,cq=status.completion_queue;
  if(!host||!layers||!cq)return;
  host.innerHTML=`<h3>Katmanlı görev kuyruğu</h3><p>Önce manuel görevlerin, sonra eksik ve hatalı ilanlar, ardından şehir × meslek rutinleri çalışır.</p>${layers.layers.map(l=>`<section data-queue-layer="${esc(l.key)}"><h4>${Number(l.priority)}. ${esc(l.label)} ${layers.active_layer===l.key?'<span class="state-pill state-running">Çalışıyor</span>':''}</h4><p>${Number(l.ready)} hazır · ${Number(l.waiting)} beklemede · ${Number(l.completed)} tamamlandı${l.draft?' · '+Number(l.draft)+' taslak':''}</p></section>`).join('')}<p class="help">Tamamlama: ${Number(cq.stages.detail||0)} kaynak detayı · ${Number(cq.stages.enrich||0)} alan işleme · ${Number(cq.counts.retry||0)} yeniden deneme · ${Number(cq.counts.unavailable||0)} kaynakta kaldırılmış.</p><p class="help">${layers.source_paused?'Kaynak erişimi beklemede. Ağ isteği gerektirmeyen hazır işler devam edebilir.':'Hazır manuel görev yoksa eksikler tamamlanır; hazır eksik yoksa rutin tarama yapılır.'} Alt katmandaki iş, daha yüksek öncelikli bir görev geldiğinde ilerlemesini koruyarak sırayı bırakır.</p>`;
  host.insertAdjacentHTML('beforeend',`<div class="actions">${button(cq.paused?'completion-resume':'completion-pause',cq.paused?'Otomatik tamamlamayı devam ettir':'Otomatik tamamlamayı duraklat')}</div>`);
}
function repairControls(j){
  if(j.deleted_at||j.source!=='linkedin'||!/^\d+$/.test(String(j.external_id)))return '';
  const fields=[['description','Açıklama'],['title','Unvan'],['company','Şirket'],['location','Konum'],['tags','Yetenekler'],['experience_years','Deneyim'],['workplace_type','Çalışma biçimi'],['category','Kategori'],['seniority','Kıdem']];
  return `<details class="job-section"><summary>Eksik veya hatalı alanları tamamla</summary><p class="help">Yeniden alınacak alanları seç. Bu isteğin manuel kuyruğa eklenir.</p><div>${fields.map(([key,label])=>`<label class="check"><input type="checkbox" data-repair-field="${key}" ${key==='description'?'checked':''}>${label}</label>`).join('')}</div>${button('repair-job','Seçili alanları kuyruğa al',`data-id="${j.id}"`)}</details>`;
}
async function repairJob(id){
  const fields=[...document.querySelectorAll('#job-content [data-repair-field]:checked')].map(el=>el.dataset.repairField);
  if(!fields.length){toast('Tamamlanacak en az bir alan seç.');return;}
  await api('/api/jobs/'+id+'/repair',{method:'POST',body:{fields}});toast('Seçili alanlar manuel öncelikle kuyruğa eklendi.');await pollStatus();
}
function connectEvents(){
  const source=new EventSource('/events');source.onopen=()=>{$('connection').textContent='Canlı';$('connection').dataset.state='ok';$('connection').title='Yeni ilanlar toplanırken bildirim şeridi güncellenir; liste akışınız kesintiye uğramaz.';pollStatus();};source.onerror=()=>{$('connection').textContent='Yeniden bağlanılıyor…';$('connection').dataset.state='warn';};
  const refreshStatus=debounce(pollStatus,300);
  const refreshNewCount=debounce(loadNewCount,1200);
  source.onmessage=event=>{let ev;try{ev=JSON.parse(event.data);}catch{return;}const d=ev.data||{};
    if(['waiting','shared_rate_wait'].includes(ev.type)){waitingUntil=Date.now()+d.seconds*1000;waitReason=d.reason;renderWait();refreshStatus();}
    if(ev.type==='job'){waitingUntil=0;if(!lastJobs.length){debounce(loadAll,1000)();}else{refreshNewCount();}refreshStatus();}
    if(['task_start','task_done','job_progress','run_finished','finished','error','source_paused','task_control'].includes(ev.type)){refreshStatus();}
    if(ev.type==='run_finished'){if(!$('view-watches').hidden)loadWatches();if(Dash.visible())Dash.load(true);currentRun=d;renderRun();refreshNewCount();loadRunOptions();if($('history-dialog').open)loadHistory();toast(`Çalışma ${tr(d.status).toLocaleLowerCase('tr')}: ${d.stats.new||0} yeni, ${d.stats.updated||0} güncellenen ilan.`,()=>{showResults('run_id',d.id);},'Sonuçları gör');}
    if(ev.type==='notice'||ev.type==='error'){toast(d.msg||'İşlem tamamlanamadı. Sonuçlar korundu.',()=>showTab('queue'),'Ayrıntılar',true);}
    if(ev.type==='log'&&busy&&!currentRun)$('maintenance-status').textContent=localLogMessage(d.msg);
    if(ev.type==='finished'&&!d.run_id){$('maintenance-status').textContent=`İşlem tamamlandı. ${d.embedded??d.classified??0} ilan işlendi, ${d.skipped||0} ilan atlandı.`;refreshNewCount();}
  };
  setInterval(()=>{if(document.visibilityState==='visible'){if(Date.now()-lastPoll>4000)pollStatus();updateQueueClocks();renderWait();}},1000);
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'){pollStatus();refreshNewCount();}});
}
async function loadRunOptions(){try{const data=await api('/api/runs');$('run-filter').innerHTML='<option value="">Tüm çalışmalar</option>'+data.runs.map(r=>`<option value="${r.id}">${esc(date(r.created_at))} · ${esc(r.tasks.map(t=>t.keyword).join(', '))}</option>`).join('');$('run-filter').value=filters.run_id?.[0]||'';if(!currentRun){const paused=data.runs.find(r=>['paused','error'].includes(r.status));if(paused){currentRun=paused;renderRun();}}}catch{}}

async function openHistory(){showDialog('history-dialog');await loadHistory();}
async function loadHistory(){try{const data=await api('/api/runs'+($('history-trash').checked?'?trash=1':''));historyRuns=data.runs;selectedHistory=new Set([...selectedHistory].filter(id=>historyRuns.some(r=>r.tasks.some(t=>t.id===id))));renderHistory();}catch(e){$('history-list').innerHTML=`<p class="notice error">${esc(e.message)}</p>${button('history','Tekrar dene')}`;}}
function renderHistory(){
  const query=$('history-search').value.toLocaleLowerCase('tr');const visible=historyRuns.filter(r=>(!$('history-status').value||r.status===$('history-status').value)&&JSON.stringify(r).toLocaleLowerCase('tr').includes(query));
  $('history-list').innerHTML=visible.map(r=>`<article class="run-card state-${esc(r.status)}"><div class="run-heading"><div><strong>${esc(date(r.created_at))}</strong> ${statusBadge(r.status)}</div><div class="actions">${!r.deleted_at?button('run-results','Çalışmanın ilanları',`data-run="${r.id}"`)+(['paused','error'].includes(r.status)?button('run-resume','Devam et',`data-run="${r.id}"`):'')+(r.status==='running'?button('run-pause','Kuyruğu duraklat',`data-run="${r.id}"`):'')+(['running','paused','error'].includes(r.status)?button('run-stop','Kuyruğu durdur',`data-run="${r.id}"`,'danger'):'')+(r.status==='queued'&&!r.has_started?button('run-cancel','Başlamadan iptal et',`data-run="${r.id}"`):'')+button('run-restart','Yeniden tara',`data-run="${r.id}"`)+button('run-delete','Çöp kutusuna taşı',`data-run="${r.id}"`):button('run-restore','Geri yükle',`data-run="${r.id}"`)+button('run-purge','Kalıcı sil',`data-run="${r.id}"`,'danger')}</div></div>
    ${metricHtml(r.stats,r.tasks.reduce((n,t)=>n+t.count,0))}<div class="queue-timing"><span>Başlangıç <strong>${r.started_at?esc(date(r.started_at)):'Bilinmiyor / başlamadı'}</strong></span><span>Geçen süre <strong>${clockHtml(r)}</strong></span></div>${reasonHtml(r)}
    ${r.tasks.map(t=>`<div class="history-task"><label class="history-select"><input type="checkbox" data-history-select="${t.id}" ${selectedHistory.has(t.id)?'checked':''}>Sorguyu seç</label>${taskCard(r,t)}<div class="actions">${button('task-results','İlanları gör',`data-task="${t.id}"`)}${button('task-new-results','İlk kez eklenenler',`data-task="${t.id}"`)}${button('task-queue','Kuyruğa ekle',`data-task="${t.id}"`)}${button('task-restart','Yeniden tara',`data-task="${t.id}"`)}${button('task-logs','İşlem kayıtları',`data-task="${t.id}" data-run="${r.id}"`)}${button('task-report','Arama verimi',`data-task="${t.id}" data-run="${r.id}"`)}</div></div>`).join('')}</article>`).join('')||'<div class="empty"><h2>Arama geçmişi bulunamadı</h2><p>Aramalar burada görünür.</p></div>';
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
function showResults(key,id,onlyNew=false){filters={ [key]:[id], ...(onlyNew?{discovery:'new'}:{})};syncControls();renderChips();persist(true);loadAll();closeDialog('history-dialog');closeDialog('drawer');showTab('jobs');$('main').scrollIntoView({block:'start'});}
async function queueTasks(tasks,restart=false){
  if(!tasks.length){toast('Önce en az bir arama seçin.');return;}
  draft.push(...tasks.map(t=>({id:newId(),keyword:t.keyword,location:t.location,limit:t.limit,package:t.package||''})));renderDraft();persist();if(!restart)scheduleDraftSave();closeDialog('history-dialog');await openDrawer(true);
  if(restart)await startScrape();else toast(`${tasks.length} görev kuyruğa eklendi. Konumları ve limitleri korundu.`);
}
async function historyBatch(action){
  const tasks=historyRuns.filter(r=>!r.kind||r.kind==='scrape').flatMap(r=>r.tasks).filter(t=>action==='all'||selectedHistory.has(t.id));
  if(action==='delete'){const ids=historyRuns.filter(r=>r.tasks.some(t=>selectedHistory.has(t.id))).map(r=>r.id);if(!ids.length){toast('Önce arama seçin.');return;}if(!await confirmAction(`${ids.length} çalışma geçmişi çöp kutusuna taşınacak. Bu çalışmalardaki seçilmemiş görevler de geçmişin parçasıdır; ortak ilanlar silinmez. Devam edilsin mi?`))return;let failures=0;for(const id of ids){try{await api(`/api/runs/${id}/delete`,{method:'POST'});}catch{failures++;}}await loadHistory();loadRunOptions();toast(failures?`${failures} çalışma taşınamadı. Aktif çalışmaları önce duraklatın.`:'Seçilen çalışmalar çöp kutusuna taşındı.',null,'',!!failures);return;}
  await queueTasks(tasks,action==='restart'||action==='all');
}

async function openReport(runId,taskId=null){reportContext={runId,taskId};showDialog('report-dialog');await loadReport();}
function searchEfficiencyHtml(a){
  if(!a)return '';
  const language=languageNames[a.keyword_language]||a.keyword_language;
  const reasons=(a.inefficiency_reasons||[]).map(reason=>`<li>${esc(reason)}</li>`).join('');
  const pair=a.bilingual_comparison,cohorts=(a.language_comparisons||[]).filter(c=>['tr','en'].includes(c.language));
  const cohortText=cohorts.map(c=>`${c.language==='tr'?'Türkçe':c.language==='en'?'İngilizce':'Diğer'}: ${c.new_jobs} yeni / ${c.unique_cards} benzersiz (%${c.new_yield_pct}; ${c.searches} arama, ${c.evidence} örnek)`).join(' · ');
  const winner=languageNames[pair?.result]||pair?.result;
  const comparison=pair?`<p class="help">Türkçe–İngilizce karşılaştırması: ${pair.result==='berabere'?'verimler eşit':esc(winner)+' araması daha yüksek verim gösterdi'}. ${esc(cohortText)}. ${esc(pair.note)}</p>`:'';
  return `<section class="search-efficiency"><strong>${esc(language)} araması · yeni ilan verimi %${esc(a.new_yield_pct??0)}</strong><p>${esc(a.new_jobs??0)} yeni ilan · ${esc(a.unique_cards??a.cards??0)} benzersiz sonuç · ${esc(a.duplicates??0)} tekrar · ${esc(a.detail_failures??0)} detay hatası</p>${comparison}${reasons?`<ul>${reasons}</ul>`:''}</section>`;
}
async function openDailySummary(){
  showDialog('daily-summary-dialog');$('daily-summary-content').innerHTML='<p class="notice">Son tamamlanan aramalar yükleniyor…</p>';
  try{const d=await api('/api/daily-summary');if(!d.available){$('daily-summary-content').innerHTML=`<p class="notice">${esc(d.message||'Günlük arama raporu henüz hazır değil.')}</p>`;return;}
    const pairs=(d.language_pairs||[]).map(pair=>{const tr=pair.languages.tr,en=pair.languages.en;return `<article class="task-row"><strong>${esc(pair.profession_group)} · ${esc(pair.location)}</strong><p>Türkçe: ${tr.new_jobs} yeni ilan / ${tr.unique_cards} benzersiz sonuç (%${tr.new_yield_pct}; ${tr.searches} arama)</p><p>İngilizce: ${en.new_jobs} yeni ilan / ${en.unique_cards} benzersiz sonuç (%${en.new_yield_pct}; ${en.searches} arama)</p></article>`;}).join('');
    const searches=(d.searches||[]).map(item=>`<article class="task-row"><strong>${esc(item.keyword)}</strong><p>${esc(item.location||'Tüm konumlar')} · ${esc(languageNames[item.efficiency.keyword_language]||'Diğer')} · ${esc(item.efficiency.profession_group||'')}</p>${searchEfficiencyHtml(item.efficiency)}${button('run-report','Arama raporunu aç',`data-run="${item.run_id}" data-task="${item.search_id}"`)}</article>`).join('');
    $('daily-summary-content').innerHTML=`<p>${esc(date(d.window_start))} – ${esc(date(d.window_end))}</p><div class="queue-metrics"><div><strong>${d.search_count}</strong><span>Tamamlanan arama</span></div><div><strong>${d.new_jobs}</strong><span>Yeni ilan</span></div><div><strong>${d.unique_cards}</strong><span>Benzersiz sonuç</span></div></div><section class="notice">${esc(d.summary)}</section>${pairs?`<h3>Türkçe ve İngilizce aramalar</h3>${pairs}`:''}<h3>Arama sonuçları ve verim</h3>${searches||'<p class="notice">Bu rapor döneminde tamamlanmış arama bulunamadı.</p>'}<p class="help">Rapor kaynağı: ${d.summary_source==='groq'?'Groq özeti':'ölçüm tabanlı özet'} · Oluşturulma: ${esc(date(d.generated_at))}</p>`;
  }catch(error){$('daily-summary-content').innerHTML=`<p class="field-error">${esc(error.message)}</p>`;}
}
async function loadReport(){
  if(!reportContext)return;const {runId,taskId}=reportContext,p=new URLSearchParams();if(taskId)p.set('task_id',taskId);
  $('report-content').innerHTML='<p class="notice">Süreç raporu hazırlanıyor…</p>';
  try{const r=await api(`/api/runs/${runId}/report?`+p),m=r.metrics;
const metrics=r.kind==='scrape'?[['Gönderilen istek',m.requests],['429 hata oranı',m.rate_429!=null?`%${(m.rate_429*100).toFixed(1)}`:'%0.0'],['Kaynak beklemesi oranı',m.frozen_ratio!=null?`%${(m.frozen_ratio*100).toFixed(1)}`:'%0.0'],['Toplam kaynak beklemesi',m.pause_seconds?`${m.pause_seconds} sn`:'0 sn'],['Önbellek isabet oranı',m.cache_hit_rate!=null?`%${(m.cache_hit_rate*100).toFixed(1)}`:'%0.0'],['İstek başına yeni ilan',m.useful_jobs_per_request!=null?m.useful_jobs_per_request:'0.0'],['Kaynak nedeniyle duraklama',m.source_pauses],['Kaynak beklemesi (sn)',m.source_wait_seconds],['İstek sırası beklemesi (sn)',m.shared_wait_seconds],['HTTP süresi (sn)',m.http_seconds],['İşleme süresi (sn)',m.processing_seconds],['Benzersiz görülen ilan',m.unique_returned_ids],['Benzersiz çekilen ilan',m.unique_collected_ids],['Bekleyen benzersiz detay',m.pending_unique_details],['Kaynaktan gelen kart',m.network_cards],['Saklanan sayfadan devam',m.snapshot_resumes],['Benzersiz ilan başına istek',m.requests_per_unique_job],['Kart görünümleri',m.returned_cards],['Sayfa başı ort. kart',m.avg_cards_per_page!=null?m.avg_cards_per_page:'0.0'],['Çekilen ilan (sayfa toplamı)',m.collected],['Tekrar kart',m.duplicates],['Detay hatası',m.detail_failures],['İşlenmeyen kart',m.not_processed],['Veritabanında ilişkili ilan',m.found_jobs],['İlk kez eklenen',m.new_jobs],['Güncellenen ilişki',m.updated_jobs],['Değişmeyen ilan',m.unchanged_jobs],['Önbellekten alınan detay',m.cache_hits],['Detayı istenen ilan',m.cache_misses],['Varsayılan listede görünür',m.visible_jobs],['Çöp kutusunda',m.deleted_jobs],['Eksik ayrıştırılan',m.invalid_jobs]]:[['Hedef kayıt',m.target_jobs],['İşlenen kayıt',m.processed_jobs],['İşleme hatası',m.processing_failures]];
    $('report-content').innerHTML=`<p class="id-text">Süreç: ${esc(r.run_id)}${r.search_id?'<br>Görev: '+esc(r.search_id):''}</p><p>${badge(tr(r.status))} · ${esc(date(r.generated_at))}</p><div class="actions"><a class="button" href="/api/runs/${runId}/report?${esc(p.toString())}${p.size?'&amp;':''}download=1" download>Raporu JSON indir</a>${button('run-logs','Tüm süreç kayıtlarını aç',`data-run="${runId}"`)}</div>
      <table class="report-table"><tbody>${metrics.map(([name,value])=>`<tr><th scope="row">${esc(name)}</th><td>${value==null?'Bilinmiyor':esc(value)}</td></tr>`).join('')}</tbody></table>
      <h3>Ne oldu, ne yapılabilir?</h3>${r.findings.map(f=>`<section class="notice ${f.severity==='warning'?'error':''}"><strong>${esc(f.title)}</strong><ul>${f.next_steps.map(s=>`<li>${esc(s)}</li>`).join('')}</ul><details><summary>Dayanak kayıt</summary><pre>${esc(typeof f.evidence==='string'?f.evidence:JSON.stringify(f.evidence,null,2))}</pre></details></section>`).join('')||'<p class="notice">Kayıtlarda belirgin bir sonuç kaybı nedeni görülmüyor. Aktif süreçlerin raporu ilerledikçe güncellenir.</p>'}
      <h3>Görevlerin sonucu</h3>${r.tasks.map(t=>{const termDesc={low_yield_threshold:'Eşik erken durma (yeni ilan <%20)',reached_limit:'Hedefe ulaşıldı',exhausted_results:'Kaynakta sonuç tükendi',no_new_jobs:'Yeni ilan kalmadı',repeated_page:'Tekrarlanan sayfa',stopped_by_user:'Kullanıcı durdurdu'}[t.termination_reason]||t.termination_reason||'Henüz tamamlanmadı veya eski kayıtta yok';return `<div class="task-row"><strong>${esc(t.keyword)}</strong><p>${t.collected} / ${t.target??'Limitsiz'} · ${esc(tr(t.status))}</p><p class="id-text">${esc(t.search_id)}</p><p>Durma nedeni: ${esc(termDesc)}</p>${searchEfficiencyHtml(t.search_efficiency)}${t.error?`<p class="field-error">${esc(t.error)}</p>`:''}${button('task-logs','Bu görevin kayıtları',`data-run="${runId}" data-task="${t.search_id}"`)}</div>`;}).join('')}
      <details class="job-section"><summary>Süreç zaman çizelgesi (${r.timeline.length})</summary>${r.timeline.map(e=>`<div class="log-entry"><small>${esc(date(e.at))} · Kayıt ${e.event_id}</small><p>${esc(e.kind)}</p><pre>${esc(JSON.stringify(e.data,null,2))}</pre></div>`).join('')}</details><div class="help">${r.notes.map(n=>'<p>'+esc(n)+'</p>').join('')}</div>`;
  }catch(e){$('report-content').innerHTML=`<p class="notice error">${esc(e.message)}</p>`;}
}
function localLogMessage(message){
  const replacements=[[/Accountless blocked/g,'Kaynağa erişim sınırlandı'],[/Entire run stopped; no retry or account fallback\./g,'Çalışma durdu; toplanan sonuçlar korundu.'],[/No jobs are missing embeddings\./g,'Tüm ilanların eşleştirme verisi hazır.'],[/Stopped by user\./g,'Kullanıcı tarafından durduruldu.'],[/Local embedding model unreachable.*stopping\./g,'Yerel eşleştirme modeline ulaşılamadı; işlem durdu.'],[/Public job\/page is no longer available\./g,'İlan veya sayfa artık erişilebilir değil.']];
  let text=String(message||'');for(const [pattern,replacement] of replacements)text=text.replace(pattern,replacement);return text;
}
async function openLogs(runId,taskId=null){const t=findTask(taskId)||currentRun?.tasks.find(t=>t.id===taskId);logContext={runId,taskId,folder:t?.folder};logBefore=null;$('log-query').value='';$('legacy-log').hidden=!t?.folder;$('log-kind').value='';$('log-level').value='';$('log-list').innerHTML='';$('download-logs').href=`/api/runs/${runId}/logs/download`;showDialog('log-dialog');await loadLogs();}
async function legacyLog(){if(!logContext?.folder)return;const data=await api('/api/searches/'+encodeURIComponent(logContext.folder)+'/log');$('log-list').innerHTML=`<article class="log-entry"><h3>Kaynak metin kaydı</h3><pre>${esc(data.log)}</pre></article>`;$('older-logs').hidden=true;}
function logSummary(e){const d=e.data;if(e.kind==='page_result')return `Sayfa ${d.page}: ${d.cards_returned} kart döndü · ${d.collected} çekildi · ${d.duplicates} tekrar · ${d.detail_failures} detay alınamadı · ${d.not_processed||0} işlenmedi${d.from_checkpoint?' · Saklanan kartlardan devam':''}${d.interrupted?' · Limit veya duraklama nedeniyle kesildi':''}`;
  if(e.kind==='request_started')return `İstek gönderildi · ${d.params?'Arama sayfası':'İlan detayı'}${d.params?' · sıra başlangıcı '+d.params.start:''}`;
  if(e.kind==='request_finished')return `Yanıt ${d.status??'alınamadı'} · ${d.duration_ms} ms${d.params?' · '+d.cards_returned+' ilan kartı':''}${d.error?' · '+d.error:''}`;
  if(e.kind==='job')return `İlan kaydedildi · ${d.title} · ${d.company} · ${d.outcome==='unchanged'?'Değişmedi':d.is_new?'Yeni':'Güncellendi'}`;
  if(e.kind==='task_start')return `Arama başladı · ${d.keyword} · ${d.location}`;
  if(e.kind==='task_done')return `Arama tamamlandı · ${d.count} ilan · ${d.reason||''}`;
  if(e.kind==='source_paused')return d.message;
  if(e.kind==='detail_deferred')return `İlan kartının açıklaması daha sonra tamamlanacak · ${d.external_id}`;
  if(e.kind==='routine_page_turn_started')return 'Rutin tarama sırası başladı; ilk sayfa tamamlanana kadar otomatik detay işine geçilmeyecek.';
  if(e.kind==='cache_hit')return `Detay önbellekten alındı · ${d.external_id}`;
  if(e.kind==='cache_miss'){const reasons={not_cached:'İlk kez detay isteniyor',expired:'Önbellek süresi doldu',card_changed:'İlan kartı değişti',forced_refresh:'Zorunlu yenileme seçildi'};return `${reasons[d.reason]||'Detay önbellekten kullanılamadı'} · ${d.external_id}`;}
  if(e.kind==='shared_rate_wait')return `Ortak istek aralığı bekleniyor · ${d.seconds} saniye`;
  if(e.kind==='shared_rate_wait_finished')return `İstek sırası beklemesi sona erdi · ${d.seconds} saniye`;
  if(e.kind==='run_completed')return d.status==='paused'?'Deneme durakladı; sonuçlar ve devam noktası korundu.':d.status==='finished'?'Çalışma tamamlandı.':`Deneme sona erdi · ${tr(d.status)}`;
  if(e.kind==='waiting')return `${d.reason} · ${d.seconds} saniye`;
  return localLogMessage(d.msg)||tr(e.kind);
}
async function loadLogs(older=false){if(!logContext)return;const p=new URLSearchParams();if(logContext.taskId)p.set('task_id',logContext.taskId);if($('log-kind').value)p.set('kind',$('log-kind').value);if($('log-level').value)p.set('level',$('log-level').value);if($('log-query').value.trim())p.set('query',$('log-query').value.trim());if(older&&logBefore)p.set('before',logBefore);
  try{const data=await api(`/api/runs/${logContext.runId}/logs?`+p);const html=data.events.map(e=>`<article class="log-entry ${esc(e.level)}"><small>${esc(date(e.ts))} · ${esc(e.kind)} · ${esc(e.level==='error'?'Hata':e.level==='warning'?'Uyarı':'Bilgi')}</small><p>${esc(logSummary(e))}</p><details><summary>Teknik kayıt ve arama kimliği</summary><pre>${esc(JSON.stringify(e,null,2))}</pre></details></article>`).join('')||'<p class="help">Bu seçimde yapılandırılmış kayıt yok. Eski aramaların metin logu havuz klasöründe korunur.</p>';
    if(older)$('log-list').insertAdjacentHTML('beforeend',html);else $('log-list').innerHTML=html;const t=data.totals;$('log-totals').textContent=`${t.unique_returned??'—'} benzersiz ilan görüldü · ${t.unique_collected??'—'} benzersiz ilan çekildi · ${t.network_cards??t.cards_returned} kart kaynaktan geldi. Kart görünümleri: ${t.cards_returned} · ${t.duplicates} tekrar · ${t.detail_failures} detay hatası · ${t.not_processed||0} işlenmeyen görünüm. Aynı ilan tekrar sayılabilir; işlenmeyen toplamı kayıp ilan sayısı değildir.`;logBefore=data.next_before;$('older-logs').hidden=!logBefore;
  }catch(e){toast(e.message,null,'',true);}
}
async function maintenance(kind,backend='local'){try{await api('/api/'+kind,{method:'POST',body:{force:$('force-recompute').checked,backend,model:$('classify-model').value||null,during_source_wait:$('maintenance-during-wait').checked}});$('maintenance-status').textContent=$('maintenance-during-wait').checked?'Analiz kaynak beklemesinde çalışmak üzere sıraya alındı.':'İşlem başladı…';await pollStatus();}catch(e){$('maintenance-status').textContent=e.message;}}

function storageHtml(st){
  if(!st)return '';const mb=b=>b==null?'—':(b/1048576).toFixed(1)+' MB';const b=st.offsite_backup,m=st.maintenance;
  const backup=!b?'Henüz yedek bilgisi yok':b.ok?`Son yedek: ${esc(date(new Date(b.at*1000).toISOString()))} · ${esc(b.size||'')}`:`Yedek başarısız: ${esc(b.message||'')}`;
  const stale=b&&b.ok&&Date.now()/1000-b.at>2*86400;
  return `<h3>Depolama ve bakım</h3><div class="queue-metrics"><div><strong>${mb(st.db_bytes)}</strong><span>Veritabanı</span></div><div><strong>${st.counts.jobs}</strong><span>İlan</span></div><div><strong>${st.details_pending??0}</strong><span>Detay bekleyen ilan</span></div><div><strong>${st.details_pending??0}</strong><span>Detay bekleyen ilan</span></div><div><strong>${st.counts.search_events}</strong><span>İşlem kaydı (${st.event_retention_days} gün)</span></div><div><strong>${st.counts.job_changes}</strong><span>Değişiklik kaydı (${st.changes_retention_days} gün)</span></div></div>
    <p class="${!b||!b.ok||stale?'notice warn':'notice'}">Sunucu dışı yedek — ${backup}${stale?' · 2 günden eski, kontrol edin.':''}</p><p class="help">Günlük bakım: ${m?`${esc(date(new Date(m.at*1000).toISOString()))} · ${m.events_deleted} işlem ve ${m.changes_deleted} değişiklik kaydı budandı`:'henüz çalışmadı'}.</p>`;
}
async function openService(){
  if(!$('service-dialog').open)showDialog('service-dialog');
  try{const [health,status]=await Promise.all([fetch('/healthz').then(r=>r.json()),api('/api/service/status')]);
    $('service-content').innerHTML=`<div class="queue-metrics"><div><strong>${health.database==='ok'?'Hazır':'Hata'}</strong><span>Veritabanı</span></div><div><strong>${status.supervisor_alive?'Açık':'Kapalı'}</strong><span>Otonom servis</span></div><div><strong>${status.api_key_configured?'Hazır':'Ayarlanmalı'}</strong><span>API anahtarı</span></div></div><p class="notice">${esc(status.source.message)}</p>${storageHtml(status.storage)}${status.last_error?`<p class="field-error">${esc(status.last_error)}</p>`:''}<h3>Tekrarlı toplamalar</h3>${status.schedules.map(s=>`<article class="task-row"><strong>${esc(s.keywords.join(', '))}</strong><p>${esc(tr(s.status))} · Tamamlandıktan ${esc(duration(s.repeat_seconds))} sonra tekrar</p><div class="actions">${button('run-logs','İşlem kayıtları',`data-run="${s.run_id}"`)}${button('disable-schedule','Tekrarı kapat',`data-run="${s.run_id}"`,'danger')}</div></article>`).join('')||'<p class="help">Tekrarlı toplama yok. API üzerinden repeat_seconds ile oluşturabilirsiniz.</p>'}`;
  }catch(e){$('service-content').textContent=e.message;}
}

const TABS=['jobs','dashboard','queue','watches'];
let devMode=false;try{devMode=localStorage.getItem('linko.dev')==='1';}catch{}
function saveDev(){try{localStorage.setItem('linko.dev',devMode?'1':'0');}catch{}}
function applyDev(){document.body.classList.toggle('dev',devMode);}
function devId(j){return `<button class="dev-only dev-id" data-action="copy-id" data-id="${j.id}" title="Kimliği kopyala">#${j.id}</button>`;}
function openDev(){
  $('dev-content').innerHTML=devMode?'<p>Geliştirici modu açık. İlan kartlarında, ilan detayında ve iş alarmlarında kimlikler görünür; karttaki kimliğe tıklayınca kopyalanır.</p><button class="danger" data-action="dev-off">Geliştirici modunu kapat</button>'
    :'<form id="dev-form" novalidate><p class="muted">İlan kimliklerini görmek için şifreyi gir.</p><label>Şifre<input id="dev-password" type="password" autocomplete="off" inputmode="numeric"></label><p id="dev-error" class="field-error" role="alert"></p><button class="primary" type="submit">Geliştirici modunu aç</button></form>';
  showDialog('dev-dialog');
  if(!devMode){$('dev-form').onsubmit=e=>{e.preventDefault();if($('dev-password').value==='321'){devMode=true;saveDev();applyDev();closeDialog('dev-dialog');toast('Geliştirici modu açıldı. İlan kimlikleri görünüyor.');}else{$('dev-error').textContent='Şifre hatalı.';$('dev-password').select();}};$('dev-password').focus();}
}
function showTab(name){
  if(!TABS.includes(name))name='jobs';
  for(const tab of TABS)$('view-'+tab).hidden=tab!==name;
  document.body.dataset.view=name;
  document.querySelectorAll('header nav [data-tab]').forEach(b=>{if(b.dataset.tab===name)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
  try{localStorage.setItem('linko.tab',name);}catch{}
  if(name==='queue')renderQueueView();
  if(name==='dashboard')Dash.load();
  if(name==='watches')loadWatches();
  syncBottomNav(name);
}
const VIEW_GROUP={jobs:'jobs',dashboard:'more',watches:'watches',queue:'queue'};
const ICON=d=>`<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
// Mobil alt menü grupları; her grupta en sık kullanılan/önemli seçenek en üstte.
const BOTTOM_GROUPS={
  scan:{title:'Tarama',items:[
    ['new-search','Yeni arama','Unvan yaz, yapay zekâ benzerleriyle çoğaltsın','<path d="M12 5v14M5 12h14"/>'],
    ['queue','Tarama kuyruğu','Canlı süreci izle, duraklat veya durdur','<path d="M4 6h16M4 12h16M4 18h10"/>']]},
  more:{title:'Diğer',items:[
    ['dashboard','Panel','İlan havuzunun ve toplayıcının özet metrikleri','<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>'],
    ['history','Geçmiş aramalar','Önceki taramaları gör, yeniden başlat','<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/>'],
    ['logs-home','İşlem kayıtları','İstekler, yanıtlar ve hatalar','<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h6"/>'],
    ['trash-home','Çöp kutusu','Silinen ilanları gör ve geri al','<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6"/>'],
    ['service-home','Servis / API','Toplayıcı durumu ve API erişimi','<rect x="3" y="3" width="18" height="7" rx="2"/><rect x="3" y="14" width="18" height="7" rx="2"/><path d="M7 6.5h.01M7 17.5h.01"/>'],
    ['daily-summary','Günlük rapor','Son aramaları ve verimlilik karşılaştırmalarını gör','<path d="M4 4h16v16H4z"/><path d="M8 10h8M8 14h5"/>'],
    ['maintenance-home','Bakım / analiz','Kayıtlı ilanları yeniden işle','<path d="M14.7 6.3a4 4 0 0 0 5 5L21 13l-8 8-3-3 6.5-6.5a4 4 0 0 1-5-5L9 9 3 3"/>'],
    ['dev-menu','Geliştirici modu','İlan kimliklerini göster','<path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/>']]},
};
function runActive(){return !!(currentRun&&activeStatus(currentRun.status));}
function syncBottomNav(view){
  const nav=$('bottom-nav');if(!nav)return;
  const sheet=$('bottom-sheet'),open=sheet&&!sheet.hidden?sheet.dataset.group:'';
  const active=open||VIEW_GROUP[view||TABS.find(t=>!$('view-'+t).hidden)]||'jobs';
  nav.querySelectorAll('[data-bottom-tab]').forEach(b=>{
    if(b.dataset.bottomTab===active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');
    if(b.dataset.bottomGroup)b.setAttribute('aria-expanded',String(b.dataset.bottomGroup===open));
  });
  const dot=nav.querySelector('.bottom-dot');if(dot)dot.hidden=!runActive();
}
function openBottomSheet(name){
  const group=BOTTOM_GROUPS[name],sheet=$('bottom-sheet');
  $('sheet-title').textContent=group.title;
  $('sheet-items').innerHTML=group.items.map(([action,label,hint,icon],i)=>{
    const live=action==='queue'&&runActive()?'<span class="state-pill state-running">● Çalışıyor</span>':'';
    return `<button class="sheet-item${i===0?' sheet-item-main':''}" data-action="${action}"><span class="sheet-icon">${ICON(icon)}</span><span class="sheet-text"><strong>${esc(label)}</strong><small>${esc(hint)}</small></span>${live}</button>`;
  }).join('');
  sheet.dataset.group=name;sheet.hidden=false;syncBottomNav();
  sheet.querySelector('.sheet-item')?.focus({preventScroll:true});
}
function closeBottomSheet(){
  const sheet=$('bottom-sheet');if(!sheet||sheet.hidden)return;
  const group=sheet.dataset.group,hadFocus=sheet.contains(document.activeElement);
  sheet.hidden=true;sheet.dataset.group='';syncBottomNav();
  // Gizlenen öğede odak kalmasın; açılan pencere kapanınca odak menü sekmesine dönsün.
  if(hadFocus)$('bottom-nav').querySelector(`[data-bottom-group="${group}"]`)?.focus({preventScroll:true});
}
function initBottomNav(){
  $('bottom-nav').addEventListener('click',e=>{
    const tab=e.target.closest('[data-bottom-tab]');if(!tab)return;
    const group=tab.dataset.bottomGroup,wasOpen=$('bottom-sheet').dataset.group;
    closeBottomSheet();
    if(group&&group!==wasOpen)openBottomSheet(group);
  });
  // Öğeye tıklanınca belge düzeyindeki data-action işleyicisi işlemi yapar; burada yalnızca panel kapanır.
  $('bottom-sheet').addEventListener('click',e=>{if(e.target.closest('[data-sheet-close],[data-action]'))closeBottomSheet();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape')closeBottomSheet();});
  syncBottomNav();
}
function renderQueueView(){const has=!!currentRun,other=queueLayerStatus?.layers?.some(l=>l.ready||l.waiting||l.running);$('queue-empty').hidden=has||waitingRuns.length>0||!!other;$('live-run').hidden=!has;syncBottomNav();}

let watchEditing=null, watchData=[];
const intervalNames={3600:'Saatte bir',10800:'3 saatte bir',21600:'6 saatte bir',43200:'12 saatte bir',86400:'Günde bir',259200:'3 günde bir',604800:'Haftada bir'};
const postedNames={0:'tüm ilanlar',86400:'son 24 saatte yayınlananlar',604800:'son 7 günde yayınlananlar',2592000:'son 30 günde yayınlananlar'};
const splitLines=v=>v.split('\n').map(x=>x.trim()).filter(Boolean);
const splitKeywords=v=>v.split(/[\n,]/).map(x=>x.trim()).filter(Boolean);
function relTime(seconds){const a=Math.abs(Math.round(seconds));const t=a<60?'1 dakikadan az':a<3600?`${Math.round(a/60)} dakika`:a<86400?`${Math.round(a/3600)} saat`:`${Math.round(a/86400)} gün`;return seconds>=0?`${t} sonra`:`${t} önce`;}
function watchBody(){return {name:$('watch-name').value.trim(),keywords:splitKeywords($('watch-keywords').value),locations:splitLines($('watch-locations').value),interval_seconds:Number($('watch-interval').value),limit:Number($('watch-limit').value),posted_within:Number($('watch-posted').value)};}
function watchCombos(){const b=watchBody(),n=b.keywords.length*b.locations.length;$('watch-combos').textContent=n?`${b.keywords.length} unvan × ${b.locations.length} konum = ${n} kombinasyon${n>40?' — en fazla 40 olabilir, listeyi bölün.':'. Her tur sırayla, ortak istek aralığıyla taranır.'}`:'';}
function resetWatchForm(){watchEditing=null;$('watch-form').reset();$('watch-locations').value='Istanbul, Turkey';$('watch-form-title').textContent='Yeni iş alarmı';$('watch-save').textContent='Alarmı kaydet';$('watch-cancel').hidden=true;$('watch-error').textContent='';watchCombos();}
async function saveWatch(e){e.preventDefault();$('watch-error').textContent='';const body=watchBody();$('watch-save').disabled=true;
  try{if(watchEditing)await api('/api/watches/'+watchEditing,{method:'PUT',body});else await api('/api/watches',{method:'POST',body});toast(watchEditing?'İş alarmı güncellendi.':'İş alarmı kaydedildi. İlk tur, kuyruk ve kaynak uygun olduğunda başlar.');resetWatchForm();await loadWatches();}
  catch(err){$('watch-error').textContent=err.message;}finally{$('watch-save').disabled=false;}}
async function loadWatches(){
  try{const [data,routine]=await Promise.all([api('/api/watches'),api('/api/routine-cities')]);watchData=data.watches;renderRoutineCities(routine);
    $('watch-list').innerHTML=watchData.length?watchData.map(w=>watchCard(w,data.now)).join(''):'<div class="empty"><h2>Henüz iş alarmın yok</h2><p>Formdan unvan ve konumları ekleyerek ilk alarmını kur.</p></div>';}
  catch(e){$('watch-list').innerHTML=`<p class="field-error">${esc(e.message)}</p>`;$('routine-city-count').textContent='Yüklenemedi';$('routine-city-list').innerHTML=`<p class="field-error">${esc(e.message)}</p>`;}
}
function renderRoutineCities(data){
  const cities=data.cities||[],now=Number(data.now||Date.now()/1000),toggle=$('routine-city-toggle');
  const defaults=[...$('routine-profession-list').querySelectorAll('.tag')].map(node=>node.textContent.trim()).filter(Boolean);
  const professions=Array.isArray(data.professions)&&data.professions.length?data.professions:defaults;
  toggle.dataset.action=data.paused?'routine-city-resume':'routine-city-pause';toggle.textContent=data.paused?'Rutin taramaları sürdür':'Rutin taramaları duraklat';
  const countryCount=data.country_count||new Set(cities.map(c=>c.country).filter(Boolean)).size;
  const countryBadge=countryCount?` · ${countryCount} ülke`:'';
  $('routine-city-count').textContent=`${cities.length} şehir${countryBadge} · ${professions.length} meslek · günlük`;
  $('routine-profession-count').textContent=`${professions.length} meslek`;
  $('routine-profession-list').innerHTML=professions.map(name=>`<span class="tag">${esc(name)}</span>`).join('');
  $('routine-city-list').innerHTML=`<table class="routine-city-table"><caption class="sr-only">Rutin arama şehirleri, ülkeleri, öncelikleri, ilan hedefleri ve sonraki tarama durumu</caption><thead><tr><th scope="col">Sıra</th><th scope="col">Şehir</th><th scope="col">Ülke</th><th scope="col">Öncelik</th><th scope="col">Meslek başına ilan hedefi</th><th scope="col">Tarama durumu</th></tr></thead><tbody>${cities.map(city=>{const due=data.paused?'Duraklatıldı':Number(city.next_due_at)<=now?'Sırada':relTime(Number(city.next_due_at)-now);const last=city.last_run;const state=last?`${tr(last.status)} · ${Number(last.new||0)} yeni · ${due}`:due;return `<tr${city.critical?' class="routine-city-critical"':''}><td>${Number(city.order)}</td><th scope="row">${esc(city.city)}</th><td>${esc(city.country||'')}</td><td>${city.critical?badge('Kritik · ilk sırada','new'):'Rutin'}</td><td>${Number(city.quota)} ilan</td><td>${esc(state)}</td></tr>`;}).join('')}</tbody></table>`;
}
function watchCard(w,now){
  const last=w.last_run,running=!!last&&!['finished','cancelled','stopped'].includes(last.status);
  const next=!w.enabled?'Duraklatıldı':running?'Tur sürüyor':w.next_due_at<=now?'Sırada — kuyruk ve kaynak uygun olunca başlar':relTime(w.next_due_at-now);
  return `<article class="watch-card${w.enabled?'':' is-disabled'}"><div class="watch-head"><div><h3>${esc(w.name)}</h3><p class="help">${esc(intervalNames[w.interval_seconds]||'')} · ${esc(postedNames[w.posted_within]??'')} · kombinasyon başına ${w.limit} ilan</p></div>${badge(running?'Taranıyor':w.enabled?'Etkin':'Duraklatıldı',w.enabled?'':'warn')}</div>
    <div class="tags">${w.keywords.map(k=>`<span class="tag">${esc(k)}</span>`).join('')}</div><p class="job-meta">Konum: ${w.locations.map(esc).join(' · ')} — ${w.combinations} kombinasyon</p>
    <dl class="watch-stats"><div><dt>Son tur</dt><dd>${last?`${esc(tr(last.status))} · ${esc(date(last.created_at))}`:'Henüz çalışmadı'}</dd></div><div><dt>Son turda</dt><dd>${last?`${last.new} yeni, ${last.updated} güncellenen`:'—'}</dd></div><div><dt>Sonraki tur</dt><dd>${esc(next)}</dd></div></dl>
    ${w.blocked?`<p class="notice error">${esc(w.blocked_reason||'Önceki tur duraklatılmış; devam ettirin ya da durdurun.')} Alarm o tur bitene kadar yeni tur açmaz.</p>`:''}
    <p class="dev-only id-text">Alarm kimliği: ${esc(w.id)}${last?' · Son çalışma: '+esc(last.id):''}</p>
    <div class="card-actions">${button('watch-run','Şimdi tara',`data-id="${w.id}"${running?' disabled':''}`)}${last?button('run-results','Son turun ilanları',`data-run="${last.id}"`):''}${button('watch-edit','Düzenle',`data-id="${w.id}"`)}${button('watch-toggle',w.enabled?'Duraklat':'Etkinleştir',`data-id="${w.id}"`)}${button('watch-delete','Sil',`data-id="${w.id}"`,'danger')}</div></article>`;
}
async function watchAction(action,id){
  const w=watchData.find(x=>x.id===id);if(!w)return;
  if(action==='edit'){watchEditing=id;$('watch-name').value=w.name;$('watch-keywords').value=w.keywords.join('\n');$('watch-locations').value=w.locations.join('\n');$('watch-interval').value=String(w.interval_seconds);$('watch-limit').value=String(w.limit);$('watch-posted').value=String(w.posted_within);$('watch-form-title').textContent='Alarmı düzenle';$('watch-save').textContent='Değişiklikleri kaydet';$('watch-cancel').hidden=false;watchCombos();$('watch-form').scrollIntoView({block:'start'});$('watch-name').focus();return;}
  if(action==='run'){await api(`/api/watches/${id}/run-now`,{method:'POST'});toast('Tur sıraya alındı. Kuyruk ve kaynak uygun olunca başlar.');}
  if(action==='toggle'){const r=await api('/api/watches/'+id,{method:'PUT',body:{enabled:!w.enabled}});toast(w.enabled?'İş alarmı duraklatıldı. Süren tur varsa tamamlanır.':r.warning?`İş alarmı etkinleştirildi, ancak: ${r.warning}`:'İş alarmı etkinleştirildi.');}
  if(action==='delete'){if(!await confirmAction(`“${w.name}” iş alarmı silinecek. Toplanan ilanlar ve geçmiş turlar korunur. Devam edilsin mi?`))return;await api('/api/watches/'+id,{method:'DELETE'});if(watchEditing===id)resetWatchForm();toast('İş alarmı silindi.');}
  await loadWatches();
}

async function dispatch(action,el){
  const id=el.dataset.id,run=el.dataset.run,task=el.dataset.task,index=Number(el.dataset.index);
  if(action==='jobs-home'||action==='trash-home'){document.querySelectorAll('dialog[open]').forEach(d=>d.close());showTab('jobs');filters=action==='trash-home'?{visibility:'trash'}:{};syncControls();renderChips();persist(true);await loadAll();$('main').scrollIntoView({block:'start'});return;}
  if(action==='logs-home'){const rows=await api('/api/runs');if(!rows.runs.length){toast('Henüz işlem kaydı yok.');return;}return openLogs(currentRun?.id||rows.runs[0].id);}
  if(action==='service-home')return openService();
  if(action==='disable-schedule'){await api(`/api/service/schedules/${run}/stop`,{method:'POST'});toast('Yeni tekrarlar kapatıldı.');return openService();}
  if(action==='maintenance-home'){await openDrawer();document.querySelector('.maintenance').open=true;document.querySelector('.maintenance').scrollIntoView({block:'start'});return;}
  if(action==='new-search')return openDrawer();if(action==='dashboard')return showTab('dashboard');if(action==='queue')return showTab('queue');if(action==='watches')return showTab('watches');
  if(action==='routine-city-pause'||action==='routine-city-resume'){await api('/api/routine-cities/'+(action==='routine-city-pause'?'pause':'resume'),{method:'POST'});toast(action==='routine-city-pause'?'Rutin şehir taramaları duraklatıldı; çalışan tur tamamlanacak.':'Rutin şehir taramaları yeniden etkinleştirildi.');await loadWatches();await pollStatus();return;}
  if(action==='dev-menu')return openDev();if(action==='dev-off'){devMode=false;saveDev();applyDev();closeDialog('dev-dialog');toast('Geliştirici modu kapatıldı.');return;}
  if(action.startsWith('watch-'))return watchAction(action.slice(6),id);if(action==='history')return openHistory();if(action==='daily-summary')return openDailySummary();if(action==='reset')return resetFilters();if(action==='job')return openJob(id);if(action==='similar')return similar(id);if(action==='toggle-translate')return toggleJobTranslation(id);
  if(action==='completion-pause'||action==='completion-resume'){await api('/api/completion-queue/'+action.slice(11),{method:'POST'});await pollStatus();return;}
  if(action==='fetch-detail'||action==='repair-job'){if(action==='repair-job')return repairJob(id);await api('/api/jobs/'+id+'/fetch-detail',{method:'POST'});toast('Açıklama manuel öncelikle kuyruğa eklendi.');await pollStatus();return;}
  if(action==='copy-id'){await navigator.clipboard.writeText(id);toast('Kimlik kopyalandı: '+id);return;}
  if(action==='run-report'||action==='task-report')return openReport(run,task||null);
  if(action==='run-logs')return openLogs(run);
  if(['delete-job','restore-job','purge-job'].includes(action))return jobAction(id,action.split('-')[0]);
  if(action.startsWith('draft-')){if(action==='draft-package-remove')draft.splice(index,Number(el.dataset.count));else if(action==='draft-remove')draft.splice(index,1);else{const other=index+(action==='draft-up'?-1:1);if(other>=0&&other<draft.length)[draft[index],draft[other]]=[draft[other],draft[index]];}renderDraft();persist();scheduleDraftSave();return;}
  if(action.startsWith('control-'))return controlTask(run,task,action.slice(8));
  if(action.startsWith('waiting-'))return waitingAction(run,action.slice(8));
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
  const comp=event.target.closest('[data-filter-company]');if(comp){const c=(comp.dataset.filterCompany||'').trim();if(c&&c!=='Şirket belirtilmemiş'){event.stopPropagation();setFilter('company',[c]);$('results')?.scrollIntoView({behavior:'smooth',block:'start'});return;}}
  const dash=event.target.closest('[data-dash-filter],[data-dash-window]');if(dash){openJobsFromDashboard(dash);return;}
  const quick=event.target.closest('[data-quick]');if(quick){toggleQuick(quick.dataset.quick);return;}
  const more=event.target.closest('[data-facet-more]');if(more){const key=more.dataset.facetMore;if(expandedFacets.has(key))expandedFacets.delete(key);else expandedFacets.add(key);facetCollapse($('facet-'+key));return;}
  // Kartın boş bir yerine tıklamak ilanı açar; metin seçimi ve iç düğmeler/bağlantılar etkilenmez.
  const card=event.target.closest('.job-card');if(card&&!event.target.closest('button,a,input,label')&&!String(getSelection()).trim()){openJob(card.dataset.id).catch(e=>toast(e.message,null,'',true));return;}
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
  if(el.id==='profession-filter-search')renderProfessionFacets();if(el.dataset.filter&&el.tagName==='INPUT'&&el.type!=='checkbox')scheduleFilters(el.dataset.filter,el.value);
  if(el.classList.contains('facet-search')){const query=el.value.toLocaleLowerCase('tr');el.closest('.facet-block').querySelectorAll('.facet-options label').forEach(label=>{label.hidden=!label.textContent.toLocaleLowerCase('tr').includes(query);});facetCollapse(el.closest('.facet-block'));}
});
// Panel kartları ilgili filtreyle İlanlar sekmesini açar: bir değer, ya da "created_from:7" gibi son N gün penceresi.
function openJobsFromDashboard(el){
  const next={};
  if(el.dataset.dashWindow!=null){const [key,days]=el.dataset.dashWindow.split(':');const d=new Date();d.setDate(d.getDate()-Number(days));next[key]=d.toISOString();}
  else if(el.dataset.dashFilter){const key=el.dataset.dashFilter,value=el.dataset.dashValue;next[key]=multiKeys.has(key)?[value]:value;}
  document.querySelectorAll('dialog[open]').forEach(d=>d.close());
  filters=next;showTab('jobs');syncControls();renderChips();persist(true);loadAll();$('main').scrollIntoView({block:'start'});
}
function setNavMore(open){const menu=$('nav-more-menu');menu.hidden=!open;menu.classList.toggle('hidden',!open);$('nav-more-toggle').setAttribute('aria-expanded',String(open));}
function wire(id,event,fn){$(id).addEventListener(event,async e=>{try{await fn(e);}catch(error){toast(error.message,null,'',true);}});}
function initTheme(){
  let theme='light';
  try{
    const saved=localStorage.getItem('linko.theme.v1');
    theme=saved==='dark'||(!saved&&window.matchMedia('(prefers-color-scheme: dark)').matches)?'dark':'light';
  }catch{}
  const apply=t=>{
    const isDark=t==='dark';
    document.documentElement.classList.toggle('dark', isDark);
    document.body.dataset.theme=t;
    const label=$('themeLabel');
    if(label)label.textContent=isDark?'Açık Tema':'Koyu Tema';
  };
  apply(theme);
  const toggleBtn=$('themeToggleBtn')||$('theme-toggle');
  if(toggleBtn){
    toggleBtn.addEventListener('click',()=>{
      const next=document.documentElement.classList.contains('dark')?'light':'dark';
      try{localStorage.setItem('linko.theme.v1',next);}catch{}
      apply(next);
    });
  }
}
function setMobileFilters(open){
  const sidebar=$('filter-panel');
  sidebar.classList.toggle('hidden',!open);
  for(const cls of ['sticky','w-72','top-[80px]','max-h-[calc(100vh-100px)]'])sidebar.classList.toggle(cls,!open);
  for(const cls of ['block','fixed','inset-0','w-full','z-50','bg-black/50','backdrop-blur-xs','p-4'])sidebar.classList.toggle(cls,open);
  $('mobileFilterBtn').setAttribute('aria-expanded',String(open));
}
function initHeroSearchAndPopovers(){
  const kwInput = $('search');
  const clearKw = $('clearKeywordBtn');
  if (kwInput) {
    if (clearKw) {
      kwInput.addEventListener('input', () => {
        clearKw.classList.toggle('hidden', !kwInput.value.trim());
      });
      clearKw.addEventListener('click', () => {
        kwInput.value = '';
        scheduleSearch.cancel();
        clearKw.classList.add('hidden');
        setFilter('search', '');
      });
    }
    kwInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        submitSearch();
      }
    });
  }

  const heroBtn = $('heroSearchBtn');
  if (heroBtn) {
    heroBtn.addEventListener('click', () => {
      submitSearch();
    });
  }

  // Hero Şirket Filtresi Olay Dinleyicileri
  const hcTrigger = $('heroCompanyTriggerBtn');
  const hcPopover = $('heroCompanyPopover');
  const hcChevron = $('heroCompanyChevron');
  const hcOptionsList = $('heroCompanyOptionsList');
  const hcQuickSearch = $('heroCompanyQuickSearch');
  const hcClearBtn = $('clearCompanyBtn');
  const hcResetBtn = $('heroCompanyResetBtn');
  const hcApplyBtn = $('heroCompanyApplyBtn');

  if (hcTrigger && hcPopover) {
    hcTrigger.addEventListener('click', e => {
      e.stopPropagation();
      const open = hcPopover.classList.toggle('hidden');
      hcTrigger.setAttribute('aria-expanded', String(open));
      if (hcChevron) hcChevron.classList.toggle('rotate-180', open);
      if (open) {
        // Konum popover açıksa kapat
        $('heroLocationPopover')?.classList.add('hidden');
        $('heroLocationTriggerBtn')?.setAttribute('aria-expanded', 'false');
        $('heroLocationChevron')?.classList.remove('rotate-180');
        renderHeroCompanyOptions();
        setTimeout(() => hcQuickSearch?.focus(), 50);
      }
    });

    document.addEventListener('click', e => {
      if (!hcPopover.contains(e.target) && !hcTrigger.contains(e.target)) {
        hcPopover.classList.add('hidden');
        hcTrigger.setAttribute('aria-expanded', 'false');
        if (hcChevron) hcChevron.classList.remove('rotate-180');
      }
    });

    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && !hcPopover.classList.contains('hidden')) {
        hcPopover.classList.add('hidden');
        hcTrigger.setAttribute('aria-expanded', 'false');
        if (hcChevron) hcChevron.classList.remove('rotate-180');
      }
    });
  }

  if (hcApplyBtn) {
    hcApplyBtn.addEventListener('click', () => {
      hcPopover?.classList.add('hidden');
      hcTrigger?.setAttribute('aria-expanded', 'false');
      if (hcChevron) hcChevron.classList.remove('rotate-180');
    });
  }

  const clearCompanySelection = (e) => {
    if (e) e.stopPropagation();
    delete filters.company;
    if (hcQuickSearch) hcQuickSearch.value = '';
    syncControls();
    persist(true);
    renderChips();
    loadAll();
    renderHeroCompanyOptions();
  };

  if (hcClearBtn) hcClearBtn.addEventListener('click', clearCompanySelection);
  if (hcResetBtn) hcResetBtn.addEventListener('click', clearCompanySelection);

  if (hcQuickSearch) {
    hcQuickSearch.addEventListener('input', renderHeroCompanyOptions);
  }

  if (hcOptionsList) {
    hcOptionsList.addEventListener('change', e => {
      const checkbox = e.target.closest('[data-hero-company-checkbox]');
      if (checkbox) {
        const val = checkbox.value;
        let current = getSelectedCompanies();
        if (checkbox.checked) {
          if (!current.includes(val)) current.push(val);
        } else {
          current = current.filter(c => c !== val);
        }
        if (current.length) {
          filters.company = current;
        } else {
          delete filters.company;
        }
        syncControls();
        persist(true);
        renderChips();
        loadAll();
      }
    });

    hcOptionsList.addEventListener('click', e => {
      const clearBtn = e.target.closest('[data-hero-company-clear]');
      if (clearBtn) {
        clearCompanySelection(e);
      }
    });
  }

  const hlTrigger = $('heroLocationTriggerBtn') || $('countryCityTriggerBtn');
  const hlPopover = $('heroLocationPopover') || $('countryCityPopover');
  const hlChevron = $('heroLocationChevron') || $('countryCityChevron');
  const hlOptionsList = $('heroLocationOptionsList') || $('countryCityOptionsList');
  const hlQuickSearch = $('heroLocationQuickSearch') || $('countryCityQuickSearch');
  const hlClearBtn = $('clearLocationBtn');
  const hlResetBtn = $('heroLocationResetBtn') || $('clearCountryCityBtn');
  const hlApplyBtn = $('heroLocationApplyBtn');

  if (hlTrigger && hlPopover) {
    hlTrigger.addEventListener('click', e => {
      e.stopPropagation();
      const open = hlPopover.classList.toggle('hidden');
      hlTrigger.setAttribute('aria-expanded', String(open));
      if (hlChevron) hlChevron.classList.toggle('rotate-180', open);
      if (open) {
        hcPopover?.classList.add('hidden');
        hcTrigger?.setAttribute('aria-expanded', 'false');
        if (hcChevron) hcChevron.classList.remove('rotate-180');
        renderHeroLocationOptions();
        setTimeout(() => hlQuickSearch?.focus(), 50);
      }
    });

    document.addEventListener('click', e => {
      if (!hlPopover.contains(e.target) && !hlTrigger.contains(e.target)) {
        hlPopover.classList.add('hidden');
        hlTrigger.setAttribute('aria-expanded', 'false');
        if (hlChevron) hlChevron.classList.remove('rotate-180');
      }
    });

    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && !hlPopover.classList.contains('hidden')) {
        hlPopover.classList.add('hidden');
        hlTrigger.setAttribute('aria-expanded', 'false');
        if (hlChevron) hlChevron.classList.remove('rotate-180');
      }
    });
  }

  if (hlApplyBtn) {
    hlApplyBtn.addEventListener('click', () => {
      hlPopover?.classList.add('hidden');
      hlTrigger?.setAttribute('aria-expanded', 'false');
      if (hlChevron) hlChevron.classList.remove('rotate-180');
    });
  }

  if (hlClearBtn) {
    hlClearBtn.addEventListener('click', e => {
      e.stopPropagation();
      delete filters.country;
      delete filters.city;
      delete filters.location_text;
      cityOptionsCountry = '';
      if (hlQuickSearch) hlQuickSearch.value = '';
      syncControls();
      persist(true);
      renderChips();
      loadAll();
      renderHeroLocationOptions();
    });
  }

  if (hlResetBtn) {
    hlResetBtn.addEventListener('click', e => {
      e.stopPropagation();
      delete filters.country;
      delete filters.city;
      delete filters.location_text;
      cityOptionsCountry = '';
      if (hlQuickSearch) hlQuickSearch.value = '';
      syncControls();
      persist(true);
      renderChips();
      loadAll();
      renderHeroLocationOptions();
    });
  }

  if (hlQuickSearch) {
    hlQuickSearch.addEventListener('input', renderHeroLocationOptions);
  }

  if (hlOptionsList) {
    hlOptionsList.addEventListener('change', e => {
      const checkbox = e.target.closest('[data-hero-city-checkbox]');
      if (checkbox) {
        const val = checkbox.value;
        let current = getSelectedCities();
        if (checkbox.checked) {
          if (!current.includes(val)) current.push(val);
        } else {
          current = current.filter(c => c !== val);
        }
        if (current.length) {
          filters.city = current;
        } else {
          delete filters.city;
        }
        syncControls();
        persist(true);
        renderChips();
        loadAll();
        
        const label = checkbox.closest('label');
        const span = label?.querySelector('span');
        if (span) {
          span.classList.toggle('font-bold', checkbox.checked);
          span.classList.toggle('text-[#0A66C2]', checkbox.checked);
          span.classList.toggle('dark:text-[#70B5F9]', checkbox.checked);
        }
        const hlFooter = $('heroLocationFooterSummary');
        if (hlFooter) {
          hlFooter.textContent = current.length ? `${filters.country}: ${current.length} şehir seçili` : `${filters.country} genelindeki tüm şehirler`;
        }
      }
    });

    hlOptionsList.addEventListener('click', e => {
      const countryBtn = e.target.closest('[data-hero-country-option], [data-country-option]');
      if (countryBtn) {
        const countryVal = countryBtn.dataset.heroCountryOption ?? countryBtn.dataset.countryOption;
        if (countryVal) {
          filters.country = countryVal;
          delete filters.city;
          cityOptionsCountry = countryVal;
        } else {
          delete filters.country;
          delete filters.city;
          cityOptionsCountry = '';
        }
        if (hlQuickSearch) hlQuickSearch.value = '';
        syncControls();
        persist(true);
        renderChips();
        loadAll();
        renderHeroLocationOptions();
        return;
      }

      if (e.target.closest('[data-hero-change-country], [data-country-change]')) {
        delete filters.country;
        delete filters.city;
        cityOptionsCountry = '';
        if (hlQuickSearch) hlQuickSearch.value = '';
        syncControls();
        persist(true);
        renderChips();
        loadAll();
        renderHeroLocationOptions();
        return;
      }

      if (e.target.closest('[data-hero-city-select-all]')) {
        delete filters.city;
        syncControls();
        persist(true);
        renderChips();
        loadAll();
        renderHeroLocationOptions();
        return;
      }

      const cityBtn = e.target.closest('[data-city-option]');
      if (cityBtn && !cityBtn.querySelector('input')) {
        const val = cityBtn.dataset.cityOption;
        if (val) filters.city = [val]; else delete filters.city;
        syncControls();
        persist(true);
        renderChips();
        loadAll();
        renderHeroLocationOptions();
      }
    });
  }

  document.querySelectorAll('.cc-quick-pill').forEach(pill => {
    pill.addEventListener('click', () => {
      const val = pill.getAttribute('data-country-city-pill');
      if (val === 'Türkiye · İstanbul') {
        const cities = getSelectedCities();
        const hasIstanbul = filters.country === 'Türkiye' && cities.includes('İstanbul');
        if (hasIstanbul) {
          const remaining = cities.filter(c => c !== 'İstanbul');
          if (remaining.length) filters.city = remaining;
          else { delete filters.country; delete filters.city; }
        } else {
          filters.country = 'Türkiye';
          filters.city = [...new Set([...cities, 'İstanbul'])];
        }
        cityOptionsCountry = filters.country || '';
        syncControls();
        persist(true);
        renderChips();
        loadAll();
        renderHeroLocationOptions();
      }
    });
  });

  const mobBtn = $('mobileFilterBtn');
  const sidebar = $('filter-panel');
  if (mobBtn && sidebar) {
    mobBtn.setAttribute('aria-controls','filter-panel');
    mobBtn.setAttribute('aria-expanded','false');
    mobBtn.addEventListener('click',()=>setMobileFilters(!sidebar.classList.contains('fixed')));
    $('close-mobile-filters').addEventListener('click',()=>setMobileFilters(false));
    sidebar.addEventListener('click',e=>{if(e.target===sidebar&&sidebar.classList.contains('fixed'))setMobileFilters(false);});
    window.matchMedia('(min-width: 1024px)').addEventListener('change',e=>{if(e.matches)setMobileFilters(false);});
  }

  const drawerBackdrop = $('jobDrawerBackdrop');
  if (drawerBackdrop) {
    drawerBackdrop.addEventListener('click', e => {
      if (e.target === drawerBackdrop) {
        closeDialog('job-dialog');
      }
    });
  }
  document.addEventListener('keydown',e=>{
    if(e.key!=='Escape'||document.querySelector('dialog[open]'))return;
    if(!drawerBackdrop.classList.contains('hidden'))closeDialog('job-dialog');
    if(sidebar.classList.contains('fixed'))setMobileFilters(false);
  });
}
function initialize(){
  initTheme();
  initHeroSearchAndPopovers();
  // Üst menüde az kullanılan seçenekler ⋯ altında; seçim yapınca, dışarı tıklayınca veya Esc ile kapanır.
  setNavMore(false);
  wire('nav-more-toggle','click',()=>setNavMore($('nav-more-menu').hidden));
  document.addEventListener('click',e=>{if(!$('nav-more-menu').hidden&&(!e.target.closest('.nav-more')||e.target.closest('#nav-more-menu [data-action]')))setNavMore(false);});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('nav-more-menu').hidden){setNavMore(false);$('nav-more-toggle').focus();}});
  const queueLabel=document.createElement('p');queueLabel.id='queue-identity';queueLabel.className='id-text';$('draft-tasks').before(queueLabel);
  const reportDialog=document.createElement('dialog');reportDialog.id='report-dialog';reportDialog.className='wide-dialog';reportDialog.setAttribute('aria-labelledby','report-title');reportDialog.innerHTML='<div class="dialog-heading"><h2 id="report-title">Arama raporu ve verim</h2><button data-close="report-dialog" aria-label="Raporu kapat">✕</button></div><button id="refresh-report">Raporu yenile</button><div id="report-content"></div>';document.body.append(reportDialog);
  const logQuery=document.createElement('input');logQuery.id='log-query';logQuery.type='search';logQuery.placeholder='İstek / ilan / deneme kimliği veya mesaj ara';logQuery.setAttribute('aria-label','İşlem kayıtlarında ara');$('log-totals').before(logQuery);
  for(const [value,label] of [['cache_hit','Önbellekten alınan detaylar'],['cache_miss','Detayı yenilenen ilanlar'],['source_paused','Kaynak nedeniyle duraklamalar'],['shared_rate_wait','Ortak istek sırası'],['processing_stage','İşleme aşamaları'],['processing_result','İşleme sonuçları'],['job_skipped','Elenen ilanlar'],['checkpoint_saved','Devam noktaları'],['user_action','Kullanıcı işlemleri'],['run_started','Çalıştırma / deneme kimlikleri'],['task_queued','Kuyruğa alınan görevler']])$('log-kind').add(new Option(label,value));
  $('facet-filters').innerHTML=groupKeys.map(key=>`<details class="filter-group facet-block" id="facet-${key}"><summary>${names[key]}</summary><input class="facet-search" type="search" placeholder="Seçeneklerde ara…" aria-label="${names[key]} seçeneklerinde ara"><div class="facet-options"></div><button type="button" class="text-button facet-more" data-facet-more="${key}" hidden></button></details>`).join('');
  $('date-filters').innerHTML=[['posted','Yayın tarihi'],['created','İlk eklenme'],['scraped','Son tarama']].map(([key,label])=>`<fieldset><legend>${label}</legend><div class="field-pair"><label>Başlangıç<input type="date" data-filter="${key}_from"></label><label>Bitiş<input type="date" data-filter="${key}_to"></label></div>${key==='posted'?'<label class="check"><input type="checkbox" data-filter="posted_missing">Yayın tarihi belirtilmemiş</label>':''}</fieldset>`).join('');
  $('content-filters').innerHTML=[['has_description','Açıklama'],['has_summary','Yapay zekâ özeti'],['has_embedding','Eşleştirme verisi']].map(([key,label])=>`<label>${label}<select data-filter="${key}"><option value="">Tümü</option><option value="1">Var</option><option value="0">Yok</option></select></label>`).join('');
  organizeFilterGroups();
  const legacyButton=document.createElement('button');legacyButton.id='legacy-log';legacyButton.textContent='Kaynak metin kaydı';legacyButton.hidden=true;$('download-logs').after(legacyButton);
  $('acknowledge-source').onclick=acknowledgeSource;
  for(const [id,value] of Object.entries(form)){if($(id)){if($(id).type==='checkbox')$(id).checked=!!value;else $(id).value=value;}}
  $('limit-input').disabled=$('unlimited').checked;$('task-error').after($('start-scrape'));readLocation();syncControls();renderChips();renderDraft();
  wire('search','input',scheduleSearch);wire('location-country','change',e=>setFilter('country',e.target.value));wire('location-city','change',e=>setFilter('city',e.target.value));wire('sort','change',e=>setFilter('sort',e.target.value));wire('per-page','change',e=>setFilter('per_page',e.target.value));
  wire('exclude-skills','input',debounce(e=>setFilter('exclude_skills',e.target.value.split(',').map(v=>v.trim()).filter(Boolean))));wire('exclude-skills','blur',()=>{$('exclude-skills').value=(filters.exclude_skills||[]).join(', ');});
  wire('run-filter','change',e=>{delete filters.task_id;setFilter('run_id',e.target.value?[e.target.value]:[]);});
  wire('date-preset','change',e=>setPostedPreset(Number(e.target.value)));
  wire('new-only','click',()=>setFilter('created_from',filters.created_from===seen.mark?'':seen.mark));wire('new-mark','click',markAllSeen);
  wire('reset-filters','click',resetFilters);wire('retry-jobs','click',loadAll);
  wire('view-cards','click',()=>{view='cards';applyView();renderJobs();persist(true);});wire('view-list','click',()=>{view='list';applyView();renderJobs();persist(true);});
  for(const [id,delta] of [['prev',-1],['next',1]])wire(id,'click',()=>{filters.page=String(Math.max(1,Math.min(pages,Number(filters.page||1)+delta)));persist(true);loadJobs();$('count').scrollIntoView({block:'center'});});
  wire('previous-job','click',()=>nav.previous&&openJob(nav.previous));wire('next-job','click',()=>nav.next&&openJob(nav.next));
  wire('persistent-prev-job','click',()=>nav.previous&&openJob(nav.previous, false));wire('persistent-next-job','click',()=>nav.next&&openJob(nav.next, false));
  $('job-dialog').addEventListener('close',()=>{if(window.innerWidth<1024){detailController?.abort();}});
  wire('add-tasks','click',addTasks);wire('start-scrape','click',startScrape);wire('suggest-titles','click',suggestTitles);wire('add-suggested','click',addSuggested);wire('cancel-suggested','click',closeSuggestions);$('suggest-list').addEventListener('change',updateSuggestCount);for(const [id,on] of [['suggest-all',true],['suggest-none',false]])wire(id,'click',()=>{document.querySelectorAll('#suggest-list [data-suggest]').forEach(el=>el.checked=on);updateSuggestCount();});['loc-input','limit-input'].forEach(id=>wire(id,'input',updateSuggestCount));wire('unlimited','change',()=>{$('limit-input').disabled=$('unlimited').checked;persist();updateSuggestCount();});
  ['kw-input','loc-input','limit-input','collection-opportunity-type','classify-backend','use-embeddings','scrape-mode','refresh-details'].forEach(id=>wire(id,'input',()=>{persist();if(draft.length&&['collection-opportunity-type','classify-backend','use-embeddings','scrape-mode','refresh-details'].includes(id))scheduleDraftSave();}));
  wire('pause-run','click',()=>currentRun&&runAction(currentRun.id,'pause'));wire('resume-run','click',()=>currentRun&&runAction(currentRun.id,'resume'));wire('stop-run','click',()=>currentRun&&runAction(currentRun.id,'stop'));wire('cancel-run','click',()=>currentRun&&runAction(currentRun.id,'cancel'));wire('cancel-all','click',cancelAll);wire('live-logs','click',()=>currentRun&&openLogs(currentRun.id));
  wire('history-status','change',renderHistory);wire('history-search','input',renderHistory);wire('history-trash','change',()=>{selectedHistory.clear();loadHistory();});
  wire('history-select-all','click',()=>{const query=$('history-search').value.toLocaleLowerCase('tr');const tasks=historyRuns.filter(r=>JSON.stringify(r).toLocaleLowerCase('tr').includes(query)).flatMap(r=>r.tasks);const all=tasks.every(t=>selectedHistory.has(t.id));for(const t of tasks)if(all)selectedHistory.delete(t.id);else selectedHistory.add(t.id);renderHistory();});
  wire('queue-selected','click',()=>historyBatch('queue'));wire('restart-selected','click',()=>historyBatch('restart'));wire('restart-all','click',()=>historyBatch('all'));wire('delete-selected','click',()=>historyBatch('delete'));
  wire('log-kind','change',()=>loadLogs());wire('log-level','change',()=>loadLogs());wire('refresh-logs','click',()=>loadLogs());wire('older-logs','click',()=>loadLogs(true));
  wire('legacy-log','click',legacyLog);
  wire('refresh-report','click',loadReport);wire('log-query','input',debounce(()=>loadLogs()));
  wire('embed-jobs','click',()=>maintenance('embed'));wire('classify-jobs','click',()=>maintenance('classify'));wire('classify-groq','click',()=>maintenance('classify','groq'));wire('stop-maintenance','click',async()=>{await api('/api/scrape/stop',{method:'POST'});$('maintenance-status').textContent='İşlem durduruluyor…';});wire('trash-filtered','click',trashFiltered);
  wire('save-task','click',saveTask);
  document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}}));
  window.addEventListener('popstate',()=>{readLocation();syncControls();renderChips();loadAll();});
  $('queue-host').append($('live-run'));
  $('waiting-list').addEventListener('toggle',e=>{const id=e.target.dataset?.waiting;if(id){if(e.target.open)openWaiting.add(id);else openWaiting.delete(id);}},true);
  Dash.initTips();wire('dash-refresh','click',()=>Dash.load(true));wire('dash-retry','click',()=>Dash.load(true));
  setInterval(()=>{if(document.visibilityState==='visible'&&Dash.visible())Dash.load();},30000);
  wire('watch-form','submit',saveWatch);wire('watch-cancel','click',resetWatchForm);['watch-keywords','watch-locations'].forEach(id=>wire(id,'input',watchCombos));watchCombos();
  setInterval(()=>{if(document.visibilityState==='visible'&&!$('view-watches').hidden)loadWatches();},20000);
  applyDev();let tab='jobs';try{tab=localStorage.getItem('linko.tab')||'jobs';}catch{}showTab(tab);
  loadAll();loadRunOptions();pollStatus();connectEvents();
  initBottomNav();
}
initialize();
