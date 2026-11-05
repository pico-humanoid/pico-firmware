'use strict';
const $ = id => document.getElementById(id);
const labels = {build:'编译固件',flash:'烧录开发板',board:'开发板日志',usbcan:'USB-CAN 测试',manual:'人工实验记录'};
const statusNames = {running:'进行中',pass:'通过',fail:'未通过',error:'操作异常',cancelled:'已停止',recorded:'已记录 / 待验收'};
let token='', state=null, selectedJob='', lastSequence=0, sourceInfo=null, dirty=false, mode=localStorage.getItem('pico-mode')||'Loopback', polling=false;
function selectedProfile(){return state&&state.profiles.find(p=>p.id===mode)}
const latest = kind => state && [...state.jobs].reverse().find(j=>j.kind===kind && j.mode===mode);
function node(tag,text,cls){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el}
function toast(message){$('toast').textContent=message;$('toast').style.display='block';clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').style.display='none',6500)}
async function api(path,body){
 const options=body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Pico-Token':token},body:JSON.stringify(body)};
 const response=await fetch(path,options);const data=await response.json();if(!response.ok)throw Error(data.error||'操作未完成');return data;
}
function switchView(name){
 document.querySelectorAll('.view').forEach(e=>e.classList.toggle('active',e.id===name));
 document.querySelectorAll('.nav').forEach(e=>e.classList.toggle('active',e.dataset.view===name));
 $('page-name').textContent={desk:'开发工作台',code:'代码工作区',history:'实验记录',wiring:'接线与流程',environment:'环境检查',profiles:'实验配置',firmware:'固件新功能'}[name];
 if(name==='profiles')renderProfiles();
 if(name==='firmware')loadFirmware().catch(e=>toast(e.message));
 if(name==='wiring')loadWiring().catch(e=>toast(e.message));
 if(name==='history')loadHistory().catch(e=>toast(e.message));
 if(name==='code'&&!sourceInfo)loadSources().catch(e=>toast(e.message));
}
document.querySelectorAll('.nav').forEach(b=>b.addEventListener('click',()=>switchView(b.dataset.view)));
function portOptions(id,kind){
 const select=$(id), old=select.value;
 const signature=JSON.stringify(state.ports);
 if(select.dataset.signature===signature)return;
 select.dataset.signature=signature;select.replaceChildren(node('option','选择串口…'));select.firstChild.value='';
 const sorted=[...state.ports].sort((a,b)=>(a.kind===kind?-1:1)-(b.kind===kind?-1:1));
 sorted.forEach(p=>{const opt=node('option',p.device+' · '+p.name);opt.value=p.device;select.append(opt)});
 if(state.ports.some(p=>p.device===old))select.value=old;
 else{const matches=state.ports.filter(p=>p.kind===kind);if(matches.length===1)select.value=matches[0].device}
}
function setPortTags(){
 for(const [select,tag] of [['board-port','board-tag'],['can-port','can-tag']]){
  const value=$(select).value;$(tag).textContent=value?'已选择':'未连接';$(tag).classList.toggle('connected',!!value);
 }
}
function paint(){
 syncProfiles();const base=selectedProfile().base_mode;
 const rate=selectedProfile().cmake_options.PICO_DEVICE_BITRATE;
 document.querySelector('.outline-badge').textContent=base==='Device'?'经典 CAN · 设备只读':base==='Custom'?'自定义实验 · 按工程配置':'经典 CAN · 标准帧';
 document.querySelector('.side-device .chip:last-child').textContent=rate?String(Number(rate)/1000)+' Kbps':base==='Custom'?'按工程配置':'1 Mbps';
 $('mode-note').textContent=selectedProfile().description;
 $('external-panel').classList.toggle('hidden',base!=='External');
 $('telemetry-panel').classList.toggle('hidden',!['Device','Custom'].includes(base));
 $('os-name').textContent=state.environment.os;portOptions('board-port','board');portOptions('can-port','usbcan');setPortTags();
 const active=state.jobs.filter(j=>j.status==='running'), exclusive=active.some(j=>j.kind==='build'||j.kind==='flash');
 $('mode').disabled=active.length>0;
 $('manage-profiles').disabled=active.length>0;
 $('build-btn').disabled=active.length>0;
 $('flash-btn').disabled=active.length>0||!state.environment.tools.programmer;
 $('board-btn').disabled=exclusive||active.some(j=>j.kind==='board')||!$('board-port').value;
 $('board-port').disabled=active.some(j=>j.kind==='board');$('can-port').disabled=active.some(j=>j.kind==='usbcan');
 $('can-btn').disabled=base!=='External'||exclusive||active.some(j=>j.kind==='usbcan')||!active.some(j=>j.kind==='board'&&j.mode===mode&&j.phase==='等待开发板 RESET / 测试数据')||!$('can-port').value||$('can-port').value===$('board-port').value;
 for(const k of ['build','flash','board']){const job=latest(k);$(k+'-state').textContent=job?job.phase:'等待开始';}
 const board=latest('board'),lastCan=latest('usbcan');
 const can=board&&lastCan&&lastCan.board_job===board.id?lastCan:null;
 $('metric-tx').replaceChildren(document.createTextNode(String(board?board.metrics.tx:0)),node('small',['Loopback','External'].includes(base)?' / 100':' 帧'));
 $('metric-done').replaceChildren(document.createTextNode(String(board?board.metrics.done:0)),node('small',['Loopback','External'].includes(base)?' / 100':' 帧'));
 $('metric-rx').replaceChildren(document.createTextNode(String(board?board.metrics.rx:0)),node('small',['Loopback','External'].includes(base)?' / 100':' 帧'));
 let verdict='尚未测试',cls='';
 if(board){
  if(base==='Loopback'){verdict=board.status==='pass'?'验收通过':board.status==='running'?'等待结果':board.status==='cancelled'?'未验收':'未通过';cls=board.status==='pass'?'pass':board.status==='running'?'':'fail';}
  else if(base==='External'){verdict='等待两端结果';if(can&&can.board_job===board.id&&board.status==='pass'&&can.status==='pass'){verdict='两端验收通过';cls='pass'}else if([board,can].some(j=>j&&['fail','error','cancelled'].includes(j.status))){verdict='未完成验收';cls='fail'}}
 }
 if(board&&['Custom','Device'].includes(base)){verdict=board.status==='running'?'正在采集':board.status==='error'?'采集异常':'待人工验收';cls=board.status==='error'?'fail':''}
 paintTelemetry(board);
 $('verdict').textContent=verdict;$('verdict').className='verdict '+cls;
 let guidance=base==='External'?'先烧录 External；打开板端日志并按 RESET 后，点击「发送 100 帧并检查返回」。':'从「编译当前配置」开始。已编译且代码未修改时，可以直接烧录。';
 if(board&&board.status==='running')guidance='开发板日志已打开后，请按板上 RESET。'+(base==='External'?'然后点击发送 100 帧；接收第一帧前开发板会等待。':'测试约 15 秒后完成。');
 if(['Device','Custom'].includes(base))guidance='此配置采集独立设备日志。按 RESET 后观察原始数据与健康统计；记录人工结论，不使用旧 100 帧 PASS 判据。';
 if(active.some(j=>j.kind==='flash'))guidance='正在写入和校验，请等待完成。';
 if(verdict.includes('验收通过'))guidance='本次测试通过。原始数据与复核结果已保存，可在「实验记录」中下载。';
 $('guidance').textContent=guidance;
 const signature=state.jobs.map(j=>j.id).join();
 if($('job-select').dataset.signature!==signature){
  $('job-select').dataset.signature=signature;$('job-select').replaceChildren();
  [...state.jobs].reverse().forEach(j=>{const opt=node('option',labels[j.kind]+' · '+j.started.slice(11));opt.value=j.id;$('job-select').append(opt)});
  if(selectedJob)$('job-select').value=selectedJob;
 }
 if(selectedJob&&!state.jobs.some(j=>j.id===selectedJob)){selectedJob='';lastSequence=0;$('console').textContent='本地服务已重新连接。历史结果请查看实验记录。';}
 if(!selectedJob&&state.jobs.length)selectJob(state.jobs[state.jobs.length-1].id);
 const selected=state.jobs.find(j=>j.id===selectedJob);
 $('stop-btn').disabled=!selected||selected.status!=='running'||selected.kind==='flash';
 $('console-status').textContent=selected?labels[selected.kind]+' · '+selected.phase:'所有输出来自实际工具和设备';
 paintEnvironment();
}
function paintEnvironment(){
 const host=$('environment-list');host.replaceChildren();
 const entries=[['操作系统',state.environment.os,true],['工程目录',state.environment.project,true]];
 Object.entries(state.environment.tools).forEach(([name,path])=>entries.push([name,path||'未找到，请检查本机安装或工具路径',!!path]));
 Object.entries(state.environment.firmware).forEach(([name,fw])=>entries.push([name+' 固件',fw.path,fw.exists]));
 entries.forEach(([name,path,ok])=>{const row=node('div',undefined,'environment-row');row.append(node('strong',name),node('code',path),node('span',ok?'已就绪':'待准备','result-badge '+(ok?'pass':'')));host.append(row)});
}
function selectJob(id){selectedJob=id;lastSequence=0;$('job-select').value=id;$('console').textContent='';$('frames').replaceChildren()}
async function refresh(){
 state=await api('/api/state');token=state.token;paint();
 $('connection-dot').style.background='#2aa678';$('connection-text').textContent='本机服务已连接';
 if(selectedJob){
  const job=await api('/api/job?id='+encodeURIComponent(selectedJob)+'&after='+lastSequence);
  if(job.id!==selectedJob)return;
  const nearEnd=$('console').scrollHeight-$('console').scrollTop-$('console').clientHeight<60;
  if(job.lines.length){$('console').textContent+=job.lines.map(x=>x.text).join('\n')+'\n';if($('console').textContent.length>250000)$('console').textContent=$('console').textContent.slice(-200000)}
  lastSequence=job.sequence;$('console-count').textContent=lastSequence+' lines';if(nearEnd)$('console').scrollTop=$('console').scrollHeight;paintFrames(job.frames);
 }
}
function paintFrames(frames){
 const host=$('frames'),filter=$('frame-filter').value;host.replaceChildren();
 const visible=frames.filter(f=>filter==='all'||(filter==='TX'?f.event.startsWith('TX'):f.event.startsWith('RX'))).slice(-180);
 if(!visible.length){const row=node('tr');const cell=node('td','尚无 CAN 报文。编译和烧录输出见左侧控制台。','empty');cell.colSpan=4;row.append(cell);host.append(row);return}
 for(const f of visible){const row=node('tr');const event=node('td');event.append(node('span',f.event,f.event.startsWith('RX')?'rx':'tx'));row.append(node('td',String(f.ms)),event,node('td',f.id),node('td',f.data));host.append(row)}
}
async function start(kind){
 try{
  if(dirty)throw Error('代码尚未保存。请先在代码工作区保存，再编译或测试。');
  const port=kind==='board'?$('board-port').value:kind==='usbcan'?$('can-port').value:'';
  const job=await api('/api/start',{kind,mode,port});selectJob(job.id);toast(labels[kind]+'已启动');await refresh();
 }catch(e){toast(e.message)}
}
for(const [id,kind] of [['build-btn','build'],['flash-btn','flash'],['board-btn','board'],['can-btn','usbcan']])$(id).addEventListener('click',()=>start(kind));
$('stop-btn').addEventListener('click',async()=>{try{await api('/api/stop',{id:selectedJob});toast('正在停止任务并释放设备')}catch(e){toast(e.message)}});
$('job-select').addEventListener('change',()=>{selectJob($('job-select').value);refresh().catch(e=>toast(e.message))});
$('mode').addEventListener('change',()=>{
 if(dirty){$('mode').value=mode;toast('请先保存当前代码，再切换实验配置。');return}
 mode=$('mode').value;sourceInfo=null;localStorage.setItem('pico-mode',mode);$('external-panel').classList.toggle('hidden',mode!=='External');
 $('mode-note').textContent=mode==='External'?'使用真实 CAN 总线，自动发送测试序列，独立核对两端结果。':'验证 FDCAN 控制器、接收中断与测试记录。无需外部 CAN 接线。';
 if(state)paint();
});
['board-port','can-port'].forEach(id=>$(id).addEventListener('change',()=>state&&paint()));
$('frame-filter').addEventListener('change',()=>refresh().catch(e=>toast(e.message)));
$('refresh').addEventListener('click',()=>refresh().then(()=>toast('设备列表已更新')).catch(e=>toast(e.message)));
async function loadSource(name,discard=false){
 if(dirty&&!discard){toast('当前代码尚未保存，请先保存；需要放弃时点击「重新载入」。');return}
 sourceInfo=await api('/api/source?mode='+encodeURIComponent(mode)+'&name='+encodeURIComponent(name));dirty=false;
 $('source').value=sourceInfo.text;$('source').readOnly=!sourceInfo.editable;$('file-name').textContent=name;
 $('file-state').textContent=sourceInfo.editable?'可编辑 · 已保存':'生成文件 · 只读';$('file-state').className='';$('save-source').disabled=!sourceInfo.editable;
 document.querySelectorAll('[data-file]').forEach(b=>b.classList.toggle('selected',b.dataset.file===name));
}
document.querySelectorAll('[data-file]').forEach(b=>b.addEventListener('click',()=>loadSource(b.dataset.file).catch(e=>toast(e.message))));
$('source').addEventListener('input',()=>{dirty=true;$('file-state').textContent='有未保存修改';$('file-state').className='dirty'});
$('source').addEventListener('keydown',e=>{if(e.key==='Tab'&&!$('source').readOnly){e.preventDefault();const el=$('source');el.setRangeText('    ',el.selectionStart,el.selectionEnd,'end');el.dispatchEvent(new Event('input'))}});
$('save-source').addEventListener('click',async()=>{
 try{const saved=await api('/api/source',{mode:sourceInfo.mode,name:sourceInfo.name,text:$('source').value,revision:sourceInfo.revision});sourceInfo.revision=saved.revision;dirty=false;$('file-state').textContent='已保存 · 请重新编译';$('file-state').className='';toast('代码已保存，原文件已备份。回到工作台重新编译。')}catch(e){toast(e.message)}
});
$('reload-source').addEventListener('click',()=>{
 if(dirty&&!window.confirm('放弃当前未保存的修改，重新读取磁盘文件？'))return;
 loadSource(sourceInfo?sourceInfo.name:'App/can_bringup.c',true).catch(e=>toast(e.message));
});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue=''}});
let historyRecords=[];
async function loadHistory(){
 const [history,files]=await Promise.all([api('/api/history?archived='+($('show-archived').checked?'1':'0')),api('/api/files')]);historyRecords=history;const host=$('history-list');host.replaceChildren();
 if(!history.length)host.append(node('div','还没有实验记录。完成任务或新建记录后，内容会保存在这里。','history-empty'));
 const conclusions={pending:'待评估',pass:'通过',fail:'未通过',incomplete:'条件不足 / 未完成'};
 history.forEach(j=>{const row=node('article',undefined,'history-row'),left=node('div'),right=node('div',undefined,'downloads'),ann=j.annotation||{};
  left.append(node('strong',ann.title||((labels[j.kind]||j.kind)+' · '+(j.profile_name||j.mode))),node('p',j.started.replace('T',' ')+'　'+(j.port||'本机记录')+'　'+j.phase));
  if(ann.purpose)left.append(node('p','目的：'+ann.purpose));
  if(ann.notes)left.append(node('p','备注：'+ann.notes));
  if(ann.participants||ann.hardware)left.append(node('p',[ann.participants,ann.hardware].filter(Boolean).join(' / ')));
  right.append(node('span','自动记录：'+(statusNames[j.status]||j.status),'result-badge '+j.status));
  if(ann.conclusion)right.append(node('span','人工结论：'+conclusions[ann.conclusion],'result-badge'));
  (j.files||[]).forEach(name=>{const a=node('a',name.endsWith('.csv')?'下载 CSV':'复核报告');a.href='/download/'+encodeURIComponent(name);right.append(a)});
  const edit=node('button','编辑记录','plain');edit.addEventListener('click',()=>editRecord(j));right.append(edit);
  const archive=node('button',ann.archived?'恢复记录':'归档','plain');archive.addEventListener('click',async()=>{try{await api('/api/record',{id:j.id,archived:!ann.archived});await loadHistory()}catch(e){toast(e.message)}});right.append(archive);
  row.append(left,right);host.append(row)
 });
 $('file-downloads').replaceChildren();
 files.forEach(file=>{const row=node('div',undefined,'download-line'),a=node('a',file.name);a.href='/download/'+encodeURIComponent(file.name);row.append(a,node('span',Math.ceil(file.bytes/1024)+' KB'));$('file-downloads').append(row)});
}
$('shutdown').addEventListener('click',async()=>{try{await api('/api/shutdown',{});toast('本地服务已关闭。下次双击开发控制台入口即可重新打开。')}catch(e){toast(e.message)}});
async function tick(){if(polling)return;polling=true;try{await refresh()}catch(e){$('connection-dot').style.background='#dca766';$('connection-text').textContent='服务未连接';}finally{polling=false}}
function syncProfiles(){
 if(!state.profiles.some(p=>p.id===mode))mode='Loopback';
 const sig=JSON.stringify(state.profiles);
 if($('mode').dataset.signature!==sig){
  $('mode').dataset.signature=sig;$('mode').replaceChildren();$('record-mode').replaceChildren();
  state.profiles.forEach(p=>{for(const id of ['mode','record-mode']){const o=node('option',p.name);o.value=p.id;$(id).append(o)}});
  $('mode').value=mode;
 }
}
function renderProfiles(){
 if(!state)return;const host=$('profile-list');host.replaceChildren();
 state.profiles.forEach(p=>{
  const row=node('article',undefined,'history-row'),left=node('div'),right=node('div');
  left.append(node('strong',p.name),node('p',p.description),node('code',p.project_dir));
  const use=node('button','选择此配置','plain');use.addEventListener('click',()=>useProfile(p.id));right.append(use);
  const copy=node('button','复制','plain');copy.addEventListener('click',()=>editProfile({...p,id:'',name:p.name+' · 副本',builtin:false}));right.append(copy);
  if(!p.builtin){
   const edit=node('button','编辑','plain');edit.addEventListener('click',()=>editProfile(p));right.append(edit);
   const remove=node('button','删除配置','plain');remove.addEventListener('click',async()=>{if(!confirm('删除此配置？已保存的实验记录和固件不会删除。'))return;try{await api('/api/profiles',{id:p.id,delete:true});await refresh();renderProfiles()}catch(e){toast(e.message)}});right.append(remove)
  }else right.append(node('span','内置基线','result-badge'));
  row.append(left,right);host.append(row)
 });
}
function useProfile(id){
 if(dirty){toast('请先保存当前代码。');return}
 if(state.jobs.some(j=>j.status==='running')){toast('请先结束当前任务。');return}
 mode=id;sourceInfo=null;$('mode').value=id;localStorage.setItem('pico-mode',mode);paint();switchView('desk');
}
function editProfile(p){
 p=p||{id:'',name:'',base_mode:'Custom',project_dir:state.environment.project,build_type:'Debug',elf_name:'PICO_CAN.elf',toolchain:'cmake/gcc-arm-none-eabi.cmake',board_baud:115200,capture_seconds:80,description:'',cmake_options:{}};
 const mapping={id:'id',name:'name',base:'base_mode',project:'project_dir',build:'build_type',elf:'elf_name',toolchain:'toolchain',baud:'board_baud',seconds:'capture_seconds',description:'description'};
 for(const [field,key] of Object.entries(mapping))$('profile-'+field).value=p[key]===undefined?(field==='seconds'?80:''):p[key];
 $('profile-options').value=JSON.stringify(p.cmake_options||{},null,2);
 $('profile-form-title').textContent=p.id?'编辑实验配置':'新增实验配置';$('profile-form').classList.remove('hidden');$('profile-form').scrollIntoView({behavior:'smooth',block:'start'});
}
$('manage-profiles').addEventListener('click',()=>{switchView('profiles');editProfile()});
$('new-profile').addEventListener('click',()=>editProfile());
$('close-profile').addEventListener('click',()=>$('profile-form').classList.add('hidden'));
$('profile-form').addEventListener('submit',async e=>{
 e.preventDefault();try{
  const p={id:$('profile-id').value,name:$('profile-name').value,base_mode:$('profile-base').value,
   project_dir:$('profile-project').value,build_type:$('profile-build').value,elf_name:$('profile-elf').value,
   toolchain:$('profile-toolchain').value,board_baud:Number($('profile-baud').value),
   capture_seconds:Number($('profile-seconds').value),description:$('profile-description').value,
   cmake_options:JSON.parse($('profile-options').value)};
  const saved=await api('/api/profiles',p);await refresh();renderProfiles();$('profile-form').classList.add('hidden');toast('实验配置已保存，可选择、编译并打开对应项目。');
 }catch(err){toast(err.message)}
});
document.querySelectorAll('[data-open]').forEach(b=>b.addEventListener('click',async()=>{
 try{await api('/api/open',{app:b.dataset.open,mode});toast('已启动 '+(b.dataset.open==='cubemx'?'CubeMX':'VS Code')+'，打开当前实验对应项目。')}catch(e){toast(e.message)}
}));
async function loadSources(){
 const sources=await api('/api/sources?mode='+encodeURIComponent(mode));
 const host=document.querySelector('.file-list');host.replaceChildren(node('strong','当前实验项目'));
 for(const name of Object.keys(sources)){const b=node('button',name);b.dataset.file=name;b.addEventListener('click',()=>loadSource(name).catch(e=>toast(e.message)));host.append(b)}
 const names=Object.keys(sources);if(names.length)await loadSource(names.includes('App/can_bringup.c')?'App/can_bringup.c':names[0]);
}
function editRecord(j){
 const a=j?j.annotation||{}:{};
 $('record-id').value=j?j.id:'';$('record-title').value=a.title||(j?(labels[j.kind]||'实验')+' · '+(j.profile_name||j.mode):'');
 $('record-mode').value=j?j.mode:mode;$('record-mode').disabled=!!j;
 for(const key of ['purpose','participants','hardware','notes'])$('record-'+key).value=a[key]||'';
 $('record-conclusion').value=a.conclusion||'pending';$('record-form').classList.remove('hidden');$('record-form').scrollIntoView({behavior:'smooth',block:'start'});
}
$('new-record').addEventListener('click',()=>editRecord(null));
$('close-record').addEventListener('click',()=>$('record-form').classList.add('hidden'));
$('show-archived').addEventListener('change',()=>loadHistory().catch(e=>toast(e.message)));
$('record-form').addEventListener('submit',async e=>{
 e.preventDefault();try{
  const data={id:$('record-id').value,mode:$('record-mode').value,conclusion:$('record-conclusion').value};
  for(const key of ['title','purpose','participants','hardware','notes'])data[key]=$('record-'+key).value;
  await api('/api/record',data);$('record-form').classList.add('hidden');await loadHistory();toast('实验记录已保存，原始自动记录和日志保留。');
 }catch(err){toast(err.message)}
});
function paintTelemetry(job){
 const host=$('telemetry');host.replaceChildren();
 if(!job||!job.telemetry){host.append(node('p','采集开始后显示 BMS / POWER 解析值及 HEALTH。'));return}
 const t=job.telemetry;
 for(const [name,fields] of Object.entries({...{HEALTH:t.health},...t.devices,...t.values})){
  const box=node('article',undefined,'telemetry-group');box.append(node('strong',name));
  const table=node('table');for(const [key,val] of Object.entries(fields||{})){const tr=node('tr');tr.append(node('td',key),node('td',typeof val==='object'?JSON.stringify(val):String(val)));table.append(tr)}box.append(table);host.append(box)
 }
}
async function loadWiring(){
 const data=await api('/api/wiring');const source=$('wiring-source');source.replaceChildren(node('strong','资料版本 '+data.updated+'　'),node('span',data.note));
 const a=node('a','查看 GitHub 电气依据');a.href=data.source;a.target='_blank';a.rel='noopener';source.append(a);
 const host=$('wiring-channels');host.replaceChildren();
 data.channels.forEach(c=>{
  const card=node('article',undefined,'panel guide-card');card.append(node('h2',c.name+' · '+c.ports),node('p',c.ic));
  const flow=node('div',undefined,'channel-flow');flow.append(node('span','G474'),node('span','→ '+c.ic.split(' · ')[0]+' →'),node('span',c.ports));card.append(flow);
  const table=node('table');for(const [key,val] of [['TX',c.tx],['RX',c.rx],['终端',c.termination],['TVS',c.tvs]]){const tr=node('tr');tr.append(node('th',key),node('td',val));table.append(tr)}card.append(table,node('p',c.purpose));host.append(card)
 });
 $('wiring-details').replaceChildren();
 data.details.forEach(d=>{const card=node('article',undefined,'panel guide-card');card.append(node('h2',d.title));const table=node('table');d.rows.forEach(([key,val])=>{const tr=node('tr');tr.append(node('th',key),node('td',val));table.append(tr)});card.append(table);$('wiring-details').append(card)});
}
async function loadFirmware(){
 const data=await api('/api/firmware');$('firmware-revision').textContent='源码快照 '+data.updated+' · '+data.commit.slice(0,12)+' · 已独立导入，原验证工程保留。';
 $('firmware-features').replaceChildren();
 data.features.forEach(f=>{const card=node('article',undefined,'panel guide-card feature-card');card.append(node('h2',f.name),node('p',f.description),node('p',f.status,'feature-status'));const choose=node('button','选择此读取配置 →','small-primary');choose.addEventListener('click',()=>useProfile(f.id));card.append(choose);$('firmware-features').append(card)});
 $('firmware-boundaries').replaceChildren(node('h2','当前能力与验收边界'));data.boundaries.forEach(text=>$('firmware-boundaries').append(node('p',text)));
 $('firmware-documents').replaceChildren(node('h2','仓库说明与操作依据'));
 data.documents.forEach(doc=>{const row=node('p');const a=node('a',doc.title+'（本地文档）');a.href='/reference/'+doc.local;a.target='_blank';const original=node('a',' GitHub 原文 ↗');original.href=doc.url;original.target='_blank';original.rel='noopener';row.append(a,original);$('firmware-documents').append(row)});
}
tick();setInterval(tick,900);
