import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve,dirname} from 'node:path';
import {spawn} from 'node:child_process';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const npm=process.platform==='win32'?'npm.cmd':'npm';
const npx=process.platform==='win32'?'npx.cmd':'npx';
function run(command,args,input){return new Promise((done,reject)=>{
 const child=spawn(command,args,{cwd:root,stdio:[input?'pipe':'inherit','inherit','inherit'],shell:process.platform==='win32'});
 if(input)child.stdin.end(input);
 child.on('error',reject);child.on('exit',code=>code===0?done():reject(new Error('Step failed; see message above.')));
});}
try{
 const key=JSON.parse(await readFile(resolve(root,'.local/firebase-admin.json'),'utf8'));
 const settings=JSON.parse(await readFile(resolve(root,'.local/deploy-settings.json'),'utf8'));
 if(key.project_id!=='ba-dms-mosul'||key.type!=='service_account'||!key.private_key||!settings.apiKey)throw new Error('Invalid local Firebase configuration. See README.');
 await run(npm,['install']);await run(npm,['--prefix','frontend','ci']);await run(npm,['run','build']);await run(npm,['test']);
 console.log('Cloudflare login: complete the official browser prompt yourself.');
 await run(npx,['wrangler','login']);
 await run(npx,['wrangler','deploy']);
 console.log('Uploading Firebase configuration to Cloudflare encrypted secrets. No key will be printed.');
 await run(npx,['wrangler','secret','bulk'],JSON.stringify({FIREBASE_SERVICE_ACCOUNT:JSON.stringify(key),FIREBASE_WEB_API_KEY:settings.apiKey}));
 console.log('Deployment commands completed. Open the workers.dev URL and test login. This computer can be shut down.');
}catch(error){console.error(error.code==='ENOENT'?'Missing .local Firebase files. See README.':error.message);process.exitCode=1;}
