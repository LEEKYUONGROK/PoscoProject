'use strict';
const $ = id => document.getElementById(id);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon = name => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const labels = {REPORT_PENDING:'생성 대기',REPORT_GENERATED:'생성 완료',REPORT_FAILED:'생성 실패',REVIEW_REQUIRED:'검토 필요',REVIEWED:'검토 완료',INSPECTION_COMPLETE:'검사 수신'};
const tones = {REPORT_PENDING:'info',REPORT_GENERATED:'success',REPORT_FAILED:'danger',REVIEW_REQUIRED:'warning',REVIEWED:'success'};
const eventNames = {fire:'화재 감지',vision:'비전 검사',other:'센서 이벤트'};
const badge = (label,tone='muted') => `<span class="badge ${tone}">${escapeHTML(label)}</span>`;
const number = value => Number(value).toLocaleString('ko-KR');
const date = value => value ? new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(value)) : '수신 이력 없음';
const state = {view:'reports',sensor:'',page:1,eventPage:1,pages:1,eventPages:1,batch:'',batchBusy:false,selected:null,detail:null,tab:'report',items:[],epoch:0,detailEpoch:0,creating:false};
let toastTimer, searchTimer;

async function api(path,body){
 const response=await fetch(path,{headers:body?{'Content-Type':'application/json'}:{},method:body?'POST':'GET',body:body?JSON.stringify(body):undefined});
 const result=await response.json();
 if(!response.ok)throw new Error(result.error || '데이터 요청을 처리하지 못했습니다.');
 return result;
}
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>{$('toast').hidden=true;},4500);}
function error(message){$('error-text').textContent=message;$('error-banner').hidden=false;}
function filters(page=state.page){
 const q=new URLSearchParams({page:String(page),size:'12'});
 for(const [key,id] of [['from','date-from'],['to','date-to'],['status','status-filter'],['sensor','sensor-filter'],['event','event-filter'],['q','search']])if($(id).value)q.set(key,$(id).value);
 if(state.batch)q.set('batch',state.batch);
 return q;
}
function resetFilters(){for(const id of ['date-from','date-to','status-filter','event-filter','search'])$(id).value='';state.page=1;state.eventPage=1;}
function setSensor(sensor){state.sensor=sensor;$('sensor-filter').value=sensor;document.querySelectorAll('[data-sensor]').forEach(b=>b.classList.toggle('active',b.dataset.sensor===sensor));state.page=1;state.eventPage=1;loadBatches();refresh();}
function setView(view){
 state.view=view;state.page=1;state.eventPage=1;
 const reports=view==='reports';
 $('reports-view').hidden=!reports;$('monitor-view').hidden=reports;$('summary-grid').hidden=!reports;$('status-filter-group').hidden=!reports;$('sensor-cards').hidden=view!=='monitor';
 const titles={reports:['AI REPORT CENTER','AI 보고서 대시보드','현장의 데이터를 읽고, 더 명확한 판단으로 연결하세요.','AI 보고서'],monitor:['LIVE OPERATIONS','실시간 센서 모니터링','화재 감지와 비전 불량 검사, 서로 다른 신호를 한눈에 확인하세요.','실시간 모니터링'],events:['EVENT EXPLORER','통합 이벤트 이력','장치가 보고한 이벤트를 수신 순서와 원문으로 확인하세요.','이벤트 이력']};
 const t=titles[view];$('eyebrow').textContent=t[0];$('page-title').textContent=t[1];$('page-subtitle').textContent=t[2];$('breadcrumb-title').textContent=t[3];
 document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view));$('sidebar').classList.remove('open');refresh();
}
async function refresh(){
 const epoch=++state.epoch;
 $('refresh').disabled=true;
 try{
  const queries=filters();const eventsQuery=filters(state.eventPage);eventsQuery.delete('batch');eventsQuery.delete('status');
  const [reports,monitor]=await Promise.all([api('/api/reports?'+queries),api('/api/monitoring?'+eventsQuery)]);
  if(epoch!==state.epoch)return;
  $('error-banner').hidden=true;
  for(const key of ['total','generated','pending','failed','review'])$('count-'+key).textContent=number(reports.counts[key]);
  state.page=reports.page;state.pages=reports.pages;state.items=reports.items;
  if(!state.batch&&state.selected&&!reports.items.some(r=>r.key===state.selected)){state.selected=null;state.detail=null;}
  renderList(reports);renderMonitoring(monitor);
  $('updated-at').textContent='최근 갱신 '+date(monitor.updated_at).split(' ').slice(-1).join(' ');
  if(state.selected)await selectReport(state.selected,true);
  else if(reports.items.length)await selectReport(reports.items[0].key);
  else{$('preview-content').hidden=true;$('preview-empty').hidden=false;$('preview-empty').textContent='조건에 맞는 보고서가 없습니다.';}
  if(state.batch)await updateBatchBanner();
 }catch(e){if(epoch===state.epoch)error(e.message);}
 finally{if(epoch===state.epoch)$('refresh').disabled=false;}
}
function renderList(result){
 $('list-count').textContent=number(result.total);$('list-description').textContent=state.batch?'고정한 목록의 첫 번째 보고서부터 표시합니다.':'최신 보고서부터 표시합니다.';
 const rows=$('report-rows');
 rows.innerHTML=result.items.length?result.items.map(r=>`<tr data-key="${escapeHTML(r.key)}" class="${state.selected===r.key?'selected':''}"><td><span class="report-number">${r.position?'#'+String(r.position).padStart(3,'0'):'RPT-'+(r.report_id?escapeHTML(r.report_id.slice(0,7).toUpperCase()):'대기')}<small>원본 기록 ${escapeHTML(r.record_seq??'미기록')}</small></span></td><td><span class="sensor-id">${escapeHTML(r.sensor_id||'—')}</span></td><td><span class="event-label">${icon(r.sensor_id==='302'?'fire':r.sensor_id==='305'?'camera':'pulse')}${escapeHTML(eventNames[r.event_type]||'센서 이벤트')}</span></td><td>${badge(r.queue_state==='running'?'생성 중':labels[r.status]||r.status,tones[r.status])}</td><td class="row-time">${escapeHTML(date(r.created_at))}</td><td><button class="row-open" aria-label="${escapeHTML(r.position?'보고서 '+r.position:r.report_id?.slice(0,7)||'대기 보고서')} 조회">조회</button></td></tr>`).join(''):'<tr><td colspan="6" class="table-empty">조건에 맞는 보고서가 없습니다.<br>필터를 변경하거나 최근 100개 보고서를 생성하세요.</td></tr>';
 rows.querySelectorAll('[data-key]').forEach(row=>{row.addEventListener('click',()=>selectReport(row.dataset.key));row.querySelector('button').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();selectReport(row.dataset.key);}});});
 $('pagination-label').textContent=result.total?`${number((result.page-1)*12+1)}–${number(Math.min(result.page*12,result.total))} / 총 ${number(result.total)}건`:'총 0건';
 $('page-prev').disabled=result.page<=1;$('page-next').disabled=result.page>=result.pages;
 const start=Math.max(1,Math.min(result.page-2,result.pages-4));
 $('page-numbers').innerHTML=Array.from({length:Math.min(5,result.pages)},(_,i)=>start+i).map(n=>`<button data-page="${n}" class="${n===result.page?'active':''}" aria-label="${n} 페이지" ${n===result.page?'aria-current="page"':''}>${n}</button>`).join('');
 document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>{state.page=Number(b.dataset.page);state.selected=null;refresh();});
}
async function selectReport(key,quiet=false){
 const epoch=++state.detailEpoch;
 if(!quiet){state.selected=key;state.tab='report';$('preview-empty').hidden=false;$('preview-content').hidden=true;$('preview-empty').innerHTML='<span class="spinner"></span><p>보고서를 불러오고 있습니다.</p>';}
 try{
  const detail=await api('/api/reports/'+encodeURIComponent(key));
  if(epoch!==state.detailEpoch)return;
  const same=state.detail?.key===detail.key;state.selected=detail.key;state.detail=detail;
  $('preview-empty').hidden=true;$('preview-content').hidden=false;
  document.querySelectorAll('#report-rows tr[data-key]').forEach(row=>row.classList.toggle('selected',row.dataset.key===detail.key));
  renderDetail(detail,same);
 }catch(e){if(epoch!==state.detailEpoch)return;if(!quiet){$('preview-empty').textContent=e.message;$('preview-empty').hidden=false;}else error(e.message);}
}
function renderDetail(d,preserve){
 const status=badge(labels[d.status]||'미기록',tones[d.status]);
 const validation=badge(d.auto_validation===true?'자동 검사 통과':d.auto_validation===false?'자동 검사 미통과':'미검증',d.auto_validation===true?'success':d.auto_validation===false?'warning':'muted');
 const meta=(label,value,full=false)=>`<div class="${full?'meta-full':''}"><span class="meta-label">${label}</span><span class="meta-value">${value}</span></div>`;
 $('report-meta').innerHTML=meta('보고서 번호',escapeHTML(d.report_id?'RPT-'+d.report_id.slice(0,12).toUpperCase():'생성 대기 · '+d.position))+meta('센서 ID',escapeHTML(d.sensor_id||'미제공')+(d.sensor_id==='302'?' · 화재 감지 센서':d.sensor_id==='305'?' · 비전 불량 검사':''))+meta('생성·요청 시간',escapeHTML(date(d.created_at)))+meta('이벤트 유형',escapeHTML(eventNames[d.event_type]||'센서 이벤트'))+meta('업무 상태',status)+meta('검증·검토 상태',`<span class="meta-status">${validation}${d.review_status==='REVIEWED'?badge('작업자 검토 완료','success'):badge('작업자 검토 대기')}</span>`);
 const method=d.details?.report_generation?.method||'';const qwen=method.startsWith('qwen_')&&Boolean(d.report_id);
 const steps=[['데이터 수신',d.log_text?'done':'','수신 기록'],['생성 대기',d.queue_state==='running'?'done':d.report_status==='REPORT_PENDING'?'running':'done','요청 상태'],['Qwen 생성',qwen?'done':d.report_status==='REPORT_FAILED'?'failed':d.queue_state==='running'?'running':'',qwen?'생성됨':d.queue_state==='running'?'진행 중':'미실행'],['자동 검사',d.auto_validation===true?'done':d.auto_validation===false?'failed':'',d.auto_validation===true?'통과':d.auto_validation===false?'미통과':'미검증'],['저장·검토',d.report_id?'done':'',d.review_status==='REVIEWED'?'검토 완료':d.report_id?'저장 · 검토 대기':'대기']];
 $('workflow').innerHTML=steps.map(([name,cls,sub],i)=>`<div class="workflow-step ${cls}"><span class="step-circle">${cls==='done'?'✓':cls==='failed'?'!':i+1}</span><span class="step-label">${name}</span><span class="step-label">${sub}</span></div>`).join('');
 $('preview-nav').hidden=!d.batch_id;
 if(d.batch_id){$('report-position').textContent=`${d.position} / ${d.batch_total}`;$('report-prev').disabled=!d.previous_key;$('report-next').disabled=!d.next_key;}
 $('download').disabled=!d.report;
 const needsRetention=d.report_id&&d.auto_validation!==true&&d.batch_id&&d.position;
 $('retention-panel').hidden=!needsRetention;
 if(needsRetention){document.querySelectorAll('[data-retention]').forEach(b=>b.classList.toggle('selected',b.dataset.retention===d.retention));$('retention-status').textContent=d.retention?'저장된 선택: '+(d.retention==='keep'?'유지':'유지하지 않음'):'';}
 renderTab(preserve);
}
function renderTab(preserve=false){
 const d=state.detail;if(!d)return;const body=$('tab-content');const scroll=preserve?body.scrollTop:0;
 document.querySelectorAll('[data-tab]').forEach(b=>{const on=b.dataset.tab===state.tab;b.classList.toggle('active',on);b.setAttribute('aria-selected',String(on));});
 if(state.tab==='report'){
  const warning=d.auto_validation===false?`<div class="warning-note">검증되지 않은 보고서입니다. ${escapeHTML(d.details.validation_error||'자동 검사를 통과하지 못했습니다.')}</div>`:d.auto_validation==null&&d.report?'<div class="status-note">이 저장본에는 자동 검사 결과가 없습니다. 미검증 보고서입니다.</div>':'';
  body.innerHTML=`<div class="doc-overline">QWEN · KOREAN REPORT</div><h3>${d.report_id?'센서 '+escapeHTML(d.sensor_id||'미제공')+' 분석 보고서':'보고서를 준비하고 있습니다'}</h3>${warning}`+(d.report?d.report.split(/\n\s*\n/).map(p=>`<p>${escapeHTML(p).replace(/\n/g,'<br>')}</p>`).join(''):`<p>${d.queue_state==='running'?'학습된 한국어 어댑터를 적용한 Qwen 모델이 보고서를 생성하고 있습니다.':'이 기록은 생성 대기 중입니다. 앞선 보고서부터 순서대로 처리합니다.'}</p><div class="status-note">목록과 원본 로그는 고정되어 있습니다. 생성이 끝나면 자동으로 표시됩니다.</div>`);
 }else if(state.tab==='analysis'){
  body.innerHTML='<h3>입력 로그</h3><pre>'+escapeHTML(d.log_text)+'</pre><h3>분석 결과 · 원문</h3><pre>'+escapeHTML(JSON.stringify({facts:d.details.facts||null,report_generation:d.details.report_generation||null,validation:d.details.validation||null},null,2))+'</pre>';
 }else{
  const units={temperature_c:'°C',humidity_pct:'%'};const names={temperature_c:'온도',humidity_pct:'습도',mq2:'MQ2',mq7:'MQ7',flame_detected:'불꽃 감지',fire_alarm:'화재 경보',danger_signal:'위험 신호',alarm_level:'경보 수준',person_detected:'사람 감지',dht_ok:'DHT 상태',inspection_result:'비전 검사 판정',timestamp:'장치 기록 시각',result:'수신 결과값'};
  body.innerHTML='<h3>실제 센서 데이터</h3><dl>'+Object.entries(d.values||{}).filter(([k])=>k!=='source_field').map(([k,v])=>'<dt>'+escapeHTML(names[k]||k)+'</dt><dd>'+escapeHTML(k==='inspection_result'?(v===0?'0 · 정상 (OK)':v===1?'1 · 불량 (NG)':'데이터 없음'):String(v)+(units[k]||''))+'</dd>').join('')+'</dl>'+(Object.keys(d.values||{}).length?'':'<p>현재 형식에서 해석된 측정값이 없습니다. 분석 정보 탭에서 원문을 확인하세요.</p>')+'<div class="status-note">장치의 측정·상태 보고입니다. 가스 센서의 물리 단위와 정상 임계값은 별도 정의가 없는 한 표시하지 않습니다.</div>';
 }
 body.scrollTop=scroll;
}
function renderMonitoring(result){
 state.eventPage=result.page;state.eventPages=result.pages;
 const received=result.worker.last_received;const online=received&&Date.now()-Date.parse(received)<result.stale_seconds*1000;
 $('connection').classList.toggle('online',Boolean(online));$('connection').innerHTML='<i></i>'+(online?'장비 데이터 수신 중':'최근 수신 신호 없음');
 const fire=result.sensors.find(s=>s.sensor_id==='302');const vision=result.sensors.find(s=>s.sensor_id==='305');
 const metric=(label,value,unit='')=>`<div><span>${label}</span><strong>${escapeHTML(value??'—')} <small>${unit}</small></strong></div>`;
 const sensorCard=(s,isFire)=>`<article class="panel sensor-card"><header><div class="sensor-card-title"><span class="summary-icon ${isFire?'red':'blue'}">${icon(isFire?'fire':'camera')}</span><div><h2>${isFire?'화재 감지 센서':'비전 불량 검사'}</h2><p>SENSOR ${s.sensor_id} · ${isFire?'FIRE & SAFETY':'VISION INSPECTION'}</p></div></div>${badge(s.fresh?'수신 중':'수신 지연',s.fresh?'success':'muted')}</header><div class="sensor-card-status ${s.tone}">${escapeHTML(s.label)}</div><div class="sensor-card-time">최근 수신 ${escapeHTML(date(s.received_at))}</div><div class="sensor-metrics">${isFire?metric('온도',s.values.temperature_c,'°C')+metric('습도',s.values.humidity_pct,'%')+metric('MQ2',s.values.mq2)+metric('MQ7',s.values.mq7):metric('정상 (OK)',number(s.ok_count),'건')+metric('불량 (NG)',number(s.ng_count),'건')+metric('수신 기록',number(s.total_received),'건')+metric('판정 기준','0 / 1','OK / NG')}</div><div class="sensor-card-bottom"><span>${isFire?'화재 경보 '+badge(s.alarm,s.alarm==='활성'?'danger':s.alarm==='비활성'?'success':'muted'):'마지막 수신 판정 '+badge(s.last_result,s.last_result==='정상 (OK)'?'success':s.last_result==='불량 (NG)'?'danger':'muted')}</span><button data-card-sensor="${s.sensor_id}">이 센서 이벤트 보기 →</button></div><div class="status-note">${isFire?'경보 수준: '+escapeHTML(s.alarm_level)+' · 불꽃 감지와 경보 활성 여부를 구분합니다.':`판정값 0은 정상, 1은 불량입니다. ${result.stale_seconds}초 이상 수신이 없으면 현재 상태는 데이터 없음으로 표시합니다.`}</div></article>`;
 $('sensor-cards').innerHTML=sensorCard(fire,true)+sensorCard(vision,false);
 document.querySelectorAll('[data-card-sensor]').forEach(b=>b.onclick=()=>{setSensor(b.dataset.cardSensor);setView('events');});
 $('events-count').textContent=number(result.total);
 $('event-rows').innerHTML=result.events.length?result.events.map(e=>`<tr><td><span class="report-number">EVT-${e.seq}</span></td><td class="row-time">${escapeHTML(date(e.received_at))}</td><td><span class="sensor-id">${escapeHTML(e.sensor_id)}</span></td><td><span class="event-label">${icon(e.sensor_id==='302'?'fire':e.sensor_id==='305'?'camera':'pulse')}${escapeHTML(e.event_type)}</span></td><td>${badge(e.label,e.tone)}</td><td><div class="event-raw" tabindex="0" role="button" aria-label="원본 로그 펼치기">${escapeHTML(e.log_text)}</div></td></tr>`).join(''):'<tr><td colspan="6" class="table-empty">조건에 맞는 수신 이벤트가 없습니다.</td></tr>';
 document.querySelectorAll('.event-raw').forEach(el=>{el.onclick=()=>el.classList.toggle('expanded');el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();el.click();}};});
 $('event-pagination-label').textContent=`총 ${number(result.total)}건 · 수신 시간 기준 최신순`;$('event-page').textContent=`${result.page} / ${result.pages}`;$('event-prev').disabled=result.page===1;$('event-next').disabled=result.page===result.pages;
}
async function loadBatches(){
 try{const result=await api('/api/batches?'+new URLSearchParams(state.sensor?{sensor:state.sensor}:{}));$('batch-history').innerHTML='<option value="">이전 생성 목록</option>'+result.items.map(b=>`<option value="${escapeHTML(b.id)}">${escapeHTML(date(b.created_at))} · ${escapeHTML(b.sensor_id||'전체')} · ${b.finished}/${b.total}</option>`).join('');$('batch-history').value=state.batch;}
 catch(e){error(e.message);}
}
async function openBatch(id,firstKey=null){
 state.batch=id;state.selected=null;resetFilters();state.sensor='';$('sensor-filter').value='';document.querySelectorAll('[data-sensor]').forEach(b=>b.classList.toggle('active',b.dataset.sensor===''));$('clear-batch').hidden=false;setView('reports');
 try{const batch=await api('/api/batches/'+id);if(batch.sensor_id)setSensor(batch.sensor_id);const first=batch.items[0];const key=firstKey||(first.report_id?'report:'+first.report_id:`batch:${id}:1`);await selectReport(key);await refresh();await loadBatches();}
 catch(e){error(e.message);}
}
async function updateBatchBanner(){const b=await api('/api/batches/'+state.batch);const finished=b.items.filter(i=>['complete','failed'].includes(i.state)).length;state.batchBusy=finished<b.items.length;$('batch-banner').hidden=false;$('batch-banner').innerHTML=`<span><strong>최근 ${b.items.length}개 보고서</strong> · 센서 ${escapeHTML(b.sensor_id||'전체')} · 요청 시점의 로그를 고정했습니다.</span><span>생성 ${finished} / ${b.items.length} · 첫 보고서부터 순서대로 검토</span>`;}

document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>setView(b.dataset.view));
document.querySelectorAll('[data-sensor]').forEach(b=>b.onclick=()=>{if(state.batch){state.batch='';state.selected=null;$('batch-banner').hidden=true;$('clear-batch').hidden=true;}setSensor(b.dataset.sensor);});
$('sensor-filter').onchange=()=>{if(state.batch){state.batch='';state.selected=null;$('batch-banner').hidden=true;$('clear-batch').hidden=true;}setSensor($('sensor-filter').value);};
for(const id of ['date-from','date-to','status-filter','event-filter'])$(id).onchange=()=>{state.page=1;state.eventPage=1;refresh();};
$('filters').onsubmit=e=>{e.preventDefault();clearTimeout(searchTimer);state.page=1;state.eventPage=1;refresh();};
$('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{state.page=1;state.eventPage=1;refresh();},350);};
$('reset-filters').onclick=()=>{resetFilters();refresh();};$('refresh').onclick=refresh;$('retry').onclick=refresh;
$('page-prev').onclick=()=>{state.page--;state.selected=null;refresh();};$('page-next').onclick=()=>{state.page++;state.selected=null;refresh();};
$('event-prev').onclick=()=>{state.eventPage--;refresh();};$('event-next').onclick=()=>{state.eventPage++;refresh();};
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{state.tab=b.dataset.tab;renderTab();});
async function navigateReport(direction){const key=state.detail?.[direction];if(!key)return;const batch=state.detail.batch_id;if(!state.batch){state.batch=batch;resetFilters();$('clear-batch').hidden=false;}await selectReport(key);state.page=Math.ceil(state.detail.position/12);refresh();}
$('report-prev').onclick=()=>navigateReport('previous_key');$('report-next').onclick=()=>navigateReport('next_key');
$('download').onclick=()=>{if(!state.detail?.report)return;const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([state.detail.report],{type:'text/plain;charset=utf-8'}));link.download=`vision4-sensor-${state.detail.sensor_id}-${state.detail.report_id}.txt`;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);};
document.querySelectorAll('[data-retention]').forEach(b=>b.onclick=async()=>{const d=state.detail;if(!d?.batch_id)return;b.disabled=true;try{await api('/api/retention',{batch_id:d.batch_id,position:d.position,report_id:d.report_id,decision:b.dataset.retention});d.retention=b.dataset.retention;renderDetail(d,true);toast('보고서 유지 선택을 저장했습니다.');}catch(e){error(e.message);}finally{b.disabled=false;}});
$('generate').onclick=()=>{if(state.batch&&state.batchBusy){toast('현재 묶음을 생성 중입니다. 완성된 첫 보고서부터 읽으세요.');return;}$('generate-description').textContent=`${state.sensor?'Sensor '+state.sensor:'전체 센서'}의 최근 수신 로그 최대 100개로 보고서를 생성합니다.`;$('generate-dialog').showModal();};
$('confirm-generate').onclick=async()=>{if(state.creating)return;state.creating=true;$('confirm-generate').disabled=true;try{const result=await api('/api/batches',{sensor:state.sensor||null});$('generate-dialog').close();await openBatch(result.id,result.first_key);toast(`${result.total}개 보고서 생성을 요청했습니다.`);}catch(e){error(e.message);$('generate-dialog').close();}finally{state.creating=false;$('confirm-generate').disabled=false;}};
$('batch-history').onchange=()=>{if($('batch-history').value)openBatch($('batch-history').value);};
$('clear-batch').onclick=()=>{state.batch='';state.selected=null;$('clear-batch').hidden=true;$('batch-banner').hidden=true;resetFilters();refresh();loadBatches();};
$('mobile-menu').onclick=()=>$('sidebar').classList.toggle('open');
setInterval(()=>{if($('auto-refresh').checked&&!document.hidden){refresh();loadBatches();}},5000);
loadBatches();refresh();
