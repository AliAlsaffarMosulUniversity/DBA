import test from 'node:test';
import assert from 'node:assert/strict';
import {Store,verifyFirebase,b64} from '../worker/store.mjs';
const enc=new TextEncoder();
test('Firebase ID token signature and required claims are enforced',async()=>{
 const pair=await crypto.subtle.generateKey({name:'RSASSA-PKCS1-v1_5',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},true,['sign','verify']);
 const jwk={...await crypto.subtle.exportKey('jwk',pair.publicKey),kid:'fixture-key'};
 const original=globalThis.fetch;globalThis.fetch=async()=>Response.json({keys:[jwk]});
 const now=Math.floor(Date.now()/1000),claims={sub:'teacher-1',aud:'project-test',iss:'https://securetoken.google.com/project-test',iat:now,auth_time:now,exp:now+3600,email:'teacher@example.org',email_verified:true};
 async function token(c){const data=b64(enc.encode(JSON.stringify({alg:'RS256',kid:'fixture-key'})))+'.'+b64(enc.encode(JSON.stringify(c)));return data+'.'+b64(await crypto.subtle.sign('RSASSA-PKCS1-v1_5',pair.privateKey,enc.encode(data)));}
 try{
  assert.equal((await verifyFirebase(await token(claims),{FIREBASE_PROJECT_ID:'project-test'})).sub,'teacher-1');
  for(const invalid of [{...claims,aud:'another-project'},{...claims,exp:now-1},{...claims,exp:undefined},{...claims,auth_time:undefined},{...claims,sub:'../bad'}])await assert.rejects(()=>verifyFirebasePromise(invalid));
  async function verifyFirebasePromise(c){return verifyFirebase(await token(c),{FIREBASE_PROJECT_ID:'project-test'});}
  const valid=await token(claims),parts=valid.split('.');parts[1]=b64(enc.encode(JSON.stringify({...claims,sub:'admin'})));await assert.rejects(()=>verifyFirebase(parts.join('.'),{FIREBASE_PROJECT_ID:'project-test'}));
 }finally{globalThis.fetch=original;}
});
test('Firestore REST serializes fields, uses create/update preconditions and does not expose service key',async()=>{
 const pair=await crypto.subtle.generateKey({name:'RSASSA-PKCS1-v1_5',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},true,['sign','verify']);
 const pem='-----BEGIN PRIVATE KEY-----\n'+Buffer.from(await crypto.subtle.exportKey('pkcs8',pair.privateKey)).toString('base64')+'\n-----END PRIVATE KEY-----';
 const env={FIREBASE_PROJECT_ID:'project-test',FIREBASE_SERVICE_ACCOUNT:JSON.stringify({project_id:'project-test',private_key:pem,client_email:'service@example.org'})};
 const original=globalThis.fetch,commits=[];let stored;
 globalThis.fetch=async(url,init)=>{
  if(url==='https://oauth2.googleapis.com/token')return Response.json({access_token:'test-access-token',expires_in:3600});
  assert.equal(init.headers.Authorization,'Bearer test-access-token');assert.ok(!JSON.stringify(init).includes('PRIVATE KEY'));
  if(url.endsWith(':commit')){const body=JSON.parse(init.body);commits.push(body);stored={...body.writes[0].update,updateTime:'fixture-time'};return Response.json({});}
  return stored?Response.json(stored):new Response('',{status:404});
 };
 try{const store=new Store(env);assert.equal(await store.get('profiles','p1'),null);const first=await store.set('profiles','p1',{name:'اسم',active:true,count:3,links:[{label:'ملف',url:'https://example.org'}]});assert.equal(first.links[0].label,'ملف');assert.equal(first.count,3);assert.deepEqual(commits[0].writes[0].currentDocument,{exists:false});await store.set('profiles','p1',{...first,name:'محدث'},first._version);assert.deepEqual(commits[1].writes[0].currentDocument,{updateTime:'fixture-time'});assert.equal(commits[1].writes[0].update.fields._version,undefined);}finally{globalThis.fetch=original;}
});
