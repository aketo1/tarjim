"use strict";

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

async function api(path, body) {
  const opt = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  };
  const res = await fetch(path, opt);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "صار خطأ غير متوقع.");
  return data;
}

let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("on");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("on"), 2200);
}

const S = { live: { state: "idle" }, check: null, profiles: [], profile: null, guideStep: 0, task: null };

/* ------------------------------- navigation ------------------------------- */

function go(view) {
  $$(".view").forEach(v => v.classList.toggle("on", v.id === `view-${view}`));
  $$(".nav[data-view]").forEach(b => b.classList.toggle("on", b.dataset.view === view));
  $("main").scrollTo({ top: 0 });
  if (view === "game") loadProfile();
  if (view === "guide") renderGuide();
}
$$(".nav[data-view]").forEach(b => b.addEventListener("click", () => go(b.dataset.view)));
document.addEventListener("click", e => {
  const t = e.target.closest("[data-goto]");
  if (t) go(t.dataset.goto);
});
$("#quit").addEventListener("click", async () => {
  if (S.live.state !== "idle" && !confirm("الترجمة شغّالة. توقّفها وتقفل البرنامج؟")) return;
  await api("/api/quit", {}).catch(() => {});
  document.body.innerHTML = '<div style="display:grid;place-items:center;height:100vh;grid-column:1/-1;color:#93a3c4;font-size:18px">تم إغلاق ترجِم. تقدر تقفل النافذة.</div>';
  setTimeout(() => window.close(), 400);
});

/* ---------------------------------- home ---------------------------------- */

const STEP_TEXT = { models: "أحمّل القارئ والمترجم…", tv: "أشغّل تطبيق التلفزيون…", ps5: "أتصل بصورة الـPS5…" };

function renderLive() {
  const { state, step, error } = S.live;
  $("#stage").dataset.state = state;
  document.body.classList.toggle("running", state === "running");
  const title = { idle: "ابدأ الترجمة", starting: "لحظات…", running: "الترجمة شغّالة", stopping: "أوقّف…" }[state];
  $("#orb-title").textContent = title;
  $("#orb-step").textContent = state === "starting" ? (STEP_TEXT[step] || "")
    : state === "running" ? "اضغط الزر للإيقاف" : state === "stopping" ? "أمسح الشاشة" : "جاهز";
  $("#orb").setAttribute("aria-label", state === "running" ? "إيقاف الترجمة" : "تشغيل الترجمة");
  const alert = $("#alert");
  alert.hidden = !error;
  alert.textContent = error || "";
  $("#game").disabled = $("#game2").disabled = state !== "idle";

  const order = ["models", "tv", "ps5"];
  const at = state === "running" ? 3 : state === "starting" ? order.indexOf(step) : -1;
  $("#n-pc").classList.toggle("live", at >= 0);
  $("#n-tv").classList.toggle("live", state === "running");
  $("#f1").classList.toggle("on", state === "running");
  $("#f2").classList.toggle("on", state === "running" || at >= 1);
  $("#home-sub").textContent = state === "running"
    ? "العب عادي. أي سطر إنجليزي يطلع عربي مكانه."
    : "اختر اللعبة واضغط الزر. الباقي علينا.";
}

function renderStats(st) {
  const set = (id, v) => {
    const n = $(id);
    if (n.textContent !== String(v)) {
      n.textContent = v;
      n.classList.remove("bump");
      void n.offsetWidth;
      n.classList.add("bump");
    }
  };
  set("#s-ms", st.latency_ms != null ? `${(st.latency_ms / 1000).toFixed(2)}s` : "—");
  set("#s-lines", st.lines ?? 0);
  set("#s-fps", st.fps ?? "—");
}

function addLine(item, animate = true) {
  const en = $("#tv-en"), ar = $("#tv-ar");
  en.textContent = item.en;
  ar.textContent = item.ar;
  if (animate) {
    [en, ar].forEach(n => { n.classList.remove("in"); void n.offsetWidth; n.classList.add("in"); });
  }
  const feed = $("#feed");
  $(".empty", feed)?.remove();
  const li = el("li");
  li.append(el("div", "ar", item.ar), el("div", "en", item.en));
  feed.prepend(li);
  while (feed.children.length > 25) feed.lastChild.remove();
  $("#feed-count").textContent = `${feed.children.length} سطر`;
}

$("#orb").addEventListener("click", async () => {
  try {
    if (S.live.state === "idle") {
      S.live = { ...S.live, state: "starting", step: "models", error: "" };
      renderLive();
      await api("/api/start", { profile: $("#game").value });
    } else if (S.live.state === "running" || S.live.state === "starting") {
      await api("/api/stop", {});
    }
  } catch (e) {
    S.live = { state: "idle", error: e.message };
    renderLive();
  }
});

async function runCheck() {
  const list = $("#checklist");
  if (!S.check) {
    list.replaceChildren(...["اللابتوب", "التلفزيون", "الـPS5"].map(t => {
      const li = el("li", "wait");
      li.append(el("span", "mark", "•"), el("b", "", `أفحص ${t}…`));
      return li;
    }));
  }
  try {
    S.check = await api("/api/check");
  } catch (e) {
    return;
  }
  const c = S.check;
  list.replaceChildren(...c.items.map(it => {
    const li = el("li", it.ok ? "yes" : "no");
    const body = el("div");
    body.append(el("b", "", it.title));
    if (!it.ok) body.append(el("small", "", it.hint));
    li.append(el("span", "mark", it.ok ? "✓" : "!"), body);
    return li;
  }));
  const byId = Object.fromEntries(c.items.map(i => [i.id, i.ok]));
  $("#n-ps5").className = `node ${byId.ps5 && byId.link ? "ok" : "bad"}`;
  $("#n-ps5-t").textContent = c.ps5_name || (c.ps5_host ? c.ps5_host : "مو مربوط");
  $("#n-tv").className = `node ${byId.tv ? "ok" : "bad"} ${S.live.state === "running" ? "live" : ""}`;
  $("#n-tv-t").textContent = c.tv_model || c.tv_ip || "مو مجهّز";
  $("#n-pc").classList.add("ok");
  $("#n-pc-t").textContent = byId.power ? "على الشاحن" : "على البطارية!";
  $("#n-pc").classList.toggle("bad", !byId.power);
  if ($("#view-guide").classList.contains("on")) {
    // Fill in what we now know (TV address, linked account) unless the user is typing.
    const typing = ["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName);
    if (!typing && !S.task?.running) renderGuide(); else renderSteps();
  }
}
$("#recheck").addEventListener("click", () => { S.check = null; runCheck(); });

/* --------------------------------- settings --------------------------------- */

const FONTS = [
  { id: "harmattan", name: "حرمتان", css: "Harmattan" },
  { id: "harmattan-bold", name: "حرمتان عريض", css: "Harmattan Bold" },
  { id: "noto-naskh", name: "نسخ", css: "Noto Naskh" },
  { id: "noto-sans-arabic", name: "عصري", css: "Tarjim UI" },
];

function fillGames() {
  for (const sel of [$("#game"), $("#game2")]) {
    const cur = sel.value || S.selected;
    sel.replaceChildren(...S.profiles.map(p => {
      const o = el("option", "", p.title);
      o.value = p.name;
      return o;
    }));
    if (S.profiles.some(p => p.name === cur)) sel.value = cur;
  }
}
function selectGame(name) {
  S.selected = name;
  $("#game").value = $("#game2").value = name;
  if ($("#view-game").classList.contains("on")) loadProfile();
}
$("#game").addEventListener("change", e => selectGame(e.target.value));
$("#game2").addEventListener("change", e => selectGame(e.target.value));

let saveTimer, previewTimer;
function save(patch, quiet) {
  Object.assign(S.profile, patch);
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    try {
      const fresh = await api("/api/profile", { name: S.profile.name, ...patch });
      S.profile.font_size = fresh.font_size;
      if (!quiet) toast("تم الحفظ ✓");
      if (S.live.state === "running") toast("تم الحفظ ✓ — يتطبّق لما تعيد تشغيل الترجمة");
    } catch (e) { toast(e.message); }
  }, 350);
  refreshPreview();
}
function refreshPreview() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(() => {
    const p = S.profile;
    if (!p) return;
    const q = new URLSearchParams({ font: p.font, text: $("#preview-text").value, fill: p.fill ? "1" : "0", t: Date.now() });
    const size = p.font_auto ? "" : p.font_size;
    if (size) q.set("size", size);
    const img = new Image();
    $("#preview-load").classList.add("on");
    img.onload = () => { $("#preview").src = img.src; $("#preview-load").classList.remove("on"); };
    img.onerror = () => $("#preview-load").classList.remove("on");
    img.src = `/api/preview?${q}`;
  }, 180);
}

async function loadProfile() {
  const name = $("#game2").value || S.selected || "default";
  const p = S.profile = await api(`/api/profile?name=${encodeURIComponent(name)}`);
  $("#g-title").textContent = p.title;

  $("#fonts").replaceChildren(...FONTS.map(f => {
    const b = el("button", `font ${p.font === f.id ? "on" : ""}`);
    const sample = el("b", "", "مرحباً بك");
    sample.style.fontFamily = `"${f.css}"`;
    b.append(sample, el("small", "", f.name));
    b.addEventListener("click", () => {
      $$(".font").forEach(x => x.classList.remove("on"));
      b.classList.add("on");
      save({ font: f.id });
    });
    return b;
  }));

  const size = $("#size"), auto = $("#size-auto");
  auto.checked = p.font_auto;
  size.value = p.font_size || 40;
  size.disabled = p.font_auto;
  const sizeLabel = () => $("#size-val").textContent = auto.checked
    ? (p.font_size ? `تلقائي (${p.font_size})` : "تلقائي") : `${size.value}`;
  sizeLabel();
  auto.onchange = () => {
    size.disabled = auto.checked;
    S.profile.font_auto = auto.checked;
    save({ font_size: auto.checked ? null : Number(size.value) });
    sizeLabel();
  };
  size.oninput = () => { S.profile.font_auto = false; S.profile.font_size = Number(size.value); sizeLabel(); refreshPreview(); };
  size.onchange = () => save({ font_size: Number(size.value) });

  $("#fill").checked = p.fill;
  $("#fill").onchange = e => save({ fill: e.target.checked });
  $("#typewriter").checked = p.settle_ms >= 200;
  $("#typewriter").onchange = e => save({ settle_ms: e.target.checked ? 280 : 40 });
  const read = $("#read");
  read.value = p.read_scale;
  const readLabel = () => $("#read-val").textContent = Number(read.value) === 1 ? "عادي" : `×${Number(read.value).toFixed(1)}`;
  readLabel();
  read.oninput = readLabel;
  read.onchange = () => save({ read_scale: Number(read.value) });

  renderNames();
  refreshPreview();
}
$("#preview-text").addEventListener("input", refreshPreview);

function renderNames() {
  const box = $("#names");
  const rows = S.profile.glossary;
  const collect = () => save({ glossary: $$(".name", box).map(r => ({ en: $(".en", r).value, ar: $(".ar", r).value })) }, true);
  box.replaceChildren(...rows.map(row => nameRow(row, collect)));
  $("#add-name").onclick = () => {
    const r = nameRow({ en: "", ar: "" }, collect);
    box.prepend(r);
    $(".en", r).focus();
  };
}
function nameRow(row, collect) {
  const r = el("div", "name");
  const en = el("input", "en"), ar = el("input", "ar"), del = el("button", "del", "×");
  en.value = row.en; en.placeholder = "Name"; en.maxLength = 60;
  ar.value = row.ar; ar.placeholder = "الاسم بالعربي"; ar.maxLength = 60;
  del.title = "حذف";
  en.addEventListener("change", collect);
  ar.addEventListener("change", collect);
  del.addEventListener("click", () => {
    r.classList.add("out");
    setTimeout(() => { r.remove(); collect(); }, 240);
  });
  r.append(en, el("span", "arrow", "←"), ar, del);
  return r;
}

$("#new-game").addEventListener("click", () => { $("#new-title").value = ""; $("#dlg-new").showModal(); });
$("#dlg-new").addEventListener("close", async () => {
  const title = $("#new-title").value.trim();
  if ($("#dlg-new").returnValue !== "ok" || !title) return;
  try {
    const p = await api("/api/profile/new", { title });
    S.profiles.push({ name: p.name, title: p.title });
    fillGames();
    selectGame(p.name);
    toast("انضافت اللعبة ✓");
  } catch (e) { toast(e.message); }
});

/* ---------------------------------- guide ---------------------------------- */

const GUIDE = [
  { title: "كيف يشتغل", done: () => true },
  { title: "التلفزيون", done: c => !!c?.tv_ip },
  { title: "الـPS5", done: c => !!c?.ps5_user },
  { title: "ابدأ", done: () => false },
];

function renderSteps() {
  $("#steps").replaceChildren(...GUIDE.map((g, i) => {
    const b = el("button", `stepdot ${i === S.guideStep ? "on" : ""} ${g.done(S.check) && i !== S.guideStep ? "done" : ""}`);
    b.append(el("span", "n", g.done(S.check) && i !== 0 && i !== S.guideStep ? "✓" : String(i + 1)), el("b", "", g.title));
    b.addEventListener("click", () => { S.guideStep = i; renderGuide(); });
    return b;
  }));
  $("#g-pos").textContent = `${S.guideStep + 1} من ${GUIDE.length}`;
  $("#g-prev").disabled = S.guideStep === 0;
  $("#g-next").textContent = S.guideStep === GUIDE.length - 1 ? "للرئيسية ←" : "التالي ←";
}
$("#g-prev").addEventListener("click", () => { S.guideStep = Math.max(0, S.guideStep - 1); renderGuide(); });
$("#g-next").addEventListener("click", () => {
  if (S.guideStep === GUIDE.length - 1) return go("home");
  S.guideStep += 1;
  renderGuide();
});

function html(strings, ...values) {
  const t = document.createElement("template");
  t.innerHTML = String.raw(strings, ...values);
  const wrap = el("div");
  wrap.append(t.content);
  return wrap;
}
function logBox(id) {
  const box = el("div", "log");
  box.id = id;
  return box;
}
function pushLog(box, item) {
  if (!box) return;
  box.append(el("div", item.kind, item.msg));
  box.scrollTop = box.scrollHeight;
}

function renderGuide() {
  renderSteps();
  const body = $("#guide-body");
  const c = S.check || {};
  let view;

  if (S.guideStep === 0) {
    view = html`
      <h2>ترجِم في ثلاث خطوات</h2>
      <p class="lead">الـPS5 يبقى موصّل بالتلفزيون مثل ما هو، ولعبتك ويدك ما يتغيّر فيهم شي. ترجِم يشتغل جنبهم.</p>
      <div class="how">
        <div><span class="num">1</span><b>اللابتوب يشوف الصورة</b><p>ياخذ نسخة من صورة الـPS5 عن طريق الشبكة، بحساب ثاني عشان يدك تبقى شغّالة.</p></div>
        <div><span class="num">2</span><b>يقرأ ويترجم</b><p>يلقط السطر الإنجليزي أول ما يطلع، ويترجمه على اللابتوب نفسه بدون إنترنت.</p></div>
        <div><span class="num">3</span><b>التلفزيون يرسم العربي</b><p>تطبيق صغير على التلفزيون يحط العربي فوق مكان الإنجليزي. كل هذا في أقل من ربع ثانية.</p></div>
      </div>
      <div class="demo"><span class="d-en">We should leave before the storm.</span><span class="d-ar">يجب أن نغادر قبل العاصفة.</span></div>`;
  }

  if (S.guideStep === 1) {
    view = html`
      <h2>جهّز التلفزيون</h2>
      <p class="lead">مرة وحدة بس. نثبّت تطبيق صغير على التلفزيون يرسم الترجمة، وتقدر تشيله بأي وقت.</p>
      <ol class="todo">
        <li><div>فعّل خيارات المطوّر: <span class="path">الإعدادات ‹ النظام ‹ حول ‹ رقم الإصدار</span> واضغط عليه 7 مرات.</div></li>
        <li><div>فعّل التصحيح: <span class="path">الإعدادات ‹ النظام ‹ خيارات المطوّر ‹ تصحيح أخطاء USB</span></div></li>
        <li><div>شوف عنوان التلفزيون: <span class="path">الإعدادات ‹ الشبكة والإنترنت ‹ اسم شبكتك ‹ عنوان IP</span> واكتبه هنا:</div></li>
      </ol>
      <div class="action">
        <input class="text" id="tv-ip" placeholder="192.168.1.50" inputmode="decimal" maxlength="15">
        <button class="btn" id="tv-setup">جهّز التلفزيون</button>
        <button class="btn soft" id="tv-test">اعرض مربعات الاختبار</button>
      </div>
      <div class="note">أول مرة بتطلع رسالة على التلفزيون: «السماح بتصحيح الأخطاء؟» اختر <b>السماح دائماً</b> ثم موافق.</div>
      <div id="tv-result"></div>`;
    view.append(logBox("tv-log"));
    $("#tv-ip", view).value = c.tv_ip || "";
    if (c.tv_ip) $("#tv-result", view).append(el("div", "note good", `التلفزيون مجهّز${c.tv_model ? ` (${c.tv_model})` : ""}. تقدر تعيد التجهيز لو تغيّر عنوانه.`));
    $("#tv-setup", view).addEventListener("click", async e => {
      $("#tv-log").replaceChildren();
      $("#tv-result").replaceChildren();
      try { await api("/api/tv/setup", { ip: $("#tv-ip").value }); setBusy(true); }
      catch (err) { $("#tv-result").append(el("div", "note bad", err.message)); }
    });
    $("#tv-test", view).addEventListener("click", async () => {
      $("#tv-log").replaceChildren();
      const r = $("#tv-result");
      r.replaceChildren();
      try {
        await api("/api/tv/test", {});
        setBusy(true);
        const box = html`<div class="note">شوف التلفزيون الحين (25 ثانية): المفروض يطلع مربعين فوق اللعبة.</div>
          <div class="ab"><i class="a">A</i><i class="b">B</i></div>`;
        r.append(box);
      } catch (err) { r.append(el("div", "note bad", err.message)); }
    });
  }

  if (S.guideStep === 2) {
    view = html`
      <h2>اربط الـPS5</h2>
      <p class="lead">اللابتوب يحتاج حساب PSN <b>ثاني</b> عشان ياخذ نسخة الصورة. لو استخدمت نفس الحساب اللي تلعب فيه، يدك بتفصل.</p>
      <ol class="todo">
        <li><div>على الـPS5 أضف مستخدم بحساب PSN ثاني (مجاني)، ثم فعّل: <span class="path">الإعدادات ‹ النظام ‹ اللعب عن بُعد ‹ تمكين اللعب عن بُعد</span></div></li>
        <li><div>خلّ الـPS5 شغّال، ثم:
          <div class="action"><button class="btn" id="p-find">دوّر على الـPS5</button><span class="muted" id="p-found"></span></div></div></li>
        <li><div>سجّل دخول <b>بالحساب الثاني</b> في صفحة Sony. بعد الدخول تطلع صفحة فاضية فيها كلمة redirect: انسخ عنوانها من فوق والصقه هنا.
          <div class="action"><button class="btn soft" id="p-login">افتح صفحة الدخول</button>
          <input class="text wide" id="p-url" placeholder="https://remoteplay.dl.playstation.net/remoteplay/redirect?code=…">
          <button class="btn" id="p-url-go">تم</button></div></div></li>
        <li><div>على الـPS5 وأنت داخل بالحساب الثاني: <span class="path">الإعدادات ‹ النظام ‹ اللعب عن بُعد ‹ ربط جهاز</span> واكتب الرقم:
          <div class="action"><input class="text" id="p-pin" placeholder="8 أرقام" inputmode="numeric" maxlength="9">
          <button class="btn" id="p-pin-go">اربط</button></div></div></li>
      </ol>
      <div id="p-result"></div>`;
    const result = $("#p-result", view);
    const say = (cls, msg) => result.replaceChildren(el("div", `note ${cls}`, msg));
    if (c.ps5_user) say("good", `اللابتوب مربوط بالحساب «${c.ps5_user}»${c.ps5_name ? ` على ${c.ps5_name}` : ""}. ما تحتاج تعيد الخطوات.`);
    const busy = async (btn, fn) => {
      btn.disabled = true;
      try { await fn(); } catch (err) { say("bad", err.message); } finally { btn.disabled = false; }
    };
    $("#p-find", view).addEventListener("click", e => busy(e.target, async () => {
      $("#p-found").textContent = "أدوّر…";
      const r = await api("/api/ps5/discover", {});
      $("#p-found").textContent = r.found ? `لقيته: ${r.name} (${r.on ? "شغّال" : "في وضع الراحة"})` : "ما لقيته. تأكد إنه شغّال وعلى نفس الشبكة.";
      if (r.found && r.linked.length) say("good", `مربوط من قبل بالحساب «${r.linked[0]}».`);
      S.check = null; runCheck();
    }));
    $("#p-login", view).addEventListener("click", e => busy(e.target, () => api("/api/ps5/open-login", {})));
    $("#p-url-go", view).addEventListener("click", e => busy(e.target, async () => {
      const r = await api("/api/ps5/redirect", { url: $("#p-url").value });
      say("good", `تمام، الحساب: «${r.user}». باقي رقم الربط من الـPS5.`);
    }));
    $("#p-pin-go", view).addEventListener("click", e => busy(e.target, async () => {
      const r = await api("/api/ps5/pin", { pin: $("#p-pin").value });
      say("good", `تم الربط بالحساب «${r.user}» ✓`);
      S.check = null; runCheck();
    }));
  }

  if (S.guideStep === 3) {
    const ready = c.setup_done;
    view = html`
      <h2>${ready ? "كل شي جاهز" : "باقي شوي"}</h2>
      <p class="lead">${ready ? "من اليوم ورايح: افتح ترجِم، اختر اللعبة، واضغط الزر." : "كمّل خطوة التلفزيون وخطوة الـPS5، ثم ارجع هنا."}</p>
      <div class="tips">
        <div><b>🔌 شبّك الشاحن</b><p>على البطارية ويندوز يبطّئ المعالج والترجمة تتأخر.</p></div>
        <div><b>🎮 العب بحسابك العادي</b><p>الحساب الثاني للنسخة بس. لا تدخل اللعبة فيه.</p></div>
        <div><b>🧾 أضف أسماء الشخصيات</b><p>من «الإعدادات» ‹ قاموس الأسماء، عشان تنكتب صح دايماً.</p></div>
        <div><b>🔕 إشعار «اللعب عن بُعد متصل»</b><p>يطلع مرة عند البداية. تقدر تطفي الإشعارات من إعدادات الـPS5 ‹ الإشعارات.</p></div>
        <div><b>⏱ الترجمة تطلع قبل اكتمال السطر؟</b><p>فعّل «اللعبة تكتب النص حرف حرف» في إعدادات اللعبة.</p></div>
        <div><b>🧹 تبي تشيل كل شي من التلفزيون؟</b><p>شغّل الأمر tarjim tv revert ويرجع التلفزيون مثل ما كان.</p></div>
      </div>
      <button class="btn" data-goto="home">${ready ? "يلا نبدأ ←" : "للرئيسية ←"}</button>`;
    api("/api/guide-seen", {}).catch(() => {});
  }

  body.replaceChildren(view);
  if (S.task?.running) setBusy(true);
}

function setBusy(on) {
  $$("#tv-setup, #tv-test").forEach(b => b.disabled = on);
}

/* ------------------------------ live connection ------------------------------ */

function connect() {
  const es = new EventSource("/api/events");
  es.addEventListener("state", e => {
    const was = S.live.state;
    S.live = { ...S.live, ...JSON.parse(e.data) };
    renderLive();
    if (was !== "idle" && S.live.state === "idle") { S.check = S.check; runCheck(); }
    if (was === "starting" && S.live.state === "running") toast("الترجمة شغّالة ✓");
  });
  es.addEventListener("line", e => addLine(JSON.parse(e.data)));
  es.addEventListener("stats", e => renderStats(JSON.parse(e.data)));
  es.addEventListener("task", e => {
    const d = JSON.parse(e.data);
    S.task = d;
    if (d.item) pushLog($("#tv-log"), d.item);
    if (!d.running) {
      setBusy(false);
      if (d.name === "tv-setup") {
        const r = $("#tv-result");
        if (r) r.replaceChildren(el("div", `note ${d.ok ? "good" : "bad"}`, d.ok ? "التلفزيون جاهز ✓ جرّب مربعات الاختبار." : "ما اكتمل التجهيز. شوف الرسائل تحت."));
        S.check = null; runCheck();
      }
    }
  });
  es.onerror = () => { /* the browser reconnects by itself */ };
}

async function boot() {
  const st = await api("/api/state");
  S.profiles = st.profiles;
  S.live = st.live;
  S.task = st.task;
  S.selected = st.live.profile || st.last_profile || (st.profiles.find(p => p.name !== "default") || st.profiles[0])?.name;
  fillGames();
  selectGame(S.selected);
  renderLive();
  renderStats(st.live.stats || {});
  [...(st.live.lines || [])].forEach(l => addLine(l, false));
  // ?still&view=game&step=2 : a frozen page for screenshots (no live connection, no timers).
  const q = new URLSearchParams(location.search);
  if (q.has("still")) {
    runCheck();
    if (q.get("step")) S.guideStep = Number(q.get("step"));
    if (q.get("view")) go(q.get("view"));
    if (q.has("demo")) {
      S.live = { state: "running", step: "", error: "" };
      renderLive();
      renderStats({ latency_ms: 150, lines: 3, fps: 30 });
      addLine({ en: "We should leave before the storm gets here.", ar: "يجب أن نغادر قبل وصول العاصفة." }, false);
      addLine({ en: "Keep your voice down and stay close.", ar: "اخفض صوتك وابقَ قريباً." }, false);
      addLine({ en: "Hold the lantern higher, I can't see a thing.", ar: "ارفع الفانوس عالياً، لا أستطيع رؤية أي شيء." }, false);
    }
    return;
  }
  connect();
  if (!st.guide_seen && !st.setup_done) go("guide");
  runCheck();
  setInterval(() => { if (S.live.state === "idle" && document.visibilityState === "visible") runCheck(); }, 20000);
}
boot().catch(e => { $("#alert").hidden = false; $("#alert").textContent = e.message; });
