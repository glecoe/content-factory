// Оболочка студии: два равноправных режима (Контент-завод и Лаборатория сайтов), их проекты-ниши,
// плавные переходы между режимами и настройки по вкладкам.
const LS = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* приватный режим */ } },
};
S.mode = LS.get("cf.mode", "factory") === "lab" ? "lab" : "factory";
S.niche = LS.get("cf.niche", "");
S.lab = LS.get("cf.lab", "");
S.pageBy = { factory: "home", lab: "labhome" };
S.page = S.mode === "lab" ? "labhome" : "home";
S.setTab = null;

const ICONS = {
  factory: `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="3.5"/><path d="M10.2 9.3v5.4l4.6-2.7z" fill="currentColor" stroke="none"/></svg>`,
  lab: `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3.5"/><path d="M3 9h18M7.5 13.5h5M7.5 16.5h8"/></svg>`,
};
const MODES = {
  factory: { title: "Контент-завод", sub: "ролики", space: "Ниша", spaces: "Ниши", add: "Добавить изделие" },
  lab: { title: "Лаборатория", sub: "сайты", space: "Направление", spaces: "Направления", add: "Новый сайт" },
};
TYPE_NAMES.B = "в деле";
TAGS.splice(TAGS.indexOf("кольцо не то"), 1, "товар не тот");

// ---------------------------------------------------------------- переходы
const reduceMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
function animateView() {
  const v = $("#view"), t = $("#top");
  for (const el of [t, v]) { el.classList.remove("enter"); void el.offsetWidth; el.classList.add("enter"); }
}
async function withTransition(ev, fn, kind = "mode") {
  if (ev && ev.clientX != null) {
    document.documentElement.style.setProperty("--vt-x", ev.clientX + "px");
    document.documentElement.style.setProperty("--vt-y", ev.clientY + "px");
  }
  document.documentElement.dataset.vt = kind;
  if (document.startViewTransition && !reduceMotion()) {
    const t = document.startViewTransition(async () => { await fn(); });
    try { await t.finished; } catch { /* прервано — не страшно */ }
  } else {
    await fn();
  }
}

async function switchMode(mode, ev) {
  if (mode === S.mode) return;
  S.pageBy[S.mode] = S.page;
  if (mode === "lab") await guard(loadSites);      // данные заранее, чтобы переход шёл без пустых кадров
  await withTransition(ev, async () => {
    S.mode = mode; LS.set("cf.mode", mode);
    S.page = S.pageBy[mode] || (mode === "lab" ? "labhome" : "home");
    if (S.page === "site" && !S.site) S.page = "labhome";
    if (S.page === "product" && !S.product) S.page = "home";
    render();
  });
}

async function switchNiche(id, ev) {
  if (id === S.niche) { S.page = "home"; render(); return; }
  S.niche = id; LS.set("cf.niche", id); S.product = null; S.research = null;
  await loadState();
  await withTransition(ev, async () => { S.page = "home"; render(); }, "space");
}
async function switchLab(id, ev) {
  S.lab = id; LS.set("cf.lab", id); S.site = null; ADM.data = null; ADM.site = ""; ADM.allSites = null;
  await loadSites();
  await withTransition(ev, async () => { S.page = "labhome"; render(); }, "space");
}

// ---------------------------------------------------------------- боковая панель
function renderRail() {
  if (!S.state) return;
  const st = S.state.settings, M = MODES[S.mode], fac = S.mode === "factory";
  const spaces = fac ? S.state.niches : (S.sites?.labs || S.state.labs || []);
  const cur = fac ? S.state.niche : (S.sites?.lab || spaces.find((x) => x.id === S.lab) || spaces[0] || { name: "—" });
  const items = fac ? S.state.products : (S.sites?.projects || []);
  const nav = fac
    ? [["home", "Обзор ниши"], ["research", "Тренды ниши"], ["taste", "Вкус ниши"], ["niche", "Контекст ниши"], ["costs", "Расходы"]]
    : [["labhome", "Обзор направления"], ["admin", "Админка · статистика"], ["lab", "Контекст направления"]];
  $("#rail").innerHTML = `
    <div class="switch" role="tablist" aria-label="Режим">
      <span class="thumb"></span>
      ${Object.entries(MODES).map(([k, m]) => `<button role="tab" aria-selected="${S.mode === k}" data-mode="${k}" class="${S.mode === k ? "on" : ""}">
        <span class="ico">${ICONS[k]}</span><span class="sw-t"><b>${m.title}</b><small>${m.sub}</small></span></button>`).join("")}
    </div>
    <div class="space">
      <button class="space-btn" id="spaceBtn" aria-haspopup="true"><small>${M.space}</small><b>${esc(cur.name)}</b><i>▾</i></button>
      <div class="space-pop" id="spacePop" hidden>
        ${spaces.map((x) => `<button data-space="${esc(x.id)}" class="${x.id === cur.id ? "on" : ""}"><b>${esc(x.name)}</b><small>${fac ? `изделий: ${x.products}` : `сайтов: ${x.sites}`}</small></button>`).join("")}
        <button data-space="__new" class="new">＋ ${fac ? "Новая ниша" : "Новое направление"}</button>
      </div>
    </div>
    <button class="btn primary wide" id="primaryBtn">${M.add}</button>
    <nav class="items">${items.length ? items.map((p) => fac
      ? `<button data-item="${esc(p.id)}" class="${S.page === "product" && S.product?.id === p.id ? "on" : ""}"><div class="p-name">${esc(p.name || "Без названия")}</div><div class="p-meta">клипов: ${p.clips} · роликов: ${p.videos}</div></button>`
      : `<button data-item="${esc(p.id)}" class="${S.page === "site" && S.site?.id === p.id ? "on" : ""}"><div class="p-name">${esc(p.name)}</div><div class="p-meta">${p.kind === "landing" ? "лендинг" : "сайт"} · ${esc(p.stage)}</div></button>`).join("")
      : `<div class="empty-rail">${fac ? "Изделий в нише пока нет" : "Сайтов в направлении пока нет"}</div>`}</nav>
    <nav class="railnav">${nav.map(([k, t]) => `<button data-page="${k}" class="${S.page === k ? "on" : ""}">${t}</button>`).join("")}</nav>
    <div class="status">
      <div><span class="dot ${claudeOK() ? "on" : ""}"></span>Claude ${claudeOK() ? "по подписке" : "не подключён"}</div>
      <div><span class="dot ${geminiOK() ? "on" : ""}"></span>Gemini ${geminiOK() ? "подключён" : "нет ключа"}</div>
      <div><span class="dot ${st.demo_mode ? "" : "on"}"></span>${st.demo_mode ? "fal.ai: демо-режим, $0" : `fal.ai: сегодня ${usd(S.state.costs.today)} из ${usd(st.daily_limit_usd)}`}</div>
    </div>
    <nav class="railnav last"><button data-page="settings" class="${S.page === "settings" ? "on" : ""}">Настройки</button></nav>`;
  const rail = $("#rail");
  rail.querySelectorAll("[data-mode]").forEach((b) => (b.onclick = (e) => switchMode(b.dataset.mode, e)));
  const pop = $("#spacePop");
  $("#spaceBtn").onclick = (e) => { e.stopPropagation(); pop.hidden = !pop.hidden; };
  document.addEventListener("click", () => { if (pop) pop.hidden = true; }, { once: true });
  pop.querySelectorAll("[data-space]").forEach((b) => (b.onclick = (e) => {
    pop.hidden = true;
    if (b.dataset.space === "__new") { S.page = fac ? "home" : "labhome"; S.newSpace = true; render(); return; }
    guard(() => (fac ? switchNiche(b.dataset.space, e) : switchLab(b.dataset.space, e)));
  }));
  $("#primaryBtn").onclick = () => guard(fac ? newProduct : newSite);
  rail.querySelectorAll("[data-item]").forEach((b) => (b.onclick = () => guard(async () => {
    if (fac) { await loadProduct(b.dataset.item); S.page = "product"; S.tab = S.tab || "item"; S.selected.clear(); }
    else { await loadSite(b.dataset.item); S.page = "site"; S.siteTab = S.siteTab || "brief"; }
    render();
  })));
  rail.querySelectorAll(".railnav [data-page]").forEach((b) => (b.onclick = () => guard(async () => {
    S.page = b.dataset.page;
    if (S.page === "research") await loadResearch();
    if (S.page === "labhome") await loadSites();
    if (S.page === "admin") ADM.data = null;
    render();
  })));
}

async function newProduct() {
  const p = await api("/api/products", { body: { name: "Новое изделие", niche: S.niche } });
  await loadState(); await loadProduct(p.id); S.page = "product"; S.tab = "item"; render();
}
async function newSite() {
  const p = await api("/api/sites", { body: { name: "Новый сайт", kind: "landing", lab: S.lab } });
  S.site = p; S.page = "site"; S.siteTab = "brief"; await loadSites(); render();
}

// ---------------------------------------------------------------- роутинг
function render() {
  document.body.dataset.mode = S.mode;
  document.title = S.mode === "lab" ? "Лаборатория сайтов" : "Контент-завод";
  renderRail();
  const v = $("#view"), top = $("#top");
  animateView();
  if (S.page === "settings") return renderSettings(v, top);
  if (S.mode === "lab") {
    if (S.page === "site" && S.site) return renderSite(v, top);
    if (S.page === "lab") return renderLabCtx(v, top);
    if (S.page === "admin") return renderAdmin(v, top);
    return renderSites(v, top);
  }
  if (S.page === "product" && S.product) return renderProduct(v, top);
  if (S.page === "research") return renderResearch(v, top);
  if (S.page === "taste") return renderTaste(v, top);
  if (S.page === "costs") return renderCosts(v, top);
  if (S.page === "niche") return renderNicheCtx(v, top);
  return renderFactoryHome(v, top);
}

// ---------------------------------------------------------------- карточки проектов (ниш / направлений)
function spaceCards(list, curId, fac) {
  return `<div class="spaces">${list.map((x, i) => `<button class="space-card ${x.id === curId ? "on" : ""}" data-sp="${esc(x.id)}" style="--i:${i}">
      <span class="sc-k">${fac ? "ниша" : "направление"}</span><b>${esc(x.name)}</b>
      <span class="sc-d">${esc(x.description || "")}</span>
      <span class="sc-n">${fac ? `${x.products} изд.` : `${x.sites} сайт.`}</span></button>`).join("")}
    <button class="space-card add" data-sp="__new"><span class="plus">＋</span><b>${fac ? "Новая ниша" : "Новое направление"}</b>
      <span class="sc-d">${fac ? "косметика, одежда, мебель — свой вкус, тренды и изделия" : "клиники, рестораны, лендинги для экспертов — свой контекст и вкус"}</span></button></div>
  <div class="panel new-space" id="newSpace" ${S.newSpace ? "" : "hidden"}>
    <h2>${fac ? "Новая ниша" : "Новое направление"}</h2>
    <p class="hint">${fac ? "У ниши будут свои изделия, профиль вкуса, тренды и правила для нейросетей. Опиши подробно, что продаём — ИИ сам заполнит технический контекст." : "У направления будут свои сайты, вкус и правила. Опиши, какие сайты здесь делаем и для кого."}</p>
    <div class="grid2"><div class="field"><label>Название</label><input type="text" id="ns_name" placeholder="${fac ? "Косметика" : "Медицина"}"></div>
      <div class="field"><label>${fac ? "Аудитория" : "Клиенты"}</label><input type="text" id="ns_aud" placeholder="${fac ? "Женщины 25–40, уход за кожей" : "Частные клиники и стоматологии"}"></div></div>
    <div class="field"><label>${fac ? "Что продаём" : "Какие сайты делаем"}</label><textarea id="ns_desc" placeholder="${fac ? "Уходовая косметика: сыворотки и кремы в стеклянных флаконах, премиум-сегмент" : "Сайты клиник: доверие, врачи, цены, онлайн-запись"}"></textarea></div>
    ${fac ? "" : `<div class="field"><label>Предпочтения по стилю (необязательно)</label><input type="text" id="ns_style" placeholder="Светлые, спокойные, много воздуха"></div>`}
    <div class="row"><button class="btn primary" id="ns_create">Создать</button><button class="btn ghost" id="ns_cancel">Отмена</button></div>
  </div>`;
}
function bindSpaceCards(fac) {
  document.querySelectorAll("[data-sp]").forEach((b) => (b.onclick = (e) => {
    if (b.dataset.sp === "__new") { S.newSpace = true; $("#newSpace").hidden = false; $("#ns_name").focus(); return; }
    guard(() => (fac ? switchNiche(b.dataset.sp, e) : switchLab(b.dataset.sp, e)));
  }));
  const c = $("#ns_create"); if (!c) return;
  $("#ns_cancel").onclick = () => { S.newSpace = false; $("#newSpace").hidden = true; };
  c.onclick = () => guard(async () => {
    const name = $("#ns_name").value.trim();
    if (!name) return toast("Напиши название", true);
    S.newSpace = false;
    if (fac) {
      const n = await api("/api/niches", { body: { name, description: $("#ns_desc").value, audience: $("#ns_aud").value } });
      S.niche = n.id; LS.set("cf.niche", n.id); S.product = null; S.research = null; await loadState();
      if (brainOK() && $("#ns_desc").value.trim()) startJob(await api(`/api/niches/${n.id}/fill`, { body: {} }));
      S.page = "niche"; render(); toast("Ниша создана — ИИ заполняет контекст для нейросетей");
    } else {
      const l = await api("/api/labs", { body: { name, description: $("#ns_desc").value, audience: $("#ns_aud").value, style: $("#ns_style").value } });
      S.lab = l.id; LS.set("cf.lab", l.id); await loadSites(); S.page = "labhome"; render(); toast("Направление создано");
    }
  });
}

// ---------------------------------------------------------------- главная завода
function renderFactoryHome(v, top) {
  const st = S.state.settings, tools = S.state.tools, cl = S.state.brains.claude, N = S.state.niche;
  const ok = (b) => `<span class="tick ${b ? "on" : ""}">${b ? "✓" : "•"}</span>`;
  top.innerHTML = `<div><div class="eyebrow">Контент-завод · ниша</div><h1>${esc(N.name)}</h1>
    <div class="sub">${esc(N.description || "Опиши нишу в «Контексте ниши»")}</div></div>
    <button class="btn" id="toCtx">Контекст ниши</button>`;
  $("#toCtx").onclick = () => { S.page = "niche"; render(); };
  const prods = S.state.products;
  v.innerHTML = `${spaceCards(S.state.niches, N.id, true)}
  <div class="grid-home">
    <div class="panel"><div class="row"><h2>Изделия ниши</h2><span class="spacer"></span><button class="btn primary sm" id="hpAdd">Добавить изделие</button></div>
      ${prods.length ? `<div class="mini-list">${prods.map((p) => `<button data-open="${esc(p.id)}"><b>${esc(p.name || "Без названия")}</b><span class="meta">клипов ${p.clips} · роликов ${p.videos}</span></button>`).join("")}</div>`
        : `<p class="hint">Пока пусто. Добавь изделие: 3–4 фото и короткое видео — завод сделает ролики.</p>`}</div>
    <div class="panel"><h2>Готовность</h2><ul class="check">
      <li>${ok(tools.ffmpeg)} ${tools.ffmpeg ? "FFmpeg найден" : "<b>Установи FFmpeg</b>: <code>brew install ffmpeg</code>"}</li>
      <li>${ok(cl.logged_in)} ${cl.logged_in ? "Claude по подписке подключён" : cl.installed ? "Claude Code: войди командой <code>claude</code>" : "Установи Claude Code"}</li>
      <li>${ok(st.fal_key_set)} ${st.fal_key_set ? "fal.ai подключён" : "fal.ai — позже, пока демо-режим"}</li>
      <li>${ok(N.product_en && N.product_en !== "product" || N.id === "jewelry")} ${N.id === "jewelry" || (N.product_en && N.product_en !== "product") ? "Контекст ниши для нейросетей заполнен" : "Заполни контекст ниши (кнопка «Заполнить ИИ»)"}</li>
      <li>${ok(S.state.research.active)} ${S.state.research.active ? `Бриф трендов ниши: ${esc(S.state.research.active)}` : "Запусти ресёрч в «Трендах ниши»"}</li>
      <li>${ok(S.state.ratings)} ${S.state.ratings ? `Оценок в нише: ${S.state.ratings}` : "Оцени первые ролики — так копится вкус ниши"}</li>
      <li>${ok(S.state.music.length)} ${S.state.music.length ? `Музыка: ${S.state.music.length} трек(ов)` : "Положи треки в <code>data/music</code>"}</li>
    </ul></div>
  </div>`;
  bindSpaceCards(true);
  $("#hpAdd").onclick = () => guard(newProduct);
  v.querySelectorAll("[data-open]").forEach((b) => (b.onclick = () => guard(async () => { await loadProduct(b.dataset.open); S.page = "product"; S.tab = "item"; render(); })));
}

// ---------------------------------------------------------------- контекст ниши
const NICHE_GROUPS = [
  ["О нише", [["name", "Название"], ["description", "Что продаём", 3], ["audience", "Аудитория", 2], ["tone", "Тон и настроение бренда", 2], ["markets", "Рынки"]]],
  ["Для нейросетей", [["product_ru", "Товар одним словом (RU)"], ["product_en", "Товар одним словом (EN)"], ["use_ru", "Как товар показывают в деле (RU)"],
    ["use_en", "In-use shot (EN)"], ["model_en", "Кто/что в ИИ-кадрах (EN)", 2], ["fidelity_en", "Что нельзя менять в товаре (EN)", 2],
    ["passport_en", "Что описывать в паспорте товара (EN)", 2], ["look_en", "Стиль рекламы (EN)", 2], ["negative_en", "Негативный промпт (EN)", 3]]],
];
function renderNicheCtx(v, top) {
  const N = S.state.niche;
  top.innerHTML = `<div><div class="eyebrow">Контент-завод · ниша</div><h1>Контекст: ${esc(N.name)}</h1>
    <div class="sub">Эти данные получает каждый агент ниши: сценарист, ресёрчер, монтажёр, контролёр, автор текстов.</div></div>`;
  v.innerHTML = NICHE_GROUPS.map(([g, fields], gi) => `<div class="panel"><div class="row"><h2>${g}</h2><span class="spacer"></span>
      ${gi === 1 ? `<button class="btn sm" id="nFill" ${brainOK() ? "" : "disabled"}>Заполнить ИИ по описанию · ${who("research")}</button>` : ""}</div>
      ${gi === 1 ? `<p class="hint">Технические подсказки для видео- и фото-моделей. ИИ заполнит их по описанию ниши — потом можно поправить руками.</p>` : ""}
      <div class="grid2">${fields.map(([k, label, rows]) => `<div class="field ${rows === 3 ? "span2" : ""}"><label>${label}</label>${rows
        ? `<textarea data-k="${k}" style="min-height:${rows * 30 + 20}px">${esc(N[k] || "")}</textarea>` : `<input type="text" data-k="${k}" value="${esc(N[k] || "")}">`}</div>`).join("")}</div></div>`).join("") +
    `<div class="row" style="margin-bottom:16px"><button class="btn primary" id="nSave">Сохранить</button><span class="spacer"></span>
      ${S.state.niches.length > 1 ? `<button class="btn ghost" id="nArch">Убрать нишу в архив</button><button class="btn danger" id="nDel">Удалить нишу</button>` : ""}</div>`;
  $("#nSave").onclick = () => guard(async () => {
    const body = {}; v.querySelectorAll("[data-k]").forEach((el) => (body[el.dataset.k] = el.value));
    await api(`/api/niches/${N.id}/update`, { body }); await loadState(); toast("Контекст сохранён"); render();
  });
  $("#nFill").onclick = () => guard(async () => startJob(await api(`/api/niches/${N.id}/fill`, { body: {} })));
  if ($("#nArch")) $("#nArch").onclick = () => guard(async () => {
    if (!confirm(`Убрать «${N.name}» в архив? Данные останутся на диске.`)) return;
    await api(`/api/niches/${N.id}/archive`, { body: {} }); S.niche = ""; LS.set("cf.niche", ""); await loadState(); S.page = "home"; render();
  });
  if ($("#nDel")) $("#nDel").onclick = () => guard(async () => {
    const n = S.state.products.length;
    if (!confirm(`Удалить нишу «${N.name}» навсегда?\n\nУдалятся контекст, вкус, оценки, тренды${n ? ` и ${n} изд. со всеми кадрами и роликами` : ""}. Отменить нельзя.`)) return;
    const r = await api(`/api/niches/${N.id}/delete`, { body: {} });
    S.niche = ""; LS.set("cf.niche", ""); S.product = null; S.research = null; await loadState(); S.page = "home"; render();
    toast(`Ниша «${r.name}» удалена${r.products ? `, изделий: ${r.products}` : ""}`);
  });
}

// ---------------------------------------------------------------- контекст направления (лаборатория)
function renderLabCtx(v, top) {
  const L = S.sites?.lab;
  if (!L) { loadSites().then(render); return; }
  const F = [["name", "Название"], ["description", "Какие сайты делаем, для кого", 3], ["audience", "Клиенты направления", 2],
    ["style", "Предпочтения по стилю", 2], ["notes", "Правила и ограничения (что обязательно, чего нельзя)", 3]];
  top.innerHTML = `<div><div class="eyebrow">Лаборатория сайтов · направление</div><h1>Контекст: ${esc(L.name)}</h1>
    <div class="sub">Получают все агенты направления: ресёрчер, стратег, фотодиректор, автор промптов и сборщик.</div></div>`;
  v.innerHTML = `<div class="panel"><div class="grid2">${F.map(([k, label, rows]) => `<div class="field ${rows === 3 ? "span2" : ""}"><label>${label}</label>${rows
      ? `<textarea data-k="${k}" style="min-height:${rows * 30 + 20}px">${esc(L[k] || "")}</textarea>` : `<input type="text" data-k="${k}" value="${esc(L[k] || "")}">`}</div>`).join("")}</div>
    <div class="row"><button class="btn primary" id="lSave">Сохранить</button><span class="spacer"></span>
      ${(S.sites.labs || []).length > 1 ? `<button class="btn ghost" id="lArch">Убрать в архив</button><button class="btn danger" id="lDel">Удалить направление</button>` : ""}</div></div>`;
  $("#lSave").onclick = () => guard(async () => {
    const body = {}; v.querySelectorAll("[data-k]").forEach((el) => (body[el.dataset.k] = el.value));
    await api(`/api/labs/${L.id}/update`, { body }); await loadSites(); toast("Сохранено"); render();
  });
  if ($("#lArch")) $("#lArch").onclick = () => guard(async () => {
    if (!confirm(`Убрать «${L.name}» в архив?`)) return;
    await api(`/api/labs/${L.id}/archive`, { body: {} }); S.lab = ""; LS.set("cf.lab", ""); await loadSites(); S.page = "labhome"; render();
  });
  if ($("#lDel")) $("#lDel").onclick = () => guard(async () => {
    const n = (S.sites.projects || []).length;
    if (!confirm(`Удалить направление «${L.name}» навсегда?\n\nУдалятся контекст и вкус направления${n ? ` и ${n} сайт(ов) со всеми фото, промптами, сборками и статистикой` : ""}. Отменить нельзя.`)) return;
    const r = await api(`/api/labs/${L.id}/delete`, { body: {} });
    S.lab = ""; LS.set("cf.lab", ""); S.site = null; ADM.data = null; await loadSites(); S.page = "labhome"; render();
    toast(`Направление «${r.name}» удалено${r.sites ? `, сайтов: ${r.sites}` : ""}`);
  });
}

// ---------------------------------------------------------------- настройки по вкладкам
function renderSettings(v, top) {
  const st = S.state.settings, tools = S.state.tools, cl = S.state.brains.claude;
  const opt = (val, cur, label) => `<option value="${val}" ${String(cur) === String(val) ? "selected" : ""}>${label}</option>`;
  const tab = S.setTab || "common";
  const roles = (pred) => `<table class="kv">${Object.entries(st.roles).filter(([r]) => pred(r)).map(([r, label]) =>
    `<tr><td>${esc(label.replace(/^Сайты · (.)/, (m, c) => c.toUpperCase()))}</td><td><select data-role="${r}">${opt("claude", st.providers[r], "Claude (подписка)")}${opt("gemini", st.providers[r], "Gemini API")}</select></td></tr>`).join("")}</table>`;
  top.innerHTML = `<div><div class="eyebrow">Студия</div><h1>Настройки</h1><div class="sub">Ключи хранятся только в файле .env на этом компьютере или сервере.</div></div>`;
  const tabs = [["common", "Общие"], ["factory", "Контент-завод"], ["lab", "Лаборатория сайтов"]];
  const body = {
    common: `
  <div class="panel"><h2>Claude по подписке</h2>
    <p class="hint">Оба цеха вызывают Claude Code в фоне (<code>claude -p</code>) — тратится лимит подписки, API-ключ не нужен. На сервере: <code>claude setup-token</code> на своём компьютере и токен сюда.</p>
    <table class="kv">
      <tr><td>Claude Code</td><td>${cl.installed ? `найден: ${esc(cl.version || "")} <span class="meta">${esc(cl.bin || "")}</span>` : `не найден — <code>curl -fsSL https://claude.ai/install.sh | bash</code>`}</td></tr>
      <tr><td>Вход</td><td>${cl.logged_in ? `выполнен (${esc(cl.method || "")}${cl.email ? ", " + esc(cl.email) : ""})` : "не выполнен — в Терминале набери <code>claude</code> и войди"}</td></tr></table>
    <div class="grid2" style="margin-top:12px">
      <div class="field"><label>Модель Claude</label><select data-s="CLAUDE_MODEL">${opt("opus", st.claude_model, "Opus — лучшее качество")}${opt("sonnet", st.claude_model, "Sonnet — быстрее, меньше тратит лимит")}${opt("haiku", st.claude_model, "Haiku — самый экономный")}</select></div>
      <div class="field"><label>Путь к claude</label><p class="meta">${st.claude_bin ? esc(st.claude_bin) : "находится автоматически"} · меняется только в файле <code>.env</code> (CLAUDE_BIN)</p></div></div>
    <div class="field"><label>Токен для сервера (CLAUDE_CODE_OAUTH_TOKEN) ${st.oauth_token_set ? "— сохранён; «-» чтобы стереть" : ""}</label><input type="password" autocomplete="new-password" data-s="CLAUDE_CODE_OAUTH_TOKEN" placeholder="${st.oauth_token_set ? "••••••••" : "необязательно на Mac"}"></div>
    <div class="row"><button class="btn" id="testC" ${cl.installed ? "" : "disabled"}>Проверить Claude</button><button class="btn ghost" id="reC">Обновить статус</button></div></div>
  <div class="panel"><h2>Ключи</h2>
    <div class="field"><label>fal.ai — видео, фото для финала и для сайтов ${st.fal_key_set ? "— сохранён" : ""}</label><input type="password" autocomplete="new-password" data-s="FAL_KEY" placeholder="${st.fal_key_set ? "••••••••" : "fal.ai/dashboard/keys"}"></div>
    <div class="field"><label>Gemini API ${st.gemini_key_set ? "— сохранён" : ""}</label><input type="password" autocomplete="new-password" data-s="GEMINI_API_KEY" placeholder="${st.gemini_key_set ? "••••••••" : "aistudio.google.com/apikey"}"></div>
    <div class="field"><label>Apify (по желанию) ${st.apify_set ? "— сохранён" : ""}</label><input type="password" autocomplete="new-password" data-s="APIFY_TOKEN" placeholder="${st.apify_set ? "••••••••" : "console.apify.com → Settings → Integrations"}"></div>
    <div class="grid2"><div class="field"><label>Модель Gemini</label><input type="text" data-s="GEMINI_MODEL" value="${esc(st.gemini_model)}"></div>
      <div class="field"><label>Дневной лимит трат fal.ai, $ (на оба цеха)</label><input type="number" data-s="DAILY_LIMIT_USD" min="0" step="1" value="${st.daily_limit_usd}"></div></div>
    <label class="row" style="gap:8px"><input type="checkbox" data-s="DEMO_MODE" data-check="1" ${st.demo_flag ? "checked" : ""}> Демо-режим: fal.ai не вызывается, вместо генераций — бесплатные заглушки</label></div>
  <div class="panel"><h2>Сервер</h2>
    <p class="hint">Эти настройки ради безопасности меняются только руками в файле <code>.env</code> в папке проекта (потом перезапуск). Как открыть студию на сервере — в <code>SERVER.md</code>.</p>
    <table class="kv">
      <tr><td>Адрес</td><td>${esc(st.host || "127.0.0.1")}:${esc(st.port || "8765")}</td></tr>
      <tr><td>Пароль</td><td>${st.password_set ? `задан (логин ${esc(st.auth_user || "admin")})` : "не задан — студия доступна только с этого компьютера"}</td></tr>
      ${st.allowed_hosts ? `<tr><td>Разрешённые домены</td><td>${esc(st.allowed_hosts)}</td></tr>` : ""}</table></div>
  <div class="panel"><h2>Проверка компьютера</h2><table>
    <tr><td>FFmpeg</td><td>${tools.ffmpeg ? "найден" : "не найден — <code>brew install ffmpeg</code>"}</td></tr>
    <tr><td>Кодек видео</td><td>${esc(tools.encoder || "—")}</td></tr>
    <tr><td>Конвертер фото iPhone (sips)</td><td>${tools.sips ? "есть" : "нет — HEIC лучше заранее перевести в JPG"}</td></tr></table></div>`,
    factory: `
  <div class="panel"><h2>Конвейер роликов</h2><div class="grid2">
    <div class="field"><label>Концептов за один заход сценариста</label><input type="number" data-s="CONCEPTS_N" min="1" max="8" value="${st.concepts_n}"></div>
    <div class="field"><label>Переделывать забракованный кадр</label><select data-s="AUTO_RETRY">${[0, 1, 2].map((n) => opt(n, st.auto_retry, n === 0 ? "не переделывать" : n + " раз")).join("")}</select></div>
    <div class="field"><label>Вертикаль для кадров из фото</label><select data-s="VERTICAL_MODE">${opt("nb2", st.vertical_mode, "Nano Banana 2 дорисовывает фон до 9:16 (+$0.08 за фото)")}${opt("blur", st.vertical_mode, "Фото на размытом фоне (бесплатно)")}${opt("off", st.vertical_mode, "Не менять")}</select></div>
    <div class="field"><label>Не вертикальный клип при монтаже</label><select data-s="MONTAGE_FIT">${opt("crop", st.montage_fit, "обрезать края")}${opt("blur", st.montage_fit, "вписать на размытый фон")}</select></div></div></div>
  <div class="panel"><h2>Кто какую работу делает</h2><p class="hint">Если выбранный «мозг» недоступен или упёрся в лимит — задача сама уходит на второй.</p>
    ${roles((r) => !r.startsWith("site_"))}<p class="meta">Контролёр кадров и разбор видео — Gemini (видит видео); без ключа — Claude по кадрам.</p></div>
  <div class="panel"><h2>Библиотека съёмки</h2>
    <p class="hint">Фото и видео «По изделиям» лежат в <code>library/</code> проекта, по папке на изделие.</p>
    <p class="meta">Папка: ${st.library_dir ? esc(st.library_dir) : "<code>library/</code> в проекте"} · другую папку можно указать только в файле <code>.env</code> (LIBRARY_DIR).</p></div>`,
    lab: `
  <div class="panel"><h2>Ресёрч и сборка</h2><div class="grid2">
    <div class="field"><label>Скриншоты сайтов-референсов</label><select data-s="SITE_SHOTS">${opt("1", st.site_shots ? "1" : "0", "делать (нужен Playwright)")}${opt("0", st.site_shots ? "1" : "0", "не делать — только текстовый ресёрч")}</select></div>
    <div class="field"><label>Модель для сборки кода</label><select data-s="SITE_BUILD_MODEL">${opt("sonnet", st.site_build_model, "Sonnet — быстрее, бережёт лимит (рекомендую)")}${opt("opus", st.site_build_model, "Opus — тщательнее, но в 2–3 раза дольше")}</select></div>
    <div class="field"><label>Минут на одну сессию сборки</label><input type="number" data-s="SITE_BUILD_MINUTES" min="10" max="180" step="5" value="${st.site_build_minutes}"></div>
    <div class="field"><label>Шагов Claude Code на сессию</label><input type="number" data-s="SITE_BUILD_TURNS" min="20" max="400" step="10" value="${st.site_build_turns}"></div>
    <div class="field"><label>Автоматических продолжений, если сессии не хватило</label><input type="number" data-s="SITE_BUILD_RESUMES" min="0" max="10" value="${st.site_build_resumes}"></div></div>
    <p class="meta">Большой сайт не обязан уложиться в одну сессию: если время или шаги кончились, Claude Code продолжает в новой сессии с того же места. Сделанное никогда не теряется.</p>
    <p class="meta">Фото для сайтов генерирует Nano Banana 2 через ключ fal.ai из «Общих», с тем же дневным лимитом.</p></div>
  <div class="panel"><h2>Кто какую работу делает</h2>${roles((r) => r.startsWith("site_"))}
    <p class="meta">Сборку сайта всегда делает Claude Code — по подписке.</p></div>`,
  };
  v.innerHTML = `<div class="tabs" role="tablist">${tabs.map(([k, t]) => `<button role="tab" data-tab="${k}" class="${tab === k ? "on" : ""}">${t}</button>`).join("")}</div>
    <div class="tabbody">${body[tab]}</div>
    <div class="row" style="margin-bottom:16px"><button class="btn primary" id="saveS">Сохранить</button></div>`;
  v.querySelectorAll(".tabs [data-tab]").forEach((b) => (b.onclick = () => { S.setTab = b.dataset.tab; render(); }));
  if ($("#testC")) $("#testC").onclick = () => guard(async () => startJob(await api("/api/claude/test", { body: {} })));
  if ($("#reC")) $("#reC").onclick = () => guard(async () => { await api("/api/claude/status", { body: {} }); await refresh(); toast("Статус обновлён"); });
  $("#saveS").onclick = () => guard(async () => {
    const b = {};
    v.querySelectorAll("[data-s]").forEach((el) => (b[el.dataset.s] = el.dataset.check ? (el.checked ? "1" : "0") : el.value));
    v.querySelectorAll("[data-role]").forEach((s) => (b["PROVIDER_" + s.dataset.role.toUpperCase()] = s.value));
    await api("/api/settings", { body: b }); toast("Настройки сохранены"); await refresh();
  });
}

// ---------------------------------------------------------------- старт
(async () => {
  document.body.dataset.mode = S.mode;
  try {
    await loadState();
    if (S.mode === "lab") await loadSites();
    for (const j of S.state.jobs) S.jobs[j.id] = j;
    if (S.state.jobs.length) pollJobs();
    render();
  } catch (e) {
    $("#view").innerHTML = `<div class="panel"><h2>Сервер не отвечает</h2><p class="hint">${esc(e.message)}. Запусти start.command ещё раз.</p></div>`;
  }
})();
