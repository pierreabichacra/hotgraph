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

// Floating layers (menus, modals, popovers) stack in the order they were
// opened rather than in CSS order: whatever opened last goes on top, so a
// window launched from inside another window never lands behind it.
let topZ = 100;
function raise(el) { el.style.zIndex = ++topZ; }

// Bubble fills are radial gradients so a token reads as a lit disc rather
// than a flat ring; CSS references these ids via fill: url(#…).
const defs = svg.append("defs");
[
  ["hgTokenFill", "#22d3ee", 0.2, 0.04],
  ["hgDeadFill", "#94a3b8", 0.1, 0.02],
].forEach(([id, color, inner, outer]) => {
  const g = defs.append("radialGradient").attr("id", id).attr("cx", "50%").attr("cy", "45%").attr("r", "60%");
  g.append("stop").attr("offset", "0%").attr("stop-color", color).attr("stop-opacity", inner);
  g.append("stop").attr("offset", "100%").attr("stop-color", color).attr("stop-opacity", outer);
});

/* ---------- chain badges ----------
 * Every token bubble wears a small badge on its top-right rim saying which
 * chain it lives on. The common chains get a recognisable glyph drawn as an
 * inline symbol (no image assets — the app is fully self-hosted); the rest
 * show their tag letters on a brand-coloured disc. */
const CHAINS = {
  SOL:       { color: "#9945ff", glyph: "sol" },
  ETH:       { color: "#627eea", glyph: "eth" },
  BSC:       { color: "#f0b90b", glyph: "bnb", ink: "#1a1a1a" },
  BASE:      { color: "#0052ff", glyph: "base" },
  ARB:       { color: "#12aaff", text: "ARB" },
  OP:        { color: "#ff0420", text: "OP" },
  POLY:      { color: "#8247e5", text: "POL" },
  AVAX:      { color: "#e84142", text: "AVX" },
  BLAST:     { color: "#fcfc03", text: "BLT", ink: "#1f1f00" },
  RH:        { color: "#00c805", text: "RH", ink: "#0b1a0c" },
  ARC:       { color: "#6366f1", text: "ARC" },
  STBL:      { color: "#f59e0b", text: "STB", ink: "#2b1a02" },
  ABS:       { color: "#00d977", text: "ABS", ink: "#04301b" },
  HYPE:      { color: "#2dd4bf", text: "HL", ink: "#062b27" },
  LINEA:     { color: "#61dfff", text: "LIN", ink: "#062a33" },
  SONIC:     { color: "#f5a524", text: "SON", ink: "#2b1a02" },
  MONAD:     { color: "#836ef9", text: "MON" },
  UNI:       { color: "#f50db4", text: "UNI" },
  ZK:        { color: "#8c8dfc", text: "ZK", ink: "#14143a" },
  SCROLL:    { color: "#ffdbb0", text: "SCR", ink: "#3b2a1a" },
  MANTLE:    { color: "#65b3ae", text: "MNT", ink: "#062a27" },
  BERA:      { color: "#f47226", text: "BER" },
  SEI:       { color: "#9e1f19", text: "SEI" },
  CRO:       { color: "#1199fa", text: "CRO" },
  XLAYER:    { color: "#94a3b8", text: "XL", ink: "#0f172a" },
  WORLD:     { color: "#e5e7eb", text: "WLD", ink: "#111827" },
  INK:       { color: "#7132f5", text: "INK" },
  PLASMA:    { color: "#00ff9d", text: "XPL", ink: "#003d26" },
  GNOSIS:    { color: "#04795b", text: "GNO" },
  CELO:      { color: "#fcff52", text: "CEL", ink: "#2a2b00" },
  TRON:      { color: "#ef0027", text: "TRX" },
};
// Bots don't agree on tags ([RH] vs [ROBINHOOD]) — aliases share a badge.
// Mirrors the registry in hotgraph/chains.py, which is what the API and the
// verifier go by.
const CHAIN_ALIASES = {
  SOLANA: "SOL", ETHEREUM: "ETH", MAINNET: "ETH", BNB: "BSC", BNBCHAIN: "BSC",
  ARBITRUM: "ARB", OPTIMISM: "OP", MATIC: "POLY", POLYGON: "POLY", POL: "POLY",
  AVALANCHE: "AVAX", ROBINHOOD: "RH", STABLE: "STBL", ABSTRACT: "ABS",
  HYPEREVM: "HYPE", HL: "HYPE", HYPERLIQUID: "HYPE", MON: "MONAD", UNICHAIN: "UNI",
  ZKSYNC: "ZK", ERA: "ZK", SCR: "SCROLL", MNT: "MANTLE", BERACHAIN: "BERA",
  CRONOS: "CRO", OKX: "XLAYER", "X-LAYER": "XLAYER", WORLDCHAIN: "WORLD", WLD: "WORLD",
  XPL: "PLASMA", GNO: "GNOSIS", XDAI: "GNOSIS", TRX: "TRON",
};
const canonTag = (tag) => {
  const t = (tag || "").toUpperCase();
  return CHAIN_ALIASES[t] || t;
};
const chainInfo = (d) => {
  const tag = canonTag(d.chain_tag);
  return CHAINS[tag] || { color: "#64748b", text: (tag || (d.chain === "solana" ? "SOL" : "EVM")).slice(0, 3) };
};

const chainDefs = svg.append("defs");
const sym = (id, inner) => chainDefs.append("symbol").attr("id", `chain-${id}`).attr("viewBox", "0 0 24 24").html(inner);
sym("eth", `<polygon points="12,2 19,12.5 12,16.5 5,12.5"/><polygon points="5,14 12,18.5 19,14 12,22" opacity=".75"/>`);
sym("sol", `<polygon points="7,4 21,4 17,8 3,8"/><polygon points="3,10 17,10 21,14 7,14"/><polygon points="7,16 21,16 17,20 3,20"/>`);
sym("bnb", [[12, 12], [5, 12], [19, 12], [12, 5], [12, 19]]
  .map(([x, y]) => `<path d="M${x},${y - 3.1}L${x + 3.1},${y}L${x},${y + 3.1}L${x - 3.1},${y}Z"/>`).join(""));
sym("base", `<circle cx="12" cy="12" r="8.5"/><rect x="1.5" y="10.7" width="11.5" height="2.6" fill="#0052ff"/>`);

// One radial gradient per chain colour, created on first use, so a bubble
// reads as a lit disc in its chain's hue rather than a flat tint.
const chainFillIds = new Map();
function chainFill(color) {
  if (!chainFillIds.has(color)) {
    const id = `hgFill-${color.replace("#", "")}`;
    const g = chainDefs.append("radialGradient").attr("id", id).attr("cx", "50%").attr("cy", "45%").attr("r", "60%");
    g.append("stop").attr("offset", "0%").attr("stop-color", color).attr("stop-opacity", 0.22);
    g.append("stop").attr("offset", "100%").attr("stop-color", color).attr("stop-opacity", 0.05);
    chainFillIds.set(color, `url(#${id})`);
  }
  return chainFillIds.get(color);
}

const root = svg.append("g");
const gLinks = root.append("g").attr("class", "links");
const gNodes = root.append("g").attr("class", "nodes");
const gFx = root.append("g").attr("class", "fx"); // dust particles, above everything

/* ---------- removal: pulverise to dust ----------
 * A bubble that leaves the graph on a live update doesn't just vanish: it
 * bursts into a cloud of dust in its own colour that drifts outward and
 * fades, while the bubble itself collapses. Filter changes still remove
 * instantly — a hundred bursts at once would be noise, not a signal. */
function pulverise(exit) {
  exit.each(function (d) {
    if (!Number.isFinite(d.x) || !Number.isFinite(d.y)) return;
    const color = d.kind === "token" ? chainInfo(d).color : d.color || "#94a3b8";
    const r = d.r || 10;
    // Dust count follows bubble size, within sane bounds.
    const n = Math.round(Math.max(14, Math.min(90, r * 0.9)));
    const cloud = gFx.append("g").attr("transform", `translate(${d.x},${d.y})`);
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2;
      const d0 = Math.sqrt(Math.random()) * r * 0.95; // uniform over the disc
      const x0 = Math.cos(a) * d0;
      const y0 = Math.sin(a) * d0;
      // Fly outward from the centre, farther for grains near the rim.
      const fly = r * (0.6 + Math.random() * 1.4) * (0.4 + d0 / r);
      const drift = (Math.random() - 0.5) * 0.9;
      const x1 = x0 + Math.cos(a + drift) * fly;
      const y1 = y0 + Math.sin(a + drift) * fly - r * 0.15 * Math.random(); // slight lift
      cloud
        .append("circle")
        .attr("cx", x0).attr("cy", y0)
        // Grain size follows the bubble so dust stays visible at the fitted
        // zoom, where a 100-unit bubble is only ~30px across.
        .attr("r", Math.max(1.2, r * (0.03 + Math.random() * 0.07)))
        .attr("fill", color).attr("opacity", 0.95)
        .transition()
        .delay(Math.random() * 180)
        .duration(650 + Math.random() * 650)
        .ease(d3.easeCubicOut)
        .attr("cx", x1).attr("cy", y1)
        .attr("r", 0.15).attr("opacity", 0)
        .remove();
    }
    cloud.transition().delay(1600).remove();
  });

  // The bubble itself: a quick swell, then collapse and fade.
  exit
    .interrupt()
    .transition().duration(140).ease(d3.easeQuadOut)
    .attr("transform", (d) => `translate(${d.x},${d.y}) scale(1.08)`)
    .transition().duration(420).ease(d3.easeCubicIn)
    .attr("transform", (d) => `translate(${d.x},${d.y}) scale(0.05)`)
    .style("opacity", 0)
    .remove();
}

// Eight hues stepped for the dark surface, in an order whose adjacent pairs
// stay distinct under colour-vision deficiency (validated, not eyeballed).
const PALETTE = [
  "#3987e5", "#d95926", "#199e70", "#c98500",
  "#d55181", "#9085e9", "#e66767", "#22b8c9",
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
// A relative time that stays live: the span carries its timestamp and
// `tickTimes` rewrites every one of them once a minute, so "0m ago" turns
// into "1m ago" without waiting for the next data refresh.
const agoSpan = (ts, cls = "when") =>
  `<span class="${cls}" data-ts="${ts || ""}">${fmtAgo(ts)}</span>`;

function tickTimes() {
  document.querySelectorAll("[data-ts]").forEach((el) => {
    const ts = +el.dataset.ts;
    const txt = fmtAgo(ts || null);
    if (el.textContent !== txt) el.textContent = txt;
  });
  // The activity strip's "now" marker moves with the clock; at midnight the
  // day rolls over and today starts fresh.
  if (typeof activity !== "undefined" && activity && actDay === null) {
    if (localDayStart() !== activity.start) { syncDayControls(); loadActivity(); }
    else renderActivity();
  }
}
// Fire on the minute boundary so all rows roll over together.
setTimeout(() => {
  tickTimes();
  setInterval(tickTimes, 60000);
}, 60000 - (Date.now() % 60000));

/* ---------- state ---------- */

let sim = null;
let currentData = { nodes: [], links: [] };
let tickCount = 0;
let arrangeMode = "free";   // 'free' | 'pack' | 'mcap' | 'newest' | 'oldest' | 'holders'
let clearPanelsUntil = 0;   // while the layout settles after a panel opens, keep bubbles clear of it
let simCtx = null;          // canvas geometry the current simulation was built for

/* ---------- change flashing ----------
 * Anything new or changed on a live update pulses for FLASH_MS so the eye
 * lands on it. Fingerprints track alert-driven fields only — a market-cap
 * refresh touches every token and must not light up the whole graph. The map
 * is cumulative (nodes filtered out of view keep their entry), so widening a
 * filter doesn't make old positions look new. */
const FLASH_MS = 30000;
const fingerprints = new Map(); // id -> string
const flashUntil = new Map(); // id -> epoch ms
let flashTimer = null;

const fingerprint = (d) =>
  d.kind === "token"
    ? `${d.n_events}|${d.n_holders}|${d.n_positions}|${d.last_action}|${d.dead ? 1 : 0}`
    : `${d.status}|${d.pct_supply}|${d.n_events}|${d.last_seen}`;

// Diff this render against the last one. Only a live (background) load
// flashes; the first paint and filter changes just seed the fingerprints.
function markChanges(data, live) {
  const now = Date.now();
  let changed = 0;
  data.nodes.forEach((n) => {
    const fp = fingerprint(n);
    const prev = fingerprints.get(n.id);
    if (live && prev !== fp) { flashUntil.set(n.id, now + FLASH_MS); changed++; }
    fingerprints.set(n.id, fp);
  });
  data.links.forEach((l) => {
    const key = `link:${l.source}|${l.target}`;
    const fp = `${l.status}`;
    const prev = fingerprints.get(key);
    if (live && prev !== fp) flashUntil.set(key, now + FLASH_MS);
    fingerprints.set(key, fp);
  });
  return changed;
}

const isFlashing = (key) => (flashUntil.get(key) || 0) > Date.now();

function applyFlash() {
  const now = Date.now();
  gNodes.selectAll("g.node").classed("flash", (d) => isFlashing(d.id));
  gLinks.selectAll("line").classed("flash", (d) => isFlashing(`link:${linkKey(d)}`));
  // Re-evaluate when the soonest active flash expires; drop stale entries.
  let next = Infinity;
  flashUntil.forEach((t, k) => {
    if (t <= now) flashUntil.delete(k);
    else next = Math.min(next, t);
  });
  clearTimeout(flashTimer);
  if (next < Infinity) flashTimer = setTimeout(applyFlash, next - now + 20);
}

// d3.forceLink swaps link endpoints from ids to node objects.
const endId = (e) => (typeof e === "object" && e !== null ? e.id : e);
const linkKey = (l) => `${endId(l.source)}|${endId(l.target)}`;

// The toolbar wraps onto a second row on narrow screens; everything laid out
// beneath it (canvas, panels, overlays) follows its real height via --bar-h.
{
  const bar = document.getElementById("bar");
  const sync = () =>
    document.documentElement.style.setProperty("--bar-h", `${bar.offsetHeight}px`);
  new ResizeObserver(sync).observe(bar);
  sync();
}

const controls = {
  includeSold: document.getElementById("includeSold"),
  minMcap: document.getElementById("minMcap"),
  maxMcap: document.getElementById("maxMcap"),
  minPct: document.getElementById("minPct"),
  topN: document.getElementById("topN"),
  sortBy: document.getElementById("sortBy"),
  window: document.getElementById("window"),
};

// FDV is worth showing only when it isn't just the market cap again: more
// than 1% apart means supply is still locked or vesting.
const fdvDiffers = (d) =>
  d.fdv_usd != null && d.mcap_usd != null && d.mcap_usd > 0 &&
  Math.abs(d.fdv_usd - d.mcap_usd) / d.mcap_usd > 0.01;

// A token with no known ticker falls back to an address-ish key — shorten it.
const displaySymbol = (s) => {
  if (!s) return "?";
  return s.length > 14 ? `${s.slice(0, 6)}…${s.slice(-4)}` : s;
};

/* ---------- market-cap range ----------
 * The exact numbers live here; the sliders and the text boxes are two views
 * of them. Sliders are logarithmic (most tokens sit under $1M but the range
 * reaches $10B, and a linear slider would bunch them all at one end); a
 * typed amount is kept exactly rather than snapped to a slider step. */
let mcapMin = 0; // 0 = no floor
let mcapMax = 0; // 0 = no cap
const mcapValue = () => mcapMin;
const maxMcapValue = () => mcapMax;

const SLIDER_MAX = 10; // log10($10B)
const sliderPos = (usd) => (usd <= 0 ? 0 : Math.max(0, Math.min(SLIDER_MAX, Math.log10(usd))));
const sliderUsd = (pos) => (pos <= 0 ? 0 : Math.pow(10, pos));

// "250k", "2.5M", "1b", "$1,000,000", "1e6" -> number; blank/"∞"/"none" -> 0.
function parseMoney(text) {
  const t = String(text || "").trim().toLowerCase().replace(/[$,\s_]/g, "");
  if (!t || t === "∞" || t === "inf" || t === "none" || t === "max" || t === "any") return 0;
  const m = /^(\d*\.?\d+(?:e\d+)?)([kmbt])?$/.exec(t);
  if (!m) return null;
  return parseFloat(m[1]) * ({ k: 1e3, m: 1e6, b: 1e9, t: 1e12 }[m[2]] || 1);
}

const minBox = document.getElementById("minMcapVal");
const maxBox = document.getElementById("maxMcapVal");

function syncLabels() {
  controls.minMcap.value = sliderPos(mcapMin);
  controls.maxMcap.value = mcapMax ? sliderPos(mcapMax) : SLIDER_MAX;
  // Don't overwrite what the user is typing.
  if (document.activeElement !== minBox) minBox.value = mcapMin ? fmtUsd(mcapMin) : "$0";
  if (document.activeElement !== maxBox) maxBox.value = mcapMax ? fmtUsd(mcapMax) : "∞";
  minBox.title = mcapMin ? `$${Math.round(mcapMin).toLocaleString()}` : "no minimum";
  maxBox.title = mcapMax ? `$${Math.round(mcapMax).toLocaleString()}` : "no cap";
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
      ["fdv", d.fdv_usd ? fmtUsd(d.fdv_usd) : "—"],
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
    ["avg entry mcap", fmtUsd(d.avg_entry_mcap_usd)],
    ["first entry mcap", fmtUsd(d.entry_mcap_usd)],
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

function render(data, live = false) {
  // Carry positions over from the previous layout so an update nudges the
  // graph instead of rebuilding it from scratch; only new bubbles need to
  // find their place.
  const prev = new Map(currentData.nodes.map((n) => [n.id, n]));
  data.nodes.forEach((n) => {
    const p = prev.get(n.id);
    if (p && Number.isFinite(p.x) && Number.isFinite(p.y)) { n.x = p.x; n.y = p.y; }
  });

  // If the user is looking at a specific token, remember where it is on
  // screen so the layout update can't drift it away from them.
  const pinned = selectedToken && prev.get(selectedToken.d.id);
  const pinScreen = pinned && Number.isFinite(pinned.x)
    ? d3.zoomTransform(svg.node()).apply([pinned.x, pinned.y])
    : null;

  currentData = data;
  const { width, height } = svg.node().getBoundingClientRect();
  const changed = markChanges(data, live);

  // New activity re-frames the whole graph so it's visible — unless a token
  // is selected, in which case the user is focused and the view stays.
  if (live && changed && !selectedToken) userMovedView = false;

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
    .data(links, linkKey)
    .join(
      (enter) => enter.append("line"),
      (update) => update,
      (exit) => (live
        ? exit.transition().duration(350).style("opacity", 0).remove()
        : exit.remove())
    )
    .attr("class", (d) => `link ${d.status === "SOLD" ? "sold" : ""}`);

  const node = gNodes
    .selectAll("g.node")
    .data(data.nodes, (d) => d.id)
    .join((enter) => {
      const g = enter.append("g").attr("class", "node");
      g.append("circle");
      g.append("text").attr("class", "label");
      g.append("text").attr("class", "label sub");
      g.append("text").attr("class", "label sub entry");
      // Chain badge (tokens only): disc + glyph-or-letters.
      const badge = g.filter((d) => d.kind === "token").append("g").attr("class", "chain");
      badge.append("circle");
      badge.append("use");
      badge.append("text");
      return g;
    },
    (update) => update,
    (exit) => (live ? pulverise(exit) : exit.remove()));

  decorateNodes(node);

  applyFlash();

  node
    .on("mousemove", (e, d) => showTip(e, d))
    .on("mouseleave", hideTip)
    .on("click", (e, d) => {
      e.stopPropagation();
      if (d.kind !== "token") return;
      selectToken(d, e.currentTarget);
      focusOn(d);
    })
    .on("contextmenu", (e, d) => {
      e.preventDefault();
      e.stopPropagation();
      if (d.kind === "token") openTokenModalFor(d);
      else openHolderModal(d);
    });

  // Aspect of the canvas area not covered by side panels, normalised so
  // that aspect >= 1 means "wider than tall".
  const availW = Math.max(200, width - visiblePanelWidth("feedPanel")
    - (visiblePanelWidth("tokenPanel") || visiblePanelWidth("mergePanel")));
  const aspectRaw = availW / Math.max(200, height);
  const aspect = aspectRaw >= 1 ? aspectRaw : 1 / aspectRaw;
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
      if (++tickCount % 20 === 0) {
        if (Date.now() < clearPanelsUntil) clearOfPanels();
        else fitToView();
      }
    })
    // Settling is the only safe moment to frame: fitting earlier locks the
    // viewport onto the initial clump, and forceCenter then drags every node
    // out of view.
    .on("end", () => {
      if (Date.now() < clearPanelsUntil) clearOfPanels();
      else fitToView();
      keepPinned(pinScreen);
    });

  // The remaining forces depend on the arrangement mode, which the user can
  // switch without a reload — see configureForces().
  simCtx = { width, height, aspect, aspectRaw };
  configureForces();

  // A layout that starts from carried-over positions only needs a gentle
  // shake to fit the newcomers in.
  if (live && prev.size) sim.alpha(0.4);

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
  document.getElementById("stat").innerHTML =
    `<b>${tokens.length}</b> tokens<i>·</i><b>${holders.length}</b> positions<i>·</i><b>${sold}</b> sold`;

  renderTokenList();
}

/* Everything that makes a bubble look like itself — size, chain tint or
 * person colour, labels, chain badge. Shared by the graph and the token
 * window so a token looks the same wherever it's drawn. */
function decorateNodes(node) {
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
    .attr("stroke", (d) => (d.kind === "token" ? null : d.color))
    // Live tokens are tinted by chain (inline style beats the stylesheet's
    // cyan default); dead ones clear it so the grey .dead rule applies.
    .style("fill", (d) => (d.kind === "token" && !d.dead ? chainFill(chainInfo(d).color) : null))
    .style("stroke", (d) => (d.kind === "token" && !d.dead ? chainInfo(d).color : null));

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
      if (d.kind === "token") return fdvDiffers(d) ? `MC ${fmtUsd(d.mcap_usd)}` : fmtUsd(d.mcap_usd);
      if (d.r < 15) return "";
      const v = d.status === "SOLD" ? d.peak_pct : d.pct_supply;
      return d.status === "SOLD" ? `sold · ${fmtPct(v)}` : fmtPct(v);
    });

  // Holders: the average market cap they bought in at, on a third line —
  // only where the bubble is big enough to carry three lines legibly.
  node
    .select("text.label.sub.entry")
    .attr("class", (d) => `label sub entry ${d.status === "SOLD" || d.dead ? "faded" : ""}`)
    .attr("dy", "2.35em")
    .text((d) => {
      // Tokens: FDV on the third line, but only when it tells a different
      // story from market cap (locked or vesting supply).
      if (d.kind === "token") return fdvDiffers(d) ? `FDV ${fmtUsd(d.fdv_usd)}` : "";
      if (d.r < 22 || d.status === "SOLD") return "";
      return d.avg_entry_mcap_usd ? `@ ${fmtUsd(d.avg_entry_mcap_usd)}` : "";
    });

  node
    .select("g.chain")
    .attr("class", (d) => `chain${d.dead ? " dead" : ""}`)
    .each(function (d) {
      const info = chainInfo(d);
      // Badge scales with the bubble, within a legible range, and sits on
      // the rim at 45° so it never covers the ticker.
      const br = Math.max(8, Math.min(13, d.r * 0.2));
      const k = Math.SQRT1_2;
      const g = d3.select(this).attr("transform", `translate(${d.r * k},${-d.r * k})`);
      g.select("circle").attr("r", br).attr("fill", info.color);
      const ink = info.ink || "#fff";
      const use = g.select("use");
      const text = g.select("text");
      if (info.glyph) {
        const sz = br * 1.35;
        use.attr("href", `#chain-${info.glyph}`).attr("x", -sz / 2).attr("y", -sz / 2)
          .attr("width", sz).attr("height", sz).attr("fill", ink).style("display", null);
        text.style("display", "none");
      } else {
        use.style("display", "none");
        text.style("display", null).text(info.text).attr("fill", ink)
          .attr("font-size", `${(info.text.length > 2 ? 0.78 : 0.95) * br}px`)
          .attr("dy", "0.36em");
      }
    });
}

/* ---------- arrangement ----------
 * "free" is the plain force layout. Every other mode gives each token a
 * target spot — packed as tightly as circles allow, or laid out in reading
 * order (left→right, top→bottom) by market cap, last action or holder
 * count — and the simulation pulls the cluster there, holders in tow. */

const ARRANGE_ORDER = {
  mcap: (a, b) => (b.value || 0) - (a.value || 0),
  newest: (a, b) => (b.last_action || 0) - (a.last_action || 0),
  oldest: (a, b) => (a.last_action || 9e15) - (b.last_action || 9e15),
  holders: (a, b) => (b.n_holders - a.n_holders) || (b.n_positions - a.n_positions),
};

function configureForces() {
  if (!sim || !simCtx) return;
  const { width, height, aspect, aspectRaw } = simCtx;
  sim.force("collide", d3.forceCollide().radius((d) => d.r + (d.kind === "token" ? 8 : 3)).iterations(4));

  if (arrangeMode === "free") {
    sim
      // Spacing comes from collision, not repulsion: a strong many-body
      // charge spread 150 tokens so far apart that fitting them all on
      // screen made every bubble tiny. Tokens keep a mild push so clusters
      // stay separable; people barely repel, so their link dominates and
      // keeps them in orbit.
      .force("charge", d3.forceManyBody().strength((d) => (d.kind === "token" ? -220 : -12)).distanceMax(600))
      // Without forceCenter the layout settles around the origin, i.e. the
      // top-left corner, leaving the canvas looking empty.
      .force("center", d3.forceCenter(width / 2, height / 2))
      // Shape the blob like the visible canvas: a weaker pull along the
      // long axis lets it spread that way, so "fit everything" fills the
      // screen instead of leaving empty side margins around a square cloud.
      .force("x", d3.forceX(width / 2).strength((d) => (d.kind === "token" ? 0.07 : 0.004) / (aspect * aspect * aspect)))
      .force("y", d3.forceY(height / 2).strength((d) => (d.kind === "token" ? 0.07 : 0.004) * (aspect < 1 ? aspect * aspect : 1)));
    return;
  }

  arrangeTargets(width, height, aspectRaw);
  sim
    // No token repulsion: the targets already keep clusters apart, and a
    // charge would only fight the pull toward them.
    .force("charge", d3.forceManyBody().strength((d) => (d.kind === "token" ? 0 : -12)).distanceMax(600))
    .force("center", null)
    .force("x", d3.forceX((d) => d.tx).strength((d) => (d.kind === "token" ? 0.6 : 0.03)))
    .force("y", d3.forceY((d) => d.ty).strength((d) => (d.kind === "token" ? 0.6 : 0.03)));
}

// Sets tx/ty on every node: tokens get their cluster's spot, holders their
// token's, so a whole cluster travels together.
function arrangeTargets(width, height, aspectRaw) {
  const byToken = new Map();
  for (const l of sim.force("link").links()) {   // endpoints are node objects here
    const t = l.target.kind === "token" ? l.target : l.source;
    const p = t === l.target ? l.source : l.target;
    if (!byToken.has(t.id)) byToken.set(t.id, []);
    byToken.get(t.id).push(p);
  }
  // A cluster is the token plus the ring of holders orbiting it. A token
  // with one or two holders doesn't use its whole ring, so its footprint is
  // trimmed — any real overlap is sorted out by the collision force.
  const clusters = currentData.nodes
    .filter((n) => n.kind === "token")
    .map((t) => {
      const hs = byToken.get(t.id) || [];
      const hmax = d3.max(hs, (p) => p.r) || 0;
      const ring = hmax ? hmax + 6 + hmax * Math.min(1, hs.length / 4) : 0;
      return { t, r: t.r + ring + 8 };
    });
  if (!clusters.length) return;

  if (arrangeMode === "pack") {
    clusters.sort((a, b) => b.r - a.r); // biggest first packs tightest
    d3.packSiblings(clusters);          // sets x, y on each cluster
  } else {
    clusters.sort((a, b) => ARRANGE_ORDER[arrangeMode](a.t, b.t));
    flowRows(clusters, aspectRaw);
  }

  // Centre the block on the canvas so it lands where the free layout lives.
  const cx = (d3.min(clusters, (c) => c.x - c.r) + d3.max(clusters, (c) => c.x + c.r)) / 2;
  const cy = (d3.min(clusters, (c) => c.y - c.r) + d3.max(clusters, (c) => c.y + c.r)) / 2;
  for (const c of clusters) {
    c.t.tx = c.x - cx + width / 2;
    c.t.ty = c.y - cy + height / 2;
    for (const p of byToken.get(c.t.id) || []) { p.tx = c.t.tx; p.ty = c.t.ty; }
  }
}

// Reading-order rows, wrapped so the whole block roughly matches the shape
// of the visible canvas rather than one endless line.
function flowRows(clusters, aspect) {
  const area = d3.sum(clusters, (c) => 4 * c.r * c.r);
  const targetW = Math.max(d3.max(clusters, (c) => 2 * c.r), Math.sqrt(area * Math.max(0.3, aspect)));
  const gap = 6;
  let x = 0;
  let y = 0;
  let row = [];
  const closeRow = () => {
    const h = d3.max(row, (c) => 2 * c.r) || 0;
    for (const c of row) c.y = y + h / 2;
    y += h + gap;
    x = 0;
    row = [];
  };
  for (const c of clusters) {
    if (row.length && x + 2 * c.r > targetW) closeRow();
    c.x = x + c.r;
    x += 2 * c.r + gap;
    row.push(c);
  }
  if (row.length) closeRow();
}

const arrangeEl = document.getElementById("arrange");
function syncArrange() {
  arrangeEl.querySelectorAll("button").forEach((b) =>
    b.classList.toggle("active", b.dataset.mode === arrangeMode));
}
arrangeEl.querySelectorAll("button").forEach((btn) => {
  btn.addEventListener("click", () => {
    // Clicking the active mode again releases the bubbles to the free layout.
    arrangeMode = arrangeMode === btn.dataset.mode ? "free" : btn.dataset.mode;
    syncArrange();
    if (!sim) return;
    configureForces();
    userMovedView = false; // a new arrangement deserves a fresh framing
    sim.alpha(1).restart();
  });
});

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
  .scaleExtent([0.03, 10])
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
  fitToView(true);
});

/* Frame every bubble once the layout settles — without this the graph sits in
 * a small clump in the middle of a mostly empty canvas.
 *
 * Fired from both the simulation's "end" event and a timer: "end" only arrives
 * once alpha decays below its threshold, which can be long after the layout is
 * visually settled (and never, if something keeps nudging alpha). */
let userMovedView = false;

function fitToView(animate = false) {
  if (userMovedView) return;
  if (!currentData.nodes.length) return;
  if (!currentData.nodes.every((n) => Number.isFinite(n.x) && Number.isFinite(n.y))) return;

  const minX = d3.min(currentData.nodes, (n) => n.x - n.r);
  const maxX = d3.max(currentData.nodes, (n) => n.x + n.r);
  const minY = d3.min(currentData.nodes, (n) => n.y - n.r);
  const maxY = d3.max(currentData.nodes, (n) => n.y + n.r);
  if (![minX, maxX, minY, maxY].every(Number.isFinite)) return;

  const w = maxX - minX;
  const h = maxY - minY;
  if (!(w > 0) || !(h > 0)) return;

  // Fit into the part of the canvas that isn't covered by an open side
  // panel, so "show every bubble" means every bubble is actually visible.
  const { width, height } = svg.node().getBoundingClientRect();
  const left = visiblePanelWidth("feedPanel");
  const right = visiblePanelWidth("tokenPanel") || visiblePanelWidth("mergePanel");
  const pad = 28;
  const availW = Math.max(120, width - left - right - pad * 2);
  const availH = Math.max(120, height - pad * 2);

  // The largest scale at which the whole graph still fits.
  const k = Math.min(availW / w, availH / h);
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  const t = d3.zoomIdentity
    .translate(left + pad + availW / 2 - k * cx, pad + availH / 2 - k * cy)
    .scale(k);

  // Framing goes through the zoom behaviour itself so it shares one
  // coordinate system with focusOn() and with user pan/zoom — a fit done via
  // viewBox instead used to leave any earlier zoom-out composed on top, which
  // is why "reset" could still show the graph small in the middle.
  (animate ? svg.transition().duration(450) : svg).call(zoom.transform, t);
}

// After a layout update, pan (never zoom) so the selected token sits where
// it did on screen before the update.
function keepPinned(pinScreen) {
  if (!pinScreen || !selectedToken) return;
  const d = currentData.nodes.find((n) => n.id === selectedToken.d.id);
  if (!d || !Number.isFinite(d.x)) return;
  const t = d3.zoomTransform(svg.node());
  const [sx, sy] = t.apply([d.x, d.y]);
  const dx = pinScreen[0] - sx;
  const dy = pinScreen[1] - sy;
  if (Math.hypot(dx, dy) < 1) return;
  svg.transition().duration(350).call(zoom.transform, t.translate(dx / t.k, dy / t.k));
}

function visiblePanelWidth(id) {
  const el = document.getElementById(id);
  return el && !el.hidden ? el.offsetWidth : 0;
}

/* A side panel opening must never hide bubbles behind it. If the user
 * hasn't taken the view, re-frame as usual; otherwise keep their zoom and
 * push the graph just far enough toward the uncovered area's centre — and
 * only when it can't fit at that zoom, zoom out until it does. */
function clearOfPanels() {
  if (!currentData.nodes.length) return;
  if (!userMovedView) return fitToView(true);
  if (!currentData.nodes.every((n) => Number.isFinite(n.x) && Number.isFinite(n.y))) return;

  const t = d3.zoomTransform(svg.node());
  const sx0 = t.applyX(d3.min(currentData.nodes, (n) => n.x - n.r));
  const sx1 = t.applyX(d3.max(currentData.nodes, (n) => n.x + n.r));
  const sy0 = t.applyY(d3.min(currentData.nodes, (n) => n.y - n.r));
  const sy1 = t.applyY(d3.max(currentData.nodes, (n) => n.y + n.r));
  if (![sx0, sx1, sy0, sy1].every(Number.isFinite)) return;

  const { width, height } = svg.node().getBoundingClientRect();
  const pad = 28;
  const x0 = visiblePanelWidth("feedPanel") + pad;
  const x1 = width - (visiblePanelWidth("tokenPanel") || visiblePanelWidth("mergePanel")) - pad;
  const y0 = pad;
  const y1 = height - pad;

  // Too big for what's left of the canvas at this zoom: zoom out to fit.
  if (sx1 - sx0 > x1 - x0 || sy1 - sy0 > y1 - y0) {
    userMovedView = false;
    fitToView(true);
    userMovedView = true; // it's still their view — live updates shouldn't re-frame it
    return;
  }

  // Otherwise the smallest pan that brings every bubble into the clear.
  let dx = 0;
  let dy = 0;
  if (sx0 < x0) dx = x0 - sx0;
  else if (sx1 > x1) dx = x1 - sx1;
  if (sy0 < y0) dy = y0 - sy0;
  else if (sy1 > y1) dy = y1 - sy1;
  if (Math.hypot(dx, dy) < 1) return;
  svg.transition().duration(450).call(zoom.transform, t.translate(dx / t.k, dy / t.k));
}

function focusOn(d) {
  userMovedView = true;
  const { width, height } = svg.node().getBoundingClientRect();
  const k = d.kind === "token" ? Math.min(2.2, 220 / d.r) : 0.8;
  svg
    .transition()
    .duration(600)
    .call(
      zoom.transform,
      d3.zoomIdentity.translate(width / 2, height / 2).scale(k).translate(-d.x, -d.y)
    );
}

/* ---------- data ---------- */

async function load(refit = true, live = false) {
  syncLabels();
  // Event-handler calls pass an Event object (truthy) = deliberate action.
  if (refit) userMovedView = false; // a new filter set deserves a fresh framing
  const p = new URLSearchParams({
    include_sold: controls.includeSold.checked,
    min_mcap: mcapValue(),
    max_mcap: maxMcapValue(),
    min_pct: controls.minPct.value,
    top: controls.topN.value,
    sort: controls.sortBy.value,
    since_hours: controls.window.value,
  });
  if (selectedChains.size) p.set("chain", [...selectedChains].join(","));
  if (selectedUsers.size) p.set("persons", [...selectedUsers].join(","));

  try {
    const res = await fetch(`/api/graph?${p}`);
    render(await res.json(), live);
  } catch (err) {
    document.getElementById("stat").textContent = `error: ${err.message}`;
  }
}

/* ---------- users filter ----------
 * Multi-select: the graph draws only the checked people's positions, and
 * tokens none of them touched drop out with them. Empty selection = everyone. */

const selectedUsers = new Set();
const userBtn = document.getElementById("userFilterBtn");
const userMenu = document.getElementById("userFilterMenu");
const userListEl = document.getElementById("userList");
const userSearch = document.getElementById("userSearch");

function syncUserBtn() {
  userBtn.textContent = selectedUsers.size ? `${selectedUsers.size} selected ▾` : "all ▾";
}

async function loadUsers() {
  const res = await fetch("/api/persons");
  const data = await res.json();
  const q = userSearch.value.trim().toLowerCase();

  userListEl.innerHTML = "";
  for (const u of data.persons) {
    if (q && !u.person.toLowerCase().includes(q)) continue;
    const row = document.createElement("label");
    row.className = "user-row";
    row.title = u.person;

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = selectedUsers.has(u.person);
    cb.addEventListener("change", () => {
      if (cb.checked) selectedUsers.add(u.person);
      else selectedUsers.delete(u.person);
      syncUserBtn();

load();
    });

    const name = document.createElement("span");
    name.className = "user-name";
    name.textContent = u.person;

    const meta = document.createElement("span");
    meta.className = "user-meta";
    meta.textContent = `${u.n_holding || 0} holding · ${u.n_positions}`;

    row.append(cb, name, meta);
    userListEl.append(row);
  }
  if (!userListEl.children.length) {
    userListEl.innerHTML = `<div class="panel-hint">no matches</div>`;
  }
}

userBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  chainMenu.hidden = true;
  userMenu.hidden = !userMenu.hidden;
  if (!userMenu.hidden) {
    raise(userMenu);
    // The header clips overflow, so the menu is a fixed element aligned to
    // the button — clamped so it never runs off the right edge.
    const r = userBtn.getBoundingClientRect();
    userMenu.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - 270))}px`;
    userSearch.value = "";
    loadUsers();
    userSearch.focus();
  }
});

document.getElementById("userClear").addEventListener("click", () => {
  selectedUsers.clear();
  syncUserBtn();
  loadUsers();

load();
});

userSearch.addEventListener("input", loadUsers);
// Clicks inside the menu must not bubble to the window handler that closes it.
userMenu.addEventListener("click", (e) => e.stopPropagation());
window.addEventListener("click", () => { userMenu.hidden = true; });

/* ---------- chain filter ----------
 * Multi-select over every chain the registry (hotgraph/chains.py) knows;
 * the graph, feed counts and activity strip all follow it. Empty = all. */

const selectedChains = new Set();
const chainBtn = document.getElementById("chainFilterBtn");
const chainMenu = document.getElementById("chainFilterMenu");
const chainListEl = document.getElementById("chainList");
const chainSearch = document.getElementById("chainSearch");
let chainCatalog = []; // /api/chains: [{tag, name, family, n_tokens, n_live}]

function syncChainBtn() {
  const n = selectedChains.size;
  chainBtn.textContent = !n ? "all ▾" : n <= 2 ? `${[...selectedChains].join(" + ")} ▾` : `${n} chains ▾`;
}

function renderChainMenu() {
  const q = chainSearch.value.trim().toLowerCase();
  chainListEl.innerHTML = "";
  // Chains with live tokens first, busiest on top; ties keep registry order.
  const rows = [...chainCatalog].sort((a, b) => (b.n_live - a.n_live) || (b.n_tokens - a.n_tokens));
  for (const c of rows) {
    if (q && !c.name.toLowerCase().includes(q) && !c.tag.toLowerCase().includes(q)) continue;
    const row = document.createElement("label");
    row.className = `user-row${c.n_tokens ? "" : " empty"}`;
    row.title = `${c.name} [${c.tag}] · ${c.family}`;

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = selectedChains.has(c.tag);
    cb.addEventListener("change", () => {
      if (cb.checked) selectedChains.add(c.tag);
      else selectedChains.delete(c.tag);
      onChainChange();
    });

    const dot = document.createElement("span");
    dot.className = "chain-dot";
    dot.style.background = (CHAINS[c.tag] || {}).color || "#64748b";

    const name = document.createElement("span");
    name.className = "user-name";
    name.textContent = c.name;

    const meta = document.createElement("span");
    meta.className = "user-meta";
    meta.textContent = c.n_tokens ? `${c.n_live} live · ${c.n_tokens}` : "—";

    row.append(cb, dot, name, meta);
    chainListEl.append(row);
  }
  if (!chainListEl.children.length) {
    chainListEl.innerHTML = `<div class="panel-hint">no matches</div>`;
  }
}

async function loadChains() {
  try {
    const res = await fetch("/api/chains");
    chainCatalog = (await res.json()).chains;
  } catch (_) { /* keep the last catalogue */ }
  renderChainMenu();
}

function onChainChange() {
  syncChainBtn();
  closeActivityPop();
  load();
  loadActivity();
}

chainBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  userMenu.hidden = true;
  chainMenu.hidden = !chainMenu.hidden;
  if (!chainMenu.hidden) {
    raise(chainMenu);
    const r = chainBtn.getBoundingClientRect();
    chainMenu.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - 270))}px`;
    chainSearch.value = "";
    loadChains();
    chainSearch.focus();
  }
});

document.getElementById("chainClear").addEventListener("click", () => {
  selectedChains.clear();
  renderChainMenu();
  onChainChange();
});

chainSearch.addEventListener("input", renderChainMenu);
chainMenu.addEventListener("click", (e) => e.stopPropagation());
window.addEventListener("click", () => { chainMenu.hidden = true; });

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
      ` · ${agoSpan(t.last_action, "ago")}</span></div>`;
    row.addEventListener("click", () => {
      const node = currentData.nodes.find((n) => n.id === t.id);
      if (node && Number.isFinite(node.x)) focusOn(node);
    });
    tokenListEl.append(row);
  });
}

// Fetch fresh market caps for every token the drawer currently lists (which
// mirrors the graph). Retries live server-side, in hotgraph/mcap.py.
// Two callers: the drawer button (progress bar + toast) and a quiet timer
// below that keeps the numbers current on its own every 15 minutes.
const mcapBtn = document.getElementById("mcapRefresh");
const MCAP_BTN_LABEL = "💲 refresh market caps";
let mcapBusy = false;
let mcapLastRun = Date.now(); // page load counts — the graph arrives fresh

async function refreshMcaps({ silent = false } = {}) {
  if (mcapBusy) return false;
  const tokens = currentData.nodes
    .filter((n) => n.kind === "token" && n.resolved)
    .map((t) => ({ chain: t.chain, token_key: t.token_key }));
  if (!tokens.length) {
    if (!silent) toast("⚠️ No address-keyed tokens shown — nothing to refresh.");
    return false;
  }
  mcapBusy = true;
  mcapBtn.disabled = true;
  mcapBtn.textContent = silent
    ? "💲 refreshing market caps…"
    : `fetching ${tokens.length} market caps…`;

  // Same top bar the rebuild uses — here the total is known, so it's a real
  // percentage from the start. The automatic run skips it: a bar sliding
  // across the top every few minutes would be noise.
  let poll = null;
  if (!silent) {
    rebuildProgress.hidden = false;
    rebuildFill.classList.remove("indeterminate");
    rebuildFill.style.width = "0%";
    rebuildLabel.textContent = `fetching market caps — 0/${tokens.length}`;
    poll = setInterval(async () => {
      try {
        const st = await (await fetch("/api/mcaps/status")).json();
        if (st.active && st.total) {
          rebuildFill.style.width = `${Math.round((st.done / st.total) * 100)}%`;
          rebuildLabel.textContent =
            `fetching market caps — ${st.done}/${st.total}`;
        }
      } catch (_) { /* transient */ }
    }, 400);
  }

  try {
    const res = await fetch("/api/mcaps", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tokens }),
    });
    const out = await res.json();
    if (!res.ok) throw new Error(out.detail || res.status);
    if (!silent) {
      const extras = [
        out.unknown ? `${out.unknown} unknown to DexScreener` : null,
        out.failed ? `${out.failed} failed after retries` : null,
      ].filter(Boolean).join(", ");
      toast(`✅ Market caps updated for ${out.updated}/${out.requested} tokens` +
        (extras ? ` (${extras})` : ""), 8000, "ok");
    }
    await load(false); // keep the user's pan/zoom; bubbles resize in place
    return true;
  } catch (err) {
    if (silent) console.warn("automatic market-cap refresh failed:", err.message);
    else toast(`⚠️ Market cap refresh failed: ${err.message}`);
    return false;
  } finally {
    // Counted whether it worked or not, so a flaky upstream (or a 409 from
    // another tab's refresh) is retried on the normal cadence, not every tick.
    mcapLastRun = Date.now();
    if (poll) clearInterval(poll);
    if (!silent) rebuildProgress.hidden = true;
    mcapBusy = false;
    mcapBtn.disabled = false;
    mcapBtn.textContent = MCAP_BTN_LABEL;
  }
}

mcapBtn.addEventListener("click", () => refreshMcaps());

// Automatic refresh: every 15 minutes, quietly, and only while the tab is
// visible — a background tab would just spend DexScreener's rate budget for
// nobody. A tab that comes back overdue refreshes right away. The interval
// is checked every 30s rather than scheduled outright so a manual refresh
// (or a failure) simply pushes the next automatic one back by a full period.
const MCAP_AUTO_MS = 15 * 60 * 1000;

function autoRefreshMcaps() {
  if (document.hidden || mcapBusy) return;
  if (Date.now() - mcapLastRun < MCAP_AUTO_MS) return;
  refreshMcaps({ silent: true });
}

setInterval(autoRefreshMcaps, 30 * 1000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) autoRefreshMcaps(); });

// Progress bar for a running holder verification (single token or the whole
// drawer). Tokens are the coarse unit; wallets within the current token fill
// in the fraction between ticks, so a token with 40 wallets still moves.
// Returns a stop() function.
function trackVerifyProgress(label, total) {
  rebuildProgress.hidden = false;
  // Slide until the first status tick lands, so the bar is visibly alive
  // from the first frame even when the whole run takes a second.
  rebuildFill.classList.add("indeterminate");
  rebuildFill.style.width = "0%";
  rebuildLabel.textContent = `${label} — starting…`;
  const poll = setInterval(async () => {
    try {
      const st = await (await fetch("/api/verify/status")).json();
      if (!st.active || !st.total) return;
      rebuildFill.classList.remove("indeterminate");
      const frac = st.wallets_total ? st.wallets_done / st.wallets_total : 0;
      const pct = Math.min(100, ((st.done + Math.min(frac, 0.999)) / st.total) * 100);
      rebuildFill.style.width = `${Math.round(pct)}%`;
      const wallets = st.wallets_total
        ? ` · wallet ${st.wallets_done}/${st.wallets_total}` : "";
      const sym = st.symbol ? ` (${displaySymbol(st.symbol)})` : "";
      rebuildLabel.textContent = st.total > 1
        ? `${label} — token ${Math.min(st.done + 1, st.total)}/${st.total}${sym}${wallets}`
        : `${label}${sym}${wallets}`;
    } catch (_) { /* transient */ }
  }, 300);
  return () => {
    clearInterval(poll);
    rebuildFill.classList.remove("indeterminate");
    rebuildProgress.hidden = true;
  };
}

// Verify every holder of every token the drawer currently lists on-chain.
// Runs server-side one token at a time (public RPCs), positions rebuild once
// at the end; per-token failures are counted, not fatal.
const verifyAllBtn = document.getElementById("verifyAll");
verifyAllBtn.addEventListener("click", async () => {
  const tokens = currentData.nodes
    .filter((n) => n.kind === "token" && n.resolved)
    .map((t) => ({ chain: t.chain, token_key: t.token_key }));
  if (!tokens.length) {
    toast("⚠️ No address-keyed tokens shown — nothing to verify.");
    return;
  }
  verifyAllBtn.disabled = true;
  verifyAllBtn.textContent = `verifying ${tokens.length} tokens…`;
  const stopProgress = trackVerifyProgress("verifying holders", tokens.length);

  try {
    const res = await fetch("/api/verify/all", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tokens }),
    });
    const out = await res.json();
    if (!res.ok) throw new Error(out.detail || res.status);
    const failed = out.results.filter((r) => r.error);
    const lines = failed
      .slice(0, 8)
      .map((r) => `${displaySymbol(r.symbol || r.token_key)}: ${r.error}`)
      .concat(failed.length > 8 ? [`…and ${failed.length - 8} more`] : [])
      .join("<br>");
    toast(
      `✅ Verified ${out.wallets_verified}/${out.wallets_checked} wallets across ` +
      `${out.tokens_verified}/${out.requested} tokens` +
      (failed.length ? `<br>⚠️ ${failed.length} token(s) skipped:<br>${lines}` : ""),
      failed.length ? 14000 : 8000, "ok");
    await load(false); // keep the user's pan/zoom; bubbles resize in place
  } catch (err) {
    toast(`⚠️ Holder verification failed: ${err.message}`);
  } finally {
    stopProgress();
    verifyAllBtn.disabled = false;
    verifyAllBtn.textContent = "✓ verify holders";
  }
});

// Reset-zoom and Tokens buttons live at the map's top-right, Feed at the
// top-left; when a side panel is open they slide aside so they never hide
// underneath it.
const resetZoomBtn = document.getElementById("resetZoom");
const listToggleBtn = document.getElementById("listToggle");
const feedToggleBtn = document.getElementById("feedToggle");

function syncMapButtons() {
  let offset = 12;
  const mp = document.getElementById("mergePanel");
  if (!tokenPanel.hidden) offset += tokenPanel.offsetWidth;
  else if (mp && !mp.hidden) offset += mp.offsetWidth;
  resetZoomBtn.style.right = `${offset}px`;
  listToggleBtn.style.right = `${offset}px`;

  const fp = document.getElementById("feedPanel");
  const feedLeft = 12 + (fp && !fp.hidden ? fp.offsetWidth : 0);
  feedToggleBtn.style.left = `${feedLeft}px`;
  document.getElementById("caSearch").style.left = `${feedLeft + feedToggleBtn.offsetWidth + 8}px`;

  // Now, and again on the next few layout ticks — a simulation still
  // settling would otherwise push bubbles back under the panel.
  clearOfPanels();
  clearPanelsUntil = Date.now() + 4000;
}

resetZoomBtn.addEventListener("click", () => {
  userMovedView = false;
  fitToView(true);
});

listToggleBtn.addEventListener("click", () => {
  tokenPanel.hidden = !tokenPanel.hidden;
  if (!tokenPanel.hidden) {
    document.getElementById("mergePanel").hidden = true;
    renderTokenList();
    loadBlacklist();
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

/* ---------- sign out of Telegram ----------
 * Logs the HotGraph device out (revoked server-side) and deletes its session
 * file. The listener's disconnect stops the whole process, so the page goes
 * dark on purpose; start.py then asks for a fresh login. The DB is kept. */
document.getElementById("signOut").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  if (!confirm(
    "Sign out of Telegram?\n\nHotGraph will stop and delete its session file. " +
    "Your alerts and positions are kept. Run start again to log back in.")) return;
  btn.disabled = true;
  try {
    const res = await fetch("/api/logout", { method: "POST" });
    const out = await res.json();
    if (!res.ok) throw new Error(out.detail || res.status);
    document.querySelectorAll(".empty").forEach((el) => el.remove());
    svg.node().insertAdjacentHTML("afterend",
      `<div class="empty">Signed out — HotGraph has stopped.<br>Run <code>start</code> again to log in.</div>`);
    toast("✅ Signed out of Telegram — HotGraph is stopping.", 15000, "ok");
  } catch (err) {
    btn.disabled = false;
    toast(`⚠️ Sign out failed: ${escapeHtml(err.message)}`);
  }
});

/* ---------- suspected new wallets ----------
 * A tracked person sending tokens to a wallet with nothing coming back is a
 * move, and the recipient is usually theirs too. Untracked recipients are
 * listed here (server derives them from the transfer events); one click
 * merges the wallet into the person, or dismisses it as not theirs. */

const walletsModal = document.getElementById("walletsModal");
const walletsBtn = document.getElementById("walletsBtn");
const walletsCount = document.getElementById("walletsCount");
let walletsData = new Map(); // wallet -> suggestion group

function updateWalletsBadge(n) {
  const count = n || 0;
  walletsBtn.classList.toggle("pulse", count > 0);
  walletsCount.hidden = !count;
  walletsCount.textContent = count;
  walletsBtn.title = count
    ? `${count} new suspected wallet${count === 1 ? "" : "s"} — tracked people sent tokens to wallets nobody tracks yet`
    : "suspected new wallets — tracked people sent tokens to these (nothing received back), but nobody tracks them yet";
}

async function loadWalletSuggestions({ markSeen = false } = {}) {
  const body = document.getElementById("wmBody");
  try {
    const res = await fetch("/api/wallet_suggestions");
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.status);
    renderWalletSuggestions(data);
    if (markSeen && data.new) {
      await fetch("/api/wallet_suggestions/seen", { method: "POST" });
      updateWalletsBadge(0);
    }
  } catch (err) {
    body.innerHTML = `<div class="panel-hint">Couldn't load suggestions: ${escapeHtml(err.message)}</div>`;
  }
}

function openWalletsModal() {
  walletsModal.hidden = false;
  raise(walletsModal);
  hideTip();
  document.getElementById("wmBody").innerHTML = `<div class="panel-hint">loading…</div>`;
  loadWalletSuggestions({ markSeen: true });
}

function closeWalletsModal() {
  walletsModal.hidden = true;
}

function renderWalletSuggestions(data) {
  const body = document.getElementById("wmBody");
  const list = data.suggestions;
  walletsData = new Map(list.map((g) => [g.wallet, g]));
  document.getElementById("wmSub").textContent =
    `${list.length} wallet${list.length === 1 ? "" : "s"}${data.new ? ` · ${data.new} new` : ""}`;
  if (!list.length) {
    body.innerHTML = `<div class="panel-hint">Nothing yet. When someone you track sends tokens to a wallet
      you don't track — and gets nothing back — that wallet shows up here as probably theirs.</div>`;
    return;
  }
  body.innerHTML = list.map((g) => {
    const s = g.senders[0];
    const names = g.senders.map((x) => escapeHtml(x.person)).join(", ");
    const isEvm = /^0x[a-fA-F0-9]{40}$/.test(g.wallet);
    const tag = g.chain_tags[0] || (g.chain === "solana" ? "SOL" : "");
    const ex = EXPLORERS[tag];
    const badges = g.chain_tags.map((t) => {
      const info = CHAINS[t] || { color: "#64748b" };
      return `<span class="badge" style="background:${info.color}22;color:${info.color}">${escapeHtml(t)}</span>`;
    }).join("");
    const toks = g.tokens.slice(0, 8).map((t) =>
      `<span class="tok" title="${agoSpan(t.ts)}${t.mcap_usd != null ? ` · MC ${fmtUsd(t.mcap_usd)}` : ""}">${escapeHtml(displaySymbol(t.symbol))}${t.pct != null ? ` ${fmtPct(t.pct)}` : ""}</span>`
    ).join("") + (g.tokens.length > 8 ? `<span class="tok">+${g.tokens.length - 8} more</span>` : "");
    return `<div class="sug-row${g.new ? " new" : ""}" data-wallet="${escapeHtml(g.wallet)}">
      <div class="head">
        <span class="dot" style="background:${s.color || personColor(s.person)}"></span>
        <span class="who">${names}</span><span class="arrow">→</span>
        <span class="addr" title="${escapeHtml(g.wallet)}">${displaySymbol(g.wallet)}</span>${badges}
        <span class="when">${g.n} move${g.n === 1 ? "" : "s"} · ${agoSpan(g.last_ts)}</span>
      </div>
      <div class="toks">${toks}</div>
      <div class="actions">
        <button class="btn small primary" data-merge title="merge this wallet into ${escapeHtml(s.person)} — positions rebuild and both wallets share one bubble">👥 it's ${escapeHtml(s.person)} — merge</button>
        ${ex ? `<a class="btn small" href="${ex[1]}${escapeHtml(g.wallet)}" target="_blank" rel="noopener">${ex[0]} ↗</a>` : ""}
        ${isEvm ? `<a class="btn small" href="https://debank.com/profile/${escapeHtml(g.wallet)}" target="_blank" rel="noopener">DeBank ↗</a>` : ""}
        <button class="btn small" data-copy>⧉ copy</button>
        <button class="btn small" data-dismiss title="not their wallet (exchange, friend…) — hide this suggestion for good">✕ not theirs</button>
      </div>
    </div>`;
  }).join("");
}

document.getElementById("wmBody").addEventListener("click", async (e) => {
  const row = e.target.closest(".sug-row");
  if (!row) return;
  const g = walletsData.get(row.dataset.wallet);
  if (!g) return;
  const btn = e.target.closest("button, a");
  if (!btn || btn.tagName === "A") return;

  if (btn.hasAttribute("data-copy")) {
    try {
      await navigator.clipboard.writeText(g.wallet);
      btn.textContent = "✓ copied";
      setTimeout(() => { btn.textContent = "⧉ copy"; }, 1500);
    } catch (_) { toast("Couldn't access the clipboard.", 4000); }
    return;
  }

  if (btn.hasAttribute("data-dismiss")) {
    btn.disabled = true;
    try {
      const res = await fetch("/api/wallet_suggestions/dismiss", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trader_key: g.wallet }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || res.status);
      loadWalletSuggestions();
    } catch (err) {
      btn.disabled = false;
      toast(`⚠️ Couldn't dismiss: ${escapeHtml(err.message)}`);
    }
    return;
  }

  if (btn.hasAttribute("data-merge")) {
    const s = g.senders[0];
    btn.disabled = true;
    btn.textContent = "merging…";
    try {
      const res = await fetch("/api/merge", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ person: s.person, keys: [s.key, g.wallet], color: s.color || null }),
      });
      const out = await res.json();
      if (!res.ok) throw new Error(out.detail || res.status);
      toast(`✅ <strong>${displaySymbol(g.wallet)}</strong> is now part of <strong>${escapeHtml(s.person)}</strong> — positions rebuilt.`, 8000, "ok");
      loadWalletSuggestions();
      await load(false);
      if (!panel.hidden) { loadTraders(); loadGroups(); }
    } catch (err) {
      btn.disabled = false;
      btn.textContent = `👥 it's ${s.person} — merge`;
      toast(`⚠️ Merge failed: ${escapeHtml(err.message)}`);
    }
  }
});

walletsBtn.addEventListener("click", openWalletsModal);
document.getElementById("wmClose").addEventListener("click", closeWalletsModal);
walletsModal.addEventListener("click", (e) => { if (e.target === walletsModal) closeWalletsModal(); });

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

// Sliders write the numbers; the range can't cross — dragging one past the
// other pushes it along, so the filter never silently empties the graph.
function setMcapRange(min, max) {
  mcapMin = Math.max(0, min || 0);
  mcapMax = Math.max(0, max || 0);
  if (mcapMax && mcapMin > mcapMax) mcapMax = mcapMin;
}
controls.minMcap.addEventListener("input", () => {
  const v = sliderUsd(+controls.minMcap.value);
  setMcapRange(v, mcapMax && mcapMax < v ? v : mcapMax);
});
controls.maxMcap.addEventListener("input", () => {
  const pos = +controls.maxMcap.value;
  const v = pos >= SLIDER_MAX ? 0 : sliderUsd(pos);
  setMcapRange(v && mcapMin > v ? v : mcapMin, v);
});
Object.values(controls).forEach((el) => el.addEventListener("input", load));

// Typed amounts: commit on Enter or blur; Escape restores the current value.
function bindMoneyBox(box, apply) {
  const commit = () => {
    const v = parseMoney(box.value);
    if (v === null) { box.classList.add("invalid"); return; }
    box.classList.remove("invalid");
    apply(v);
    box.blur();
    load();
  };
  box.addEventListener("keydown", (e) => {
    if (e.key === "Enter") commit();
    if (e.key === "Escape") { box.blur(); syncLabels(); }
  });
  box.addEventListener("change", commit);
  box.addEventListener("focus", () => box.select());
}
bindMoneyBox(minBox, (v) => setMcapRange(v, mcapMax && mcapMax < v ? v : mcapMax));
bindMoneyBox(maxBox, (v) => setMcapRange(v && mcapMin > v ? v : mcapMin, v));
document.getElementById("reload").addEventListener("click", load);
window.addEventListener("resize", () => {
  if (!sim || !simCtx) return;
  const { width, height } = svg.node().getBoundingClientRect();
  simCtx = { ...simCtx, width, height };
  configureForces();
  sim.alpha(0.3).restart();
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

// Only ever called from inside a user gesture: constructing an AudioContext
// anywhere else makes Chrome log "The AudioContext was not allowed to start".
function ensureAudio() {
  if (!audioCtx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    audioCtx = new AC();
  }
  if (audioCtx.state === "suspended") audioCtx.resume().catch(() => {});
  return audioCtx;
}

// Keep listening until audio is actually unlocked — a first click while sound
// is muted must not use up the only chance to unlock it.
function unlockAudio() {
  if (!soundOn) return;
  const ctx = ensureAudio();
  if (ctx && ctx.state === "running") {
    window.removeEventListener("pointerdown", unlockAudio);
    window.removeEventListener("keydown", unlockAudio);
  }
}
window.addEventListener("pointerdown", unlockAudio);
window.addEventListener("keydown", unlockAudio);

function ding() {
  if (!soundOn) return;
  // A ding from the background poll is not a gesture, so it can only use a
  // context that a gesture already unlocked; before that it stays silent.
  const ctx = audioCtx;
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

/* ---------- find by contract address ----------
 * A token the current filters draw is focused in place; anything else —
 * filtered out, outside the top-N, hidden, or long since exited — opens in
 * its own window with every holder attached and everything known about it. */

const caInput = document.getElementById("caSearch");
const normKey = (s) => {
  const v = s.trim();
  return /^0x[a-fA-F0-9]{40}$/.test(v) ? v.toLowerCase() : v;
};

function findOnGraph(q) {
  const ql = normKey(q).toLowerCase();
  return currentData.nodes.find((n) => n.kind === "token" &&
    (String(n.token_key).toLowerCase() === ql || (n.symbol || "").toLowerCase() === ql));
}

async function searchToken(q) {
  if (!q.trim()) return;
  const hit = findOnGraph(q);
  if (hit) {
    closeTokenModal();
    const gEl = gNodes.selectAll("g.node").filter((d) => d.id === hit.id).node();
    if (gEl) selectToken(hit, gEl);
    focusOn(hit);
    return;
  }
  caInput.disabled = true;
  try {
    const res = await fetch(`/api/token?q=${encodeURIComponent(normKey(q))}`);
    if (res.status === 404) {
      toast(`No token seen for <code>${escapeHtml(q.trim())}</code> — nobody tracked has traded it.`, 6000);
      return;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    openTokenModal(await res.json());
  } catch (err) {
    toast(`Search failed: ${escapeHtml(err.message)}`, 6000);
  } finally {
    caInput.disabled = false;
  }
}

const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

caInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); searchToken(caInput.value); }
  if (e.key === "Escape") caInput.blur();
});

/* ---------- token window ----------
 * The same bubbles as the main graph — token in the middle, holders in
 * orbit, same styling and tooltips — drawn for one token in a modal, with
 * the side column spelling out what the bubbles only hint at. Opened by
 * right-clicking a token bubble, or by searching for a token that isn't
 * drawn. */

const tokenModal = document.getElementById("tokenModal");
const tmGraph = d3.select("#tmGraph");
const tmRoot = tmGraph.append("g");
const tmLinks = tmRoot.append("g").attr("class", "links");
const tmNodes = tmRoot.append("g").attr("class", "nodes");
let tmSim = null;
let tmData = null; // what the open window shows; null when closed
const tmVerify = document.getElementById("tmVerify");
const tmMcap = document.getElementById("tmMcap");

// Right-click on a token bubble: fetch the full picture and open its window.
async function openTokenModalFor(d) {
  if (tmData && tmData.token.id === d.id) return;
  try {
    const res = await fetch(`/api/token?q=${encodeURIComponent(String(d.token_key))}`);
    if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
    openTokenModal(await res.json());
  } catch (err) {
    toast(`Couldn't load token: ${escapeHtml(err.message)}`, 6000);
  }
}

function openTokenModal(data) {
  tmData = data;
  if (tokenModal.hidden) {
    tokenModal.hidden = false;
    raise(tokenModal);
  }
  renderTokenModal(data);
}

function renderTokenModal(data) {
  const t = data.token;
  document.getElementById("tmTitle").textContent = displaySymbol(t.symbol);
  document.getElementById("tmSub").textContent =
    `${t.name && t.name !== t.symbol ? `${t.name} · ` : ""}${t.n_holders} holding · ${t.n_positions} positions`;
  // Ticker-only tokens have no contract address: nothing to ask the chain
  // or DexScreener about.
  tmVerify.hidden = tmMcap.hidden = !t.resolved;
  renderTokenSide(data);
  renderMiniGraph(data);
}

// Re-fetch the token the window shows (after a verify / mcap refresh) and
// redraw it in place — unless the user has closed it or opened another.
async function reloadTokenModal(t) {
  if (!tmData || tmData.token.id !== t.id) return;
  try {
    const res = await fetch(`/api/token?q=${encodeURIComponent(String(t.token_key))}`);
    if (!res.ok) return;
    const data = await res.json();
    if (tmData && tmData.token.id === t.id) {
      tmData = data;
      renderTokenModal(data);
    }
  } catch (_) { /* the window keeps its old numbers */ }
}

function closeTokenModal() {
  if (tokenModal.hidden) return;
  tokenModal.hidden = true;
  tmData = null;
  if (tmSim) tmSim.stop();
  hideTip();
}

// Verify holders: every listed wallet's real share, straight from the chain.
tmVerify.addEventListener("click", async () => {
  if (!tmData) return;
  const t = tmData.token;
  tmVerify.disabled = true;
  tmVerify.textContent = "verifying…";
  const stopProgress = trackVerifyProgress(`verifying ${displaySymbol(t.symbol)}`, 1);
  try {
    const res = await fetch("/api/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chain: t.chain, token_key: t.token_key }),
    });
    const out = await res.json();
    if (!res.ok) throw new Error(out.detail || res.status);
    const lines = out.results
      .map((r) => r.error
        ? `${displaySymbol(r.trader_key)}: ${r.error}`
        : `${displaySymbol(r.trader_key)}: ${fmtPct(r.pct)} on-chain`)
      .join("<br>");
    toast(
      `✅ <strong>${displaySymbol(out.symbol || t.symbol)}</strong> checked on-chain ` +
      `(${out.verified}/${out.checked} wallets)<br>${lines}`,
      12000, "ok");
    await Promise.all([reloadTokenModal(t), load(false)]);
  } catch (err) {
    toast(`⚠️ Verify <strong>${displaySymbol(t.symbol)}</strong> failed: ${escapeHtml(err.message)}`);
  } finally {
    stopProgress();
    tmVerify.disabled = false;
    tmVerify.textContent = "✓ verify holders";
  }
});

// Verify market cap: one DexScreener lookup for this token, freshest wins.
tmMcap.addEventListener("click", async () => {
  if (!tmData) return;
  if (mcapBusy) { toast("⚠️ A market-cap refresh is already running — try again in a moment."); return; }
  const t = tmData.token;
  mcapBusy = true; // keeps the automatic refresh from colliding (409)
  tmMcap.disabled = true;
  tmMcap.textContent = "fetching…";
  rebuildProgress.hidden = false;
  rebuildFill.classList.add("indeterminate");
  rebuildFill.style.width = "0%";
  rebuildLabel.textContent = `fetching market cap — ${displaySymbol(t.symbol)}`;
  try {
    const res = await fetch("/api/mcaps", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tokens: [{ chain: t.chain, token_key: t.token_key }] }),
    });
    const out = await res.json();
    if (!res.ok) throw new Error(out.detail || res.status);
    if (!out.updated) {
      toast(out.failed
        ? `⚠️ DexScreener didn't answer for <strong>${displaySymbol(t.symbol)}</strong> — try again shortly.`
        : `⚠️ DexScreener doesn't know <strong>${displaySymbol(t.symbol)}</strong> — market cap unchanged.`);
      return;
    }
    await Promise.all([reloadTokenModal(t), load(false)]);
    const fresh = tmData && tmData.token.id === t.id ? tmData.token : t;
    toast(`✅ <strong>${displaySymbol(t.symbol)}</strong> market cap now ${fmtUsd(fresh.mcap_usd)}` +
      (fresh.fdv_usd != null ? ` · fdv ${fmtUsd(fresh.fdv_usd)}` : ""), 8000, "ok");
  } catch (err) {
    toast(`⚠️ Market cap check failed: ${escapeHtml(err.message)}`);
  } finally {
    mcapLastRun = Date.now();
    rebuildFill.classList.remove("indeterminate");
    rebuildProgress.hidden = true;
    mcapBusy = false;
    tmMcap.disabled = false;
    tmMcap.textContent = "💲 verify market cap";
  }
});

document.getElementById("tmClose").addEventListener("click", closeTokenModal);
tokenModal.addEventListener("click", (e) => { if (e.target === tokenModal) closeTokenModal(); });
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!holderModal.hidden) closeHolderModal();
  else if (!walletsModal.hidden) closeWalletsModal();
  else closeTokenModal();
});

function renderMiniGraph(data) {
  const nodes = data.nodes.map((n) => ({ ...n }));
  const links = data.links.map((l) => ({ ...l }));
  const radius = radiusScales(nodes);
  nodes.forEach((n) => {
    n.r = radius(n);
    if (n.kind === "person" && !n.color) n.color = personColor(n.person);
  });
  // One big token bubble in a small window: cap the token so its ring of
  // holders still fits around it.
  const token = nodes.find((n) => n.kind === "token");
  if (token) token.r = Math.min(token.r, 96);

  const { width, height } = tmGraph.node().getBoundingClientRect();

  const link = tmLinks.selectAll("line").data(links, linkKey).join("line")
    .attr("class", (d) => `link ${d.status === "SOLD" ? "sold" : ""}`);

  const node = tmNodes.selectAll("g.node").data(nodes, (d) => d.id).join((enter) => {
    const g = enter.append("g").attr("class", "node");
    g.append("circle");
    g.append("text").attr("class", "label");
    g.append("text").attr("class", "label sub");
    g.append("text").attr("class", "label sub entry");
    const badge = g.filter((d) => d.kind === "token").append("g").attr("class", "chain");
    badge.append("circle");
    badge.append("use");
    badge.append("text");
    return g;
  });
  decorateNodes(node);

  node
    .on("mousemove", (e, d) => showTip(e, d))
    .on("mouseleave", hideTip)
    .on("contextmenu", (e, d) => {
      e.preventDefault();
      e.stopPropagation();
      if (d.kind === "person") openHolderModal(d);
    })
    .call(d3.drag()
      .on("start", (e, d) => { if (!e.active) tmSim.alphaTarget(0.25).restart(); d.fx = d.x; d.fy = d.y; })
      .on("drag", (e, d) => { d.fx = e.x; d.fy = e.y; })
      .on("end", (e, d) => { if (!e.active) tmSim.alphaTarget(0); d.fx = null; d.fy = null; }));

  if (tmSim) tmSim.stop();
  if (token) { token.fx = width / 2; token.fy = height / 2; } // the token anchors the picture
  tmSim = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(links).id((d) => d.id)
      .distance((l) => (l.target.r || 40) + (l.source.r || 12) + 6).strength(1))
    .force("charge", d3.forceManyBody().strength(-30))
    .force("collide", d3.forceCollide().radius((d) => d.r + 3).iterations(4))
    .force("x", d3.forceX(width / 2).strength(0.02))
    .force("y", d3.forceY(height / 2).strength(0.02))
    .on("tick", () => {
      link.attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y)
        .attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
      node.attr("transform", (d) => `translate(${d.x},${d.y})`);
    });
}

function renderTokenSide(data) {
  const t = data.token;
  const holders = data.nodes.filter((n) => n.kind === "person");
  const info = chainInfo(t);
  const side = document.getElementById("tmSide");
  const money = (v) => (v == null ? "—" : fmtUsd(v));
  const signed = (v) => (v == null ? "—" : `<span class="${v >= 0 ? "pos" : "neg"}">${v >= 0 ? "+" : "−"}${fmtUsd(Math.abs(v))}</span>`);

  let html = "";
  if (t.hidden) html += `<div class="modal-note">Hidden from the graph — restore it from the Tokens panel.</div>`;
  else if (t.dead) html += `<div class="modal-note">Everyone tracked has exited — not drawn on the graph.</div>`;
  else if (!findOnGraph(String(t.token_key))) {
    html += `<div class="modal-note">Not among the bubbles right now — outside the current chain, window, mcap, % or top-N filters.</div>`;
  }

  html += `<h4>Token</h4><dl class="kv">
    <dt>chain</dt><dd><span class="badge" style="background:${info.color}22;color:${info.color}">${escapeHtml(canonTag(t.chain_tag) || t.chain)}</span></dd>
    <dt>address</dt><dd>${t.resolved ? escapeHtml(t.token_key) : "— (ticker only)"}</dd>
    <dt>market cap</dt><dd>${money(t.mcap_usd)}</dd>
    <dt>fdv</dt><dd>${money(t.fdv_usd)}</dd>
    <dt>mcap seen</dt><dd>${agoSpan(t.mcap_as_of)}</dd>
    <dt>holding now</dt><dd>${t.n_holders} of ${t.n_positions}</dd>
    <dt>alerts</dt><dd>${t.n_events ?? "—"}</dd>
    <dt>first seen</dt><dd>${agoSpan(t.first_seen)}</dd>
    <dt>last action</dt><dd>${agoSpan(t.last_action)}</dd>
  </dl>`;
  if (t.resolved) {
    html += `<div class="modal-actions">
      <a class="btn small" href="${gmgnUrl(t)}" target="_blank" rel="noopener">📈 chart on GMGN</a>
      <button class="btn small" id="tmCopy">⧉ copy address</button>
    </div>`;
  }

  html += `<h4>Holders · ${holders.length}</h4>`;
  if (!holders.length) html += `<div class="panel-hint">No positions recorded.</div>`;
  for (const h of holders) {
    const sold = h.status === "SOLD";
    const pct = sold ? `sold · peak ${fmtPct(h.peak_pct)}` : fmtPct(h.pct_supply);
    html += `<div class="holder-row${sold ? " sold" : ""}" title="${escapeHtml(h.handle || "")}">
      <span class="dot" style="background:${h.color}"></span>
      <span class="name">${escapeHtml(h.person || h.handle || "?")}</span>
      <span class="pct">${pct}</span>
      <span class="meta">
        bought ${fmtPct(h.bought_pct)} · sold ${fmtPct(h.sold_pct)}${h.confidence === "low" ? " · est." : ""}<br>
        in ${money(h.invested_usd)} · out ${money(h.realized_usd)} · pnl ${signed(h.pnl_usd)}<br>
        entry @ ${money(h.avg_entry_mcap_usd || h.entry_mcap_usd)} · ${h.n_events} alert${h.n_events === 1 ? "" : "s"} ·
        ${agoSpan(h.first_seen)} → ${agoSpan(h.last_seen)}
      </span>
    </div>`;
  }
  side.innerHTML = html;

  const copy = document.getElementById("tmCopy");
  if (copy) {
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(String(t.token_key));
        copy.textContent = "✓ copied";
        setTimeout(() => { copy.textContent = "⧉ copy address"; }, 1500);
      } catch (_) { toast("Couldn't access the clipboard.", 4000); }
    });
  }
}

/* ---------- holder window ----------
 * Right-click a holder bubble: their position in that token in full, every token
 * the wallet holds underneath, and a button that asks the chain what the
 * wallet really holds of each. */

const holderModal = document.getElementById("holderModal");
const hmVerify = document.getElementById("hmVerify");
let holderData = null;

const fmtMoney = (v) => (v == null ? "—" : fmtUsd(v));
const fmtSigned = (v) => (v == null ? "—"
  : `<span class="${v >= 0 ? "pos" : "neg"}">${v >= 0 ? "+" : "−"}${fmtUsd(Math.abs(v))}</span>`);
const chainBadge = (t) => {
  const info = chainInfo(t);
  return `<span class="badge" style="background:${info.color}22;color:${info.color}">${escapeHtml(canonTag(t.chain_tag) || t.chain)}</span>`;
};

async function openHolderModal(d) {
  const p = new URLSearchParams({ trader_key: d.trader_key || "" });
  const tokenId = d.token_id || (d.id.startsWith("pos:") ? `token:${d.id.split(":").slice(1, 3).join(":")}` : "");
  const [, chain, ...rest] = tokenId.split(":");
  if (chain) { p.set("chain", chain); p.set("token_key", rest.join(":")); }
  try {
    const res = await fetch(`/api/holder?${p}`);
    if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
    holderData = await res.json();
  } catch (err) {
    toast(`Couldn't load holder: ${escapeHtml(err.message)}`, 6000);
    return;
  }
  holderModal.hidden = false;
  raise(holderModal);
  hideTip();
  renderHolderModal();
}

function closeHolderModal() {
  holderModal.hidden = true;
}

// Block explorer address pages, per canonical chain tag. An EVM wallet is the
// same address on every EVM chain, so a link is offered for each chain the
// wallet has actually traded on (from its positions), not the whole list.
const EXPLORERS = {
  SOL:    ["Solscan",      "https://solscan.io/account/"],
  ETH:    ["Etherscan",    "https://etherscan.io/address/"],
  BSC:    ["BscScan",      "https://bscscan.com/address/"],
  BASE:   ["Basescan",     "https://basescan.org/address/"],
  ARB:    ["Arbiscan",     "https://arbiscan.io/address/"],
  OP:     ["Etherscan",    "https://optimistic.etherscan.io/address/"],
  POLY:   ["Polygonscan",  "https://polygonscan.com/address/"],
  AVAX:   ["Snowscan",     "https://snowscan.xyz/address/"],
  BLAST:  ["Blastscan",    "https://blastscan.io/address/"],
  ABS:    ["Abscan",       "https://abscan.org/address/"],
  HYPE:   ["HyperEVMScan", "https://hyperevmscan.io/address/"],
  LINEA:  ["Lineascan",    "https://lineascan.build/address/"],
  SONIC:  ["Sonicscan",    "https://sonicscan.org/address/"],
  MONAD:  ["Monadscan",    "https://monadscan.com/address/"],
  UNI:    ["Uniscan",      "https://uniscan.xyz/address/"],
  ZK:     ["Era explorer", "https://era.zksync.network/address/"],
  SCROLL: ["Scrollscan",   "https://scrollscan.com/address/"],
  MANTLE: ["Mantlescan",   "https://mantlescan.xyz/address/"],
  BERA:   ["Berascan",     "https://berascan.com/address/"],
  SEI:    ["Seitrace",     "https://seitrace.com/address/"],
  CRO:    ["Cronoscan",    "https://cronoscan.com/address/"],
  XLAYER: ["OKLink",       "https://www.oklink.com/xlayer/address/"],
  WORLD:  ["Worldscan",    "https://worldscan.org/address/"],
  INK:    ["Ink explorer", "https://explorer.inkonchain.com/address/"],
  PLASMA: ["Plasmascan",   "https://plasmascan.to/address/"],
  GNOSIS: ["Gnosisscan",   "https://gnosisscan.io/address/"],
  CELO:   ["Celoscan",     "https://celoscan.io/address/"],
  TRON:   ["Tronscan",     "https://tronscan.org/#/address/"],
};

function renderHolderLinks(h) {
  const box = document.getElementById("hmLinks");
  if (!h.is_wallet) { box.hidden = true; box.innerHTML = ""; return; }
  const addr = String(h.trader_key);
  const isEvm = /^0x[a-fA-F0-9]{40}$/.test(addr);

  // Chains this wallet has traded on, the clicked position's chain first.
  const tags = [];
  const seen = new Set();
  for (const e of [h.focus, ...h.positions].filter(Boolean)) {
    const t = e.token;
    const tag = canonTag(t.chain_tag) || (t.chain === "solana" ? "SOL" : "");
    if (tag && !seen.has(tag)) { seen.add(tag); tags.push(tag); }
  }

  const a = (label, url, tag) => {
    const info = tag ? CHAINS[tag] : null;
    const badge = info
      ? `<span class="badge" style="background:${info.color}22;color:${info.color}">${escapeHtml(tag)}</span>` : "";
    return `<a class="btn small" href="${escapeHtml(url + addr)}" target="_blank" rel="noopener" title="${escapeHtml(addr)} on ${escapeHtml(label)}">${badge}${escapeHtml(label)} ↗</a>`;
  };
  let html = `<span class="cap">wallet</span><span class="addr" title="${escapeHtml(addr)}">${displaySymbol(addr)}</span>`;
  const known = tags.filter((t) => EXPLORERS[t]);
  for (const tag of known) html += a(EXPLORERS[tag][0], EXPLORERS[tag][1], tag);
  // Trading-focused wallet pages: GMGN for the chain in focus, DeBank across
  // every EVM chain at once (also the fallback when a chain has no explorer above).
  const gm = tags.map((t) => GMGN_SLUGS[t]).find(Boolean);
  if (gm) html += a("GMGN wallet", `https://gmgn.ai/${gm}/address/`);
  if (isEvm) html += a("DeBank", "https://debank.com/profile/");
  html += `<button class="btn small" id="hmCopy" title="copy the full address">⧉ copy</button>`;
  box.innerHTML = html;
  box.hidden = false;
  document.getElementById("hmCopy").addEventListener("click", async (e) => {
    try {
      await navigator.clipboard.writeText(addr);
      e.currentTarget.textContent = "✓ copied";
      setTimeout(() => { const b = document.getElementById("hmCopy"); if (b) b.textContent = "⧉ copy"; }, 1500);
    } catch (_) { toast("Couldn't access the clipboard.", 4000); }
  });
}

function renderHolderModal() {
  const h = holderData;
  const name = h.person || h.handle || displaySymbol(h.trader_key);
  document.getElementById("hmDot").style.background = h.color || personColor(name);
  document.getElementById("hmTitle").textContent = name;
  renderHolderLinks(h);
  document.getElementById("hmSub").innerHTML =
    `${h.handle && h.handle !== name ? `${escapeHtml(h.handle)} · ` : ""}` +
    `${h.is_wallet ? `<span title="${escapeHtml(h.trader_key)}">${displaySymbol(h.trader_key)}</span> · ` : ""}` +
    `${h.n_holding} holding · ${h.n_sold} exited`;
  const checkable = h.positions.filter((e) => e.status === "HOLDING" && e.token.resolved);
  hmVerify.disabled = !h.is_wallet || !checkable.length;
  hmVerify.title = !h.is_wallet
    ? "no full wallet address for this trader — nothing to check on-chain"
    : !checkable.length ? "no address-keyed holdings to check"
    : `check this wallet's real balance of ${checkable.length} token${checkable.length === 1 ? "" : "s"}, on-chain`;

  let html = "";
  const f = h.focus;
  if (f) {
    const t = f.token;
    const sold = f.status !== "HOLDING";
    const ver = f.verified;
    html += `<div class="focus-card">
      <div class="head">
        <span class="sym">${escapeHtml(displaySymbol(t.symbol))}</span>${chainBadge(t)}
        <span class="pill ${sold ? "exited" : "holding"}">${sold ? "exited" : "holding"}</span>
        <span class="mc">MC ${fmtMoney(t.mcap_usd)}${fdvDiffers(t) ? ` · FDV ${fmtMoney(t.fdv_usd)}` : ""}</span>
        <button class="btn small" data-show-token="${escapeHtml(String(t.token_key))}">show token</button>
      </div>
      <dl class="kv">
        <dt>${sold ? "peak share" : "share held"}</dt><dd>${fmtPct(sold ? f.peak_pct : f.pct_supply)}${f.confidence === "low" ? " (estimated)" : ""}</dd>
        <dt>bought / sold</dt><dd>${fmtPct(f.bought_pct)} / ${fmtPct(f.sold_pct)}</dd>
        <dt>invested</dt><dd>${fmtMoney(f.invested_usd)}</dd>
        <dt>realised</dt><dd>${fmtMoney(f.realized_usd)}</dd>
        <dt>pnl</dt><dd>${fmtSigned(f.pnl_usd)}</dd>
        <dt>entry mcap</dt><dd>${fmtMoney(f.avg_entry_mcap_usd || f.entry_mcap_usd)}${f.entry_mcap_usd && f.avg_entry_mcap_usd && f.entry_mcap_usd !== f.avg_entry_mcap_usd ? ` (first ${fmtMoney(f.entry_mcap_usd)})` : ""}</dd>
        <dt>alerts</dt><dd>${f.n_events}</dd>
        <dt>first → last</dt><dd>${agoSpan(f.first_seen)} → ${agoSpan(f.last_seen)}</dd>
        <dt>on-chain</dt><dd>${ver ? `${fmtPct(ver.pct)} · checked ${agoSpan(ver.ts)}` : "not verified yet"}</dd>
        <dt>token</dt><dd>${t.n_holders} tracked holding · ${t.n_positions} positions · last action ${agoSpan(t.last_action)}</dd>
      </dl>
    </div>`;
  }

  const holding = h.positions.filter((e) => e.status === "HOLDING");
  const exited = h.positions.filter((e) => e.status !== "HOLDING");
  const row = (e) => {
    const t = e.token;
    const sold = e.status !== "HOLDING";
    const ver = e.verified;
    let verHtml = "";
    if (ver) {
      const off = e.pct_supply != null && ver.pct != null && Math.abs(ver.pct - e.pct_supply) > Math.max(0.01, e.pct_supply * 0.1);
      verHtml = `<span class="ver${off ? " off" : ""}" title="on-chain share, checked ${fmtAgo(ver.ts)}">⛓ ${fmtPct(ver.pct)}</span>`;
    }
    return `<div class="tok-row${sold ? " sold" : ""}" data-show-token="${escapeHtml(String(t.token_key))}" title="open this token">
      <span class="sym">${escapeHtml(displaySymbol(t.symbol))} ${chainBadge(t)}</span>
      <span class="num">${fmtPct(sold ? e.peak_pct : e.pct_supply)}<small>${sold ? "peak" : "share"}</small></span>
      <span class="num">${fmtMoney(t.mcap_usd)}<small>mcap</small></span>
      <span class="num">${fmtSigned(e.pnl_usd)}<small>pnl</small></span>
      <span class="meta">in ${fmtMoney(e.invested_usd)} · out ${fmtMoney(e.realized_usd)} · entry @ ${fmtMoney(e.avg_entry_mcap_usd || e.entry_mcap_usd)} · ${e.n_events} alert${e.n_events === 1 ? "" : "s"} · ${agoSpan(e.last_seen)} ${verHtml}</span>
    </div>`;
  };
  html += `<h4>Holding · ${holding.length}</h4>`;
  html += holding.length ? holding.map(row).join("") : `<div class="panel-hint">Nothing held right now.</div>`;
  if (exited.length) {
    html += `<details><summary>${exited.length} exited position${exited.length === 1 ? "" : "s"}</summary>${exited.map(row).join("")}</details>`;
  }
  const body = document.getElementById("hmBody");
  body.innerHTML = html;
  body.querySelectorAll("[data-show-token]").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      closeHolderModal();
      searchToken(el.dataset.showToken);
    });
  });
}

document.getElementById("hmClose").addEventListener("click", closeHolderModal);
holderModal.addEventListener("click", (e) => { if (e.target === holderModal) closeHolderModal(); });

hmVerify.addEventListener("click", async () => {
  if (!holderData) return;
  const h = holderData;
  const tokens = h.positions
    .filter((e) => e.status === "HOLDING" && e.token.resolved)
    .map((e) => ({ chain: e.token.chain, token_key: e.token.token_key }));
  if (!tokens.length) return;
  hmVerify.disabled = true;
  hmVerify.textContent = "verifying…";
  const label = `verifying ${h.person || h.handle || displaySymbol(h.trader_key)}`;
  const stopProgress = trackVerifyProgress(label, tokens.length);
  try {
    const res = await fetch("/api/verify_wallet", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ trader_key: h.trader_key, tokens }),
    });
    const out = await res.json();
    if (!res.ok) {
      toast(`⚠️ Verify failed: ${escapeHtml(out.detail || res.status)}`);
    } else {
      const lines = out.results
        .map((r) => r.error
          ? `${escapeHtml(displaySymbol(r.symbol || r.token_key))}: ${escapeHtml(r.error)}`
          : `${escapeHtml(displaySymbol(r.symbol || r.token_key))}: ${fmtPct(r.pct)} on-chain`)
        .join("<br>");
      toast(`✅ <strong>${escapeHtml(h.person || h.handle || displaySymbol(h.trader_key))}</strong> checked on-chain ` +
        `(${out.verified}/${out.checked} tokens)<br>${lines}`, 12000, "ok");
      // Fresh numbers: re-read the wallet (verified shares, rebuilt positions)
      // and let the graph pick the rebuild up without losing the view.
      const f = h.focus;
      const p = new URLSearchParams({ trader_key: h.trader_key });
      if (f) { p.set("chain", f.token.chain); p.set("token_key", f.token.token_key); }
      const again = await fetch(`/api/holder?${p}`);
      if (again.ok) { holderData = await again.json(); renderHolderModal(); }
      load(false, true);
    }
  } catch (err) {
    toast(`⚠️ Verify failed: ${escapeHtml(err.message)}`);
  } finally {
    stopProgress();
    hmVerify.textContent = "✓ verify holdings";
    if (holderData) renderHolderModal(); // restores the button's enabled state
  }
});

/* ---------- per-token action buttons ---------- */

const nodeActions = document.getElementById("nodeActions");
const actVerify = document.getElementById("actVerify");
const actChart = document.getElementById("actChart");
const actHide = document.getElementById("actHide");
let selectedToken = null; // { d, circle }

// gmgn.ai path slug per (canonical) chain tag: gmgn.ai/<slug>/token/<address>
const GMGN_SLUGS = {
  SOL: "sol", ETH: "eth", BSC: "bsc", BASE: "base", RH: "robinhood",
  HYPE: "hyperevm", ARB: "arb", ABS: "abstract", BLAST: "blast", TRON: "tron",
  MONAD: "monad",
};

function gmgnUrl(d) {
  const tag = canonTag(d.chain_tag);
  const slug = GMGN_SLUGS[tag] || (d.chain === "solana" ? "sol" : tag.toLowerCase() || "eth");
  return `https://gmgn.ai/${slug}/token/${d.token_key}`;
}

function selectToken(d, gEl) {
  selectedToken = { d, circle: gEl.querySelector("circle") };
  // Ticker-keyed tokens have no contract address: nothing to chart or
  // verify — but hiding still works, so the popup stays available.
  actVerify.hidden = actChart.hidden = !d.resolved;
  // Not raise()d: this is a map annotation that follows its bubble, so it must
  // stay below dropdowns, panels and windows (CSS z-index 14) or it paints
  // over an open chain/user menu whenever the bubble drifts underneath it.
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
  const stopProgress = trackVerifyProgress(`verifying ${displaySymbol(d.symbol)}`, 1);
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
    stopProgress();
    actVerify.disabled = false;
    actVerify.textContent = "✓ verify holders";
  }
});

/* ---------- token blacklist ---------- */

actHide.addEventListener("click", async () => {
  if (!selectedToken) return;
  const { d } = selectedToken;
  try {
    const res = await fetch("/api/blacklist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chain: d.chain, token_key: d.token_key }),
    });
    const out = await res.json();
    if (!res.ok) throw new Error(out.detail || res.status);
    clearTokenSelection();
    toast(`🚫 <strong>${displaySymbol(d.symbol)}</strong> hidden — restore it from the Tokens panel.`, 7000);
    load(false);
    if (!tokenPanel.hidden) loadBlacklist();
  } catch (err) {
    toast(`⚠️ Hide failed: ${err.message}`);
  }
});

async function loadBlacklist() {
  const listEl = document.getElementById("blacklistList");
  try {
    const res = await fetch("/api/blacklist");
    const data = await res.json();
    document.getElementById("blacklistMeta").textContent =
      data.tokens.length ? `${data.tokens.length} hidden` : "";
    listEl.innerHTML = "";
    if (!data.tokens.length) {
      listEl.innerHTML = `<div class="panel-hint">Nothing hidden. Click a token
        bubble, then 🚫 hide.</div>`;
      return;
    }
    for (const t of data.tokens) {
      const row = document.createElement("div");
      row.className = "group-row";
      const main = document.createElement("div");
      main.className = "trader-main";
      main.innerHTML =
        `<div class="trader-name">${displaySymbol(t.symbol || t.token_key)}` +
        `<span class="chain-tag">${t.chain}</span></div>`;
      const btn = document.createElement("button");
      btn.className = "btn small";
      btn.textContent = "Restore";
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        await fetch("/api/blacklist/remove", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chain: t.chain, token_key: t.token_key }),
        });
        await Promise.all([loadBlacklist(), load(false)]);
      });
      row.append(main, btn);
      listEl.append(row);
    }
  } catch (_) { /* transient */ }
}

/* ---------- notification feed drawer ---------- */

const feedPanel = document.getElementById("feedPanel");
const feedList = document.getElementById("feedList");
const feedSeg = document.getElementById("feedSeg");
let feedKind = "all";

function feedRowHtml(it) {
  const when = agoSpan(it.ts);
  if (it.type === "OTHER") {
    return `<div class="head"><span class="pill other">INFO</span>
        <span class="sym">${it.title || "(no text)"}</span>${when}</div>` +
      (it.detail ? `<div class="body">${it.detail}</div>` : "");
  }
  // Wallet-to-wallet moves are not trades: their own pill, and the other
  // wallet named instead of a dollar figure (there is none).
  const xferOut = it.type === "TRANSFER_OUT";
  const xferIn = it.type === "TRANSFER_IN";
  const pill = it.type === "BUY"
    ? `<span class="pill buy">BUY</span>`
    : xferOut ? `<span class="pill xfer" title="tokens moved to another wallet — not a sale">MOVE →</span>`
    : xferIn ? `<span class="pill xfer" title="tokens received from another wallet — not a buy">← MOVE</span>`
    : it.exit_kind === "full" || it.is_exit
      ? `<span class="pill sell" title="sold the whole position — nothing left in the wallet">EXIT</span>`
      : `<span class="pill sell" title="${it.exit_kind === "partial" ? "sold part of the position" : "sell — history too thin to say how much of the bag"}">SELL</span>`;
  // Partial sells say how much of the bag went ("sold 38% of bag"), so a
  // trim and a near-exit read differently at a glance.
  const bagBit = it.type === "SELL" && it.exit_kind === "partial" && it.sold_frac != null
    ? `sold ${Math.round(it.sold_frac * 100)}% of bag`
    : null;
  const bits = [
    it.who ? displaySymbol(String(it.who)) : null,
    it.counterparty ? `${xferIn ? "from" : "to"} ${displaySymbol(String(it.counterparty))}` : null,
    bagBit,
    it.pct_supply != null ? fmtPct(it.pct_supply) : null,
    it.amount_usd != null ? fmtUsd(it.amount_usd) : null,
    it.mcap_usd != null ? `MC ${fmtUsd(it.mcap_usd)}` : null,
  ].filter(Boolean).join(" · ");
  return `<div class="head">${pill}
      <span class="sym">${displaySymbol(it.symbol)}</span>
      ${it.chain_tag ? `<span class="badge">${it.chain_tag}</span>` : ""}${when}</div>
    <div class="body">${bits}</div>`;
}

/* Feed rows: click goes to the token's bubble; right-click opens the alert's
 * own links (TX, chart sites, wallet...) as a quick-link menu. */
function makeFeedRow(it) {
  const row = document.createElement("div");
  row.className = `feed-row${it.token_key ? " linked" : ""}`;
  row.innerHTML = feedRowHtml(it);
  row.addEventListener("click", () => goToToken(it));
  row.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    openLinkMenu(it, e.clientX, e.clientY);
  });
  return row;
}

function goToToken(it) {
  if (!it.token_key) return;
  const id = `token:${it.chain}:${it.token_key}`;
  const d = currentData.nodes.find((n) => n.id === id);
  if (!d || !Number.isFinite(d.x)) {
    toast(`<strong>${displaySymbol(it.symbol)}</strong> isn't on the graph with the current filters.`, 4000);
    return;
  }
  const gEl = [...document.querySelectorAll("g.node")].find((el) => d3.select(el).datum() === d);
  if (gEl) selectToken(d, gEl);
  focusOn(d);
}

const linkMenu = document.getElementById("linkMenu");
const LINK_ICONS = { tx: "TX", chart: "📈", wallet: "👛", token: "T", block: "#", telegram: "TG", other: "↗" };

async function openLinkMenu(it, x, y) {
  linkMenu.innerHTML = `<div class="ctx-head">${it.symbol ? displaySymbol(it.symbol) : "alert"} · links</div>
    <div class="ctx-empty">loading…</div>`;
  linkMenu.hidden = false;
  raise(linkMenu);
  placeMenu(x, y);
  if (!it.raw_id) {
    linkMenu.querySelector(".ctx-empty").textContent = "no source message for this row";
    return;
  }
  try {
    const res = await fetch(`/api/message/${it.raw_id}/links`);
    const data = await res.json();
    if (linkMenu.hidden) return;
    const items = data.links.map((l) =>
      `<a class="ctx-item" href="${l.url}" target="_blank" rel="noopener noreferrer" title="${l.url}">
         <span class="ico ${l.kind}">${LINK_ICONS[l.kind] || "↗"}</span>
         <span class="label">${l.label}</span><span class="host">${l.host}</span></a>`).join("");
    linkMenu.innerHTML = `<div class="ctx-head">${it.symbol ? displaySymbol(it.symbol) : "alert"} · ${data.links.length} links</div>` +
      (items || `<div class="ctx-empty">this alert carried no links</div>`);
    placeMenu(x, y);
  } catch (_) {
    linkMenu.querySelector(".ctx-empty").textContent = "couldn't load links";
  }
}

function placeMenu(x, y) {
  const w = linkMenu.offsetWidth, h = linkMenu.offsetHeight;
  linkMenu.style.left = `${Math.max(4, Math.min(window.innerWidth - w - 4, x))}px`;
  linkMenu.style.top = `${Math.max(4, Math.min(window.innerHeight - h - 4, y))}px`;
}

function closeLinkMenu() { linkMenu.hidden = true; }
document.addEventListener("click", (e) => { if (!linkMenu.contains(e.target)) closeLinkMenu(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeLinkMenu(); });
document.addEventListener("scroll", closeLinkMenu, true);
linkMenu.addEventListener("click", (e) => { if (e.target.closest("a")) closeLinkMenu(); });

async function loadFeed() {
  if (feedPanel.hidden) return;
  try {
    const res = await fetch(`/api/feed?kind=${feedKind}&limit=100`);
    const data = await res.json();
    document.getElementById("feedMeta").textContent = `${data.items.length} shown`;
    feedList.innerHTML = "";
    for (const it of data.items) feedList.append(makeFeedRow(it));
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

feedToggleBtn.addEventListener("click", () => {
  feedPanel.hidden = !feedPanel.hidden;
  if (!feedPanel.hidden) loadFeed();
  syncMapButtons();
});
document.getElementById("feedClose").addEventListener("click", () => {
  feedPanel.hidden = true;
  syncMapButtons();
});

// Deep link: open the page with #feed to start with the drawer expanded.
if (location.hash.includes("feed")) {
  feedPanel.hidden = false;
  loadFeed();
  syncMapButtons();
}

/* ---------- rebuild with timeframe ----------
 * POST /api/rebuild {days} re-fetches Telegram that far back, re-parses, and
 * rebuilds positions. While the request is in flight we poll
 * /api/rebuild/status to drive the bar: the fetch phase has no known total
 * (indeterminate slide + running count), the parse phase is a real fraction. */

const rebuildBtn = document.getElementById("rebuildBtn");
const rebuildProgress = document.getElementById("rebuildProgress");
const rebuildFill = rebuildProgress.querySelector(".progress-fill");
const rebuildLabel = document.getElementById("rebuildLabel");

function renderRebuildStatus(st) {
  let label;
  if (st.phase === "fetch") {
    label = `fetching from Telegram${st.detail ? ` (${st.detail.replace("bot_", "bot ")})` : ""}` +
      (st.done ? ` — ${st.done.toLocaleString()} alerts scanned` : "…");
  } else if (st.phase === "parse") {
    label = st.total
      ? `parsing alerts — ${st.done.toLocaleString()} / ${st.total.toLocaleString()}`
      : "parsing alerts…";
  } else {
    label = "building positions…";
  }
  rebuildLabel.textContent = label;

  if (st.phase === "parse" && st.total) {
    rebuildFill.classList.remove("indeterminate");
    rebuildFill.style.width = `${Math.round((st.done / st.total) * 100)}%`;
  } else {
    rebuildFill.classList.add("indeterminate");
  }
}

rebuildBtn.addEventListener("click", async () => {
  const days = +document.getElementById("rebuildDays").value;
  rebuildBtn.disabled = true;
  rebuildProgress.hidden = false;
  renderRebuildStatus({ phase: "fetch", done: 0 });

  const poll = setInterval(async () => {
    try {
      const st = await (await fetch("/api/rebuild/status")).json();
      if (st.active) renderRebuildStatus(st);
    } catch (_) { /* transient */ }
  }, 400);

  try {
    const res = await fetch("/api/rebuild", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ days: days || null }),
    });
    const out = await res.json();
    if (!res.ok) throw new Error(out.detail || res.status);
    toast(
      `✅ Rebuilt from ${days ? `the last ${days} day(s)` : "all captured history"} — ` +
      `${out.fetched} new alert(s) fetched, ${out.tokens} tokens, ` +
      `${out.positions} positions`, 9000, "ok");

load();
  } catch (err) {
    toast(`⚠️ Rebuild failed: ${err.message}`);
  } finally {
    clearInterval(poll);
    rebuildProgress.hidden = true;
    rebuildBtn.disabled = false;
  }
});

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

/* ---------- activity strip ----------
 * One day's alert activity, local midnight to midnight, in buckets of a
 * chosen size: transactions on the top strip, USD volume on the bottom,
 * each on its own scale (one axis per measure — never two measures on one
 * axis). Today re-fetches whenever new alerts land and every few minutes,
 * and is re-drawn each minute so the "now" marker keeps moving; any past
 * day can be picked, and the server keeps a 30-minute snapshot so it stays
 * viewable after the underlying events are rebuilt away. Clicking a bucket
 * lists its trades. */
const actSvg = d3.select("#activitySvg");
const actTip = document.getElementById("activityTip");
const actDate = document.getElementById("actDate");
const actToday = document.getElementById("actToday");
const actBucketSel = document.getElementById("actBucket");
const actPop = document.getElementById("activityPop");
let activity = null;
let actDay = null;      // epoch of the local midnight being viewed; null = today
let actBucket = +(localStorage.getItem("hg_act_bucket") || 1800);
let actOpen = null;     // index of the bucket whose trades are listed
actBucketSel.value = String(actBucket);

const dayStartOf = (date) => {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  return Math.floor(d.getTime() / 1000);
};
const localDayStart = () => dayStartOf(new Date());
const viewedDay = () => actDay ?? localDayStart();
const isoDay = (secs) => {
  const d = new Date(secs * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const hhmm = (secs) => {
  const d = new Date(secs * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};

async function loadActivity() {
  try {
    const p = new URLSearchParams({ start: viewedDay(), bucket: actBucket });
    if (selectedChains.size) p.set("chain", [...selectedChains].join(","));
    const res = await fetch(`/api/activity?${p}`);
    activity = await res.json();
    renderActivity();
  } catch (_) { /* transient — the next refresh will catch up */ }
}

function setActivityDay(secs) {
  const today = localDayStart();
  actDay = secs >= today ? null : secs;
  closeActivityPop();
  syncDayControls();
  loadActivity();
}

function syncDayControls() {
  const day = viewedDay();
  actDate.value = isoDay(day);
  actDate.max = isoDay(localDayStart());
  actToday.hidden = actDay === null;
  document.getElementById("actNext").disabled = actDay === null;
}

actDate.addEventListener("change", () => {
  if (!actDate.value) return;
  const [y, m, d] = actDate.value.split("-").map(Number);
  setActivityDay(dayStartOf(new Date(y, m - 1, d)));
});
document.getElementById("actPrev").addEventListener("click", () => setActivityDay(viewedDay() - 86400));
document.getElementById("actNext").addEventListener("click", () => setActivityDay(viewedDay() + 86400));
actToday.addEventListener("click", () => setActivityDay(localDayStart()));
actBucketSel.addEventListener("change", () => {
  actBucket = +actBucketSel.value;
  localStorage.setItem("hg_act_bucket", String(actBucket));
  closeActivityPop();
  loadActivity();
});

function renderActivity() {
  if (!activity) return;
  const svgEl = actSvg.node();
  const W = svgEl.clientWidth || 300;
  const H = 30;
  actSvg.attr("viewBox", `0 0 ${W} ${H}`).attr("width", W).attr("height", H);
  actSvg.selectAll("*").remove();

  const { start, bucket, buckets } = activity;
  const n = buckets.length;
  const slot = W / n;
  const gap = n > 24 ? 1.5 : 2;
  const bw = Math.max(1, slot - gap); // surface gap between bars
  const isToday = actDay === null;
  const nowIdx = isToday ? Math.floor((Date.now() / 1000 - start) / bucket) : n;

  document.getElementById("actTx").textContent = activity.tx.toLocaleString();
  document.getElementById("actUsd").textContent = fmtUsd(activity.usd);

  // Two strips, top = tx count, bottom = $ volume, each 13px tall.
  const strips = [
    { key: "tx", y0: 0, h: 13, max: d3.max(buckets, (b) => b.tx) || 0 },
    { key: "usd", y0: 17, h: 13, max: d3.max(buckets, (b) => b.usd) || 0 },
  ];

  // Hour guides at 06 / 12 / 18 plus the day edges.
  [0, 6, 12, 18, 24].forEach((hr) => {
    const x = (hr / 24) * W;
    actSvg.append("line").attr("class", "guide")
      .attr("x1", x).attr("x2", x).attr("y1", 0).attr("y2", H);
    if (hr < 24) {
      actSvg.append("text").attr("class", "hour")
        .attr("x", x + 2).attr("y", H - 1)
        .text(String(hr).padStart(2, "0"));
    }
  });

  strips.forEach((s) => {
    const scale = d3.scaleLinear().domain([0, s.max || 1]).range([0, s.h]);
    const barH = (b, i) => {
      if (i > nowIdx) return 0;
      const v = b[s.key];
      return v > 0 ? Math.max(1.5, scale(v)) : 0;
    };
    actSvg.selectAll(`rect.${s.key}`).data(buckets).join("rect")
      .attr("class", (b, i) => `bar ${s.key}${i === actOpen ? " open" : ""}`)
      .attr("x", (b, i) => i * slot + gap / 2)
      .attr("width", bw)
      .attr("y", (b, i) => s.y0 + s.h - barH(b, i))
      .attr("height", barH)
      .attr("rx", 1);
    // Baseline so an empty stretch still reads as "zero".
    actSvg.append("line").attr("class", "guide")
      .attr("x1", 0).attr("x2", W).attr("y1", s.y0 + s.h + 0.5).attr("y2", s.y0 + s.h + 0.5);
  });

  if (isToday) {
    const nowX = Math.min(W, Math.max(0, ((Date.now() / 1000 - start) / 86400) * W));
    actSvg.append("line").attr("class", "now")
      .attr("x1", nowX).attr("x2", nowX).attr("y1", -1).attr("y2", H + 1);
  }

  if (!activity.tx) {
    actSvg.append("text").attr("class", "empty-msg")
      .attr("x", W / 2).attr("y", H / 2 + 3.5).attr("text-anchor", "middle")
      .text(isToday ? "no alerts yet today" : "no alerts recorded that day");
  }

  const bucketAt = (e) => {
    const [mx] = d3.pointer(e, svgEl);
    return Math.max(0, Math.min(n - 1, Math.floor(mx / slot)));
  };

  // Hover: which bucket, how many trades, how much money. Click: list them.
  actSvg
    .on("mousemove", (e) => {
      const i = bucketAt(e);
      const b = buckets[i];
      const t0 = start + i * bucket;
      actTip.hidden = false;
      actTip.innerHTML = `<b>${hhmm(t0)}–${hhmm(t0 + bucket)}</b> · ` +
        `<b>${b.tx}</b> tx (${b.buys} buy / ${b.tx - b.buys} sell) · <b>${fmtUsd(b.usd)}</b>`;
      const box = document.getElementById("activity").getBoundingClientRect();
      const left = Math.max(0, Math.min(box.width - actTip.offsetWidth, e.clientX - box.left - actTip.offsetWidth / 2));
      actTip.style.left = `${left}px`;
      actSvg.selectAll("rect.bar").classed("hot", (d, j) => j === i);
    })
    .on("mouseleave", () => {
      actTip.hidden = true;
      actSvg.selectAll("rect.bar").classed("hot", false);
    })
    .on("click", (e) => {
      e.stopPropagation();
      openActivityPop(bucketAt(e), e.clientX);
    });
}

async function openActivityPop(i, clientX) {
  if (!activity) return;
  const { start, bucket, buckets } = activity;
  const b = buckets[i];
  const t0 = start + i * bucket;
  const t1 = t0 + bucket;
  actOpen = i;
  actSvg.selectAll("rect.bar").classed("open", (d, j) => j === i);

  document.getElementById("actPopTitle").textContent = `${hhmm(t0)}–${hhmm(t1)}`;
  document.getElementById("actPopMeta").textContent =
    `${b.tx} tx · ${b.buys} buy / ${b.tx - b.buys} sell · ${fmtUsd(b.usd)}`;
  const list = document.getElementById("actPopList");
  list.innerHTML = `<div class="note">loading…</div>`;
  actPop.hidden = false;
  raise(actPop);
  actTip.hidden = true;

  // Anchor under the clicked bucket, kept inside the viewport. The popover
  // lives outside the header (which is its own stacking context) so it can
  // be raised above modals like any other floating layer.
  const box = document.getElementById("activity").getBoundingClientRect();
  const left = Math.max(8, Math.min(window.innerWidth - actPop.offsetWidth - 8, clientX - actPop.offsetWidth / 2));
  actPop.style.left = `${left}px`;
  actPop.style.top = `${box.bottom + 8}px`;

  try {
    const p = new URLSearchParams({ start: t0, end: t1 });
    if (selectedChains.size) p.set("chain", [...selectedChains].join(","));
    const res = await fetch(`/api/activity/txs?${p}`);
    const data = await res.json();
    if (actOpen !== i) return; // user clicked elsewhere meanwhile
    actItems = data.items;
    actMissing = Math.max(0, b.tx - data.items.length);
    renderActPopList();
  } catch (_) {
    list.innerHTML = `<div class="note">Couldn't load trades — try again.</div>`;
  }
}

// The open bucket's trades, plus the buy/sell filter and sort applied to
// them client-side (the list is at most a few hundred rows).
let actItems = [];
let actMissing = 0;
let actKind = "all";                       // all | buy | sell
let actSort = { key: "ts", dir: -1 };      // dir: -1 = descending, 1 = ascending
const ACT_SORT_LABELS = { ts: "time", mcap_usd: "mcap", amount_usd: "$ amount", pct_supply: "% supply" };

function renderActPopList() {
  const list = document.getElementById("actPopList");
  const { key, dir } = actSort;
  const rows = actItems
    .filter((it) => actKind === "all" || String(it.type).toLowerCase() === actKind)
    .sort((a, b) => {
      const av = a[key], bv = b[key];
      if (av == null && bv == null) return b.ts - a.ts;
      if (av == null) return 1;               // unknown values always last
      if (bv == null) return -1;
      return (av - bv) * dir || b.ts - a.ts;   // ties: newest first
    });
  list.innerHTML = "";
  for (const it of rows) list.append(makeFeedRow(it));
  if (!actItems.length) {
    list.innerHTML = `<div class="note">No trades in this window.</div>`;
  } else if (!rows.length) {
    list.innerHTML = `<div class="note">No ${actKind}s in this window.</div>`;
  }
  if (actMissing) {
    // The snapshot remembers more than the event history still holds —
    // an older rebuild window dropped the rest.
    list.insertAdjacentHTML("beforeend",
      `<div class="note">${actMissing} more transaction(s) are in the day's totals
       but no longer in the event history (rebuilt with a shorter window).</div>`);
  }
}

document.getElementById("actPopKind").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-kind]");
  if (!btn) return;
  actKind = btn.dataset.kind;
  for (const b of btn.parentElement.children) b.classList.toggle("active", b === btn);
  renderActPopList();
});

document.getElementById("actPopSort").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-key]");
  if (!btn) return;
  const key = btn.dataset.key;
  // Same key again flips the direction; a new key starts descending
  // (newest / biggest first), which is what people look for.
  actSort = key === actSort.key ? { key, dir: -actSort.dir } : { key, dir: -1 };
  for (const b of btn.parentElement.children) {
    const active = b.dataset.key === actSort.key;
    b.classList.toggle("active", active);
    b.textContent = ACT_SORT_LABELS[b.dataset.key] + (active ? (actSort.dir < 0 ? " ▼" : " ▲") : "");
  }
  renderActPopList();
});

function closeActivityPop() {
  if (actPop.hidden) return;
  actPop.hidden = true;
  actOpen = null;
  actSvg.selectAll("rect.bar").classed("open", false);
}

document.getElementById("actPopClose").addEventListener("click", closeActivityPop);
actPop.addEventListener("click", (e) => e.stopPropagation());
document.addEventListener("click", (e) => {
  if (!document.getElementById("activity").contains(e.target)) closeActivityPop();
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeActivityPop(); });

new ResizeObserver(() => renderActivity()).observe(document.getElementById("activity"));
setInterval(() => { if (actDay === null) loadActivity(); }, 5 * 60 * 1000);
syncDayControls();
loadActivity();

/* ---------- live updates ----------
 * The listener writes new alerts into the DB as they arrive and pushes a
 * /api/health payload down /api/stream the moment it has (server-sent
 * events), so the graph moves as soon as positions are rebuilt — not on the
 * next poll. The 10s poll of the same payload stays as a fallback for a
 * dropped stream, and keeps the "⟳ ago" label ticking. Passing refit=false
 * keeps the user's pan/zoom during background updates. */
let lastHealth = "";
let prevRaw = null;

function applyHealth(h) {
  const syncEl = document.getElementById("sync");
  syncEl.innerHTML = h.last_fetch ? `⟳ ${agoSpan(h.last_fetch, "ago")}` : "";

  // New alert arrived (not just a rebuild we caused ourselves) -> chime.
  if (prevRaw !== null && h.raw_messages > prevRaw) ding();
  prevRaw = h.raw_messages;

  handleEliminations(h.eliminations);
  updateWalletsBadge(h.wallet_suggestions_new);

  // Data signature: counts plus the positions-rebuild stamp. The stamp
  // matters — a live alert first inserts events, then rebuilds positions a
  // moment later; without it a poll landing in between would render the old
  // ordering and never re-check (counts stop changing).
  const sig = `${h.raw_messages}|${h.events}|${h.positions}|${h.tokens}|${h.built_at}`;
  if (lastHealth && sig !== lastHealth) {
    load(false, true); // live: flash whatever changed
    if (!panel.hidden) { loadTraders(); loadGroups(); }
    loadFeed(); // no-op when the drawer is closed
    if (actDay === null) loadActivity();
  }
  lastHealth = sig;
}

// Push channel. EventSource reconnects on its own after a drop, and the
// server's first message on every (re)connection is a full payload, so
// nothing that happened while disconnected is missed.
if (window.EventSource) {
  const es = new EventSource("/api/stream");
  es.addEventListener("change", (e) => {
    try { applyHealth(JSON.parse(e.data)); } catch (_) { /* malformed frame */ }
  });
}

setInterval(async () => {
  try {
    const res = await fetch("/api/health");
    applyHealth(await res.json());
  } catch (_) { /* server briefly down — retry next tick */ }
}, 10000);

// Preview hook: open the page with #flashtest to flash the first token and
// its holders as if they'd just changed.
if (location.hash.includes("flashtest")) {
  setTimeout(() => {
    const tok = currentData.nodes.find((n) => n.kind === "token");
    if (!tok) return;
    const now = Date.now();
    flashUntil.set(tok.id, now + FLASH_MS);
    currentData.links.forEach((l) => {
      if (endId(l.target) === tok.id || endId(l.source) === tok.id) {
        flashUntil.set(`link:${linkKey(l)}`, now + FLASH_MS);
        flashUntil.set(endId(l.source) === tok.id ? endId(l.target) : endId(l.source), now + FLASH_MS);
      }
    });
    applyFlash();
  }, 1500);
}

// Preview hook: open the page with #dusttest to watch a random token (and its
// holders) get pulverised two seconds after the layout settles.
if (location.hash.includes("dusttest")) {
  const arm = () => {
    if (!sim || sim.alpha() >= sim.alphaMin()) return setTimeout(arm, 300);
    setTimeout(() => {
      const tokens = currentData.nodes.filter((n) => n.kind === "token");
      const victim = tokens[Math.floor(Math.random() * tokens.length)];
      if (!victim) return;
      const gone = new Set([victim.id]);
      currentData.links.forEach((l) => {
        if (endId(l.target) === victim.id) gone.add(endId(l.source));
        if (endId(l.source) === victim.id) gone.add(endId(l.target));
      });
      render({
        ...currentData,
        nodes: currentData.nodes.filter((n) => !gone.has(n.id)),
        links: currentData.links
          .filter((l) => !gone.has(endId(l.source)) && !gone.has(endId(l.target)))
          .map((l) => ({ ...l, source: endId(l.source), target: endId(l.target) })),
      }, true);
    }, 2000);
  };
  arm();
}

load();
