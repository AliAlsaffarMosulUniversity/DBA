import {readFile} from 'node:fs/promises';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {Store} from '../worker/store.mjs';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
try{
 const rows=JSON.parse(await readFile(resolve(root,'.local/faculty-profiles.json'),'utf8'));
 const keys=['name','name_en','rank','qualification','specialty','detailed_specialty','email','employment','bio'];
 if(!Array.isArray(rows)||!rows.length||rows.length>100)throw new Error('Expected 1 to 100 profiles');
 const clean=rows.map(r=>Object.fromEntries(keys.map(k=>{const v=r[k]||'';if(typeof v!=='string'||v.length>(k==='bio'?1500:200))throw new Error('Invalid profile field');return [k,v.trim()];})));
 if(clean.some(r=>!r.name))throw new Error('Profile name is required');
 console.log('Validated profiles:',clean.length);
 if(!process.argv.includes('--apply')){console.log('Local validation only. No connection or upload.');process.exit(0);}
 const credential=await readFile(resolve(root,'.local/firebase-admin.json'),'utf8');
 const store=new Store({FIREBASE_PROJECT_ID:'ba-dms-mosul',FIREBASE_SERVICE_ACCOUNT:credential});
 const existing=await store.list('profiles');
 // A source fingerprint makes retries idempotent and detects a changed input file.
 const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(clean))))).map(x=>x.toString(16).padStart(2,'0')).join('').slice(0,24);
 const expected=clean.map((_,i)=>`import_${hash}_${i+1}`);
 if(existing.some(p=>!expected.includes(p.id)))throw new Error('Destination has other profiles; refusing to merge or overwrite.');
 let count=0;
 for(let i=0;i<clean.length;i++){
  if(existing.some(p=>p.id===expected[i]))continue;
  await store.set('profiles',expected[i],{...clean[i],createdAt:new Date().toISOString(),updatedAt:new Date().toISOString()});count++;
 }
 console.log('Newly imported profiles:',count,'; total source:',clean.length);
}catch(error){console.error('Import stopped:',error.message);process.exitCode=1;}
