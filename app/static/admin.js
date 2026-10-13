// Лаборатория сайтов · «Админка»: статистика сайтов — посетители, интересы, заявки, продажи
const ADM = { scope: "lab", site: "", days: 30, metric: "visitors", data: null };
const METRICS = [["visitors", "Посетители"], ["views", "Просмотры"], ["leads", "Заявки"], ["orders", "Продажи"], ["revenue", "Выручка"]];
const num = (v) => Math.round(Number(v || 0)).toLocaleString("ru-RU");
const money = (v) => num(v) + " ₽";
const pct = (v) => Number(v || 0).toLocaleString("ru-RU", { maximumFractionDigits: 1 }) + "%";
const fmtM = (m, v) => (m === "revenue" ? money(v) : num(v));
const dayRu = (d) => new Date(d + "T12:00").toLocaleDateString("ru-RU", { day: "numeric", month: "short" });

async function loadAdmin() {
  const lab = ADM.scope === "all" ? "__all__" : S.lab;
  ADM.data = await api(`/api/stats?lab=${encodeURIComponent(lab || "")}&days=${ADM.days}&site=${encodeURIComponent(ADM.site)}`);
}

function delta(cur, prev, invert) {
  if (!prev) return cur ? `<span class="delta new">новое</span>` : `<span class="delta">—</span>`;
  const d = ((cur - prev) / prev) * 100;
  if (Math.abs(d) < 0.5) return `<span class="delta">без изменений</span>`;
  const up = d > 0;
  return `<span class="delta ${up !== !!invert ? "up" : "down"}">${up ? "▲" : "▼"} ${Math.abs(d).toFixed(0)}%</span>`;
}

function renderAdmin(v, top) {
  const D = ADM.data;
  if (!D) { v.innerHTML = `<div class="panel">Считаю статистику…</div>`; guard(async () => { await loadAdmin(); render(); }); return; }
  const T = D.totals, P = D.prev, labName = S.sites?.lab?.name || "";
  top.innerHTML = `<div><div class="eyebrow">Лаборатория сайтов · админка</div><h1>Статистика сайтов</h1>
    <div class="sub">${ADM.scope === "all" ? "Все направления" : esc(labName)} · последние ${D.days} дн. · сравнение с предыдущими ${D.days} дн.</div></div>
    <div class="row">${D.has_demo ? `<span class="badge exp" title="Часть цифр — демо-данные">есть демо-данные</span>` : ""}
      <button class="btn sm" id="admReload">Обновить</button></div>`;
  const sites = D.sites;
  v.innerHTML = `
  <div class="adm-filters">
    <div class="seg small" id="admScope"><button data-v="lab" class="${ADM.scope === "lab" ? "on" : ""}">Это направление</button><button data-v="all" class="${ADM.scope === "all" ? "on" : ""}">Все направления</button></div>
    <select id="admSite"><option value="">Все сайты (${sites.length})</option>${(ADM.allSites || sites).map((s) => `<option value="${esc(s.id)}" ${ADM.site === s.id ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select>
    <div class="seg small" id="admDays">${[7, 30, 90, 365].map((d) => `<button data-v="${d}" class="${ADM.days === d ? "on" : ""}">${d === 365 ? "год" : d + " дн."}</button>`).join("")}</div>
  </div>
  <div class="kpis">
    ${kpi("Посетители", num(T.visitors), delta(T.visitors, P.visitors), `просмотров: ${num(T.views)}`)}
    ${kpi("Заявки", num(T.leads), delta(T.leads, P.leads), `интересов: ${num(T.interests)}`)}
    ${kpi("Продажи", num(T.orders), delta(T.orders, P.orders), `средний чек: ${money(T.avg_check)}`)}
    ${kpi("Выручка", money(T.revenue), delta(T.revenue, P.revenue), `прошлый период: ${money(P.revenue)}`)}
    ${kpi("Конверсия", pct(T.conversion), delta(T.conversion, P.conversion), "заявки и продажи / посетители")}
  </div>
  <div class="panel"><div class="row"><h2>По дням</h2><span class="spacer"></span>
      <div class="seg small" id="admMetric">${METRICS.map(([k, t]) => `<button data-v="${k}" class="${ADM.metric === k ? "on" : ""}">${t}</button>`).join("")}</div></div>
    <div class="chart" id="admChart">${dayChart(D.series, ADM.metric)}</div>
    <details class="meta"><summary>Таблица по дням</summary><div class="tscroll"><table><tr><th>День</th>${METRICS.map(([, t]) => `<th class="num">${t}</th>`).join("")}</tr>
      ${D.series.slice().reverse().map((d) => `<tr><td>${dayRu(d.date)}</td>${METRICS.map(([k]) => `<td class="num">${fmtM(k, d[k])}</td>`).join("")}</tr>`).join("")}</table></div></details>
  </div>
  <div class="grid2 adm-grid">
    ${hbarsPanel("Интересы посетителей", "На что кликают: услуги, товары, тарифы, кнопки (элементы с data-interest)", D.interests, num)}
    ${hbarsPanel("Откуда приходят", "Уникальные посетители по источнику: utm_source или сайт-источник", D.sources, num)}
    ${hbarsPanel("Что покупают", "Выручка по товарам и услугам", D.products, money)}
    ${hbarsPanel("Популярные страницы", "Просмотры страниц", D.pages, num)}
  </div>
  <div class="panel"><div class="row"><h2>Сайты</h2><span class="spacer"></span>
      <button class="btn sm" id="admDemo" ${sites.length ? "" : "disabled"}>Заполнить демо-данными</button>
      ${D.has_demo ? `<button class="btn sm ghost danger" id="admClear">Убрать демо-данные</button>` : ""}</div>
    ${sites.length ? `<div class="tscroll"><table class="adm-table"><tr><th>Сайт</th>${ADM.scope === "all" ? "<th>Направление</th>" : ""}<th class="num">Посетители</th><th class="num">Заявки</th><th class="num">Продажи</th><th class="num">Выручка</th><th class="num">Конверсия</th><th>Счётчик</th><th></th></tr>
      ${sites.map((s) => `<tr data-sid="${esc(s.id)}"><td><a href="#" class="adm-open"><b>${esc(s.name)}</b></a><div class="meta">этап: ${esc(s.stage)}${s.demo ? " · демо" : ""}</div></td>
        ${ADM.scope === "all" ? `<td>${esc(s.lab)}</td>` : ""}
        <td class="num">${num(s.visitors)}</td><td class="num">${num(s.leads)}</td><td class="num">${num(s.orders)}</td><td class="num">${money(s.revenue)}</td><td class="num">${pct(s.conversion)}</td>
        <td>${s.connected ? `<span class="badge ok">подключён</span>` : `<span class="badge">нет</span>`}<div class="meta">${s.last ? "последнее: " + new Date(s.last * 1000).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "событий нет"}</div></td>
        <td class="nowrap"><button class="btn sm adm-conn">Код счётчика</button> <button class="btn sm ghost danger adm-del" title="Удалить сайт">Удалить</button></td></tr>`).join("")}</table></div>`
      : `<p class="hint">В ${ADM.scope === "all" ? "студии" : "этом направлении"} пока нет сайтов.</p>`}
    <p class="meta">Счётчик встраивается в сайт при сборке (файл STATS.md в пакете промптов) или вручную — кнопкой «Код счётчика». Продажи приходят с сервера сайта после подтверждённой оплаты; офлайн-продажи можно внести ниже.
      Чтобы сайты могли отправлять события, студия должна быть доступна по домену из ALLOWED_HOSTS (см. SERVER.md).</p>
  </div>
  <div class="grid2 adm-grid">
    <div class="panel"><h2>Последние заявки и продажи</h2>
      ${D.recent.length ? `<ul class="feed">${D.recent.map((e) => `<li><span class="badge ${e.type === "order" ? "ok" : ""}">${e.type === "order" ? "продажа" : "заявка"}</span>
        <div><b>${esc(e.site)}</b>${e.label ? ` · ${esc(e.label)}` : ""}<div class="meta">${new Date(e.ts * 1000).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })} · ${esc(e.src || "")}${e.manual ? " · вручную" : ""}${e.demo ? " · демо" : ""}</div></div>
        ${e.type === "order" ? `<b class="nowrap">${money(e.amount)}</b>` : ""}</li>`).join("")}</ul>` : `<p class="hint">Пока ничего.</p>`}</div>
    <div class="panel"><h2>Внести вручную</h2><p class="hint">Продажа или заявка, которая прошла мимо сайта: по телефону, в мессенджере, в офисе.</p>
      <div class="grid2">
        <div class="field"><label>Сайт</label><select id="mSite">${sites.map((s) => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join("")}</select></div>
        <div class="field"><label>Что</label><select id="mType"><option value="order">Продажа</option><option value="lead">Заявка</option></select></div>
        <div class="field"><label>Сумма, ₽</label><input type="number" id="mAmount" min="0" step="1" placeholder="4900"></div>
        <div class="field"><label>Дата</label><input type="date" id="mDate" value="${new Date().toISOString().slice(0, 10)}"></div>
        <div class="field"><label>Товар / услуга</label><input type="text" id="mLabel" placeholder="Имплантация"></div>
        <div class="field"><label>Источник</label><input type="text" id="mSrc" placeholder="телефон, Авито, сарафан"></div>
      </div>
      <button class="btn primary" id="mAdd" ${sites.length ? "" : "disabled"}>Добавить</button></div>
  </div>`;
  bindAdmin(v);
}

const kpi = (l, val, d, sub) => `<div class="kpi"><div class="l">${l}</div><div class="big">${val}</div><div class="kpi-f">${d}<span class="meta">${sub}</span></div></div>`;

function hbarsPanel(title, hint, rows, f) {
  const max = Math.max(1, ...rows.map((r) => r.n));
  return `<div class="panel"><h2>${title}</h2><p class="hint">${hint}</p>
    ${rows.length ? `<div class="hbars">${rows.map((r) => `<div class="hb" title="${esc(r.name)}: ${esc(f(r.n))}"><span class="hb-n">${esc(r.name)}</span>
      <span class="hb-t"><i style="width:${Math.max(1.5, (r.n / max) * 100).toFixed(1)}%"></i></span><b>${f(r.n)}</b></div>`).join("")}</div>`
      : `<p class="meta">Данных за период нет.</p>`}</div>`;
}

// столбики по дням: одна метрика, одна ось; подсказка при наведении
function dayChart(series, m) {
  const W = 960, H = 240, L = 54, R = 8, Tp = 10, B = 26;
  const vals = series.map((d) => d[m] || 0);
  const raw = Math.max(1, ...vals);
  const pow = 10 ** Math.floor(Math.log10(raw)), step = [1, 2, 2.5, 5, 10].map((k) => k * pow).find((s) => raw / s <= 4) || pow * 10;
  const max = Math.ceil(raw / step) * step;
  const n = series.length, slot = (W - L - R) / n, bw = Math.max(1, slot - 2);
  const y = (v) => Tp + (H - Tp - B) * (1 - v / max);
  const grid = [];
  for (let g = 0; g <= max + 1e-9; g += step) grid.push(`<line x1="${L}" x2="${W - R}" y1="${y(g)}" y2="${y(g)}" class="gl"/><text x="${L - 8}" y="${y(g) + 4}" text-anchor="end" class="ax">${m === "revenue" ? num(g / 1000) + (g ? "k" : "") : num(g)}</text>`);
  const every = Math.ceil(n / 8);
  const bars = series.map((d, i) => {
    const x = L + i * slot + 1, v = d[m] || 0, top = y(v), h = H - B - top, r = Math.min(4, bw / 2, h);
    const path = v ? `M${x},${H - B} V${top + r} Q${x},${top} ${x + r},${top} H${x + bw - r} Q${x + bw},${top} ${x + bw},${top + r} V${H - B} Z` : "";
    return `<g class="bar" data-i="${i}">${path ? `<path d="${path}"/>` : ""}<rect class="hit" x="${L + i * slot}" y="${Tp}" width="${slot}" height="${H - Tp - B}"/>
      ${(i % every === 0 && n - 1 - i >= every / 2) || i === n - 1 ? `<text x="${x + bw / 2}" y="${H - 8}" text-anchor="middle" class="ax">${dayRu(d.date)}</text>` : ""}</g>`;
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(METRICS.find((x) => x[0] === m)[1])} по дням">${grid.join("")}<line x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}" class="base"/>${bars}</svg><div class="tip" hidden></div>`;
}

function bindChart(v) {
  const box = v.querySelector("#admChart"), tip = box.querySelector(".tip"), svg = box.querySelector("svg");
  box.querySelectorAll(".bar").forEach((g) => {
    g.onmouseenter = () => {
      const d = ADM.data.series[+g.dataset.i];
      box.querySelectorAll(".bar.on").forEach((x) => x.classList.remove("on")); g.classList.add("on");
      tip.innerHTML = `<b>${dayRu(d.date)}</b>${METRICS.map(([k, t]) => `<div class="${k === ADM.metric ? "cur" : ""}"><span>${t}</span><b>${fmtM(k, d[k])}</b></div>`).join("")}`;
      tip.hidden = false;
      const r = g.querySelector(".hit").getBoundingClientRect(), br = box.getBoundingClientRect();
      const left = r.left - br.left + r.width / 2;
      tip.style.left = Math.min(Math.max(left, 90), br.width - 90) + "px";
      tip.style.top = "6px";
    };
  });
  svg.onmouseleave = () => { tip.hidden = true; box.querySelectorAll(".bar.on").forEach((x) => x.classList.remove("on")); };
}

function bindAdmin(v) {
  const reload = () => guard(async () => { await loadAdmin(); render(); });
  $("#admReload").onclick = reload;
  bindChart(v);
  v.querySelectorAll("#admScope button").forEach((b) => (b.onclick = () => { ADM.scope = b.dataset.v; ADM.site = ""; ADM.allSites = null; reload(); }));
  v.querySelectorAll("#admDays button").forEach((b) => (b.onclick = () => { ADM.days = +b.dataset.v; reload(); }));
  v.querySelectorAll("#admMetric button").forEach((b) => (b.onclick = () => {
    ADM.metric = b.dataset.v;
    v.querySelectorAll("#admMetric button").forEach((x) => x.classList.toggle("on", x === b));
    $("#admChart").innerHTML = dayChart(ADM.data.series, ADM.metric); bindChart(v);
  }));
  $("#admSite").onchange = () => { if (!ADM.site) ADM.allSites = ADM.data.sites; ADM.site = $("#admSite").value; if (!ADM.site) ADM.allSites = null; reload(); };
  if ($("#admDemo")) $("#admDemo").onclick = () => guard(async () => {
    const one = ADM.site ? "этого сайта" : "всех сайтов в списке";
    if (!confirm(`Добавить демо-статистику за 30 дней для ${one}? Она помечается как демо и убирается одной кнопкой.`)) return;
    const r = await api(`/api/stats/demo?${ADM.scope === "all" ? "lab=__all__" : lq()}`, { body: { site: ADM.site } });
    toast(`Добавлено демо-событий: ${num(r.events)}`); reload();
  });
  if ($("#admClear")) $("#admClear").onclick = () => guard(async () => {
    if (!confirm("Убрать все демо-данные? Настоящая статистика останется.")) return;
    const r = await api(`/api/stats/cleardemo?${ADM.scope === "all" ? "lab=__all__" : lq()}`, { body: { site: ADM.site } });
    toast(`Убрано демо-событий: ${num(r.events)}`); reload();
  });
  v.querySelectorAll(".adm-table tr[data-sid]").forEach((tr) => {
    const sid = tr.dataset.sid, s = ADM.data.sites.find((x) => x.id === sid);
    tr.querySelector(".adm-open").onclick = (e) => { e.preventDefault(); guard(async () => { await loadSite(sid); S.page = "site"; S.siteTab = S.siteTab || "brief"; render(); }); };
    tr.querySelector(".adm-conn").onclick = () => guard(() => showCounter(sid, s.name));
    tr.querySelector(".adm-del").onclick = () => guard(async () => { if (await deleteSite(sid, s.name)) { ADM.site = ""; ADM.allSites = null; reload(); } });
  });
  $("#mAdd").onclick = () => guard(async () => {
    const type = $("#mType").value, amount = $("#mAmount").value;
    if (type === "order" && !(+amount > 0)) return toast("Укажи сумму продажи", true);
    await api(`/api/stats/${encodeURIComponent($("#mSite").value)}/add`, { body: { type, amount, date: $("#mDate").value, label: $("#mLabel").value, src: $("#mSrc").value } });
    toast(type === "order" ? "Продажа добавлена" : "Заявка добавлена"); reload();
  });
}

// код счётчика для сайта: скрипт, ключ сервера, пример для вебхука оплаты
async function showCounter(sid, name) {
  const I = await api(`/api/stats/${encodeURIComponent(sid)}/connect`, { body: {} });
  const o = document.createElement("div");
  o.className = "overlay";
  o.innerHTML = `<div class="dialog" role="dialog" aria-label="Счётчик сайта"><div class="dlg-head"><h2>Счётчик · ${esc(name)}</h2><button class="btn ghost" data-x>Закрыть</button></div>
    <p class="hint">Если пакет промптов уже написан, в нём появился файл STATS.md — при сборке Claude Code сам встроит счётчик. Для готового сайта вставь код вручную перед &lt;/body&gt; каждой страницы.
      Интересы — атрибут <code>data-interest="Название"</code> на кнопках и карточках; заявка — <code>studioStats("lead", {form: "Заявка"})</code> после отправки формы.</p>
    ${/example\.com/.test(I.url) ? `<p class="lib-info err">Студия пока без домена: в .env на сервере задай ALLOWED_HOSTS (см. SERVER.md) — иначе сайтам некуда отправлять события. Сейчас в коде заглушка ${esc(I.url)}.</p>` : ""}
    <h3>Код для сайта</h3><textarea class="code" readonly style="min-height:260px">${esc(I.snippet)}</textarea>
    <div class="row" style="margin:8px 0 14px"><button class="btn sm" data-copy="snippet">Копировать код</button></div>
    <h3>Продажи с сервера сайта</h3><p class="meta">Секретный ключ — только в .env сервера сайта (STUDIO_STATS_SECRET), никогда в браузерный код.</p>
    <div class="row" style="margin:6px 0"><input type="password" readonly value="${esc(I.secret)}" id="cSecret" style="max-width:360px"><button class="btn sm" id="cShow">Показать</button><button class="btn sm" data-copy="secret">Копировать</button></div>
    <textarea class="code" readonly style="min-height:150px">${esc(I.server)}</textarea></div>`;
  document.body.appendChild(o);
  const close = () => o.remove();
  o.onclick = (e) => { if (e.target === o) close(); };
  o.querySelector("[data-x]").onclick = close;
  o.querySelector("#cShow").onclick = () => { const i = o.querySelector("#cSecret"); i.type = i.type === "password" ? "text" : "password"; };
  o.querySelectorAll("[data-copy]").forEach((b) => (b.onclick = () => copy(I[b.dataset.copy])));
}

// удаление сайта — общее для админки и страницы сайта
async function deleteSite(sid, name) {
  if (!confirm(`Удалить сайт «${name}» навсегда?\n\nУдалятся бриф, ресёрч, концепции, фото, видео, промпты, все сборки и статистика. Отменить нельзя.`)) return false;
  await api(`/api/sites/${encodeURIComponent(sid)}/delete`, { body: {} });
  if (S.site?.id === sid) S.site = null;
  await loadSites(); toast(`Сайт «${name}» удалён`);
  return true;
}
