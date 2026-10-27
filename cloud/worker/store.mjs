const encoder = new TextEncoder();
export const b64 = bytes => btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/=/g,'').replace(/\+/g,'-').replace(/\//g,'_');
export function unb64(s) {return Uint8Array.from(atob(s.replace(/-/g,'+').replace(/_/g,'/')), c=>c.charCodeAt(0));}
let cachedToken;
async function googleToken(env) {
  const account = JSON.parse(env.FIREBASE_SERVICE_ACCOUNT || '{}');
  if(account.project_id !== env.FIREBASE_PROJECT_ID || !account.private_key) throw new Error('Firebase credential configuration missing');
  if(cachedToken?.email===account.client_email && cachedToken.until>Date.now()) return cachedToken.token;
  const now=Math.floor(Date.now()/1000);
  const head=b64(encoder.encode(JSON.stringify({alg:'RS256',typ:'JWT'})));
  const body=b64(encoder.encode(JSON.stringify({iss:account.client_email,scope:'https://www.googleapis.com/auth/datastore',aud:'https://oauth2.googleapis.com/token',iat:now,exp:now+3600})));
  const pem=account.private_key.replace(/-----[^-]+-----/g,'').replace(/\s/g,'');
  const key=await crypto.subtle.importKey('pkcs8',unb64(pem),{name:'RSASSA-PKCS1-v1_5',hash:'SHA-256'},false,['sign']);
  const signature=await crypto.subtle.sign('RSASSA-PKCS1-v1_5',key,encoder.encode(head+'.'+body));
  const response=await fetch('https://oauth2.googleapis.com/token',{method:'POST',body:new URLSearchParams({grant_type:'urn:ietf:params:oauth:grant-type:jwt-bearer',assertion:head+'.'+body+'.'+b64(signature)})});
  if(!response.ok)throw new Error('Firebase service authentication failed');
  const data=await response.json(); cachedToken={email:account.client_email,token:data.access_token,until:Date.now()+(data.expires_in-120)*1000}; return data.access_token;
}
const field=v=>v===null?{nullValue:null}:typeof v==='boolean'?{booleanValue:v}:typeof v==='number'?{doubleValue:v}:typeof v==='string'?{stringValue:v}:Array.isArray(v)?{arrayValue:{values:v.map(field)}}:{mapValue:{fields:fields(v)}};
const fields=obj=>Object.fromEntries(Object.entries(obj).filter(([,v])=>v!==undefined).map(([k,v])=>[k,field(v)]));
const value=v=>'stringValue'in v?v.stringValue:'integerValue'in v?Number(v.integerValue):'doubleValue'in v?v.doubleValue:'booleanValue'in v?v.booleanValue:'nullValue'in v?null:'arrayValue'in v?(v.arrayValue.values||[]).map(value):Object.fromEntries(Object.entries(v.mapValue?.fields||{}).map(([k,v])=>[k,value(v)]));
const decode=doc=>doc?{...Object.fromEntries(Object.entries(doc.fields||{}).map(([k,v])=>[k,value(v)])),id:doc.name.split('/').pop(),_version:doc.updateTime}:null;
export class Store {
  constructor(env){this.env=env;this.base=`https://firestore.googleapis.com/v1/projects/${env.FIREBASE_PROJECT_ID}/databases/(default)/documents`;}
  path(col,id){if(!/^[a-z_]+$/.test(col)||! /^[a-zA-Z0-9_-]{1,128}$/.test(id))throw new Error('Invalid document path');return `cloud_v3_${col}/${id}`;}
  async call(path,init={}){
    const response=await fetch(this.base+path,{...init,headers:{Authorization:'Bearer '+await googleToken(this.env),'Content-Type':'application/json',...init.headers}});
    if(response.status===404)return null;
    if(!response.ok){const error=new Error(response.status===409||response.status===400||response.status===412?'تعذر الحفظ بسبب تعديل متزامن، أعد تحميل البيانات':'تعذر الاتصال بقاعدة البيانات');error.status=response.status===409||response.status===412?409:503;throw error;}
    return response.status===204?null:response.json();
  }
  async get(col,id){return decode(await this.call('/'+this.path(col,id)));}
  async list(col){
    let rows=[],next='';
    do{const data=await this.call(`/cloud_v3_${col}?pageSize=200${next?'&pageToken='+encodeURIComponent(next):''}`);rows.push(...(data?.documents||[]).map(decode));next=data?.nextPageToken||'';if(rows.length>2000)throw new Error('حد النسخة المخففة 2000 سجل للمجموعة');}while(next);
    return rows;
  }
  async set(col,id,data,version){
    const clean={...data};delete clean.id;delete clean._version;
    const writes=[{update:{name:this.base.replace('https://firestore.googleapis.com/v1/','')+'/'+this.path(col,id),fields:fields(clean)},currentDocument:version?{updateTime:version}:{exists:false}}];
    await this.call(':commit',{method:'POST',body:JSON.stringify({writes})});return this.get(col,id);
  }
}
let certCache;
export async function verifyFirebase(token,env){
  try{
    const parts=token.split('.');if(parts.length!==3)throw 0;
    const [header,claims]=parts.slice(0,2).map(p=>JSON.parse(new TextDecoder().decode(unb64(p))));
    const now=Math.floor(Date.now()/1000);
    if(header.alg!=='RS256'||!header.kid||claims.aud!==env.FIREBASE_PROJECT_ID||claims.iss!==`https://securetoken.google.com/${env.FIREBASE_PROJECT_ID}`||typeof claims.sub!=='string'||! /^[a-zA-Z0-9_-]{1,128}$/.test(claims.sub)||!Number.isFinite(claims.exp)||!Number.isFinite(claims.iat)||!Number.isFinite(claims.auth_time)||claims.exp<=now||claims.iat>now+30||claims.auth_time>now+30)throw 0;
    if(!certCache||certCache.until<Date.now()){
      const r=await fetch('https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com');if(!r.ok)throw 0;
      certCache={keys:(await r.json()).keys,until:Date.now()+3600000};
    }
    const jwk=certCache.keys.find(k=>k.kid===header.kid);if(!jwk)throw 0;
    const key=await crypto.subtle.importKey('jwk',jwk,{name:'RSASSA-PKCS1-v1_5',hash:'SHA-256'},false,['verify']);
    if(!await crypto.subtle.verify('RSASSA-PKCS1-v1_5',key,unb64(parts[2]),encoder.encode(parts[0]+'.'+parts[1])))throw 0;
    return claims;
  }catch{const error=new Error('انتهت الجلسة، سجّل الدخول مجددًا');error.status=401;throw error;}
}
