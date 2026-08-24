/* HotGraph — token bubbles with holder bubbles orbiting them.
 *
 * Radii use sqrt(value) so a bubble's AREA is proportional to what it
 * represents; scaling the radius directly would make a 10x market cap look
 * 100x bigger.
 */

const svg = d3.select("#graph");
const tip = d3.select("#tip");

// Surface script errors in the header instead of failing silently to a blank
// canvas — a broken render otherwise looks identical to "no data".
window.addEventListener("error", (e) => {
  const el = document.getElementById("stat");
  if (el) el.textContent = `js error: ${e.message}`;
  document.title = `ERR ${e.message}`;
});

const root = svg.append("g");
const gLinks = root.append("g").attr("class", "links");
const gNodes = root.append("g").attr("class", "nodes");

const PALETTE = [
  "#f97316", "#38bdf8", "#a78bfa", "#4ade80", "#f472b6",
  "#facc15", "#fb7185", "#2dd4bf", "#c084fc", "#60a5fa",
];
const personColor = (() => {
  const seen = new Map();
  return (name) => {
    if (!seen.has(name)) seen.set(name, PALETTE[seen.size % PALETTE.length]);
    return seen.get(name);
  };
})();

/* ---------- formatting ---------- */

const fmtUsd = (v) => {
  if (v == null) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `$${(v / 1e3).toFixed(1)}K`;
  return `$${v.toFixed(2)}`;
};
const fmtPct = (v) => (v == null ? "—" : `${v.toFixed(v < 0.1 ? 4 : 2)}%`);
const fmtAgo = (ts) => {
  if (!ts) return "—";
  const s = Date.now() / 1000 - ts;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
};

/* ---------- state ---------- */

let sim = null;
let currentData = { nodes: [], links: [] };
let tickCount = 0;

const controls = {
  chain: document.getElementById("chain"),
  includeSold: document.getElementById("includeSold"),
  minMcap: document.getElementById("minMcap"),
  minPct: document.getElementById("minPct"),
  topN: document.getElementById("topN"),
  sortBy: document.getElementById("sortBy"),
  window: document.getElementById("window"),
};

// A token with no known ticker falls back to an address-ish key — shorten it.
const displaySymbol = (s) => {
  if (!s) return "?";
  return s.length > 14 ? `${s.slice(0, 6)}…${s.slice(-4)}` : s;
};

// The mcap slider is logarithmic — most tokens sit under $1M but the range
// needs to reach $10M+, and a linear slider would bunch them all at one end.
const mcapValue = () => {
  const v = +controls.minMcap.value;
  return v <= 0 ? 0 : Math.pow(10, v);
};

function syncLabels() {
  const m = mcapValue();
  document.getElementById("minMcapVal").textContent = m ? fmtUsd(m) : "$0";
  document.getElementById("minPctVal").textContent = `${(+controls.minPct.value).toFixed(2)}%`;
}

/* ---------- sizing ---------- */

function radiusScales(nodes) {
  const tokens = nodes.filter((n) => n.kind === "token");
  const people = nodes.filter((n) => n.kind === "person");

  const tokenMax = d3.max(tokens, (d) => d.value) || 1;
  const personMax = d3.max(people, (d) => d.value) || 1;

  const rToken = d3.scaleSqrt().domain([0, tokenMax]).range([39, 117]).clamp(true);
  const rPerson = d3.scaleSqrt().domain([0, personMax]).range([10.5, 51]).clamp(true);

  return (d) => (d.kind === "token" ? rToken(d.value) : rPerson(d.value));
}

/* ---------- tooltip ---------- */

function tooltipHtml(d) {
  if (d.kind === "token") {
    const rows = [
      ["chain", d.chain],
      ["market cap", fmtUsd(d.mcap_usd)],
      ["mcap seen", fmtAgo(d.mcap_as_of)],
      ["holding now", `${d.n_holders} of ${d.n_positions}`],
      ["last action", fmtAgo(d.last_action)],
      ["alerts", d.n_events],
    ];
    let warn = d.resolved
      ? ""
      : `<div class="warn">Ticker-keyed — no contract address seen yet, so
         same-ticker tokens could merge.</div>`;
    if (d.dead) warn += `<div class="warn">Everyone tracked has exited this token.</div>`;
    return `<h4>${displaySymbol(d.symbol)}</h4>
      ${d.name ? `<div style="color:#8b98ad;margin:-3px 0 6px">${d.name}</div>` : ""}
      <table>${rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("")}</table>
      ${warn}`;
  }

  const pnl = d.pnl_usd;
  const pnlCell =
    pnl == null ? "—" : `<span class="${pnl >= 0 ? "pos" : "neg"}">${fmtUsd(pnl)}</span>`;

  const rows = [
    ["status", d.status],
    ["holds now", fmtPct(d.pct_supply)],
    ["peak held", fmtPct(d.peak_pct)],
    ["bought", fmtPct(d.bought_pct)],
    ["sold", fmtPct(d.sold_pct)],
    ["invested", fmtUsd(d.invested_usd)],
    ["realized", fmtUsd(d.realized_usd)],
    ["pnl", pnlCell],
    ["entry mcap", fmtUsd(d.entry_mcap_usd)],
    ["alerts", d.n_events],
    ["last seen", fmtAgo(d.last_seen)],
  ];

  const warn =
    d.confidence === "low"
      ? `<div class="warn">Estimated — some alerts were missing a supply %,
         or a sell had no matching buy in our history.</div>`
      : "";

  return `<h4>${d.person}${d.handle ? ` <span style="color:#8b98ad">@${d.handle}</span>` : ""}</h4>
    <table>${rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("")}</table>
    ${warn}`;
}

function showTip(event, d) {
  tip.attr("hidden", null).html(tooltipHtml(d));
  moveTip(event);
}

function moveTip(event) {
  const pad = 14;
  const node = tip.node();
  const w = node.offsetWidth;
  const h = node.offsetHeight;
  let x = event.clientX + pad;
  let y = event.clientY + pad;
  if (x + w > window.innerWidth - 8) x = event.clientX - w - pad;
  if (y + h > window.innerHeight - 8) y = event.clientY - h - pad;
  tip.style("left", `${x}px`).style("top", `${y}px`);
}

const hideTip = () => tip.attr("hidden", true);

/* ---------- render ---------- */

function render(data) {
  currentData = data;
  const { width, height } = svg.node().getBoundingClientRect();

  document.querySelectorAll(".empty").forEach((el) => el.remove());
  if (!data.nodes.length) {
    gLinks.selectAll("*").remove();
    gNodes.selectAll("*").remove();
    showEmpty(data);
    return;
  }

  const radius = radiusScales(data.nodes);
  data.nodes.forEach((n) => {
    n.r = radius(n);
    if (n.kind === "person" && !n.color) n.color = personColor(n.person);
  });

  // Links reference node ids; d3 mutates them into object refs.
  const links = data.links.map((l) => ({ ...l }));

  const link = gLinks
    .selectAll("line")
    .data(links, (d) => `${d.source}|${d.target}`)
    .join("line")
    .attr("class", (d) => `link ${d.status === "SOLD" ? "sold" : ""}`);

  const node = gNodes
    .selectAll("g.node")
    .data(data.nodes, (d) => d.id)
    .join((enter) => {
      const g = enter.append("g").attr("class", "node");
      g.append("circle");
      g.append("text").attr("class", "label");
      g.append("text").attr("class", "label sub");
      return g;
    });

  node
    .select("circle")
    .attr("r", (d) => d.r)
    .attr("class", (d) => {
      const cls = ["bubble", d.kind];
      if (d.status === "SOLD") cls.push("sold");
      if (d.dead) cls.push("dead");
      if (d.confidence === "low" || d.resolved === false) cls.push("low");
      return cls.join(" ");
    })
    .attr("fill", (d) =>
      d.kind === "token" ? null : d3.color(d.color).copy({ opacity: 0.28 })
    )
    .attr("stroke", (d) => (d.kind === "token" ? null : d.color));

  node
    .select("text.label:not(.sub)")
    .attr("class", (d) =>
      `label ${d.kind === "token" ? "token" : ""} ${d.status === "SOLD" || d.dead ? "faded" : ""}`
    )
    .attr("dy", (d) => (d.kind === "token" ? "0.02em" : "-0.05em"))
    .text((d) => {
      if (d.kind === "token") return displaySymbol(d.symbol);
      // Hide the name on bubbles too small to fit it.
      return d.r >= 15 ? d.person : "";
    });

  node
    .select("text.label.sub")
    .attr("class", (d) => `label sub ${d.status === "SOLD" || d.dead ? "faded" : ""}`)
    .attr("dy", "1.15em")
    .text((d) => {
      if (d.kind === "token") return fmtUsd(d.mcap_usd);
      if (d.r < 15) return "";
      const v = d.status === "SOLD" ? d.peak_pct : d.pct_supply;
      return d.status === "SOLD" ? `sold · ${fmtPct(v)}` : fmtPct(v);
    });

  node
    .on("mousemove", (e, d) => showTip(e, d))
    .on("mouseleave", hideTip)
    .on("click", (e, d) => {
      e.stopPropagation();
      if (d.kind === "token") selectToken(d, e.currentTarget);
      focusOn(d);
    });

  if (sim) sim.stop();
  sim = d3
    .forceSimulation(data.nodes)
    .force(
      "link",
      d3
        .forceLink(links)
        .id((d) => d.id)
        // Tight links so each holder hugs its token as a satellite rather
        // than drifting into a neighbouring cluster.
        .distance((l) => (l.target.r || 40) + (l.source.r || 12) + 6)
        .strength(1)
    )
    // Tokens push each other apart hard so clusters stay separable; people
    // barely repel, so their link dominates and keeps them in orbit.
    .force("charge", d3.forceManyBody().strength((d) => (d.kind === "token" ? -1100 : -35)))
    .force("collide", d3.forceCollide().radius((d) => d.r + 3).iterations(3))
    // Without forceCenter the layout settles around the origin, i.e. the
    // top-left corner, leaving the canvas looking empty.
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force("x", d3.forceX(width / 2).strength((d) => (d.kind === "token" ? 0.04 : 0.002)))
    .force("y", d3.forceY(height / 2).strength((d) => (d.kind === "token" ? 0.04 : 0.002)))
    .on("tick", () => {
      link
        .attr("x1", (d) => d.source.x)
        .attr("y1", (d) => d.source.y)
        .attr("x2", (d) => d.target.x)
        .attr("y2", (d) => d.target.y);
      node.attr("transform", (d) => `translate(${d.x},${d.y})`);
      updateNodeActions();

      // Re-frame off the tick counter rather than a timer. Ticks track the
      // layout's actual progress, so the view can never end up pinned to an
      // early clump that the simulation then moves away from.
      if (++tickCount % 20 === 0) fitToView();
    })
    // Settling is the only safe moment to frame: fitting earlier locks the
    // viewport onto the initial clump, and forceCenter then drags every node
    // out of view.
    .on("end", fitToView);

  tickCount = 0;

  node.call(
    d3
      .drag()
      .on("start", (e, d) => {
        if (!e.active) sim.alphaTarget(0.25).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on("drag", (e, d) => {
        d.fx = e.x;
        d.fy = e.y;
      })
      .on("end", (e, d) => {
        if (!e.active) sim.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      })
  );

  const holders = data.nodes.filter((n) => n.kind === "person");
  const tokens = data.nodes.filter((n) => n.kind === "token");
  const sold = holders.filter((n) => n.status === "SOLD").length;
  document.getElementById("stat").textContent =
    `${tokens.length} tokens · ${holders.length} positions · ${sold} sold`;

  renderTokenList();
}

function showEmpty(data) {
  const total = (data.stats && data.stats.raw_messages) || 0;
  const msg = total
    ? `No positions match these filters.<br>Try widening them, or check
       <code>config/people.yaml</code> handles.`
    : `No data yet.<br>Run <code>python -m tests.seed_demo</code> for a demo,
       or connect Telegram with <code>python -m hotgraph.tg_login</code>.`;
  svg.node().insertAdjacentHTML("afterend", `<div class="empty">${msg}</div>`);
  document.getElementById("stat").textContent = "";
}

/* ---------- interaction ---------- */

const zoom = d3
  .zoom()
  .scaleExtent([0.15, 10])
  .on("zoom", (e) => {
    // Only a real gesture counts as taking manual control — programmatic
    // transitions (fit / focus) fire this too but carry no sourceEvent.
    if (e.sourceEvent) userMovedView = true;
    root.attr("transform", e.transform);
    updateNodeActions();
  });

svg.call(zoom).on("dblclick.zoom", null);
// Double-click anywhere re-frames the whole graph.
svg.on("dblclick", () => {
  userMovedView = false;
  fitToView();
});

/* Frame every bubble once the layout settles — without this the graph sits in
 * a small clump in the middle of a mostly empty canvas.
 *
 * Fired from both the simulation's "end" event and a timer: "end" only arrives
 * once alpha decays below its threshold, which can be long after the layout is
 * visually settled (and never, if something keeps nudging alpha). */
let userMovedView = false;

function fitToView() {
  if (userMovedView) return;
  if (!currentData.nodes.length) return;
  if (!currentData.nodes.every((n) => Number.isFinite(n.x) && Number.isFinite(n.y))) return;

  const minX = d3.min(currentData.nodes, (n) => n.x - n.r);
  const maxX = d3.max(currentData.nodes, (n) => n.x + n.r);
  const minY = d3.min(currentData.nodes, (n) => n.y - n.r);
  const maxY = d3.max(currentData.nodes, (n) => n.y + n.r);
  if (![minX, maxX, minY, maxY].every(Number.isFinite)) return;

  const pad = 50;
  const w = maxX - minX + pad * 2;
  const h = maxY - minY + pad * 2;
  if (!(w > 0) || !(h > 0)) return;

  // Framing via viewBox rather than a zoom transform: preserveAspectRatio does
  // the centring and scaling for us, and it leaves the zoom transform at
  // identity so user pan/zoom still composes cleanly on top.
  svg
    .attr("viewBox", `${minX - pad} ${minY - pad} ${w} ${h}`)
    .attr("preserveAspectRatio", "xMidYMid meet");
}

function focusOn(d) {
  userMovedView = true;
  const { width, height } = svg.node().getBoundingClientRect();
  const k = d.kind === "token" ? Math.min(6.6, 660 / d.r) : 2.4;
  svg
    .transition()
    .duration(600)
    .call(
      zoom.transform,
      d3.zoomIdentity.translate(width / 2, height / 2).scale(k).translate(-d.x, -d.y)
    );
}

/* ---------- data ---------- */

async function load(refit = true) {
  syncLabels();
  // Event-handler calls pass an Event object (truthy) = deliberate action.
  if (refit) userMovedView = false; // a new filter set deserves a fresh framing
  const p = new URLSearchParams({
    include_sold: controls.includeSold.checked,
    min_mcap: mcapValue(),
    min_pct: controls.minPct.value,
    top: controls.topN.value,
    sort: controls.sortBy.value,
    since_hours: controls.window.value,
  });
  if (controls.chain.value) p.set("chain", controls.chain.value);

  try {
    const res = await fetch(`/api/graph?${p}`);
    render(await res.json());
  } catch (err) {
    document.getElementById("stat").textContent = `error: ${err.message}`;
  }
}

/* ---------- token list panel ----------
 * Built from currentData, so it always mirrors exactly what the graph shows —
 * same chain / mcap / % / top / sort filters, same order the API sorted by. */

const tokenPanel = document.getElementById("tokenPanel");
const tokenListEl = document.getElementById("tokenList");
const sortSeg = document.getElementById("sortSeg");

// Quick-sort buttons — same state as the top-bar Sort select, two ways in.
sortSeg.querySelectorAll("button").forEach((btn) => {
  btn.addEventListener("click", () => {
    controls.sortBy.value = btn.dataset.sort;
    load();
  });
});

function syncSortSeg() {
  sortSeg.querySelectorAll("button").forEach((btn) =>
    btn.classList.toggle("active", btn.dataset.sort === controls.sortBy.value)
  );
}

function renderTokenList() {
  if (tokenPanel.hidden) return;
  syncSortSeg();
  const tokens = currentData.nodes.filter((n) => n.kind === "token");
  document.getElementById("tokenListMeta").textContent =
    `${tokens.length} shown · sorted by ${controls.sortBy.selectedOptions[0].text}`;

  tokenListEl.innerHTML = "";
  tokens.forEach((t, i) => {
    const row = document.createElement("div");
    row.className = `token-row${t.dead ? " dead" : ""}`;
    row.innerHTML =
      `<div class="rank">${i + 1}</div>` +
      `<div class="sym">${displaySymbol(t.symbol)}` +
      `<span class="chain-tag">${t.chain}</span></div>` +
      `<div class="nums">${fmtUsd(t.mcap_usd)}<br>` +
      `<span class="sub">${t.dead ? "all exited" : `${t.n_holders} holding`}` +
      ` · ${fmtAgo(t.last_action)}</span></div>`;
    row.addEventListener("click", () => {
      const node = currentData.nodes.find((n) => n.id === t.id);
      if (node && Number.isFinite(node.x)) focusOn(node);
    });
    tokenListEl.append(row);
  });
}

// Reset-zoom button lives at the map's top-right; when a side panel is open
// it slides left so it never hides underneath.
const resetZoomBtn = document.getElementById("resetZoom");

function syncMapButtons() {
  let offset = 12;
  const mp = document.getElementById("mergePanel");
  if (!tokenPanel.hidden) offset += tokenPanel.offsetWidth;
  else if (mp && !mp.hidden) offset += mp.offsetWidth;
  resetZoomBtn.style.right = `${offset}px`;
}

resetZoomBtn.addEventListener("click", () => {
  userMovedView = false;
  fitToView();
});

document.getElementById("listToggle").addEventListener("click", () => {
  tokenPanel.hidden = !tokenPanel.hidden;
  if (!tokenPanel.hidden) {
    document.getElementById("mergePanel").hidden = true;
    renderTokenList();
  }
  syncMapButtons();
});
document.getElementById("listClose").addEventListener("click", () => {
  tokenPanel.hidden = true;
  syncMapButtons();
});

// Deep link: open the page with #tokens to start with the list expanded.
if (location.hash.includes("tokens")) tokenPanel.hidden = false;
syncMapButtons();

/* ---------- merge panel ---------- */

const panel = document.getElementById("mergePanel");
const traderList = document.getElementById("traderList");
const groupList = document.getElementById("groupList");
const mergeBtn = document.getElementById("mergeBtn");
const mergeName = document.getElementById("mergeName");
const traderSearch = document.getElementById("traderSearch");

const selectedKeys = new Set();

function shortKey(k) {
  if (!k) return "";
  return k.length > 26 ? `${k.slice(0, 12)}…${k.slice(-8)}` : k;
}

function updateMergeBtn() {
  mergeBtn.textContent = `Merge ${selectedKeys.size}`;
  mergeBtn.disabled = selectedKeys.size === 0 || !mergeName.value.trim();
}

async function loadTraders() {
  const q = encodeURIComponent(traderSearch.value.trim());
  const res = await fetch(`/api/traders?q=${q}&limit=200`);
  const data = await res.json();

  traderList.innerHTML = "";
  for (const t of data.traders) {
    const row = document.createElement("label");
    row.className = "trader-row";

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = selectedKeys.has(t.trader_key);
    cb.addEventListener("change", () => {
      if (cb.checked) selectedKeys.add(t.trader_key);
      else selectedKeys.delete(t.trader_key);
      // Pre-fill the name from the first selected identity's label.
      if (!mergeName.value.trim() && (t.person || t.handle)) {
        mergeName.value = t.person || t.handle;
      }
      updateMergeBtn();
    });

    const main = document.createElement("div");
    main.className = "trader-main";
    const label = t.person || t.handle || shortKey(t.trader_key);
    main.innerHTML =
      `<div class="trader-name">${label}` +
      (t.person ? `<span class="badge person">${t.person}</span>` : "") +
      `</div><div class="trader-key">${shortKey(t.trader_key)}</div>`;

    const meta = document.createElement("div");
    meta.className = "trader-meta";
    meta.innerHTML =
      `${t.n_events} alerts · ${t.n_tokens} tokens<br>` +
      t.sources.map((s) => `<span class="badge">${s.replace("bot_", "")}</span>`).join("");

    row.append(cb, main, meta);
    traderList.append(row);
  }
}

async function loadGroups() {
  const res = await fetch("/api/people");
  const data = await res.json();
  groupList.innerHTML = "";
  if (!data.people.length) {
    groupList.innerHTML = `<div class="panel-hint">No merges yet.</div>`;
  }
  for (const g of data.people) {
    const row = document.createElement("div");
    row.className = "group-row";
    const main = document.createElement("div");
    main.className = "trader-main";
    main.innerHTML =
      `<div class="trader-name">${g.person}</div>` +
      `<div class="trader-key">${g.keys.map(shortKey).join(" · ")}</div>`;
    const btn = document.createElement("button");
    btn.className = "btn small";
    btn.textContent = "Unmerge";
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      await fetch("/api/unmerge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keys: g.keys }),
      });
      await Promise.all([loadGroups(), loadTraders(), load()]);
    });
    row.append(main, btn);
    groupList.append(row);
  }
}

mergeBtn.addEventListener("click", async () => {
  const person = mergeName.value.trim();
  if (!person || !selectedKeys.size) return;
  mergeBtn.disabled = true;
  mergeBtn.textContent = "Merging…";
  await fetch("/api/merge", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ person, keys: [...selectedKeys] }),
  });
  selectedKeys.clear();
  mergeName.value = "";
  updateMergeBtn();
  await Promise.all([loadGroups(), loadTraders(), load()]);
});

mergeName.addEventListener("input", updateMergeBtn);
traderSearch.addEventListener("input", () => loadTraders());

document.getElementById("mergeToggle").addEventListener("click", () => {
  panel.hidden = !panel.hidden;
  if (!panel.hidden) {
    tokenPanel.hidden = true;
    loadTraders();
    loadGroups();
  }
  syncMapButtons();
});
document.getElementById("mergeClose").addEventListener("click", () => {
  panel.hidden = true;
  syncMapButtons();
});

Object.values(controls).forEach((el) => el.addEventListener("input", load));
document.getElementById("reload").addEventListener("click", load);
window.addEventListener("resize", () => {
  if (!sim) return;
  const { width, height } = svg.node().getBoundingClientRect();
  sim.force("center", d3.forceCenter(width / 2, height / 2)).alpha(0.3).restart();
});

/* ---------- alert sound ----------
 * WebAudio two-tone chime, generated in code — no audio file to load.
 * Browsers refuse to start audio before a user gesture, so the context is
 * created lazily and unlocked by the first click/keypress on the page. */

let soundOn = localStorage.getItem("hg_sound") !== "off";
let audioCtx = null;

const soundBtn = document.getElementById("soundToggle");

function syncSoundBtn() {
  soundBtn.textContent = soundOn ? "🔔" : "🔕";
  soundBtn.title = soundOn
    ? "sound ON for new alerts — click to mute"
    : "sound OFF — click to enable";
}
syncSoundBtn();

function ensureAudio() {
  if (!audioCtx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    audioCtx = new AC();
  }
  if (audioCtx.state === "suspended") audioCtx.resume().catch(() => {});
  return audioCtx;
}

// Any first interaction unlocks audio for later dings.
["pointerdown", "keydown"].forEach((evt) =>
  window.addEventListener(evt, () => { if (soundOn) ensureAudio(); }, { once: true })
);

function ding() {
  if (!soundOn) return;
  const ctx = ensureAudio();
  if (!ctx || ctx.state !== "running") return;
  const t0 = ctx.currentTime;
  [[880, 0], [1318.5, 0.12]].forEach(([freq, dt]) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.0001, t0 + dt);
    gain.gain.exponentialRampToValueAtTime(0.12, t0 + dt + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + dt + 0.35);
    osc.connect(gain).connect(ctx.destination);
    osc.start(t0 + dt);
    osc.stop(t0 + dt + 0.4);
  });
}

soundBtn.addEventListener("click", () => {
  soundOn = !soundOn;
  localStorage.setItem("hg_sound", soundOn ? "on" : "off");
  syncSoundBtn();
  if (soundOn) {
    ensureAudio();
    ding(); // audible confirmation that it works
  }
});

/* ---------- per-token action buttons ---------- */

const nodeActions = document.getElementById("nodeActions");
const actVerify = document.getElementById("actVerify");
const actChart = document.getElementById("actChart");
let selectedToken = null; // { d, circle }

// gmgn.ai path slug per chain tag: gmgn.ai/<slug>/token/<address>
const GMGN_SLUGS = {
  SOL: "sol", SOLANA: "sol",
  ETH: "eth", BSC: "bsc", BASE: "base",
  RH: "robinhood", ROBINHOOD: "robinhood",
  HYPE: "hyperevm", ARB: "arb", ABS: "abstract",
};

function gmgnUrl(d) {
  const tag = (d.chain_tag || "").toUpperCase();
  const slug = GMGN_SLUGS[tag] || (d.chain === "solana" ? "sol" : tag.toLowerCase() || "eth");
  return `https://gmgn.ai/${slug}/token/${d.token_key}`;
}

function selectToken(d, gEl) {
  // Ticker-keyed tokens have no contract address: nothing to chart or verify.
  if (!d.resolved) {
    clearTokenSelection();
    return;
  }
  selectedToken = { d, circle: gEl.querySelector("circle") };
  nodeActions.hidden = false;
  updateNodeActions();
}

function clearTokenSelection() {
  selectedToken = null;
  nodeActions.hidden = true;
}

function updateNodeActions() {
  if (!selectedToken) return;
  const { d, circle } = selectedToken;
  if (!circle.isConnected) return clearTokenSelection(); // node left the graph
  const r = circle.getBoundingClientRect();
  if (r.width === 0) return;
  nodeActions.style.left = `${r.left + r.width / 2}px`;
  nodeActions.style.top = `${r.top - 8}px`;
  actChart.dataset.tokenId = d.id;
}

// Clicking empty map space dismisses the buttons.
svg.on("click", () => clearTokenSelection());

actChart.addEventListener("click", () => {
  if (selectedToken) window.open(gmgnUrl(selectedToken.d), "_blank");
});

actVerify.addEventListener("click", async () => {
  if (!selectedToken) return;
  const { d } = selectedToken;
  actVerify.disabled = true;
  actVerify.textContent = "verifying…";
  try {
    const res = await fetch("/api/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chain: d.chain, token_key: d.token_key }),
    });
    const out = await res.json();
    if (!res.ok) {
      toast(`⚠️ Verify <strong>${displaySymbol(d.symbol)}</strong> failed: ${out.detail || res.status}`);
    } else {
      const lines = out.results
        .map((r) => r.error
          ? `${displaySymbol(r.trader_key)}: ${r.error}`
          : `${displaySymbol(r.trader_key)}: ${fmtPct(r.pct)} on-chain`)
        .join("<br>");
      toast(
        `✅ <strong>${displaySymbol(out.symbol || d.symbol)}</strong> checked on-chain ` +
        `(${out.verified}/${out.checked} wallets)<br>${lines}`,
        12000, "ok");
    }
  } catch (err) {
    toast(`⚠️ Verify failed: ${err.message}`);
  } finally {
    actVerify.disabled = false;
    actVerify.textContent = "✓ verify holders";
  }
});

/* ---------- notification feed drawer ---------- */

const feedPanel = document.getElementById("feedPanel");
const feedList = document.getElementById("feedList");
const feedSeg = document.getElementById("feedSeg");
let feedKind = "all";

function feedRowHtml(it) {
  const when = `<span class="when">${fmtAgo(it.ts)}</span>`;
  if (it.type === "OTHER") {
    return `<div class="head"><span class="pill other">INFO</span>
        <span class="sym">${it.title || "(no text)"}</span>${when}</div>` +
      (it.detail ? `<div class="body">${it.detail}</div>` : "");
  }
  const pill = it.type === "BUY"
    ? `<span class="pill buy">BUY</span>`
    : `<span class="pill sell">${it.is_exit ? "EXIT" : "SELL"}</span>`;
  const bits = [
    it.who ? displaySymbol(String(it.who)) : null,
    it.pct_supply != null ? fmtPct(it.pct_supply) : null,
    it.amount_usd != null ? fmtUsd(it.amount_usd) : null,
    it.mcap_usd != null ? `MC ${fmtUsd(it.mcap_usd)}` : null,
  ].filter(Boolean).join(" · ");
  return `<div class="head">${pill}
      <span class="sym">${displaySymbol(it.symbol)}</span>
      ${it.chain_tag ? `<span class="badge">${it.chain_tag}</span>` : ""}${when}</div>
    <div class="body">${bits}</div>`;
}

async function loadFeed() {
  if (feedPanel.hidden) return;
  try {
    const res = await fetch(`/api/feed?kind=${feedKind}&limit=100`);
    const data = await res.json();
    document.getElementById("feedMeta").textContent = `${data.items.length} shown`;
    feedList.innerHTML = "";
    for (const it of data.items) {
      const row = document.createElement("div");
      row.className = "feed-row";
      row.innerHTML = feedRowHtml(it);
      feedList.append(row);
    }
  } catch (_) { /* transient */ }
}

feedSeg.querySelectorAll("button").forEach((btn) => {
  btn.addEventListener("click", () => {
    feedKind = btn.dataset.kind;
    feedSeg.querySelectorAll("button").forEach((b) =>
      b.classList.toggle("active", b === btn));
    loadFeed();
  });
});

document.getElementById("feedToggle").addEventListener("click", () => {
  feedPanel.hidden = !feedPanel.hidden;
  if (!feedPanel.hidden) loadFeed();
});
document.getElementById("feedClose").addEventListener("click", () => {
  feedPanel.hidden = true;
});

// Deep link: open the page with #feed to start with the drawer expanded.
if (location.hash.includes("feed")) {
  feedPanel.hidden = false;
  loadFeed();
}

/* ---------- toasts ---------- */

function toast(html, ms = 10000, cls = "") {
  const box = document.getElementById("toasts");
  const el = document.createElement("div");
  el.className = `toast ${cls}`;
  el.innerHTML = html;
  el.addEventListener("click", () => el.remove());
  box.append(el);
  setTimeout(() => el.remove(), ms);
}

// Announce tokens whose last holder just sold out. Baseline is set on the
// first poll so history isn't replayed on every page load.
let lastElimId = null;

function handleEliminations(elims) {
  if (!Array.isArray(elims)) return;
  const maxId = elims.length ? Math.max(...elims.map((e) => e.id)) : 0;
  if (lastElimId === null) {
    lastElimId = maxId;
    return;
  }
  for (const e of elims) {
    if (e.id > lastElimId) {
      const sym = displaySymbol(e.symbol || String(e.token_key).replace("sym:", ""));
      toast(`⚠️ <strong>${sym}</strong> is no longer held by anyone — removing it from the graph.`);
    }
  }
  lastElimId = Math.max(lastElimId, maxId);
}

// Preview hook: open the page with #elimtest to see a sample warning.
if (location.hash.includes("elimtest")) {
  setTimeout(() =>
    toast("⚠️ <strong>WOF</strong> is no longer held by anyone — removing it from the graph."), 700);
}

/* ---------- live updates ----------
 * `capture --live` writes new alerts into the DB as they arrive; poll a cheap
 * counts endpoint and re-fetch the graph when anything changed. Passing
 * refit=false keeps the user's pan/zoom during background updates. */
let lastHealth = "";
let prevRaw = null;
setInterval(async () => {
  try {
    const res = await fetch("/api/health");
    const h = await res.json();

    const syncEl = document.getElementById("sync");
    syncEl.textContent = h.last_fetch ? `⟳ ${fmtAgo(h.last_fetch)}` : "";

    // New alert arrived (not just a rebuild we caused ourselves) -> chime.
    if (prevRaw !== null && h.raw_messages > prevRaw) ding();
    prevRaw = h.raw_messages;

    handleEliminations(h.eliminations);

    // Data signature: counts plus the positions-rebuild stamp. The stamp
    // matters — a live alert first inserts events, then rebuilds positions a
    // moment later; without it a poll landing in between would render the old
    // ordering and never re-check (counts stop changing).
    const sig = `${h.raw_messages}|${h.events}|${h.positions}|${h.tokens}|${h.built_at}`;
    if (lastHealth && sig !== lastHealth) {
      load(false);
      if (!panel.hidden) { loadTraders(); loadGroups(); }
      loadFeed(); // no-op when the drawer is closed
    }
    lastHealth = sig;
  } catch (_) { /* server briefly down — retry next tick */ }
}, 10000);

load();
