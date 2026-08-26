const API = `${location.protocol}//${location.hostname}:8000/api/v1`;
let currentRunId = null, pollTimer = null, eventSource = null, generationReady = false, providerCatalog = {};
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const esc = (value='') => String(value).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const json = (value) => esc(JSON.stringify(value ?? {}, null, 2));

function toast(message){const el=$('#toast');el.textContent=message;el.classList.add('show');setTimeout(()=>el.classList.remove('show'),2600)}
function showView(name){$$('.view').forEach(v=>v.classList.remove('active'));$(`#${name}View`).classList.add('active');$$('.nav').forEach(n=>n.classList.toggle('active',n.dataset.view===name));if(name==='templates') loadCharacterTemplates();if(name==='runs') loadRuns();if(name==='settings') loadSystem();}
$$('.nav').forEach(button=>button.onclick=()=>showView(button.dataset.view));

const fileInput=$('#productImage'), drop=$('#dropZone');
function previewFile(file){if(!file)return;const reader=new FileReader();reader.onload=e=>{$('#preview').src=e.target.result;drop.classList.add('has-image')};reader.readAsDataURL(file)}
fileInput.onchange=()=>previewFile(fileInput.files[0]);
['dragenter','dragover'].forEach(name=>drop.addEventListener(name,e=>{e.preventDefault();drop.classList.add('drag')}));
['dragleave','drop'].forEach(name=>drop.addEventListener(name,e=>{e.preventDefault();drop.classList.remove('drag')}));
drop.addEventListener('drop',e=>{if(e.dataTransfer.files.length){fileInput.files=e.dataTransfer.files;previewFile(fileInput.files[0])}});

$('#uploadForm').onsubmit=async event=>{event.preventDefault();$('#formError').textContent='';if(!generationReady){$('#formError').textContent='真实生成服务尚未配置；请到“设置”选择服务商和模型，并保存 API Key。';return}const file=fileInput.files[0];if(!file)return;const data=new FormData();data.append('product_image',file);data.append('character_id','asian_girl_001');$('#generateButton').disabled=true;try{const response=await fetch(`${API}/generate`,{method:'POST',body:data});if(!response.ok)throw new Error((await response.json()).detail||'生成请求失败');const run=await response.json();currentRunId=run.run_id;updateProgress({progress:0,current_step:'任务已入队'});watchRun(run.run_id);toast('任务已提交，开始锁定人物、替换衣服并生成 18 秒视频')}catch(error){$('#formError').textContent=error.message;$('#generateButton').disabled=!generationReady}};

function updateProgress(run){const progress=run.progress||0;$('#progressValue').textContent=`${progress}%`;$('#progressBar').style.width=`${progress}%`;$('#currentStep').textContent=run.current_step||run.status;$$('#pipelineSteps li').forEach((li,index)=>{const min=Number(li.dataset.min);li.classList.toggle('done',progress>=(index===5?100:min+12));li.classList.toggle('active',progress>=min && progress<(index===5?100:min+12));li.querySelector('b').textContent=li.classList.contains('done')?'✓':li.classList.contains('active')?'●':'○'});if(run.status==='COMPLETED')showFinal(run);if(run.status==='FAILED'){$('#formError').textContent=run.error||'流水线失败';$('#generateButton').disabled=!generationReady}}
function watchRun(runId){clearInterval(pollTimer);if(eventSource)eventSource.close();eventSource=new EventSource(`${API}/runs/${runId}/events`);eventSource.addEventListener('progress',()=>fetchRun(runId));eventSource.addEventListener('close',()=>eventSource.close());pollTimer=setInterval(()=>fetchRun(runId),900);fetchRun(runId)}
async function fetchRun(runId){try{const response=await fetch(`${API}/runs/${runId}`);if(!response.ok)return;const run=await response.json();updateProgress(run);if(['COMPLETED','FAILED'].includes(run.status)){clearInterval(pollTimer);eventSource?.close();$('#generateButton').disabled=!generationReady}}catch{}}
function showFinal(run){const panel=$('#finalPanel');panel.classList.remove('hidden');const copy=run.is_real_output?'人物身份与当前衣服主题已锁定，五个审核镜头合成为 18 秒 9:16 H.264 成片。':'这是工程流程演示，不代表真实换装结果。';panel.innerHTML=`<video controls playsinline src="${esc(`${location.protocol}//${location.hostname}:8000${run.final_video_url}`)}"></video><div><p class="eyebrow">${run.is_real_output?'THEME TRY-ON COMPLETED':'PIPELINE DEMO'}</p><h2>你的成片已就绪。</h2><p>${copy}</p><button class="primary" onclick="openRun('${esc(run.run_id)}')"><span>查看完整任务</span><b>→</b></button></div>`;panel.scrollIntoView({behavior:'smooth'})}

let characterTemplatesLoaded=false;
async function loadCharacterTemplates(){
  if(characterTemplatesLoaded)return;
  const response=await fetch(`${API}/character-templates`);
  if(!response.ok){$('#templateGrid').innerHTML='<p class="error">人物模板目录读取失败</p>';return}
  const catalog=await response.json();
  $('#templateGrid').innerHTML=catalog.templates.map(item=>`<article class="template-card"><img src="${esc(item.cover)}" alt="${esc(item.name)}"><div><span class="template-ratio">${esc(item.aspect_ratio)}</span><h3>${esc(item.name)}</h3><p>${esc(item.summary)}</p><button class="primary compact template-generate" data-template="${esc(item.id)}"><span>生成这一类型</span><b>→</b></button></div></article>`).join('');
  $$('.template-generate').forEach(button=>button.onclick=()=>generateCharacterTemplate(button));
  characterTemplatesLoaded=true;
}
async function generateCharacterTemplate(button){
  const result=$('#templateResult'),original=button.innerHTML;
  button.disabled=true;button.innerHTML='<span>图片生成中…</span><b>•</b>';
  result.classList.remove('hidden');result.innerHTML='<p class="settings-note">正在使用当前换装图片模型生成，仅执行这一张图片。</p>';
  try{
    const response=await fetch(`${API}/character-templates/${encodeURIComponent(button.dataset.template)}/generate`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({character_id:'asian_girl_001'})});
    const payload=await response.json();
    if(!response.ok)throw new Error(payload.detail||'人物模板生成失败');
    const media=`${location.protocol}//${location.hostname}:8000${payload.image_url}`;
    result.innerHTML=`<img src="${esc(media)}" alt="${esc(payload.template_name)}"><div><p class="eyebrow">IMAGE GENERATED</p><h3>${esc(payload.template_name)}</h3><p>模型：${esc(payload.model)} · 人物：${esc(payload.character_id)}</p><a class="secondary result-link" href="${esc(media)}" target="_blank" rel="noopener">打开原图</a></div>`;
    result.scrollIntoView({behavior:'smooth'});toast(`${payload.template_name} 已生成`);
  }catch(error){result.innerHTML=`<p class="error">${esc(error.message)}</p>`}
  finally{button.disabled=false;button.innerHTML=original}
}

$('#refreshRuns').onclick=loadRuns;
async function loadRuns(){const response=await fetch(`${API}/runs`);const runs=response.ok?await response.json():[];$('#runList').innerHTML=runs.length?runs.map(run=>`<button class="run-item ${run.run_id===currentRunId?'active':''}" onclick="selectRun('${esc(run.run_id)}')"><strong>${esc(run.run_id)}</strong><span>${esc(run.status)} · ${run.progress}%</span><span>${esc(run.current_step)}</span></button>`).join(''):'<div class="run-detail empty">尚无本地任务</div>'}
window.openRun=runId=>{showView('runs');selectRun(runId)};
window.selectRun=async runId=>{currentRunId=runId;await loadRuns();const response=await fetch(`${API}/runs/${runId}`);if(!response.ok)return;renderDetail(await response.json())};
function renderDetail(run){const root=$('#runDetail');root.classList.remove('empty');const final=run.final_video_url?`<video class="detail-video" controls src="${location.protocol}//${location.hostname}:8000${run.final_video_url}"></video>`:'';const allowRetry=generationReady&&run.generation_mode!=='reviewed_theme_tryon';const shots=run.shots.map(shot=>`<article class="shot"><img src="${shot.keyframe_url?`${location.protocol}//${location.hostname}:8000${shot.keyframe_url}`:''}" alt="${esc(shot.shot_id)}"><h4>${esc(shot.shot_id)} · ${esc(shot.shot_type)}</h4><p>${esc(shot.motion_id)} · ${shot.duration}s · KF ${shot.attempts.keyframe} / VID ${shot.attempts.video}</p>${shot.video_url?`<video controls src="${location.protocol}//${location.hostname}:8000${shot.video_url}"></video>`:''}${allowRetry?`<div class="shot-actions"><button onclick="runAction('${run.run_id}','shots/${shot.shot_id}/retry-keyframe')">重试画面</button><button onclick="runAction('${run.run_id}','shots/${shot.shot_id}/retry-video')">重试视频</button></div>`:''}<details><summary>QA</summary><pre>${json({image:shot.image_qa,video:shot.video_qa})}</pre></details></article>`).join('');root.innerHTML=`<div class="detail-head"><div><h3>${esc(run.run_id)}</h3><p>${esc(run.current_step)} · ${run.progress}% · ${esc(run.generation_mode)}</p></div><span class="badge">${run.is_real_output?'REAL THEME':'DEMO'} · ${esc(run.status)}</span></div><div class="detail-actions">${run.status!=='COMPLETED'?`<button onclick="runAction('${run.run_id}','resume')">继续任务</button>`:''}<button onclick="runAction('${run.run_id}','compose')">重新合成</button><button onclick="openOutput('${run.run_id}')">打开输出目录</button><button class="danger" onclick="deleteRun('${run.run_id}')">删除任务</button></div>${final}<div class="json-grid"><div class="json-card"><h4>商品识别</h4><pre>${json(run.product_analysis)}</pre></div><div class="json-card"><h4>场景排名</h4><pre>${json(run.scene_decision)}</pre></div><div class="json-card"><h4>动作决策</h4><pre>${json(run.motion_decision)}</pre></div><div class="json-card"><h4>分镜</h4><pre>${json(run.storyboard)}</pre></div></div><h3>镜头与 QA</h3><div class="shots">${shots}</div>`}
window.runAction=async(runId,path)=>{const response=await fetch(`${API}/runs/${runId}/${path}`,{method:'POST'});if(!response.ok)return toast('操作失败');toast('操作已加入本地队列');watchRun(runId);setTimeout(()=>selectRun(runId),1000)};
window.openOutput=async runId=>{const response=await fetch(`${API}/runs/${runId}/open-output`,{method:'POST'});const result=await response.json();toast(result.opened?'已打开输出目录':`输出路径：${result.path||result.detail}`)};
window.deleteRun=async runId=>{if(!confirm('删除该任务及其全部本地产物？'))return;await fetch(`${API}/runs/${runId}`,{method:'DELETE'});currentRunId=null;$('#runDetail').className='run-detail empty';$('#runDetail').textContent='选择一个任务查看完整调试产物';loadRuns()};

function modelOptions(models,selected,groups=[]){
  const grouped=new Set(groups.flatMap(group=>group.models||[]));
  const sections=groups.map(group=>`<optgroup label="${esc(group.label)}">${(group.models||[]).filter(model=>models.includes(model)).map(model=>`<option value="${esc(model)}" ${model===selected?'selected':''}>${esc(model)}</option>`).join('')}</optgroup>`).join('');
  const remaining=models.filter(model=>!grouped.has(model)).map(model=>`<option value="${esc(model)}" ${model===selected?'selected':''}>${esc(model)}</option>`).join('');
  return sections+remaining;
}
const capabilities=['vision','image','video'];
function providerFor(capability,providerId){return (providerCatalog[capability]?.providers||[]).find(item=>item.id===providerId)}
function renderCapability(capability,status,useDefault=false){
  const providerSelect=$(`#${capability}Provider`),active=status?.capabilities?.[capability];
  const provider=providerFor(capability,providerSelect.value)||providerFor(capability,active?.provider_id)||(providerCatalog[capability]?.providers||[])[0];
  if(!provider)return;
  providerSelect.value=provider.id;
  $(`#${capability}BaseUrl`).value=provider.base_url;
  const selectedModel=useDefault?provider.default_model:(active?.provider_id===provider.id?active.model:provider.default_model);
  $(`#${capability}Model`).innerHTML=modelOptions(provider.models,selectedModel,provider.model_groups||[]);
  const configured=active?.provider_id===provider.id?active.api_key_configured:provider.api_key_configured;
  const masked=active?.provider_id===provider.id?active.api_key_masked:provider.api_key_masked;
  const badge=$(`#${capability}ApiKeyBadge`);
  badge.textContent=configured?`已配置 ${masked||''}`:'未配置';
  badge.classList.toggle('ready',Boolean(configured));
}
function renderProviderConfig(config){
  capabilities.forEach(capability=>renderCapability(capability,config));
  const all=$('#allApiKeyBadge');
  all.textContent=config.all_api_keys_configured?'三个 API Key 已保存':'尚未完整配置';
  all.classList.toggle('ready',Boolean(config.all_api_keys_configured));
  $('#providerMessage').textContent=config.all_api_keys_configured?'三个独立 API Key 已加密保存；请分别测试模型分组，生成前也会自动预检。':`还需配置：${(config.missing_capability_labels||[]).join('、')} API Key。`;
}
capabilities.forEach(capability=>{
  $(`#${capability}Provider`).onchange=()=>renderCapability(capability,null,true);
});
$('#providerForm').onsubmit=async event=>{
  event.preventDefault();
  const payload={};
  capabilities.forEach(capability=>{
    payload[`${capability}_provider_id`]=$(`#${capability}Provider`).value;
    payload[`${capability}_model`]=$(`#${capability}Model`).value;
    const key=$(`#${capability}ApiKey`).value.trim();
    if(key)payload[`${capability}_api_key`]=key;
  });
  const response=await fetch(`${API}/provider-config`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const result=await response.json();
  if(!response.ok){$('#providerMessage').textContent=result.detail||'保存失败';return}
  capabilities.forEach(capability=>$(`#${capability}ApiKey`).value='');
  toast(result.all_api_keys_configured?'三个 API 已独立启用':'配置已保存，仍有 API Key 缺失');
  await loadSystem();
};
$('#testProvider').onclick=async()=>{const response=await fetch(`${API}/provider-config/test`,{method:'POST'});const result=await response.json();$('#providerMessage').textContent=result.message;toast(result.connected?'连接成功':'连接失败')};
$$('.test-capability-key').forEach(button=>button.onclick=async()=>{
  const capability=button.dataset.capability;
  const response=await fetch(`${API}/provider-config/test?capability=${encodeURIComponent(capability)}`,{method:'POST'});
  const result=await response.json();
  $('#providerMessage').textContent=result.message;
  toast(result.connected?`${providerCatalog[capability]?.label||capability}连接成功`:`${providerCatalog[capability]?.label||capability}连接失败`);
});
$$('.delete-capability-key').forEach(button=>button.onclick=async()=>{
  const capability=button.dataset.capability,providerId=$(`#${capability}Provider`).value;
  if(!confirm(`仅删除当前${providerCatalog[capability]?.label||capability} API Key？`))return;
  const response=await fetch(`${API}/provider-config/api-key/${capability}?provider_id=${encodeURIComponent(providerId)}`,{method:'DELETE'});
  const result=await response.json();
  $('#providerMessage').textContent=result.deleted?'该能力的 Key 已独立删除。':'该能力没有已保存的 Key。';
  await loadSystem();
});
async function loadSystem(){try{const [status,settings,catalog,provider]=await Promise.all([fetch(`${API}/system/status`).then(r=>r.json()),fetch(`${API}/settings`).then(r=>r.json()),fetch(`${API}/provider-config/catalog`).then(r=>r.json()),fetch(`${API}/provider-config`).then(r=>r.json())]);providerCatalog=catalog.capabilities||{};capabilities.forEach(capability=>{const providers=providerCatalog[capability]?.providers||[];$(`#${capability}Provider`).innerHTML=providers.map(item=>`<option value="${esc(item.id)}">${esc(item.label)}</option>`).join('')});renderProviderConfig(provider);renderSystem(status,settings)}catch(error){$('#systemGrid').innerHTML='<div class="status-item">后端未连接</div>'}}
function renderSystem(status,settings){generationReady=Boolean(status.generation_ready);const videoLabel=status.real_video_ready?status.providers.video_model:status.providers.video;const values=[['FFmpeg',status.ffmpeg?'就绪':'缺失'],['视觉分析',status.real_vision_ready?status.providers.vision_provider_label:'未配置'],['换装图片',status.real_tryon_ready?status.providers.image_provider_label:'未配置'],['视频生成',status.real_video_ready?status.providers.video_provider_label:'未配置'],['Video',videoLabel],['目标模型',status.providers.configured_video_model],['环境',status.video_environment_generated?'视频生成':'关键帧生成'],['Character',status.character.asian_girl_001?'就绪':'缺失'],['Disk',`${status.disk_free_gb} GB`]];$('#systemGrid').innerHTML=values.map(([a,b])=>`<div class="status-item"><span>${esc(a)}</span><b>${esc(b)}</b></div>`).join('');$('#settingsGrid').innerHTML=Object.entries(settings).map(([key,value])=>`<div class="setting"><span>${esc(key.replaceAll('_',' '))}</span><strong>${esc(Array.isArray(value)?value.join('、'):value)}</strong></div>`).join('');const button=$('#generateButton'),notice=$('#generationNotice');button.disabled=!generationReady;$('#generateButtonLabel').textContent=generationReady?'按当前衣服生成亚洲日常场景 18S 视频':'先分别配置三个 API 与 Key';notice.textContent=generationReady?`视觉 ${status.providers.vision_provider_label} / 换装 ${status.providers.image_provider_label} / 视频 ${status.providers.video_provider_label}：三条 API 独立运行，提交前自动校验 Key 的模型分组。`:'当前禁止 Mock 服装分析、贴图假换装与静态 FFmpeg 视频；请先完成三个独立 API 配置。';notice.classList.toggle('ready',generationReady);$('#heroEyebrow').textContent=generationReady?`${status.providers.video_provider_label} · ASIAN DAILY-LIFE VIDEO`:'THREE API CONFIGURATIONS REQUIRED';const healthy=status.ffmpeg&&status.character.asian_girl_001;$('#systemPill').classList.toggle('ok',healthy&&generationReady);$('#systemPill').innerHTML=`<i></i> ${generationReady?'三个 API 已配置 · 生成前预检':healthy?'成片可播放 · 生成待配置':'检查系统设置'}`}
loadSystem();
