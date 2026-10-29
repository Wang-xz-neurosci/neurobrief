"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const escape = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const safeUrl = (value) => { try { const u = new URL(value); return u.protocol === "https:" ? escape(u.href) : "#"; } catch { return "#"; } };
  const url = new URL(location.href);
  const allowedViews = ["all", "saved", "language", "cognition", "structure-function", "brain-disorders", "rest-naturalistic"];
  const legacyView = {"coupling":"structure-function", "white-matter":"structure-function", "summary-preview":"all"};
  const requestedView = legacyView[url.searchParams.get("topic")] || url.searchParams.get("topic");
  const state = {
    view: allowedViews.includes(requestedView) ? requestedView : "all",
    days: ["7", "30", "90", "all", "today"].includes(url.searchParams.get("days")) ? url.searchParams.get("days") : "30",
    q: url.searchParams.get("q") || "", type: "all", method: "all", journalScope: "all", sort: ["published","added"].includes(url.searchParams.get("sort")) ? url.searchParams.get("sort") : "published", limit: 15,
  };
  const beijingDate = new Intl.DateTimeFormat("en-CA", {timeZone:"Asia/Shanghai", year:"numeric",month:"2-digit",day:"2-digit"});
  const today = beijingDate.format(new Date());
  let data, filtered = [], saved = new Set(), toastTimer;
  let manifest, catalogPromise, searchPromise, searchIndex, searchFailed=false;
  const detailPromises = new Map();
  try { const items = JSON.parse(localStorage.getItem("neurobrief-saved-v1") || "[]"); if (Array.isArray(items)) saved = new Set(items.filter(x => typeof x === "string")); } catch { /* Storage is optional. */ }
  function toast(message) { $("toast").textContent = message; $("toast").hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { $("toast").hidden = true; }, 3000); }
  function withinDays(p, days) {
    if (days === "today") {
      const seen = new Date(p.first_seen);
      return Number.isFinite(seen.getTime()) && beijingDate.format(seen) === today;
    }
    if (days === "all") return true;
    if (!p.published || p.published > today) return false;
    const lower = new Date(today + "T00:00:00Z"); lower.setUTCDate(lower.getUTCDate() - Number(days) + 1);
    return p.published >= lower.toISOString().slice(0, 10);
  }
  const topicMap = {};
  function searchable(p) {
    return [p.title,p.authors,p.journal,p.doi,p.abstract ?? searchIndex?.[p.id],...p.methods,...p.tracts,...p.topics.map(t => topicMap[t]?.name || t)].join(" ").toLocaleLowerCase();
  }
  function filterPapers() {
    const terms = state.q.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    return data.papers.filter(p =>
      (state.view === "all" || (state.view === "saved" ? saved.has(p.id) : p.topics.includes(state.view))) &&
      withinDays(p, state.days) &&
      (state.type === "all" || (state.type === "preprint" ? p.is_preprint : state.type === "journal" ? !p.is_preprint : p.is_review)) &&
      (state.method === "all" || p.methods.includes(state.method)) &&
      (state.journalScope === "all" || p.is_monitored_journal) &&
      (!terms.length || terms.every(term => searchable(p).includes(term)))
    ).sort((a,b) => {
      if (state.sort === "added") return (new Date(b.first_seen).getTime() - new Date(a.first_seen).getTime()) || a.title.localeCompare(b.title);
      const key = state.sort === "added" ? "first_seen" : "published";
      return (b[key] || "").localeCompare(a[key] || "") || a.title.localeCompare(b.title);
    });
  }
  function card(p) {
    const stamp = p.published ? `<span class="day">${escape(p.published.slice(5).replace("-", "."))}</span><span class="year">${escape(p.published.slice(0,4))}</span>` : '<span class="year">日期未提供</span>';
    const topicTags = p.topics.map(t => `<span class="tag ${escape(t)}">${escape(topicMap[t]?.short_name || t)}</span>`).join("");
    const methods = p.methods.slice(0,3).map(m => `<span class="tag method">${escape(m)}</span>`).join("");
    const matched = [...new Set(Object.values(p.evidence).flat())];
    const abstract = p.abstract ?? p.abstract_preview ?? "";
    const overview = p.summary_zh ? `<div class="summary-zh"><span>AI 中文概览</span><p>${escape(p.summary_zh)}</p></div>` : `${p.has_abstract || p.abstract ? '<div class="summary-zh"><span>原始摘要（暂无中文概览）</span><p>'+escape(abstract)+'</p></div>' : '<div class="summary-zh"><p>来源尚未提供摘要，本文仅依据题目暂时收录，请结合原文核实。</p></div>'}`;
    return `<article class="paper"><div class="paper-date" aria-label="发表日期 ${escape(p.published || '未提供')}">${stamp}</div><div class="paper-body"><div class="paper-meta"><span class="journal">${escape(p.journal)}</span><span class="type-badge ${p.is_preprint ? 'preprint' : ''}">${p.is_preprint ? '预印本' : '期刊文章'}</span>${p.is_review ? '<span class="type-badge">综述</span>' : ''}</div><h3><a href="${safeUrl(p.url)}" target="_blank" rel="noopener">${escape(p.title)}</a></h3><div class="authors" title="${escape(p.authors)}">${escape(p.authors || '来源未提供作者')}</div>${overview}<div class="paper-tags">${topicTags}${methods}</div><details data-paper-id="${escape(p.id)}"><summary>原始摘要与收录依据</summary>${detailContent(p)}</details></div><button class="bookmark" data-id="${escape(p.id)}" aria-pressed="${saved.has(p.id)}" aria-label="${saved.has(p.id) ? '取消收藏' : '收藏'}：${escape(p.title)}" title="${saved.has(p.id) ? '取消本机收藏' : '保存到本机收藏'}">${saved.has(p.id) ? '◆' : '◇'}</button></article>`;
  }
  function detailContent(p) {
    if (p.abstract === undefined) return '<div class="detail-content"><p>正在读取原始摘要…</p></div>';
    const abstract=p.abstract || "来源尚未提供摘要，暂无法生成中文概览，请点击题目阅读原文。";
    const matched=[...new Set(Object.values(p.evidence).flat())];
    return `<div class="detail-content"><p class="full-abstract">${escape(abstract)}</p><p class="evidence">检索命中：${escape(matched.join(' · ') || '匹配本方向检索式，详见原始数据')}。<br>方法标签按标题与摘要推断，优先使用方法部分，并非人工核实。本站首次收录：${escape(p.first_seen ? beijingDate.format(new Date(p.first_seen)) : '—')}；来源收录：${escape(p.indexed || '未提供')}。</p>${p.tracts.length ? `<p class="evidence">相关纤维束：${escape(p.tracts.join(' · '))}</p>` : ''}<div class="detail-links"><a href="${safeUrl(p.url)}" target="_blank" rel="noopener">前往原文 ↗</a><a href="${safeUrl(p.source_url)}" target="_blank" rel="noopener">Europe PMC 记录 ↗</a></div><p class="doi-line">${p.doi ? 'DOI: ' + escape(p.doi) : '来源编号: ' + escape(p.source + ':' + p.source_id)}</p></div>`;
  }
  function syncUrl() {
    const u = new URL(location.href);
    for (const [key, value, defaultValue] of [["topic",state.view,"all"],["days",state.days,"30"],["q",state.q,""],["sort",state.sort,"published"]]) {
      if (value === defaultValue) u.searchParams.delete(key); else u.searchParams.set(key,value);
    }
    u.searchParams.delete("summary");
    try { history.replaceState(null,"",u); } catch { /* Some browsers restrict history on local HTML files. */ }
  }
  function render() {
    if (!data) return;
    if (state.q.trim() && !embedded && (!searchIndex || data.partial)) {
      $("result-count").textContent="检索索引载入中";
      $("papers").innerHTML='<div class="loading">'+(searchFailed?'摘要检索暂时未能载入，请重新载入页面。':'正在准备完整的标题与摘要检索…')+'</div>';
      $("export-button").disabled=true;$("load-more").hidden=true;
      if (!searchFailed) ensureSearch().then(render).catch(()=>{searchFailed=true;render();});
      return;
    }
    if (!data) return;
    filtered = filterPapers();
    $("papers").setAttribute("aria-busy", "false");
    $("result-count").textContent = data.partial ? "正在补齐完整列表" : `${filtered.length} 篇`;
    $("list-title").firstChild.textContent = state.view === "saved" ? "本机收藏 " : "最新文献 ";
    const current = topicMap[state.view];
    $("page-title").innerHTML = `${escape(current?.short_name || (state.view === 'saved' ? '我的阅读清单' : '文献观察'))}<span class="title-dot">.</span>`;
    $("page-description").textContent = current?.description || (state.view === "saved" ? "留住值得再读的研究。收藏仅保存在当前浏览器。" : "不知道该怎么做？来看最新的前沿进展。");
    document.querySelectorAll("[data-view]").forEach(b => { const active = b.dataset.view === state.view; b.classList.toggle("active", active); b.setAttribute("aria-pressed", active); });
    document.querySelectorAll("[data-days]").forEach(b => { const active = b.dataset.days === state.days; b.classList.toggle("selected", active); b.setAttribute("aria-pressed", active); });
    $("count-saved").textContent = data.papers.filter(p=>saved.has(p.id)).length;
    $("export-button").disabled = data.partial || filtered.length === 0;
    if (filtered.length) {
      $("papers").innerHTML = filtered.slice(0,state.limit).map(card).join("");
    } else if (data.partial) {
      $("papers").innerHTML='<div class="loading">正在补齐该筛选范围的文献…</div>';
    } else {
      const emptySaved = state.view === "saved" && !data.papers.some(p=>saved.has(p.id));
      $("papers").innerHTML = `<div class="empty"><strong>${emptySaved ? '给下一次阅读留个位置。' : '暂时没有匹配的文献。'}</strong><p>${emptySaved ? '点击论文右侧的 ◇，把它加入当前浏览器的收藏。' : '可以扩大时间范围，或减少关键词和方法筛选。'}</p><button id="reset-filters">${emptySaved ? '浏览全部文献' : '清除筛选'}</button></div>`;
      $("reset-filters").addEventListener("click", () => { if (emptySaved) state.view = "all"; state.days = "all"; state.q = ""; state.type = "all"; state.method = "all"; state.journalScope = "all"; state.limit = 15; $("search").value = ""; $("type").value = "all"; $("method").value = "all"; $("journal-scope").value = "all"; render(); });
    }
    $("load-more").hidden = data.partial || filtered.length <= state.limit;
    $("load-more").innerHTML = `继续阅读 · 还有 ${Math.max(0,filtered.length-state.limit)} 篇 <span>↓</span>`;
    syncUrl();
  }
  function saveBookmark(button) {
    const id = button.dataset.id;
    if (saved.has(id)) saved.delete(id); else saved.add(id);
    let persisted = true;
    try { localStorage.setItem("neurobrief-saved-v1", JSON.stringify([...saved])); } catch { persisted = false; }
    if (state.view === "saved") render();
    else { button.setAttribute("aria-pressed", saved.has(id)); button.textContent = saved.has(id) ? "◆" : "◇"; button.title = saved.has(id) ? "取消本机收藏" : "保存到本机收藏"; const paper = data.papers.find(p=>p.id===id); button.setAttribute("aria-label", `${saved.has(id) ? '取消收藏' : '收藏'}：${paper?.title || ''}`); $("count-saved").textContent = data.papers.filter(p=>saved.has(p.id)).length; }
    toast(persisted ? (saved.has(id) ? "已保存到本机收藏" : "已移出收藏") : "浏览器禁止保存；收藏仅在本次打开时有效");
  }
  async function exportRis() {
    if (!data || data.partial) return;
    const exportVersion=data.version, selected=[...filtered];
    const button=$("export-button");button.disabled=true;
    try {
    let exportPapers=selected;
    if (!embedded) {
      const full=await readJSON(manifest.full,true);
      if (data.version!==exportVersion) throw new Error("Dataset changed");
      const byId=new Map(full.papers.map(p=>[p.id,p]));
      exportPapers=selected.map(p=>byId.get(p.id));
      if (exportPapers.some(p=>!p)) throw new Error("Incomplete export");
    }
    const clean = (s) => String(s || "").replace(/[\r\n]+/g," ");
    const records = exportPapers.map(p => ["TY  - " + (p.is_preprint ? "UNPB" : "JOUR"),"TI  - " + clean(p.title),...p.authors.split(/,\s*/).filter(Boolean).map(a=>"AU  - " + clean(a)),"JO  - " + clean(p.journal),...(p.published ? ["PY  - " + p.published.slice(0,4),"DA  - " + p.published.replaceAll("-","/")] : []),...(p.doi ? ["DO  - " + clean(p.doi)] : []),"UR  - " + clean(p.url),...(p.abstract ? ["AB  - " + clean(p.abstract)] : []),...p.topics.map(t=>"KW  - " + topicMap[t].name),"ER  - ",""].join("\r\n")).join("\r\n");
    const blob = new Blob([records],{type:"application/x-research-info-systems;charset=utf-8"});
    const objectUrl = URL.createObjectURL(blob); const a = document.createElement("a"); a.href=objectUrl; a.download=`neurobrief-${today}-${filtered.length}.ris`; document.body.append(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(objectUrl),30000); toast(`已导出 ${exportPapers.length} 篇，可导入 Zotero`);
    } catch {toast("导出资料暂时未能读取，请稍后重试。");} finally {button.disabled=false;}
  }
  document.querySelectorAll("[data-view]").forEach(b=>b.addEventListener("click",()=>{state.view=b.dataset.view;state.limit=15;render();}));
  document.querySelectorAll("[data-days]").forEach(b=>b.addEventListener("click",()=>{state.days=b.dataset.days;state.limit=15;render();}));
  $("search").value=state.q;
  $("sort").value=state.sort;
  $("search").addEventListener("input",e=>{state.q=e.target.value;state.limit=15;render();});
  for (const key of ["type","method","sort"]) $(key).addEventListener("change",e=>{state[key]=e.target.value;state.limit=15;render();});
  $("journal-scope").addEventListener("change",e=>{state.journalScope=e.target.value;state.limit=15;render();});
  $("papers").addEventListener("click",e=>{const b=e.target.closest(".bookmark");if(b)saveBookmark(b);});
  $("papers").addEventListener("toggle",async e=>{
    const element=e.target;
    if(element.tagName!=="DETAILS"||!element.open) return;
    const p=data?.papers.find(p=>p.id===element.dataset.paperId);
    if(!p||p.abstract!==undefined) return;
    const version=data.version;
    try {
      const key=version+":"+p.detail_bucket;
      if(!detailPromises.has(key)) detailPromises.set(key,readJSON(manifest.details+p.detail_bucket+".json",false));
      const records=await detailPromises.get(key);
      if(!records[p.id]||data.version!==version) throw new Error("Changed or missing detail");
      Object.assign(p,records[p.id]);
      if(element.isConnected) element.querySelector(".detail-content").outerHTML=detailContent(p);
    } catch {
      detailPromises.delete(version+":"+p.detail_bucket);
      if(element.isConnected) element.querySelector(".detail-content").innerHTML='<p>原始摘要暂时未能读取；可关闭后再展开，或点击题目阅读原文。</p>';
    }
  },true);
  $("load-more").addEventListener("click",()=>{state.limit+=15;render();});
  $("export-button").addEventListener("click",exportRis);
  $("about-button").addEventListener("click",()=>$("about-dialog").showModal());
  $("close-about").addEventListener("click",()=>$("about-dialog").close());
  $("about-dialog").addEventListener("click",e=>{if(e.target===$("about-dialog"))$("about-dialog").close();});
  // A mobile-accessible copy of the source information link.
  const aboutFooter = document.createElement("button"); aboutFooter.textContent="数据来源与收录说明 ↗"; aboutFooter.className="footer-about"; aboutFooter.addEventListener("click",()=>$("about-dialog").showModal()); document.querySelector("footer .footer-links").append(aboutFooter);
  document.addEventListener("keydown",e=>{if(e.key==="/"&&!/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)&&!$("about-dialog").open){e.preventDefault();$("search").focus();}});
  const embedded = document.getElementById("snapshot-data");
  function installDataset(d) {
    if (!d || !Array.isArray(d.papers) || !Array.isArray(d.topics)) throw new Error("Invalid dataset");
    if(data?.version!==d.version){searchIndex=undefined;searchPromise=undefined;searchFailed=false;detailPromises.clear();}
    data=d; for(const t of data.topics)topicMap[t.id]=t;
    $("papers").setAttribute("aria-busy","false");
    $("journal-guide-title").textContent=`关注期刊如何选择？查看 ${data.monitored_journals.length} 本名单`;
    $("journal-list").innerHTML=`<p>${data.monitored_journals.map(j=>escape(j.name)).join(" · ")}</p>`;
    $("count-all").textContent=data.total ?? data.papers.length;$("stat-total").textContent=data.total ?? data.papers.length;
    $("stat-week").textContent=data.partial ? "—" : data.papers.filter(p=>withinDays(p,"7")).length;
    for(const t of data.topics)$("count-"+t.id).textContent=data.topic_counts?.[t.id] ?? data.papers.filter(p=>p.topics.includes(t.id)).length;
    const stamp=new Date(data.updated_at);
    $("stat-updated").textContent=new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",month:"2-digit",day:"2-digit"}).format(stamp)+" 已更新";
    $("stat-updated").title=`最近成功采集：${stamp.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})}（北京时间）`;
    const intakeDay=data.update_summary?.date;
    $("update-mode").textContent=`${intakeDay===today ? "本日" : intakeDay ? intakeDay.slice(5).replace("-","/")+" " : "本次"}收录文献 ${data.update_summary?.new_papers ?? 0} 篇`;
    $("update-mode").title="按北京时间统计该更新日首次进入本站的去重文献；包含延迟收录的文章，不等于当天发表数量。";
    $("about-meta").textContent=`首次回溯起点：${data.initial_coverage_start}。最近成功采集：${stamp.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})}（北京时间）。`;
    if(data.update_mode==="github-actions"&&!embedded){ $("about-update").textContent="由 GitHub Actions 每天北京时间 03:00 左右自动采集并部署；调度和来源收录可能延迟。每日新收录数按北京时间统计去重后的首次收录记录，同一天重复运行不重复计数。“已更新”表示采集成功，并不表示出版方今天发表的文章已经全部入库。若审查或中文概览尚未完成，后续任务会接续补齐。"; }
    const age=(Date.now()-stamp.getTime())/86400000;
    if(age>2){$("notice").hidden=false;$("notice").textContent=`文献库已超过 ${Math.floor(age)} 天未成功更新。当前显示已保存的数据，请检查更新任务。`;}
    render();
  }
  async function readJSON(path,compressed=false,cache="default") {
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),45000);
    const useGzip=compressed && "DecompressionStream" in window;
    try {
      const response=await fetch(path+(useGzip?".gz":""),{cache,signal:controller.signal});
      if(useGzip && response.status===404)return await readJSON(path,false,cache);
      if(!response.ok)throw new Error(`HTTP ${response.status}`);
      return await (useGzip?new Response(response.body.pipeThrough(new DecompressionStream("gzip"))):response).json();
    } finally {clearTimeout(timer);}
  }
  // Optional, bounded storage: a denied/full browser cache never blocks reading.
  let database;
  function openCache(){
    if(database)return database;
    database=new Promise(resolve=>{
      if(!window.indexedDB){resolve(null);return;}
      let done=false;const finish=value=>{if(!done){done=true;clearTimeout(timer);resolve(value);}};
      const timer=setTimeout(()=>finish(null),1200);
      try {const request=window.indexedDB.open("neurobrief-reading-cache",1);
        request.onupgradeneeded=()=>request.result.createObjectStore("catalog");
        request.onsuccess=()=>{request.result.onversionchange=()=>request.result.close();finish(request.result);};
        request.onerror=()=>finish(null);request.onblocked=()=>finish(null);
      } catch {finish(null);}
    });return database;
  }
  async function cachedCatalog(value){
    const db=await openCache();if(!db)return null;
    return new Promise(resolve=>{
      const timer=setTimeout(()=>resolve(null),1200);
      try {const tx=db.transaction("catalog",value?"readwrite":"readonly"),store=tx.objectStore("catalog");
        const request=value?store.put(value,"latest"):store.get("latest");
        request.onsuccess=()=>{clearTimeout(timer);resolve(value||request.result||null);};
        request.onerror=()=>{clearTimeout(timer);resolve(null);};
      } catch {clearTimeout(timer);resolve(null);}
    });
  }
  async function ensureSearch(){
    if(embedded)return;
    if(catalogPromise)await catalogPromise;
    if(data.partial)throw new Error("Catalog unavailable");
    if(searchIndex)return;
    if(!searchPromise){
      const version=data.version;
      searchPromise=readJSON(manifest.search,true).then(index=>{
        if(data.version!==version)throw new Error("Dataset changed");
        searchIndex=index;
      });
    }
    return searchPromise;
  }
  function loadFailure(error){
    console.error("Dataset load failed:",error);
    $("papers").setAttribute("aria-busy","false");
    if(data){
      $("notice").hidden=false;
      $("notice").textContent=data.partial?"完整列表暂时未能载入，当前可阅读首页文献。请稍后重新载入。":"最新数据暂时未能载入，当前显示已保存的文献。";
    } else {
      $("export-button").disabled=true;
      $("papers").innerHTML='<div class="empty"><strong>文献数据暂时无法读取。</strong><p>请检查网络后重新载入。</p><button id="retry">重新载入</button></div>';
      $("retry").addEventListener("click",()=>location.reload());
    }
  }
  async function start(){
    if(embedded){installDataset(JSON.parse(embedded.textContent));return;}
    const initial=document.getElementById("initial-data");
    if(initial){const first=JSON.parse(initial.textContent);manifest=first.manifest;installDataset(first);}
    const cached=await cachedCatalog();
    if(cached && (!data || cached.version===data.version)){
      if(!manifest)manifest={version:cached.version,catalog:`./assets-data/${cached.version}/catalog.json`,search:`./assets-data/${cached.version}/search.json`,full:`./assets-data/${cached.version}/full.json`,details:`./assets-data/${cached.version}/`};
      installDataset(cached);
    }
    let latest;
    try {latest=await readJSON("./manifest.json",false,"no-cache");}
    catch(error){
      if(!manifest)throw error;
      latest=manifest;
    }
    if(cached?.version===latest.version){manifest=latest;installDataset(cached);return;}
    if(!data?.partial && data?.version===latest.version)return;
    const catalog=await readJSON(latest.catalog,true);
    if(catalog.version!==latest.version)throw new Error("Mismatched catalog version");
    manifest=latest;
    installDataset(catalog);
    cachedCatalog(catalog);
  }
  catalogPromise=Promise.resolve().then(start);
  catalogPromise.catch(loadFailure);

})();
