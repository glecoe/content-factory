// Лаборатория сайтов · анкета заказчика: отправить файлом или ссылкой, проверить ответы, перенести в бриф
const ANK_VIA = { "файл": "файлом", "ссылка": "по ссылке" };
const ankDate = (s) => (s ? new Date(s).toLocaleString("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" }) : "");
const ankIssues = (list) => (list || []).map(([lvl, m]) => `<div class="ank-msg ${lvl}">${lvl === "error" ? "⛔" : "⚠️"} ${esc(m)}</div>`).join("");

function anketaPanel() {
  return `<div class="panel ank" id="ankPanel"><div class="row"><div><h2>Анкета заказчика</h2>
      <p class="hint" style="margin:0">Отправьте заказчику анкету — он сам заполнит бриф: о компании, задаче, стиле, контактах, оплате. Ответы проверятся (обязательные поля, ИНН и ОГРН, почта, телефон, ссылки), и вы выберете, что перенести в бриф.</p></div></div>
    <div id="ankBody"><p class="meta">Загружаю…</p></div></div>`;
}

async function bindAnketa(s) {
  const box = $("#ankBody"); if (!box) return;
  let R;
  try { R = await api(`/api/sites/${s.id}/form`); } catch (e) { box.innerHTML = `<p class="meta">${esc(e.message)}</p>`; return; }
  if (!$("#ankBody") || S.site?.id !== s.id) return;       // пока грузилось, ушли со страницы
  const F = R.form || {};
  box.innerHTML = `
    <div class="ank-send">
      <div><b>Файлом</b><p class="meta">Скачайте анкету и отправьте в мессенджер или на почту. Заказчик откроет её в браузере, заполнит и пришлёт обратно файл с ответами.${F.downloaded ? ` Последний раз скачана: ${esc(ankDate(F.downloaded))}.` : ""}</p>
        <a class="btn sm primary" href="/api/sites/${s.id}/formfile" id="ankDl">Скачать анкету (.html)</a></div>
      <div><b>Ссылкой</b><p class="meta">Заказчик заполняет на странице студии — ответы приходят сюда сами. Нужна студия на сервере с доменом (SERVER.md).</p>
        <button class="btn sm" id="ankLink">${F.token ? "Показать ссылку" : "Получить ссылку"}</button><div id="ankLinkBox"></div></div>
      <div><b>Ответы</b><p class="meta">Пришёл файл «Ответы на анкету….json» — загрузите его сюда.</p>
        <button class="btn sm" id="ankUp">Загрузить ответы</button><input type="file" id="ankIn" accept=".json,application/json" hidden></div>
    </div>
    ${R.answers ? ankReview(R) : ""}`;
  $("#ankDl").onclick = () => setTimeout(() => toast("Анкета скачана — отправьте файл заказчику"), 400);
  $("#ankLink").onclick = () => guard(async () => ankShowLink(s, await api(`/api/sites/${s.id}/formlink`, { body: {} })));
  const inp = $("#ankIn");
  $("#ankUp").onclick = () => inp.click();
  inp.onchange = () => guard(async () => {
    const f = inp.files[0]; if (!f) return;
    await api(`/api/sites/${s.id}/formupload`, { raw: f });
    toast("Ответы загружены — проверьте и перенесите в бриф"); bindAnketa(s);
  });
  if (!R.answers) return;
  $("#ankApply").onclick = () => guard(async () => {
    const keys = [...box.querySelectorAll(".ank-pick:checked")].map((c) => c.value);
    if (!keys.length) return toast("Отметьте, что перенести", true);
    const bad = R.rows.filter((r) => keys.includes(r.key) && !r.ok).map((r) => r.label);
    if (bad.length && !confirm(`В полях с ошибками: ${bad.join(", ")}. Всё равно перенести?`)) return;
    S.site = await api(`/api/sites/${s.id}/formapply`, { body: { keys } });
    toast(`Перенесено в бриф: ${keys.length}`); render();
  });
  $("#ankClear").onclick = () => guard(async () => {
    if (!confirm("Убрать ответы анкеты из проверки? Файл останется в истории папки сайта.")) return;
    await api(`/api/sites/${s.id}/formclear`, { body: {} }); bindAnketa(s);
  });
  $("#ankAll").onchange = (e) => box.querySelectorAll(".ank-pick:not(:disabled)").forEach((c) => (c.checked = e.target.checked));
}

function ankShowLink(s, r) {
  const local = /localhost|127\.0\.0\.1/.test(r.url);
  $("#ankLinkBox").innerHTML = `<div class="ank-link"><input type="text" readonly value="${esc(r.url)}"><button class="btn sm" id="ankCopy">Копировать</button>
    <button class="btn sm ghost danger" id="ankRenew" title="Старая ссылка перестанет работать">Новая ссылка</button></div>
    ${local ? `<p class="meta ank-warn">Студия пока работает только на этом компьютере — заказчик по такой ссылке не попадёт. Отправьте анкету файлом или перенесите студию на сервер с доменом (ALLOWED_HOSTS).</p>` : ""}`;
  $("#ankCopy").onclick = () => copy(r.url);
  $("#ankRenew").onclick = () => guard(async () => {
    if (!confirm("Сделать новую ссылку? Старая перестанет открываться.")) return;
    ankShowLink(s, await api(`/api/sites/${s.id}/formrenew`, { body: {} })); toast("Новая ссылка готова");
  });
}

function ankReview(R) {
  const applied = R.form?.applied;
  return `<div class="ank-rev">
    <div class="row"><h3 style="margin:0">Ответы от ${esc(ankDate(R.received))}</h3>
      <span class="meta">${esc(ANK_VIA[R.via] || R.via || "")}${R.who ? ` · заполнил(а): ${esc(R.who)}` : ""}</span><span class="spacer"></span>
      ${R.errors ? `<span class="badge bad">ошибок: ${R.errors}</span>` : `<span class="badge ok">ошибок нет</span>`}
      ${R.warnings ? `<span class="badge exp">замечаний: ${R.warnings}</span>` : ""}
      ${applied ? `<span class="badge ok">перенесено ${esc(ankDate(applied))}</span>` : ""}</div>
    <p class="meta">Отмечено то, что можно перенести без вопросов. Поля с ошибками не отмечены — проверьте их и при необходимости уточните у заказчика. Перенос заменяет текущее значение в брифе.</p>
    <div class="tscroll"><table class="ank-table"><tr><th><input type="checkbox" id="ankAll" title="Отметить все"></th><th>Поле брифа</th><th>Из анкеты</th><th>Сейчас в брифе</th></tr>
      ${R.rows.map((r) => `<tr class="${r.ok ? "" : "bad"} ${r.same ? "same" : ""}">
        <td><input type="checkbox" class="ank-pick" value="${esc(r.key)}" ${r.ok && !r.same && !applied ? "checked" : ""} ${r.same ? "disabled" : ""}></td>
        <td><b>${esc(r.label)}</b>${r.same ? `<div class="meta">совпадает</div>` : ""}</td>
        <td><div class="ank-val">${esc(r.new)}</div>${ankIssues(r.issues)}</td>
        <td><div class="ank-val meta">${esc(r.cur) || "—"}</div></td></tr>`).join("")}</table></div>
    <div class="row" style="margin-top:12px"><button class="btn primary" id="ankApply">Перенести выбранное в бриф</button>
      <button class="btn ghost danger" id="ankClear">Убрать ответы</button></div>
    <details style="margin-top:12px"><summary class="meta">Все ответы анкеты, как их написал заказчик</summary>
      ${R.answers.map((sec) => `<h3>${esc(sec.section)}</h3><dl class="ank-qa">${sec.items.map((q) => `<dt>${esc(q.label)}</dt>
        <dd>${q.value ? esc(q.value) : `<span class="meta">—</span>`}${ankIssues(q.issues)}</dd>`).join("")}</dl>`).join("")}
    </details></div>`;
}

// главная лаборатории: файл ответов → свой сайт или новый
function bindAnketaImport() {
  const b = $("#ankImport"); if (!b) return;
  const inp = $("#ankImportIn");
  b.onclick = () => inp.click();
  inp.onchange = () => guard(async () => {
    const f = inp.files[0]; if (!f) return;
    const r = await api(`/api/sites/formimport?${lq()}`, { raw: f });
    await loadSites(); await loadSite(r.site); S.page = "site"; S.siteTab = "brief"; render();
    toast(r.created ? "Создан новый сайт по анкете — проверьте ответы и перенесите в бриф" : "Ответы загружены в сайт — проверьте и перенесите в бриф");
  });
}
