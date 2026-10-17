'use strict';
// Panel sekmesi: /api/dashboard verisini sayı kartı, çubuk, sütun, halka ve ısı haritası olarak çizer.
// Grafik kütüphanesi yoktur; her şey HTML/SVG. app.js'ten $, esc, tr, api, shortDate paylaşılır (yalnızca çağrı anında kullanılır).
const Dash=(()=>{
  let controller,serial=0,data=null,lastKey='',tip=null;
  const nf=n=>Number(n||0).toLocaleString('tr-TR');
  const compact=n=>n>=1e6?(n/1e6).toLocaleString('tr-TR',{maximumFractionDigits:1})+' Mn':n>=1000?(n/1000).toLocaleString('tr-TR',{maximumFractionDigits:1})+' B':String(Math.round(n*10)/10).replace('.',',');
  const share=(a,b)=>b?'%'+(100*a/b).toLocaleString('tr-TR',{maximumFractionDigits:1}):'—';
  const parse=iso=>{const d=new Date(iso);return isNaN(d)?null:d;};
  const ago=iso=>{const d=iso&&parse(iso);if(!d)return 'henüz yok';const s=Math.max(0,(Date.now()-d)/1000);return s<90?'az önce':s<3600?`${Math.round(s/60)} dk önce`:s<86400?`${Math.round(s/3600)} sa önce`:`${Math.round(s/86400)} gün önce`;};
  const inTime=sec=>sec<=60?'birkaç saniye içinde':sec<5400?`${Math.round(sec/60)} dk sonra`:sec<172800?`${Math.round(sec/3600)} sa sonra`:`${Math.round(sec/86400)} gün sonra`;
  const clock=sec=>`${String(Math.floor(sec/60)).padStart(2,'0')}:${String(Math.floor(sec%60)).padStart(2,'0')}`;
  const dayKey=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  const dayName=d=>d.toLocaleDateString('tr-TR',{day:'numeric',month:'short',weekday:'short'});
  const dayShort=d=>d.toLocaleDateString('tr-TR',{day:'numeric',month:'short'});
  const WEEKDAYS=['Pazartesi','Salı','Çarşamba','Perşembe','Cuma','Cumartesi','Pazar'],WEEKDAYS_SHORT=['Pzt','Sal','Çar','Per','Cum','Cmt','Paz'];
  // Yalnızca doğrulanmış mavi/turuncu/camgöbeği üçlüsü + nötr gri ("bilinmiyor", yapay zekâsız) kullanılır.
  const COLORS={Remote:'var(--s1)',Hybrid:'var(--s3)',Onsite:'var(--s2)',__missing__:'var(--s0)',rules:'var(--s0)',groq:'var(--s3)',local:'var(--s2)',claude:'var(--s1)',llm:'var(--s1)'};
  const SENIORITY=['Intern','Junior','Mid','Senior','Lead','Manager','__missing__'];
  const tipAttr=text=>`data-tip="${esc(text)}"`;
  const label=value=>value==='__missing__'?'Belirtilmemiş':tr(value);

  // 1, 2, 4, 6, 8 × 10^k: yarı değeri de tam sayı kalan tavan.
  function niceMax(v){if(v<=2)return 2;const p=10**Math.floor(Math.log10(v));return Math.ceil(v/p/2)*2*p;}

  function daily(hourly,days){
    const map=new Map();
    for(const [hour,n] of hourly){const d=parse(hour.replace(' ','T')+':00:00Z');if(d)map.set(dayKey(d),(map.get(dayKey(d))||0)+n);}
    const today=new Date();today.setHours(12,0,0,0);const out=[];
    for(let i=days-1;i>=0;i--){const d=new Date(today);d.setDate(d.getDate()-i);out.push({date:d,count:map.get(dayKey(d))||0});}
    return out;
  }
  function last24(hourly){
    const map=new Map(hourly);const out=[];
    for(let i=23;i>=0;i--)out.push(map.get(new Date(Date.now()-i*3600e3).toISOString().slice(0,13).replace('T',' '))||0);
    return out;
  }
  function heat(hourly){
    const grid=Array.from({length:7},()=>Array(24).fill(0));
    for(const [hour,n] of hourly){const d=parse(hour.replace(' ','T')+':00:00Z');if(d)grid[(d.getDay()+6)%7][d.getHours()]+=n;}
    return grid;
  }

  function table(title,headers,rows){
    return `<details class="d-table" data-k="${esc(title)}"><summary>Tablo olarak göster</summary><div class="d-table-wrap"><table class="report-table"><thead><tr>${headers.map(h=>`<th scope="col">${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map((c,i)=>i?`<td>${esc(c)}</td>`:`<th scope="row">${esc(c)}</th>`).join('')}</tr>`).join('')}</tbody></table></div></details>`;
  }
  const card=(span,title,sub,body,extra='',cls='')=>`<section class="d-card d-${span} ${cls}" aria-label="${esc(title)}"><header><h2>${esc(title)}</h2>${sub?`<p class="help">${esc(sub)}</p>`:''}</header>${body}${extra}</section>`;
  const none=text=>`<p class="d-none">${esc(text)}</p>`;

  function spark(values,split=0){
    const n=values.length,max=Math.max(1,...values),w=100,h=30;
    const pts=values.map((v,i)=>[n>1?i*w/(n-1):w/2,h-3-(v/max)*(h-8)]);
    const line=p=>p.map(q=>q[0].toFixed(1)+','+q[1].toFixed(1)).join(' ');
    const last=pts[n-1];
    const body=split&&split<n?`<polyline class="d-line muted" points="${line(pts.slice(0,n-split+1))}"/><polyline class="d-line" points="${line(pts.slice(n-split))}"/>`
      :`<polygon class="d-area" points="0,${h} ${line(pts)} ${w},${h}"/><polyline class="d-line" points="${line(pts)}"/>`;
    return `<span class="d-spark" aria-hidden="true"><svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">${body}</svg><i class="d-dot" style="top:${(last[1]/h*100).toFixed(1)}%"></i></span>`;
  }
  function delta(cur,prev,text){
    if(!cur&&!prev)return `<span class="d-delta flat">— ${esc(text)}</span>`;
    if(!prev)return `<span class="d-delta up">▲ yeni · ${esc(text)}</span>`;
    const p=Math.round(100*(cur-prev)/prev);
    return `<span class="d-delta ${p>=0?'up':'down'}">${p>=0?'▲':'▼'} %${Math.abs(p)} · ${esc(text)}</span>`;
  }
  // <button> içinde yalnızca satır içi öğeler kullanılır; bu yüzden liste yerine iç içe span.
  const mini=rows=>`<span class="d-mini">${rows.map(([k,v])=>`<span><span>${esc(k)}</span><b>${v}</b></span>`).join('')}</span>`;
  function stat({cls='',name,value,sub='',attrs='',extra='',tip=''}){
    return `<button type="button" class="d-stat ${cls}" ${attrs} ${tip?tipAttr(tip):''}><span class="d-stat-l">${esc(name)}</span><strong class="d-stat-v">${value}</strong><span class="d-stat-s">${sub}</span>${extra}</button>`;
  }

  // labelEvery=0: yalnızca dolu etiketler gösterilir; partial: henüz bitmemiş dönem (açık renkli çizilir).
  function columns(items,{labelEvery=5,height=176,aria=''}={}){
    const max=niceMax(Math.max(0,...items.map(i=>i.total)));
    const lines=[max,max/2,0].map(v=>`<span class="d-gl${v?'':' base'}" style="bottom:${v/max*100}%"><em>${compact(v)}</em></span>`).join('');
    const cols=items.map(i=>{
      const segs=(i.segs||[{v:i.total,c:i.color||'var(--s1)'}]).filter(s=>s.v>0);
      return `<span class="d-col${i.partial?' partial':''}" ${tipAttr(i.tip)}>${i.total>0?`<span class="d-stack" style="height:${i.total/max*100}%">${segs.map(s=>`<i style="flex:${s.v} 0 0;background:${s.c}"></i>`).join('')}</span>`:''}</span>`;
    }).join('');
    const n=items.length;
    const xs=items.map((i,k)=>`<span>${i.label&&(!labelEvery||(n-1-k)%labelEvery===0)?`<b>${esc(i.label)}</b>`:''}</span>`).join('');
    return `<div class="d-chart" role="img" aria-label="${esc(aria)}"><div class="d-plot" style="min-height:${height}px">${lines}<div class="d-cols" style="--n:${n}">${cols}</div></div><div class="d-x" style="--n:${n}">${xs}</div></div>`;
  }

  function bars(rows,key,total,{order}={}){
    if(!rows.length)return none('Henüz veri yok.');
    const max=Math.max(1,...rows.map(r=>r.count));
    const list=order?[...rows].sort((a,b)=>(order.indexOf(a.value)+1||99)-(order.indexOf(b.value)+1||99)):rows;
    return `<div class="d-bars">${list.map(r=>{
      const text=`${label(r.value)}\n${nf(r.count)} ilan · ${share(r.count,total)}`;
      return `<button type="button" class="d-bar" data-dash-filter="${key}" data-dash-value="${esc(r.value)}" ${tipAttr(text)} aria-label="${esc(text.replace('\n',': '))}; ilanları göster"><span class="d-bar-l">${esc(label(r.value))}</span><span class="d-bar-t"><i style="width:${Math.max(2,r.count/max*100)}%"></i></span><span class="d-bar-v">${nf(r.count)}</span></button>`;
    }).join('')}</div>`;
  }

  function legend(rows,key,total){
    return `<div class="d-legend">${rows.map(r=>`<button type="button" class="d-leg" data-dash-filter="${key}" data-dash-value="${esc(r.value)}"><i style="background:${COLORS[r.value]||'var(--s0)'}"></i><span>${esc(label(r.value))}</span><b>${nf(r.count)}</b><small>${share(r.count,total)}</small></button>`).join('')}</div>`;
  }

  function donut(rows,total,centerLabel){
    const R=15.9155,C=2*Math.PI*R;let offset=0;
    const arcs=rows.filter(r=>r.count>0).map((r,_,all)=>{
      const len=r.count/total*C,gap=all.length>1?Math.min(.8,len*.25):0;
      const el=`<circle cx="21" cy="21" r="${R}" fill="none" stroke="${COLORS[r.value]||'var(--s0)'}" stroke-width="5" stroke-dasharray="${(len-gap).toFixed(2)} ${(C-len+gap).toFixed(2)}" stroke-dashoffset="${(-offset).toFixed(2)}" transform="rotate(-90 21 21)" ${tipAttr(`${label(r.value)}\n${nf(r.count)} ilan · ${share(r.count,total)}`)}/>`;
      offset+=len;return el;
    }).join('');
    return `<div class="d-donut" aria-hidden="true"><svg viewBox="0 0 42 42"><circle cx="21" cy="21" r="${R}" fill="none" class="d-donut-track" stroke-width="5"/>${arcs}</svg><div class="d-donut-c"><strong>${nf(total)}</strong><span>${esc(centerLabel)}</span></div></div>`;
  }

  function meter(name,count,total,filter,warn=false){
    const p=total?count/total*100:0;
    const body=`<span class="d-meter-h"><span>${warn?'⚠ ':''}${esc(name)}</span><b>${share(count,total)}</b></span><span class="d-meter-t"><i class="${warn?'warn':''}" style="width:${p.toFixed(1)}%"></i></span><small>${nf(count)} / ${nf(total)} ilan</small>`;
    const text=`${name}\n${nf(count)} / ${nf(total)} ilan · ${share(count,total)}`;
    return filter?`<button type="button" class="d-meter" data-dash-filter="${filter[0]}" data-dash-value="${filter[1]}" ${tipAttr(text)}>${body}</button>`:`<div class="d-meter" ${tipAttr(text)}>${body}</div>`;
  }

  function salaryRows(rows){
    if(!rows.length)return none('Maaş ve para birimi/dönemi belirtilen ilan henüz yok.');
    return `<div class="d-salary">${rows.map(r=>{
      const span=r.max-r.min||1,pos=v=>((v-r.min)/span*100);
      const low=pos(r.p25),high=Math.max(pos(r.p75),low+3);
      const text=`${r.currency} · ${tr(r.period)}\n${nf(r.count)} ilan\nOrta noktaların medyanı ${nf(r.median)} · çeyrekler ${nf(r.p25)}–${nf(r.p75)} · uçlar ${nf(r.min)}–${nf(r.max)}`;
      return `<div class="d-sal" ${tipAttr(text)}><div class="d-sal-h"><span>${esc(r.currency)} · ${esc(tr(r.period).toLocaleLowerCase('tr'))}</span><b>${nf(r.median)} <small>medyan</small></b></div><div class="d-sal-t"><i class="range" style="left:${low}%;width:${Math.min(high,100)-low}%"></i><i class="med" style="left:${pos(r.median)}%"></i></div><small>${nf(r.count)} ilan · ${nf(r.min)} – ${nf(r.max)}</small></div>`;
    }).join('')}</div>`;
  }

  function collector(c,t){
    const src=c.source,w=c.watches,now=c.now;
    // Kaynak beklerken yeni tur açılmaz (watches.dispatch); bu yüzden vakti gelmiş tur beklemenin bitmesine bağlıdır.
    const wait=src.paused?src.remaining_seconds:0;
    const due=w.next_due_at==null?'Etkin alarm yok':w.next_due_at-now<=wait?(src.paused?'Kaynak beklemesi bitince':'Sırası geldi, kuyruğa alınacak'):inTime(w.next_due_at-now);
    const statuses=Object.entries(c.run_statuses).map(([s,n])=>`<span class="state-pill state-${esc(s)}">● ${esc(tr(s))} ${n}</span>`).join('')||'<span class="help">Son 7 günde tur yok</span>';
    const row=(k,v)=>`<div><dt>${esc(k)}</dt><dd>${v}</dd></div>`;
    return `<div class="d-source ${src.paused?'paused':'ready'}" role="status"><span aria-hidden="true">${src.paused?'⏸':'✓'}</span><div><strong>${src.paused?`Kaynak bekliyor · ${clock(src.remaining_seconds)} kaldı`:'Kaynak erişime hazır'}</strong>${src.paused&&src.reason?`<small>${esc(src.reason)}</small>`:'<small>Hız sınırı ve bekleme kuralları otomatik uygulanır.</small>'}</div></div>
      <dl class="d-facts">${row('Tarama',c.running?'<span class="state-pill state-running">● Çalışıyor</span>':'Boşta')}${row('İş alarmları',`${nf(w.enabled)} / ${nf(w.total)} etkin`)}${row('Sıradaki alarm turu',esc(due))}${row('Son ilan eklenme',esc(ago(t.last_created_at)))}${row('Son tarama',esc(ago(t.last_scraped_at)))}${row('İstek aralığı tabanı',`${nf(src.interval_floor)} sn`)}</dl>
      <div class="d-chips" aria-label="Son 7 gündeki turların durumu">${statuses}</div>
      <div class="actions"><button type="button" data-action="queue">Kuyruğu aç</button><button type="button" data-action="watches">İş alarmları</button></div>`;
  }

  function render(){
    const d=data,t=d.totals,c=d.collector,total=t.total;
    const body=$('dash-body');
    if(!total&&!c.runs.length){
      body.innerHTML=`<div class="empty d-12"><h2>Panel henüz boş</h2><p>İlk taramadan sonra ilan akışı, dağılımlar ve toplayıcı durumu burada görünür.</p><button class="primary" data-action="new-search">+ Yeni arama</button></div>`;
      return;
    }
    const days=daily(d.hourly,30),hours=last24(d.hourly),week=days.slice(-14).map(x=>x.count);
    const peak=days.reduce((a,b)=>b.count>a.count?b:a,days[0]);
    const created30=days.reduce((s,x)=>s+x.count,0);
    const tiles=[
      stat({cls:'d-hero',name:'Etkin ilan',value:nf(total),sub:`${nf(t.companies)} şirket · ${nf(t.trash)} ilan çöp kutusunda`,attrs:'data-dash-filter=""',
        extra:mini([['Uzaktan veya hibrit',share(t.remote+t.hybrid,total)],['Son 30 günde eklenen',nf(created30)],['Son ilan eklenme',esc(ago(t.last_created_at))]])+spark(days.map(x=>x.count)),tip:'Tüm etkin ilanları göster'}),
    ];
    const small=[
      stat({name:'Son 24 saatte eklenen',value:nf(t.created_24h),sub:'sisteme ilk kez eklenen',attrs:'data-dash-window="created_from:1"',extra:spark(hours),tip:'Son 24 saatte eklenen ilanları göster'}),
      stat({name:'Son 7 günde eklenen',value:nf(t.created_7d),sub:delta(t.created_7d,t.created_prev_7d,'önceki 7 güne göre'),attrs:'data-dash-window="created_from:7"',extra:spark(week,7),tip:'Son 7 günde eklenen ilanları göster'}),
      stat({name:'Yayını son 7 günde olan',value:nf(t.posted_7d),sub:`${nf(t.posted_24h)} tanesi son 24 saatte yayınlandı`,attrs:'data-dash-window="posted_from:7"',tip:'Son 7 günde yayınlanan ilanları göster'}),
      stat({name:'Maaşı belirtilen',value:share(t.with_salary,total),sub:`${nf(t.with_salary)} ilan`,attrs:'data-dash-filter="has_salary" data-dash-value="1"',extra:`<span class="d-meter-t slim" aria-hidden="true"><i style="width:${total?t.with_salary/total*100:0}%"></i></span>`,tip:'Maaşı belirtilen ilanları göster'}),
    ];

    const flow=card(8,'Günlük ilan akışı','Her gün sisteme ilk kez eklenen ilan sayısı · son 30 gün · bugünün sütunu açık renkli, gün henüz bitmedi',
      columns(days.map((x,k)=>({total:x.count,label:dayShort(x.date),partial:k===days.length-1,tip:`${dayName(x.date)}${k===days.length-1?' (bugün, sürüyor)':''}\n${nf(x.count)} yeni ilan`})),{aria:`Son 30 günde ${nf(created30)} ilan eklendi. En yoğun gün ${dayName(peak.date)}, ${nf(peak.count)} ilan.`})
      +`<p class="d-note">${created30?`30 günde <b>${nf(created30)}</b> ilan · en yoğun gün <b>${esc(dayName(peak.date))}</b> (${nf(peak.count)})`:'Son 30 günde yeni ilan eklenmedi.'}</p>`,
      table('Günlük ilan akışı',['Gün','Eklenen ilan'],days.map(x=>[dayName(x.date),nf(x.count)])));
    const status=card(4,'Toplayıcı durumu','Kaynak, iş alarmları ve son etkinlik',collector(c,t),'','d-collector');

    const professions=card(4,'Meslek grupları','Bir ilan birden çok grupta sayılabilir · ilk 8',bars(d.professions,'profession_group',total),
      table('Meslek grupları',['Grup','İlan'],d.professions.map(r=>[r.value,nf(r.count)])));
    const wTotal=d.workplace.reduce((s,r)=>s+r.count,0);
    const workplace=card(4,'Çalışma biçimi','Uzaktan, hibrit ve ofiste dağılımı',
      wTotal?`<div class="d-donut-row">${donut(d.workplace,wTotal,'ilan')}${legend(d.workplace,'workplace',wTotal)}</div>`:none('Henüz veri yok.'),
      table('Çalışma biçimi',['Biçim','İlan'],d.workplace.map(r=>[label(r.value),nf(r.count)])));
    const seniority=card(4,'Kıdem düzeyi','Stajyerden yöneticiye',bars(d.seniority,'seniority',total,{order:SENIORITY}),
      table('Kıdem düzeyi',['Kıdem','İlan'],d.seniority.map(r=>[label(r.value),nf(r.count)])));

    const skills=card(4,'En çok istenen yetenekler','İlan açıklamalarından çıkarılan · ilk 12',bars(d.skills,'skills',total),
      table('Yetenekler',['Yetenek','İlan'],d.skills.map(r=>[r.value,nf(r.count)])));
    const companies=card(4,'En çok ilan veren şirketler','İlk 8',bars(d.companies,'company',total),table('Şirketler',['Şirket','İlan'],d.companies.map(r=>[r.value,nf(r.count)])));
    // d-tw: iki sütunlu (tablet) düzende tek kalacak kartlar tam genişlikte gösterilir.
    const locations=card(4,'En çok ilan olan konumlar','İlk 8',bars(d.locations,'location',total),table('Konumlar',['Konum','İlan'],d.locations.map(r=>[r.value,nf(r.count)])),'d-tw');

    let prevDay='';
    const runItems=c.runs.map(r=>{const when=parse(r.ended_at||r.created_at),name=when?dayShort(when):'',first=name!==prevDay;prevDay=name;return {total:r.new+r.updated,label:first?name:'',segs:[{v:r.new,c:'var(--s3)'},{v:r.updated,c:'var(--s1)'}],
      tip:`${when?when.toLocaleString('tr-TR',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}):''}\n${tr(r.status)} · ${r.watch?'iş alarmı':'elle başlatılan'}\n${nf(r.new)} yeni · ${nf(r.updated)} güncellenen · ${nf(r.tasks)} arama`};});
    const runs=card(6,'Son tarama turları','Her sütun bir tur: yeni ve güncellenen ilan sayısı',
      c.runs.length?`<div class="d-keys"><span><i style="background:var(--s3)"></i>Yeni</span><span><i style="background:var(--s1)"></i>Güncellenen</span></div>${columns(runItems,{labelEvery:0,height:150,aria:`Son ${c.runs.length} tarama turunda ${nf(c.runs.reduce((s,r)=>s+r.new,0))} yeni ilan bulundu.`})}`:none('Son 7 günde tarama turu yok.'),
      c.runs.length?table('Son tarama turları',['Tur','Durum','Tür','Yeni','Güncellenen','Arama'],c.runs.map(r=>[shortDate(r.ended_at||r.created_at,true),tr(r.status),r.watch?'İş alarmı':'Elle',nf(r.new),nf(r.updated),nf(r.tasks)])):'');

    const grid=heat(d.hourly),hmax=Math.max(0,...grid.flat());
    let best=[0,0];grid.forEach((row,i)=>row.forEach((v,j)=>{if(v>grid[best[0]][best[1]])best=[i,j];}));
    const hours24=[...Array(24).keys()];
    const heatBody=hmax?`<div class="d-heat" role="img" aria-label="Son 30 günde ilanların hangi gün ve saatte eklendiği. En yoğun zaman ${WEEKDAYS[best[0]]} ${String(best[1]).padStart(2,'0')}:00."><span></span>${hours24.map(h=>`<span class="d-heat-h">${h%3===0?String(h).padStart(2,'0'):''}</span>`).join('')}${grid.map((row,i)=>`<span class="d-heat-d">${WEEKDAYS_SHORT[i]}</span>${row.map((v,j)=>`<span class="d-cell${v?'':' zero'}" style="--v:${v?Math.round(18+82*v/hmax):0}%" ${tipAttr(`${WEEKDAYS[i]} ${String(j).padStart(2,'0')}:00–${String((j+1)%24).padStart(2,'0')}:00\n${nf(v)} ilan eklendi`)}></span>`).join('')}`).join('')}</div><div class="d-heat-key"><span>Az</span><i></i><span>Çok</span></div><p class="d-note">En yoğun zaman: <b>${WEEKDAYS[best[0]]} ${String(best[1]).padStart(2,'0')}:00</b> · saatler tarayıcının saat dilimine göre</p>`:none('Son 30 günde yeni ilan eklenmedi.');
    const heatCard=card(6,'İlanlar ne zaman ekleniyor?','Haftanın günü ve saatine göre eklenme yoğunluğu · son 30 gün',heatBody,
      hmax?table('Eklenme yoğunluğu',['Gün',...hours24.map(h=>String(h).padStart(2,'0'))],grid.map((row,i)=>[WEEKDAYS[i],...row.map(nf)])):'');

    const ageTotal=d.posted_age.reduce((s,r)=>s+r.count,0);
    const age=card(4,'İlan yaşı','Yayın tarihine göre',ageTotal?columns(d.posted_age.map(r=>({total:r.count,label:r.label,color:r.key==='unknown'?'var(--s0)':'var(--s1)',tip:`${r.label}\n${nf(r.count)} ilan · ${share(r.count,ageTotal)}`})),{labelEvery:1,height:150,aria:'Yayın yaşına göre ilan dağılımı.'}):none('Henüz veri yok.'),
      table('İlan yaşı',['Yaş','İlan'],d.posted_age.map(r=>[r.label,nf(r.count)])));
    const salary=card(4,'Maaş aralıkları','Her satır kendi para birimi ve döneminde · aralık orta noktaları',salaryRows(d.salary),
      d.salary.length?table('Maaş aralıkları',['Para birimi / dönem','İlan','Alt','Medyan','Üst'],d.salary.map(r=>[`${r.currency} · ${tr(r.period)}`,nf(r.count),nf(r.p25),nf(r.median),nf(r.p75)])):'');
    const backendTotal=d.backend.reduce((s,r)=>s+r.count,0);
    const backendBar=backendTotal?`<div class="d-stackbar" aria-hidden="true">${d.backend.map(r=>`<i style="flex:${r.count} 0 0;background:${COLORS[r.value]||'var(--s0)'}" ${tipAttr(`${label(r.value)}\n${nf(r.count)} ilan · ${share(r.count,backendTotal)}`)}></i>`).join('')}</div>${legend(d.backend,'backend',backendTotal)}`:'';
    const quality=card(4,'Veri kalitesi','Etkin ilanların ne kadarı zenginleştirilmiş',
      `<div class="d-meters">${meter('Açıklaması olan',t.with_description,total,['has_description','1'])}${meter('Yapay zekâ özeti olan',t.with_summary,total,['has_summary','1'])}${meter('Eşleştirme verisi olan',t.with_embedding,total,['has_embedding','1'])}${meter('Şüpheli işaretlenen',t.flagged,total,null,true)}</div><h3 class="d-sub">Analiz yöntemi</h3>${backendBar}`,
      table('Veri kalitesi',['Ölçüt','İlan','Oran'],[['Açıklaması olan',t.with_description,share(t.with_description,total)],['Yapay zekâ özeti olan',t.with_summary,share(t.with_summary,total)],['Eşleştirme verisi olan',t.with_embedding,share(t.with_embedding,total)],['Şüpheli işaretlenen',t.flagged,share(t.flagged,total)],...d.backend.map(r=>[`Analiz: ${label(r.value)}`,r.count,share(r.count,backendTotal)])].map(r=>[r[0],nf(r[1]),r[2]])),'d-tw');

    const open=new Set([...body.querySelectorAll('details[open]')].map(x=>x.dataset.k));
    body.innerHTML=`<div class="d-tiles d-12">${tiles.join('')}<div class="d-small">${small.join('')}</div></div>${flow}${status}${professions}${workplace}${seniority}${skills}${companies}${locations}${runs}${heatCard}${age}${salary}${quality}`;
    body.querySelectorAll('details[open]').forEach(x=>x.removeAttribute('open'));
    body.querySelectorAll('details').forEach(x=>{if(open.has(x.dataset.k))x.open=true;});
    hideTip();
  }

  function hideTip(){if(tip)tip.hidden=true;}
  function showTip(el,x,y){
    tip.textContent=el.dataset.tip;tip.hidden=false;
    const r=tip.getBoundingClientRect();
    tip.style.left=Math.max(8,Math.min(x+14,innerWidth-r.width-8))+'px';
    tip.style.top=(y-r.height-14<8?y+18:y-r.height-14)+'px';
  }
  function initTips(){
    tip=document.createElement('div');tip.id='dash-tip';tip.className='d-tip';tip.setAttribute('role','tooltip');tip.hidden=true;document.body.append(tip);
    const host=$('dash-body');
    host.addEventListener('pointermove',e=>{const el=e.target.closest('[data-tip]');if(el)showTip(el,e.clientX,e.clientY);else hideTip();});
    host.addEventListener('pointerleave',hideTip);
    host.addEventListener('focusin',e=>{const el=e.target.closest('[data-tip]');if(el){const r=el.getBoundingClientRect();showTip(el,r.left+r.width/2,r.top);}});
    host.addEventListener('focusout',hideTip);
    document.addEventListener('scroll',hideTip,{passive:true});
    document.addEventListener('keydown',e=>{if(e.key==='Escape')hideTip();});
  }

  async function load(force=false){
    controller?.abort();controller=new AbortController();const mine=++serial;
    const host=$('dash-body'),first=!data;
    host.setAttribute('aria-busy','true');if(first)host.innerHTML='<p class="notice d-12" role="status">Panel yükleniyor…</p>';
    $('dash-refresh').disabled=true;
    try{
      const next=await api('/api/dashboard'+(force?'?refresh=1':''),{signal:controller.signal});
      if(mine!==serial)return;
      const key=JSON.stringify({...next,generated_at:0,collector:{...next.collector,now:0},minute:Math.floor(Date.now()/60000)});
      data=next;$('dash-error').hidden=true;
      if(key!==lastKey||first){lastKey=key;render();}
      $('dash-updated').textContent='Güncellendi '+new Date(next.generated_at).toLocaleTimeString('tr-TR',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
    }catch(e){
      if(e.name==='AbortError'||mine!==serial)return;
      $('dash-error').hidden=false;$('dash-error-text').textContent=e.message;
      if(first)host.innerHTML='';
    }finally{if(mine===serial){host.setAttribute('aria-busy','false');$('dash-refresh').disabled=false;}}
  }
  return {load,initTips,visible:()=>!$('view-dashboard').hidden};
})();
