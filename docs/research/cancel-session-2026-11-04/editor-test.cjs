'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const vscode = require('vscode');
const root = __dirname;
const runtimePath = path.resolve(root, '../worktree/scripts/variant/file-based-apps/runtime.cjs');
const result = { success: false, checks: [], sequence: [], errors: [], stops: [],
 scope: { realEditorApi: true, nativeAdapterFromNormallyInstalledVsix: true, runtimeLoadedDirectly: true,
 injectedProgressCancellation: true, directInstalledCommand: false, physicalF5: false, VSCodium: false, macOS: false, published: false } };
function record(event, detail) { result.sequence.push({event, detail, at:Date.now()}); fs.writeFileSync(path.join(root,'progress.json'), JSON.stringify(result,null,2)); }
async function until(predicate, label, ms=60000) {
 const end=Date.now()+ms;
 while(!predicate() && Date.now()<end) await new Promise(resolve=>setTimeout(resolve,10));
 assert(predicate(), `Timed out: ${label}`);
}
exports.run = async function () {
 const subscriptions=[];
 let releaseFirst;
 let cancel;
 let firstConfig;
 const sessions=[];
 const terminated=[];
 const stops=[];
 const dap=[];
 const logs=[];
 let earlyCleanup=false;
 let api;
 try {
  result.editorVersion=vscode.version;
  result.runtimeSha256=crypto.createHash('sha256').update(fs.readFileSync(runtimePath)).digest('hex');
  const extension=vscode.extensions.getExtension('dotnetdev-kr-custom.csharp-with-netcoredbg');
  assert(extension, 'Public extension must be normally installed');
  await extension.activate();
  result.installedVersion=extension.packageJSON.version;
  assert(JSON.parse(fs.readFileSync(path.join(extension.extensionPath,'package.json'),'utf8')).__metadata);
  result.checks.push('Public 11.7.18004 normally installed and activated in isolated profile');
  subscriptions.push(vscode.debug.onDidStartDebugSession(s=>{sessions.push(s);record('editor-start',{id:s.id,config:s.configuration});}));
  subscriptions.push(vscode.debug.onDidTerminateDebugSession(s=>{
   terminated.push(s);
   record('editor-terminate',{id:s.id,programExists:fs.existsSync(s.configuration.program)});
  }));
  subscriptions.push(vscode.debug.registerDebugAdapterTrackerFactory('coreclr',{createDebugAdapterTracker(session){ return {onDidSendMessage(message){dap.push({session:session.id,message});}}; }}));
  subscriptions.push(vscode.debug.registerDebugConfigurationProvider('coreclr',{
   async resolveDebugConfiguration(_folder, config) {
    if(config.__netcoredbgFileAppOutput && !firstConfig && config.program.startsWith(path.join(root,'storage'))) {
     firstConfig=config;record('provider-held-first-config',config);
     await new Promise(resolve=>{releaseFirst=resolve;});
     record('provider-released-first-config');
    }
    return config;
   }
  }));
  const source=path.join(root,'workspace/app.cs');
  const document=await vscode.workspace.openTextDocument(source);
  await vscode.window.showTextDocument(document);
  const context={globalStorageUri:vscode.Uri.file(path.join(root,'storage')),subscriptions:[],extension:{packageJSON:{netcoredbgBuild:{target:'win32-arm64'}}}};
  const facade={
   ProgressLocation:vscode.ProgressLocation, workspace:vscode.workspace,
   commands:{registerCommand(){return {dispose(){}};},executeCommand:(...args)=>vscode.commands.executeCommand(...args)},
   window:{get activeTextEditor(){return vscode.window.activeTextEditor;},
    createOutputChannel:()=>({append(value){logs.push(String(value));},appendLine(value){logs.push(String(value));},dispose(){}}),
    showErrorMessage(message){result.errors.push(message);record('runtime-error',message);return vscode.window.showErrorMessage(message);},
    async withProgress(_settings,callback){
     const emitter=new vscode.EventEmitter();
     const token={isCancellationRequested:false,onCancellationRequested:emitter.event};
     cancel=()=>{token.isCancellationRequested=true;record('progress-cancel');emitter.fire();};
     try{return await callback({report(value){record('runtime-progress',value);}},token);}finally{emitter.dispose();}
    }
   },
   debug:{
    onDidStartDebugSession:callback=>vscode.debug.onDidStartDebugSession(callback),
    onDidTerminateDebugSession:callback=>vscode.debug.onDidTerminateDebugSession(callback),
    startDebugging:(...args)=>vscode.debug.startDebugging(...args),
    async stopDebugging(session){
     assert(session);stops.push(session);result.stops.push(session.id);record('runtime-stop-request',session.id);
     await vscode.debug.stopDebugging(session);
     const ended=terminated.some(s=>s.id===session.id);
     const exists=fs.existsSync(session.configuration.program);
     if(!ended&&!exists)earlyCleanup=true;
     record('runtime-stop-resolved',{id:session.id,terminated:ended,programExists:exists});
     setTimeout(()=>{
      const ended=terminated.some(s=>s.id===session.id);
      const exists=fs.existsSync(session.configuration.program);
      if(!ended&&!exists)earlyCleanup=true;
      record('post-stop-resolve-output',{sessionId:session.id,terminated:ended,programExists:exists});
     },50);
    }
   }
  };
  api=require(runtimePath).activate(context,{vscode:facade});
  subscriptions.push(...context.subscriptions);
  const first=api.debugActiveFile();
  await until(()=>releaseFirst,'first real start reaches configuration provider');
  assert(fs.existsSync(firstConfig.program));
  cancel();
  assert.equal(await Promise.race([first,new Promise(resolve=>setTimeout(()=>resolve('pending'),5000))]),false);
  record('foreground-cancel-returned');
  assert(fs.existsSync(firstConfig.program));
  result.checks.push('Injected cancellation releases foreground command before real start API settles and preserves pending DLL');
  releaseFirst();
  await until(()=>stops.length===1,'late actual session stopped');
  await until(()=>terminated.some(s=>s.id===stops[0].id),'actual late session termination');
  assert.equal(earlyCleanup,false,'Stop API completion must not delete DLL before the actual termination event');
  assert.equal(result.sequence.find(x=>x.event==='editor-terminate'&&x.detail.id===stops[0].id).detail.programExists,true,
   'DLL must remain until the termination event is observed');
  await until(()=>!fs.existsSync(firstConfig.__netcoredbgFileAppOutput),'late output removed after stop');
  const firstSession=sessions.find(s=>s.id===stops[0].id);
  assert(firstSession);
  assert.equal(firstSession.configuration.program,firstConfig.program);
  assert.equal(firstSession.configuration.__netcoredbgFileAppOutput,firstConfig.__netcoredbgFileAppOutput);
  assert.equal(result.errors.length,0);
  result.checks.push('Real start event preserves ownership fields; exactly its session is stopped and output is cleaned');
  vscode.debug.addBreakpoints([new vscode.SourceBreakpoint(new vscode.Location(document.uri,new vscode.Position(2,0)))]);
  assert.equal(await api.debugActiveFile(),true);
  await until(()=>dap.some(x=>x.message.event==='stopped'&&x.message.body?.reason==='breakpoint'),'retry source breakpoint');
  const breakpoint=dap.find(x=>x.message.event==='stopped'&&x.message.body?.reason==='breakpoint');
  const retry=sessions.find(s=>s.id===breakpoint.session);
  assert(retry);
  assert.notEqual(retry.id,firstSession.id);
  assert.notEqual(retry.configuration.program,firstConfig.program);
  assert(fs.existsSync(retry.configuration.program));
  const frames=(await retry.customRequest('stackTrace',{threadId:breakpoint.message.body.threadId})).stackFrames;
  assert.equal(frames[0].line,3);
  const evaluated=await retry.customRequest('evaluate',{frameId:frames[0].id,expression:'answer',context:'watch'});
  assert.equal(evaluated.result,'40');
  assert.equal(stops.length,1);
  result.checks.push('Same-file retry uses fresh output and real netcoredbg breakpoint with answer=40');
  await vscode.debug.stopDebugging(retry);
  await until(()=>terminated.some(s=>s.id===retry.id),'retry termination');
  await until(()=>!fs.existsSync(retry.configuration.__netcoredbgFileAppOutput),'retry output cleanup');
  assert.equal(result.errors.length,0);
  result.checks.push('Normal retry termination cleans output without a cancellation error');
  result.success=true;
 } catch(error){result.error=error.stack||String(error);throw error;}
 finally{
  result.logs=logs;
  for(const sub of subscriptions.reverse())sub.dispose();
  fs.writeFileSync(path.join(root,'editor-result.json'),JSON.stringify(result,null,2)+'\n');
 }
};
