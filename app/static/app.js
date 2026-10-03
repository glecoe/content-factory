// Контент-завод · интерфейс. Без сборки и фреймворков.
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const S = { state: null, product: null, page: "welcome", tab: "item", selected: new Set(), jobs: {}, research: null };
const TAGS = ["свет", "темп", "хук", "модель", "рука", "кольцо не то", "музыка", "плашка", "скучно", "дорого выглядит", "тренд зашёл"];
const TYPE_NAMES = { A: "макро", B: "на руке", C: "ИИ-модель", D: "атмосфера" };

async function api(path, opts = {}) {
  const o = { method: opts.method || (opts.body !== undefined ? "POST" : "GET"), headers: {} };
  if (opts.raw) { o.body = opts.raw; o.method = "POST"; }
  else if (opts.body !== undefined) { o.body = JSON.stringify(opts.body); o.headers["Content-Type"] = "application/json"; }
  const r = await fetch(path, o);
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.error) throw new Error(j.error || `Ошибка ${r.status}`);
  return j;
}
function toast(msg, err = false) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast show" + (err ? " err" : "");
  clearTimeout(t._h); t._h = setTimeout(() => (t.className = "toast"), err ? 6000 : 2600);
}
const usd = (v) => "$" + Number(v || 0).toFixed(2);
const rub = (v) => Math.round(Number(v || 0) * (S.state?.settings.usd_rub || 84.41)).toLocaleString("ru-RU") + " ₽";
const fileUrl = (p, sub, f) => `/files/products/${p.id}/${sub}/${encodeURIComponent(f)}`;
const claudeOK = () => !!S.state?.brains?.claude?.logged_in;
const geminiOK = () => !!S.state?.brains?.gemini?.key;
const brainOK = () => claudeOK() || geminiOK();
const who = (role) => {
  const pref = S.state.settings.providers[role];
  if (pref === "claude" && claudeOK()) return "Claude";
  if (pref === "gemini" && geminiOK()) return "Gemini";
  return claudeOK() ? "Claude" : geminiOK() ? "Gemini" : "—";
};
async function copy(text) { try { await navigator.clipboard.writeText(text); toast("Скопировано"); } catch { toast("Не удалось скопировать", true); } }
async function guard(fn) { try { await fn(); } catch (e) { toast(e.message, true); } }

// ---------------------------------------------------------------- загрузка
async function loadState() { S.state = await api("/api/state"); renderRail(); }
async function loadProduct(id) { S.product = await api(`/api/products/${id}`); }
async function loadResearch() { S.research = await api("/api/research"); }
async function refresh() {
  await loadState();
  if (S.product) await loadProduct(S.product.id);
  if (S.page === "research") await loadResearch();
  render();
}

// ---------------------------------------------------------------- боковая панель
function renderRail() {
  const st = S.state.settings;
  const m = $("#mode");
  m.className = "mode" + (st.demo_mode ? "" : " live");
  m.innerHTML = (st.demo_mode
    ? `<b>Демо-режим</b><br>Клипы собираются из фото, бесплатно`
    : `<b>Боевой режим · fal.ai</b><br>Сегодня ${usd(S.state.costs.today)} из ${usd(st.daily_limit_usd)}`) +
    `<div class="brains"><span class="dot ${claudeOK() ? "on" : ""}"></span>Claude ${claudeOK() ? "по подписке" : "не подключён"}
     <br><span class="dot ${geminiOK() ? "on" : ""}"></span>Gemini ${geminiOK() ? "подключён" : "нет ключа"}</div>`;
  const list = $("#products");
  list.innerHTML = S.state.products.length ? "" : `<div class="empty-rail">Изделий пока нет</div>`;
  for (const p of S.state.products) {
    const b = document.createElement("button");
    b.className = S.page === "product" && S.product?.id === p.id ? "on" : "";
    b.innerHTML = `<div class="p-name">${esc(p.name || "Без названия")}</div><div class="p-meta">клипов: ${p.clips} · роликов: ${p.videos}</div>`;
    b.onclick = async () => { await loadProduct(p.id); S.page = "product"; S.tab = S.tab || "item"; S.selected.clear(); render(); };
    list.appendChild(b);
  }
  document.querySelectorAll(".railnav button").forEach((b) => b.classList.toggle("on", S.page === b.dataset.page));
}
document.querySelectorAll(".railnav button").forEach((b) => (b.onclick = async () => {
  S.page = b.dataset.page;
  if (S.page === "research") await guard(loadResearch);
  render();
}));
$("#newProduct").onclick = async () => {
  const p = await api("/api/products", { body: { name: "Новое кольцо" } });
  await loadState(); await loadProduct(p.id); S.page = "product"; S.tab = "item"; render();
};

// ---------------------------------------------------------------- роутинг
function render() {
  renderRail();
  const v = $("#view"), top = $("#top");
  if (S.page === "product" && S.product) return renderProduct(v, top);
  if (S.page === "research") return renderResearch(v, top);
  if (S.page === "taste") return renderTaste(v, top);
  if (S.page === "costs") return renderCosts(v, top);
  if (S.page === "settings") return renderSettings(v, top);
  return renderWelcome(v, top);
}

function renderWelcome(v, top) {
  top.innerHTML = "";
  const st = S.state.settings, tools = S.state.tools, cl = S.state.brains.claude;
  const ok = (b) => `<span class="tick ${b ? "on" : ""}">${b ? "✓" : "•"}</span>`;
  v.innerHTML = `<div class="welcome">
    <h1>Кольцо на входе — ролики на выходе</h1>
    <p class="meta">Цепочка завода: ресёрч трендов → изделие → сценарист → кадры с контролем качества → монтаж → тексты публикаций → твоя оценка → профиль вкуса.</p>
    <ul class="check">
      <li>${ok(tools.ffmpeg)} ${tools.ffmpeg ? "FFmpeg найден" : "<b>Установи FFmpeg</b>: <code>brew install ffmpeg</code>"}</li>
      <li>${ok(cl.logged_in)} ${cl.logged_in ? `Claude по подписке подключён (${esc(cl.method || "OAuth")}) — сценарист, ресёрчер, монтажёр, тексты`
        : cl.installed ? "Claude Code установлен, но вход не выполнен: открой Терминал и набери <code>claude</code>, войди своим аккаунтом"
        : "Claude Code не установлен: в Терминале <code>curl -fsSL https://claude.ai/install.sh | bash</code>, потом <code>claude</code> для входа"}</li>
      <li>${ok(st.gemini_key_set)} ${st.gemini_key_set ? "Gemini подключён — паспорт по фото, контроль кадров, разбор роликов" : "Вставь ключ Gemini в «Настройках» — он смотрит видео и проверяет кадры"}</li>
      <li>${ok(st.fal_key_set)} ${st.fal_key_set ? "fal.ai подключён" : "Ключ fal.ai можно добавить позже: пока работает демо-режим"}</li>
      <li>${ok(S.state.research.active)} ${S.state.research.active ? `Бриф трендов активен: ${esc(S.state.research.active)}` : "Запусти ресёрч на странице «Тренды недели» — сценарист будет опираться на свежие тренды"}</li>
      <li>${ok(S.state.music.length)} ${S.state.music.length ? `Музыка: ${S.state.music.length} трек(ов)` : "Положи 2–3 трека в папку <code>data/music</code>"}</li>
    </ul>
    <button class="btn primary" onclick="document.getElementById('newProduct').click()">Добавить изделие</button>
  </div>`;
}

// ---------------------------------------------------------------- изделие
const TABS = [["item", "Изделие"], ["script", "Сценарий"], ["clips", "Кадры"], ["reels", "Ролики"]];
function renderProduct(v, top) {
  const p = S.product, st = S.state.settings;
  top.innerHTML = `<div><h1>${esc(p.name || "Без названия")}</h1>
    <div class="sub">${esc([p.price, p.promo && "промокод " + p.promo].filter(Boolean).join(", ")) || "Заполни карточку изделия"}</div></div>
    <div class="autopilot"><div class="meta">Автопилот: паспорт → ${st.concepts_n} концепта → кадры → по 2 версии монтажа</div>
      <button class="btn dark" id="autoBtn" ${p.photos.length && brainOK() ? "" : "disabled title='Нужны фото и Claude или Gemini'"}>Сделать ролики</button></div>`;
  $("#autoBtn").onclick = autopilot;
  const done = { item: p.photos.length > 0, script: p.concepts.length > 0, clips: p.clips.length > 0, reels: p.videos.length > 0 };
  const steps = `<div class="steps">${TABS.map(([k, t], i) =>
    `<button data-tab="${k}" class="${S.tab === k ? "on" : ""} ${done[k] ? "done" : ""}"><span class="n">${i + 1}</span>${t}</button>`).join("")}</div>`;
  v.innerHTML = steps + `<div id="tab"></div>`;
  v.querySelectorAll(".steps button").forEach((b) => (b.onclick = () => { S.tab = b.dataset.tab; render(); }));
  ({ item: tabItem, script: tabScript, clips: tabClips, reels: tabReels })[S.tab]($("#tab"), p);
}

async function autopilot() {
  const p = S.product, st = S.state.settings;
  let msg = `Автопилот сделает ${st.concepts_n} концепта, сгенерирует кадры и смонтирует по 2 версии каждого.`;
  if (!st.demo_mode) {
    const perConcept = 3 * 5 * 0.112;
    msg += `\nПримерная стоимость кадров: ${usd(st.concepts_n * perConcept)}–${usd(st.concepts_n * perConcept * 2.2)} (зависит от моделей, которые выберет сценарист, и переделок). Лимит дня: ${usd(st.daily_limit_usd)}.`;
  }
  if (!confirm(msg + "\n\nЗапустить?")) return;
  await guard(async () => {
    await api(`/api/products/${p.id}/endcard`, { body: { png: await drawEndcard(p) } });
    startJob(await api(`/api/products/${p.id}/autopilot`, { body: { variants: 2 } }));
    S.tab = "reels"; render();
  });
}

function tabItem(t, p) {
  t.innerHTML = `
  <div class="panel"><h2>Карточка изделия</h2>
    <p class="hint">Описание можно вставить как на сайте. Для нейросетей важна внешность: металл, форма, камни.</p>
    <div class="grid2">
      <div class="field"><label>Название</label><input type="text" id="f_name" value="${esc(p.name)}"></div>
      <div class="field"><label>Бренд / рекламодатель (для плашки и маркировки)</label><input type="text" id="f_brand" value="${esc(p.brand)}"></div>
      <div class="field"><label>Цена</label><input type="text" id="f_price" value="${esc(p.price)}" placeholder="49 900 ₽"></div>
      <div class="field"><label>Промокод</label><input type="text" id="f_promo" value="${esc(p.promo)}" placeholder="LUNA5"></div>
    </div>
    <div class="field"><label>Ссылка на товар (к ней автоматически добавятся UTM-метки для каждого ролика)</label><input type="text" id="f_link" value="${esc(p.link)}"></div>
    <div class="field"><label>Описание</label><textarea id="f_desc">${esc(p.description_ru)}</textarea></div>
    <div class="field"><label>Паспорт для нейросетей (английский, одна фраза). Можно написать самому или нажать «Составить паспорт».</label>
      <textarea id="f_visual" style="min-height:64px">${esc(p.visual_en)}</textarea></div>
    ${p.passport?.risks?.length ? `<p class="meta">Что модели могут исказить: ${p.passport.risks.map(esc).join("; ")}</p>` : ""}
    <div class="row"><button class="btn primary" id="saveItem">Сохранить карточку</button>
      <button class="btn" id="passport" ${brainOK() ? "" : "disabled title='Нужен Claude или Gemini'"}>Составить паспорт по фото · ${who("passport")}</button></div>
  </div>
  <div class="panel"><h2>Съёмка сборщика</h2>
    <p class="hint">3–4 фото (анфас, профиль, 3/4 сверху, на пальце) и одно видео 10–15 секунд: кольцо на руке, кисть медленно поворачивается. Видео обрежется до 5 секунд — столько стоит обработка.</p>
    <div class="drop" id="drop">Перетащи сюда фото и видео или нажми, чтобы выбрать файлы
      <input type="file" id="fileIn" multiple accept="image/*,video/*,.heic,.HEIC" hidden></div>
    <div class="row" style="margin-top:10px"><span class="meta">или</span>
      <button class="btn" id="fromLib">Выбрать из библиотеки «По изделиям»</button></div>
    <div class="files" id="files"></div>
  </div>`;
  const files = $("#files");
  p.photos.forEach((ph, i) => files.insertAdjacentHTML("beforeend",
    `<div class="file"><img src="${fileUrl(p, "prepared", ph.file)}" alt=""><div class="f-foot"><span>фото ${i + 1}</span><button data-k="photo" data-f="${esc(ph.file)}">убрать</button></div></div>`));
  if (p.video) files.insertAdjacentHTML("beforeend",
    `<div class="file"><video src="${fileUrl(p, "prepared", p.video.file)}" muted loop playsinline autoplay></video><div class="f-foot"><span>видео ${p.video.duration}с</span><button data-k="video" data-f="${esc(p.video.file)}">убрать</button></div></div>`);
  files.querySelectorAll("button").forEach((b) => (b.onclick = async () => {
    S.product = await api(`/api/products/${p.id}/remove`, { body: { kind: b.dataset.k, file: b.dataset.f } }); render();
  }));
  $("#fromLib").onclick = () => guard(openLibrary);
  $("#saveItem").onclick = saveItem;
  $("#passport").onclick = async () => { await saveItem(true); startJob(await api(`/api/products/${p.id}/passport`, { body: {} })); };
  const drop = $("#drop"), inp = $("#fileIn");
  drop.onclick = () => inp.click();
  inp.onchange = () => upload([...inp.files]);
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); upload([...e.dataTransfer.files]); };
}
async function saveItem(silent) {
  const p = S.product;
  S.product = await api(`/api/products/${p.id}/update`, { body: {
    name: $("#f_name").value, brand: $("#f_brand").value, price: $("#f_price").value, promo: $("#f_promo").value,
    link: $("#f_link").value, description_ru: $("#f_desc").value, visual_en: $("#f_visual").value } });
  if (silent !== true) { toast("Карточка сохранена"); await loadState(); render(); }
}
async function upload(list) {
  const p = S.product;
  for (const f of list) {
    toast(`Загружаю ${f.name}…`);
    try { await api(`/api/products/${p.id}/upload?name=${encodeURIComponent(f.name)}`, { raw: f }); }
    catch (e) { toast(e.message, true); }
  }
  await loadProduct(p.id); await loadState(); render(); toast("Файлы готовы");
}

// ---------------------------------------------------------------- сценарий
function tabScript(t, p) {
  const st = S.state.settings;
  const trend = S.state.research.active;
  t.innerHTML = `
  <div class="panel"><h2>Сценарист</h2>
    <p class="hint">Каждый ролик — 3 разных кадра: два красивых кадра из фото и кольцо на руке, в конце плашка с ценой.
      Сценарист (${who("scenario")}) смотрит фото, учитывает профиль вкуса и ${trend ? `бриф трендов <b>${esc(trend)}</b>` : "общие правила (бриф трендов ещё не собран — загляни в «Тренды недели»)"}.
      ${brainOK() ? "" : "Ни Claude, ни Gemini не подключены — используй ручной режим или шаблон."}</p>
    <div class="row">
      <button class="btn primary" id="auto" ${brainOK() ? "" : "disabled"}>Написать ${st.concepts_n} концепта</button>
      <button class="btn" id="tmplBtn">Концепт по шаблону</button>
      <button class="btn" id="manualBtn">Ручной режим</button>
      <span class="spacer"></span>
      ${p.concepts.length ? `<button class="btn ghost" id="clearC">Удалить все концепты</button>` : ""}
    </div>
    <div id="manual" hidden style="margin-top:14px">
      <div class="field"><label>1. Скопируй бриф и отправь его в чат с Claude (приложи фото кольца)</label>
        <textarea class="code" id="briefTxt" readonly></textarea></div>
      <div class="row" style="margin-bottom:12px"><button class="btn" id="copyBrief">Скопировать бриф</button></div>
      <div class="field"><label>2. Вставь ответ целиком (JSON)</label><textarea class="code" id="manualTxt" placeholder='{"concepts": [...]}'></textarea></div>
      <button class="btn primary" id="loadManual">Загрузить концепты</button>
    </div>
  </div>
  <div id="concepts"></div>`;
  $("#auto").onclick = async () => guard(async () => startJob(await api(`/api/products/${p.id}/scenario`, { body: {} })));
  $("#tmplBtn").onclick = async () => guard(async () => { S.product = await api(`/api/products/${p.id}/template`, { body: {} }); toast("Концепт по шаблону добавлен"); render(); });
  $("#manualBtn").onclick = async () => {
    const m = $("#manual"); m.hidden = !m.hidden;
    if (!m.hidden) $("#briefTxt").value = (await api(`/api/products/${p.id}/brief`)).brief;
  };
  $("#copyBrief").onclick = () => copy($("#briefTxt").value);
  $("#loadManual").onclick = async () => guard(async () => {
    await api(`/api/products/${p.id}/manual`, { body: { text: $("#manualTxt").value } }); await loadProduct(p.id); toast("Концепты загружены"); render();
  });
  if ($("#clearC")) $("#clearC").onclick = async () => {
    if (!confirm("Удалить все концепты? Клипы и ролики останутся.")) return;
    S.product = await api(`/api/products/${p.id}/clearconcepts`, { body: {} }); S.selected.clear(); render();
  };
  renderConcepts($("#concepts"), p);
}

function sourceOptions(p, model, cur) {
  const need = S.state.models[model].needs;
  if (need === "video") return `<option value="video">видео сборщика</option>`;
  if (need === "photos") return `<option value="photos">все фото</option>`;
  return p.photos.map((_, i) => `<option value="photo:${i + 1}" ${cur === `photo:${i + 1}` ? "selected" : ""}>фото ${i + 1}</option>`).join("") || `<option value="photo:1">фото 1</option>`;
}
function shotCost(sh) {
  const m = S.state.models[sh.model] || {};
  const prep = ["kling_i2v", "seedance_i2v", "veo_i2v"].includes(sh.model) && S.state.settings.vertical_mode === "nb2" ? 0.08 : 0;
  return (m.usd_per_sec || 0) * sh.duration + (m.extra_usd || 0) + prep;
}

function renderConcepts(box, p) {
  if (!p.concepts.length) { box.innerHTML = ""; return; }
  box.innerHTML = p.concepts.map((c, ci) => `
    <div class="concept ${S.selected.has(c.id) ? "sel" : ""}" data-c="${ci}">
      <div class="row"><label class="row" style="gap:8px;cursor:pointer"><input type="checkbox" class="pick" ${S.selected.has(c.id) ? "checked" : ""}>
        <h3>${esc(c.title)}</h3></label>
        <span class="badge ${c.mode === "experiment" ? "exp" : ""}">${c.mode === "experiment" ? "эксперимент" : "по вкусу"}</span>
        ${c.trend ? `<span class="badge trend" title="Тренд из брифа">${esc(c.trend)}</span>` : ""}
        <span class="spacer"></span><span class="cost">${usd(c.shots.reduce((a, s) => a + shotCost(s), 0))}</span></div>
      <p class="idea">${esc(c.idea)}</p>
      <div class="meta">Хук: ${esc(c.hook)} · Музыка: ${esc(c.music_mood)}</div>
      ${c.shots.map((s, si) => `
        <div class="shot" data-s="${si}">
          <div class="t">${esc(s.type)}<small>${TYPE_NAMES[s.type] || ""}</small></div>
          <div>
            <div class="shot-controls">
              <select class="m">${Object.entries(S.state.models).map(([k, m]) => `<option value="${k}" ${k === s.model ? "selected" : ""}>${esc(m.title)} · $${m.usd_per_sec}/с</option>`).join("")}</select>
              <select class="src">${sourceOptions(p, s.model, s.source)}</select>
              <select class="d">${S.state.models[s.model].durations.map((d) => `<option ${d == s.duration ? "selected" : ""}>${d}</option>`).join("")}</select>
            </div>
            ${s.model === "keyframe_kling" ? `<label class="mini">Стоп-кадр для Nano Banana 2</label><textarea class="kf">${esc(s.keyframe_prompt || "")}</textarea><label class="mini">Движение для Kling</label>` : ""}
            <textarea class="pr">${esc(s.prompt)}</textarea>
          </div>
        </div>`).join("")}
    </div>`).join("") + `
    <div class="bar"><span id="selInfo"></span><span class="spacer"></span>
      <button class="btn" id="saveC">Сохранить правки</button>
      <button class="btn primary" id="gen">Сгенерировать кадры</button></div>`;

  box.querySelectorAll(".concept").forEach((el) => {
    const c = p.concepts[+el.dataset.c];
    el.querySelector(".pick").onchange = (e) => { e.target.checked ? S.selected.add(c.id) : S.selected.delete(c.id); el.classList.toggle("sel", e.target.checked); selInfo(); };
    el.querySelectorAll(".shot").forEach((sel) => {
      const s = c.shots[+sel.dataset.s];
      sel.querySelector(".m").onchange = (e) => { s.model = e.target.value; const d = S.state.models[s.model].durations; if (!d.includes(+s.duration)) s.duration = d[0];
        const need = S.state.models[s.model].needs;
        if (need === "video") s.source = "video"; else if (need === "photos") s.source = "photos"; else if (!String(s.source).startsWith("photo:")) s.source = "photo:1";
        renderConcepts(box, p); };
      sel.querySelector(".src").onchange = (e) => (s.source = e.target.value);
      sel.querySelector(".d").onchange = (e) => { s.duration = +e.target.value; renderConcepts(box, p); };
      sel.querySelector(".pr").oninput = (e) => (s.prompt = e.target.value);
      const kf = sel.querySelector(".kf"); if (kf) kf.oninput = (e) => (s.keyframe_prompt = e.target.value);
    });
  });
  $("#saveC").onclick = async () => { await api(`/api/products/${p.id}/concepts`, { body: { concepts: p.concepts } }); toast("Правки сохранены"); };
  $("#gen").onclick = generate;
  selInfo();
}
function selInfo() {
  const p = S.product, cs = p.concepts.filter((c) => S.selected.has(c.id));
  const cost = cs.reduce((a, c) => a + c.shots.reduce((b, s) => b + shotCost(s), 0), 0);
  const demo = S.state.settings.demo_mode;
  const el = $("#selInfo"); if (!el) return;
  el.innerHTML = cs.length ? `Выбрано: ${cs.length} · ${demo ? "демо, $0" : `<span class="cost">${usd(cost)} ≈ ${rub(cost)}</span> без учёта переделок`}` : "Отметь концепты галочкой";
  $("#gen").disabled = !cs.length;
}
async function generate() {
  const p = S.product;
  await api(`/api/products/${p.id}/concepts`, { body: { concepts: p.concepts } });
  const ids = [...S.selected];
  const est = await api(`/api/products/${p.id}/estimate`, { body: { concepts: ids } });
  if (!est.demo && !confirm(`Запустить генерацию в fal.ai?\nОценка: ${usd(est.usd)} (${rub(est.usd)}). Брак контролёр переделает до ${S.state.settings.auto_retry} раз — это может добавить расходов.`)) return;
  startJob(await api(`/api/products/${p.id}/generate`, { body: { concepts: ids, qa: true } }));
  S.tab = "clips"; render();
}

// ---------------------------------------------------------------- кадры
function tabClips(t, p) {
  if (!p.clips.length) { t.innerHTML = `<div class="panel"><h2>Кадров пока нет</h2><p class="hint">Отметь концепты на шаге «Сценарий» и нажми «Сгенерировать кадры» — или нажми «Сделать ролики» вверху.</p></div>`; return; }
  const byConcept = {};
  p.clips.forEach((c) => (byConcept[c.concept] ||= []).push(c));
  t.innerHTML = Object.entries(byConcept).map(([cid, list]) => {
    const concept = p.concepts.find((c) => c.id === cid);
    return `<div class="panel"><div class="row"><h2>${esc(concept?.title || cid)}</h2><span class="spacer"></span>
      <button class="btn primary sm" data-montage="${cid}">Смонтировать 2 версии</button></div>
      <p class="hint">Монтажёр берёт последний годный клип каждого кадра. Брак можно убрать вручную.</p>
      <div class="clips">${list.slice().reverse().map((c) => clipCard(p, c)).join("")}</div></div>`;
  }).join("");
  t.querySelectorAll("[data-qa]").forEach((b) => (b.onclick = async () => startJob(await api(`/api/products/${p.id}/qa`, { body: { clip: b.dataset.qa } }))));
  t.querySelectorAll("[data-rej]").forEach((b) => (b.onclick = async () => {
    S.product = await api(`/api/products/${p.id}/reject`, { body: { clip: b.dataset.rej, rejected: b.dataset.v === "1" } }); render(); }));
  t.querySelectorAll("[data-montage]").forEach((b) => (b.onclick = () => montage(b.dataset.montage)));
}
function clipCard(p, c) {
  const qa = p.qa?.[c.file];
  const q = qa ? `<span class="badge ${qa.verdict === "ok" ? "ok" : "bad"}">${qa.verdict === "ok" ? "годен" : "брак"} · ${qa.score ?? ""}</span>
     ${qa.issues_ru?.length ? `<ul class="issues">${qa.issues_ru.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>` : ""}` : "";
  const extras = [c.attempt > 1 ? `попытка ${c.attempt}` : "", c.keyframe ? `<a href="${fileUrl(p, "clips", c.keyframe)}" target="_blank">стоп-кадр</a>` : "",
    c.start_image ? `<a href="${fileUrl(p, "prepared", c.start_image)}" target="_blank">старт 9:16</a>` : ""].filter(Boolean).join(" · ");
  return `<div class="clip ${c.rejected ? "rej" : ""}">
    <video src="${fileUrl(p, "clips", c.file)}" poster="${fileUrl(p, "clips", c.thumb)}" controls muted playsinline preload="none"></video>
    <div class="c-body"><b>Кадр ${c.shot + 1} · ${esc(c.type)}</b> <span class="meta">${esc(TYPE_NAMES[c.type] || "")}</span><br>
      <span class="meta">${esc(S.state.models[c.model]?.title || c.model)} · ${c.duration}с · ${c.demo ? "демо" : usd(c.usd)}${c.width ? ` · ${c.width}×${c.height}` : ""}</span><br>
      ${extras ? `<span class="meta">${extras}</span><br>` : ""}${q}
      <div class="row" style="margin-top:6px">
        ${(geminiOK() || claudeOK()) && !c.demo ? `<button class="btn sm" data-qa="${esc(c.file)}">Проверить</button>` : ""}
        <button class="btn sm ${c.rejected ? "" : "danger"}" data-rej="${esc(c.file)}" data-v="${c.rejected ? 0 : 1}">${c.rejected ? "Вернуть" : "В брак"}</button></div></div></div>`;
}

// ---------------------------------------------------------------- ролики
// ---------------------------------------------------------------- финальный кадр
const PALETTES = {
  gold:  { name: "Золото",   accent: "#D8B878", ink: "#F6F1E7", dark: "#0E1311", paper: "#F2ECE2", paperInk: "#1E2522", paperAccent: "#A8803A" },
  silver:{ name: "Платина",  accent: "#D9DEE2", ink: "#F7F8F9", dark: "#0F1214", paper: "#ECEEF0", paperInk: "#1C2126", paperAccent: "#7D8A96" },
  rose:  { name: "Розовое золото", accent: "#E7B9A4", ink: "#FBF3EF", dark: "#1A1211", paper: "#F6ECE7", paperInk: "#2A1F1C", paperAccent: "#B57562" },
  emerald:{ name: "Изумруд", accent: "#E2C98E", ink: "#F3F1EA", dark: "#0B2620", paper: "#E9EFEA", paperInk: "#0F2C25", paperAccent: "#1F6B55" },
};
const TEMPLATES = { editorial: "Журнал", arch: "Арка", minimal: "Минимал" };
const SERIF = "'Cormorant Garamond', 'Times New Roman', serif", SANS = "Onest, 'Helvetica Neue', Arial, sans-serif";
const ecfg = (p) => ({ template: "editorial", palette: "gold", hero: null, tagline: "", cta: "Ссылка в описании", show_price: true, show_promo: true, ...(p.endcard || {}) });
const _imgCache = {};
function loadImg(src) {
  if (!_imgCache[src]) _imgCache[src] = new Promise((res) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => res(null); i.src = src; });
  return _imgCache[src];
}
async function fontsReady() {
  try { await Promise.all([`600 90px ${SERIF}`, `italic 500 40px ${SERIF}`, `500 40px ${SERIF}`, `300 40px ${SANS}`, `500 30px ${SANS}`].map((f) => document.fonts.load(f))); } catch {}
  await document.fonts.ready;
}
function cover(g, img, x, y, w, h, focusY = 0.45) {
  const s = Math.max(w / img.naturalWidth, h / img.naturalHeight);
  const iw = img.naturalWidth * s, ih = img.naturalHeight * s;
  g.drawImage(img, x + (w - iw) / 2, y + (h - ih) * focusY, iw, ih);
}
// текст с разрядкой (буквы в капсе с воздухом между ними)
function spaced(g, text, x, y, spacing) {
  const chars = [...text]; const widths = chars.map((c) => g.measureText(c).width);
  const total = widths.reduce((a, b) => a + b, 0) + spacing * (chars.length - 1);
  let cx = x - total / 2; const al = g.textAlign; g.textAlign = "left";
  chars.forEach((c, i) => { g.fillText(c, cx, y); cx += widths[i] + spacing; });
  g.textAlign = al; return total;
}
function lines(g, text, maxW, max = 2) {
  const words = String(text || "").split(/\s+/).filter(Boolean); const out = []; let line = "";
  for (const w of words) { const t = line ? line + " " + w : w; if (g.measureText(t).width > maxW && line) { out.push(line); line = w; } else line = t; }
  if (line) out.push(line);
  if (out.length > max) { out.length = max; out[max - 1] += "…"; }
  return out;
}
function fitFont(g, text, weightStyle, family, size, maxW, maxLines = 2, min = 54) {
  for (let s = size; s >= min; s -= 4) { g.font = `${weightStyle} ${s}px ${family}`; if (lines(g, text, maxW, 99).length <= maxLines) return s; }
  return min;
}
function divider(g, cx, y, w, color) {
  g.strokeStyle = color; g.lineWidth = 2; g.beginPath(); g.moveTo(cx - w / 2, y); g.lineTo(cx - 14, y); g.moveTo(cx + 14, y); g.lineTo(cx + w / 2, y); g.stroke();
  g.fillStyle = color; g.beginPath(); g.moveTo(cx, y - 8); g.lineTo(cx + 8, y); g.lineTo(cx, y + 8); g.lineTo(cx - 8, y); g.closePath(); g.fill();
}
function pill(g, text, cx, y, color, fill = null) {
  g.font = `500 34px ${SANS}`;
  const w = [...text].reduce((a, c) => a + g.measureText(c).width, 0) + 6 * (text.length - 1) + 96, h = 84;
  roundRect(g, cx - w / 2, y - h / 2, w, h, h / 2);
  if (fill) { g.fillStyle = fill; g.fill(); }
  g.strokeStyle = color; g.lineWidth = 2.5; g.stroke();
  g.fillStyle = color; g.textBaseline = "middle"; spaced(g, text, cx, y + 2, 6); g.textBaseline = "alphabetic";
}
function roundRect(g, x, y, w, h, r) { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); }
function vgrad(g, y0, y1, stops) { const gr = g.createLinearGradient(0, y0, 0, y1); stops.forEach(([o, c]) => gr.addColorStop(o, c)); return gr; }
const rgba = (hex, a) => { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`; };

async function drawEndcard(p, canvas) {
  const cv = canvas || $("#endcardCanvas"), g = cv.getContext("2d"), W = 1080, H = 1920;
  const c = ecfg(p), P = PALETTES[c.palette] || PALETTES.gold;
  await fontsReady();
  const src = c.hero ? fileUrl(p, "cards", c.hero) : p.photos.length ? fileUrl(p, "prepared", p.photos[0].file) : null;
  const img = src ? await loadImg(src) : null;
  const brand = (p.brand || "").toUpperCase(), name = p.name || "", price = c.show_price ? p.price : "", promo = c.show_promo && p.promo ? `ПРОМОКОД  ${p.promo}` : "";
  g.save(); g.clearRect(0, 0, W, H); g.textAlign = "center"; g.textBaseline = "alphabetic";

  if (c.template === "arch") {
    g.fillStyle = P.paper; g.fillRect(0, 0, W, H);
    const ax = 170, aw = W - 340, ay = 230, ah = 930, r = aw / 2;
    const arch = () => { g.beginPath(); g.moveTo(ax, ay + ah); g.lineTo(ax, ay + r); g.arc(ax + r, ay + r, r, Math.PI, 0); g.lineTo(ax + aw, ay + ah); g.closePath(); };
    g.save(); arch(); g.clip(); g.fillStyle = P.paperInk; g.fillRect(ax, ay, aw, ah); if (img) cover(g, img, ax, ay, aw, ah, 0.42); g.restore();
    g.save(); g.translate(0, 0); g.strokeStyle = P.paperAccent; g.lineWidth = 2;
    g.beginPath(); const o = 22; g.moveTo(ax - o, ay + ah + o); g.lineTo(ax - o, ay + r); g.arc(ax + r, ay + r, r + o, Math.PI, 0); g.lineTo(ax + aw + o, ay + ah + o); g.stroke(); g.restore();
    if (brand) { g.fillStyle = P.paperAccent; g.font = `500 28px ${SANS}`; spaced(g, brand, W / 2, 150, 12); }
    let y = 1300;
    g.fillStyle = P.paperInk; const fs = fitFont(g, name, "600", SERIF, 88, 860);
    lines(g, name, 860).forEach((l, i) => g.fillText(l, W / 2, y + i * fs * 1.02)); y += lines(g, name, 860).length * fs * 1.02;
    if (c.tagline) { g.fillStyle = P.paperAccent; g.font = `italic 500 44px ${SERIF}`; g.fillText(c.tagline, W / 2, y); y += 62; }
    divider(g, W / 2, y, 220, P.paperAccent); y += 92;
    if (price) { g.fillStyle = P.paperInk; g.font = `300 60px ${SANS}`; spaced(g, price, W / 2, y, 3); y += 92; }
    if (promo) { pill(g, promo, W / 2, y, P.paperAccent); y += 98; }
    if (c.cta) { g.fillStyle = rgba(P.paperInk, .6); g.font = `400 26px ${SANS}`; spaced(g, c.cta.toUpperCase(), W / 2, Math.min(Math.max(y, 1800), 1880), 6); }
  } else if (c.template === "minimal") {
    g.fillStyle = P.dark; g.fillRect(0, 0, W, H);
    if (img) cover(g, img, 0, 0, W, H, 0.4);
    g.fillStyle = vgrad(g, 0, H, [[0, rgba(P.dark, .55)], [0.25, rgba(P.dark, .05)], [0.6, rgba(P.dark, .15)], [1, rgba(P.dark, .9)]]); g.fillRect(0, 0, W, H);
    const vg = g.createRadialGradient(W / 2, H * .45, H * .25, W / 2, H * .5, H * .8); vg.addColorStop(0, "rgba(0,0,0,0)"); vg.addColorStop(1, "rgba(0,0,0,.45)"); g.fillStyle = vg; g.fillRect(0, 0, W, H);
    if (brand) { g.fillStyle = P.ink; g.font = `500 26px ${SANS}`; spaced(g, brand, W / 2, 130, 14); }
    let y = 1560;
    g.fillStyle = P.ink; g.font = `300 46px ${SANS}`;
    const ml = lines(g, name.toUpperCase(), 760, 2);
    y -= (ml.length - 1) * 64; ml.forEach((l, i) => spaced(g, l, W / 2, y + i * 64, 8)); y += ml.length * 64 + 20;
    if (price) { g.fillStyle = P.accent; g.font = `500 64px ${SERIF}`; g.fillText(price, W / 2, y + 20); y += 90; }
    const small = [promo && promo.replace("  ", " "), c.cta].filter(Boolean).join("   ·   ");
    if (small) { g.fillStyle = rgba(P.ink, .75); g.font = `400 26px ${SANS}`; spaced(g, small.toUpperCase(), W / 2, Math.max(y + 10, 1840), 4); }
  } else {  // editorial
    g.fillStyle = P.dark; g.fillRect(0, 0, W, H);
    if (img) cover(g, img, 0, 0, W, H, 0.35);
    g.fillStyle = vgrad(g, 0, 380, [[0, rgba(P.dark, .7)], [1, rgba(P.dark, 0)]]); g.fillRect(0, 0, W, 380);
    g.fillStyle = vgrad(g, H * 0.5, H, [[0, rgba(P.dark, 0)], [0.38, rgba(P.dark, .78)], [1, rgba(P.dark, .97)]]); g.fillRect(0, H * 0.5, W, H * 0.5);
    if (brand) { g.fillStyle = P.ink; g.font = `500 28px ${SANS}`; spaced(g, brand, W / 2, 140, 14); g.fillStyle = P.accent; g.fillRect(W / 2 - 30, 172, 60, 2); }
    g.fillStyle = P.ink; const fs = fitFont(g, name, "600", SERIF, 104, 900);
    const nl = lines(g, name, 900);
    let y = 1500 - (nl.length - 1) * fs * 0.98 - (c.tagline ? 60 : 0);
    if (c.tagline) { g.fillStyle = P.accent; g.font = `italic 500 48px ${SERIF}`; g.fillText(c.tagline, W / 2, y - fs * 0.85); }
    g.fillStyle = P.ink; g.font = `600 ${fs}px ${SERIF}`;
    nl.forEach((l, i) => g.fillText(l, W / 2, y + i * fs * 0.98)); y += (nl.length - 1) * fs * 0.98 + 70;
    divider(g, W / 2, y, 260, P.accent); y += 100;
    if (price) { g.fillStyle = P.ink; g.font = `300 64px ${SANS}`; spaced(g, price, W / 2, y, 3); y += 105; }
    if (promo) { pill(g, promo, W / 2, y, P.accent, rgba(P.dark, .35)); y += 90; }
    if (c.cta) { g.fillStyle = rgba(P.ink, .7); g.font = `400 26px ${SANS}`; spaced(g, c.cta.toUpperCase(), W / 2, Math.max(y + 10, 1860), 6); }
  }
  g.restore();
  return cv.toDataURL("image/png");
}

async function saveEndcardCfg(p, patch) {
  p.endcard = { ...ecfg(p), ...patch };
  await api(`/api/products/${p.id}/endcardcfg`, { body: patch });
  await drawEndcard(p, $("#prev"));
}

function endcardPanel(p) {
  const c = ecfg(p), heroes = p.heroes || [];
  const styles = S.state.hero_styles || {};
  const demo = S.state.settings.demo_mode;
  return `<div class="panel endcard-panel"><div class="ec-grid">
    <canvas class="endcard-prev" id="prev" width="1080" height="1920"></canvas>
    <div>
      <h2>Финальный кадр</h2>
      <p class="hint">Красивое фото кольца + надписи из карточки изделия. Держится 3 секунды в конце каждого ролика.</p>
      <div class="field"><label>Макет</label><div class="seg" id="ecTpl">${Object.entries(TEMPLATES).map(([k, n]) => `<button data-v="${k}" class="${c.template === k ? "on" : ""}">${n}</button>`).join("")}</div></div>
      <div class="field"><label>Цвет надписей</label><div class="seg" id="ecPal">${Object.entries(PALETTES).map(([k, v]) => `<button data-v="${k}" class="${c.palette === k ? "on" : ""}"><i style="background:${v.accent}"></i>${v.name}</button>`).join("")}</div></div>
      <div class="grid2">
        <div class="field"><label>Слоган (необязательно)</label><input type="text" id="ecTag" value="${esc(c.tagline)}" placeholder="Свет, который остаётся"></div>
        <div class="field"><label>Призыв внизу</label><input type="text" id="ecCta" value="${esc(c.cta)}"></div>
      </div>
      ${(p.taglines || []).length ? `<div class="chips light">${p.taglines.map((t) => `<button class="chip" data-tl="${esc(t)}">${esc(t)}</button>`).join("")}</div>` : ""}
      <div class="row" style="margin:4px 0 14px">
        <label class="row" style="gap:6px"><input type="checkbox" id="ecPrice" ${c.show_price ? "checked" : ""}> цена</label>
        <label class="row" style="gap:6px"><input type="checkbox" id="ecPromo" ${c.show_promo ? "checked" : ""}> промокод</label>
        <span class="spacer"></span>
        <button class="btn sm" id="ecTagAI" ${brainOK() ? "" : "disabled"}>Придумать слоганы · ${who("publish")}</button>
      </div>
      <div class="field"><label>Фото</label>
        <div class="heroes">
          <button class="hero ${!c.hero ? "on" : ""}" data-h=""><img src="${p.photos[0] ? fileUrl(p, "prepared", p.photos[0].file) : ""}" alt=""><span>фото изделия</span></button>
          ${heroes.map((h) => `<button class="hero ${c.hero === h ? "on" : ""}" data-h="${esc(h)}"><img src="${fileUrl(p, "cards", h)}" alt=""></button>`).join("")}
        </div></div>
      <div class="row">
        <div class="seg small" id="ecStyles">${Object.entries(styles).map(([k, n], i) => `<button data-v="${k}" class="${i < 2 ? "on" : ""}">${esc(n)}</button>`).join("")}</div>
      </div>
      <div class="row" style="margin-top:10px">
        <button class="btn primary" id="ecHero" ${p.photos.length ? "" : "disabled"}>Снять красивое фото${demo ? " (демо)" : ` · ~$${(0.12 * 2).toFixed(2)}`}</button>
        <button class="btn" id="ecUp">Загрузить своё фото</button><input type="file" id="ecFile" accept="image/*,.heic" hidden>
      </div>
      <p class="meta" style="margin-top:8px">Nano Banana 2 ставит твоё кольцо в выбранную сцену и оставляет сверху и снизу место под надписи. Отметь 1–4 сцены — на каждую по одному фото.</p>
    </div></div></div>`;
}

function bindEndcardPanel(p) {
  drawEndcard(p, $("#prev"));
  const seg = (id, key) => $(id).querySelectorAll("button").forEach((b) => (b.onclick = async () => {
    $(id).querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b)); await saveEndcardCfg(p, { [key]: b.dataset.v }); }));
  seg("#ecTpl", "template"); seg("#ecPal", "palette");
  let tm; const deb = (patch) => { clearTimeout(tm); tm = setTimeout(() => saveEndcardCfg(p, patch), 350); };
  $("#ecTag").oninput = (e) => deb({ tagline: e.target.value });
  $("#ecCta").oninput = (e) => deb({ cta: e.target.value });
  $("#ecPrice").onchange = (e) => saveEndcardCfg(p, { show_price: e.target.checked });
  $("#ecPromo").onchange = (e) => saveEndcardCfg(p, { show_promo: e.target.checked });
  document.querySelectorAll("[data-tl]").forEach((b) => (b.onclick = () => { $("#ecTag").value = b.dataset.tl; saveEndcardCfg(p, { tagline: b.dataset.tl }); }));
  document.querySelectorAll(".hero").forEach((b) => (b.onclick = async () => {
    document.querySelectorAll(".hero").forEach((x) => x.classList.toggle("on", x === b)); await saveEndcardCfg(p, { hero: b.dataset.h || null }); }));
  $("#ecStyles").querySelectorAll("button").forEach((b) => (b.onclick = () => b.classList.toggle("on")));
  $("#ecHero").onclick = () => guard(async () => {
    const styles = [...$("#ecStyles").querySelectorAll("button.on")].map((b) => b.dataset.v);
    if (!styles.length) return toast("Отметь хотя бы одну сцену", true);
    if (!S.state.settings.demo_mode && !confirm(`Снять ${styles.length} фото в Nano Banana 2? Примерно $${(0.12 * styles.length).toFixed(2)}.`)) return;
    startJob(await api(`/api/products/${p.id}/hero`, { body: { styles } }));
  });
  $("#ecTagAI").onclick = () => guard(async () => startJob(await api(`/api/products/${p.id}/tagline`, { body: {} })));
  $("#ecUp").onclick = () => $("#ecFile").click();
  $("#ecFile").onchange = () => guard(async () => {
    const f = $("#ecFile").files[0]; if (!f) return; toast("Загружаю фото…");
    S.product = await api(`/api/products/${p.id}/heroupload?name=${encodeURIComponent(f.name)}`, { raw: f }); render();
  });
}

async function montage(cid) {
  const p = S.product;
  await guard(async () => {
    await api(`/api/products/${p.id}/endcard`, { body: { png: await drawEndcard(p) } });
    startJob(await api(`/api/products/${p.id}/montage`, { body: { concept: cid, variants: 2, ai: true } }));
    S.tab = "reels"; render();
  });
}

function tabReels(t, p) {
  const withClips = [...new Set(p.clips.filter((c) => !c.rejected).map((c) => c.concept))];
  t.innerHTML = `
  ${endcardPanel(p)}
  <div class="panel"><h2>Монтаж</h2>
    <p class="hint" style="margin:0">Монтажёр (${who("montage")}) сам решает порядок кадров, длину, переходы и музыку — две разные версии на концепт, в конце — финальный кадр выше.
    Музыка: ${S.state.music.length ? S.state.music.map(esc).join(", ") : "треков нет — положи mp3 в папку data/music"}.</p>
    <div class="row" style="margin-top:12px">${withClips.map((cid) => `<button class="btn" data-montage="${cid}">Смонтировать «${esc(p.concepts.find((c) => c.id === cid)?.title || cid)}»</button>`).join("") || `<span class="meta">Сначала сгенерируй кадры.</span>`}</div>
  </div>
  <div class="tray"><h2>Готовые ролики</h2>
    <p class="hint">Оцени каждый: «Беру» или «Не беру», причины и комментарий. Из оценок складывается профиль вкуса. Для тех, что берёшь, — тексты публикации со ссылками.</p>
    <div class="reels">${p.videos.slice().reverse().map((v) => reelCard(p, v)).join("") || `<p class="hint">Роликов пока нет.</p>`}</div></div>`;
  bindEndcardPanel(p);
  t.querySelectorAll("[data-montage]").forEach((b) => (b.onclick = () => montage(b.dataset.montage)));
  t.querySelectorAll(".reel").forEach((el) => {
    const v = p.videos.find((x) => x.file === el.dataset.f);
    const state = { like: v.like ?? null, tags: new Set(v.tags || []) };
    const sync = () => { el.querySelector(".yes").classList.toggle("on", state.like === true); el.querySelector(".no").classList.toggle("on", state.like === false);
      el.querySelectorAll(".chip").forEach((c) => c.classList.toggle("on", state.tags.has(c.dataset.t))); };
    el.querySelector(".yes").onclick = () => { state.like = true; sync(); };
    el.querySelector(".no").onclick = () => { state.like = false; sync(); };
    el.querySelectorAll(".chip").forEach((c) => (c.onclick = () => { state.tags.has(c.dataset.t) ? state.tags.delete(c.dataset.t) : state.tags.add(c.dataset.t); sync(); }));
    el.querySelector(".save").onclick = async () => {
      if (state.like === null) return toast("Сначала выбери «Беру» или «Не беру»", true);
      await api(`/api/products/${p.id}/rate`, { body: { video: v.file, like: state.like, tags: [...state.tags], comment: el.querySelector("textarea").value } });
      v.like = state.like; v.tags = [...state.tags]; toast("Оценка сохранена"); loadState();
    };
    const pb = el.querySelector(".packBtn");
    if (pb) pb.onclick = async () => guard(async () => startJob(await api(`/api/products/${p.id}/publish`, { body: { video: v.file } })));
    el.querySelectorAll("[data-copy]").forEach((b) => (b.onclick = () => copy(v.pack[b.dataset.copy])));
    sync();
  });
}
function reelCard(p, v) {
  const pk = v.pack;
  const pack = pk ? `<details class="pack"><summary>Тексты публикации · ${esc(pk.by || "")}</summary>
      ${[["vk", "VK Клипы"], ["telegram", "Telegram"], ["youtube_title", "YouTube · заголовок"], ["youtube", "YouTube · описание"]].map(([k, n]) =>
        `<div class="pk"><div class="row"><b>${n}</b><span class="spacer"></span><button class="btn sm ghost" data-copy="${k}">копировать</button></div><pre>${esc(pk[k])}</pre></div>`).join("")}
      <p class="meta">${esc(pk.note || "")}</p></details>` : "";
  return `<div class="reel" data-f="${esc(v.file)}">
    <video src="${fileUrl(p, "videos", v.file)}" poster="${fileUrl(p, "videos", v.thumb)}" controls playsinline preload="none"></video>
    <div class="r-body"><div class="r-title">${esc(v.concept_title)}</div>
      <div class="r-meta">${esc(v.variant)} · ${v.duration}с · ${esc(v.music || "без музыки")} · кадры ${usd(v.cost_usd)}</div>
      ${v.why ? `<div class="r-meta why">${esc(v.why)}</div>` : ""}
      ${v.trend ? `<div class="r-meta">тренд: ${esc(v.trend)}</div>` : ""}
      <div class="vote"><button class="yes">Беру</button><button class="no">Не беру</button></div>
      <div class="chips">${TAGS.map((t) => `<button class="chip" data-t="${t}">${t}</button>`).join("")}</div>
      <textarea placeholder="Что понравилось или что поменять">${esc(v.comment || "")}</textarea>
      <div class="row" style="margin-top:8px"><button class="btn sm save">Сохранить оценку</button>
      ${brainOK() ? `<button class="btn sm ghost packBtn" style="color:#E7CC86">${pk ? "Тексты заново" : "Тексты для публикации"}</button>` : ""}
      <a class="btn sm ghost" style="color:#A9BAB3" href="${fileUrl(p, "videos", v.file)}" download>Скачать</a></div>
      ${pack}</div></div>`;
}

// ---------------------------------------------------------------- тренды
function renderResearch(v, top) {
  const R = S.research;
  if (!R) { v.innerHTML = `<div class="panel">Загружаю…</div>`; loadResearch().then(render); return; }
  const c = R.config, B = R.brief?.brief;
  top.innerHTML = `<div><h1>Тренды недели</h1><div class="sub">Ресёрчер (${who("research")}) ищет в интернете, Gemini смотрит ролики-референсы, итог — бриф для сценариста.</div></div>
    <button class="btn dark" id="runR" ${brainOK() ? "" : "disabled"}>Запустить ресёрч</button>`;
  $("#runR").onclick = async () => guard(async () => startJob(await api("/api/research/run", { body: {} })));
  const list = (arr) => (arr || []).length ? `<ul>${arr.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : `<p class="meta">—</p>`;
  const briefHtml = B ? `
    <p class="lead">${esc(B.summary_ru)}</p>
    <div class="trends">${(B.top_trends || []).map((t) => `<div class="trend-card"><b>${esc(t.title)}</b><p>${esc(t.why || "")}</p><p class="use">Как применить: ${esc(t.how_to_use)}</p></div>`).join("")}</div>
    <div class="grid2">
      <div><h3>Хуки первых секунд</h3>${list(B.hooks)}</div>
      <div><h3>Идеи кадров</h3>${(B.shot_ideas || []).length ? `<ul>${B.shot_ideas.map((s) => `<li><b>${esc(s.type || "")}</b> ${esc(s.idea_en)}${s.why ? ` <span class="meta">— ${esc(s.why)}</span>` : ""}</li>`).join("")}</ul>` : "—"}</div>
      <div><h3>Делать</h3>${list(B.do)}</div><div><h3>Не делать</h3>${list(B.dont)}</div>
      <div><h3>Визуал</h3><p>Свет: ${esc(B.visual?.light || "—")}<br>Цвета: ${esc(B.visual?.colors || "—")}<br>Фоны: ${esc(B.visual?.backgrounds || "—")}</p></div>
      <div><h3>Музыка и эксперименты</h3>${list([...(B.music_moods || []), ...(B.experiments || []).map((e) => "Эксперимент: " + e)])}</div>
    </div>
    ${(B.sources || []).length ? `<h3>Источники</h3><ol class="src">${B.sources.map((s) => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title || s.url)}</a></li>`).join("")}</ol>` : ""}`
    : `<p class="hint">Брифа ещё нет. Проверь, что ищем (ниже), и нажми «Запустить ресёрч» — это займёт 3–10 минут.</p>`;
  v.innerHTML = `
  <div class="panel"><div class="row"><h2>Активный бриф ${R.active ? "· " + esc(R.active) : ""}</h2><span class="spacer"></span>
    ${R.briefs.length > 1 ? `<select id="briefSel">${R.briefs.map((b) => `<option value="${esc(b.id)}" ${b.id === R.active ? "selected" : ""}>${esc(b.id)}</option>`).join("")}</select>
    <button class="btn sm" id="actB">Сделать активным</button>` : ""}</div>${briefHtml}</div>

  <div class="panel"><h2>Что ищем</h2>
    <p class="hint">Это задание для ресёрчера. Конкурентов и ключевые слова лучше уточнить под своего производителя.</p>
    <div class="grid2">
      <div class="field"><label>Ниша</label><textarea id="r_niche">${esc(c.niche)}</textarea></div>
      <div class="field"><label>Аудитория</label><textarea id="r_aud">${esc(c.audience)}</textarea></div>
      <div class="field"><label>Рынки</label><input type="text" id="r_mk" value="${esc(c.markets)}"></div>
      <div class="field"><label>Площадки</label><input type="text" id="r_pl" value="${esc(c.platforms)}"></div>
      <div class="field"><label>Конкуренты (по одному в строке)</label><textarea id="r_comp">${esc(c.competitors)}</textarea></div>
      <div class="field"><label>Ключевые слова</label><textarea id="r_kw">${esc(c.keywords)}</textarea></div>
    </div>
    <div class="field"><label>Ссылки на ролики-референсы (YouTube/Shorts, по одной в строке) — Gemini посмотрит их целиком</label><textarea id="r_links" placeholder="https://www.youtube.com/shorts/...">${esc(c.reference_links)}</textarea></div>
    <details><summary class="meta">Сборщики Apify (по желанию)</summary>
      <p class="hint">Готовые «акторы» Apify собирают данные из TikTok Creative Center, Pinterest и т.п. Токен — в «Настройках». Формат: <code>[{"name":"TikTok хэштеги","actor":"автор/актор","input":{...},"max_items":50}]</code></p>
      <textarea class="code" id="r_apify" style="min-height:110px">${esc(JSON.stringify(c.apify_tasks || [], null, 1))}</textarea></details>
    <div class="row" style="margin-top:12px"><button class="btn primary" id="saveR">Сохранить задание</button></div>
  </div>

  <div class="panel"><h2>Ролики-референсы</h2>
    <p class="hint">Скачанные ролики из TikTok/Reels/VK, которые нравятся, — загрузи файлом. Gemini разберёт хук, кадры, свет, темп и что из этого взять нам.</p>
    <div class="drop" id="rdrop">Перетащи сюда видео-референсы или нажми, чтобы выбрать<input type="file" id="rIn" multiple accept="video/*" hidden></div>
    <div class="refs">${R.refs.map((f) => `<div class="ref-row"><span>${esc(f)}</span><span class="spacer"></span>
      <button class="btn sm" data-an="${esc(f)}" ${geminiOK() ? "" : "disabled"}>Разобрать</button><button class="btn sm ghost danger" data-del="${esc(f)}">удалить</button></div>`).join("")}</div>
    ${R.breakdowns.length ? `<h3>Разборы</h3><div class="bds">${R.breakdowns.map((b) => `<div class="bd"><b>${esc(b.title || b.ref)}</b>
      <p><span class="meta">Хук:</span> ${esc(b.hook || "")}</p><p><span class="meta">Почему работает:</span> ${esc(b.why_it_works || "")}</p>
      ${(b.ideas_for_us || []).length ? `<p><span class="meta">Взять нам:</span> ${b.ideas_for_us.map(esc).join("; ")}</p>` : ""}
      <p class="meta">${esc(String(b.ref || "").slice(0, 80))}</p></div>`).join("")}</div>` : ""}
  </div>`;
  if ($("#actB")) $("#actB").onclick = async () => guard(async () => { await api("/api/research/activate", { body: { id: $("#briefSel").value } }); await refresh(); toast("Бриф активен"); });
  $("#saveR").onclick = async () => guard(async () => {
    await api("/api/research/config", { body: { niche: $("#r_niche").value, audience: $("#r_aud").value, markets: $("#r_mk").value,
      platforms: $("#r_pl").value, competitors: $("#r_comp").value, keywords: $("#r_kw").value, reference_links: $("#r_links").value,
      apify_tasks: $("#r_apify").value } });
    await loadResearch(); toast("Задание сохранено"); render();
  });
  const drop = $("#rdrop"), inp = $("#rIn");
  const up = async (files) => { for (const f of files) { toast(`Загружаю ${f.name}…`); await guard(() => api(`/api/research/upload?name=${encodeURIComponent(f.name)}`, { raw: f })); } await loadResearch(); render(); };
  drop.onclick = () => inp.click(); inp.onchange = () => up([...inp.files]);
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); up([...e.dataTransfer.files]); };
  v.querySelectorAll("[data-an]").forEach((b) => (b.onclick = async () => guard(async () => startJob(await api("/api/research/analyze", { body: { ref: b.dataset.an, kind: "file" } })))));
  v.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => { if (!confirm("Удалить референс?")) return; await api("/api/research/deleteref", { body: { name: b.dataset.del } }); await loadResearch(); render(); }));
}

// ---------------------------------------------------------------- вкус / расходы / настройки
function renderTaste(v, top) {
  top.innerHTML = `<div><h1>Профиль вкуса</h1><div class="sub">Оценок: ${S.state.ratings}. Профиль получают сценарист, монтажёр и ресёрчер.</div></div>`;
  v.innerHTML = `<div class="panel"><div class="field"><label>Можно править руками — это прямая инструкция агентам</label>
    <textarea id="taste" style="min-height:320px">${esc(S.state.taste)}</textarea></div>
    <div class="row"><button class="btn primary" id="saveTaste">Сохранить</button>
    <button class="btn" id="updTaste">Обновить по оценкам · ${who("taste")}</button></div></div>`;
  $("#saveTaste").onclick = async () => { await api("/api/taste", { body: { text: $("#taste").value } }); toast("Профиль сохранён"); loadState(); };
  $("#updTaste").onclick = async () => guard(async () => startJob(await api("/api/taste/update", { body: {} })));
}

function renderCosts(v, top) {
  const c = S.state.costs;
  top.innerHTML = `<div><h1>Расходы</h1><div class="sub">Оценка по прайсам моделей. Точные списания — в личном кабинете fal.ai. Claude по подписке — $0 сверх подписки.</div></div>`;
  v.innerHTML = `<div class="stats">
      <div class="stat"><div class="l">Сегодня</div><div class="big">${usd(c.today)}</div><div class="meta">${rub(c.today)}</div></div>
      <div class="stat"><div class="l">Всего</div><div class="big">${usd(c.total)}</div><div class="meta">${rub(c.total)}</div></div>
      <div class="stat"><div class="l">Дневной лимит</div><div class="big">${usd(S.state.settings.daily_limit_usd)}</div><div class="meta">меняется в «Настройках»</div></div></div>
    <div class="panel"><h2>Цены моделей</h2><table><tr><th>Модель</th><th>За секунду</th><th>Клип 5 сек</th><th>Нужно</th></tr>
      ${Object.values(S.state.models).map((m) => { const k = m.usd_per_sec * 5 + (m.extra_usd || 0); return `<tr><td>${esc(m.title)}</td><td>$${m.usd_per_sec}${m.extra_usd ? ` + ${usd(m.extra_usd)} кадр` : ""}</td><td>${usd(k)} · ${rub(k)}</td><td>${{ photo: "фото", photos: "фото (референсы)", video: "видео" }[m.needs]}</td></tr>`; }).join("")}
      <tr><td>Вертикальный старт 9:16 (Nano Banana 2, один раз на фото)</td><td colspan="3">$0.08 за фото · ${rub(0.08)}</td></tr></table></div>
    <div class="panel"><h2>Последние списания</h2>${c.last.length ? `<table><tr><th>Когда</th><th>Что</th><th>Сумма</th></tr>
      ${c.last.map((r) => `<tr><td>${new Date(r.ts * 1000).toLocaleString("ru-RU")}</td><td>${esc(r.detail)}</td><td>${usd(r.usd)}</td></tr>`).join("")}</table>` : `<p class="hint">Пока ничего не потрачено.</p>`}</div>`;
}

function renderSettings(v, top) {
  const st = S.state.settings, tools = S.state.tools, cl = S.state.brains.claude;
  const opt = (val, cur, label) => `<option value="${val}" ${String(cur) === String(val) ? "selected" : ""}>${label}</option>`;
  top.innerHTML = `<div><h1>Настройки</h1><div class="sub">Ключи хранятся только в файле .env на этом компьютере или сервере.</div></div>`;
  v.innerHTML = `
  <div class="panel"><h2>Claude по подписке</h2>
    <p class="hint">Завод вызывает Claude Code в фоне (<code>claude -p</code>) — тратится лимит твоей подписки, отдельный API-ключ не нужен.
      На Mac: установи Claude Code и один раз войди. На сервере: на своём компьютере выполни <code>claude setup-token</code> и вставь токен сюда.</p>
    <table class="kv">
      <tr><td>Claude Code</td><td>${cl.installed ? `найден: ${esc(cl.version || "")} <span class="meta">${esc(cl.bin || "")}</span>` : `не найден — <code>curl -fsSL https://claude.ai/install.sh | bash</code>`}</td></tr>
      <tr><td>Вход</td><td>${cl.logged_in ? `выполнен (${esc(cl.method || "")}${cl.email ? ", " + esc(cl.email) : ""})` : "не выполнен — в Терминале набери <code>claude</code> и войди аккаунтом с подпиской"}</td></tr></table>
    <div class="grid2" style="margin-top:12px">
      <div class="field"><label>Модель Claude</label><select id="s_cm">${opt("opus", st.claude_model, "Opus — лучшее качество")}${opt("sonnet", st.claude_model, "Sonnet — быстрее, меньше тратит лимит")}${opt("haiku", st.claude_model, "Haiku — самый экономный")}</select></div>
      <div class="field"><label>Путь к claude (если не находится сам)</label><input type="text" id="s_cb" value="${esc(st.claude_bin || "")}" placeholder="~/.local/bin/claude"></div>
    </div>
    <div class="field"><label>Токен для сервера (CLAUDE_CODE_OAUTH_TOKEN) ${st.oauth_token_set ? "— сохранён; «-» чтобы стереть" : ""}</label><input type="password" autocomplete="new-password" id="s_tok" placeholder="${st.oauth_token_set ? "••••••••" : "необязательно на Mac"}"></div>
    <div class="row"><button class="btn" id="testC" ${cl.installed ? "" : "disabled"}>Проверить Claude</button><button class="btn ghost" id="reC">Обновить статус</button></div>
  </div>

  <div class="panel"><h2>Кто какую работу делает</h2>
    <p class="hint">Если выбранный «мозг» недоступен или упал по лимиту — задача автоматически уходит на второй.</p>
    <table class="kv">${Object.entries(st.roles).map(([r, label]) => `<tr><td>${esc(label)}</td><td><select data-role="${r}">${opt("claude", st.providers[r], "Claude (подписка)")}${opt("gemini", st.providers[r], "Gemini API")}</select></td></tr>`).join("")}
      <tr><td>Контролёр кадров, разбор видео</td><td class="meta">всегда Gemini (видит видео); без ключа — Claude по кадрам</td></tr></table>
  </div>

  <div class="panel"><h2>Ключи</h2>
    <div class="field"><label>fal.ai API key ${st.fal_key_set ? "— сохранён, вставь новый, чтобы заменить" : ""}</label><input type="password" autocomplete="new-password" id="s_fal" placeholder="${st.fal_key_set ? "••••••••" : "вставь ключ из fal.ai/dashboard/keys"}"></div>
    <div class="field"><label>Gemini API key ${st.gemini_key_set ? "— сохранён" : ""}</label><input type="password" autocomplete="new-password" id="s_gem" placeholder="${st.gemini_key_set ? "••••••••" : "вставь ключ из aistudio.google.com/apikey"}"></div>
    <div class="field"><label>Apify token (по желанию, для сборщиков трендов) ${st.apify_set ? "— сохранён" : ""}</label><input type="password" autocomplete="new-password" id="s_apify" placeholder="${st.apify_set ? "••••••••" : "console.apify.com → Settings → Integrations"}"></div>
    <div class="grid2"><div class="field"><label>Модель Gemini</label><input type="text" id="s_gm" value="${esc(st.gemini_model)}"></div>
    <div class="field"><label>Дневной лимит трат fal.ai, $</label><input type="number" id="s_lim" min="0" step="1" value="${st.daily_limit_usd}"></div></div>
    <label class="row" style="gap:8px;margin:6px 0 4px"><input type="checkbox" id="s_demo" ${st.demo_flag ? "checked" : ""}> Демо-режим: клипы собираются из фото через FFmpeg, fal.ai не вызывается</label>
  </div>

  <div class="panel"><h2>Конвейер</h2>
    <div class="grid2">
      <div class="field"><label>Концептов за один заход сценариста</label><input type="number" id="s_cn" min="1" max="8" value="${st.concepts_n}"></div>
      <div class="field"><label>Сколько раз переделывать забракованный кадр</label><select id="s_ar">${[0, 1, 2].map((n) => opt(n, st.auto_retry, n === 0 ? "не переделывать" : n + " раз")).join("")}</select></div>
      <div class="field"><label>Вертикаль для кадров из фото</label><select id="s_vm">${opt("nb2", st.vertical_mode, "Nano Banana 2 дорисовывает фон до 9:16 (+$0.08 за фото)")}${opt("blur", st.vertical_mode, "Фото на размытом фоне (бесплатно)")}${opt("off", st.vertical_mode, "Не менять (Kling отдаст квадрат)")}</select></div>
      <div class="field"><label>Если клип не вертикальный, при монтаже</label><select id="s_mf">${opt("crop", st.montage_fit, "обрезать края")}${opt("blur", st.montage_fit, "вписать на размытый фон")}</select></div>
    </div>
  </div>

  <div class="panel"><h2>Библиотека съёмки</h2>
    <p class="hint">Фото и видео «По изделиям» лежат в папке <code>library/</code> проекта: внутри по папке на изделие. Из неё выбираются файлы на вкладке «Изделие». Новые съёмки клади туда же.</p>
    <div class="field"><label>Другая папка библиотеки (необязательно; пусто — <code>library/</code> в проекте)</label><input type="text" id="s_lib" value="${esc(st.library_dir || "")}" placeholder="library"></div>
  </div>

  <div class="panel"><h2>Сервер</h2>
    <p class="hint">Пока работаешь на Mac — не трогай. На сервере: HOST 0.0.0.0 и обязательно пароль (без пароля наружу не откроется). Применяется после перезапуска.</p>
    <div class="grid2">
      <div class="field"><label>HOST</label><input type="text" id="s_host" value="${esc(st.host)}"></div>
      <div class="field"><label>PORT</label><input type="text" id="s_port" value="${esc(st.port)}"></div>
      <div class="field"><label>Логин</label><input type="text" id="s_user" value="${esc(st.auth_user)}"></div>
      <div class="field"><label>Пароль ${st.password_set ? "— задан; «-» чтобы снять" : ""}</label><input type="password" autocomplete="new-password" id="s_pw" placeholder="${st.password_set ? "••••••••" : "не задан"}"></div>
    </div>
  </div>
  <div class="row" style="margin-bottom:16px"><button class="btn primary" id="saveS">Сохранить настройки</button></div>

  <div class="panel"><h2>Проверка компьютера</h2><table>
    <tr><td>FFmpeg</td><td>${tools.ffmpeg ? "найден" : "не найден — <code>brew install ffmpeg</code>"}</td></tr>
    <tr><td>Кодек видео</td><td>${esc(tools.encoder || "—")}</td></tr>
    <tr><td>Конвертер фото iPhone (sips)</td><td>${tools.sips ? "есть" : "нет — HEIC лучше заранее перевести в JPG"}</td></tr></table></div>`;
  $("#testC").onclick = async () => guard(async () => startJob(await api("/api/claude/test", { body: {} })));
  $("#reC").onclick = async () => guard(async () => { await api("/api/claude/status", { body: {} }); await refresh(); toast("Статус обновлён"); });
  $("#saveS").onclick = async () => guard(async () => {
    const body = { FAL_KEY: $("#s_fal").value, GEMINI_API_KEY: $("#s_gem").value, APIFY_TOKEN: $("#s_apify").value,
      CLAUDE_CODE_OAUTH_TOKEN: $("#s_tok").value, AUTH_PASSWORD: $("#s_pw").value,
      GEMINI_MODEL: $("#s_gm").value, DAILY_LIMIT_USD: $("#s_lim").value, DEMO_MODE: $("#s_demo").checked ? "1" : "0",
      CLAUDE_MODEL: $("#s_cm").value, CLAUDE_BIN: $("#s_cb").value, CONCEPTS_N: $("#s_cn").value, AUTO_RETRY: $("#s_ar").value,
      VERTICAL_MODE: $("#s_vm").value, MONTAGE_FIT: $("#s_mf").value, LIBRARY_DIR: $("#s_lib").value, HOST: $("#s_host").value, PORT: $("#s_port").value, AUTH_USER: $("#s_user").value };
    v.querySelectorAll("[data-role]").forEach((s) => (body["PROVIDER_" + s.dataset.role.toUpperCase()] = s.value));
    await api("/api/settings", { body });
    toast("Настройки сохранены"); await refresh();
  });
}

// ---------------------------------------------------------------- библиотека «По изделиям»
const libThumb = (path) => `/library/thumb?f=${encodeURIComponent(path)}`;
async function openLibrary() {
  const lib = await api("/api/library");
  if (!lib.ok) {
    toast(`Папка библиотеки не найдена: ${lib.root}`, true);
    S.page = "settings"; render(); return;
  }
  const ov = document.createElement("div");
  ov.className = "overlay";
  ov.innerHTML = `<div class="dialog" role="dialog" aria-modal="true" aria-label="Библиотека «По изделиям»"></div>`;
  document.body.appendChild(ov);
  const dlg = $(".dialog", ov);
  const close = () => { ov.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  ov.onclick = (e) => { if (e.target === ov) close(); };
  let query = "";

  const grid = () => {
    const q = query.trim().toLowerCase();
    const items = lib.items.filter((it) => !q || it.id.toLowerCase().includes(q) || it.code.toLowerCase().includes(q));
    dlg.innerHTML = `<div class="dlg-head"><h2>Библиотека «По изделиям»</h2>
        <input type="search" id="libQ" placeholder="Номер папки или артикул" value="${esc(query)}">
        <button class="btn ghost" data-close>Закрыть</button></div>
      <div class="lib-grid">${items.map((it) => `<button class="lib-card" data-id="${esc(it.id)}">
          <img src="${libThumb(it.cover)}" alt="" loading="lazy">
          <div class="lib-cap"><b>№ ${esc(it.id)}</b> ${esc(it.code)}<div class="meta">фото: ${it.photos} · видео: ${it.videos}</div></div>
        </button>`).join("") || `<p class="meta">Ничего не нашлось</p>`}</div>`;
    $("[data-close]", dlg).onclick = close;
    const qi = $("#libQ", dlg);
    qi.oninput = () => { query = qi.value; grid(); const n = $("#libQ", dlg); n.focus(); n.setSelectionRange(n.value.length, n.value.length); };
    dlg.querySelectorAll(".lib-card").forEach((b) => (b.onclick = () => folder(lib.items.find((it) => it.id === b.dataset.id))));
  };

  const folder = (it) => {
    const p = S.product;
    const have = new Set([...p.photos.map((x) => x.source), p.video?.source].filter(Boolean));
    const sel = new Set(it.files.filter((f) => f.kind === "photo" && !have.has(f.path)).map((f) => f.path));
    const draw = () => {
      dlg.innerHTML = `<div class="dlg-head"><button class="btn ghost" data-back>← Все изделия</button>
          <h2>№ ${esc(it.id)} ${esc(it.code)}</h2><button class="btn ghost" data-close>Закрыть</button></div>
        <p class="hint">Отметь файлы для изделия. Видео можно взять одно — оно обрежется до 5 секунд, как при ручной загрузке.</p>
        <div class="lib-grid">${it.files.map((f) => {
          const added = have.has(f.path);
          return `<label class="lib-card ${sel.has(f.path) ? "on" : ""} ${added ? "added" : ""}" title="${esc(f.name)}">
            <input type="checkbox" data-f="${esc(f.path)}" ${sel.has(f.path) ? "checked" : ""} ${added ? "disabled" : ""}>
            <img src="${libThumb(f.path)}" alt="" loading="lazy">
            <div class="lib-cap">${f.kind === "video" ? "видео" : "фото"}${f.label ? " · " + esc(f.label) : ""}
              <div class="meta">${added ? "уже добавлено" : (f.size / 1048576).toFixed(1) + " МБ"}</div></div></label>`;
        }).join("")}</div>
        <div class="row dlg-foot"><button class="btn primary" data-add ${sel.size ? "" : "disabled"}>Добавить выбранные (${sel.size})</button></div>`;
      $("[data-close]", dlg).onclick = close;
      $("[data-back]", dlg).onclick = grid;
      dlg.querySelectorAll("input[data-f]").forEach((c) => (c.onchange = () => {
        const f = it.files.find((x) => x.path === c.dataset.f);
        if (c.checked) {
          if (f.kind === "video") it.files.forEach((x) => x.kind === "video" && sel.delete(x.path));
          sel.add(f.path);
        } else sel.delete(f.path);
        draw();
      }));
      $("[data-add]", dlg).onclick = () => addFromLibrary(it, [...sel], close);
    };
    draw();
  };
  grid();
}
async function addFromLibrary(it, files, close) {
  const p = S.product;
  close();
  let n = 0;
  for (const f of files) {
    toast(`Добавляю ${++n} из ${files.length}…`);
    try { await api(`/api/products/${p.id}/fromlibrary`, { body: { file: f } }); }
    catch (e) { toast(e.message, true); }
  }
  // новое изделие без названия получает артикул из библиотеки
  if (it.code && (!p.name || p.name === "Новое кольцо"))
    await guard(() => api(`/api/products/${p.id}/update`, { body: { name: it.code } }));
  await loadProduct(p.id); await loadState(); render(); toast("Файлы из библиотеки добавлены");
}

// ---------------------------------------------------------------- задачи
function startJob(j) { S.jobs[j.id] = j; drawJobs(); pollJobs(); }
let polling = false;
async function pollJobs() {
  if (polling) return; polling = true;
  while (Object.values(S.jobs).some((j) => j.status === "running")) {
    await new Promise((r) => setTimeout(r, 1500));
    for (const id of Object.keys(S.jobs)) {
      if (S.jobs[id].status !== "running") continue;
      try {
        const j = await api(`/api/jobs/${id}`); const was = S.jobs[id].status; S.jobs[id] = j;
        if (was === "running" && j.status !== "running") {
          toast(j.status === "done" ? `${j.title}: готово` : `${j.title}: ошибка — подробности в окне задачи`, j.status !== "done");
          await refresh();
        } else if (S.product && S.page === "product") {
          const before = S.product.clips.length + S.product.videos.length + S.product.concepts.length;
          await loadProduct(S.product.id);
          if (S.product.clips.length + S.product.videos.length + S.product.concepts.length !== before) render();
        }
      } catch (e) { S.jobs[id].status = "error"; }
    }
    drawJobs();
  }
  polling = false; drawJobs();
}
function drawJobs() {
  const box = $("#jobs");
  box.innerHTML = Object.values(S.jobs).slice(-3).map((j) => `<div class="job ${j.status}">
    <div class="j-head"><span>${esc(j.title)}</span><span>${j.status === "running" ? j.elapsed + " с" : j.status === "done" ? "готово" : "ошибка"} <button data-close="${j.id}">скрыть</button></span></div>
    <div class="j-prog"><i style="width:${Math.max(4, (j.progress || 0) * 100)}%"></i></div>
    <pre>${esc((j.log || []).slice(-10).join("\n"))}</pre></div>`).join("");
  box.querySelectorAll("[data-close]").forEach((b) => (b.onclick = () => { delete S.jobs[b.dataset.close]; drawJobs(); }));
  box.querySelectorAll("pre").forEach((p) => (p.scrollTop = p.scrollHeight));
}

// ---------------------------------------------------------------- старт
(async () => {
  try { await loadState(); for (const j of S.state.jobs) S.jobs[j.id] = j; if (S.state.jobs.length) pollJobs(); render(); }
  catch (e) { $("#view").innerHTML = `<div class="panel"><h2>Сервер не отвечает</h2><p class="hint">${esc(e.message)}. Запусти start.command ещё раз.</p></div>`; }
})();
