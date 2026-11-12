const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
const full=fs.readFileSync('research_os/static/app.js','utf8');const source=full.slice(0,full.lastIndexOf('\n(async()=>'));
function setup(fetcher){
 const root={innerHTML:''},message={textContent:'',className:''};const handlers={};
 const context=vm.createContext({URLSearchParams,AbortController,Response,TextEncoder,console,setTimeout:(fn,ms)=>{const t=setTimeout(fn,ms);t.unref();return t},clearTimeout,fetch:fetcher,document:{querySelector:s=>s==='#app'?root:message,addEventListener:(name,handler)=>handlers[name]=handler}});
 vm.runInContext(source,context);vm.runInContext("state.user=true;state.csrf='test-csrf'",context);return {context,root,message,handlers,run:code=>vm.runInContext(code,context)};
}
const json=data=>new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
test('HTML server errors are reported with endpoint and status, not generic Safari syntax error',async()=>{
 const h=setup(async()=>new Response('<html>Bad Gateway</html>',{status:502}));
 await assert.rejects(h.run("api('/api/items')"),/api\/items.*HTTP 502.*JSON/);
});
test('empty success responses are handled explicitly',async()=>{
 const h=setup(async()=>new Response(null,{status:204}));await assert.rejects(h.run("api('/api/items')"),/응답이 비어/);
});
test('navigation renders immediately while a request is still pending',async()=>{
 let resolve;const pending=new Promise(r=>resolve=r);const h=setup(path=>path.startsWith('/api/items')?pending:Promise.resolve(json({sources:[],runs:[],pending:[]})));
 h.run("state.tab='news'");const loading=h.run('load()');assert.match(h.root.innerHTML,/Newsroom/);assert.match(h.root.innerHTML,/자료를 불러오는 중/);
 resolve(json({items:[],total:0}));await loading;assert.equal(h.run('state.loading'),false);
});
test('one failed section does not discard other sections or block menu changes',async()=>{
 const paths=[];const h=setup(async path=>{paths.push(path);return path==='/api/sources'?new Response('upstream error',{status:503}):json({items:[],total:0})});h.run("state.tab='news'");await h.run('load()');
 assert.match(h.root.innerHTML,/Newsroom/);assert.match(h.root.innerHTML,/HTTP 503/);assert.equal(h.run('state.loading'),false);assert.equal(paths.some(p=>p==='/api/economy'),false);assert.equal(paths.some(p=>p==='/api/overview'),false);
 h.run("state.tab='reports'");await h.run('load()');assert.match(h.root.innerHTML,/Research library/);
});
test('late response cannot replace a newly selected tab',async()=>{
 let resolve;const slow=new Promise(r=>resolve=r);const h=setup(path=>path.startsWith('/api/items')?slow:Promise.resolve(json(path==='/api/sources'?{sources:[],runs:[],pending:[]}:{keywords:[],eligible_sources:[],excluded_sources:[],indicators:[],events:[],warning:'test'})));
 h.run("state.tab='news'");const old=h.run('load()');h.run("state.tab='signals'");await h.run('load()');assert.match(h.root.innerHTML,/Signal monitor/);
 resolve(json({items:[],total:0}));await old;assert.match(h.root.innerHTML,/Signal monitor/);assert.equal(h.run('state.data'),null);
});
test('malformed timestamps do not crash the workspace renderer',()=>{const h=setup(async()=>json({}));assert.equal(h.run("date('not-a-date')"),'날짜 형식 미확인')});

test('public workspace offers optional private login rather than mandatory login',()=>{
 const h=setup(async()=>json({}));h.run("state.authenticated=false;state.tab='news';render()");assert.match(h.root.innerHTML,/개인 보관함 로그인/);assert.doesNotMatch(h.root.innerHTML,/id="login-form"/);
});

test('empty database explains collection never ran instead of implying refresh collects',async()=>{
 const h=setup(async path=>json(path==='/api/sources'?{sources:[],runs:[],pending:[],collection_state:'never_run'}:{items:[],total:0}));h.run("state.tab='news'");await h.run('load()');assert.match(h.root.innerHTML,/GitHub Actions/);assert.match(h.root.innerHTML,/새로고침은 수집을 시작하지 않습니다/);
});
function setupResearch(){const h=setup(async()=>json({}));vm.runInContext(fs.readFileSync('research_os/static/research.js','utf8').replace(/\nrender\(\);\s*$/,''),h.context);return h}
test('research charts preserve missing observations as gaps',()=>{const h=setupResearch();const html=h.run("plot([{date:'2026-01-01',value:1},{date:'2026-01-02',value:null},{date:'2026-01-03',value:3}])");assert.match(html,/M18\.00/);assert.match(html,/M882\.00/);assert.doesNotMatch(html,/L882\.00/)});
test('new research navigation and guest privacy remain functional',()=>{const h=setupResearch();h.run("state.authenticated=false;state.tab='research-archive';state.researchArchive={projects:[{name:'PRIVATE PROJECT'}]};research.output={secret:'PRIVATE RESULT'};render()");assert.match(h.root.innerHTML,/로그인/);assert.doesNotMatch(h.root.innerHTML,/PRIVATE PROJECT|PRIVATE RESULT/);assert.match(h.root.innerHTML,/>10<\/span>/)});
test('private research state is cleared with authentication state',()=>{const h=setupResearch();h.run("state.researchArchive={notes:['private']};state.eventData={my_note:'private'};research.output={private:true};clearResearchPrivate()");assert.equal(h.run('state.researchArchive'),null);assert.equal(h.run('state.eventData'),null);assert.equal(h.run('research.output'),null)});
test('missing research history produces an explanation, not invented chart data',()=>{const h=setupResearch();h.run("state.tab='trends';state.researchData=null;render()");assert.match(h.root.innerHTML,/데이터 축적 중/);assert.doesNotMatch(h.root.innerHTML,/<svg/)});
test('JANUS results are isolated from macro forecasts and cleared on logout',()=>{const h=setupResearch();h.run("research.output={type:'macro'};research.janusOutput={type:'trading'}");assert.equal(h.run('research.output.type'),'macro');assert.equal(h.run('research.janusOutput.type'),'trading');h.run('clearResearchPrivate()');assert.equal(h.run('research.janusOutput'),null)});
