// Pure JS tests: fake DOM and fetch, no browser or external services.
import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
const code = await readFile(new URL("../web/app.js", import.meta.url), "utf8");
function runtime(
  fetchOverride = async () => {
    throw new Error("Unexpected API request");
  },
) {
  const elements = new Map();
  let document;
  function element(id = "") {
    if (id && elements.has(id)) return elements.get(id);
    const classes = new Set();
    const node = {
      id,
      dataset: {},
      value: "",
      checked: false,
      disabled: false,
      textContent: "",
      innerHTML: "",
      listeners: {},
      attributes: {},
      children: [],
      classList: {
        add(name) {
          classes.add(name);
        },
        remove(name) {
          classes.delete(name);
        },
        toggle(name, on) {
          if (on) classes.add(name);
          else classes.delete(name);
        },
        contains: (name) => classes.has(name),
      },
      addEventListener(event, handler) {
        this.listeners[event] = handler;
      },
      setAttribute(key, value) {
        this.attributes[key] = value;
      },
      querySelector: () => element(),
      querySelectorAll: () => [],
      closest: () => null,
      replaceChildren() {
        this.children = [];
      },
      append(child) {
        this.children.push(child);
      },
      prepend() {},
      focus() {
        document.activeElement = this;
      },
      scrollIntoView(options) {
        this.lastScroll = options;
      },
      getBoundingClientRect: () => ({ top: 0 }),
    };
    if (id) elements.set(id, node);
    return node;
  }
  document = {
    getElementById: element,
    querySelectorAll: () => [],
    createElement: () => element(),
    activeElement: null,
    documentElement: Object.assign(element("html"), { scrollHeight: 10000 }),
  };
  const context = vm.createContext({
    document,
    window: {
      addEventListener() {},
      removeEventListener() {},
      matchMedia: () => ({ matches: false }),
      scrollY: 0,
      innerHeight: 900,
      scrollTo({ top }) {
        this.scrollY = top;
      },
      requestAnimationFrame() {
        return 1;
      },
      cancelAnimationFrame() {},
    },
    structuredClone,
    URL,
    AbortController,
    AbortSignal,
    TextDecoder,
    TextEncoder,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    fetch: async (url, ...args) =>
      url === "/api/health"
        ? { ok: true, json: async () => ({ ok: true }) }
        : fetchOverride(url, ...args),
  });
  vm.runInContext(code, context);
  return context;
}
function streamResponse(chunks) {
  let i = 0;
  return {
    ok: true,
    body: {
      getReader: () => ({
        read: async () =>
          i < chunks.length
            ? { done: false, value: chunks[i++] }
            : { done: true },
        releaseLock() {},
      }),
    },
  };
}
test("stream parser keeps Japanese text split across byte chunks and final line without newline", async () => {
  const source =
    '{"type":"progress","node":"owned_research"}\n{"type":"result","result":{"status":"RECOMMENDATION_READY","message":"肌の調査"}}';
  const bytes = new TextEncoder().encode(source);
  const chunks = Array.from(bytes, (b) => new Uint8Array([b]));
  const ctx = runtime(async () => streamResponse(chunks));
  const result = await vm.runInContext(
    "recommendStream({}, undefined, ()=>{})",
    ctx,
  );
  assert.equal(result.message, "肌の調査");
});
test("a stream with no result is an error, never a permanent progress screen", async () => {
  const ctx = runtime(async () =>
    streamResponse([
      new TextEncoder().encode('{"type":"progress","node":"explain"}\n'),
    ]),
  );
  await assert.rejects(
    vm.runInContext("recommendStream({}, undefined, ()=>{})", ctx),
    /通信が切れました/,
  );
});
test("a failed HTTP request is recoverable", async () => {
  const ctx = runtime(async () => ({ ok: false, status: 429 }));
  await assert.rejects(
    vm.runInContext("recommendStream({}, undefined, ()=>{})", ctx),
    /調査を開始できません/,
  );
});
test("search data is escaped, including attribute quote delimiters", () => {
  const ctx = runtime();
  ctx.input = '<img src=x onerror="alert(1)">\'';
  const output = vm.runInContext("esc(input)", ctx);
  assert(!output.includes("<"));
  assert(!output.includes('"'));
  assert(!output.includes("'"));
});
test("source links reject scripts and local executable schemes", () => {
  const ctx = runtime();
  for (const url of [
    "javascript:alert(1)",
    "data:text/html,x",
    "file:///tmp/private",
  ]) {
    ctx.input = url;
    assert.equal(vm.runInContext("safeURL(input)", ctx), null);
  }
  ctx.input = "https://example.com/product";
  assert.equal(vm.runInContext("safeURL(input)", ctx), ctx.input);
});
test("product photos accept saved assets and https images only", () => {
  const ctx = runtime();
  const card = (media) => {
    ctx.input = { brand: "B", name: "Serum", category: "serum", media };
    return vm.runInContext("mediaMarkup(input, 1)", ctx);
  };
  const yahoo = card({
    src: "https://item-shopping.c.yimg.jp/i/l/x",
    source_url: "https://store.shopping.yahoo.co.jp/x.html",
    credit: "Yahoo!ショッピング",
    provider: "yahoo",
  });
  assert.match(
    yahoo,
    /<img src="https:\/\/item-shopping\.c\.yimg\.jp\/i\/l\/x"/,
  );
  assert.match(yahoo, /referrerpolicy="no-referrer"/);
  assert.match(
    yahoo,
    /href="https:\/\/store\.shopping\.yahoo\.co\.jp\/x\.html"/,
  );
  assert.match(yahoo, /Yahoo!ショッピングで見る/);
  assert(!yahoo.includes("is-small"));
  const rakuten = card({
    src: "https://thumbnail.image.rakuten.co.jp/x.jpg?_ex=128x128",
    source_url: "https://item.rakuten.co.jp/shop/x/",
    credit: "楽天市場",
    provider: "rakuten",
  });
  assert.match(rakuten, /class="is-small"/);
  assert.match(rakuten, /楽天市場で見る/);
  // 楽天の画像の枠には楽天へのリンクだけを置く
  assert.deepEqual(
    [...rakuten.matchAll(/href="([^"]+)"/g)].map((m) => m[1]),
    ["https://item.rakuten.co.jp/shop/x/"],
  );
  const registered = card({
    src: "/assets/products/chifure-rich.png",
    source_url: "https://www.chifure.co.jp/products/essence/2634",
    credit: "ちふれ 公式サイト",
  });
  assert.match(registered, /src="\/assets\/products\/chifure-rich\.png"/);
  assert.match(registered, /ちふれ 公式サイト/);
  for (const src of [
    "http://example.com/x.jpg",
    "javascript:alert(1)",
    "data:image/png;base64,AA",
    "/assets/products/../secret.png",
  ]) {
    const html = card({ src, source_url: "https://example.com", credit: "c" });
    assert(!html.includes("<img"), src);
    assert.match(html, /商品写真は未確認です/);
  }
});
test("routine thumbnails use the same photo rules", () => {
  const ctx = runtime();
  ctx.input = [
    {
      brand: "B",
      name: "Serum",
      category: "serum",
      media: {
        src: "https://item-shopping.c.yimg.jp/i/l/x",
        provider: "yahoo",
      },
    },
    {
      brand: "B",
      name: "Lotion",
      category: "lotion",
      media: { src: "javascript:alert(1)" },
    },
  ];
  const html = vm.runInContext("routineSteps(input)", ctx);
  assert.equal((html.match(/<img /g) || []).length, 1);
  assert.match(html, /referrerpolicy="no-referrer"/);
});
test("only registered photos are labelled as the official product page", () => {
  const ctx = runtime();
  const linkFor = (media) => {
    ctx.input = {
      media,
      price_source: { url: "https://maker.example/price", title: "maker" },
    };
    return vm.runInContext("productPageLink(input)", ctx);
  };
  assert.match(
    linkFor({
      src: "/assets/products/a.png",
      source_url: "https://maker.example/p",
      credit: "c",
    }),
    /公式の商品ページ/,
  );
  const shop = linkFor({
    src: "https://item-shopping.c.yimg.jp/i/l/x",
    source_url: "https://store.shopping.yahoo.co.jp/x.html",
    credit: "Yahoo!ショッピング",
    provider: "yahoo",
  });
  assert.match(shop, /商品の情報を見る/);
  assert.match(shop, /maker\.example\/price/);
  assert.match(linkFor(null), /商品の情報を見る/);
});
test("stickiness is not silently prioritized when the user did not request it", () => {
  const ctx = runtime();
  assert.equal(
    vm.runInContext("JSON.stringify(defaultPriorities())", ctx),
    '["concern","price"]',
  );
  vm.runInContext(
    'state.conditions={texture_preferences:[{aspect:"stickiness",preference:"avoid"}]}',
    ctx,
  );
  assert.equal(
    vm.runInContext("JSON.stringify(defaultPriorities())", ctx),
    '["concern","stickiness","price"]',
  );
});

function run(ctx, source) {
  return vm.runInContext(source, ctx);
}
function seedResult(ctx) {
  run(
    ctx,
    `
    state.conditions = {...emptyConditions(), concern_label:"乾燥", concern_note:null, keep_note:null};
    state.confirmedConditions = structuredClone(state.conditions);
    state.ownedItems = [{brand:"Brand",name:"Lotion",category:"lotion",keep:true}];
    state.confirmedInventory = structuredClone(inventoryValue());
    state.currentResult = {status:"RECOMMENDATION_READY",candidates:[{product_id:"one",brand:"B",name:"Serum"}]};
    state.currentRoutineProductId = "one";
    state.selectedProductId = "one";
    state.screen = "routines";
  `,
  );
}
test("completed steps stay above the only expanded step", () => {
  const ctx = runtime();
  seedResult(ctx);
  const layout = run(ctx, "flowLayout(state)");
  assert(layout.intake.visible && !layout.intake.open);
  assert(layout.inventory.visible && !layout.inventory.open);
  assert(layout.candidates.visible && !layout.candidates.open);
  assert(layout.routines.visible && layout.routines.open);
  assert.equal(layout.progress.visible, false);
});
test("preview does not mark the user inputs complete or reveal inventory", () => {
  const ctx = runtime();
  run(ctx, 'state.currentResult={is_preview:true}; state.screen="candidates"');
  const layout = run(ctx, "flowLayout(state)");
  assert.match(layout.intake.status, /未入力/);
  assert.equal(layout.inventory.visible, false);
  assert.equal(layout.candidates.visible, true);
});
test("editing earlier input hides all downstream controls", () => {
  const ctx = runtime();
  seedResult(ctx);
  run(ctx, 'beginEdit("intake")');
  const layout = run(ctx, "flowLayout(state)");
  assert.equal(layout.intake.open, true);
  for (const step of ["inventory", "progress", "candidates", "routines"])
    assert.equal(layout[step].visible, false);
  assert.equal(run(ctx, "state.selectedProductId"), "one");
});
test("unchanged conditions resume the selected routine and preserve priorities", () => {
  const ctx = runtime();
  seedResult(ctx);
  run(
    ctx,
    'state.currentPriorities=["stickiness","concern","price"]; beginEdit("intake")',
  );
  assert.equal(
    run(ctx, "commitConditions(structuredClone(state.conditions))"),
    "routines",
  );
  assert.equal(run(ctx, "state.selectedProductId"), "one");
  assert.equal(run(ctx, "state.currentPriorities[0]"), "stickiness");
});
test("changed conditions invalidate the result but keep owned input", () => {
  const ctx = runtime();
  seedResult(ctx);
  run(ctx, 'beginEdit("intake")');
  assert.equal(
    run(ctx, "commitConditions({...state.conditions,budget_jpy_max:1500})"),
    "inventory",
  );
  assert.equal(run(ctx, "state.currentResult"), null);
  assert.equal(run(ctx, "state.selectedProductId"), null);
  assert.equal(run(ctx, "state.confirmedInventory"), null);
  assert.equal(run(ctx, "state.ownedItems[0].name"), "Lotion");
});
test("unchanged inventory restores result without a recommendation request", async () => {
  let calls = 0;
  const ctx = runtime(async () => {
    calls++;
    throw new Error("must reuse");
  });
  seedResult(ctx);
  run(ctx, 'beginEdit("inventory")');
  await run(
    ctx,
    'document.getElementById("btn-start-recommend").listeners.click()',
  );
  assert.equal(calls, 0);
  assert.equal(run(ctx, "state.screen"), "routines");
  assert.equal(run(ctx, "state.selectedProductId"), "one");
});
test("changing the keep choice invalidates old recommendations", () => {
  const ctx = runtime();
  seedResult(ctx);
  run(ctx, 'beginEdit("inventory"); state.ownedItems[0].keep=false');
  assert.equal(run(ctx, "commitInventory()"), null);
  assert.equal(run(ctx, "state.currentResult"), null);
  assert.equal(run(ctx, "state.confirmedInventory.owned_items[0].keep"), false);
});
test("cancel editing restores input, selection, and previous expanded step", () => {
  const ctx = runtime();
  seedResult(ctx);
  run(
    ctx,
    'beginEdit("inventory"); state.ownedItems[0].name="Changed"; state.ownedItems.push({brand:"",name:"Extra",category:"other",keep:false}); cancelEdit()',
  );
  assert.equal(run(ctx, "state.ownedItems.length"), 1);
  assert.equal(run(ctx, "state.ownedItems[0].name"), "Lotion");
  assert.equal(run(ctx, "state.selectedProductId"), "one");
  assert.equal(run(ctx, "state.screen"), "routines");
});
test("editing is blocked while research is running, cancellation keeps the input", () => {
  const ctx = runtime();
  seedResult(ctx);
  run(
    ctx,
    'state.screen="progress"; state.busy=true; state.request=new AbortController(); beginEdit("intake")',
  );
  assert.equal(run(ctx, "state.screen"), "progress");
  run(ctx, 'document.getElementById("btn-cancel").listeners.click()');
  assert.equal(run(ctx, "state.screen"), "inventory");
  assert.equal(run(ctx, "state.ownedItems[0].name"), "Lotion");
  assert.equal(run(ctx, "state.busy"), false);
});
test("reduced motion uses an instant scroll and keeps focus on the destination", () => {
  const ctx = runtime();
  run(ctx, 'window.matchMedia=()=>({matches:true}); showSection("intake")');
  assert.equal(
    run(
      ctx,
      'document.getElementById("step-heading-intake").lastScroll.behavior',
    ),
    "instant",
  );
  assert.equal(run(ctx, "document.activeElement.id"), "step-heading-intake");
});
test("automatic results do not move focus away from the stable research anchor", () => {
  const ctx = runtime();
  seedResult(ctx);
  run(ctx, 'showSection("progress"); showSection("candidates",{scroll:false})');
  assert.equal(run(ctx, "document.activeElement.id"), "research-stage");
});
test("a late parsed response cannot overwrite conditions after cancelling an edit", async () => {
  let resolve;
  const ctx = runtime(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  seedResult(ctx);
  run(
    ctx,
    'beginEdit("intake"); document.getElementById("intake-text").value="別の希望"',
  );
  const pending = run(
    ctx,
    'document.getElementById("btn-parse-intake").listeners.click()',
  );
  run(ctx, "cancelEdit()");
  resolve({
    ok: true,
    json: async () => ({
      conditions: { concern_label: "遅い回答" },
      follow_up_questions: [],
    }),
  });
  await pending;
  assert.equal(run(ctx, "state.conditions.concern_label"), "乾燥");
  assert.equal(run(ctx, "state.screen"), "routines");
});

function seedScrollGeometry(ctx, previous = "intake", next = "inventory") {
  ctx.previousStep = previous;
  ctx.nextStep = next;
  run(
    ctx,
    `
    state.screen = previousStep;
    state.confirmedConditions = {...emptyConditions(),concern_label:"乾燥"};
    renderFlow();
    window.scrollY = 1000;
    const scrollTarget = nextStep === "progress" ? document.getElementById("research-stage") : document.getElementById("step-heading-" + nextStep);
    scrollTarget.getBoundingClientRect = () => ({top:(document.getElementById("step-body-" + previousStep).classList.contains("hidden") ? 700 : 2500) - window.scrollY});
    scrollTarget.scrollIntoView = function(options) { this.lastScroll = options; this.scrollDestination = window.scrollY + this.getBoundingClientRect().top - 52; };
  `,
  );
}
test("forward navigation scrolls down before folding the previous input", () => {
  const ctx = runtime();
  seedScrollGeometry(ctx);
  run(ctx, 'showSection("inventory")');
  assert.equal(
    run(
      ctx,
      'document.getElementById("step-body-intake").classList.contains("hidden")',
    ),
    false,
  );
  assert.equal(
    run(ctx, 'document.getElementById("section-intake").inert'),
    true,
  );
  assert(
    run(
      ctx,
      'document.getElementById("step-heading-inventory").scrollDestination > window.scrollY',
    ),
  );
  run(ctx, "window.scrollY=2448; forwardTransition.check()");
  assert.equal(
    run(
      ctx,
      'document.getElementById("step-body-intake").classList.contains("hidden")',
    ),
    true,
  );
  assert.equal(
    run(
      ctx,
      'document.getElementById("step-heading-inventory").getBoundingClientRect().top',
    ),
    52,
  );
  assert.equal(run(ctx, "forwardTransition"), null);
});
test("interrupting a downward scroll does not force a premature fold", () => {
  const ctx = runtime();
  seedScrollGeometry(ctx);
  run(
    ctx,
    'showSection("inventory"); window.scrollY=1300; forwardTransition.check()',
  );
  assert.equal(
    run(
      ctx,
      'document.getElementById("step-body-intake").classList.contains("hidden")',
    ),
    false,
  );
  assert.equal(run(ctx, "window.scrollY"), 1300);
  run(ctx, "window.scrollY=2448; forwardTransition.check()");
  assert.equal(
    run(
      ctx,
      'document.getElementById("step-heading-inventory").getBoundingClientRect().top',
    ),
    52,
  );
});
test("an immediate result keeps the in-flight downward transition intact", () => {
  const ctx = runtime();
  seedScrollGeometry(ctx, "inventory", "progress");
  run(
    ctx,
    'showSection("progress"); state.currentResult={status:"RECOMMENDATION_READY"}; showSection("candidates",{scroll:false})',
  );
  assert.equal(run(ctx, "forwardTransition.step"), "inventory");
  assert.equal(
    run(
      ctx,
      'document.getElementById("step-body-inventory").classList.contains("hidden")',
    ),
    false,
  );
  run(ctx, "window.scrollY=2448; forwardTransition.check()");
  assert.equal(
    run(
      ctx,
      'document.getElementById("research-stage").getBoundingClientRect().top',
    ),
    52,
  );
  assert.equal(run(ctx, "document.activeElement.id"), "research-stage");
});
