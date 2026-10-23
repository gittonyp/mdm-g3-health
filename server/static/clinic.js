(function(){
  const ClinicUI={
    api:async function(path,options){const r=await fetch(path,Object.assign({headers:{'content-type':'application/json','X-Demo-Actor':this.actor()}},options||{}));const body=await r.json();if(!r.ok)throw new Error(body.detail||'Request failed');return body},
    esc:v=>String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
    fmtAge:s=>{if(s==null)return '—';if(s<60)return `${Math.round(s)}s`;if(s<3600)return `${Math.round(s/60)}m`;return `${Math.round(s/3600)}h`},
    fmtDateTime:v=>v?new Date(v).toLocaleString():'—',fmtValue:(v,d=0)=>v==null?'Unknown':Number(v).toFixed(d),
    tierClass:t=>`tier-${t||'unknown'}`,actor:()=>localStorage.getItem('clinic.actor')||'doctor',
    setActor:a=>localStorage.setItem('clinic.actor',a),
    renderNav(active){document.querySelector('#nav').innerHTML=`<a href="/clinic" class="${active==='clinic'?'active':''}">Clinic</a><a href="/live" class="${active==='live'?'active':''}">Live</a><a href="/history">History</a><a href="/care">Caregiver</a><span class="spacer"></span><label>View <select id="actor"><option value="doctor">Doctor</option><option value="caregiver">Caregiver</option></select></label><a href="/api/health">System</a>`;const s=document.querySelector('#actor');s.value=this.actor();s.onchange=()=>this.setActor(s.value)},
    poll(fn,ms){fn();return setInterval(fn,ms)},openDialog:id=>document.getElementById(id).showModal(),
    drawChart(svg,series,key,options){svg.innerHTML='';if(!series||series.length<2){svg.innerHTML='<text x="8" y="24">No data</text>';return}const vals=series.map(x=>Number(x[key])).filter(Number.isFinite),w=svg.viewBox.baseVal.width||500,h=svg.viewBox.baseVal.height||150,min=Math.min(...vals),max=Math.max(...vals),pts=series.map((x,i)=>`${i*(w-10)/(series.length-1)+5},${h-8-(Number(x[key])-min)/(max-min||1)*(h-16)}`).join(' ');svg.innerHTML=`<polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="2"/>`},
  };window.ClinicUI=ClinicUI;
})();
