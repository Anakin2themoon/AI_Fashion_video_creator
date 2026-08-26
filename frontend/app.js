const IS_LOCAL_HOST = ['127.0.0.1', 'localhost'].includes(location.hostname);
const API_ORIGIN = IS_LOCAL_HOST ? `${location.protocol}//${location.hostname}:8000` : location.origin;
const API = `${API_ORIGIN}/api/v1`;
const mediaUrl = (path='') => path ? `${API_ORIGIN}${path}` : '';
const downloadUrl = (runId) => `${API}/runs/${encodeURIComponent(runId)}/download`;
const nativeFetch = window.fetch.bind(window);
window.fetch = async (input, init={}) => {const response=await nativeFetch(input,{credentials:'include',...init});const url=String(input);if(response.status===401&&!url.includes('/auth/')&&isAuthenticated){setAuthenticated(false);showAuthPrompt('登录状态已过期，请重新验证')}return response};
let currentRunId = null, pollTimer = null, eventSource = null, generationReady = false, imageReady = false, providerCatalog = {}, styleCatalog = null, isAuthenticated = false, authenticatedUsername = '', pendingProtectedView = null, pendingCreationSubmit = false, activeProgressMode = 'image';
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const esc = (value='') => String(value).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const json = (value) => esc(JSON.stringify(value ?? {}, null, 2));

function toast(message){const el=$('#toast');el.textContent=message;el.classList.add('show');setTimeout(()=>el.classList.remove('show'),2600)}
function showAuthPrompt(message='此功能需要账号密码',targetView=null){pendingProtectedView=targetView;document.body.classList.add('auth-prompt');$('#loginGate').setAttribute('aria-hidden','false');$('#loginContext').textContent=message;$('#loginError').textContent='';setTimeout(()=>$('#loginUsername').focus(),0)}
function closeAuthPrompt(){document.body.classList.remove('auth-prompt');$('#loginGate').setAttribute('aria-hidden','true');pendingProtectedView=null;pendingCreationSubmit=false}
function setAuthenticated(authenticated,username=''){isAuthenticated=authenticated;authenticatedUsername=authenticated?(username||authenticatedUsername||'admin'):'';document.body.classList.remove('auth-prompt');$('#loginGate').setAttribute('aria-hidden','true');$('#accountStatus').hidden=!authenticated;$('#accountName').textContent=authenticatedUsername;if(!authenticated){clearInterval(pollTimer);eventSource?.close();$('#loginPassword').value=''}}
$('#closeLogin').onclick=closeAuthPrompt;
$('#loginGate').onclick=event=>{if(event.target===$('#loginGate'))closeAuthPrompt()};
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&document.body.classList.contains('auth-prompt'))closeAuthPrompt()});
$('#loginForm').onsubmit=async event=>{event.preventDefault();const button=$('#loginButton'),error=$('#loginError'),targetView=pendingProtectedView,resumeCreation=pendingCreationSubmit;error.textContent='';button.disabled=true;try{const response=await fetch(`${API}/auth/login`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:$('#loginUsername').value.trim(),password:$('#loginPassword').value})});const result=await response.json();if(!response.ok)throw new Error(result.detail||'登录失败');setAuthenticated(true,result.username);pendingProtectedView=null;pendingCreationSubmit=false;await initializeApp();if(targetView)showView(targetView);toast(`${result.username} 已登录，生成服务已解锁`);if(resumeCreation)setTimeout(()=>$('#uploadForm').requestSubmit(),0)}catch(loginError){error.textContent=loginError.message}finally{button.disabled=false}};
$('#accountStatus').onclick=async()=>{await fetch(`${API}/auth/logout`,{method:'POST'});setAuthenticated(false);showView('generate');await initializeApp();toast('已退出，浏览功能仍可使用')};
function showView(name){if(['runs','settings'].includes(name)&&!isAuthenticated){showAuthPrompt(name==='runs'?'查看任务产物需要登录':'配置生成 API 需要登录',name);return}$$('.view').forEach(v=>v.classList.remove('active'));$(`#${name}View`).classList.add('active');$$('.nav').forEach(n=>n.classList.toggle('active',n.dataset.view===name));if(name==='templates') loadCharacterTemplates();if(name==='runs') loadRuns();if(name==='settings') loadSystem();}
$$('.nav').forEach(button=>button.onclick=()=>showView(button.dataset.view));

const fileInput=$('#productImage'), drop=$('#dropZone');
function previewFile(file){if(!file)return;const reader=new FileReader();reader.onload=e=>{$('#preview').src=e.target.result;drop.classList.add('has-image')};reader.readAsDataURL(file)}
fileInput.onchange=()=>previewFile(fileInput.files[0]);
['dragenter','dragover'].forEach(name=>drop.addEventListener(name,e=>{e.preventDefault();drop.classList.add('drag')}));
['dragleave','drop'].forEach(name=>drop.addEventListener(name,e=>{e.preventDefault();drop.classList.remove('drag')}));
drop.addEventListener('drop',e=>{if(e.dataTransfer.files.length){fileInput.files=e.dataTransfer.files;previewFile(fileInput.files[0])}});

$('#uploadForm').onsubmit=async event=>{event.preventDefault();$('#formError').textContent='';const outputType=$('#creationOutputType').value;renderPipeline(outputType);if(!isAuthenticated){pendingCreationSubmit=true;showAuthPrompt(`生成${outputType==='image'?'图片':'18S 视频'}需要登录，验证后将自动继续`);return}const ready=outputType==='image'?imageReady:generationReady;if(!ready){$('#formError').textContent=outputType==='image'?'请先配置换装图片 API 与 Key。':'请先完整配置视觉、图片和视频三个 API。';return}const file=fileInput.files[0];if(!file)return;const data=new FormData();data.append('product_image',file);data.append('character_id','asian_girl_001');data.append('image_template_id',$('#creationImageTemplate').value);data.append('video_style_id',$('#creationVideoStyle').value);data.append('output_type',outputType);data.append('prompt_input',$('#creationPromptInput').value);$('#generateButton').disabled=true;try{const response=await fetch(`${API}/generate`,{method:'POST',body:data});if(!response.ok)throw new Error((await response.json()).detail||'生成请求失败');const run=await response.json();currentRunId=run.run_id;updateProgress({progress:0,current_step:'任务已入队',output_type:outputType});watchRun(run.run_id);toast(run.output_type==='image'?`图片任务已提交 · Prompt Builder · ${run.image_template_id}`:`视频任务已提交 · Prompt Builder · ${run.video_style_id}`)}catch(error){$('#formError').textContent=error.message;refreshGenerateAvailability()}};

const PIPELINES={image:{title:'图片生成进度',badge:'IMAGE CREATION',steps:[[5,'商品识别','Garment facts only'],[25,'质感与提示词编译','Fashion look + prompt plan'],[50,'真实换装生成','Identity + garment fidelity'],[85,'图片 QA 与导出','Quality check + downloadable image']]},video:{title:'18S 视频编排进度',badge:'VIDEO CREATION · 18S',steps:[[5,'商品识别','Visible facts only'],[15,'场景路由','Asian daily-life location'],[23,'动作与分镜','Motion + storyboard'],[45,'换装关键帧与图片 QA','Identity + garment fidelity'],[75,'视频生成与时间 QA','18-second reviewed sequence'],[96,'成片合成与导出','H.264 · downloadable MP4']]}};
function renderPipeline(mode='image'){activeProgressMode=mode;const pipeline=PIPELINES[mode]||PIPELINES.image;$('#pipelineTitle').textContent=pipeline.title;$('#pipelineModeBadge').textContent=pipeline.badge;$('#pipelineSteps').innerHTML=pipeline.steps.map(([min,name,detail],index)=>`<li data-min="${min}"><i>${String(index+1).padStart(2,'0')}</i><span>${esc(name)}<small>${esc(detail)}</small></span><b>○</b></li>`).join('');updatePipelineMarkers(0)}
function updatePipelineMarkers(progress){const steps=$$('#pipelineSteps li');steps.forEach((li,index)=>{const min=Number(li.dataset.min),next=index===steps.length-1?100:Number(steps[index+1].dataset.min),done=progress>=(index===steps.length-1?100:next),active=progress>=min&&!done;li.classList.toggle('done',done);li.classList.toggle('active',active);li.querySelector('b').textContent=done?'✓':active?'●':'○'})}
function updateProgress(run){const progress=run.progress||0,mode=run.output_type||activeProgressMode;if(mode!==activeProgressMode)renderPipeline(mode);$('#progressValue').textContent=`${progress}%`;$('#progressBar').style.width=`${progress}%`;$('#currentStep').textContent=run.current_step||run.status;updatePipelineMarkers(progress);if(run.status==='COMPLETED')showFinal(run);if(run.status==='FAILED'){$('#formError').textContent=run.error||'流水线失败';refreshGenerateAvailability()}}
function watchRun(runId){clearInterval(pollTimer);if(eventSource)eventSource.close();eventSource=new EventSource(`${API}/runs/${runId}/events`,{withCredentials:true});eventSource.addEventListener('progress',()=>fetchRun(runId));eventSource.addEventListener('close',()=>eventSource.close());pollTimer=setInterval(()=>fetchRun(runId),900);fetchRun(runId)}
async function fetchRun(runId){try{const response=await fetch(`${API}/runs/${runId}`);if(!response.ok)return;const run=await response.json();updateProgress(run);if(['COMPLETED','FAILED'].includes(run.status)){clearInterval(pollTimer);eventSource?.close();refreshGenerateAvailability()}}catch{}}
function showFinal(run){const panel=$('#finalPanel'),download=downloadUrl(run.run_id);panel.classList.remove('hidden');if(run.output_type==='image'){const media=mediaUrl(run.image_output_url);panel.innerHTML=`<img class="final-image" src="${esc(media)}" alt="${esc(run.image_template_id)}"><div><p class="eyebrow">IMAGE CREATION COMPLETED</p><h2>高清换装图片已就绪。</h2><p>换装质感：${esc(run.generation_styles?.image_template?.name||run.image_template_id)}。可直接保存最终图片。</p><div class="download-actions"><a class="primary download-button" href="${esc(download)}"><span>下载图片</span><b>↓</b></a><button class="secondary" onclick="openRun('${esc(run.run_id)}')">查看任务</button></div></div>`}else{const media=mediaUrl(run.final_video_url),copy=run.is_real_output?'人物身份与当前衣服主题已锁定，18 秒竖屏成片已通过时间与格式检查。':'这是工程流程演示，不代表真实换装结果。';panel.innerHTML=`<video controls playsinline src="${esc(media)}"></video><div><p class="eyebrow">${run.is_real_output?'18S VIDEO COMPLETED':'PIPELINE DEMO'}</p><h2>你的成片已就绪。</h2><p>${copy}</p><div class="download-actions"><a class="primary download-button" href="${esc(download)}"><span>下载 MP4</span><b>↓</b></a><button class="secondary" onclick="openRun('${esc(run.run_id)}')">查看任务</button></div></div>`}panel.scrollIntoView({behavior:'smooth'})}

async function loadStyleCatalog(){
  if(styleCatalog)return styleCatalog;
  const response=await fetch(`${API}/style-catalog`);
  if(!response.ok)throw new Error('完整风格目录读取失败');
  styleCatalog=await response.json();
  $('#creationVideoStyle').innerHTML=styleCatalog.video_styles.map(item=>`<option value="${esc(item.id)}" ${item.id===styleCatalog.defaults.video_style_id?'selected':''}>${esc(item.name)}</option>`).join('');
  const defaultTemplate=styleCatalog.image_templates.find(item=>item.id===styleCatalog.defaults.image_template_id)||styleCatalog.image_templates[0];
  renderCreationImageTemplates(defaultTemplate.id);
  $('#creationOutputType').onchange=()=>{renderPipeline($('#creationOutputType').value);refreshGenerateAvailability()};
  return styleCatalog;
}
function renderCreationImageTemplates(selectedId=''){
  const items=styleCatalog?.image_templates||[];
  $('#creationImageTemplate').innerHTML=items.map(item=>`<option value="${esc(item.id)}" ${item.id===selectedId?'selected':''}>${esc(item.name)} · ${esc(item.aspect_ratio)}</option>`).join('');
}
async function loadCharacterTemplates(){
  try{await loadStyleCatalog()}catch(error){$('#templateGrid').innerHTML=`<p class="error">${esc(error.message)}</p>`;return}
  renderTemplateGrid();
}
function renderTemplateGrid(){
  const items=styleCatalog.image_templates;
  $('#templateCount').textContent=`${items.length} 个核心写实换装模板`;
  $('#templateGrid').innerHTML=items.map(item=>`<article class="template-card"><img src="${esc(item.cover)}" alt="${esc(item.name)}"><div><span class="template-ratio">高清写实换装 · ${esc(item.aspect_ratio)}</span><h3>${esc(item.name)}</h3><p>${esc(item.summary)}</p><button class="secondary template-use" data-template="${esc(item.id)}"><span>在创作页使用</span><b>→</b></button></div></article>`).join('');
  $$('.template-use').forEach(button=>button.onclick=()=>useTemplateInCreation(button.dataset.template));
}
function useTemplateInCreation(templateId){showView('generate');renderCreationImageTemplates(templateId);$('#creationOutputType').value='image';renderPipeline('image');refreshGenerateAvailability();document.querySelector('.generation-style-controls').scrollIntoView({behavior:'smooth',block:'center'});toast('换装质感已带入创作页，请上传衣服后生成')}

$('#refreshRuns').onclick=loadRuns;
async function loadRuns(){const response=await fetch(`${API}/runs`);const runs=response.ok?await response.json():[];$('#runList').innerHTML=runs.length?runs.map(run=>`<button class="run-item ${run.run_id===currentRunId?'active':''}" onclick="selectRun('${esc(run.run_id)}')"><strong>${esc(run.run_id)}</strong><span>${esc(run.status)} · ${run.progress}%</span><span>${esc(run.current_step)}</span></button>`).join(''):'<div class="run-detail empty">尚无本地任务</div>'}
window.openRun=runId=>{showView('runs');selectRun(runId)};
window.selectRun=async runId=>{currentRunId=runId;await loadRuns();const response=await fetch(`${API}/runs/${runId}`);if(!response.ok)return;renderDetail(await response.json())};
function renderDetail(run){const root=$('#runDetail');root.classList.remove('empty');const resultMedia=run.output_type==='image'?run.image_output_url:run.final_video_url,final=resultMedia?(run.output_type==='image'?`<img class="detail-image" src="${mediaUrl(resultMedia)}" alt="最终图片">`:`<video class="detail-video" controls src="${mediaUrl(resultMedia)}"></video>`)+`<a class="primary detail-download" href="${downloadUrl(run.run_id)}"><span>${run.output_type==='image'?'下载最终图片':'下载最终 MP4'}</span><b>↓</b></a>`:'';const allowRetry=generationReady&&run.generation_mode!=='reviewed_theme_tryon';const shots=run.shots.map(shot=>`<article class="shot"><img src="${mediaUrl(shot.keyframe_url)}" alt="${esc(shot.shot_id)}"><h4>${esc(shot.shot_id)} · ${esc(shot.shot_type)}</h4><p>${esc(shot.motion_id)} · ${shot.duration}s · KF ${shot.attempts.keyframe} / VID ${shot.attempts.video}</p>${shot.video_url?`<video controls src="${mediaUrl(shot.video_url)}"></video>`:''}${allowRetry?`<div class="shot-actions"><button onclick="runAction('${run.run_id}','shots/${shot.shot_id}/retry-keyframe')">重试画面</button><button onclick="runAction('${run.run_id}','shots/${shot.shot_id}/retry-video')">重试视频</button></div>`:''}<details><summary>QA</summary><pre>${json({image:shot.image_qa,video:shot.video_qa})}</pre></details></article>`).join('');root.innerHTML=`<div class="detail-head"><div><h3>${esc(run.run_id)}</h3><p>${esc(run.current_step)} · ${run.progress}% · ${esc(run.generation_mode)}</p><p>任务图片模板：${esc(run.generation_styles?.image_template?.name||run.image_template_id)} · 视频风格：${esc(run.generation_styles?.video_style?.name||run.video_style_id)}</p></div><span class="badge">${run.is_real_output?'REAL THEME':'DEMO'} · ${esc(run.status)}</span></div><div class="detail-actions">${run.status!=='COMPLETED'?`<button onclick="runAction('${run.run_id}','resume')">继续任务</button>`:''}${run.output_type==='video'?`<button onclick="runAction('${run.run_id}','compose')">重新合成</button>`:''}<button onclick="openOutput('${run.run_id}')">打开输出目录</button><button class="danger" onclick="deleteRun('${run.run_id}')">删除任务</button></div>${final}<div class="json-grid"><div class="json-card"><h4>图片模板 / 视频风格</h4><pre>${json(run.generation_styles)}</pre></div><div class="json-card"><h4>商品识别</h4><pre>${json(run.product_analysis)}</pre></div><div class="json-card"><h4>场景排名</h4><pre>${json(run.scene_decision)}</pre></div><div class="json-card"><h4>动作决策</h4><pre>${json(run.motion_decision)}</pre></div><div class="json-card"><h4>分镜</h4><pre>${json(run.storyboard)}</pre></div></div><h3>镜头与 QA</h3><div class="shots">${shots}</div>`}
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
async function loadSystem(){try{const [status,catalog]=await Promise.all([fetch(`${API}/system/status`).then(r=>r.json()),fetch(`${API}/provider-config/catalog`).then(r=>r.json())]);providerCatalog=catalog.capabilities||{};capabilities.forEach(capability=>{const providers=providerCatalog[capability]?.providers||[];$(`#${capability}Provider`).innerHTML=providers.map(item=>`<option value="${esc(item.id)}">${esc(item.label)}</option>`).join('')});if(isAuthenticated){const [settings,provider]=await Promise.all([fetch(`${API}/settings`).then(r=>r.json()),fetch(`${API}/provider-config`).then(r=>r.json())]);renderProviderConfig(provider);renderSystem(status,settings)}else{renderSystem(status,{authentication:'创作、任务与 API 配置需要登录'});$('#providerMessage').textContent='登录后才能查看或修改三个生成 API 配置。'}}catch(error){$('#systemGrid').innerHTML='<div class="status-item">后端未连接</div>'}}
function renderSystem(status,settings){generationReady=Boolean(status.generation_ready);imageReady=Boolean(status.real_tryon_ready);const videoLabel=status.real_video_ready?status.providers.video_model:status.providers.video;const values=[['FFmpeg',status.ffmpeg?'就绪':'缺失'],['视觉分析',status.real_vision_ready?status.providers.vision_provider_label:'未配置'],['换装图片',status.real_tryon_ready?status.providers.image_provider_label:'未配置'],['视频生成',status.real_video_ready?status.providers.video_provider_label:'未配置'],['Video',videoLabel],['目标模型',status.providers.configured_video_model],['环境',status.video_environment_generated?'视频生成':'关键帧生成'],['Character',status.character.asian_girl_001?'就绪':'缺失'],['Disk',`${status.disk_free_gb} GB`]];$('#systemGrid').innerHTML=values.map(([a,b])=>`<div class="status-item"><span>${esc(a)}</span><b>${esc(b)}</b></div>`).join('');$('#settingsGrid').innerHTML=Object.entries(settings).map(([key,value])=>`<div class="setting"><span>${esc(key.replaceAll('_',' '))}</span><strong>${esc(Array.isArray(value)?value.join('、'):value)}</strong></div>`).join('');$('#heroEyebrow').textContent=generationReady?`${status.providers.video_provider_label} · ASIAN DAILY-LIFE VIDEO`:'INDEPENDENT IMAGE / VIDEO CREATION';const healthy=status.ffmpeg&&status.character.asian_girl_001;$('#systemPill').classList.toggle('ok',healthy&&imageReady);$('#systemPill').innerHTML=`<i></i> ${generationReady?'图片与视频均可生成':imageReady?'图片生成可用 · 视频待配置':'检查系统设置'}`;refreshGenerateAvailability()}
function refreshGenerateAvailability(){const outputType=$('#creationOutputType')?.value||'image',ready=outputType==='image'?imageReady:generationReady,button=$('#generateButton'),notice=$('#generationNotice');button.disabled=isAuthenticated&&!ready;$('#creationVideoStyleLabel').classList.toggle('style-disabled',outputType==='image');$('#generateButtonLabel').textContent=outputType==='image'?'按当前衣服生成高清换装图片':'按当前衣服生成 18S 换装视频';notice.textContent=!isAuthenticated?'上传衣服并点击生成后，登录账号即可自动继续当前创作。':outputType==='image'?'仅调用独立图片 API；高清换装图片与生成清单单独保存，不调用视觉或视频 API。':'换装质感控制关键帧，视频风格控制真实日常动态镜头；生成前校验三个 API。';notice.classList.toggle('ready',!isAuthenticated||ready)}
async function initializeApp(){styleCatalog=null;await loadStyleCatalog().catch(error=>{$('#formError').textContent=error.message});await loadSystem()}
async function bootstrapAuth(){try{const response=await fetch(`${API}/auth/session`);const session=await response.json();setAuthenticated(Boolean(session.authenticated),session.username||'');await initializeApp()}catch{setAuthenticated(false);await initializeApp()}}
renderPipeline('image');
bootstrapAuth();
