// Лаборатория сайтов · интерфейс второго цеха
const siteUrl = (s, sub, f) => `/files/sites/${s.id}/${sub}/${String(f).split("/").map(encodeURIComponent).join("/")}`;
const SITE_TABS = [["brief", "Бриф"], ["research", "Ресёрч"], ["concepts", "Концепции"], ["photos", "Фото и видео"], ["prompt", "Промпт"], ["build", "Сборка"]];
const GOALS = ["Оставить заявку", "Позвонить", "Записаться", "Купить", "Запросить расчёт", "Написать в мессенджер"];

async function loadSites() {
  S.sites = await api(`/api/sites?${lq()}`);
  S.lab = S.sites.lab.id;
  try { localStorage.setItem("cf.lab", S.lab); } catch { /* ok */ }
}
async function loadSite(id) { S.site = await api(`/api/sites/${id}`); }

function swatches(colors) {
  return `<div class="swatches">${(colors || []).map((c) => `<div class="sw"><i style="background:${hexc(c.hex)}"></i><b>${esc(c.hex)}</b><span>${esc(c.role || c.name || "")}</span></div>`).join("")}</div>`;
}
const listHtml = (arr) => (arr || []).length ? `<ul>${arr.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : `<p class="meta">—</p>`;

// масштабирование живых превью (iframe 1440px вписывается в ширину карточки)
function fitFrames(root = document) {
  root.querySelectorAll(".frame").forEach((w) => {
    const f = w.querySelector("iframe"); if (!f) return;
    const fw = +f.getAttribute("width"), fh = +f.getAttribute("height");
    const sc = w.clientWidth / fw; f.style.transform = `scale(${sc})`; w.style.height = fh * sc + "px";
  });
}
window.addEventListener("resize", () => fitFrames());
const frame = (src, w = 1440, h = 900, cls = "") =>
  `<div class="frame ${cls}"><iframe src="${src}" width="${w}" height="${h}" sandbox="allow-scripts" referrerpolicy="no-referrer"></iframe></div>`;

// ---------------------------------------------------------------- список проектов
function renderSites(v, top) {
  const L = S.sites;
  if (!L) { v.innerHTML = `<div class="panel">Загружаю…</div>`; loadSites().then(render); return; }
  top.innerHTML = `<div><div class="eyebrow">Лаборатория сайтов · направление</div><h1>${esc(L.lab.name)}</h1>
    <div class="sub">${esc(L.lab.description || "")}</div></div>
    <button class="btn" id="toLabCtx">Контекст направления</button>`;
  v.innerHTML = `${spaceCards(L.labs, L.lab.id, false)}
  <div class="panel"><div class="row"><h2>Сайты направления</h2><span class="spacer"></span><button class="btn sm" id="ankImport" title="Файл «Ответы на анкету….json» от заказчика">Загрузить ответы анкеты</button><input type="file" id="ankImportIn" accept=".json,application/json" hidden><button class="btn primary sm" id="newSite">Новый сайт</button></div>
    <p class="hint" style="margin-bottom:12px">Бриф → ресёрч лидеров сферы, трендов и фото → 3 концепции с живыми превью → фото → идеальный промпт для Claude Code / Codex → сборка и проверка.</p>
    <div class="site-list">${L.projects.map((p, i) => `<button class="site-card" data-id="${esc(p.id)}" style="--i:${i}">
      ${p.logo ? `<img class="sc-logo" src="/files/sites/${esc(p.id)}/logo/${encodeURIComponent(p.logo)}" alt="">` : `<span class="sc-mono">${esc((p.name || "?").slice(0, 1))}</span>`}
      <div class="sc-name">${esc(p.name)}</div><div class="meta">${p.kind === "landing" ? "лендинг" : "сайт"} · этап: ${esc(p.stage)}${p.builds ? ` · сборок: ${p.builds}` : ""}</div>
      ${p.sphere ? `<div class="meta">${esc(p.sphere)}</div>` : ""}</button>`).join("")
    || `<p class="hint">В этом направлении сайтов пока нет. Нажми «Новый сайт».</p>`}</div></div>
  <div class="panel"><h2>Вкус направления</h2>
    <p class="hint">Свой для каждого направления: стратег учитывает его в концепциях, автор промптов — в промптах. Обновляется по оценкам концепций и сборок этого направления (оценок: ${L.ratings}).</p>
    <textarea id="siteTaste" style="min-height:180px">${esc(L.taste)}</textarea>
    <div class="row" style="margin-top:10px"><button class="btn primary" id="saveST">Сохранить</button>
      <button class="btn" id="updST" ${L.ratings ? "" : "disabled"}>Обновить по оценкам · ${who("site_strategy")}</button></div></div>`;
  bindSpaceCards(false);
  $("#toLabCtx").onclick = () => { S.page = "lab"; render(); };
  $("#newSite").onclick = () => guard(newSite);
  bindAnketaImport();
  v.querySelectorAll(".site-card").forEach((b) => (b.onclick = () => guard(async () => { await loadSite(b.dataset.id); S.page = "site"; S.siteTab = S.siteTab || "brief"; render(); })));
  $("#saveST").onclick = () => guard(async () => { await api(`/api/sites/taste?${lq()}`, { body: { text: $("#siteTaste").value } }); toast("Сохранено"); });
  $("#updST").onclick = () => guard(async () => startJob(await api(`/api/sites/taste/update?${lq()}`, { body: {} })));
}

// ---------------------------------------------------------------- проект
function renderSite(v, top) {
  const s = S.site;
  S.siteTab = S.siteTab || "brief";
  top.innerHTML = `<div><div class="crumb"><a href="#" id="toSites">${esc(S.sites?.lab?.name || "Лаборатория сайтов")}</a></div><h1>${esc(s.name)}</h1>
    <div class="sub">${esc(s.sphere || "сфера не указана")} · ${s.kind === "landing" ? "лендинг" : `сайт, ${s.pages_n} стр.`}</div></div>
    <div class="autopilot"><div class="meta">Бренд-кит → ресёрч → 3 концепции с превью, одной кнопкой</div>
      <button class="btn dark" id="siteAuto" ${brainOK() && s.sphere ? "" : "disabled title='Заполни сферу и подключи Claude или Gemini'"}>Подготовить концепции</button></div>`;
  $("#toSites").onclick = (e) => { e.preventDefault(); S.page = "labhome"; loadSites().then(render); };
  $("#siteAuto").onclick = () => guard(async () => { await saveBrief(true); startJob(await api(`/api/sites/${s.id}/auto`, { body: {} })); S.siteTab = "concepts"; render(); });
  const done = { brief: !!s.sphere, research: !!s.research, concepts: s.concepts.length > 0, photos: (s.photos?.slots || []).some((x) => x.chosen) || (s.videos?.slots || []).some((x) => x.chosen), prompt: !!s.prompts, build: s.builds.length > 0 };
  v.innerHTML = `<div class="steps">${SITE_TABS.map(([k, t], i) => `<button data-tab="${k}" class="${S.siteTab === k ? "on" : ""} ${done[k] ? "done" : ""}"><span class="n">${i + 1}</span>${t}</button>`).join("")}</div><div id="tab"></div>`;
  v.querySelectorAll(".steps button").forEach((b) => (b.onclick = () => { S.siteTab = b.dataset.tab; render(); }));
  ({ brief: siteBrief, research: siteResearch, concepts: siteConcepts, photos: sitePhotos, prompt: sitePrompt, build: siteBuild })[S.siteTab]($("#tab"), s);
  requestAnimationFrame(() => fitFrames());
}

// ---------------------------------------------------------------- 1. бриф
function siteBrief(t, s) {
  const B = s.brand;
  t.innerHTML = `${anketaPanel()}
  <div class="panel"><h2>О компании</h2>
    <div class="grid2">
      <div class="field"><label>Название компании</label><input type="text" id="b_name" value="${esc(s.name)}"></div>
      <div class="field"><label>Главное действие на сайте</label><input type="text" id="b_goal" list="goals" value="${esc(s.goal)}" placeholder="Оставить заявку"><datalist id="goals">${GOALS.map((g) => `<option value="${g}">`).join("")}</datalist></div>
    </div>
    <div class="field"><label>Сфера деятельности — чем занимается, что продаёт, чем отличается</label><textarea id="b_sphere" placeholder="Стоматологическая клиника в Казани: имплантация, виниры, детская стоматология. Премиум-сегмент.">${esc(s.sphere)}</textarea></div>
    <div class="field"><label>Аудитория (необязательно)</label><input type="text" id="b_aud" value="${esc(s.audience)}" placeholder="Взрослые 30–55 лет, ценят качество и сервис"></div>
    <div class="field"><label>Логотип (png, svg, jpg) — или оставь пустым, тогда фирменный стиль придумается по названию</label>
      <div class="logo-row">
        ${s.logo ? `<div class="logo-box"><img src="${siteUrl(s, "logo", s.logo)}" alt="логотип"></div><button class="btn sm ghost danger" id="logoRm">убрать</button>` : ""}
        <div class="drop" id="logoDrop">${s.logo ? "Заменить логотип" : "Перетащи логотип сюда или нажми"}<input type="file" id="logoIn" accept="image/*,.svg" hidden></div>
      </div></div>
  </div>
  <div class="panel"><h2>Формат</h2>
    <div class="seg" id="b_kind"><button data-v="landing" class="${s.kind === "landing" ? "on" : ""}">Лендинг — одна страница</button><button data-v="site" class="${s.kind !== "landing" ? "on" : ""}">Полноценный сайт</button></div>
    <div id="pagesBox" ${s.kind === "landing" ? "hidden" : ""} style="margin-top:14px">
      <div class="grid2"><div class="field"><label>Сколько страниц</label><input type="number" id="b_pages" min="2" max="30" value="${s.kind === "landing" ? 5 : s.pages_n}"></div>
      <div class="field"><label>Какие страницы обязательно (необязательно)</label><input type="text" id="b_wish" value="${esc(s.pages_wish)}" placeholder="Главная, Услуги, Цены, Врачи, Контакты"></div></div>
    </div>
    <div class="field" style="margin-top:12px"><label>Технология</label>
      <div class="seg" id="b_stack"><button data-v="static" class="${(s.stack || "static") === "static" ? "on" : ""}">HTML/CSS — смотрится прямо здесь</button><button data-v="nextjs" class="${s.stack === "nextjs" ? "on" : ""}">Next.js — статический</button><button data-v="nextjs_server" class="${s.stack === "nextjs_server" ? "on" : ""}">Next.js с сервером — оплата и заявки</button></div></div>
    <div class="field"><label>Сайты, которые нравятся (ссылки через пробел или с новой строки, необязательно)</label><textarea id="b_refs" style="min-height:60px">${esc(s.references)}</textarea></div>
    <div class="field"><label>Пожелания (необязательно)</label><textarea id="b_notes" style="min-height:60px" placeholder="Тёмная тема, без стоковых фото, нужен калькулятор стоимости…">${esc(s.notes)}</textarea></div>
    <div class="row"><button class="btn primary" id="saveBrief">Сохранить бриф</button>
      <button class="btn" id="brandBtn" ${brainOK() ? "" : "disabled"}>${B ? "Пересобрать бренд-кит" : "Собрать бренд-кит"} · ${who("site_brand")}</button></div>
  </div>
  ${launchPanel(s)}
  ${B ? `<div class="panel"><h2>Бренд-кит</h2><p class="lead">${esc(B.summary)}</p>
    ${swatches(B.colors)}
    ${B.measured?.length ? `<p class="meta">Цвета, измеренные по логотипу: ${B.measured.map((h) => `<span class="dotc" style="background:${hexc(h)}"></span>${esc(h)}`).join(" ")}</p>` : ""}
    <div class="grid2"><div><h3>Шрифты</h3><p><b>${esc(B.fonts?.heading)}</b> — заголовки<br><b>${esc(B.fonts?.body)}</b> — текст<br><span class="meta">${esc(B.fonts?.why || "")}</span></p></div>
    <div><h3>Характер и тон</h3><p>${esc((B.personality || []).join(" · "))}</p><p class="meta">${esc(B.tone_of_voice)}</p></div>
    <div><h3>Делать</h3>${listHtml(B.do)}</div><div><h3>Не делать</h3>${listHtml(B.dont)}</div></div></div>` : ""}
  <div class="panel danger-zone"><div class="row"><div><h2>Удалить сайт</h2>
      <p class="hint" style="margin:0">Навсегда удалит бриф, ресёрч, концепции, фото, видео, промпты, все сборки и статистику этого сайта.</p></div>
      <span class="spacer"></span><button class="btn danger" id="siteDel">Удалить сайт</button></div></div>`;
  t.querySelectorAll("#b_kind button").forEach((b) => (b.onclick = () => { t.querySelectorAll("#b_kind button").forEach((x) => x.classList.toggle("on", x === b)); $("#pagesBox").hidden = b.dataset.v === "landing"; }));
  t.querySelectorAll("#b_stack button").forEach((b) => (b.onclick = () => { t.querySelectorAll("#b_stack button").forEach((x) => x.classList.toggle("on", x === b)); }));
  bindLaunch(t);
  $("#saveBrief").onclick = () => guard(saveBrief);
  $("#brandBtn").onclick = () => guard(async () => { await saveBrief(true); startJob(await api(`/api/sites/${s.id}/brand`, { body: {} })); });
  const drop = $("#logoDrop"), inp = $("#logoIn");
  const up = (f) => guard(async () => { if (!f) return; S.site = await api(`/api/sites/${s.id}/logo?name=${encodeURIComponent(f.name)}`, { raw: f }); toast("Логотип загружен"); render(); });
  drop.onclick = () => inp.click(); inp.onchange = () => up(inp.files[0]);
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); up(e.dataTransfer.files[0]); };
  bindAnketa(s);
  $("#siteDel").onclick = () => guard(async () => { if (await deleteSite(s.id, s.name)) { S.page = "labhome"; render(); } });
  if ($("#logoRm")) $("#logoRm").onclick = () => guard(async () => { S.site = await api(`/api/sites/${s.id}/logoremove`, { body: {} }); render(); });
}
// сохранить бриф, если открыта вкладка «Бриф» (с других вкладок — ничего не делает)
async function saveBrief(silent) {
  if (!$("#b_name") || !S.site) return;
  S.site = await api(`/api/sites/${S.site.id}/brief`, { body: { name: $("#b_name").value, goal: $("#b_goal").value,
    sphere: $("#b_sphere").value, audience: $("#b_aud").value, kind: $("#b_kind button.on").dataset.v,
    stack: $("#b_stack button.on").dataset.v, pages_n: +($("#b_pages").value || 5), pages_wish: $("#b_wish").value,
    references: $("#b_refs").value, notes: $("#b_notes").value, launch: readLaunch() } });
  if (silent !== true) { toast("Бриф сохранён"); render(); }
}

// ---------------------------------------------------------------- 2. ресёрч
function siteResearch(t, s) {
  const R = s.research;
  t.innerHTML = `<div class="panel"><div class="row"><div><h2>Ресёрч</h2>
      <p class="hint" style="margin:0">${who("site_research")} ищет лидеров сферы и эталоны дизайна, прототип снимает скриншоты, ${who("site_research")} разбирает их глазами. 5–15 минут.</p></div>
      <span class="spacer"></span><button class="btn primary" id="runRes" ${brainOK() && s.sphere ? "" : "disabled"}>${R ? "Обновить ресёрч" : "Запустить ресёрч"}</button></div></div>
  ${R ? `
  <div class="panel"><h2>Сайты</h2><div class="site-shots">${R.sites.map((x) => {
      const sh = R.shots?.[x.url]; const rv = (R.visual?.reviews || []).find((r) => r.url === x.url) || {};
      return `<div class="shot-card">${sh ? `<a href="${siteUrl(s, "shots", sh.full)}" target="_blank"><img src="${siteUrl(s, "shots", sh.hero)}" alt=""></a>` : `<div class="noshot">скриншота нет</div>`}
        <div class="b"><div class="row"><b>${esc(x.name)}</b><span class="badge ${x.kind === "reference" ? "exp" : ""}">${x.kind === "reference" ? "эталон" : "сфера"}</span></div>
        <a class="meta" href="${esc(safeUrl(x.url))}" target="_blank" rel="noopener noreferrer">${esc(x.url.replace(/^https?:\/\//, "").slice(0, 40))}</a>
        <p>${esc(x.why)}</p>${rv.steal ? `<p class="steal">Взять: ${esc(rv.steal)}</p>` : ""}${rv.weak ? `<p class="meta">Слабо: ${esc(rv.weak)}</p>` : ""}</div></div>`; }).join("")}</div></div>
  ${(R.photo_trends || []).length ? `<div class="panel"><h2>Фото, которые сейчас работают</h2>
    <div class="trends">${R.photo_trends.map((x) => `<div class="trend-card"><b>${esc(x.name)}</b><p>${esc(x.what)}</p><p class="use">Как снять: ${esc(x.how_to_shoot)}</p>${x.where ? `<p class="meta">Где: ${esc(x.where)}</p>` : ""}</div>`).join("")}</div>
    ${(R.photo_avoid || []).length ? `<h3>Выглядит дёшево</h3>${listHtml(R.photo_avoid)}` : ""}</div>` : ""}
  ${R.visual ? `<div class="panel"><h2>Визуальный язык сферы</h2><p class="lead">${esc(R.visual.common_visual_language)}</p><h3>Чем выделиться</h3>${listHtml(R.visual.gaps)}</div>` : ""}
  <div class="panel"><h2>Тренды</h2><div class="trends">${(R.trends || []).map((x) => `<div class="trend-card"><b>${esc(x.name)}</b><p class="use">${esc(x.how_to_use)}</p></div>`).join("")}</div>
    <div class="grid2"><div><h3>Типично для сферы</h3>${listHtml(R.sphere_patterns)}</div><div><h3>Обязательные блоки</h3>${listHtml(R.must_have_sections)}</div>
    <div><h3>Что повышает заявки</h3>${listHtml(R.conversion)}</div><div><h3>Частые ошибки</h3>${listHtml(R.mistakes)}</div></div>
    ${(R.sources || []).length ? `<h3>Источники</h3><ol class="src">${R.sources.map((x) => `<li><a href="${esc(safeUrl(x.url))}" target="_blank" rel="noopener noreferrer">${esc(x.title || x.url)}</a></li>`).join("")}</ol>` : ""}</div>`
  : `<div class="panel"><p class="hint">Ресёрча пока нет.</p></div>`}`;
  $("#runRes").onclick = () => guard(async () => { await saveBrief(true); startJob(await api(`/api/sites/${s.id}/research`, { body: {} })); });
}

// ---------------------------------------------------------------- 3. концепции
function siteConcepts(t, s) {
  t.innerHTML = `<div class="panel"><div class="row"><div><h2>Концепции</h2>
      <p class="hint" style="margin:0">Стратег (${who("site_strategy")}) предлагает 3 разных направления и рисует первый экран каждого. Выбери одно — можно с правками словами.</p></div>
      <span class="spacer"></span><button class="btn primary" id="runCon" ${brainOK() ? "" : "disabled"}>${s.concepts.length ? "Предложить заново" : "Предложить 3 концепции"}</button></div></div>
  <div class="concepts3">${s.concepts.map((c, i) => `
    <div class="cc ${s.chosen === i ? "chosen" : ""}">
      ${c.preview ? frame(siteUrl(s, "previews", c.preview)) : `<div class="noshot tall">превью рисуется…</div>`}
      <div class="b">
        <div class="row"><h3>${esc(c.name)}</h3>${s.chosen === i ? `<span class="badge ok">выбрана</span>` : ""}<span class="spacer"></span>
          ${c.preview ? `<a class="btn sm ghost" href="${siteUrl(s, "previews", c.preview)}" target="_blank">открыть</a>` : ""}</div>
        <p>${esc(c.idea)}</p>
        ${swatches(c.palette)}
        <p class="meta"><b>${esc(c.typography?.heading)}</b> + ${esc(c.typography?.body)} · ${esc(c.mood || "")}</p>
        <p class="meta">Сетка: ${esc(c.layout)}</p>
        ${c.signature ? `<p class="steal">Фишка: ${esc(c.signature)}</p>` : ""}
        <details><summary class="meta">Почему так · страницы и секции</summary>
          <p>${esc(c.why || "")}</p>
          ${(c.pages || []).map((pg) => `<p><b>${esc(pg.title)}</b> <span class="meta">/${esc(pg.slug)}</span><br><span class="meta">${(pg.sections || []).map(esc).join(" → ")}</span></p>`).join("")}
        </details>
        <div class="field" style="margin-top:10px"><textarea class="fb" placeholder="Что поменять в этой концепции (необязательно)">${s.chosen === i ? esc(s.feedback) : ""}</textarea></div>
        <div class="row">
          <button class="btn primary sm pick" data-i="${i}">Выбрать</button>
          <button class="btn sm ghost redo" data-i="${i}">Перерисовать превью</button>
          <span class="spacer"></span>
          <button class="btn sm ${c.like === true ? "primary" : ""} lk" data-i="${i}" data-v="1" title="Нравится">♥</button>
          <button class="btn sm ${c.like === false ? "danger" : ""} lk" data-i="${i}" data-v="0" title="Не нравится">✕</button>
        </div>
      </div></div>`).join("")}</div>`;
  $("#runCon").onclick = () => guard(async () => startJob(await api(`/api/sites/${s.id}/concepts`, { body: { n: 3 } })));
  t.querySelectorAll(".pick").forEach((b) => (b.onclick = () => guard(async () => {
    const fb = b.closest(".cc").querySelector(".fb").value;
    S.site = await api(`/api/sites/${s.id}/choose`, { body: { idx: +b.dataset.i, feedback: fb } });
    toast("Концепция выбрана"); S.siteTab = "photos"; render();
  })));
  t.querySelectorAll(".redo").forEach((b) => (b.onclick = () => guard(async () => startJob(await api(`/api/sites/${s.id}/preview`, { body: { idx: +b.dataset.i } })))));
  t.querySelectorAll(".lk").forEach((b) => (b.onclick = () => guard(async () => {
    S.site = await api(`/api/sites/${s.id}/rate`, { body: { what: "concept", ref: +b.dataset.i, like: b.dataset.v === "1", comment: b.closest(".cc").querySelector(".fb").value } });
    toast("Оценка сохранена — она пойдёт во вкус сайтов"); render();
  })));
}

// ---------------------------------------------------------------- 5. промпт
function sitePrompt(t, s) {
  const c = s.chosen != null ? s.concepts[s.chosen] : null;
  const P = s.prompts;
  const live = !!s.launch?.on;
  const edits = (P?.edits || []).slice().reverse();
  const lastChanged = new Set((edits.find((e) => !e.undone) || {}).changed || []);
  const files = P?.files || [];
  const launchMissing = live && P && !files.includes("INTEGRATIONS.md");
  t.innerHTML = `<div class="panel"><div class="row"><div><h2>Пакет промптов для Claude Code / Codex</h2>
      <p class="hint" style="margin:0">${c ? `Концепция: <b>${esc(c.name)}</b>${s.feedback ? ` · правки: ${esc(s.feedback)}` : ""}.` : "Сначала выбери концепцию на шаге 3."}
      Пакет: MASTER (он же CLAUDE.md / AGENTS.md) с дизайн-системой, промпт на каждую страницу с точными текстами, тексты отдельно, фото и видео, чек-лист приёмки${live ? ", а для боевого сайта — INTEGRATIONS.md (оплата, чеки, заявки), LEGAL.md и LAUNCH.md — инструкция, что сделать руками" : ""}.</p></div>
      <span class="spacer"></span><button class="btn ${P ? "" : "primary"}" id="runPr" ${c && brainOK() ? "" : "disabled"}>${P ? "Написать заново" : "Написать пакет"} · ${who("site_prompt")}</button></div>
    ${launchMissing ? `<div class="resume" style="margin-top:12px"><b>Сайт отмечен как боевой, а пакета запуска ещё нет.</b><span class="meta">Допишу интеграции, юр. тексты и инструкцию LAUNCH.md к текущему пакету.</span><button class="btn primary sm" id="pLaunch2" ${brainOK() ? "" : "disabled"}>Дописать пакет запуска</button></div>` : ""}</div>
  ${P ? `<div class="panel"><h2>Правки по пожеланиям</h2>
    <p class="hint">Напиши своими словами, что поменять. Claude Code сам найдёт нужные файлы пакета и поправит только их, не перечитывая и не переписывая остальное — обычно 1–3 минуты.
      Перед каждой правкой пакет сохраняется, любую правку можно откатить.</p>
    <textarea id="pWish" style="min-height:70px" placeholder="Например: добавь блок отзывов на главную после услуг; кнопки сделай терракотовыми; убери страницу «Блог»; в оферте срок возврата 14 дней"></textarea>
    <div class="row" style="margin-top:10px"><button class="btn primary" id="pEdit" ${claudeOK() ? "" : "disabled title='Нужен Claude Code (вход по подписке)'"}>Внести правки · Claude Code</button>
      ${live ? `<button class="btn" id="pLaunch" ${brainOK() ? "" : "disabled"}>Обновить пакет запуска</button>` : ""}</div>
    ${edits.length ? `<ul class="edits">${edits.map((e) => `<li class="${e.undone ? "undone" : ""}"><div class="row"><b>${esc(e.wish)}</b><span class="spacer"></span>
        <span class="meta">${esc((e.at || "").replace("T", " "))}</span>${e.undone ? `<span class="badge">откачено</span>` : `<button class="btn sm ghost undo" data-sn="${esc(e.snapshot)}">Откатить</button>`}</div>
        <div class="chips">${(e.changed || []).map((f) => `<span>${esc(f)}</span>`).join("") || `<span>без изменений</span>`}</div>
        <details><summary class="meta">Что сделал Claude</summary><pre class="rep">${esc(e.summary || "")}</pre></details></li>`).join("")}</ul>` : ""}
  </div>
  <div class="panel prompt-ed"><div class="pfiles">${files.map((f, i) => `<button data-f="${esc(f)}" class="${i === 0 ? "on" : ""} ${lastChanged.has(f) ? "chg" : ""}" title="${lastChanged.has(f) ? "изменён последней правкой" : ""}">${esc(f)}</button>`).join("")}</div>
    <div><textarea id="pText" class="code" style="min-height:520px"></textarea>
    <div class="row" style="margin-top:10px"><button class="btn" id="pSave">Сохранить правки</button><button class="btn" id="pCopy">Копировать</button>
      <a class="btn" href="/api/sites/${s.id}/download?what=prompts">Скачать пакет .zip</a><span class="spacer"></span>
      <button class="btn dark" id="toBuild">Собрать сайт →</button></div></div></div>` : ""}`;
  $("#runPr").onclick = () => guard(async () => {
    if (P && !confirm("Написать пакет заново? Текущий сохранится в истории — его можно будет вернуть.")) return;
    startJob(await api(`/api/sites/${s.id}/prompts`, { body: {} })); });
  const lp = () => guard(async () => startJob(await api(`/api/sites/${s.id}/launchpack`, { body: {} })));
  if ($("#pLaunch")) $("#pLaunch").onclick = lp;
  if ($("#pLaunch2")) $("#pLaunch2").onclick = lp;
  if (!P) return;
  $("#pEdit").onclick = () => guard(async () => {
    const w = $("#pWish").value.trim(); if (!w) return toast("Напиши, что поменять", true);
    startJob(await api(`/api/sites/${s.id}/promptedit`, { body: { wish: w } })); $("#pWish").value = ""; });
  t.querySelectorAll(".undo").forEach((b) => (b.onclick = () => guard(async () => {
    if (!confirm("Вернуть пакет к состоянию до этой правки? Более поздние правки тоже откатятся (текущий вариант сохранится в истории).")) return;
    S.site = await api(`/api/sites/${s.id}/promptundo`, { body: { snapshot: b.dataset.sn } }); toast("Откатил"); render(); })));
  let cur = files[0];
  const open = async (f) => { cur = f; $("#pText").value = (await api(`/api/sites/${s.id}/prompt?file=${encodeURIComponent(f)}`)).text;
    t.querySelectorAll(".pfiles button").forEach((b) => b.classList.toggle("on", b.dataset.f === f)); };
  t.querySelectorAll(".pfiles button").forEach((b) => (b.onclick = () => guard(() => open(b.dataset.f))));
  $("#pSave").onclick = () => guard(async () => { await api(`/api/sites/${s.id}/promptsave`, { body: { file: cur, text: $("#pText").value } }); toast("Сохранено"); });
  $("#pCopy").onclick = () => copy($("#pText").value);
  $("#toBuild").onclick = () => { S.siteTab = "build"; render(); };
  guard(() => open(cur));
}

// ---------------------------------------------------------------- 5. сборка
function siteBuild(t, s) {
  const builds = s.builds.slice().reverse();
  const nextjs = (s.stack || "static") !== "static";
  t.innerHTML = `<div class="panel"><div class="row"><div><h2>Сборка</h2>
      <p class="hint" style="margin:0">Claude Code по подписке собирает сайт по пакету промптов (обычно 5–20 минут), затем снимает скриншоты десктопа и мобильной версии и проверяет себя.
      ${nextjs ? "Для Next.js собираются исходники проекта; посмотреть его можно после <code>npm install && npm run dev</code>." : ""}</p></div></div>
    <div class="field" style="margin-top:12px"><label>Пожелания к сборке (необязательно)</label><textarea id="bExtra" style="min-height:56px" placeholder="Например: добавь калькулятор стоимости на главную"></textarea></div>
    <button class="btn primary" id="runBuild" ${s.prompts && claudeOK() ? "" : "disabled"}>${builds.length ? "Собрать новую версию" : "Собрать сайт"}</button>
    ${!claudeOK() ? `<span class="meta"> — для сборки нужен Claude Code (вход по подписке)</span>` : ""}</div>
  ${builds.map((b) => buildCard(s, b)).join("")}`;
  $("#runBuild").onclick = () => guard(async () => startJob(await api(`/api/sites/${s.id}/build`, { body: { extra: $("#bExtra").value } })));
  t.querySelectorAll(".bcard").forEach((el) => {
    const b = s.builds.find((x) => x.dir === el.dataset.d);
    const show = (page, mode) => {
      el.querySelector(".viewer").innerHTML = mode === "mobile" ? frame(siteUrl(s, `builds/${b.dir}`, page), 390, 844, "mobile") : frame(siteUrl(s, `builds/${b.dir}`, page));
      el.querySelector(".newtab").href = siteUrl(s, `builds/${b.dir}`, page); fitFrames(el);
    };
    let page = b.pages[0], mode = "desktop";
    if (page) show(page, mode);
    el.querySelectorAll("[data-page]").forEach((x) => (x.onclick = () => { page = x.dataset.page; el.querySelectorAll("[data-page]").forEach((y) => y.classList.toggle("on", y === x)); show(page, mode); }));
    el.querySelectorAll("[data-mode]").forEach((x) => (x.onclick = () => { mode = x.dataset.mode; el.querySelectorAll("[data-mode]").forEach((y) => y.classList.toggle("on", y === x)); show(page, mode); }));
    el.querySelector(".fix").onclick = () => guard(async () => startJob(await api(`/api/sites/${s.id}/fix`, { body: { dir: b.dir, extra: el.querySelector(".fx").value, use_review: true } })));
    const rb = el.querySelector(".resumeBtn");
    if (rb) rb.onclick = () => guard(async () => startJob(await api(`/api/sites/${s.id}/resume`, { body: { dir: b.dir, extra: el.querySelector(".fx").value } })));
    el.querySelector(".rev").onclick = () => guard(async () => startJob(await api(`/api/sites/${s.id}/review`, { body: { dir: b.dir } })));
    el.querySelectorAll(".lk").forEach((x) => (x.onclick = () => guard(async () => {
      S.site = await api(`/api/sites/${s.id}/rate`, { body: { what: "build", ref: b.dir, like: x.dataset.v === "1", comment: el.querySelector(".fx").value } });
      toast("Оценка сохранена"); render(); })));
  });
}
function buildCard(s, b) {
  const R = b.review;
  return `<div class="panel bcard" data-d="${esc(b.dir)}">
    <div class="row"><h2>Версия ${esc(b.dir)}</h2>
      ${b.status === "partial" ? `<span class="badge bad">не закончена</span>` : b.status === "running" ? `<span class="badge exp">собирается</span>` : `<span class="badge ok">готова</span>`}
      <span class="meta">${esc((b.created || "").replace("T", " "))} · ${esc(b.concept || "")} · файлов ${b.files ?? "?"} · ${b.turns || "?"} шагов · ${Math.round((b.seconds || 0) / 60)} мин${(b.sessions || []).length > 1 ? ` · сессий ${b.sessions.length}` : ""}</span>
      <span class="spacer"></span>
      <button class="btn sm ${b.like === true ? "primary" : ""} lk" data-v="1">♥</button><button class="btn sm ${b.like === false ? "danger" : ""} lk" data-v="0">✕</button>
      <a class="btn sm" href="/api/sites/${s.id}/download?what=${encodeURIComponent(b.dir)}">Скачать .zip</a></div>
    ${b.pages.length ? `<div class="row" style="margin:10px 0"><div class="seg small">${b.pages.map((p, i) => `<button data-page="${esc(p)}" class="${i === 0 ? "on" : ""}">${esc(p.replace(".html", ""))}</button>`).join("")}</div>
      <span class="spacer"></span><div class="seg small"><button data-mode="desktop" class="on">Десктоп</button><button data-mode="mobile">Телефон</button></div>
      <a class="btn sm ghost newtab" target="_blank">в новой вкладке</a></div>
      <div class="viewer"></div>` : `<p class="hint">HTML-страниц в корне нет${(s.stack || "static") !== "static" ? " — это проект Next.js, скачай его и запусти локально" : ""}.</p>`}
    ${R ? `<div class="review"><div class="row"><b>Проверка: ${esc(R.score)}/100</b><span class="meta">${esc(R.summary)}</span></div>
      ${(R.issues || []).length ? `<ul class="issues2">${R.issues.map((i) => `<li class="${esc(i.severity || "")}"><b>${esc(i.page || "")}</b> ${esc(i.problem)} <span class="meta">→ ${esc(i.fix)}</span></li>`).join("")}</ul>` : ""}</div>` : ""}
    ${b.status === "partial" ? `<div class="resume"><b>Сборка остановилась на полпути — всё сделанное сохранено.</b>
      <span class="meta">${esc(b.summary || "")}</span>
      <button class="btn primary sm resumeBtn" ${claudeOK() ? "" : "disabled"}>Продолжить сборку</button></div>` : ""}
    ${(b.stack || "static") !== "static" && !b.pages.length ? `<p class="hint">Это проект Next.js: файлов ${b.files ?? "?"}. Посмотреть — скачать архив и в папке выполнить <code>npm install && npm run dev</code> (нужен Node.js).</p>` : ""}
    ${(b.fixes || []).length ? `<p class="meta">Правок внесено: ${b.fixes.length}. Последняя: ${esc((b.fixes.at(-1).summary || "").slice(0, 200))}</p>` : ""}
    <div class="field" style="margin-top:10px"><textarea class="fx" style="min-height:56px" placeholder="Что поправить своими словами (необязательно)">${esc(b.comment || "")}</textarea></div>
    <div class="row"><button class="btn primary sm fix" ${claudeOK() ? "" : "disabled"}>Исправить${R?.issues?.length ? " замечания" : ""}</button>
      <button class="btn sm rev" ${brainOK() ? "" : "disabled"}>Проверить заново</button>
      ${b.summary ? `<details><summary class="meta">Отчёт Claude Code</summary><pre class="rep">${esc(b.summary)}</pre></details>` : ""}</div>
  </div>`;
}


// ---------------------------------------------------------------- 4. фото
const ASPECTS = ["21:9", "16:9", "3:2", "4:3", "5:4", "1:1", "4:5", "3:4", "2:3", "9:16"];
const KIND_RU = { ai: "ИИ", upload: "своё", enhanced: "улучшено" };
function sitePhotos(t, s) {
  const ph = s.photos || { slots: [], uploads: [] };
  const c = s.chosen != null ? s.concepts[s.chosen] : null;
  const demo = S.state.settings.demo_mode;
  const empty = ph.slots.filter((x) => !x.chosen).length;
  const free = (ph.uploads || []).filter((u) => !u.slot);
  const price = (n) => demo ? "демо, $0" : `~$${(0.12 * n).toFixed(2)}`;
  t.innerHTML = `
  <div class="panel"><div class="row"><div><h2>Фото для сайта</h2>
      <p class="hint" style="margin:0">Фотодиректор (${who("site_strategy")}) по концепции и фото-трендам из ресёрча составляет единый фотостиль и список мест под фото и видео.
      Каждое место можно закрыть фото от ИИ (Nano Banana 2) или своим — а своё ИИ доведёт до уровня хорошей фотосессии. Выбранные фото уйдут в промпт и в сборку.</p></div>
      <span class="spacer"></span>
      <button class="btn ${ph.slots.length ? "" : "primary"}" id="phPlan" ${c && brainOK() ? "" : "disabled title='Сначала выбери концепцию'"}>${ph.slots.length ? "Новый план фото" : "Составить план фото"}</button></div>
    ${ph.style ? `<div class="ph-style"><b>Фотостиль:</b> ${esc(ph.style.summary)}
      <span class="meta">${[ph.style.light && "свет — " + ph.style.light, ph.style.color_grade && "цвет — " + ph.style.color_grade, ph.style.composition && "композиция — " + ph.style.composition, ph.style.people && "люди — " + ph.style.people, ph.style.avoid && "избегать — " + ph.style.avoid].filter(Boolean).map(esc).join(" · ")}</span></div>` : ""}
    ${ph.slots.length ? `<div class="row" style="margin-top:12px">
      <button class="btn primary" id="phGenAll" ${empty ? "" : "disabled"}>Сгенерировать пустые места (${empty}) · ${price(empty)}</button>
      <button class="btn" id="phAssign" ${free.length && brainOK() ? "" : "disabled"}>Разложить мои фото по местам (${free.length})</button></div>` : ""}
  </div>
  <div class="panel"><h2>Мои фото</h2>
    <p class="hint">Загрузи свои фото (офис, команда, товары, работы) — ИИ разложит их по местам и подскажет, какие улучшить. Можно и сразу в конкретное место кнопкой «Своё фото».</p>
    <div class="drop" id="phDrop">Перетащи фото сюда или нажми, чтобы выбрать<input type="file" id="phIn" multiple accept="image/*,.heic,.HEIC" hidden></div>
    ${(ph.uploads || []).length ? `<div class="ups">${ph.uploads.map((u) => `<div class="up">
      <img src="${siteUrl(s, "photos", u.file)}" alt=""><div class="meta">${esc(u.name || u.file)}</div>
      <select data-use="${esc(u.file)}"><option value="">— место —</option>${ph.slots.map((x) => `<option value="${esc(x.id)}" ${u.slot === x.id ? "selected" : ""}>${esc(x.id)}</option>`).join("")}</select></div>`).join("")}</div>` : ""}
    ${(ph.advice || []).length ? `<p class="meta">Совет фоторедактора: улучшить ${ph.advice.map((a) => `${esc(a.slot)} (${a.mode === "studio" ? "фотосессия" : "ретушь"})`).join(", ")}</p>` : ""}
  </div>
  <div class="slots">${ph.slots.map((x) => slotCard(s, x)).join("")}</div>
  ${videoSection(s)}`;
  bindVideos(t, s);
  $("#phPlan").onclick = () => guard(async () => { if (ph.slots.length && !confirm("Составить новый план? Текущие места и варианты заменятся (свои загруженные фото останутся).")) return;
    startJob(await api(`/api/sites/${s.id}/photoplan`, { body: {} })); });
  if ($("#phGenAll")) $("#phGenAll").onclick = () => guard(async () => {
    if (!demo && !confirm(`Сгенерировать ${empty} фото в Nano Banana 2? Примерно $${(0.12 * empty).toFixed(2)}.`)) return;
    startJob(await api(`/api/sites/${s.id}/photogen`, { body: {} })); });
  if ($("#phAssign")) $("#phAssign").onclick = () => guard(async () => startJob(await api(`/api/sites/${s.id}/photoassign`, { body: {} })));
  const drop = $("#phDrop"), inp = $("#phIn");
  const up = async (files, slot = "") => { for (const f of files) { toast(`Загружаю ${f.name}…`);
      await guard(async () => { S.site = await api(`/api/sites/${s.id}/photoupload?name=${encodeURIComponent(f.name)}&slot=${encodeURIComponent(slot)}`, { raw: f }); }); }
    render(); };
  drop.onclick = () => inp.click(); inp.onchange = () => up([...inp.files]);
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); up([...e.dataTransfer.files]); };
  t.querySelectorAll("[data-use]").forEach((sel) => (sel.onchange = () => guard(async () => { S.site = await api(`/api/sites/${s.id}/photouse`, { body: { file: sel.dataset.use, slot: sel.value } }); render(); })));
  t.querySelectorAll(".slot:not(.vslot)").forEach((el) => {
    const id = el.dataset.id, x = ph.slots.find((y) => y.id === id);
    el.querySelectorAll("[data-v]").forEach((b) => (b.onclick = () => guard(async () => { S.site = await api(`/api/sites/${s.id}/photochoose`, { body: { slot: id, file: b.dataset.v } }); render(); })));
    el.querySelector(".gen").onclick = () => guard(async () => {
      if (!demo && !confirm("Сгенерировать фото для этого места? ~$0.12")) return;
      await api(`/api/sites/${s.id}/photoslot`, { body: { slot: id, prompt_en: el.querySelector(".pe").value } });
      startJob(await api(`/api/sites/${s.id}/photogen`, { body: { slots: [id] } })); });
    el.querySelectorAll(".enh").forEach((b) => (b.onclick = () => guard(async () => {
      if (!x.chosen) return toast("Сначала выбери фото, которое улучшать", true);
      if (!demo && !confirm(`${b.textContent.trim()} — Nano Banana 2, ~$0.12?`)) return;
      startJob(await api(`/api/sites/${s.id}/photoenhance`, { body: { slot: id, file: x.chosen, mode: b.dataset.mode, extra: el.querySelector(".ex").value } })); })));
    const fi = el.querySelector(".own-in");
    el.querySelector(".own").onclick = () => fi.click();
    fi.onchange = () => up([...fi.files], id);
    el.querySelector(".savep").onclick = () => guard(async () => {
      S.site = await api(`/api/sites/${s.id}/photoslot`, { body: { slot: id, prompt_en: el.querySelector(".pe").value, alt_ru: el.querySelector(".alt").value, aspect: el.querySelector(".asp").value } });
      toast("Сохранено"); });
  });
}
function slotCard(s, x) {
  return `<div class="slot ${x.chosen ? "has" : ""}" data-id="${esc(x.id)}">
    <div class="slot-img">${x.chosen ? `<a href="${siteUrl(s, "photos", x.chosen)}" target="_blank"><img src="${siteUrl(s, "photos", x.chosen)}" alt="${esc(x.alt_ru || "")}"></a>` : `<span>${esc(x.subject_ru || "нет фото")}</span>`}</div>
    <div class="b">
      <div class="row"><b>${esc(x.id)}</b><span class="badge">${esc(x.aspect)}</span><span class="meta">${esc(x.page)} · ${esc(x.section)}</span></div>
      <p class="meta" style="margin:4px 0 8px">${esc(x.purpose || x.subject_ru || "")}</p>
      ${(x.variants || []).length ? `<div class="vars">${x.variants.map((v) => `<button data-v="${esc(v.file)}" class="${x.chosen === v.file ? "on" : ""}" title="${esc(KIND_RU[v.kind] || v.kind)}"><img src="${siteUrl(s, "photos", v.file)}" alt=""><i>${esc(KIND_RU[v.kind] || "")}</i></button>`).join("")}</div>` : ""}
      <div class="row" style="margin-top:8px">
        <button class="btn sm primary gen">${x.chosen ? "Ещё вариант ИИ" : "Сгенерировать"}</button>
        <button class="btn sm own">Своё фото</button><input type="file" class="own-in" accept="image/*,.heic" hidden>
        <button class="btn sm enh" data-mode="retouch" ${x.chosen ? "" : "disabled"}>Ретушь</button>
        <button class="btn sm enh" data-mode="studio" ${x.chosen ? "" : "disabled"}>Как с фотосессии</button>
      </div>
      <input type="text" class="ex" placeholder="Пожелание к улучшению (необязательно): тёплый свет, белый фон…" style="margin-top:8px">
      <details style="margin-top:8px"><summary class="meta">Промпт, alt и пропорции</summary>
        <textarea class="pe code" style="min-height:90px">${esc(x.prompt_en || "")}</textarea>
        <div class="grid2" style="margin-top:6px"><input type="text" class="alt" value="${esc(x.alt_ru || "")}" placeholder="alt-текст">
          <select class="asp">${ASPECTS.map((a) => `<option ${a === x.aspect ? "selected" : ""}>${a}</option>`).join("")}</select></div>
        <button class="btn sm savep" style="margin-top:6px">Сохранить</button></details>
    </div></div>`;
}

// ---------------------------------------------------------------- запуск: боевой сайт (оплата, чеки, заявки)
const LAUNCH_ENUMS = {
  legal: { ip: "ИП", ooo: "ООО", npd: "самозанятый (НПД)" },
  tax: { usn_income: "УСН «доходы»", usn_ie: "УСН «доходы минус расходы»", osn: "ОСН", patent: "ПСН (патент)", npd: "НПД (самозанятый)", unknown: "не знаю" },
  vat: { none: "без НДС", 22: "НДС 22%", 10: "НДС 10%", 5: "НДС 5% (УСН)", 7: "НДС 7% (УСН)", 0: "НДС 0%" },
  sells: { goods: "товары с доставкой", services: "услуги", digital: "цифровые товары / доступы", booking: "запись / бронирование с предоплатой" },
  checkout: { cart: "корзина на несколько товаров", buy: "кнопка «Купить» на товар/услугу", deposit: "предоплата / депозит за запись" },
  payments: { yookassa: "ЮKassa", tbank: "Т-Банк · интернет-эквайринг (Т-Касса)", cloudpayments: "CloudPayments", robokassa: "Robokassa", other: "другой сервис", none: "без онлайн-оплаты" },
  receipts: { provider: "чеки платёжного сервиса (без своей кассы)", own: "своя облачная касса", npd: "чеки самозанятого («Мой налог»)", unknown: "ещё не решили" },
  forms: { telegram: "заявки в Telegram", email: "заявки на почту", both: "Telegram и почта", none: "без форм" },
  hosting: { ru: "сервер в России (VPS / облако)", vercel: "Vercel или другой зарубежный", unknown: "ещё не выбрали" },
};
const RECEIPT_HINT = {
  yookassa: "Чеки: «Чеки от ЮKassa» — своя касса не нужна, включаются в личном кабинете. Или своя облачная касса партнёра (АТОЛ Онлайн, Orange Data…). Самозанятым ЮKassa чеки с 29.12.2025 сама не пробивает.",
  tbank: "Чеки: нужна облачная онлайн-касса — подключается в личном кабинете Т-Бизнеса.",
  cloudpayments: "Чеки: CloudKassir — аренда облачной кассы (по сайту от ~3 000 ₽/мес + старт), регистрацию кассы в ФНС делаете сами с КЭП. Или другая облачная касса.",
  robokassa: "Чеки: «Робочеки» — без своей кассы и фискального накопителя; для самозанятых — «Робочеки СМЗ» (чек в «Мой налог»).",
  other: "Сборщик найдёт документацию сервиса; чеки — по правилам сервиса.",
  none: "Без онлайн-оплаты: только заявки, касса не нужна.",
};
const launchOf = (s) => ({ ...(S.sites?.launch?.default || {}), on: false, legal: "ip", tax: "usn_income", vat: "none", sells: "services", checkout: "buy",
  payments: "yookassa", payments_other: "", receipts: "provider", forms: "telegram", hosting: "ru", domain: "", metrika: true, legal_docs: true,
  ...(s.launch || {}), company: { legal_name: "", inn: "", ogrn: "", address: "", email: "", phone: "", ...((s.launch || {}).company || {}) } });
function launchPanel(s) {
  const L = launchOf(s), E = LAUNCH_ENUMS;
  const sel = (k, label) => `<div class="field"><label>${label}</label><select id="l_${k}">${Object.entries(E[k]).map(([v, t]) => `<option value="${esc(v)}" ${String(L[k]) === String(v) ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></div>`;
  const inp = (k, label, ph = "") => `<div class="field"><label>${label}</label><input type="text" id="lc_${k}" value="${esc(L.company[k])}" placeholder="${esc(ph)}"></div>`;
  return `<div class="panel launch ${L.on ? "on" : ""}"><div class="row"><div><h2>Запуск: боевой сайт</h2>
      <p class="hint" style="margin:0">Не макет, а сайт, который принимает деньги и заявки: оплата с чеками 54-ФЗ, заявки в Telegram или на почту, Метрика, юридические страницы.
      Код пишет Claude Code, а в пакете будет <b>LAUNCH.md</b> — что сделать руками: договор с платёжным сервисом, чеки, ключи. Оплате и заявкам нужен сервер — технология станет «Next.js с сервером».</p></div>
      <span class="spacer"></span><label class="row" style="gap:8px;white-space:nowrap"><input type="checkbox" id="l_on" ${L.on ? "checked" : ""}> Готов к запуску</label></div>
    <div id="launchBox" ${L.on ? "" : "hidden"} style="margin-top:12px">
      <h3>Кто продаёт</h3><div class="grid3">${sel("legal", "Статус")}${sel("tax", "Налог")}${sel("vat", "НДС в чеке")}</div>
      <p class="meta">С 2026 года базовая ставка НДС — 22%. УСН с доходом за прошлый год до 20 млн ₽ — без НДС, выше — 5% или 7%. Если не уверен, уточни у бухгалтера.</p>
      <h3>Что и как продаём</h3><div class="grid3">${sel("sells", "Что продаём")}${sel("checkout", "Как оформляют")}${sel("payments", "Онлайн-оплата")}</div>
      <div class="field" id="l_otherBox" ${L.payments === "other" ? "" : "hidden"}><label>Какой сервис</label><input type="text" id="l_payments_other" value="${esc(L.payments_other)}" placeholder="Например: Prodamus, PayKeeper, Сбер"></div>
      <div class="grid3">${sel("receipts", "Чеки 54-ФЗ")}${sel("forms", "Заявки с форм")}${sel("hosting", "Где будет сайт")}</div>
      <p class="meta" id="l_hint">${esc(RECEIPT_HINT[L.payments] || "")}</p>
      <div class="grid3"><div class="field"><label>Домен (если есть)</label><input type="text" id="l_domain" value="${esc(L.domain)}" placeholder="studio-example.ru"></div>
        <label class="row" style="gap:8px;margin-top:22px"><input type="checkbox" id="l_metrika" ${L.metrika ? "checked" : ""}> Яндекс Метрика + баннер cookies</label>
        <label class="row" style="gap:8px;margin-top:22px"><input type="checkbox" id="l_legal_docs" ${L.legal_docs ? "checked" : ""}> Юридические страницы (шаблоны)</label></div>
      <h3>Реквизиты для футера, оферты и платёжного сервиса</h3>
      <p class="meta">Это публичные данные: их требуют платёжные сервисы при проверке сайта. Ключи и пароли сюда не пиши — они вносятся только в .env на сервере.</p>
      <div class="grid3">${inp("legal_name", "Наименование / ФИО ИП", "ИП Иванов Иван Иванович")}${inp("inn", "ИНН")}${inp("ogrn", "ОГРН / ОГРНИП")}
        ${inp("address", "Адрес")}${inp("email", "Email для клиентов")}${inp("phone", "Телефон")}</div>
    </div></div>`;
}
function bindLaunch(t) {
  const box = t.querySelector("#launchBox"); if (!box) return;
  const pickServer = () => {
    const need = $("#l_on").checked && ($("#l_payments").value !== "none" || $("#l_forms").value !== "none");
    if (need) t.querySelectorAll("#b_stack button").forEach((x) => x.classList.toggle("on", x.dataset.v === "nextjs_server"));
  };
  $("#l_on").onchange = () => { box.hidden = !$("#l_on").checked; t.querySelector(".launch").classList.toggle("on", $("#l_on").checked); pickServer(); };
  $("#l_payments").onchange = () => { $("#l_otherBox").hidden = $("#l_payments").value !== "other"; $("#l_hint").textContent = RECEIPT_HINT[$("#l_payments").value] || ""; pickServer(); };
  $("#l_forms").onchange = pickServer;
  $("#l_legal").onchange = () => { if ($("#l_legal").value === "npd") { $("#l_tax").value = "npd"; $("#l_vat").value = "none"; $("#l_receipts").value = "npd"; } };
}
function readLaunch() {
  if (!$("#l_on")) return undefined;
  const v = (k) => $("#l_" + k).value;
  const c = {}; ["legal_name", "inn", "ogrn", "address", "email", "phone"].forEach((k) => (c[k] = $("#lc_" + k).value));
  return { on: $("#l_on").checked, legal: v("legal"), tax: v("tax"), vat: v("vat"), sells: v("sells"), checkout: v("checkout"),
    payments: v("payments"), payments_other: $("#l_payments_other").value, receipts: v("receipts"), forms: v("forms"),
    hosting: v("hosting"), domain: $("#l_domain").value, metrika: $("#l_metrika").checked, legal_docs: $("#l_legal_docs").checked, company: c };
}


// ---------------------------------------------------------------- видео (на вкладке «Фото и видео»)
const V_KIND = { ai: "ИИ", upload: "своё", enhanced: "улучшено" };
const vPoster = (s, f) => siteUrl(s, "videos", String(f).replace(/\.mp4$/i, ".jpg"));
const usd2 = (v) => "$" + Number(v || 0).toFixed(2);
function videoSection(s) {
  const V = s.videos || { slots: [], uploads: [] };
  const U = S.sites?.video?.usd || { generate: 0.112, studio: 0.168, upscale: 0.02 };
  const demo = S.state.settings.demo_mode;
  const ph = s.photos || { slots: [], uploads: [] };
  const srcs = [...ph.slots.filter((x) => x.chosen).map((x) => [x.chosen, `фото · ${x.id}`]),
    ...(ph.uploads || []).map((u) => [u.file, `своё · ${u.name || u.file}`])].filter((v, i, a) => a.findIndex((y) => y[0] === v[0]) === i);
  return `<div class="panel" id="videos"><div class="row"><div><h2>Видео для сайта</h2>
      <p class="hint" style="margin:0">Короткие ролики без звука — фон первого экрана, процесс работы, товар в деле. Места под видео предлагает фотодиректор вместе с планом фото, можно добавить своё.
      Видео — своё (ИИ доведёт до уровня дорогой съёмки) или из фото через ИИ (Kling 3.0). Выбранные видео уйдут в промпт и в сборку (<code>assets/videos</code> с постерами).</p></div></div>
    <div class="drop" id="vDrop" style="margin-top:12px">Перетащи свои видео (mp4, mov, webm) сюда или нажми, чтобы выбрать<input type="file" id="vIn" multiple accept="video/*,.mov,.m4v,.webm" hidden></div>
    ${V.uploads.length ? `<div class="ups">${V.uploads.map((u) => `<div class="up"><img class="poster" src="${vPoster(s, u.file)}" alt="">
      <div class="meta">${esc(u.name || u.file)} · ${esc(u.seconds)} с · ${esc(u.width)}×${esc(u.height)}</div>
      <select data-vuse="${esc(u.file)}"><option value="">— место —</option>${V.slots.map((x) => `<option value="${esc(x.id)}" ${u.slot === x.id ? "selected" : ""}>${esc(x.id)}</option>`).join("")}</select></div>`).join("")}</div>` : ""}
    <div class="vadd"><input type="text" id="va_sec" placeholder="Где на сайте: первый экран, «как мы работаем»…"><input type="text" id="va_subj" placeholder="Что в кадре">
      <select id="va_asp">${["16:9", "9:16", "1:1"].map((a) => `<option>${a}</option>`).join("")}</select><button class="btn" id="vaAdd">+ Место под видео</button></div>
  </div>
  <div class="slots">${V.slots.map((x) => vslotCard(s, x, srcs, U, demo)).join("")}</div>`;
}
function vslotCard(s, x, srcs, U, demo) {
  const ch = (x.variants || []).find((v) => v.file === x.chosen);
  const sec = ch?.seconds || x.duration || 5;
  const price = (m, t) => demo ? "$0" : "~" + usd2(U[m] * t);
  return `<div class="slot vslot ${x.chosen ? "has" : ""}" data-id="${esc(x.id)}">
    <div class="slot-img">${x.chosen ? `<video src="${siteUrl(s, "videos", x.chosen)}" poster="${vPoster(s, x.chosen)}" muted loop playsinline controls preload="metadata"></video>` : `<span>${esc(x.subject_ru || "нет видео")}</span>`}</div>
    <div class="b">
      <div class="row"><b>${esc(x.id)}</b><span class="badge">${esc(x.aspect)}</span><span class="meta">${esc(x.page || "")}${x.page ? " · " : ""}${esc(x.section || "")}</span><span class="spacer"></span>
        <button class="btn sm ghost vdel" title="Убрать место">✕</button></div>
      <p class="meta" style="margin:4px 0 8px">${esc(x.purpose || x.subject_ru || "")}</p>
      ${(x.variants || []).length ? `<div class="vars">${x.variants.map((v) => `<button data-vv="${esc(v.file)}" class="vv ${x.chosen === v.file ? "on" : ""}" title="${esc(V_KIND[v.kind] || v.kind)} · ${esc(v.seconds || "")} с"><img src="${vPoster(s, v.file)}" alt=""><i>${esc(V_KIND[v.kind] || "")}</i></button>`).join("")}</div>` : ""}
      <div class="row" style="margin-top:8px;flex-wrap:wrap;gap:6px">
        <select class="vsrc" style="max-width:200px">${srcs.length ? srcs.map(([f, t]) => `<option value="${esc(f)}">${esc(t)}</option>`).join("") : `<option value="">нет фото — сначала выбери фото</option>`}</select>
        <select class="vdur"><option value="5" ${x.duration !== 10 ? "selected" : ""}>5 с</option><option value="10" ${x.duration === 10 ? "selected" : ""}>10 с</option></select>
        <button class="btn sm primary vgen" ${srcs.length ? "" : "disabled"}>Видео из фото · <span class="vgp">${price("generate", x.duration === 10 ? 10 : 5)}</span></button></div>
      <div class="row" style="margin-top:6px;flex-wrap:wrap;gap:6px">
        <button class="btn sm vown">Своё видео</button><input type="file" class="vown-in" accept="video/*,.mov,.m4v,.webm" hidden>
        <button class="btn sm venh" data-mode="grade" ${x.chosen ? "" : "disabled"}>Цвет и резкость · $0</button>
        <button class="btn sm venh" data-mode="upscale" ${x.chosen ? "" : "disabled"}>Качество ×2 · ${price("upscale", sec)}</button>
        <button class="btn sm venh" data-mode="studio" ${x.chosen ? "" : "disabled"}>Как дорогая съёмка · ${price("studio", Math.min(Math.max(sec, 3), 10))}</button></div>
      <input type="text" class="vex" placeholder="Пожелание (необязательно): тёплый вечерний свет, медленный проезд камеры…" style="margin-top:8px">
      <details style="margin-top:8px"><summary class="meta">Промпт движения и пропорции</summary>
        <textarea class="vpe code" style="min-height:80px">${esc(x.prompt_en || "")}</textarea>
        <div class="grid2" style="margin-top:6px"><input type="text" class="vsub" value="${esc(x.subject_ru || "")}" placeholder="Что в кадре (по-русски)">
          <select class="vasp">${["16:9", "9:16", "1:1"].map((a) => `<option ${a === x.aspect ? "selected" : ""}>${a}</option>`).join("")}</select></div>
        <button class="btn sm vsave" style="margin-top:6px">Сохранить</button></details>
    </div></div>`;
}
function bindVideos(t, s) {
  const V = s.videos || { slots: [], uploads: [] };
  const U = S.sites?.video?.usd || { generate: 0.112, studio: 0.168, upscale: 0.02 };
  const demo = S.state.settings.demo_mode;
  const drop = $("#vDrop"), inp = $("#vIn");
  if (!drop) return;
  const up = async (files, slot = "") => { for (const f of files) { toast(`Загружаю и готовлю ${f.name}… (большое видео — до пары минут)`);
      await guard(async () => { S.site = await api(`/api/sites/${s.id}/videoupload?name=${encodeURIComponent(f.name)}&slot=${encodeURIComponent(slot)}`, { raw: f }); }); }
    render(); };
  drop.onclick = () => inp.click(); inp.onchange = () => up([...inp.files]);
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); up([...e.dataTransfer.files]); };
  t.querySelectorAll("[data-vuse]").forEach((sel) => (sel.onchange = () => guard(async () => { S.site = await api(`/api/sites/${s.id}/videouse`, { body: { file: sel.dataset.vuse, slot: sel.value } }); render(); })));
  $("#vaAdd").onclick = () => guard(async () => {
    const sec = $("#va_sec").value.trim(); if (!sec) return toast("Напиши, где на сайте будет видео", true);
    S.site = await api(`/api/sites/${s.id}/videoslotadd`, { body: { section: sec, subject_ru: $("#va_subj").value, aspect: $("#va_asp").value } }); render(); });
  t.querySelectorAll(".vslot").forEach((el) => {
    const id = el.dataset.id, x = V.slots.find((y) => y.id === id);
    const ch = (x.variants || []).find((v) => v.file === x.chosen);
    el.querySelectorAll("[data-vv]").forEach((b) => (b.onclick = () => guard(async () => { S.site = await api(`/api/sites/${s.id}/videochoose`, { body: { slot: id, file: b.dataset.vv } }); render(); })));
    el.querySelector(".vdel").onclick = () => guard(async () => { if (!confirm(`Убрать место «${id}»? Файлы видео останутся на диске.`)) return;
      S.site = await api(`/api/sites/${s.id}/videoslotdel`, { body: { slot: id } }); render(); });
    el.querySelector(".vdur").onchange = () => { el.querySelector(".vgp").textContent = demo ? "$0" : "~" + usd2(U.generate * +el.querySelector(".vdur").value); };
    el.querySelector(".vgen").onclick = () => guard(async () => {
      const dur = +el.querySelector(".vdur").value;
      if (!demo && !confirm(`Сделать видео ${dur} с из фото в Kling 3.0? Примерно ${usd2(U.generate * dur)}.`)) return;
      await api(`/api/sites/${s.id}/videoslot`, { body: { slot: id, prompt_en: el.querySelector(".vpe").value, duration: dur } });
      startJob(await api(`/api/sites/${s.id}/videogen`, { body: { slot: id, photo: el.querySelector(".vsrc").value, duration: dur, extra: el.querySelector(".vex").value } })); });
    const fi = el.querySelector(".vown-in");
    el.querySelector(".vown").onclick = () => fi.click();
    fi.onchange = () => up([...fi.files], id);
    el.querySelectorAll(".venh").forEach((b) => (b.onclick = () => guard(async () => {
      if (!x.chosen) return toast("Сначала выбери видео, которое улучшать", true);
      const m = b.dataset.mode, sec = ch?.seconds || 5;
      const cost = m === "upscale" ? U.upscale * sec : m === "studio" ? U.studio * Math.min(Math.max(sec, 3), 10) : 0;
      if (!demo && cost && !confirm(`${b.textContent.split("·")[0].trim()} — примерно ${usd2(cost)}. Запустить?`)) return;
      startJob(await api(`/api/sites/${s.id}/videoenhance`, { body: { slot: id, file: x.chosen, mode: m, extra: el.querySelector(".vex").value, seconds: 10 } })); })));
    el.querySelector(".vsave").onclick = () => guard(async () => {
      S.site = await api(`/api/sites/${s.id}/videoslot`, { body: { slot: id, prompt_en: el.querySelector(".vpe").value, subject_ru: el.querySelector(".vsub").value, aspect: el.querySelector(".vasp").value } });
      toast("Сохранено"); });
  });
}
