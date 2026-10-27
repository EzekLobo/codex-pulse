'use strict';
function activityKey(){return 'codex-pulse-activities-v1'+(state.data?.demo?'-demo':'');}
function evaluations(){try{const rows=JSON.parse(localStorage.getItem(activityKey())||'[]');return Array.isArray(rows)?rows:[];}catch{return [];}}
function renderWorkflow(){
 const calls=state.data?.calls||[], groups=bucketize(calls,'session');
 const selected=$('activity-session').value;
 $('activity-session').innerHTML=groups.map(g=>`<option value="${escapeHtml(g.id)}">${escapeHtml(shortPath(g.project))} · ${escapeHtml(g.id)} · ${g.calls} chamadas</option>`).join('');
 if(groups.some(g=>g.id===selected))$('activity-session').value=selected;
 const hour=calls.filter(c=>{const age=Date.now()-Date.parse(c.timestamp);return age>=0&&age<=3600000;});
 $('workflow-insights').textContent=`Última hora: ${number(sum(hour,'total'))} tokens · ${hour.length} chamadas. ${hour.length?'Observe chamadas repetidas e crescimento do contexto ao avaliar retrabalho.':'Sem atividade recente registrada.'}`;
 const stats=new Map();
 for(const row of evaluations()){
   if(!row.type||!row.complexity||!Array.isArray(row.models)||!row.models.length)continue;
   const key=JSON.stringify([row.type,row.complexity,row.models.slice().sort()]);
   if(!stats.has(key))stats.set(key,{...row,n:0,accepted:0,tokens:0,cost:0,partial:false});
   const s=stats.get(key);s.n++;s.accepted+=row.result==='accepted'?1:0;s.tokens+=Number(row.tokens)||0;s.cost+=Number(row.cost)||0;s.partial ||= row.partial;
 }
 $('activity-comparison').innerHTML=stats.size?`<div style="overflow:auto"><table>${headers(['Atividade / complexidade','Modelo(s)','Avaliadas','Sucesso','Tokens / entrega aceita','API equivalente / entrega','Confiança'])}<tbody>${[...stats.values()].map(s=>`<tr><td>${escapeHtml(s.type)} / ${escapeHtml(s.complexity)}</td><td>${s.models.map(escapeHtml).join(', ')}</td><td>${s.n}</td><td>${percent(100*s.accepted/s.n)}</td><td>${s.accepted?number(Math.round(s.tokens/s.accepted)):'Sem entrega aceita'}</td><td>${s.partial?'Tarifas incompletas':s.accepted?dollar(s.cost/s.accepted):'—'}</td><td>${s.n<5?'Experimental: poucas amostras':'Histórico observacional'}</td></tr>`).join('')}</tbody></table><p>Consumo inclui tentativas sem sucesso. Sessões com vários modelos são avaliadas em conjunto. Compare atividades de mesma complexidade; a classificação é manual.</p></div>`:empty('Avalie sessões para comparar modelos por resultado.');
}
document.addEventListener('DOMContentLoaded',()=>{
 $('activity-form').addEventListener('submit',event=>{
   event.preventDefault();const id=$('activity-session').value;
   const calls=(state.data?.calls||[]).filter(c=>c.session_id===id);if(!calls.length)return;
   const rows=evaluations().filter(r=>r.id!==id);
   rows.push({id,type:$('activity-type').value,complexity:$('activity-complexity').value,result:$('activity-result').value,models:[...new Set(calls.map(c=>c.model))],tokens:sum(calls,'total'),cost:sum(calls,'cost'),partial:calls.some(c=>c.cost==null),calls:calls.length,updated:new Date().toISOString()});
   try{localStorage.setItem(activityKey(),JSON.stringify(rows));$('activity-status').textContent='Avaliação salva; salvar novamente substitui a avaliação desta sessão.';renderWorkflow();}catch{$('activity-status').textContent='Não foi possível salvar no navegador. Verifique o armazenamento disponível.';}
 });
 $('activity-export').addEventListener('click',()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(evaluations(),null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='codex-pulse-atividades.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
});
const $ = id => document.getElementById(id);
const state = {data:null, rows:[], view:'overview', showPrompts:false, page:40, loading:false, lastUpdated:null};
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const compact = n => new Intl.NumberFormat('pt-BR',{notation:'compact',maximumFractionDigits:1}).format(n||0);
const number = n => new Intl.NumberFormat('pt-BR').format(n||0);
const dollar = n => n == null ? 'Sem preço' : new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',minimumFractionDigits:n<.01?4:2,maximumFractionDigits:4}).format(n);
const percent = n => new Intl.NumberFormat('pt-BR',{maximumFractionDigits:1}).format(n||0)+'%';
const dt = t => t ? new Date(t).toLocaleString('pt-BR',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}) : '—';
const day = t => new Date(t).toLocaleDateString('pt-BR',{day:'2-digit',month:'short'});
const shortPath = x => String(x||'Sem projeto').split(/[\\/]/).filter(Boolean).slice(-1)[0] || 'Sem projeto';
const sum = (items, field) => items.reduce((a,x) => a+(Number(x[field])||0),0);
const safeModel = m => `<span class="model-pill">${escapeHtml(m)}</span>`;
const empty = text => `<div class="empty">${escapeHtml(text)}</div>`;
const headers = cols => `<thead><tr>${cols.map(x=>`<th>${x}</th>`).join('')}</tr></thead>`;

async function refresh(){
 if(state.loading)return;state.loading=true;$('refresh').textContent='…';
 try{
  const r=await fetch('/api/data',{cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);
  state.data=await r.json();
  state.lastUpdated=new Date();$('updated').textContent=`Atualizado ${state.lastUpdated.toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}`;
  $('source').textContent=state.data.source;$('demoNotice').hidden=!state.data.demo;
  updateOptions();render();
  renderWorkflow();
 }catch(error){$('updated').textContent='Erro de leitura';console.error(error);if(!state.data)$('trend').innerHTML=empty('Não foi possível acessar o servidor local.');}
 finally{state.loading=false;$('refresh').textContent='↻';}
}
function updateOptions(){
 for(const [id, values, mapper] of [
  ['project',state.data.calls.map(x=>x.project),shortPath],
  ['model',state.data.calls.map(x=>x.model),x=>x]]){
  const el=$(id), current=el.value;
  const choices=[...new Set(values)].sort((a,b)=>a.localeCompare(b));
  el.innerHTML=`<option value="">${id==='project'?'Todos os projetos':'Todos os modelos'}</option>`+choices.map(x=>`<option value="${escapeHtml(x)}">${escapeHtml(mapper(x))}</option>`).join('');
  el.value=choices.includes(current)?current:'';
 }
}
function getRows(){
 const period=Number($('period').value),project=$('project').value,model=$('model').value,q=$('search').value.trim().toLowerCase();
 const cutoff=period?Date.now()-period*86400000:0;
 return (state.data?.calls||[]).filter(x=>(!period||new Date(x.timestamp).getTime()>=cutoff)&&(!project||x.project===project)&&(!model||x.model===model)&&(!q||[x.id,x.session_id,x.project,x.model,x.prompt,x.prompt_id].join(' ').toLowerCase().includes(q)));
}
function getOverview(rows){
 const input=sum(rows,'input'),cached=sum(rows,'cached'),output=sum(rows,'output'),reasoning=sum(rows,'reasoning');
 const priced=rows.filter(x=>x.cost!=null),unpriced=rows.length-priced.length;
 return {input,cached,output,reasoning,tokens:input+output,cacheRate:input?cached/input*100:0,cost:sum(priced,'cost'),unpriced,prompts:new Set(rows.map(x=>x.prompt_id)).size,sessions:new Set(rows.map(x=>x.session_id)).size};
}
function setView(view){
 state.view=view;state.page=40;
 for(const item of document.querySelectorAll('.nav-link'))item.classList.toggle('active',item.dataset.view===view);
 for(const item of document.querySelectorAll('.page'))item.classList.toggle('active',item.id===view);
 const labels={overview:['Visão geral','Acompanhe tokens, custos equivalentes e atividade em tempo quase real.'],prompts:['Análise de prompts','Descubra quais pedidos movimentam mais respostas e tokens.'],calls:['Chamadas ao modelo','Registros individuais dos responses, com custos equivalentes.'],sessions:['Sessões e projetos','Consumo acumulado por sessão do Codex.']};
 $('view-title').textContent=labels[view][0];$('view-subtitle').textContent=labels[view][1];render();
}
function render(){
 if(!state.data)return;
 state.rows=getRows();
 if(state.view==='overview')renderOverview(state.rows);
 else if(state.view==='prompts')renderPrompts(state.rows);
 else if(state.view==='calls')renderCalls(state.rows);
 else renderSessions(state.rows);
}
function renderOverview(rows){
 const s=getOverview(rows);
 $('kpi-tokens').textContent=compact(s.tokens);$('kpi-tokens-note').textContent=`${compact(s.input)} entrada · ${compact(s.output)} saída`;
 $('kpi-cost').textContent=s.unpriced===rows.length?'Sem preço':dollar(rows.length?s.cost:null);
 $('kpi-cost-note').textContent=s.unpriced?`${s.unpriced} chamada(s) sem tarifa configurada`:'Simulação pelo preço da API';
 $('kpi-cache').textContent=percent(s.cacheRate);
 $('kpi-calls').textContent=number(rows.length);$('kpi-calls-note').textContent=`${number(s.prompts)} prompts · ${number(s.sessions)} sessões`;
 renderTrend(rows);
 const byModel=new Map();rows.forEach(x=>byModel.set(x.model,(byModel.get(x.model)||0)+x.total));
 const ranked=[...byModel].sort((a,b)=>b[1]-a[1]).slice(0,6);
 $('model-bars').innerHTML=ranked.length?ranked.map(([m,n])=>`<div><div class="bar-header"><span>${escapeHtml(m)}</span><span>${percent(n/s.tokens*100)} · ${compact(n)}</span></div><div class="meter"><div style="width:${n/s.tokens*100}%"></div></div></div>`).join(''):empty('Nenhum modelo com registros neste intervalo.');
 const fresh=s.input-s.cached, parts=[['Entrada em cache',s.cached,'#5bd9bb'],['Entrada nova',fresh,'#477eaa'],['Saída',s.output,'#b496e9']];
 $('token-composition').innerHTML=s.tokens?`<div class="composition">${parts.map(([_,n,c])=>`<div style="width:${n/s.tokens*100}%;background:${c}"></div>`).join('')}</div><div class="legend">${parts.map(([label,n,c])=>`<span><i class="swatch" style="background:${c}"></i>${label} <b>${compact(n)}</b></span>`).join('')}</div>`:empty('Ainda não há tokens para analisar.');
 const saved=rows.reduce((n,x)=>n+Number(x.cost_breakdown?.saved_by_cache||0),0);
 $('insights').innerHTML=s.tokens?`<b>${compact(s.cached)}</b> tokens reutilizados (${percent(s.cacheRate)} das entradas). Economia API-equivalente com cache: <b>${dollar(saved)}</b> nas chamadas precificadas. ${compact(s.reasoning)} tokens de raciocínio já estão incluídos na saída.`:'Os insights aparecem quando houver chamadas.';
 renderLimits(state.data.limits);
 renderTable('recent-table',rows.slice(0,7),'calls',false);
}
function renderTrend(rows){
 const count=Number($('period').value), all=rows.filter(x=>x.timestamp);
 const now=new Date(), finish=new Date(now.getFullYear(),now.getMonth(),now.getDate());
 const earliest=all.reduce((n,c)=>Math.min(n,new Date(c.timestamp).getTime()),finish.getTime());
 const start=count?new Date(finish.getTime()-(count-1)*86400000):new Date(earliest);
 const dateStart=new Date(start.getFullYear(),start.getMonth(),start.getDate());
 const monthly=!count && (finish-dateStart)/86400000>120;
 const dates=[],vals=[];
 if(monthly){
   for(let d=new Date(dateStart.getFullYear(),dateStart.getMonth(),1), safety=0;d<=finish && safety<500;safety++,d.setMonth(d.getMonth()+1)){
     dates.push(`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`);vals.push(0);
   }
 }else{
   for(let d=new Date(dateStart),safety=0;d<=finish&&safety<121;safety++,d.setDate(d.getDate()+1)){
     dates.push(`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`);vals.push(0);
   }
 }
 const dateMap=new Map(dates.map((d,i)=>[d,i]));
 for(const c of all){
  const d=new Date(c.timestamp);const k=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}${monthly?'':`-${String(d.getDate()).padStart(2,'0')}`}`;
  const i=dateMap.get(k);if(i!==undefined)vals[i]+=c.total;
 }
 if(!dates.length||!all.length){$('trend').innerHTML=empty('Sem atividade registrada no período.');return;}
 const W=750,H=250,L=55,R=17,T=12,B=29;
 const max=Math.max(...vals,1)*1.16;const x=i=>L+(dates.length===1?(W-L-R)/2:i/(dates.length-1)*(W-L-R));const y=v=>T+(H-T-B)*(1-v/max);
 const points=vals.map((v,i)=>[x(i),y(v)]);const line=points.map((p,i)=>(i?'L':'M')+p.map(x=>x.toFixed(2)).join(',')).join(' ');
 const area=line+` L${x(dates.length-1)},${H-B} L${x(0)},${H-B} Z`;
 const ticks=[0,.25,.5,.75,1].map(r=>`<line x1="${L}" y1="${y(max*r)}" x2="${W-R}" y2="${y(max*r)}" class="chart-grid"/><text x="${L-12}" y="${y(max*r)+3}" class="axis-label" text-anchor="end">${compact(max*r)}</text>`).join('');
 const wanted=[...new Set([0,Math.round((dates.length-1)/4),Math.round((dates.length-1)/2),Math.round((dates.length-1)*.75),dates.length-1])];
 const axis=wanted.map(i=>`<text x="${x(i)}" y="${H-5}" class="axis-label" text-anchor="middle">${escapeHtml(monthly?new Date(`${dates[i]}-01T12:00:00`).toLocaleDateString('pt-BR',{month:'short',year:'2-digit'}):day(`${dates[i]}T12:00:00`))}</text>`).join('');
 const circle=points.map((p,i)=>`<circle cx="${p[0]}" cy="${p[1]}" r="4" class="chart-point"><title>${dates[i]}: ${number(vals[i])} tokens</title></circle>`).join('');
 $('trend').innerHTML=`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Gráfico de tokens por dia"><defs><linearGradient id="lineGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#54d9b9" stop-opacity=".33"/><stop offset="100%" stop-color="#54d9b9" stop-opacity="0"/></linearGradient></defs>${ticks}${axis}<path class="chart-fill" d="${area}"/><path class="chart-line" d="${line}"/>${dates.length<=45?circle:''}</svg>`;
}
function renderLimits(limits){
 if(!limits){$('limits').innerHTML=empty('Nenhum snapshot de limite encontrado nos logs.');return;}
 let wins=[limits.primary,limits.secondary].filter(x=>x&&x.window_minutes!=null);
 wins.sort((a,b)=>a.window_minutes-b.window_minutes);
 $('limits').innerHTML=wins.length?wins.map(w=>{
   const measured=Date.parse(limits.timestamp), age=(Date.now()-measured)/60000;
   const reset=w.resets_at!=null?Number(w.resets_at)*1000:measured+Number(w.resets_in_seconds)*1000;
   const expired=Number.isFinite(reset)&&reset<=Date.now();
   const valid=w.used_percent!=null&&Number.isFinite(Number(w.used_percent))&&Number.isFinite(measured)&&!expired;
   const pct=valid?Math.max(0,Math.min(100,Number(w.used_percent))):0,m=w.window_minutes;
   const name=m===300?'Janela de 5 horas':m===10080?'Janela semanal':m>=1440?`${m/1440} dias`:`${m} minutos`;
   const end=w.resets_at?new Date(w.resets_at*1000).toLocaleString('pt-BR',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}):'não disponível';
   return `<div class="quota"><div class="quota-title"><span>${name}</span><strong>${valid?`${percent(pct)} usado · ${percent(100-pct)} restante`:expired?'Registro expirado':'Não informado'}</strong></div><div class="meter"><div style="width:${pct}%;background:${pct>80?'#dbab71':'linear-gradient(90deg,#49869c,#62d6b8)'}"></div></div><div class="quota-note">Reinício informado: ${escapeHtml(Number.isFinite(reset)?dt(new Date(reset).toISOString()):end)} · ${Number.isFinite(age)?`Registro há ${Math.max(0,Math.floor(age))} min${age>15?' · antigo':''}`:'Data indisponível'}${valid&&pct>=80?' · Atenção: limite próximo':''}</div></div>`;
 }).join(''):empty('Sem informação das janelas.');
}
function bucketize(rows,by){
 const groups=new Map();
 for(const c of rows){
  const id=by==='prompt'?c.prompt_id:c.session_id;
  if(!groups.has(id)) groups.set(id,{id,session_id:c.session_id,project:c.project,prompt:c.prompt||'(prompt indisponível)',calls:0,models:new Set(),input:0,cached:0,fresh:0,output:0,reasoning:0,total:0,cost:0,unpriced:0,latest:c.timestamp});
  const p=groups.get(id);p.calls++;p.models.add(c.model);
  ['input','cached','fresh','output','reasoning','total'].forEach(k=>p[k]+=c[k]);
  if(c.cost==null)p.unpriced++;else p.cost+=c.cost;
  if(c.timestamp>p.latest)p.latest=c.timestamp;
 }
 return [...groups.values()].sort((a,b)=>(b.latest||'').localeCompare(a.latest||''));
}
function renderPrompts(rows){renderTable('prompts-table',bucketize(rows,'prompt'),'prompts',false)}
function renderCalls(rows){$('calls-count').textContent=number(rows.length)+' registros';renderTable('calls-table',rows.slice(0,state.page),'calls',true);$('more-calls').hidden=rows.length<=state.page;}
function renderSessions(rows){renderTable('sessions-table',bucketize(rows,'session'),'sessions',false);}
let displayed={};
function renderTable(id,rows,kind,full){
 displayed[id]=rows;
 const no=empty('Nenhum registro atende aos filtros.');
 if(!rows.length){$(id).innerHTML=no;return;}
 let cols=['DATA','PROJETO',kind==='calls'?'MODELO':kind==='prompts'?'PROMPT':'SESSÃO','CHAMADAS','TOKENS','CACHE','CUSTO API'];
 if(kind==='calls')cols=['DATA','PROJETO','MODELO','ENTRADA','CACHE','SAÍDA','TOTAL','CUSTO API'];
 const body=rows.map((r,i)=>{
  const project=`<strong>${escapeHtml(shortPath(r.project))}</strong><small title="${escapeHtml(r.project)}">${escapeHtml(r.session_id.slice(0,17))}</small>`;
  const cost=kind==='calls'?r.cost:r.unpriced?null:r.cost;
  if(kind==='calls')return `<tr class="clickable" data-idx="${i}"><td>${dt(r.timestamp)}</td><td>${project}</td><td>${safeModel(r.model)}<small>${escapeHtml(r.effort||'')}</small></td><td class="mono">${compact(r.input)}</td><td class="mono">${compact(r.cached)}</td><td class="mono">${compact(r.output)}</td><td class="mono"><strong>${compact(r.total)}</strong></td><td class="cost-cell">${dollar(cost)}</td></tr>`;
  const groupName=kind==='prompts'?(state.showPrompts?`<div class="cell-detail" title="${escapeHtml(r.prompt)}">${escapeHtml(r.prompt)}</div>`:`<strong>Prompt ${escapeHtml(r.id.split(':').pop().slice(0,17))}</strong><small>Texto oculto</small>`):`<strong>${escapeHtml(r.id.slice(0,24))}</strong>`;
  return `<tr class="clickable" data-idx="${i}"><td>${dt(r.latest)}</td><td>${project}</td><td>${groupName}</td><td>${number(r.calls)}</td><td><strong>${compact(r.total)}</strong></td><td>${percent(r.input?r.cached/r.input*100:0)}</td><td class="cost-cell">${dollar(cost)}</td></tr>`;
 }).join('');
 $(id).innerHTML=`<div class="table-wrap"><table>${headers(cols)}<tbody>${body}</tbody></table></div>`;
 $(id).querySelectorAll('tr.clickable').forEach(tr=>tr.addEventListener('click',()=>showDetails(displayed[id][Number(tr.dataset.idx)],kind)));
}
function detailsField(label,value){return `<div class="detail-card"><div class="detail-label">${label}</div><div class="detail-value">${escapeHtml(value)}</div></div>`;}
function showDetails(r,kind){
 const single=kind==='calls';const total=r.total,inp=r.input,out=r.output,cached=r.cached;
 $('drawer-title').textContent=single?'Chamada ao modelo':kind==='prompts'?'Grupo de prompt':'Sessão Codex';
 const parts=single && r.cost_breakdown?`<div class="detail-card"><div class="detail-label">DECOMPOSIÇÃO DO CUSTO</div><div class="detail-value">Entrada nova: ${dollar(r.cost_breakdown.fresh)}<br>Entrada em cache: ${dollar(r.cost_breakdown.cached)}<br>Saída: ${dollar(r.cost_breakdown.output)}<br>Economia pelo cache: ${dollar(r.cost_breakdown.saved_by_cache)}</div></div>`:'';
 const context=single?(r.context_window?`<div class="disclaimer">Contexto configurado da sessão: ${number(r.context_window)} tokens. Não representa ocupação exata do contexto no momento da chamada.</div>`:''):'<div class="disclaimer">O grupo reúne as chamadas associadas pelos IDs de turno ou pela proximidade cronológica do prompt. Pode não englobar subagentes executados em outras sessões.</div>';
 const cost=single?r.cost:r.unpriced?null:r.cost;
 $('drawer-body').innerHTML=`<div class="detail-label">CUSTO EQUIVALENTE POR API</div><div style="font-size:38px;color:#75e3c0;font-weight:750;letter-spacing:-1px;margin:4px 0 20px">${escapeHtml(dollar(cost))}</div>${detailsField('PROJETO',r.project)}${detailsField('MODELO / MODELOS',single?r.model:r.models.size?[...r.models].join(', '):r.models.join(', '))}${detailsField('IDENTIFICADOR',single?r.id:r.id)}${kind==='prompts'||single&&r.prompt?detailsField('PROMPT ASSOCIADO',state.showPrompts?r.prompt||'Não identificado':'Oculto. Ative "Exibir texto dos prompts" na aba Prompts.'):''}<div class="detail-grid"><div class="detail-card"><div class="detail-label">ENTRADA</div><strong>${number(inp)}</strong></div><div class="detail-card"><div class="detail-label">EM CACHE</div><strong>${number(cached)}</strong></div><div class="detail-card"><div class="detail-label">SAÍDA</div><strong>${number(out)}</strong></div><div class="detail-card"><div class="detail-label">RACIOCÍNIO</div><strong>${number(r.reasoning)}</strong></div><div class="detail-card"><div class="detail-label">TOTAL</div><strong>${number(total)}</strong></div><div class="detail-card"><div class="detail-label">CACHE HIT</div><strong>${percent(inp?cached/inp*100:0)}</strong></div></div>${single?detailsField('DATA/HORA',dt(r.timestamp)):detailsField('CHAMADAS NO GRUPO',r.calls)}${parts}${context}<p class="disclaimer">Valores em USD estimados com as tarifas definidas em <code>pricing.json</code>. Tokens de cache fazem parte da entrada e tokens de raciocínio fazem parte da saída. Não é cobrança real nem inclui taxas de ferramentas.</p>`;
 $('overlay').hidden=false;$('drawer').hidden=false;$('close-drawer').focus();
}
function closeDetails(){$('overlay').hidden=true;$('drawer').hidden=true;}
document.querySelectorAll('.nav-link').forEach(button=>button.addEventListener('click',()=>setView(button.dataset.view)));
for(const id of ['period','project','model','search'])$(id).addEventListener(id==='search'?'input':'change',()=>{state.page=40;render();});
$('refresh').addEventListener('click',refresh);
$('clear').addEventListener('click',()=>{$('period').value='7';$('project').value='';$('model').value='';$('search').value='';render();});
$('go-calls').addEventListener('click',()=>setView('calls'));
$('show-prompts').addEventListener('change',e=>{state.showPrompts=e.target.checked;render();});
$('more-calls').addEventListener('click',()=>{state.page+=40;render();});
$('overlay').addEventListener('click',closeDetails);$('close-drawer').addEventListener('click',closeDetails);
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeDetails();});
refresh();setInterval(refresh,12000);
