'use strict';
// Driver activation, rather than extensionTestsPath, survives actual workbench Reload.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const net = require('node:net');
const path = require('node:path');
const vscode = require('vscode');
const COMMAND = 'netcoredbg.debugActiveFile';
const MODULES = ['entry.cjs', 'runtime.cjs', 'classify.cjs', 'web.cjs', 'recovery.cjs'];
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const exists = file => { try { fs.lstatSync(file); return true; } catch (e) { if (e.code === 'ENOENT') return false; throw e; } };
const same = (a, b) => path.resolve(a).toLowerCase() === path.resolve(b).toLowerCase();
function within(root, file) { const r = path.relative(path.resolve(root), path.resolve(file)); return r && r !== '..' && !r.startsWith('..' + path.sep) && !path.isAbsolute(r); }
function alive(pid) { assert(Number.isSafeInteger(pid) && pid > 0); try { process.kill(pid, 0); return true; } catch (e) { if (e.code === 'ESRCH') return false; throw e; } }
async function port() { const s = net.createServer(); await new Promise((r,j) => {s.once('error',j);s.listen(0,'127.0.0.1',r);});const p=s.address().port;await new Promise((r,j)=>s.close(e=>e?j(e):r()));return p; }
async function bindable(p) { const s=net.createServer();return new Promise((r,j)=>{s.once('error',e=>e.code==='EADDRINUSE'?r(false):j(e));s.listen(p,'127.0.0.1',()=>s.close(e=>e?j(e):r(true)));}); }
async function probe(origin) {const r=await fetch(origin+'/probe',{signal:AbortSignal.timeout(2000)});assert.equal(r.status,200);return r.json();}
exports.run = async function run() {
    const root = process.env.NETCOREDBG_LIFECYCLE_ROOT; assert(root && path.isAbsolute(root));
    const read = name => JSON.parse(fs.readFileSync(path.join(root,name),'utf8').replace(/^\uFEFF/,''));
    const write = (name,value) => fs.writeFileSync(path.join(root,name),JSON.stringify(value,null,2)+'\n');
    const expected=read('expected.json'); assert.equal(expected.scenario,'actual-workbench-reload');
    const previous=exists(path.join(root,'phase.json'))?read('phase.json'):undefined;
    const phase=previous?2:1;
    const trace=(event,value)=>fs.appendFileSync(path.join(root,'trace.jsonl'),JSON.stringify({atUtc:new Date().toISOString(),phase,host:process.pid,event,value})+'\n');
    const launches=previous?[previous.launch]:[];const byToken=new Map();const subscriptions=[];let observerError;
    const state=l=>({...l,session:undefined,captured:undefined,sessionId:l.session?.id||l.sessionId,capturedSessions:l.captured?[...l.captured.values()].map(c=>({...c,session:undefined,sessionId:c.session.id})):l.capturedSessions});
    const save=()=>write('owned-launches.json',{schema:1,launches:launches.map(state)});
    const result={schema:1,success:false,mechanicsCompleted:false,phase,expected,host:process.pid,checks:[],scope:{actualWorkbenchReload:true,appLaunches:1,installedCandidate:true,injectedTargetRuntime:false,extensionTestsPath:false,commandApi:true,physicalF5:false,macOS:false,localOnly:true,published:false,qualification:false}};
    async function until(check,label,limit=90000){const start=performance.now();while(true){if(observerError)throw observerError;if(await check())return;if(performance.now()-start>limit)throw Error('Safety timeout: '+label);await delay(25);}}
    function observe(action){try{action();}catch(e){observerError||=e;trace('observer-error',e.stack);save();}}
    function capture(s){const l=byToken.get(s.configuration?.env?.LIFECYCLE_TOKEN);if(!l)return;
        if(!l.captured.has(s.id))l.captured.set(s.id,{session:s,output:s.configuration.__netcoredbgFileAppOutput,program:s.configuration.program});
        l.session||=s;save();assert.equal(l.session.id,s.id);assert.equal(s.type,'coreclr');
        l.output=s.configuration.__netcoredbgFileAppOutput;l.program=s.configuration.program;
        assert(within(root,l.output)&&within(root,l.program)&&same(path.dirname(l.program),l.output));l.base=path.dirname(path.dirname(l.output));save();}
    function logFiles(){const matches=[];function visit(d){if(!exists(d))return;for(const e of fs.readdirSync(d,{withFileTypes:true})){const f=path.join(d,e.name);if(e.isDirectory())visit(f);else if(e.isFile()&&e.name.endsWith('C# File Debugging.log'))matches.push(f);}}visit(path.join(root,'profile/logs'));return matches;}
    function outputText(){return logFiles().map(f=>fs.readFileSync(f,'utf8')).join('\n');}
    function queueEmpty(base){const count=name=>{const d=path.join(base,name);return exists(d)?fs.readdirSync(d).length:0;};return count('terminal-cleanup-v1')===0&&count('terminal-cleanup-staging-v1')===0&&count('terminal-cleanup-v1')===0;}
    function terminalReleased(l){return !exists(l.output)&&queueEmpty(l.base)&&!exists(l.output);}
    async function snapshot(l){const v={observedAtUtc:new Date().toISOString(),pid:l.pid,pidAlive:alive(l.pid),port:l.port,portBindable:await bindable(l.port),output:l.output,outputExists:exists(l.output),programExists:exists(l.program),terminalQueuesEmpty:queueEmpty(l.base),activeDebugSession:vscode.debug.activeDebugSession?.id};
        if(v.pidAlive){try{v.http=await probe(l.origin);v.httpOwned=v.http.pid===l.pid&&v.http.nonce===l.nonce;}catch(e){v.httpError=String(e);}}return v;}
    async function start(label){const l={label,source:path.join(root,'workspace/a.cs'),nonce:crypto.randomUUID(),port:await port(),captured:new Map()};l.origin='http://127.0.0.1:'+l.port;launches.push(l);byToken.set(l.nonce,l);save();
        fs.writeFileSync(l.source.replace(/\.cs$/,'.run.json'),JSON.stringify({profiles:{LifecycleHttp:{commandName:'Project',applicationUrl:l.origin,launchBrowser:false,environmentVariables:{LIFECYCLE_TOKEN:l.nonce,ASPNETCORE_ENVIRONMENT:'Development'}}}}));
        const document=await vscode.workspace.openTextDocument(l.source);await vscode.window.showTextDocument(document);assert(!document.isDirty);l.sourceSha256=sha(l.source);save();
        trace('public-command-start',{label,command:COMMAND});assert.equal(await vscode.commands.executeCommand(COMMAND),true);
        await until(()=>l.started&&l.session,label+' matching session');assert.equal(l.captured.size,1);assert(exists(l.program));
        await until(async()=>{try{l.response=await probe(l.origin);}catch(e){if(e instanceof assert.AssertionError)throw e;return false;}assert.equal(l.response.nonce,l.nonce);assert.equal(l.response.revision,'initial');assert.equal(l.response.value,42);if(l.pid)assert.equal(l.pid,l.response.pid);l.pid=l.response.pid;assert(alive(l.pid));const c=l.captured.get(l.session.id);if(c.pid)assert.equal(c.pid,l.pid);c.pid=l.pid;return true;},label+' real HTTP');
        l.httpReadyAtUtc=new Date().toISOString();save();trace('real-web-ready',state(l));return l;}
    async function stop(l){trace('exact-stop-request',{sessionId:l.session.id,pid:l.pid});await vscode.debug.stopDebugging(l.session);await until(()=>l.terminated,l.label+' exact termination');await until(()=>!alive(l.pid),l.label+' PID exit');await until(()=>bindable(l.port),l.label+' port free');await until(()=>terminalReleased(l),l.label+' original output absent and READY/STAGING/READY empty');trace('exact-retry-cleanup',state(l));}
    try{
        subscriptions.push(vscode.debug.onDidStartDebugSession(s=>observe(()=>{capture(s);const l=byToken.get(s.configuration?.env?.LIFECYCLE_TOKEN);if(l)l.started=true;trace('debug-start',{sessionId:s.id,token:s.configuration?.env?.LIFECYCLE_TOKEN});})));
        subscriptions.push(vscode.debug.onDidTerminateDebugSession(s=>observe(()=>{const l=byToken.get(s.configuration?.env?.LIFECYCLE_TOKEN);if(l){const c=l.captured.get(s.id);if(c)c.terminated=true;if(l.session?.id===s.id)l.terminated=true;save();}trace('debug-termination',{sessionId:s.id,token:s.configuration?.env?.LIFECYCLE_TOKEN});})));
        subscriptions.push(vscode.debug.registerDebugAdapterTrackerFactory('coreclr',{createDebugAdapterTracker(s){const l=byToken.get(s.configuration?.env?.LIFECYCLE_TOKEN);if(!l)return;observe(()=>capture(s));return{onWillReceiveMessage(m){trace('dap-to-adapter',{sessionId:s.id,message:m});},onDidSendMessage(m){observe(()=>{if(m.event==='process'&&m.body?.isLocalProcess){assert(Number.isSafeInteger(m.body.systemProcessId)&&m.body.systemProcessId>0);l.pid=m.body.systemProcessId;l.captured.get(s.id).pid=l.pid;save();}trace('dap-from-adapter',{sessionId:s.id,message:m});});},onExit(code,signal){trace('adapter-exit',{sessionId:s.id,code,signal});}};}}));
        const extension=vscode.extensions.getExtension(expected.extensionId);const dependency=vscode.extensions.getExtension('ms-dotnettools.vscode-dotnet-runtime');assert(extension&&dependency&&within(path.join(root,'extensions'),extension.extensionPath)&&within(path.join(root,'extensions'),dependency.extensionPath));assert.equal(dependency.packageJSON.version,expected.dependency.version);
        const metadata=JSON.parse(fs.readFileSync(path.join(extension.extensionPath,'package.json'),'utf8'));assert(metadata.__metadata&&metadata.netcoredbgBuild.localCandidate);assert.equal(metadata.version,expected.candidate.version);assert.equal(metadata.netcoredbgBuild.lifecycleBuildId,expected.candidate.buildId);assert.equal(`${process.platform}-${process.arch}`,expected.candidate.target);
        result.installedModules={};for(const name of MODULES){const actual=sha(path.join(extension.extensionPath,'.netcoredbg',name));assert.equal(actual,expected.candidate.ownedModules[name]);result.installedModules[name]=actual;}
        result.installed={path:extension.extensionPath,metadata:metadata.__metadata,build:metadata.netcoredbgBuild,dependencyPath:dependency.extensionPath};
        if(previous)result.immediateOldObservation=await snapshot(previous.launch);
        write(`host-${phase}.json`,{schema:1,nonce:expected.actualReload.nonce,extensionHostPid:process.pid,phase,installed:result.installed});
        await until(()=>exists(path.join(root,`ack-${phase}.json`)),'runner host lineage acknowledgement',30000);const ack=read(`ack-${phase}.json`);assert.equal(ack.nonce,expected.actualReload.nonce);assert.equal(ack.extensionHostPid,process.pid);result.editorPid=ack.editorPid;
        if(previous){assert.notEqual(previous.extensionHostPid,process.pid);assert.equal(previous.editorPid,ack.editorPid);}
        await extension.activate();assert((await vscode.commands.getCommands(true)).includes(COMMAND));
        if(!previous){
            const a=await start('A-before-actual-reload');await until(()=>/Terminal output recovery: scanned=\d+, attempted=\d+, removed=\d+/.test(outputText()),'initial recovery log');
            const guard=fs.mkdtempSync(path.join(path.dirname(a.output),'run-'));const guardPath=path.join(guard,'unmarked-reload-sentinel');assert(within(root,guardPath));fs.writeFileSync(guardPath,expected.actualReload.nonce);a.guard={directory:guard,path:guardPath,content:expected.actualReload.nonce,sha256:sha(guardPath)};
            const before=await snapshot(a);assert(before.pidAlive&&before.httpOwned&&!before.portBindable&&before.outputExists);assert.equal(sha(a.source),a.sourceSha256);save();
            const firstHostLogPaths=logFiles();assert(firstHostLogPaths.length===1);for(const file of firstHostLogPaths)assert(within(root,file));
            write('phase.json',{schema:1,phase:2,extensionHostPid:process.pid,editorPid:ack.editorPid,launch:state(a),before,firstHostLogPaths,sourceCommit:expected.candidate.sourceCommit});
            trace('before-actual-reload',{command:'workbench.action.reloadWindow',sessionId:a.session.id,pid:a.pid,origin:a.origin,nonce:a.nonce,output:a.output,before});
            write('before-reload.json',{command:'workbench.action.reloadWindow',extensionHostPid:process.pid,editorPid:ack.editorPid,atUtc:new Date().toISOString(),sessionId:a.session.id,before});
            void vscode.commands.executeCommand('workbench.action.reloadWindow').then(()=>trace('reload-command-returned',{}),e=>trace('reload-command-rejected',String(e)));
            await new Promise(()=>{});
        }else{
            const old=previous.launch;result.firstHost=previous.extensionHostPid;result.firstHostAliveAtPhase2=alive(previous.extensionHostPid);result.firstLaunch=old;result.beforeReload=previous.before;
            // Observe before further command recovery, and again after initial recovery has settled.
            let newHostLog;
            await until(()=>{const files=logFiles().filter(file=>!previous.firstHostLogPaths.some(first=>same(first,file)));assert(files.length<=1,'Expected exactly one fresh host logger path');if(!files.length)return false;newHostLog=files[0];return /^Terminal output recovery: scanned=\d+, attempted=\d+, removed=\d+$/m.test(fs.readFileSync(newHostLog,'utf8').replace(/\r/g,''));},'new host initial recovery completion in a distinct logger path (reused logger is unproven)');
            result.newHostInitialRecoveryLog={path:newHostLog,sha256:sha(newHostLog),text:fs.readFileSync(newHostLog,'utf8')};result.afterInitialRecovery=await snapshot(old);trace('old-resources-after-actual-reload',result.afterInitialRecovery);
            assert.equal(sha(old.source),old.sourceSha256);assert.equal(fs.readFileSync(old.guard.path,'utf8'),old.guard.content);
            const retry=await start('A-after-actual-reload');assert.notEqual(retry.output,old.output);assert.notEqual(retry.pid,old.pid);await stop(retry);
            result.retry=state(retry);result.finalOldObservation=await snapshot(old);result.unmarkedGuardPreserved=fs.readFileSync(old.guard.path,'utf8')===old.guard.content;assert(result.unmarkedGuardPreserved);
            const beforeRetry=result.afterInitialRecovery;
            result.reloadResourcesReleasedBeforeRetry=!beforeRetry.pidAlive&&beforeRetry.portBindable&&!beforeRetry.outputExists&&beforeRetry.terminalQueuesEmpty;
            result.mechanicsCompleted=true;result.success=result.reloadResourcesReleasedBeforeRetry;
            result.checks.push('actual reload command; same app PID; different extension host PIDs','normally installed candidate payload verified in both hosts','real public Web command and HTTP nonce/PID before reload and retry','exact retry Stop/PID/port/output cleanup','unmarked sibling preserved');
            trace('completed',result);write('result.json',result);
        }
    }catch(e){result.error=e.stack||String(e);trace('first-failure',result.error);write(`phase-${phase}-failure.json`,result);throw e;
    }finally{
        // Phase1 stays pending until the workbench destroys this actual extension host.
        for(const l of launches){for(const captured of l.captured?.values()||[]){if(!captured.terminated){try{await vscode.debug.stopDebugging(captured.session);}catch(e){trace('failure-exact-stop-error',{sessionId:captured.session.id,error:String(e)});}}}}
        for(const l of launches){const knownPids=new Set([l.pid,...(l.captured?[...l.captured.values()]:l.capturedSessions||[]).map(c=>c.pid)].filter(p=>Number.isSafeInteger(p)&&p>0));if([...knownPids].some(alive)){try{const body=await probe(l.origin);assert(knownPids.has(body.pid),'HTTP PID must match an owned captured process');assert.equal(body.nonce,l.nonce);await fetch(l.origin+'/shutdown?token='+encodeURIComponent(l.nonce),{method:'POST',signal:AbortSignal.timeout(2000)});trace('fixture-finally-http-shutdown',{pid:body.pid,nonce:l.nonce});}catch(e){trace('fixture-finally-shutdown-error',String(e));}}}
        for(const s of subscriptions)s.dispose();save();
    }
};
