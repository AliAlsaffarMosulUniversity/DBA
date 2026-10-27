import {Store,verifyFirebase} from './store.mjs';
import {conflicts,validateRows} from './schedule.mjs';
const roles=['admin','head','secretary','teacher'];
const fail=(status,message)=>{const e=new Error(message);e.status=status;throw e;};
const text=(v,max=200,required=false)=>{if(typeof v!=='string'||v.length>max||required&&!v.trim())fail(422,'حقل نصي مفقود أو أطول من الحد');return v.trim();};
const now=()=>new Date().toISOString();
const uid=()=>crypto.randomUUID();
const manager=user=>{if(!['admin','head','secretary'].includes(user.role))fail(403,'هذه العملية للإدارة فقط');};
const administrator=user=>{if(user.role!=='admin')fail(403,'هذه العملية لمدير النظام فقط');};
const visible=(n,user)=>user.role!=='teacher'||n.recipients.includes(user.profileId);
const version=(data,row)=>{if(!data._version||data._version!==row._version)fail(409,'تغير السجل؛ أعد تحميل البيانات قبل الحفظ');};
function links(input=[]){if(!Array.isArray(input)||input.length>6)fail(422,'حتى 6 روابط فقط');return input.map(x=>{
  const label=text(x.label,100,true),url=text(x.url,1000,true);let u;try{u=new URL(url);}catch{fail(422,'رابط غير صالح');}
  if(u.protocol!=='https:'||u.username||u.password)fail(422,'استخدم رابط HTTPS دون بيانات دخول');return {label,url};
});}
function profile(data){return Object.fromEntries(['name','name_en','rank','qualification','specialty','detailed_specialty','email','employment','bio'].map(k=>[k,text(data[k]||'',k==='bio'?1500:200,k==='name')]));}
async function receiptId(notice,user){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(notice+':'+user)))).map(x=>x.toString(16).padStart(2,'0')).join('');}
export function createHandler(dependencies={}){
 return {async fetch(request,env){
  const headers={'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY'};
  const reply=(body,status=200)=>new Response(JSON.stringify(body),{status,headers});
  try{
   const url=new URL(request.url),path=url.pathname.replace(/^\/api/,'');
   if(!url.pathname.startsWith('/api/')){
     const asset=await env.ASSETS.fetch(request);const r=new Response(asset.body,asset);r.headers.set('X-Content-Type-Options','nosniff');r.headers.set('Referrer-Policy','no-referrer');r.headers.set('X-Frame-Options','DENY');
     r.headers.set('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self' https://identitytoolkit.googleapis.com; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'");return r;
   }
   if(request.method==='GET'&&path==='/config')return reply({projectId:env.FIREBASE_PROJECT_ID,apiKey:env.FIREBASE_WEB_API_KEY||'',adminEmail:env.ADMIN_EMAIL});
   if(request.method==='GET'&&path==='/health')return reply({status:'worker-ready',database:'not checked',version:'3.0-cloud'});
   const token=request.headers.get('Authorization')?.match(/^Bearer (.+)$/)?.[1];if(!token)fail(401,'سجّل الدخول أولًا');
   const claims=await (dependencies.verify||verifyFirebase)(token,env);
   if(env.API_LIMITER){const limit=await env.API_LIMITER.limit({key:'uid:'+claims.sub});if(!limit.success)return reply({detail:'طلبات كثيرة؛ انتظر دقيقة'},429);}
   if(claims.email_verified!==true||!claims.email)fail(403,'تحقق من بريدك الإلكتروني ثم سجّل الدخول مجددًا');
   const store=dependencies.store||new Store(env);
   let user=await store.get('users',claims.sub);
   if(!user){
    const isAdmin=claims.email.toLowerCase()===env.ADMIN_EMAIL?.toLowerCase();
    const match=isAdmin?null:(await store.list('profiles')).find(p=>p.email.toLowerCase()===claims.email.toLowerCase());
    if(!isAdmin&&!match)fail(403,'بريدك غير مسجل في ملفات القسم؛ تواصل مع مدير النظام');
    user=await store.set('users',claims.sub,{email:claims.email,name:match?.name||'مدير النظام',role:isAdmin?'admin':'teacher',active:true,profileId:match?.id||'',createdAt:now()});
   }
   if(!user.active)fail(403,'الحساب معطل؛ تواصل مع مدير النظام');
   if(path==='/me'&&request.method==='GET')return reply(user);
   let body={};
   if(!['GET','HEAD'].includes(request.method)){
    if(!request.headers.get('Content-Type')?.startsWith('application/json'))fail(415,'استخدم بيانات JSON');
    if(Number(request.headers.get('Content-Length')||0)>180000)fail(413,'الطلب كبير');
    const reader=request.body?.getReader();let size=0,chunks=[];if(reader){while(true){const part=await reader.read();if(part.done)break;size+=part.value.length;if(size>180000){await reader.cancel();fail(413,'الطلب كبير');}chunks.push(part.value);}}
    const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
    try{body=JSON.parse(new TextDecoder().decode(bytes));}catch{fail(422,'بيانات غير صالحة');}
    if(!body||Array.isArray(body)||typeof body!=='object')fail(422,'بيانات غير صالحة');
   }
   const method=request.method;
   if(path==='/profiles'&&method==='GET')return reply(await store.list('profiles'));
   if(path==='/profiles'&&method==='POST'){
    manager(user);const data=profile(body);if(data.email&&!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(data.email))fail(422,'بريد غير صالح');
    return reply(await store.set('profiles',uid(),{...data,createdAt:now(),updatedAt:now()}),201);
   }
   const profilePath=path.match(/^\/profiles\/([\w-]+)$/);
   if(profilePath&&method==='PUT'){
    manager(user);const old=await store.get('profiles',profilePath[1]);if(!old)fail(404,'الملف غير موجود');version(body,old);
    const data=profile(body);if(data.email&&!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(data.email))fail(422,'بريد غير صالح');
    // Keep account linking explicit: changing a profile email does not transfer a user's identity.
    if(data.email!==old.email&&(await store.list('users')).some(u=>u.profileId===old.id))fail(409,'البريد مرتبط بحساب؛ لا يمكن تغييره من ملف التدريسي');
    return reply(await store.set('profiles',old.id,{...old,...data,updatedAt:now()},old._version));
   }
   if(path==='/users'&&method==='GET'){administrator(user);return reply(await store.list('users'));}
   const userPath=path.match(/^\/users\/([\w-]+)$/);
   if(userPath&&method==='PUT'){
    administrator(user);const old=await store.get('users',userPath[1]);if(!old)fail(404,'الحساب غير موجود');version(body,old);
    if(!roles.includes(body.role)||typeof body.active!=='boolean')fail(422,'دور أو حالة غير صالحة');
    if(old.id===user.id&&(body.role!=='admin'||!body.active))fail(422,'لا يمكنك تعطيل نفسك أو إزالة دورك');
    return reply(await store.set('users',old.id,{...old,role:body.role,active:body.active},old._version));
   }
   if(path==='/notices'&&method==='GET'){
    const list=(await store.list('notices')).filter(n=>visible(n,user)).sort((a,b)=>b.createdAt.localeCompare(a.createdAt));
    // Read only this user's receipt for each accessible notice; never expose other receipts to teachers.
    const receipts=(await store.list('receipts')).filter(r=>r.userId===user.id);
    return reply(list.slice(0,100).map(n=>({...n,receipt:receipts.find(r=>r.noticeId===n.id)||null})));
   }
   if(path==='/notices'&&method==='POST'){
    manager(user);const profiles=await store.list('profiles');const ids=new Set(profiles.map(p=>p.id));
    if(!Array.isArray(body.recipients)||!body.recipients.length||body.recipients.length>100||new Set(body.recipients).size!==body.recipients.length||body.recipients.some(id=>!ids.has(id)))fail(422,'اختر من 1 إلى 100 مستلم مسجل');
    return reply(await store.set('notices',uid(),{title:text(body.title,200,true),content:text(body.content,10000,true),links:links(body.links),recipients:body.recipients,author:user.name,authorId:user.id,createdAt:now(),archived:false}),201);
   }
   const noticePath=path.match(/^\/notices\/([\w-]+)\/(view|ack|receipts|archive)$/);
   if(noticePath){
    const [,id,action]=noticePath,n=await store.get('notices',id);if(!n||!visible(n,user))fail(404,'التبليغ غير موجود');
    if(action==='receipts'&&method==='GET'){manager(user);const receipts=(await store.list('receipts')).filter(r=>r.noticeId===id);const profiles=await store.list('profiles');return reply(n.recipients.map(profileId=>({name:profiles.find(p=>p.id===profileId)?.name||'تدريسي',...(receipts.find(r=>r.profileId===profileId)||{})})));}
    if(action==='archive'&&method==='POST'){manager(user);version(body,n);return reply(await store.set('notices',id,{...n,archived:!n.archived},n._version));}
    if(['view','ack'].includes(action)&&method==='POST'){
     if(!n.recipients.includes(user.profileId))fail(403,'أنت لست ضمن المستلمين');
     const rid=await receiptId(id,user.id),old=await store.get('receipts',rid);
     if(action==='ack'&&!old?.viewedAt)fail(422,'افتح التبليغ قبل تأكيد الاطلاع');
     return reply(await store.set('receipts',rid,{...(old||{}),noticeId:id,userId:user.id,profileId:user.profileId,viewedAt:old?.viewedAt||now(),acknowledgedAt:old?.acknowledgedAt||(action==='ack'?now():null)},old?._version));
    }
   }
   const state=()=>store.get('state','timetable');
   if(path==='/schedules'&&method==='GET'){const s=await state();return reply((s?.plans||[]).filter(p=>user.role!=='teacher'||p.status==='published'));}
   if(path==='/schedules/check'&&method==='POST'){manager(user);const rows=validateRows(body.rows,await store.list('profiles'));return reply({rows,conflicts:conflicts(rows)});}
   if(path==='/schedules'&&method==='POST'){
    manager(user);const s=await state(),plans=s?.plans||[];if(plans.length>=20)fail(422,'حد النسخة المخففة 20 خطة؛ صدّر الخطط قبل التوسع');
    const rows=validateRows(body.rows,await store.list('profiles'));const found=conflicts(rows);if(found.length)fail(422,'تعارض في الجلسات: '+JSON.stringify(found.slice(0,5)));
    if(!['weekly','exam'].includes(body.kind))fail(422,'نوع جدول غير صالح');
    const plan={id:uid(),title:text(body.title,200,true),kind:body.kind,rows,status:'draft',createdAt:now(),author:user.name,version:1};
    const data={plans:[...plans,plan]};if(JSON.stringify(data).length>250000)fail(422,'حجم الخطط تجاوز حد النسخة المخففة');
    await store.set('state','timetable',data,s?._version);return reply(plan,201);
   }
   const planPath=path.match(/^\/schedules\/([\w-]+)\/(approve|publish|archive)$/);
   if(planPath&&method==='POST'){
    const [,id,action]=planPath;if(!['admin','head'].includes(user.role))fail(403,'الاعتماد والنشر لرئيس القسم أو مدير النظام');
    const s=await state(),plan=s?.plans.find(p=>p.id===id);if(!plan)fail(404,'الجدول غير موجود');if(body.version!==plan.version)fail(409,'تغير إصدار الجدول؛ أعد تحميله');
    if(action==='approve'&&plan.status!=='draft'||action==='publish'&&plan.status!=='approved'||action==='archive'&&plan.status==='archived')fail(422,'حالة الجدول لا تسمح بالعملية');
    if(action==='publish'){
     const other=s.plans.filter(p=>p.id!==id&&p.status==='published').flatMap(p=>p.rows);
     if(other.length+plan.rows.length>200)fail(422,'حد النسخة المخففة 200 جلسة منشورة؛ أرشف الخطط المنتهية أولًا');
     if(conflicts([...plan.rows,...other]).length)fail(409,'يتعارض الجدول مع خطة منشورة؛ أرشف الخطة القديمة أو أنشئ خطة مصححة');
    }
    const updated={...plan,status:{approve:'approved',publish:'published',archive:'archived'}[action],version:plan.version+1,updatedAt:now(),updatedBy:user.name};
    await store.set('state','timetable',{plans:s.plans.map(p=>p.id===id?updated:p)},s._version);return reply(updated);
   }
   fail(404,'المسار غير موجود');
  }catch(error){return reply({detail:error.status?error.message:'تعذر الاتصال بالخدمة؛ تحقق من إعداد Firebase وأعد المحاولة'},error.status||503);}
 }};
}
export default createHandler();
