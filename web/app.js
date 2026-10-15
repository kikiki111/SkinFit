"use strict";
const $ = (id) => document.getElementById(id);
const state = {
  conditions: null,
  ownedItems: [],
  ownedProductIds: [],
  catalogProducts: [],
  currentResult: null,
  currentPriorities: ["concern", "routine", "stickiness", "price"],
  currentRoutineProductId: null,
  selectedProductId: null,
  routineView: "proposed",
  screen: "intake",
  confirmedConditions: null,
  confirmedInventory: null,
  edit: null,
  request: null,
  version: 0,
  photoUrl: null,
  busy: false,
};
const CATEGORY = {
  serum: "美容液",
  lotion: "化粧水",
  emulsion: "乳液",
  cream: "クリーム",
  cleanser: "クレンジング",
  sunscreen: "日焼け止め",
  other: "その他",
};
// 使う順番の目安（app/routine.py の ORDER と同じ）
const ORDER = {
  cleanser: 0,
  lotion: 1,
  serum: 2,
  emulsion: 3,
  cream: 4,
  sunscreen: 5,
  other: 6,
};
const ROUTINE_TEXT = {
  adds: "手持ちに無い方向性を加える",
  overlap: "手持ちに無い方向性は加わらない",
  unknown: "判断できない（手持ちの成分を確認しきれず）",
};
const ASPECT = {
  stickiness: "ベタつき",
  absorption: "なじみ",
  spread: "伸び",
  scent: "香り",
  moisture: "保湿感",
  makeup: "メイク前の使いやすさ",
  irritation: "刺激感",
};
const DEMO_TEXT =
  "3,000円以内で、乾燥による小じわが気になる自分向けの美容液を1本。ベタつくものは苦手。今の化粧水は残したい。";
const emptyConditions = () => ({
  concern: "",
  concern_label: "",
  category: "serum",
  budget_jpy_max: null,
  texture_preferences: [],
  avoid_ingredients: [],
  require_texture_evidence: false,
});
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
function safeURL(value) {
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}
function link(source, label) {
  const url = safeURL(source?.url || source?.source_url);
  return url
    ? `<a class="source-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label || source.title || "出典を見る")} ↗</a>`
    : "";
}
const show = (id, visible = true) =>
  $(id)?.classList.toggle("hidden", !visible);
function scrollBehavior() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
    ? "instant"
    : "smooth";
}
function moveTo(element, { focus = true } = {}) {
  if (!element) return;
  if (focus) element.focus({ preventScroll: true });
  element.scrollIntoView({ block: "start", behavior: scrollBehavior() });
}
function notice(message, success = false) {
  const host = $(`step-body-${state.screen}`) || $(`section-${state.screen}`);
  host?.prepend($("notice"));
  $("notice").textContent = message;
  $("notice").classList.toggle("success", success);
  show("notice");
  moveTo($("notice"), { focus: false });
}
function clearNotice() {
  show("notice", false);
}
// Pure projection: completed steps stay above the active step instead of being replaced.
function flowLayout(s) {
  const active = s.screen;
  const preview =
    !!s.currentResult?.is_preview &&
    ["candidates", "routines"].includes(active);
  const afterInput = ["progress", "candidates", "routines"].includes(active);
  return {
    intake: {
      visible: true,
      open: active === "intake",
      status: preview
        ? "未入力 · サンプル表示中"
        : active === "intake"
          ? s.edit
            ? "編集中"
            : "入力中"
          : "確認済み",
    },
    inventory: {
      visible: !preview && !!s.confirmedConditions && active !== "intake",
      open: active === "inventory",
      status:
        active === "inventory" ? (s.edit ? "編集中" : "入力中") : "確認済み",
    },
    progress: { visible: active === "progress", open: true, status: "調査中" },
    candidates: {
      visible: afterInput && active !== "progress" && !!s.currentResult,
      open: active === "candidates",
      status: preview
        ? "比較サンプル"
        : active === "routines"
          ? "使い方を確認中"
          : "比較する",
    },
    routines: {
      visible: active === "routines" && !!s.currentRoutineProductId,
      open: true,
      status:
        s.selectedProductId && s.selectedProductId === s.currentRoutineProductId
          ? "選択済み"
          : "確認する",
    },
  };
}
function inventoryValue() {
  return {
    owned_items: state.ownedItems.map(({ brand, name, category, keep }) => ({
      brand: brand.trim(),
      name: name.trim(),
      category,
      keep: !!keep,
    })),
    owned_product_ids: [...state.ownedProductIds],
  };
}
function fingerprint(value) {
  if (Array.isArray(value)) return `[${value.map(fingerprint).join(",")}]`;
  if (value && typeof value === "object")
    return `{${Object.keys(value)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${fingerprint(value[k])}`)
      .join(",")}}`;
  return JSON.stringify(value);
}
function invalidateResult() {
  state.currentResult = null;
  state.currentRoutineProductId = null;
  state.selectedProductId = null;
  state.confirmedInventory = null;
}
function finishEdit() {
  if (state.edit?.photoUrl && state.edit.photoUrl !== state.photoUrl)
    URL.revokeObjectURL(state.edit.photoUrl);
  state.edit = null;
}
function commitConditions(next) {
  const unchanged =
    fingerprint(next) === fingerprint(state.confirmedConditions);
  const resume = state.edit?.returnScreen;
  state.conditions = next;
  state.confirmedConditions = structuredClone(next);
  if (!unchanged || state.currentResult?.is_preview) {
    invalidateResult();
    state.currentPriorities = defaultPriorities();
  }
  finishEdit();
  return unchanged && state.currentResult && resume ? resume : "inventory";
}
function commitInventory() {
  const next = inventoryValue();
  const unchanged = fingerprint(next) === fingerprint(state.confirmedInventory);
  const resume = state.edit?.returnScreen || "candidates";
  const reusable =
    unchanged &&
    state.currentResult &&
    !state.currentResult.is_preview &&
    state.currentResult.status !== "HALTED";
  finishEdit();
  if (reusable) return resume;
  invalidateResult();
  state.confirmedInventory = structuredClone(next);
  return null;
}
let forwardTransition = null;
const flowOrder = {
  intake: 0,
  inventory: 1,
  progress: 2,
  candidates: 2,
  routines: 3,
};

// Keep the outgoing panel's height until the next heading has arrived on screen.
// Folding first would move that heading above the current scroll position.
function finishForwardTransition() {
  const transition = forwardTransition;
  if (!transition) return;
  window.cancelAnimationFrame(transition.frame);
  window.removeEventListener("scroll", transition.check);
  const topBefore = transition.target.getBoundingClientRect().top;
  forwardTransition = null;
  renderFlow();
  const delta = transition.target.getBoundingClientRect().top - topBefore;
  window.scrollTo({ top: window.scrollY + delta, behavior: "instant" });
  document.documentElement.classList.remove("flow-moving");
}
function watchForwardTransition() {
  const transition = forwardTransition;
  let frames = 0;
  transition.check = () => {
    if (forwardTransition !== transition) return;
    const top = transition.target.getBoundingClientRect().top;
    const atBottom =
      window.scrollY + window.innerHeight >=
      document.documentElement.scrollHeight - 2;
    if (top <= 54 || (atBottom && top < window.innerHeight))
      finishForwardTransition();
  };
  // If the user interrupts the scroll, keep the old panel in place until they
  // reach the next step themselves. Do not force another scroll or a collapse.
  window.addEventListener("scroll", transition.check, { passive: true });
  const checkFrame = () => {
    transition.check();
    if (forwardTransition === transition && ++frames < 120)
      transition.frame = window.requestAnimationFrame(checkFrame);
  };
  transition.frame = window.requestAnimationFrame(checkFrame);
}
function renderFlow() {
  const layout = flowLayout(state);
  show("research-stage", layout.progress.visible || layout.candidates.visible);
  const preview = state.currentResult?.is_preview;
  $("step-summary-text-intake").textContent = preview
    ? "比較サンプルを表示しています。ご自身の希望を入力して探すこともできます。"
    : state.confirmedConditions
      ? [
          conditionText(state.confirmedConditions),
          ...(state.confirmedConditions.texture_preferences || []).map(
            (p) =>
              p.note ||
              (p.aspect === "stickiness"
                ? "ベタつきにくさを重視"
                : ASPECT[p.aspect]),
          ),
        ]
          .filter(Boolean)
          .join(" / ")
      : "希望を入力するところから始めましょう。";
  const owned = [
    ...state.ownedItems.map((p) => [p.brand, p.name].filter(Boolean).join(" ")),
    ...state.ownedProductIds.map(
      (id) =>
        state.catalogProducts.find((p) => p.product_id === id)?.name || id,
    ),
  ];
  $("step-summary-text-inventory").textContent =
    `${owned.length}点 · ${owned.join(" / ")}`;
  const product = state.currentResult?.candidates?.find(
    (c) => c.product_id === state.currentRoutineProductId,
  );
  $("step-summary-text-candidates").textContent = product
    ? [product.brand, product.name, "の使い方を確認しています。"]
        .filter(Boolean)
        .join(" ")
    : "商品を比較する";
  for (const [step, view] of Object.entries(layout)) {
    if (forwardTransition?.step === step) {
      $(`section-${step}`).inert = true;
      continue;
    }
    $(`section-${step}`).inert = false;
    show(`section-${step}`, view.visible);
    show(`step-body-${step}`, view.open);
    show(`step-summary-${step}`, !view.open);
    $(`section-${step}`).dataset.flowState = view.open ? "active" : "complete";
    if (preview && step === "intake")
      $(`section-${step}`).dataset.flowState = "sample";
    if ($(`step-status-${step}`))
      $(`step-status-${step}`).textContent = view.status;
    document.querySelectorAll(`[data-go="${step}"]`).forEach((b) => {
      b.setAttribute("aria-expanded", String(view.visible && view.open));
      b.setAttribute("aria-controls", `step-body-${step}`);
      b.disabled = state.screen === "progress" || state.busy;
    });
  }
  show("cancel-edit-intake", state.edit?.step === "intake");
  show("cancel-edit-inventory", state.edit?.step === "inventory");
  $("btn-confirm-conditions").innerHTML = state.edit
    ? '変更を確定して続ける <span aria-hidden="true">↓</span>'
    : '次へ：いま使っているもの <span aria-hidden="true">↓</span>';
  $("btn-start-recommend").innerHTML = state.edit
    ? '内容を確定して続ける <span aria-hidden="true">↓</span>'
    : '次の1本を探す <span aria-hidden="true">↓</span>';
  $("btn-preview").disabled = state.screen === "progress" || state.busy;
}
function showSection(screen, { scroll = true } = {}) {
  const target = ["progress", "candidates"].includes(screen)
    ? $("research-stage")
    : $(`step-heading-${screen}`);
  // A fast response replaces progress at the same anchor while the downward
  // movement is still running; it must not interrupt that movement.
  const continuing = !scroll && forwardTransition?.target === target;
  if (!continuing) finishForwardTransition();
  const previous = state.screen;
  if (
    scroll &&
    flowOrder[screen] > flowOrder[previous] &&
    $(`step-body-${previous}`) &&
    !$(`step-body-${previous}`).classList.contains("hidden")
  ) {
    forwardTransition = { step: previous, target, frame: null, check: null };
    document.documentElement.classList.add("flow-moving");
  }
  state.screen = screen;
  renderFlow();
  if (scroll) moveTo(target);
  else if (document.activeElement?.closest(".hidden"))
    target?.focus({ preventScroll: true });
  if (scroll && forwardTransition) watchForwardTransition();
}
function cancelRequest() {
  state.version++;
  state.request?.abort();
  state.request = null;
  state.busy = false;
}
function beginEdit(step) {
  if (state.busy || state.screen === "progress") return;
  if (state.edit) cancelEdit(false);
  cancelRequest();
  const confirmed =
    step === "intake" ? state.confirmedConditions : state.confirmedInventory;
  if (confirmed) {
    state.edit = {
      step,
      returnScreen: state.screen,
      conditions: structuredClone(state.conditions),
      ownedItems: structuredClone(state.ownedItems),
      ownedProductIds: [...state.ownedProductIds],
      photoUrl: state.photoUrl,
      intakeText: $("intake-text").value,
    };
  }
  if (step === "intake" && state.conditions)
    renderConditions(state.conditions, []);
  clearNotice();
  showSection(step);
}
function cancelEdit(scroll = true) {
  const edit = state.edit;
  if (!edit) return;
  cancelRequest();
  if (state.photoUrl && state.photoUrl !== edit.photoUrl)
    URL.revokeObjectURL(state.photoUrl);
  state.conditions = edit.conditions;
  state.ownedItems = edit.ownedItems;
  state.ownedProductIds = edit.ownedProductIds;
  state.photoUrl = edit.photoUrl;
  $("intake-text").value = edit.intakeText;
  $("photo-preview").src = state.photoUrl || "";
  $("inventory-photo").value = "";
  show("photo-preview", !!state.photoUrl);
  show("inventory-detection", false);
  if (state.conditions) renderConditions(state.conditions, []);
  renderOwned();
  renderCatalog();
  state.edit = null;
  clearNotice();
  showSection(edit.returnScreen, { scroll });
}
function navigate(screen) {
  if (state.busy || state.screen === "progress") return;
  if (screen === "inventory" && !state.confirmedConditions) return;
  if (["intake", "inventory"].includes(screen)) return beginEdit(screen);
  if (screen === "candidates" && !state.currentResult) return;
  cancelRequest();
  clearNotice();
  showSection(screen);
}
document
  .querySelectorAll("[data-go]")
  .forEach((b) => b.addEventListener("click", () => navigate(b.dataset.go)));
for (const step of ["intake", "inventory"])
  $(`cancel-edit-${step}`).addEventListener("click", () => cancelEdit());
async function fetchJSON(url, options = {}) {
  const res = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (!res.ok) {
    let message = "通信に失敗しました。時間をおいてもう一度お試しください。";
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
    } catch {}
    throw new Error(message);
  }
  return res.json();
}
async function withBusy(button, label, work) {
  if (button.disabled) return;
  const old = button.innerHTML;
  button.disabled = true;
  button.textContent = label;
  clearNotice();
  try {
    await work();
  } catch (err) {
    if (err.name !== "AbortError") notice(err.message);
  } finally {
    button.disabled = false;
    button.innerHTML = old;
  }
}
function conditionText(cond) {
  return [
    cond.concern_label,
    CATEGORY[cond.category],
    cond.budget_jpy_max
      ? `${Number(cond.budget_jpy_max).toLocaleString()}円以内`
      : "予算の指定なし",
  ]
    .filter(Boolean)
    .join(" / ");
}
function defaultPriorities() {
  return (state.conditions?.texture_preferences || []).some(
    (p) => p.aspect === "stickiness" && p.preference === "avoid",
  )
    ? ["concern", "routine", "stickiness", "price"]
    : ["concern", "routine", "price"];
}

$("btn-demo-intake").addEventListener("click", () => {
  $("intake-text").value = DEMO_TEXT;
  $("intake-text").focus();
});
document.querySelectorAll("[data-concern]").forEach((b) =>
  b.addEventListener("click", () => {
    $("intake-text").value = `${b.dataset.concern}が気になります。`;
    $("intake-text").focus();
  }),
);
$("btn-direct-input").addEventListener("click", () => {
  cancelRequest();
  renderConditions(state.conditions || emptyConditions(), []);
  $("cond-concern-label").focus();
});
$("btn-parse-intake").addEventListener("click", () =>
  withBusy($("btn-parse-intake"), "希望を整理しています…", async () => {
    const text = $("intake-text").value.trim();
    if (!text) {
      $("intake-text").focus();
      throw new Error(
        "気になることを入力するか、フォームへの直接入力を選んでください。",
      );
    }
    cancelRequest();
    const version = state.version;
    const controller = new AbortController();
    state.request = controller;
    const timer = setTimeout(() => controller.abort(), 90000);
    try {
      const data = await fetchJSON("/api/intake/parse", {
        method: "POST",
        body: JSON.stringify({ text }),
        signal: controller.signal,
      });
      if (version !== state.version) return;
      renderConditions(data.conditions, data.follow_up_questions || []);
      moveTo($("intake-result"), { focus: false });
    } catch (err) {
      if (version !== state.version) return;
      renderConditions(state.conditions || emptyConditions(), []);
      throw new Error(
        "希望を自動で整理できませんでした。下のフォームに直接入力して続けられます。",
      );
    } finally {
      clearTimeout(timer);
      if (version === state.version) state.request = null;
    }
  }),
);
function renderConditions(cond, questions) {
  state.conditions = { ...emptyConditions(), ...cond };
  $("cond-concern-label").value = cond.concern_label || "";
  $("cond-category").value = cond.category || "serum";
  $("cond-budget").value = cond.budget_jpy_max ?? "";
  $("cond-concern-note").value = cond.concern_note || "";
  $("cond-keep-note").value = cond.keep_note || "";
  $("cond-avoid-ingredients").value = (cond.avoid_ingredients || []).join("、");
  $("cond-avoid-sticky").checked = (cond.texture_preferences || []).some(
    (p) => p.aspect === "stickiness" && p.preference === "avoid",
  );
  $("cond-require-texture").checked = !!cond.require_texture_evidence;
  const other = (cond.texture_preferences || []).filter(
    (p) => p.aspect !== "stickiness",
  );
  $("texture-preferences-list").innerHTML = other.length
    ? `<p class="note">ほかの希望：${other.map((p) => esc(p.note || ASPECT[p.aspect])).join(" / ")}<br>これらは説明の参考として扱います。並び順は悩みとの関連・ベタつき・価格から決めます。</p>`
    : "";
  $("followup-questions").innerHTML = questions
    .map((q) => `<p>${esc(q)}</p>`)
    .join("");
  show("followup-questions", questions.length > 0);
  show("intake-result");
}
$("form-conditions").addEventListener("submit", async (e) => {
  e.preventDefault();
  clearNotice();
  const concern = $("cond-concern-label").value.trim();
  if (!concern) {
    notice("いちばん気になることを入力してください。");
    $("cond-concern-label").focus();
    return;
  }
  const raw = $("cond-budget").value,
    budget = raw ? Number(raw) : null;
  if (raw && (!Number.isSafeInteger(budget) || budget <= 0)) {
    notice("予算は1円以上の整数で入力してください。");
    $("cond-budget").focus();
    return;
  }
  const prefs = (state.conditions?.texture_preferences || []).filter(
    (p) => p.aspect !== "stickiness",
  );
  if ($("cond-avoid-sticky").checked)
    prefs.push({ aspect: "stickiness", preference: "avoid" });
  const nextConditions = {
    ...emptyConditions(),
    ...state.conditions,
    concern: "",
    concern_label: concern,
    category: $("cond-category").value,
    budget_jpy_max: budget,
    concern_note: $("cond-concern-note").value.trim() || null,
    keep_note: $("cond-keep-note").value.trim() || null,
    texture_preferences: prefs,
    require_texture_evidence: $("cond-require-texture").checked,
    avoid_ingredients: $("cond-avoid-ingredients")
      .value.split(/[,、，\n]/)
      .map((s) => s.trim())
      .filter(Boolean),
  };
  cancelRequest();
  const nextScreen = commitConditions(nextConditions);
  $("condition-summary").textContent = conditionText(state.conditions);
  renderOwned();
  showSection(nextScreen);
  try {
    const data = await fetchJSON("/api/catalog", {
      signal: AbortSignal.timeout(15000),
    });
    state.catalogProducts = data.owned_candidates || [];
    renderCatalog();
  } catch {
    show("catalog-details", false);
  }
});
function renderCatalog() {
  const products = state.catalogProducts;
  show("catalog-details", products.length > 0);
  $("catalog-list").replaceChildren();
  products.forEach((p) => {
    const row = document.createElement("label");
    row.className = "check";
    row.innerHTML = `<input type="checkbox" ${state.ownedProductIds.includes(p.product_id) ? "checked" : ""}><span>${esc(p.brand)} ${esc(p.name)}</span>`;
    row.querySelector("input").addEventListener("change", (e) => {
      if (
        e.target.checked &&
        state.ownedItems.length + state.ownedProductIds.length >= 8
      ) {
        e.target.checked = false;
        notice("手持ちは8点まで登録できます。");
        return;
      }
      state.ownedProductIds = e.target.checked
        ? [...state.ownedProductIds, p.product_id]
        : state.ownedProductIds.filter((id) => id !== p.product_id);
      renderOwned();
    });
    $("catalog-list").append(row);
  });
}
function addOwned() {
  if (state.ownedItems.length + state.ownedProductIds.length >= 8) {
    notice("手持ちは8点まで登録できます。");
    return;
  }
  state.ownedItems.push({
    brand: "",
    name: "",
    category: "other",
    keep: false,
  });
  renderOwned();
  $("owned-items-list")
    .lastElementChild?.querySelector('[data-field="name"]')
    ?.focus();
}
$("btn-manual-input").addEventListener("click", addOwned);
$("btn-add-owned-row").addEventListener("click", addOwned);
$("btn-sample-owned").addEventListener("click", () => {
  state.ownedItems = [
    {
      brand: "ちふれ",
      name: "化粧水 とてもしっとりタイプ",
      category: "lotion",
      keep: true,
    },
    {
      brand: "キュレル",
      name: "潤浸保湿 乳液",
      category: "emulsion",
      keep: false,
    },
  ];
  state.ownedProductIds = [];
  renderOwned();
  renderCatalog();
});
// 探すアイテムと同じ種類で「残したい」でない手持ちは、入れ替える前提で調べる（サーバーの判定と同じ規則）
function replacementText(cond, items) {
  const target = cond?.category;
  if (!target || target === "other") return "";
  const same = items.filter((i) => i.category === target && !i.keep);
  if (!same.length) return "";
  const names = same
    .map(
      (i) =>
        [i.brand, i.name].filter(Boolean).join(" ") || "名前未入力のアイテム",
    )
    .join("・");
  return `${CATEGORY[target]}を探しているため、今の${names}と入れ替える前提で調べます。併用する場合は「このアイテムは残したい」にチェックしてください。`;
}
function renderReplaceNote() {
  const catalog = state.ownedProductIds
    .map((id) => state.catalogProducts.find((p) => p.product_id === id))
    .filter(Boolean)
    .map((p) => ({ ...p, keep: false }));
  const text = replacementText(state.conditions, [
    ...state.ownedItems,
    ...catalog,
  ]);
  $("owned-replace-note").textContent = text;
  show("owned-replace-note", !!text);
}
function renderOwned() {
  const list = $("owned-items-list");
  list.replaceChildren();
  $("owned-count").textContent =
    `${state.ownedItems.length + state.ownedProductIds.length} / 8`;
  if (!state.ownedItems.length)
    list.innerHTML = `<p class="empty-shelf">${state.ownedProductIds.length ? "登録済みのアイテムを選択しています。" : "まだアイテムがありません。<br>写真から読み取るか、商品名を入力してください。"}</p>`;
  state.ownedItems.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = "owned-item-row";
    row.innerHTML = `<div class="row-top"><span>ITEM ${String(index + 1).padStart(2, "0")}</span><button class="owned-item-remove" aria-label="${index + 1}点目を削除">削除</button></div><div class="form-grid"><div class="field"><label for="owned-brand-${index}">ブランド</label><input id="owned-brand-${index}" data-field="brand" value="${esc(item.brand)}" maxlength="120" placeholder="例：ちふれ"></div><div class="field"><label for="owned-name-${index}">商品名</label><input id="owned-name-${index}" data-field="name" value="${esc(item.name)}" maxlength="120" placeholder="ラベルに書かれた商品名" list="alternatives-${index}"><datalist id="alternatives-${index}">${(item.alternatives || []).map((x) => `<option value="${esc(x)}"></option>`).join("")}</datalist></div></div><div class="form-grid"><div class="field"><label for="owned-category-${index}">種類</label><select id="owned-category-${index}" data-field="category">${Object.entries(
      CATEGORY,
    )
      .map(
        ([k, v]) =>
          `<option value="${k}" ${item.category === k ? "selected" : ""}>${v}</option>`,
      )
      .join(
        "",
      )}</select></div><label class="check"><input type="checkbox" data-field="keep" ${item.keep ? "checked" : ""}>このアイテムは残したい</label></div>${item.is_sample ? '<p class="owned-item-hint">試供品の可能性があります。対象に含めるか確認してください。</p>' : ""}${item.visible_text ? `<p class="owned-item-hint">読み取った文字：${esc(item.visible_text)}</p>` : ""}`;
    row.querySelectorAll("[data-field]").forEach((input) =>
      input.addEventListener("input", () => {
        item[input.dataset.field] =
          input.type === "checkbox" ? input.checked : input.value;
        renderReplaceNote();
      }),
    );
    row.querySelector(".owned-item-remove").addEventListener("click", () => {
      state.ownedItems.splice(index, 1);
      renderOwned();
    });
    list.append(row);
  });
  renderReplaceNote();
}
$("inventory-photo").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  clearNotice();
  if (file.size > 7 * 1024 * 1024) {
    notice("写真は7MB以下のものを選んでください。");
    e.target.value = "";
    return;
  }
  if (
    ![
      "image/jpeg",
      "image/png",
      "image/heic",
      "image/heif",
      "image/webp",
    ].includes(file.type)
  ) {
    notice("JPEG・PNG・HEIC・WebPの写真を選んでください。");
    e.target.value = "";
    return;
  }
  if (state.photoUrl && state.photoUrl !== state.edit?.photoUrl)
    URL.revokeObjectURL(state.photoUrl);
  state.photoUrl = URL.createObjectURL(file);
  $("photo-preview").src = state.photoUrl;
  show("photo-preview");
  cancelRequest();
  const version = state.version;
  const controller = new AbortController();
  state.request = controller;
  state.busy = true;
  renderFlow();
  e.target.disabled = true;
  $("inventory-detection").textContent = "写真から商品名を読み取っています…";
  show("inventory-detection");
  const timer = setTimeout(() => controller.abort(), 90000);
  try {
    const data = new FormData();
    data.append("image", file, file.name);
    const res = await fetch("/api/inventory/extract", {
      method: "POST",
      body: data,
      signal: controller.signal,
    });
    const result = await res.json();
    if (!res.ok)
      throw new Error(
        typeof result.detail === "string"
          ? result.detail
          : "写真を読み取れませんでした。",
      );
    if (version !== state.version) return;
    const detected = result.detections || [];
    if (detected.length) {
      const room = 8 - state.ownedProductIds.length;
      state.ownedItems = detected.slice(0, room).map((d) => ({
        brand: d.brand || "",
        name: d.name_guess || d.visible_text || "",
        category: CATEGORY[d.category] ? d.category : "other",
        keep: false,
        alternatives: d.alternatives || [],
        visible_text: d.visible_text || "",
        is_sample: !!d.is_sample,
      }));
      renderOwned();
    }
    $("inventory-detection").textContent =
      (result.note || "商品名・種類が合っているか確認してください。") +
      (detected.length > state.ownedItems.length
        ? " 登録上限の8点に収まる範囲で表示しています。"
        : "") +
      (!detected.length ? " 商品名を手で入力して続けられます。" : "");
  } catch (err) {
    if (version === state.version) {
      $("inventory-detection").textContent =
        "写真を読み取れませんでした。商品名を手で入力して続けられます。";
      notice(
        err.name === "AbortError"
          ? "読み取りが時間内に終わりませんでした。写真を変えるか、手で入力してください。"
          : err.message,
      );
    }
  } finally {
    clearTimeout(timer);
    e.target.disabled = false;
    if (version === state.version) {
      state.busy = false;
      state.request = null;
      renderFlow();
    }
  }
});
const progressStages = [
  {
    label: "手持ちの成分をたしかめる",
    nodes: ["intake_check", "owned_research"],
  },
  {
    label: "希望に合う商品を探す",
    nodes: ["concern_planner", "candidate_discovery", "candidate_search"],
  },
  {
    label: "成分・使い心地を比べる",
    nodes: [
      "candidate_research",
      "other_step_research",
      "ingredient_branch",
      "review_branch",
      "routine_branch",
      "join",
    ],
  },
  { label: "おすすめと使い方をまとめる", nodes: ["rank", "explain", "verify"] },
];
let progressIndex = 0;
function renderProgress(event) {
  const index = progressStages.findIndex((s) => s.nodes.includes(event.node));
  if (index >= 0) progressIndex = Math.max(progressIndex, index);
  $("progress-list").innerHTML = progressStages
    .map(
      (s, i) =>
        `<li class="progress-item ${i < progressIndex ? "done" : i === progressIndex ? "running" : ""}">${esc(s.label)}</li>`,
    )
    .join("");
}
$("btn-start-recommend").addEventListener("click", async () => {
  if (state.busy) {
    notice("写真の読み取りが終わってから、商品名を確認してください。");
    return;
  }
  if (!state.ownedItems.length && !state.ownedProductIds.length) {
    notice("手持ちの商品を1点以上入力してください。");
    return;
  }
  const blank = state.ownedItems.findIndex((p) => !p.name.trim());
  if (blank >= 0) {
    notice(
      `${blank + 1}点目の商品名を入力するか、空のアイテムを削除してください。`,
    );
    $(`owned-name-${blank}`).focus();
    return;
  }
  const resume = commitInventory();
  clearNotice();
  if (resume) {
    showSection(resume);
    return;
  }
  cancelRequest();
  const version = state.version;
  const controller = new AbortController();
  state.request = controller;
  state.busy = true;
  progressIndex = 0;
  $("research-announcement").textContent = "";
  renderProgress({ node: "intake_check" });
  showSection("progress");
  const start = Date.now();
  const interval = setInterval(() => {
    $("progress-elapsed").textContent =
      `／ ${Math.floor((Date.now() - start) / 1000)}秒経過`;
  }, 1000);
  $("progress-elapsed").textContent = "";
  const timer = setTimeout(() => controller.abort(), 300000);
  try {
    const result = await recommendStream(
      {
        conditions: state.conditions,
        owned_items: state.ownedItems.map(
          ({ brand, name, category, keep }) => ({
            brand,
            name: name.trim(),
            category,
            keep,
          }),
        ),
        owned_product_ids: state.ownedProductIds,
        priorities: state.currentPriorities,
      },
      controller.signal,
      (event) => {
        if (version === state.version) renderProgress(event);
      },
    );
    if (version !== state.version) return;
    state.currentResult = result;
    state.busy = false;
    renderResult(result);
    showSection("candidates", { scroll: false });
    $("research-announcement").textContent =
      "調査が完了しました。この下で結果を確認できます。";
  } catch (err) {
    if (version === state.version) {
      state.busy = false;
      showSection("inventory", { scroll: false });
      notice(
        err.name === "AbortError"
          ? "調査が時間内に終わりませんでした。入力は残っています。もう一度お試しください。"
          : err.message,
      );
    }
  } finally {
    clearInterval(interval);
    clearTimeout(timer);
    if (version === state.version) {
      state.request = null;
      state.busy = false;
    }
  }
});
$("btn-cancel").addEventListener("click", () => {
  cancelRequest();
  showSection("inventory");
  notice("調査を中止しました。入力内容はそのまま残っています。", true);
});
async function recommendStream(body, signal, onProgress) {
  const res = await fetch("/api/recommend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body)
    throw new Error(
      "調査を開始できませんでした。入力を確認してもう一度お試しください。",
    );
  const reader = res.body.getReader(),
    decoder = new TextDecoder();
  let buffer = "",
    result = null;
  const line = (s) => {
    if (!s.trim()) return;
    const event = JSON.parse(s);
    if (event.type === "progress") onProgress(event);
    if (event.type === "result") result = event.result;
  };
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        buffer += decoder.decode();
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      lines.forEach(line);
    }
    line(buffer);
  } finally {
    reader.releaseLock();
  }
  if (!result)
    throw new Error(
      "調査の途中で通信が切れました。入力は残っています。もう一度お試しください。",
    );
  return result;
}
$("btn-preview").addEventListener("click", () =>
  withBusy($("btn-preview"), "サンプルを開いています…", async () => {
    cancelRequest();
    const version = state.version;
    const result = await fetchJSON("/api/preview", {
      signal: AbortSignal.timeout(15000),
    });
    if (version !== state.version) return;
    finishEdit();
    state.currentRoutineProductId = null;
    state.currentResult = result;
    state.currentPriorities = ["concern", "routine", "stickiness", "price"];
    state.selectedProductId = null;
    renderResult(result);
    showSection("candidates");
  }),
);
// 商品写真は、https の画像だけを表示する（Yahoo!・楽天の公式APIの画像、登録データの公式画像URL）
function mediaSrc(media) {
  const src = media?.src;
  if (!src) return null;
  try {
    const url = new URL(src);
    return url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}
// 楽天の規約で、楽天の画像を出す枠には楽天へのリンクだけを置く。リンク先は各社の商品ページ
const MEDIA_LINK_LABEL = {
  yahoo: "Yahoo!ショッピングで見る",
  rakuten: "楽天市場で見る",
};
function mediaMarkup(product, rank) {
  const media = product.media;
  const src = mediaSrc(media);
  const small = media?.provider === "rakuten" ? ' class="is-small"' : ""; // 楽天の画像は128pxなので引き伸ばさない
  return `<div class="product-visual"><div class="product-kicker"><span>${String(rank).padStart(2, "0")}</span>${rank === 1 ? "OUR PICK" : "ANOTHER OPTION"}</div>${src ? `<img src="${esc(src)}"${small} alt="${esc(product.brand)} ${esc(product.name)}" loading="lazy" referrerpolicy="no-referrer" width="400" height="400"><div class="product-credit">${link(media, MEDIA_LINK_LABEL[media.provider] || media.credit)}</div>` : `<div class="product-placeholder"><span class="placeholder-mark" aria-hidden="true">s.</span><span>${esc(CATEGORY[product.category] || "スキンケア")}</span><p>商品写真は未確認です</p></div>`}</div>`;
}
// 「公式の商品ページ」と書くのは、人が公式ページで確かめた登録画像のときだけ。ショップの画像なら価格の出典へ
function productPageLink(c) {
  return c.media && (c.media.provider || "registered") === "registered"
    ? link(c.media, "公式の商品ページ")
    : link(c.price_source, "商品の情報を見る");
}
function priceMarkup(c) {
  return c.price_jpy != null
    ? `<span class="price">¥${Number(c.price_jpy).toLocaleString()}<small>税込${c.volume_text ? ` / ${esc(c.volume_text)}` : ""}</small></span>`
    : '<span class="note">価格は未確認です</span>';
}
function reviewChart(aspect, scope) {
  if (!aspect)
    return '<p class="note">この使用感についての情報はありません。</p>';
  const rows = [
    ["positive", "肯定"],
    ["negative", "否定"],
    ["mixed", "混在"],
    ["unknown", "言及なし"],
  ];
  const total = rows.reduce((s, [k]) => s + (Number(aspect[k]) || 0), 0);
  if (!total) return '<p class="note">使用感を判断できる情報がありません。</p>';
  return `<figure class="review-chart"><figcaption>${esc(aspect.label)}について · ${total}${scope?.unit === "sources" ? "情報源" : "件の口コミ"}</figcaption><div class="review-bar" aria-hidden="true">${rows.map(([key]) => `<span class="${key}" style="width:${(100 * (Number(aspect[key]) || 0)) / total}%"></span>`).join("")}</div><div class="legend">${rows.map(([k, label]) => `<span><i class="${k}" aria-hidden="true"></i>${label} ${Number(aspect[k]) || 0}</span>`).join("")}</div></figure>`;
}
function detailMarkup(c) {
  const rel = c.concern_relevance || {},
    scope = c.review_scope || {},
    ex = c.explanation || {};
  const claims = (rel.claims || [])
    .map((cl) => `<p>${esc(cl.text)}</p>${link(cl.source)}`)
    .join("");
  const evidence = (rel.evidence || [])
    .map(
      (e) =>
        `<p>${esc(e.summary)}</p><p class="note">対象・条件：${esc(e.scope)}<br>わかっていないこと：${esc(e.limitations)}</p>${link(e.source)}`,
    )
    .join("");
  const ingredients = [...new Set((rel.ingredients || []).map((i) => i.name))];
  const notes = [
    ...(c.cautions || []),
    ...(c.unknown || []),
    ...(ex.unverified || []),
  ];
  return `<details class="product-detail"><summary>成分・口コミ・選んだ理由を詳しく見る</summary><div class="detail-grid"><div class="detail-block"><h4>製品の表示と成分</h4>${claims || '<p class="note">悩みに対応する効能表示は確認できていません。</p>'}<p>${ingredients.map((i) => `<span class="tag">${esc(i)}</span>`).join("")}</p>${evidence ? `<h4>成分に関する一般的な知見</h4>${evidence}` : ""}<p class="note">成分の研究結果が、そのままこの製品の効果を示すわけではありません。</p></div><div class="detail-block"><h4>使用感の内訳</h4>${
    (c.texture?.aspects || [])
      .filter((a) => a.positive + a.negative + a.mixed > 0)
      .map((a) => reviewChart(a, scope))
      .join("") || '<p class="note">口コミの情報が不足しています。</p>'
  }<p class="note">${Number(scope.analyzed_count) || 0}${scope.unit === "sources" ? "情報源" : "件の口コミ"}を分析。${scope.unit === "sources" ? "投稿者の人数や満足度を示す数値ではありません。" : ""}</p>${(scope.notes || []).map((n) => `<p class="note">${esc(n)}</p>`).join("")}${c.texture?.maker_description ? `<h4>メーカーによる使用感の説明</h4><p>${esc(c.texture.maker_description)}</p>` : ""}${(
    c.texture?.aspects || []
  )
    .flatMap((a) => a.examples || [])
    .filter(
      (e, i, all) => all.findIndex((x) => x.review_id === e.review_id) === i,
    )
    .slice(0, 4)
    .map(
      (e) =>
        `<p class="note">${esc(e.summary)} ${link(e, e.source_title || "口コミの出典")}</p>`,
    )
    .join("")}</div><div class="detail-block"><h4>手持ちとの関係</h4>${(
    c.owned_relation?.note || "手持ちを入力すると比較できます。"
  )
    .split("。")
    .filter(Boolean)
    .map((t) => `<p>${esc(t)}。</p>`)
    .join(
      "",
    )}${c.owned_relation?.active_ingredients?.length ? `<h4>この候補の有効成分</h4><p>${c.owned_relation.active_ingredients.map((a) => `<span class="tag">${esc(a)}</span>`).join("")}</p>` : ""}<h4>順位の理由</h4><p>${esc(c.rank_reason)}</p>${(ex.reasons || []).map((r) => `<p class="note">${esc(r.text)}</p>`).join("")}</div><div class="detail-block"><h4>使い方と確認事項</h4><p>${c.usage?.timing?.length ? c.usage.timing.map((t) => (t === "morning" ? "朝" : "夜")).join("・") : "使用する時間帯は未確認です。"}</p><p>${esc(c.usage?.order_note)}</p>${link(c.usage?.source)}${[...new Set(notes)].map((n) => `<p class="note">${esc(n)}</p>`).join("")}<p class="note">参考価格の確認日：${esc(c.price_checked_at || "未確認")}<br>${esc(c.price_note)}</p>${link(c.price_source, "価格の出典")}</div></div></details>`;
}
// 入れ替える手持ちと候補の、メーカーの使用感の説明を並べる（重い・軽いの判定はしない）
function textureCompare(c) {
  const rows = Object.entries(c.owned_relation?.replaced_textures || {});
  if (!rows.length) return "";
  const mine = c.texture?.maker_description || "メーカーの説明を確認できず";
  return `<div class="texture-compare"><p class="micro">使用感の比較（メーカーの説明）</p>${rows
    .map(
      ([name, desc]) =>
        `<p>今の${esc(name)}：${esc(desc || "メーカーの説明を確認できず")}<span aria-hidden="true"> → </span><span class="sr-only">、</span>この候補：${esc(mine)}</p>`,
    )
    .join("")}</div>`;
}
function productCard(c, index, result) {
  const card = document.createElement("article");
  card.className = index === 0 ? "featured-product" : "alternative";
  const rel = c.concern_relevance || {};
  const shortRel =
    {
      claim: "悩みに対応する効能表示あり",
      ingredient: "関連する成分を確認",
      none: "関連は未確認",
    }[rel.level] || rel.label;
  const shortTexture = {
    good: "ベタつきへの否定が少ない",
    mixed: "評価が分かれる",
    bad: "ベタつきへの否定が多い",
    insufficient: "情報が足りない",
  }[c.texture?.stickiness_level];
  const routineFact = result.is_preview
    ? ""
    : `<div><dt>手持ちとの補い合い</dt><dd>${esc(ROUTINE_TEXT[c.owned_relation?.routine_level] || ROUTINE_TEXT.unknown)}</dd></div>`;
  card.innerHTML = `${mediaMarkup(c, index + 1)}<div class="product-copy"><p class="product-brand">${esc(c.brand)}</p><h2 class="product-name">${esc(c.name)}</h2><p class="product-meta">${esc(CATEGORY[c.category])}${c.regulatory_class === "quasi_drug" ? " / 医薬部外品" : ""}</p>${priceMarkup(c)}<p class="product-summary">${esc(c.explanation?.summary || rel.label)}</p><dl class="fit-facts"><div><dt>悩みとの関連</dt><dd>${esc(shortRel)}</dd></div><div><dt>使い心地の傾向</dt><dd>${esc(shortTexture)}</dd></div>${routineFact}</dl>${textureCompare(c)}${
    index === 0
      ? reviewChart(
          c.texture?.aspects?.find((a) => a.aspect === "stickiness"),
          c.review_scope,
        )
      : ""
  }${c.explanation?.tradeoffs?.length ? `<p class="note">留意したいこと：${esc(c.explanation.tradeoffs[0])}</p>` : ""}<button class="button ${index === 0 ? "primary" : "secondary"} routine-button">${result.is_preview ? "使い方の案を見る" : "手持ちと組んでみる"}<span aria-hidden="true">↓</span></button>${productPageLink(c)}</div>${detailMarkup(c)}`;
  card.querySelector(".routine-button").addEventListener("click", () => {
    state.currentRoutineProductId = c.product_id;
    state.routineView = "proposed";
    renderRoutines();
    showSection("routines");
  });
  // 外部の画像が読めないときは、写真なしと同じ表示に戻す
  card.querySelector(".product-visual img")?.addEventListener("error", (e) => {
    e.target.closest(".product-visual").outerHTML = mediaMarkup(
      { ...c, media: null },
      index + 1,
    );
  });
  return card;
}
function renderResult(result) {
  clearNotice();
  show("rank-change-message", false);
  for (const id of [
    "candidates-list",
    "comparison",
    "other-step",
    "owned-analysis",
    "ranking-why",
    "status-message",
    "search-suggestions",
  ]) {
    $(id).replaceChildren();
  }
  show("status-message", false);
  show("research-mode-banner", false);
  show("search-suggestions", false);
  const banner = $("research-mode-banner");
  if (result.is_preview) {
    banner.textContent =
      "比較サンプル · 小じわ / 美容液 / 3,000円以内。登録済みの実在商品を使った表示例です。手持ちの入力や最新情報の検索は行っていません。";
    show("research-mode-banner");
  } else if (result.research_mode === "catalog_fallback") {
    banner.textContent =
      "検索が完了しなかったため、登録済みの候補から比較しています。";
    show("research-mode-banner");
  } else if (result.research_mode === "live") {
    banner.textContent = `検索で確認した情報をもとにしています${result.researched_at ? `（${result.researched_at}）` : ""}。`; // safe-html: textContentへの代入でHTMLとして解釈されない
    show("research-mode-banner");
  }
  if (result.uses_dummy_data) {
    banner.textContent += " 検証用のダミーデータを含みます。";
    show("research-mode-banner");
  }
  banner.classList.toggle(
    "warning",
    result.research_mode === "catalog_fallback" || result.uses_dummy_data,
  );
  const ready =
    result.status === "RECOMMENDATION_READY" && result.candidates?.length;
  show("result-content", !!ready);
  if (!ready) {
    const labels = {
      NEEDS_MORE_INFO: "あと少し、教えてください。",
      NO_MATCH_IN_SCOPE: "この条件では、選びきれませんでした。",
      HALTED: "今回は調べきれませんでした。",
    };
    $("status-message").innerHTML =
      `<h2>${esc(labels[result.status] || "結果を確認できませんでした。")}</h2><p>${esc(result.status_message)}</p>${[...(result.follow_up_questions || []), ...(result.missing || [])].map((q) => `<p class="note">${esc(q)}</p>`).join("")}<button class="button secondary">条件を見直して、もう一度 ↑</button>`;
    $("status-message")
      .querySelector("button")
      .addEventListener("click", () =>
        navigate(result.status === "HALTED" ? "inventory" : "intake"),
      );
    show("status-message");
  } else {
    $("result-conditions").textContent = result.is_preview
      ? "小じわ / 美容液 / 3,000円以内"
      : conditionText(state.conditions || emptyConditions());
    $("ranking-why").textContent = result.ranking?.why_top || "";
    const list = $("candidates-list");
    list.append(productCard(result.candidates[0], 0, result));
    if (result.candidates.length > 1) {
      const header = document.createElement("div");
      header.className = "alternatives-title";
      header.innerHTML =
        "<h2>こちらも、選択肢に。</h2><span>OTHER POSSIBILITIES</span>";
      list.append(header);
      const alternatives = document.createElement("div");
      alternatives.className = "alternatives";
      result.candidates
        .slice(1)
        .forEach((c, i) => alternatives.append(productCard(c, i + 1, result)));
      list.append(alternatives);
    }
    renderComparison(result);
    $("other-step").innerHTML = otherStepMarkup(result.other_step);
    updatePriorityButtons();
  }
  renderOwnedAnalysis(result);
  renderSuggestions(result.search_suggestions_html || []);
}
function updatePriorityButtons() {
  const concern = state.currentPriorities[0] === "concern";
  $("btn-priority-concern").setAttribute("aria-pressed", String(concern));
  $("btn-priority-light").setAttribute("aria-pressed", String(!concern));
}
$("btn-priority-concern").addEventListener("click", () =>
  rerank(
    state.currentResult?.is_preview
      ? ["concern", "routine", "stickiness", "price"]
      : defaultPriorities(),
  ),
);
$("btn-priority-light").addEventListener("click", () =>
  rerank(["stickiness", "concern", "routine", "price"]),
);
async function rerank(priorities) {
  if (
    !state.currentResult ||
    JSON.stringify(priorities) === JSON.stringify(state.currentPriorities)
  )
    return;
  cancelRequest();
  const version = state.version;
  const controller = new AbortController();
  state.request = controller;
  const timeout = setTimeout(() => controller.abort(), 30000);
  const previous = state.currentResult;
  $("btn-priority-concern").disabled = true;
  $("btn-priority-light").disabled = true;
  clearNotice();
  try {
    const result = previous.is_preview
      ? await fetchJSON(
          `/api/preview?priority=${priorities[0] === "stickiness" ? "light" : "concern"}`,
          { signal: controller.signal },
        )
      : await fetchJSON("/api/rerank", {
          method: "POST",
          body: JSON.stringify({
            conditions: state.conditions,
            owned_items: state.ownedItems.map(
              ({ brand, name, category, keep }) => ({
                brand,
                name,
                category,
                keep,
              }),
            ),
            owned_product_ids: state.ownedProductIds,
            priorities,
            analysis: previous.analysis,
          }),
          signal: controller.signal,
        });
    if (version !== state.version) return;
    state.currentPriorities = priorities;
    state.currentResult = result;
    renderResult(result);
    show("rank-change-message");
    $("rank-change-message").textContent =
      previous.recommended_product_id === result.recommended_product_id
        ? "優先する観点を変えても、おすすめは同じでした。 "
        : "優先する観点に合わせて、おすすめが変わりました。 ";
  } catch (err) {
    if (version === state.version)
      notice(
        "並べ替えができませんでした。直前の順番を表示しています。もう一度お試しください。",
      );
  } finally {
    clearTimeout(timeout);
    $("btn-priority-concern").disabled = false;
    $("btn-priority-light").disabled = false;
    if (version === state.version) state.request = null;
  }
}
// 1位と2位の差を、折りたたまずに1文で出す（順位の計算で最初に差がついた観点）
function rankLead(result) {
  const cmp = result.ranking?.comparisons?.[0],
    cs = result.candidates || [];
  if (!cmp || cs.length < 2) return "";
  const name = (id) => cs.find((c) => c.product_id === id)?.name || id;
  return `<p class="rank-lead"><strong>${esc(name(cmp.winner))}を${esc(name(cmp.loser))}より上にした理由</strong><span>${esc(cmp.detail)}</span></p>`;
}
function renderComparison(result) {
  const cs = result.candidates;
  if (cs.length < 2) return;
  const row = (label, fn) =>
    `<tr><th scope="row">${label}</th>${cs.map((c, i) => `<td class="${i === 0 ? "best" : ""}">${fn(c)}</td>`).join("")}</tr>`;
  $("comparison").innerHTML =
    `<div class="block-heading"><h2>違いを、ひと目で。</h2><span>SIDE BY SIDE</span></div>${rankLead(result)}<div class="comparison-wrap" tabindex="0" role="region" aria-label="商品比較表。スマホでは横にスクロールできます"><table class="comparison-table"><caption>悩みとの関連・使用感・参考価格で比較。横にスクロールできます。</caption><thead><tr><th scope="col">比べるポイント</th>${cs.map((c) => `<th scope="col"><span class="micro">${esc(c.brand)}</span><span class="table-name">${esc(c.name)}</span></th>`).join("")}</tr></thead><tbody>${row("参考価格", (c) => (c.price_jpy == null ? "未確認" : `¥${Number(c.price_jpy).toLocaleString()}<span class="micro">税込${c.volume_text ? ` / ${esc(c.volume_text)}` : ""}</span>`))}${row("悩みとの関連", (c) => esc(c.concern_relevance.label))}${result.is_preview ? "" : row("手持ちとの補い合い", (c) => esc(ROUTINE_TEXT[c.owned_relation?.routine_level] || ROUTINE_TEXT.unknown))}${row("ベタつき", (c) => esc(c.texture.stickiness_label))}${row("情報の範囲", (c) => `${c.review_scope.analyzed_count}${c.review_scope.unit === "sources" ? "情報源" : "件の口コミ"}`)}${row("使う時間帯", (c) => (c.usage.timing.length ? c.usage.timing.map((t) => (t === "morning" ? "朝" : "夜")).join("・") : "未確認"))}</tbody></table></div>`;
}
function otherStepMarkup(o) {
  if (!o?.products?.length) return "";
  const price = (p) =>
    p.price_jpy == null
      ? "価格は未確認"
      : `¥${Number(p.price_jpy).toLocaleString()}（税込・検索時点）`;
  return `<div class="block-heading"><h2>ほかのアイテムで、検討できること。</h2><span>ANOTHER STEP</span></div><div class="other-step"><p>${esc(o.message)}</p><ul>${o.products
    .map(
      (p) =>
        `<li><span class="micro">${esc(p.brand)}</span><strong>${esc(p.name)}</strong><span>${esc(price(p))}</span><span>${esc(o.direction_label)}の成分：${esc((p.ingredients || []).join("、"))}</span>${link(p.source, "検索で確認した出典")}</li>`,
    )
    .join(
      "",
    )}</ul>${o.cautions ? `<p class="note">成分の資料に書かれた注意：${esc(o.cautions)}</p>${link(o.caution_source, "資料の出典")}` : ""}<p class="note">${esc(o.note)}</p></div>`;
}
// 手持ちのステップ × 方向性の表。各行に全成分の出典と確認範囲を付ける
function shelfTable(analysis) {
  const dirs = analysis.coverage || [];
  const products = [...analysis.products].sort(
    (a, b) => (ORDER[a.category] ?? 9) - (ORDER[b.category] ?? 9),
  );
  const scope = (p) =>
    !p.ingredients_available
      ? "未確認"
      : p.ingredients_complete
        ? "全体を確認"
        : "一部のみ確認";
  const cell = (p, d) => {
    const names = [
      ...new Set(
        (p.directions_found || [])
          .filter((h) => h.direction_id === d.direction_id)
          .map((h) => h.name),
      ),
    ];
    return names.length ? esc(names.join("、")) : "—";
  };
  return `<div class="comparison-wrap" tabindex="0" role="region" aria-label="手持ちの成分の表。スマホでは横にスクロールできます"><table class="comparison-table shelf-table"><caption>手持ちの全成分表示で確認できた成分。横にスクロールできます。</caption><thead><tr><th scope="col">手持ち</th>${dirs.map((d) => `<th scope="col">${esc(d.label)}</th>`).join("")}<th scope="col">有効成分</th><th scope="col">全成分の確認</th></tr></thead><tbody>${products
    .map(
      (p) =>
        `<tr class="${p.replaced ? "replaced" : ""}"><th scope="row"><span class="micro">${esc(CATEGORY[p.category] || "その他")}</span><span class="table-name">${esc([p.brand, p.name].filter(Boolean).join(" "))}</span>${p.replaced ? '<span class="replace-badge">入れ替え予定</span>' : ""}</th>${dirs.map((d) => `<td>${cell(p, d)}</td>`).join("")}<td>${esc((p.active_ingredients || []).join("、") || "明記を確認できず")}</td><td>${esc(scope(p))}${link(p.ingredient_source, "全成分の出典")}</td></tr>`,
    )
    .join("")}</tbody></table></div>`;
}
function renderOwnedAnalysis(result) {
  const analysis = result.owned_analysis,
    logs = result.research_log || [];
  let html = "";
  if (!result.is_preview && analysis?.products?.length) {
    html = `<div class="block-heading"><h2>今のケアとのつながり。</h2><span>ON YOUR SHELF</span></div><p class="note">手持ちの表示で確認できた成分です。「見当たらない」は、肌に不足しているという意味ではありません。</p>${shelfTable(analysis)}${analysis.replaced_product_ids?.length ? '<p class="note">下の確認結果は、「入れ替え予定」の手持ちを除いたセットで判断しています。</p>' : ""}<div class="coverage-grid">`;
    html += (analysis.coverage || [])
      .map(
        (c) =>
          `<div class="coverage-card"><h3>${esc(c.label)}</h3><span class="coverage-status">${{ found: "手持ちで確認", not_found: "表示では見当たらず", unknown: "一部未確認" }[c.status] || "未確認"}</span><p>${esc((c.ingredients || []).join("、") || c.note)}</p></div>`,
      )
      .join("");
    html += "</div>";
  }
  if (
    logs.length ||
    result.research_notes?.length ||
    result.ranking?.excluded?.length
  ) {
    html +=
      '<details class="research-details"><summary>調べた内容と出典・候補から外れた理由</summary>';
    html += (result.research_notes || [])
      .map((n) => `<p class="note">${esc(n)}</p>`)
      .join("");
    html += (result.ranking?.excluded || [])
      .map((e) => `<p class="note">${esc(e.name)}：${esc(e.reason)}</p>`)
      .join("");
    html += logs
      .map(
        (l) =>
          `<article class="research-log-item"><h4>${esc(l.target)}</h4><p>${esc(l.summary)}</p><ul>${(l.details || []).map((d) => `<li>${esc(d)}</li>`).join("")}</ul>${(l.sources || []).map((s) => link(s)).join("")}</article>`,
      )
      .join("");
    html += "</details>";
  }
  $("owned-analysis").innerHTML = html;
}
function renderSuggestions(suggestions) {
  const container = $("search-suggestions");
  container.replaceChildren();
  show("search-suggestions", suggestions.length > 0);
  suggestions.slice(0, 3).forEach((html) => {
    const iframe = document.createElement("iframe");
    iframe.title = "Google検索の検索候補";
    iframe.setAttribute(
      "sandbox",
      "allow-popups allow-popups-to-escape-sandbox",
    );
    iframe.srcdoc = `<!doctype html><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src https: data:; base-uri 'none'; form-action 'none'"><base target="_blank">${html}`;
    container.append(iframe);
  });
}
function routineSteps(steps) {
  return steps?.length
    ? `<ol class="routine-steps">${steps.map((s, i) => `<li class="routine-step ${s.is_new ? "new" : ""}"><span class="routine-step-number">${String(i + 1).padStart(2, "0")}</span>${mediaSrc(s.media) ? `<img src="${esc(mediaSrc(s.media))}" alt="" referrerpolicy="no-referrer" width="45" height="54">` : ""}<div><small>${esc(CATEGORY[s.category])} / ${esc(s.brand)}</small><strong>${esc(s.name)}</strong></div>${s.is_new ? '<span class="new-label">＋ NEW</span>' : ""}</li>`).join("")}</ol>`
    : '<p class="empty-shelf">配置できるアイテムはありません。</p>';
}
function renderRoutines() {
  const result = state.currentResult,
    plans = result?.routines || [];
  const proposed = plans.find(
      (r) => r.product_id === state.currentRoutineProductId,
    ),
    current = plans.find((r) => r.product_id === null);
  const plan = state.routineView === "current" ? current : proposed;
  const container = $("routines-container");
  show(
    "routine-adopt-banner",
    state.selectedProductId === state.currentRoutineProductId,
  );
  $("routine-adopt-banner").textContent =
    "この組み合わせを選びました。比較を見直して、別の組み合わせを選ぶこともできます。";
  $("btn-adopt").disabled = !proposed;
  $("btn-adopt").textContent =
    state.selectedProductId === state.currentRoutineProductId
      ? "この組み合わせを選択中 ✓"
      : "この組み合わせを選ぶ ✓";
  if (!plan) {
    container.innerHTML =
      '<p class="soft-note">使い方の案を確認できませんでした。商品の比較に戻ってください。</p>';
    return;
  }
  container.innerHTML = `${result.is_preview ? '<p class="soft-note">手持ち未入力のサンプルです。選んだ商品だけの配置を表示しています。</p>' : ""}<div class="routine-tabs" role="group" aria-label="使い方の比較"><button data-view="current" aria-pressed="${state.routineView === "current"}">いまの組み合わせ</button><button data-view="proposed" aria-pressed="${state.routineView === "proposed"}">${proposed?.diff?.some((d) => d.type === "remove") ? "入れ替えると" : "1本を加えると"}</button></div><div class="routine-grid"><div class="routine-column"><h2>朝のケア <small>${plan.plan.morning.length}ステップ</small></h2>${routineSteps(plan.plan.morning)}</div><div class="routine-column"><h2>夜のケア <small>${plan.plan.night.length}ステップ</small></h2>${routineSteps(plan.plan.night)}</div></div>${plan.unplaced?.length ? `<div class="unplaced"><h3>使う時間帯の確認待ち</h3><p class="note">朝夜の用法がわからないため、自動では配置していません。</p>${routineSteps(plan.unplaced)}</div>` : ""}<ul class="routine-notes">${(plan.notes || []).map((n) => `<li>${esc(n)}</li>`).join("")}<li>この図は使う順番の目安です。併用の安全性や使用頻度を判定するものではありません。</li></ul>${
    plan.diff?.length
      ? `<details class="research-details"><summary>変わること・そのまま残ること</summary>${plan.diff
          .map((d) => {
            // 入れ替えで外す手持ちは新しい配置に無いので、今の配置から名前を探す
            const step = [plan, current]
              .filter(Boolean)
              .flatMap((r) => [
                ...r.plan.morning,
                ...r.plan.night,
                ...(r.unplaced || []),
              ])
              .find((s) => s.product_id === d.product_id);
            return `<p class="note">${{ add: "追加", keep: "維持", remove: "入れ替え（外す）", move: "移動" }[d.type] || "維持"} · ${esc(step?.name || d.product_id)}（${{ both: "朝・夜", morning: "朝", night: "夜", unplaced: "確認待ち" }[d.slot]}）：${esc(d.reason)}</p>`;
          })
          .join("")}</details>`
      : ""
  }`;
  container.querySelectorAll("[data-view]").forEach((b) =>
    b.addEventListener("click", () => {
      state.routineView = b.dataset.view;
      renderRoutines();
    }),
  );
  container
    .querySelectorAll(".routine-step img")
    .forEach((img) => img.addEventListener("error", () => img.remove()));
}
$("btn-adopt").addEventListener("click", () => {
  state.selectedProductId = state.currentRoutineProductId;
  state.routineView = "proposed";
  renderRoutines();
  renderFlow();
  $("routine-adopt-banner").scrollIntoView({
    block: "start",
    behavior: scrollBehavior(),
  });
});
fetchJSON("/api/health", { signal: AbortSignal.timeout(10000) })
  .then((data) => {
    if (data.stub) {
      $("service-banner").textContent =
        "画面確認モード · 相談・調査には検証用データを使います。比較サンプルでは登録済みの商品を表示します。";
      show("service-banner");
    }
  })
  .catch(() => {});
window.addEventListener("pagehide", () => {
  cancelRequest();
  if (state.photoUrl) URL.revokeObjectURL(state.photoUrl);
});

$("hero-start").addEventListener("click", (e) => {
  e.preventDefault();
  beginEdit("intake");
});
renderFlow();
