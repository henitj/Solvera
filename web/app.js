// Bundled UI/SDK, same-origin account transport; Puter AI is explicit, consented opt-in.
const root = element.querySelector("#solvra");
const $ = (id) => root.querySelector("#" + id);
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
const moneyFormats = new Map();
const money = (n, digits = 2) => {
  if (!moneyFormats.has(digits))
    moneyFormats.set(
      digits,
      new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      }),
    );
  return moneyFormats.get(digits).format(Number(n) || 0);
};
const numberFormat = new Intl.NumberFormat("en-US");
const num = (n) => numberFormat.format(n);
const date = (s, full = false) =>
  new Date(String(s).slice(0, 10) + "T12:00:00").toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    ...(full ? { year: "numeric" } : {}),
  });
const uid = () =>
  globalThis.crypto?.randomUUID?.() ||
  Date.now().toString(36) + Math.random().toString(36).slice(2);
const paths = {
  overview:
    '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  arrows: '<path d="M4 7h15m-4-4 4 4-4 4M20 17H5m4-4-4 4 4 4"/>',
  calendar:
    '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4m10-4v4M3 11h18m-13 4h2m4 0h2m-8 3h2"/>',
  sparkles:
    '<path d="m12 3 2.3 6.7L21 12l-6.7 2.3L12 21l-2.3-6.7L3 12l6.7-2.3L12 3Zm7-1v4m-2-2h4M4 17v4m-2-2h4"/>',
  wallet:
    '<path d="M20 8V5a2 2 0 0 0-2-2L5 6a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h15V8H5a2 2 0 0 1 0-4"/><path d="M20 12h-5v5h5m-3-2.5h.01"/>',
  piggy:
    '<path d="M7 7c3-3 8-2 10 1l4 1v6l-3 1-1 4h-3v-3H9v3H6l-1-5c-3-2-3-7 0-8l1-4 4 2M10 9h4m3 2h.01M3 10H1"/>',
  shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/>',
  trend: '<path d="m3 17 6-6 4 4 8-10m-6 0h6v6"/>',
  "trend-down": '<path d="m3 7 6 6 4-4 8 10m-6 0h6v-6"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5"/>',
  chevrons: '<path d="m8 8 4-4 4 4M8 16l4 4 4-4"/>',
  "chevron-down": '<path d="m6 9 6 6 6-6"/>',
  "chevron-right": '<path d="m9 6 6 6-6 6"/>',
  "chevron-left": '<path d="m15 6-6 6 6 6"/>',
  "arrow-up-right": '<path d="M6 18 18 6M6 6h12v12"/>',
  "arrow-right": '<path d="M4 12h16m-6-6 6 6-6 6"/>',
  "arrow-up": '<path d="M12 20V4m-6 6 6-6 6 6"/>',
  "arrow-down": '<path d="M12 4v16m-6-6 6 6 6-6"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.2 9a3 3 0 0 1 5.6 1.5c0 1.5-2.8 2-2.8 3.5m0 3h.01"/>',
  settings:
    '<path d="m10 3-1 3-3 1-3 3 2 2-1 4 3 3 3-1 2 3 4-1 1-3 3-2-1-4 2-2-3-3-4 1-2-3h-2Z"/><circle cx="12" cy="12" r="3"/>',
  lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 8-3 8h18s-3-1-3-8M10 20h4"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  upload: '<path d="M12 16V4m-5 5 5-5 5 5M4 16v5h16v-5"/>',
  wave: '<path d="M3 10v4m4-8v12m5-16v20m5-17v14m4-10v6"/>',
  expand: '<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>',
  collapse: '<path d="M3 8h5V3m8 0v5h5M8 21v-5H3m18 0h-5v5"/>',
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
  paperclip: '<path d="m9 13 7-7a3 3 0 0 1 4 4L9 21a5 5 0 0 1-7-7L13 3a2 2 0 0 1 3 3L5 17"/>',
  mic: '<rect x="8" y="2" width="8" height="13" rx="4"/><path d="M5 10v2a7 7 0 0 0 14 0v-2m-7 9v3m-4 0h8"/>',
  "mic-off":
    '<path d="m3 3 18 18M8 8v3a4 4 0 0 0 7 3m1-6V6a4 4 0 0 0-7-3M5 10v2a7 7 0 0 0 11 6m3-8v2c0 1-.2 2-.6 2.8M12 19v3m-4 0h8"/>',
  stop: '<rect x="5" y="5" width="14" height="14" rx="2"/>',
  x: '<path d="m6 6 12 12M6 18 18 6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  bolt: '<path d="m14 2-9 12h7l-2 8 9-12h-7l2-8Z"/>',
  card: '<rect x="2" y="5" width="20" height="15" rx="3"/><path d="M2 10h20M6 15h3"/>',
  home: '<path d="m3 10 9-7 9 7v11h-6v-7H9v7H3V10Z"/>',
  globe:
    '<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/>',
  phone: '<rect x="6" y="2" width="12" height="20" rx="3"/><path d="M10 18h4"/>',
  car: '<path d="m5 5-3 8v6h3v-3h14v3h3v-6l-3-8H5Zm-2 7h18M6 14h2m8 0h2"/>',
  bag: '<path d="M4 7h16l1 14H3L4 7Zm4 0V6a4 4 0 0 1 8 0v1"/>',
  coffee:
    '<path d="M3 8h13v9a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V8Zm13 1h2a4 4 0 0 1 0 8h-2M6 2v3m5-3v3"/>',
  heart: '<path d="M20 5a5 5 0 0 0-8 1 5 5 0 0 0-8-1c-6 6 8 15 8 15S26 11 20 5Z"/>',
  play: '<path d="m8 4 13 8-13 8V4Z"/>',
  copy: '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
  volume: '<path d="m10 4-6 5H1v6h3l6 5V4Zm4 4a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>',
  refresh: '<path d="M20 8a8 8 0 1 0 0 8m0-14v6h-6"/>',
  activity: '<path d="M2 12h4l3-9 6 18 3-9h4"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/>',
  leaf: '<path d="M20 3S4 1 4 12a7 7 0 0 0 12 5c4-4 4-14 4-14ZM3 21 15 9"/>',
};
const icon = (name) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.sparkles}</svg>`;
function icons(scope = root) {
  scope.querySelectorAll("[data-icon]").forEach((el) => {
    el.innerHTML = icon(el.dataset.icon);
  });
}
function storeGet(key) {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}
function storeSet(key, value) {
  try {
    sessionStorage.setItem(key, value);
  } catch {
    /* Storage may be blocked in a third-party iframe. */
  }
}
const transactionFilters = (overrides = {}) => ({
  search: "",
  category: "",
  account: "",
  direction: "",
  period: "all",
  sort: "date",
  order: "desc",
  page: 1,
  ...overrides,
});
const state = {
  session: storeGet("solvra.session.v3"),
  workspace: storeGet("solvra.workspace.v1"),
  profile: null,
  people: [],
  epoch: 0,
  loginBusy: false,
  dashboard: null,
  view: "overview",
  period: "month",
  chart: "flow",
  messages: [],
  pending: null,
  busy: false,
  voiceCaps: {},
  expanded: false,
  tx: transactionFilters(),
  txResult: null,
  txSeq: 0,
  planSeq: 0,
  revision: 0,
  plan: null,
  billTab: "bills",
  failed: null,
};
let voice;
let financeAI;
let searchTimer;
function toast(text, error = false) {
  if (!text) return;
  const el = document.createElement("div");
  el.className = "toast" + (error ? " error" : "");
  el.innerHTML = icon(error ? "info" : "check") + `<span>${esc(text)}</span>`;
  $("toast-region").append(el);
  setTimeout(() => el.remove(), error ? 7000 : 4200);
}
async function timed(promise, ms = 45000) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timer = setTimeout(
          () => reject(new Error("The server is taking too long. Try again; your draft is safe.")),
          ms,
        );
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}
function unpack(value) {
  const data = typeof value === "string" ? JSON.parse(value) : value;
  if (!data || typeof data !== "object")
    throw new Error("The server returned an unreadable response. Please try again.");
  if (data.error) throw Object.assign(new Error(data.error), { code: data.code });
  return data;
}
function currentRequest() {
  return { session: state.session, epoch: state.epoch };
}
function checkRequest(context) {
  if (context.epoch !== state.epoch || context.session !== state.session)
    throw Object.assign(new Error(""), { silent: true });
}
async function serverRequest(method, args, context = currentRequest()) {
  checkRequest(context);
  let raw;
  try {
    raw = await timed(server[method]({ ...args, session: context.session }));
  } catch (error) {
    checkRequest(context);
    throw error;
  }
  checkRequest(context);
  try {
    return unpack(raw);
  } catch (error) {
    if (error.code === "login_required") {
      showLogin({ profiles: state.people, workspace: state.workspace }, error.message);
      throw Object.assign(new Error(""), { silent: true });
    }
    throw error;
  }
}
async function api(op, args = {}, context = currentRequest()) {
  return serverRequest("workspace_action", { ...args, op }, context);
}
function moneyParts(n) {
  const parts = money(n).split(".");
  return esc(parts[0]) + `<span class="cents">.${parts[1]}</span>`;
}
function comparison() {
  const { previous_start: start, previous_end: end } = state.dashboard.period;
  const full = start.slice(0, 4) !== end.slice(0, 4);
  return `${date(start, full)}–${start.slice(0, 7) === end.slice(0, 7) ? Number(end.slice(-2)) : date(end, full)}`;
}
function change(current, before, expense = false) {
  if (!before) return `<span>No comparable previous activity</span>`;
  const pct = ((current - before) / before) * 100;
  const good = expense ? pct <= 0 : pct >= 0;
  return `<span class="stat-change${good ? "" : " down"}">${icon(pct >= 0 ? "trend" : "trend-down")}${Math.abs(pct).toFixed(1)}%</span><span>vs ${esc(comparison())}</span>`;
}
function statsMarkup() {
  const d = state.dashboard;
  return `<div class="stats-grid"><section class="stat-card"><div class="stat-top">Checking balance<span class="stat-icon">${icon("wallet")}</span></div><div class="stat-value">${moneyParts(d.checking)}</div><div class="stat-meta">${icon("shield")}<span>Plus ${money(d.savings, 0)} in savings</span></div></section><section class="stat-card"><div class="stat-top">Money in<span class="stat-icon">${icon("arrow-down")}</span></div><div class="stat-value">${moneyParts(d.totals.income)}</div><div class="stat-meta">${change(d.totals.income, d.previous.income)}</div></section><section class="stat-card"><div class="stat-top">Money out<span class="stat-icon">${icon("arrow-up")}</span></div><div class="stat-value">${moneyParts(d.totals.spending)}</div><div class="stat-meta">${change(d.totals.spending, d.previous.spending, true)}</div></section></div>`;
}
function chartMarkup() {
  const d = state.dashboard;
  const flow = state.chart === "flow";
  const values = flow ? d.chart : d.balances;
  const max = Math.max(
    ...values.flatMap((v) => (flow ? [v.income, v.spending] : [v.checking, v.savings])),
    1,
  );
  const ceil = Math.ceil(max / (flow ? 1000 : 5000)) * (flow ? 1000 : 5000);
  const compact = innerWidth < 500,
    width = compact ? 360 : 600;
  const h = 126,
    base = 154,
    left = compact ? 26 : 44,
    step = compact ? 52 : 86;
  const a = flow ? "income" : "checking",
    b = flow ? "spending" : "savings";
  const grid = [0, 0.25, 0.5, 0.75, 1]
    .map((v) => {
      const y = base - v * h;
      return `<line class="chart-grid" x1="${compact ? 24 : 40}" y1="${y}" x2="${width - 23}" y2="${y}"/><text class="chart-label" x="${left - 13}" y="${y + 3}" text-anchor="end">${v === 0 ? "$0" : "$" + ((ceil * v) / 1000).toFixed(ceil < 10000 && (v * ceil) % 1000 ? 1 : 0) + "k"}</text>`;
    })
    .join("");
  let shapes;
  if (flow) {
    shapes = values
      .map((v, i) => {
        const x = left + i * step + (compact ? 8 : 20);
        const label = `${v.month}${v.partial ? " (partial)" : ""}: income ${money(v.income)}, spending ${money(v.spending)}`;
        return `<g tabindex="0" role="img" aria-label="${esc(label)}"><title>${esc(label)}</title><rect class="chart-bar" x="${x}" y="${base - (v.income / ceil) * h}" width="${compact ? 14 : 22}" height="${(v.income / ceil) * h}" rx="3" fill="var(--chart-primary)"/><rect class="chart-bar" x="${x + (compact ? 17 : 27)}" y="${base - (v.spending / ceil) * h}" width="${compact ? 14 : 22}" height="${(v.spending / ceil) * h}" rx="3" fill="var(--chart-secondary)"/><text class="chart-label" x="${x + (compact ? 15 : 25)}" y="178" text-anchor="middle">${v.month}${v.partial ? "*" : ""}</text></g>`;
      })
      .join("");
  } else {
    shapes =
      [a, b]
        .map((key, j) => {
          const pts = values
            .map((v, i) => `${left + (compact ? 22 : 42) + i * step},${base - (v[key] / ceil) * h}`)
            .join(" ");
          return (
            `<polyline points="${pts}" fill="none" stroke="${j ? "var(--chart-secondary)" : "var(--chart-primary)"}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>` +
            values
              .map(
                (v, i) =>
                  `<circle cx="${left + (compact ? 22 : 42) + i * step}" cy="${base - (v[key] / ceil) * h}" r="3" fill="${j ? "var(--chart-secondary)" : "var(--chart-primary)"}"><title>${v.month} ${key}: ${money(v[key])}</title></circle>`,
              )
              .join("")
          );
        })
        .join("") +
      values
        .map(
          (v, i) =>
            `<text class="chart-label" x="${left + (compact ? 22 : 42) + i * step}" y="178" text-anchor="middle">${v.month}${i === values.length - 1 ? "*" : ""}</text>`,
        )
        .join("");
  }
  const sumA = flow ? values.reduce((s, v) => s + v[a], 0) : d.checking,
    sumB = flow ? values.reduce((s, v) => s + v[b], 0) : d.savings;
  return `<section class="card chart-card"><div class="card-header"><div><h2 class="card-title">A little perspective</h2><div class="card-subtitle">Your six-month ${flow ? "cash-flow" : "balance"} story</div></div><div class="segmented" aria-label="Chart type"><button data-chart="flow" class="${flow ? "active" : ""}" aria-pressed="${flow}">Cash flow</button><button data-chart="balance" class="${!flow ? "active" : ""}" aria-pressed="${!flow}">Balances</button></div></div><div class="chart-summary"><div><i></i><span><small>${flow ? "Total income" : "Checking"}</small><b>${money(sumA)}</b></span></div><div><i></i><span><small>${flow ? "Total spending" : "Savings"}</small><b>${money(sumB)}</b></span></div></div><div class="chart-container"><svg viewBox="0 0 ${width} 188" role="img" aria-label="${flow ? "Monthly income and spending" : "Checking and savings balances"} from June to November 2026">${grid}${shapes}</svg></div><div class="chart-footnote">${icon("info")}* November is partial, through ${date(d.as_of)}. ${flow ? "Spending excludes transfers." : "Balances are month-end snapshots, except November."}</div></section>`;
}
function billIcon(b) {
  return b.name.includes("Electric") || b.name.includes("Gas")
    ? "bolt"
    : b.name.includes("Rent")
      ? "home"
      : b.name.includes("Phone")
        ? "phone"
        : b.name.includes("Internet")
          ? "globe"
          : b.name.includes("Auto")
            ? "car"
            : b.category === "Debt payments"
              ? "card"
              : "layers";
}
function billMini(b) {
  return `<button class="bill-mini" data-bill="${esc(b.id)}"><span class="bill-icon ${b.category === "Utilities" ? "utility-icon" : "debt-icon"}">${icon(billIcon(b))}</span><span class="bill-info"><span class="bill-name">${esc(b.name.replace(" Minimum", ""))}</span><span class="bill-date">${date(b.due)} · ${esc(b.provider)}</span></span><span class="bill-right"><span class="bill-amount">${money(b.amount)}</span><span class="due-label ${b.days < 0 ? "overdue" : b.days > 3 ? "normal" : ""}">${b.days < 0 ? Math.abs(b.days) + "d overdue" : b.days === 0 ? "Due today" : "In " + b.days + " days"}</span></span></button>`;
}
const colors = ["primary", "secondary", "amber", "violet", "slate"].map(
  (name) => `var(--chart-${name})`,
);
function donutMarkup() {
  const d = state.dashboard;
  let cats = d.categories.slice(0, 4);
  const other = d.categories.slice(4).reduce((s, c) => s + c.amount, 0);
  if (other) cats.push({ name: "Other", amount: other });
  const total = d.totals.spending;
  let offset = 0;
  const r = 48,
    circumference = 2 * Math.PI * r;
  const rings = cats
    .map((c, i) => {
      const fraction = c.amount / Math.max(total, 1),
        length = Math.max(0, fraction * circumference - 3),
        start = offset;
      offset += fraction * circumference;
      return `<circle cx="64" cy="64" r="48" fill="none" stroke="${colors[i]}" stroke-width="12" stroke-dasharray="${length} ${circumference - length}" stroke-dashoffset="${-start}" stroke-linecap="butt"><title>${esc(c.name)}: ${money(c.amount)} (${(fraction * 100).toFixed(1)}%)</title></circle>`;
    })
    .join("");
  return `<section class="card"><div class="card-header"><div><h2 class="card-title">Where it’s going</h2><div class="card-subtitle">${esc(d.period.label)}</div></div><button class="icon-button" data-category="" data-direction="out" aria-label="Explore spending transactions">${icon("arrow-up-right")}</button></div><div class="donut-area"><div class="donut"><svg viewBox="0 0 128 128" role="img" aria-label="Spending by category"><circle cx="64" cy="64" r="48" fill="none" stroke="var(--surface-muted)" stroke-width="12"/>${rings}</svg><div class="donut-label"><small>Total spent</small><b>${money(total, 0)}</b></div></div><div class="donut-legend">${cats.map((c, i) => `<button class="legend-row" data-category="${c.name === "Other" ? "" : esc(c.name)}" data-direction="out"><i style="background:${colors[i]}"></i><span>${esc(c.name)}</span><b>${Math.round((c.amount / Math.max(total, 1)) * 100)}%</b></button>`).join("") || '<span class="card-subtitle">No expenses in this period.</span>'}</div></div><div class="card-footer"><span>Based on recorded expenses</span><button class="text-button" data-category="" data-direction="out">Explore spending ${icon("arrow-right")}</button></div></section>`;
}
const categoryIcons = {
  Groceries: "bag",
  "Dining & Entertainment": "coffee",
  Transportation: "car",
  Income: "arrow-down",
  Medical: "heart",
  Housing: "home",
  Utilities: "bolt",
};
const merchantIcon = (tx) =>
  `<span class="merchant-icon">${icon(categoryIcons[tx.category] || "card")}</span>`;
const detailRows = (rows) =>
  rows
    .map(
      ([label, value]) =>
        `<div class="detail-row"><span>${esc(label)}</span><span>${esc(value)}</span></div>`,
    )
    .join("");
function transactionTable(items, compact = false) {
  return `<div class="table-wrap"><table class="${compact ? "" : "transaction-list"}"><thead><tr><th>Transaction</th><th>Category</th><th>Date</th>${compact ? "" : "<th>Account</th>"}<th class="align-right">Amount</th></tr></thead><tbody>${items.map((tx) => `<tr class="clickable-row" data-tx="${esc(tx.id)}" tabindex="0" aria-label="${esc(tx.merchant)}, ${money(tx.amount)}, ${date(tx.date)}"><td><span class="merchant">${merchantIcon(tx)}${esc(tx.merchant)}</span></td><td><span class="category-tag ${["Dining & Entertainment", "Medical", "Shopping"].includes(tx.category) ? "peach" : ""}">${esc(tx.category)}</span></td><td>${date(tx.date)}</td>${compact ? "" : `<td>${esc(tx.account)}</td>`}<td class="amount-cell${tx.amount > 0 ? " positive" : ""}">${tx.amount > 0 ? "+" : "−"}${money(Math.abs(tx.amount))}</td></tr>`).join("")}</tbody></table></div>`;
}
function troubleMarkup(compact = false) {
  const t = state.dashboard.trouble;
  return `<section class="card trouble-card ${compact ? "compact" : ""}" data-level="${esc(t.level)}" aria-label="Financial-trouble ranking"><div class="trouble-summary"><span class="trouble-symbol">${icon("shield")}</span><div class="trouble-heading"><div class="eyebrow">FINANCIAL-TROUBLE TRIAGE · V1</div><h2>${esc(t.label)} <span>· Priority ${t.rank} of 4</span></h2><p>${esc(t.action)}</p><div class="trouble-meter" aria-hidden="true"><i style="width:${t.score}%"></i></div><small>Higher pressure points = more urgency. Not a credit score.</small></div><div class="trouble-points"><b>${t.score}<span>/100</span></b><small>PRESSURE POINTS</small></div></div>${
    compact
      ? `<div class="trouble-footer"><span>${t.drivers
          .slice(0, 2)
          .map((x) => esc(x.name))
          .join(
            " · ",
          )}</span><button class="text-button" data-view="insights">Why this ranking ${icon("arrow-right")}</button></div>`
      : `<div class="trouble-method"><p>Six weighted signals from this person’s ledger, at ${date(t.as_of, true)}. These fixed windows do not change with the reporting filter.</p><ol class="trouble-scale">${t.scale.map((b) => `<li ${b.level === t.level ? 'aria-current="true" class="selected"' : ""}><b>${b.rank}. ${esc(b.label)}</b><span>${b.min}–${b.max} points</span></li>`).join("")}</ol>${t.override ? `<p class="trouble-override"><b>Safety floor:</b> ${esc(t.override)} Weighted total ${t.raw_score}; floor ${t.floor}; final ${t.score}.</p>` : ""}<details class="trouble-details"><summary>See every factor, point and rule</summary><div class="trouble-factors">${t.factors.map((f) => `<div class="trouble-factor"><div><b>${esc(f.name)}</b><strong>${f.points} / ${f.max_points}</strong></div><p>${esc(f.evidence)}</p><small>${esc(f.rule)}</small></div>`).join("")}</div><p class="form-note">Essential arrears set a minimum of High (40). Housing overdue beyond its recorded grace period plus insufficient checking for overdue essentials sets a minimum of Critical (70). The final score is the larger of the weighted total and the applicable floor.</p></details><p class="form-note">${esc(t.limits)}</p><div class="dialog-actions"><button class="button secondary" data-prompt="Explain my financial trouble ranking and what I should do first.">${icon("sparkles")}Discuss my ranking</button><button class="text-button" data-action="open-plan">Build a payment plan ${icon("arrow-right")}</button></div></div>`
  }</section>`;
}
function renderOverview() {
  const d = state.dashboard;
  $("view-content").innerHTML =
    statsMarkup() +
    troubleMarkup(true) +
    chartMarkup() +
    `<div class="overview-split"><section class="card"><div class="card-header"><div><h2 class="card-title">Coming up next</h2><div class="card-subtitle">A few dates to keep in mind</div></div><button class="text-button" data-view="bills">View all ${icon("arrow-right")}</button></div><div class="bills-mini">${d.bills.slice(0, 4).map(billMini).join("") || '<div class="table-empty">No open bills. A little breathing room.</div>'}</div><div class="card-footer"><span>${d.bills.length} open bills</span><span>Nothing is on autopay here</span></div></section>${donutMarkup()}</div><section><div class="insights-heading"><h2>${icon("sparkles")}Worth a closer look<span class="small-label">FOR YOU</span></h2><button class="text-button" data-view="insights">All insights ${icon("arrow-right")}</button></div><div class="insights-preview-grid">${d.insights
      .slice(1, 3)
      .map(
        (i) =>
          `<button class="insight-preview" data-tone="${esc(i.tone)}" data-prompt="${esc(i.prompt)}"><span class="insight-eyebrow">${icon(i.icon)}${esc(i.eyebrow)}</span><b>${esc(i.title)}</b><p>${esc(i.description)}</p><span class="insight-link">Let’s unpack this ${icon("arrow-up-right")}</span></button>`,
      )
      .join(
        "",
      )}</div></section><section class="card recent-card"><div class="card-header"><div><h2 class="card-title">The latest activity</h2><div class="card-subtitle">Small details. The full picture.</div></div><button class="text-button" data-view="transactions">View all ${icon("arrow-right")}</button></div>${transactionTable(d.recent.slice(0, 5), true)}</section>`;
}
const headings = {
  overview: ["THE BIG PICTURE", "Your money, in focus.", "A little clarity for your next move."],
  transactions: [
    "THE DETAILS THAT MATTER",
    "Every move, accounted for.",
    "Search, filter, and get to know your money.",
  ],
  bills: [
    "ONE LESS THING TO JUGGLE",
    "A plan for what’s next.",
    "Know what’s due. Decide what comes first.",
  ],
  insights: [
    "A FRESH PERSPECTIVE",
    "Good insights. Better moves.",
    "Real patterns from your ledger, with the working shown.",
  ],
};
function setView(view, filters = null) {
  if (!headings[view] || !state.dashboard) return;
  state.view = view;
  setNavigation(false);
  if (state.expanded) toggleChat(false);
  const h = headings[view];
  $("page-eyebrow").textContent = h[0];
  $("page-title").innerHTML = esc(h[1].slice(0, -1)) + "<span>.</span>";
  $("page-subtitle").textContent = h[2];
  $("breadcrumb-current").textContent = {
    overview: "Overview",
    transactions: "Transactions",
    bills: "Bills & payments",
    insights: "Insights",
  }[view];
  root.querySelectorAll(".main-nav .nav-item").forEach((b) => {
    b.classList.toggle("active", b.dataset.view === view);
    b.setAttribute("aria-current", b.dataset.view === view ? "page" : "false");
  });
  $("reporting-period").parentElement.hidden = view === "bills" || view === "transactions";
  if (filters) state.tx = transactionFilters(filters);
  renderView();
}
function renderView() {
  if (!state.dashboard) return;
  $("view-content").setAttribute("aria-busy", "false");
  if (state.view === "overview") renderOverview();
  if (state.view === "transactions") renderTransactions();
  if (state.view === "bills") renderBills();
  if (state.view === "insights") renderInsights();
}
function updateDashboard(d) {
  state.dashboard = d;
  state.period = d.period_key;
  $("reporting-period").value = d.period_key;
  $("snapshot-date").textContent = date(d.as_of, true);
  $("nav-tx-count").textContent = num(d.transaction_count);
}
function optionList(values, selected, first) {
  return (
    `<option value="">${first}</option>` +
    values
      .map(
        (v) => `<option value="${esc(v)}"${v === selected ? " selected" : ""}>${esc(v)}</option>`,
      )
      .join("")
  );
}
function renderTransactions() {
  const t = state.tx,
    d = state.dashboard;
  $("view-content").innerHTML =
    `<div class="view-toolbar"><label class="filter-search">${icon("search")}<input id="tx-search" placeholder="Merchant, category, or description…" value="${esc(t.search)}" aria-label="Filter transactions"></label><button class="button primary" data-action="add-transaction">${icon("plus")}Add transaction</button></div><div class="view-toolbar"><select id="tx-period" class="filter-select" aria-label="Filter by date"><option value="all">All history</option><option value="month" ${t.period === "month" ? "selected" : ""}>This month</option><option value="last_month" ${t.period === "last_month" ? "selected" : ""}>Last month</option><option value="90days" ${t.period === "90days" ? "selected" : ""}>Last 90 days</option></select><select id="tx-category" class="filter-select" aria-label="Filter by category">${optionList(d.categories_all, t.category, "All categories")}</select><select id="tx-account" class="filter-select" aria-label="Filter by account">${optionList(d.accounts, t.account, "All accounts")}</select><select id="tx-direction" class="filter-select" aria-label="Filter by direction"><option value="">Money in & out</option><option value="in" ${t.direction === "in" ? "selected" : ""}>Money in</option><option value="out" ${t.direction === "out" ? "selected" : ""}>Money out</option></select><button class="text-button" data-action="clear-filters">Clear filters</button></div><div id="tx-filter-summary" class="filter-count"></div><section id="tx-results" class="card"><div class="loading-state" style="min-height:250px"><span class="loading-symbol"></span></div></section>`;
  loadTransactions();
}
async function loadTransactions() {
  const seq = ++state.txSeq;
  try {
    const res = await api("transactions", { ...state.tx, size: 10 });
    if (seq !== state.txSeq || state.view !== "transactions") return;
    state.txResult = res;
    state.tx.page = res.page;
    $("tx-filter-summary").innerHTML =
      `<span><b>${num(res.total)}</b> matching transactions</span><span>In ${money(res.inflow)} <span aria-hidden="true">/</span> Out ${money(res.outflow)}</span>`;
    $("tx-results").innerHTML =
      (res.items.length
        ? transactionTable(res.items)
        : `<div class="table-empty">${icon("search")}<b>No transactions match just yet.</b><p>Try another search or a wider date range.</p><button class="button secondary" data-action="clear-filters">Clear filters</button></div>`) +
      `<div class="pagination"><span>${res.total ? `${(res.page - 1) * 10 + 1}–${Math.min(res.page * 10, res.total)} of ${num(res.total)}` : "0 results"}</span><div class="pagination-controls"><button class="button secondary" data-page="${res.page - 1}" ${res.page <= 1 ? "disabled" : ""} aria-label="Previous page">${icon("chevron-left")}</button><span>Page ${res.page} of ${res.pages}</span><button class="button secondary" data-page="${res.page + 1}" ${res.page >= res.pages ? "disabled" : ""} aria-label="Next page">${icon("chevron-right")}</button></div></div>`;
  } catch (e) {
    if (seq === state.txSeq && $("tx-results"))
      $("tx-results").innerHTML =
        `<div class="table-empty"><b>Couldn’t load these transactions.</b><p>${esc(e.message)}</p><button class="button secondary" data-action="retry-transactions">Try again</button></div>`;
  }
}
function billTable() {
  return `<section class="card"><div class="card-header"><div><h2 class="card-title">Your open bills</h2><div class="card-subtitle">Recorded obligations, not live provider balances</div></div><span class="category-tag">${state.dashboard.bills.length} OPEN</span></div><div class="table-wrap"><table class="bill-table"><thead><tr><th>Bill & provider</th><th>Due</th><th class="align-right">Amount</th><th></th></tr></thead><tbody>${state.dashboard.bills.map((b) => `<tr><td><button class="text-button" data-bill="${esc(b.id)}"><span class="bill-icon ${b.category === "Utilities" ? "utility-icon" : "debt-icon"}">${icon(billIcon(b))}</span><span class="bill-info"><span class="bill-name">${esc(b.name)}</span><span class="bill-date">${esc(b.provider)}</span></span></button></td><td>${date(b.due)}<br><span class="due-label ${b.days <= 3 ? "" : "normal"}">${b.days < 0 ? "Overdue" : b.days === 0 ? "Today" : "In " + b.days + " days"}</span></td><td class="amount-cell">${money(b.amount)}</td><td><button class="text-button" data-record-payment="${esc(b.id)}" aria-label="Record a payment already made to ${esc(b.name)}">Record paid ${icon("plus")}</button></td></tr>`).join("") || '<tr><td colspan="4" class="table-empty">No open bills remain.</td></tr>'}</tbody></table></div></section>`;
}
function planResultsMarkup() {
  const p = state.plan;
  if (!p)
    return `<div class="card table-empty">${icon("calendar")}<b>Your plan, built around your real constraints.</b><p>Choose a cash reserve, then calculate a preview.<br>No payments are made or scheduled.</p><button class="button primary" data-action="recalculate-plan">Build payment plan ${icon("arrow-right")}</button></div>`;
  return `<div class="plan-results"><div class="plan-summary"><div><small>Allocated to bills</small><b>${money(p.allocated)}</b></div><div><small>Uncovered bills</small><b>${money(p.unpaid)}</b></div><div><small>Checking after plan</small><b>${money(p.remaining)}</b></div></div><section class="card"><div class="card-header"><div><h2 class="card-title">Your suggested payment order</h2><div class="card-subtitle">A preview only · reserve included in remaining cash</div></div><button class="text-button" data-prompt="Explain the order of my bill payment plan.">Why this order? ${icon("arrow-up-right")}</button></div><div class="payment-timeline">${p.payments.map((v, i) => `<div class="payment-step"><span class="step-number">${i + 1}</span><div class="step-content"><b>${esc(v.bill)}</b><p>Due ${date(v.due)}${v.late ? " · after due date" : ""}</p><details class="message-sources"><summary>View reasoning</summary><div class="source-item">${esc(v.reason)}</div></details></div><div class="step-amount"><b>${money(v.amount)}</b><small>${date(v.date)}</small></div></div>`).join("") || '<div class="table-empty">No feasible payments under the current constraints.</div>'}</div></section>${p.uncovered.length ? `<div class="simulation-result"><b>These amounts are not covered:</b><br>${p.uncovered.map((v) => `${esc(v.name)}: ${money(v.amount)}. ${esc(v.reason)}`).join("<br>")}<br>Check extensions with providers. Do not assume a late payment is harmless.</div>` : ""}<details class="assumptions" open><summary>Assumptions & limits</summary>${p.assumptions.map((a) => `<p>• ${esc(a)}</p>`).join("")}<p>Modeled late fees ${money(p.late_fees)} · interest ${money(p.interest)} · ${num(p.risk_points)} non-monetary risk points.</p></details></div>`;
}
function renderBills() {
  const d = state.dashboard;
  $("view-content").innerHTML =
    `<div class="plan-intro"><span data-icon="shield"></span><div><h2>${d.checking >= d.bill_total ? "A clearer plan. A little less worry." : "Let’s find a workable payment plan."}</h2><p>${money(d.bill_total)} in open bills · ${money(d.checking)} in checking</p></div></div><div class="segmented" style="align-self:flex-start"><button data-bill-tab="bills" class="${state.billTab === "bills" ? "active" : ""}" aria-pressed="${state.billTab === "bills"}">Upcoming bills</button><button data-bill-tab="plan" class="${state.billTab === "plan" ? "active" : ""}" aria-pressed="${state.billTab === "plan"}">Payment planner</button></div><form id="plan-form" class="plan-controls"><label>Cash reserve to hold back<span class="money-input">$<input id="plan-reserve" type="number" min="0" max="1000000" step="0.01" value="${state.plan?.reserve ?? d.buffer.reserve}" aria-label="Cash reserve amount"></span></label><label class="checkbox-label"><input id="plan-income" type="checkbox" ${state.plan?.include_income ? "checked" : ""}>Include expected ${money(d.paycheck.amount, 0)} paycheck (unconfirmed)</label><button class="button primary" type="submit">${icon("refresh")}Apply reserve & calculate</button></form><div id="bills-content">${state.billTab === "bills" ? billTable() : planResultsMarkup()}</div><section class="card simulator"><h2 class="card-title">What if a payment runs late?</h2><p class="card-subtitle">Explore the modeled impact. Your actual due dates won’t change.</p><form id="simulate-form" class="simulation-controls"><label>Choose a bill<select id="sim-bill" required>${d.bills.map((b) => `<option value="${esc(b.id)}">${esc(b.name)}</option>`).join("")}</select></label><label>Days late<input id="sim-days" type="number" min="0" max="90" step="1" value="5" required></label><button class="button secondary" ${!d.bills.length ? "disabled" : ""}>Preview impact ${icon("arrow-right")}</button></form><div id="simulation-output" aria-live="polite"></div></section>`;
  icons($("view-content"));
}
async function calculatePlan() {
  const seq = ++state.planSeq,
    revision = state.revision;
  const reserve = Number($("plan-reserve")?.value ?? state.dashboard.buffer.reserve),
    include_income = $("plan-income")?.checked || false;
  if (!Number.isFinite(reserve) || reserve < 0 || reserve > 1000000) {
    toast("Enter a cash reserve between $0 and $1,000,000.", true);
    return;
  }
  const button = $("plan-form")?.querySelector("button");
  if (button) {
    button.disabled = true;
    button.textContent = "Calculating…";
  }
  try {
    const res = await api("plan", { reserve, include_income });
    if (seq !== state.planSeq || revision !== state.revision) return;
    state.plan = res.plan;
    updateDashboard(res.dashboard);
    state.billTab = "plan";
    if (state.view === "bills") renderBills();
    toast("Plan recalculated. No payments were scheduled.");
  } catch (e) {
    toast(e.message, true);
  } finally {
    if (button?.isConnected) {
      button.disabled = false;
      button.textContent = "Apply reserve & calculate";
    }
  }
}
function renderInsights() {
  const d = state.dashboard;
  $("view-content").innerHTML =
    troubleMarkup() +
    `<section class="card"><div class="health-card"><div class="health-gauge"><svg viewBox="0 0 110 110" role="img" aria-label="Financial health score ${d.health.score} out of 100"><circle cx="55" cy="55" r="47" stroke="var(--surface-muted)" stroke-width="7" fill="none"/><circle cx="55" cy="55" r="47" stroke="var(--primary)" stroke-width="7" fill="none" stroke-linecap="round" stroke-dasharray="${(d.health.score / 100) * 295.3} 295.3"/></svg><span><b>${d.health.score}</b><small>OUT OF 100</small></span></div><div><h2 class="section-title">A check-in, not a judgment.</h2><p>Your modeled financial health, from seven account-history factors. Not a credit score or a guarantee. Click below to see what goes into it.</p><button class="text-button" style="margin-top:9px" data-action="toggle-factors">See the full breakdown ${icon("chevron-down")}</button></div></div><div id="health-factors" class="health-factors" hidden>${d.health.factors.map((v) => `<div class="health-factor"><span>${esc(v.factor)} <small>(${Math.round(v.weight * 100)}% weight)</small></span><span class="factor-track"><i style="width:${v.component_score_0_100}%"></i></span><span class="factor-score">${Math.round(v.component_score_0_100)}</span></div>`).join("")}</div></section>${d.insights.map((i) => `<article class="insight-full" data-tone="${esc(i.tone)}"><div class="insight-eyebrow">${icon(i.icon)}${esc(i.eyebrow)}</div><h2>${esc(i.title)}</h2><p>${esc(i.description)}</p><div class="insight-evidence"><b>The working, not just the takeaway</b>${i.evidence.map((s) => `<div>• ${esc(s)}</div>`).join("")}</div><div class="insight-actions"><span class="insight-type">Account-derived · as of ${date(d.as_of)}</span><button class="button secondary" data-prompt="${esc(i.prompt)}">Explore with Solvra ${icon("arrow-up-right")}</button></div></article>`).join("")}<div class="assumptions">These are rules-based observations from fictional data, not AI predictions or personalized financial advice. Spending comparisons use the same days of the prior month for a partial current month. No bank connection or external data is used.</div>`;
}
function welcomeMarkup() {
  const d = state.dashboard;
  return `<div class="chat-welcome"><div class="welcome-art" aria-hidden="true"><span class="art-card">${icon("wave")}</span><span class="art-card back">${icon("sparkles")}</span><span class="art-star">${icon("plus")}</span></div><h2>Hi ${esc(state.profile.first_name)}.<br>Let’s talk money.</h2><p>Big plans or everyday questions.<br>We’ll work through the numbers together.</p><div class="welcome-note">You have <b>${money(d.checking)}</b> in checking.${d.bills.length ? (d.bills[0].days < 0 ? ` Your oldest unpaid bill, <b>${esc(d.bills[0].name)}</b>, was due <b>${date(d.bills[0].due)}</b>.` : ` Your next bill is <b>${esc(d.bills[0].name)}</b> on <b>${date(d.bills[0].due)}</b>.`) : ""} Where would you like to start?</div><div class="prompt-label">A GOOD PLACE TO START</div><div class="welcome-prompts"><button class="welcome-prompt" data-prompt="Can I afford a $200 purchase?"><span data-icon="wallet"></span><span><b>Do I have room for a little extra?</b><small>Check a $200 purchase against your plan</small></span><span data-icon="arrow-up-right"></span></button><button class="welcome-prompt" data-prompt="Where can I cut back?"><span data-icon="leaf"></span><span><b>Where could I spend a little less?</b><small>Find opportunities in your recorded spending</small></span><span data-icon="arrow-up-right"></span></button><button class="welcome-prompt" data-prompt="Build my bill payment plan and explain the order."><span data-icon="calendar"></span><span><b>Help me get ahead of my bills</b><small>A payment plan with the reasoning shown</small></span><span data-icon="arrow-up-right"></span></button></div></div>`;
}
function messageMarkup(m, index) {
  if (m.role === "user")
    return `<div class="chat-message user"><div class="message-label">YOU</div><div class="message-text">${esc(m.content)}</div></div>`;
  return `<div class="chat-message assistant"><div class="message-label">${icon("sparkles")}SOLVRA<span class="engine-badge">${m.intent === "scope" ? "Finance-only" : m.engine === "puter" ? "Grok AI" : "Local finance engine"}</span></div><div class="message-text">${String(
    m.content || "",
  )
    .split(/\n\s*\n/)
    .map((p) => `<p>${esc(p).replace(/\n/g, "<br>")}</p>`)
    .join(
      "",
    )}</div>${m.notice ? `<p class="answer-notice">${esc(m.notice)}</p>` : ""}${m.sources?.length ? `<details class="message-sources"><summary>${icon("layers")}${m.sources.length} account source${m.sources.length !== 1 ? "s" : ""} · see the working</summary>${m.sources.map((s) => `<div class="source-item"><b>${esc(s.label)}</b><br>${esc(s.detail)}</div>`).join("")}</details>` : ""}<div class="message-actions"><button class="icon-button" data-copy-message="${index}" aria-label="Copy answer">${icon("copy")}</button><button class="icon-button" data-read-message="${index}" aria-label="Read answer aloud">${icon("volume")}</button></div></div>`;
}
function renderChat(scroll = true) {
  const log = $("chat-log");
  log.innerHTML = state.messages.length
    ? state.messages.map(messageMarkup).join("")
    : welcomeMarkup();
  if (state.busy)
    log.insertAdjacentHTML(
      "beforeend",
      '<div class="typing-indicator" aria-label="Solvra is working"><i></i><i></i><i></i></div>',
    );
  if (state.failed)
    log.insertAdjacentHTML(
      "beforeend",
      `<div class="chat-error" role="alert">${esc(state.failed.error)}<button class="text-button" data-action="retry-chat">Retry this question ${icon("refresh")}</button></div>`,
    );
  $("chat-pending").hidden = !state.pending;
  const last = [...state.messages].reverse().find((m) => m.role === "assistant");
  $("follow-up-prompts").innerHTML =
    state.messages.length && !state.busy && !state.failed
      ? (last?.suggestions || [])
          .map((p) => `<button data-prompt="${esc(p)}">${esc(p)}</button>`)
          .join("")
      : "";
  icons(log);
  if (scroll) log.scrollTop = log.scrollHeight;
  setBusy(state.busy);
}
function setBusy(busy) {
  state.busy = busy;
  $("chat-send").disabled = busy || !state.profile;
  root.querySelectorAll("[data-confirm], [data-busy-lock]").forEach((b) => (b.disabled = busy));
  $("chat-form").setAttribute("aria-busy", String(busy));
  voice?.syncButtons();
  financeAI?.syncUI();
}
function assistantMessage(response) {
  return {
    role: "assistant",
    content: response.reply,
    id: response.message_id,
    speech: response.speech,
    speech_chunks: response.speech_chunks,
    sources: response.sources,
    suggestions: response.suggestions,
    intent: response.intent,
    engine: response.engine,
    model: response.model,
    notice: response.notice,
  };
}
async function sendMessage(text, retry = false) {
  text = String(text || "").trim();
  if (!text) return;
  if (state.busy) {
    toast("One moment—your draft will stay here.");
    return;
  }
  if (!state.session) {
    toast("The workspace is still connecting. Your draft is safe.", true);
    return;
  }
  if (text.length > 3000) {
    toast("Keep your question under 3,000 characters.", true);
    return;
  }
  voice?.stopSpeaking();
  const context = currentRequest();
  const request_id = retry ? state.failed.request_id : uid();
  state.failed = null;
  if (!retry) {
    state.messages.push({ role: "user", content: text });
    if ($("chat-input").value.trim() === text) {
      $("chat-input").value = "";
      storeSet("solvra.draft", "");
    }
  }
  setBusy(true);
  renderChat();
  try {
    let res = await serverRequest(
      "live_turn",
      { text, request_id, ai: financeAI?.enabled === true },
      context,
    );
    checkRequest(context);
    res = await financeAI.enhance(res, context);
    checkRequest(context);
    state.pending = res.pending;
    state.messages.push(assistantMessage(res));
    if (res.dashboard) {
      updateDashboard(res.dashboard);
      state.plan = null;
      ++state.revision;
      renderView();
    }
    setBusy(false);
    renderChat();
    if (res.end) voice?.stopAll();
    else voice?.onReply(res);
  } catch (e) {
    if (context.epoch !== state.epoch || e.silent) return;
    state.failed = {
      text,
      request_id,
      error: e.message || "Could not reach the server. Try again.",
    };
    if (!$("chat-input").value) {
      $("chat-input").value = text;
      storeSet("solvra.draft", text);
    }
    setBusy(false);
    renderChat();
  }
}
function acceptStagedResponse(res, description) {
  state.messages.push({ role: "user", content: description }, assistantMessage(res));
  state.pending = res.pending;
  renderChat();
  if (innerWidth <= 1060) toggleChat(true);
  toast("Review and confirm the change in the assistant.");
}
function toggleChat(expand = !state.expanded) {
  state.expanded = expand;
  root.classList.toggle("chat-expanded", expand);
  $("expand-chat").innerHTML = icon(expand ? "collapse" : "expand");
  $("expand-chat").setAttribute("aria-label", expand ? "Back to workspace" : "Expand assistant");
  if (expand) {
    $("chat-input").focus({ preventScroll: true });
    $("assistant-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  }
}
function openDialog(title, content, eyebrow = "YOUR WORKSPACE") {
  $("dialog-title").textContent = title;
  $("dialog-eyebrow").textContent = eyebrow;
  $("dialog-content").innerHTML = content;
  icons($("dialog-content"));
  setBusy(state.busy);
  if (!$("app-dialog").open) $("app-dialog").showModal();
}
function showTransaction(id) {
  const tx = [...state.dashboard.recent, ...(state.txResult?.items || [])].find((t) => t.id === id);
  if (!tx) return;
  openDialog(
    tx.merchant,
    `<div class="detail-amount">${tx.amount > 0 ? "+" : "−"}${money(Math.abs(tx.amount))}</div><div class="detail-list">${detailRows(
      [
        ["Date", date(tx.date, true)],
        ["Category", tx.category],
        ["Account", tx.account],
        ["Payment method", tx.method],
        ["Description", tx.description],
        ["Record ID", tx.id],
      ],
    )}</div><p class="form-note">A recorded demo transaction, not a live bank statement.</p><div class="dialog-actions"><button class="button secondary" data-category="${esc(tx.category)}">See similar transactions ${icon("arrow-right")}</button></div>`,
    "A CLOSER LOOK",
  );
}
function showBill(id) {
  const b = state.dashboard.bills.find((v) => v.id === id);
  if (!b) return;
  openDialog(
    b.name,
    `<p class="dialog-copy">${esc(b.provider)}</p><div class="detail-amount">${money(b.amount)}</div><div class="detail-list">${detailRows(
      [
        ["Due date", date(b.due, true)],
        ["Minimum recorded", money(b.minimum)],
        ["Late fee", money(b.late_fee)],
        ["Grace period", b.grace_days + " days"],
        ["Recorded APR", (b.apr * 100).toFixed(1) + "%"],
        ["Partial payments", b.partial_allowed ? "Allowed by demo terms" : "Full payment required"],
      ],
    )}</div><p class="form-note">${esc(b.consequence)}. Terms are fictional estimates; confirm actual terms with the provider.</p><div class="dialog-actions"><button class="button secondary" data-prompt="What if I pay ${esc(b.name)} 5 days late?">Explore a what-if</button><button class="button primary" data-record-payment="${esc(b.id)}">Record already paid</button></div>`,
    "ONE LESS UNKNOWN",
  );
}
function addTransactionDialog() {
  const cats = state.dashboard.categories_all.filter((c) => !["Income", "Transfers"].includes(c));
  openDialog(
    "Add a little detail.",
    `<form id="add-transaction-form"><div class="form-grid"><label>Type<select name="kind"><option value="expense">Expense</option><option value="income">Income</option></select></label><label>Amount ($)<input name="amount" type="number" min="0.01" max="1000000" step="0.01" placeholder="0.00" required></label><label class="wide">Merchant or income source<input name="merchant" maxlength="120" placeholder="Who was it with?" required></label><label class="wide">Category<select name="category">${cats.map((c) => `<option>${esc(c)}</option>`).join("")}</select></label><label class="wide">Description (optional)<input name="description" maxlength="500" placeholder="A note for your future self"></label></div><p class="form-note">Recorded in demo checking on ${date(state.dashboard.as_of, true)}. You’ll confirm the details in the assistant before anything is added.</p><div id="transaction-form-error" class="form-error" hidden role="alert"></div><div class="dialog-actions"><button class="button secondary" type="button" data-action="close-dialog">Cancel</button><button class="button primary">Review transaction ${icon("arrow-right")}</button></div></form>`,
    "YOUR LEDGER",
  );
}
function paymentDialog(id) {
  const b = state.dashboard.bills.find((v) => v.id === id);
  if (!b) return;
  openDialog(
    "Already paid? Record it.",
    `<form id="record-payment-form"><input type="hidden" name="bill_id" value="${esc(id)}"><p class="dialog-copy">Add a payment you have <b>already made</b> toward ${esc(b.name)}. This does not pay the provider.</p><div class="form-grid" style="margin-top:17px"><label class="wide">Payment amount ($)<input type="number" name="amount" min="0.01" max="${b.amount}" step="0.01" value="${b.amount.toFixed(2)}" required></label></div><p class="form-note">You’ll confirm before the demo checking ledger or bill balance changes.</p><div id="transaction-form-error" class="form-error" hidden role="alert"></div><div class="dialog-actions"><button type="button" class="button secondary" data-action="close-dialog">Cancel</button><button class="button primary">Review payment ${icon("arrow-right")}</button></div></form>`,
    "RECORD, NOT SEND",
  );
}
function showHelp() {
  openDialog(
    "A clearer way to see your money.",
    `<div class="dialog-copy"><p><b>Four fictional households. Four separate ledgers.</b><br>You’re viewing ${esc(state.profile?.name || "a demo person")}. Their overview, planner, insights, assistant and voice use the same account. Each person has different seeded income, spending, debt, savings and bills. Logout in Settings to choose someone else. Changes and chats stay separate in this tab for up to 8 hours while the server runs.</p><p><b>Answers with the working shown.</b><br>Connect Grok AI for broader finance-only guidance and follow-ups. AI sharing requires your consent and Puter sign-in. Without it, exact local calculations, bill planning and confirmations still work. Answers are labeled by engine; expand account sources to check their basis.</p><p><b>Voice, in one clean turn.</b><br>Ask by voice directly from the composer—no separate speaking popup. Chrome, Edge, and Safari wait for final recognition, remove repeated phrases, then process and send one question automatically. If browser speech fails, local recording processes the completed audio and sends it in the same flow. Open the app in a new tab if an embedding page blocks the microphone. Replies use local neural speech by default; choose a voice, preview it, or change the pace in voice settings.</p><p><b>Financial trouble, explained.</b><br>Pressure points combine overdue essentials, 14-day bills, 30-day headroom, completed-month deficits, emergency savings and required debt service. Higher points mean more pressure; priority 1 is most urgent. Inspect the thresholds and safety floors in Insights. Grok receives this exact assessment after consent, not other people’s finances.</p><p><b>You always have the final say.</b><br>No real bank is connected. Nothing is paid, scheduled, transferred, or canceled. Ledger changes require confirmation. All figures are estimates from demo data—not financial advice.</p></div><div class="dialog-actions"><button class="button primary" data-action="help-voice">Try voice ${icon("mic")}</button></div>`,
    "GOOD TO KNOW",
  );
}
function showSettings() {
  openDialog(
    "A workspace that’s yours.",
    `<div class="dialog-copy"><p><b>${esc(state.profile.name)} · ${esc(state.profile.role)}</b><br>${esc(state.profile.household)}. ${esc(state.profile.goal)}</p><p><b>Demo session</b><br>Refresh restores this person. Each tab has separate fictional profiles. Logout cancels unconfirmed changes, stops voice and disconnects AI; this person’s confirmed changes and conversation are kept separately for up to 8 hours while the server runs. This simulated login is not secure authentication. Grok AI is optional: after consent, relevant financial context is shared with Puter and its model provider. Local mode does not send prompts to them.</p><p><b>Planning reserve</b><br>Currently ${money(state.dashboard.buffer.reserve)}. Change it in Bills & payments; the affordability model will use the same reserve.</p></div><div class="dialog-actions"><button class="button secondary" data-action="settings-plan">Adjust planning reserve ${icon("arrow-right")}</button><button class="button secondary" data-action="voice-settings">${icon("volume")}Voice & read-aloud</button><button class="button secondary" data-action="ai-settings">${icon("sparkles")}Grok AI settings</button></div><div class="danger-zone"><h3>Start with a clean slate</h3><p>Restore ${esc(state.profile.first_name)}’s own starting ledger, bills, preferences, and conversation only. Other people’s profiles are not affected. This cannot be undone.</p><button class="button secondary" data-action="confirm-reset" data-busy-lock>Reset demo account ${icon("refresh")}</button></div><div class="settings-logout"><div><h3>Switch to another story</h3><p>Log out to choose a different fictional person. Unconfirmed changes will be canceled.</p></div><button class="button secondary" data-action="logout">Log out ${icon("arrow-right")}</button></div>`,
    "DEMO SETTINGS",
  );
}
async function downloadExport() {
  const btn = $("export-button");
  btn.disabled = true;
  try {
    const res = await api(
      "export",
      state.view === "transactions" ? state.tx : { period: state.period },
    );
    download(res.csv, res.filename, "text/csv;charset=utf-8");
    toast(`Exported ${num(res.count)} transactions.`);
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
  }
}
function download(content, name, type = "text/plain;charset=utf-8") {
  const a = document.createElement("a"),
    url = URL.createObjectURL(new Blob([content], { type }));
  a.href = url;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}
function loginControls(message = "") {
  $("demo-person").disabled = state.loginBusy || !state.people.length;
  $("demo-login-button").disabled = state.loginBusy || !$("demo-person").value;
  $("demo-login-button").innerHTML = state.loginBusy
    ? "Opening demo…"
    : `Log in to demo ${icon("arrow-right")}`;
  if (message) $("demo-login-status").textContent = message;
}
function previewPerson() {
  const p = state.people.find((p) => p.id === $("demo-person").value);
  $("login-person-preview").innerHTML = p
    ? `<span class="login-person-avatar">${esc(p.initials)}</span><div><b>${esc(p.name)}</b><small>${esc(p.role)} · ${esc(p.household)}</small><span class="login-person-status" data-situation="${esc(p.situation || "")}">${esc(p.situation || "Different financial picture")}</span><p>${esc(p.story)}</p><p class="login-person-detail">${esc(p.situation_detail || "Each fictional account has a distinct financial starting point.")}</p><p class="login-person-goal">Goal: ${esc(p.goal)}</p></div>`
    : `${icon("layers")}<p>Choose a person to see whether their fictional starting point is stable, worth watching, tight, or urgent.</p>`;
  loginControls();
}
function updatePerson() {
  const p = state.profile;
  $("sidebar-person-name").textContent = p?.name || "Demo household";
  $("workspace-person-name").textContent = p ? `${p.first_name}’s workspace` : "Personal workspace";
  $("sidebar-person-role").textContent = p?.role || "Fictional profile";
  $("sidebar-initials").textContent = $("profile-button").textContent = p?.initials || "—";
  $("profile-button").setAttribute(
    "aria-label",
    p ? `View ${p.name}’s demo account` : "Demo profile",
  );
  for (const kind of ["checking", "savings"])
    $(kind + "-suffix").textContent = p ? `Demo · ${p[kind + "_suffix"]}` : "Demo account";
}
function showLogin(res = {}, message = "Choose a fictional person to begin.") {
  ++state.epoch;
  ++state.revision;
  ++state.txSeq;
  ++state.planSeq;
  clearTimeout(searchTimer);
  financeAI?.resetProfile();
  voice?.clearProfile();
  for (const id of ["app-dialog", "voice-dialog"]) $(id).close();
  $("dialog-content").innerHTML = "";
  $("dialog-title").textContent = "";
  Object.assign(state, {
    session: null,
    profile: null,
    dashboard: null,
    messages: [],
    pending: null,
    busy: false,
    plan: null,
    failed: null,
    txResult: null,
    tx: transactionFilters(),
    view: "overview",
    chart: "flow",
    billTab: "bills",
    expanded: false,
  });
  state.workspace = res.workspace || state.workspace;
  state.people = res.profiles || state.people;
  storeSet("solvra.session.v3", "");
  storeSet("solvra.workspace.v1", state.workspace || "");
  storeSet("solvra.draft", "");
  for (const id of ["chat-input", "global-search", "audio-upload"]) $(id).value = "";
  for (const id of ["view-content", "chat-log", "follow-up-prompts", "toast-region"])
    $(id).innerHTML = "";
  $("chat-pending").hidden = true;
  $("nav-tx-count").textContent = "—";
  root.classList.remove("nav-open", "chat-expanded");
  $("workspace-shell").hidden = true;
  $("demo-login").hidden = false;
  $("demo-person").innerHTML =
    `<option value="">Choose a fictional person…</option>` +
    state.people
      .map(
        (p) =>
          `<option value="${esc(p.id)}">${esc(p.name)} — ${esc(p.role)} · ${esc(p.situation || "Fictional profile")}</option>`,
      )
      .join("");
  $("login-retry").hidden = !!state.people.length;
  updatePerson();
  previewPerson();
  loginControls(message);
}
function enterWorkspace(res) {
  ++state.epoch;
  state.session = res.session;
  state.workspace = res.workspace;
  state.profile = res.profile;
  state.people = res.profiles || state.people;
  storeSet("solvra.session.v3", res.session);
  storeSet("solvra.workspace.v1", res.workspace);
  state.messages = res.messages || [];
  state.pending = res.pending;
  state.voiceCaps = res.voice;
  state.plan = null;
  $("demo-login").hidden = true;
  $("workspace-shell").hidden = false;
  $("reporting-period").disabled = false;
  $("export-button").disabled = false;
  updatePerson();
  updateDashboard(res.dashboard);
  setView("overview");
  renderChat(false);
  voice?.configure(res.voice);
  financeAI?.restore();
  $("chat-input").value = res.restored ? storeGet("solvra.draft") || "" : "";
  if (!res.restored) {
    $("main-content").focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }
}
async function bootstrap() {
  state.loginBusy = true;
  loginControls("Checking demo access…");
  try {
    const res = unpack(
      await timed(
        server.workspace_action({
          op: "bootstrap",
          session: state.session,
          workspace: state.workspace,
        }),
      ),
    );
    if (res.authenticated) enterWorkspace(res);
    else
      showLogin(
        res,
        res.expired
          ? "This demo login expired. Choose a person to continue; expired server data is not retained."
          : undefined,
      );
  } catch (e) {
    showLogin({}, e.message || "The demo server is unavailable. Retry the connection.");
    $("login-retry").hidden = false;
  } finally {
    state.loginBusy = false;
    loginControls();
  }
}
async function loginDemo() {
  const profile_id = $("demo-person").value;
  if (state.loginBusy || !profile_id) return;
  state.loginBusy = true;
  loginControls("Opening this person’s fictional finances…");
  try {
    const res = unpack(
      await timed(
        server.workspace_action({
          op: "login",
          workspace: state.workspace,
          profile_id,
        }),
      ),
    );
    enterWorkspace(res);
  } catch (e) {
    loginControls(e.message || "Could not open this demo. Please try again.");
  } finally {
    state.loginBusy = false;
    loginControls();
  }
}
async function logoutDemo() {
  const session = state.session,
    workspace = state.workspace;
  state.loginBusy = true;
  showLogin({ profiles: state.people, workspace }, "Logging out and stopping voice and AI…");
  try {
    const res = unpack(await timed(server.workspace_action({ op: "logout", session, workspace })));
    showLogin(res, "Logged out. Choose another fictional person, or return to your saved demo.");
  } catch {
    loginControls(
      "Logged out in this tab. Server logout could not be confirmed; logging in again will replace the old demo login.",
    );
  } finally {
    state.loginBusy = false;
    loginControls();
    $("demo-person").focus();
  }
}
async function resetDemo() {
  if (state.busy) return;
  const epoch = state.epoch;
  setBusy(true);
  try {
    const r = await api("reset", { request_id: uid() });
    updateDashboard(r.dashboard);
    state.messages = [];
    state.pending = null;
    state.failed = null;
    state.plan = null;
    state.txResult = null;
    ++state.revision;
    state.tx = transactionFilters();
    $("app-dialog").close();
    renderView();
    renderChat(false);
    voice?.clearProfile();
    toast(`${state.profile.first_name}’s demo account and conversation have been reset.`);
  } catch (e) {
    toast(e.message, true);
  } finally {
    if (epoch === state.epoch) {
      setBusy(false);
      renderChat(false);
    }
  }
}
// Delegation keeps filters, newly rendered suggestions, and modal controls functional.
root.addEventListener("click", async (event) => {
  const b = event.target.closest("button, [data-tx]");
  if (!b || b.disabled) return;
  if (b.dataset.view) {
    if ($("app-dialog").open) $("app-dialog").close();
    setView(b.dataset.view);
    return;
  }
  if (b.dataset.prompt) {
    if ($("app-dialog").open) $("app-dialog").close();
    if (innerWidth <= 1060) toggleChat(true);
    sendMessage(b.dataset.prompt);
    return;
  }
  if (b.dataset.confirm) {
    sendMessage(b.dataset.confirm);
    return;
  }
  if (b.dataset.chart) {
    state.chart = b.dataset.chart;
    renderOverview();
    return;
  }
  if ("category" in b.dataset) {
    if ($("app-dialog").open) $("app-dialog").close();
    setView("transactions", {
      category: b.dataset.category,
      period: state.period,
      direction: b.dataset.direction || "",
    });
    return;
  }
  if (b.dataset.account) {
    setView("transactions", {
      account: b.dataset.account,
      period: "all",
    });
    return;
  }
  if (b.dataset.tx) {
    showTransaction(b.dataset.tx);
    return;
  }
  if (b.dataset.bill) {
    showBill(b.dataset.bill);
    return;
  }
  if (b.dataset.recordPayment) {
    paymentDialog(b.dataset.recordPayment);
    return;
  }
  if (b.dataset.billTab) {
    state.billTab = b.dataset.billTab;
    root.querySelectorAll("[data-bill-tab]").forEach((tab) => {
      const selected = tab.dataset.billTab === state.billTab;
      tab.classList.toggle("active", selected);
      tab.setAttribute("aria-pressed", String(selected));
    });
    $("bills-content").innerHTML = state.billTab === "bills" ? billTable() : planResultsMarkup();
    return;
  }
  if (b.dataset.page) {
    state.tx.page = Number(b.dataset.page);
    loadTransactions();
    return;
  }
  if (b.dataset.copyMessage) {
    const m = state.messages[Number(b.dataset.copyMessage)];
    try {
      await navigator.clipboard.writeText(m.content);
      toast("Answer copied.");
    } catch {
      toast("Copy is blocked by this browser. Select the answer text to copy it.", true);
    }
    return;
  }
  if (b.dataset.readMessage) {
    voice?.speak(state.messages[Number(b.dataset.readMessage)], true);
    return;
  }
  const action = b.dataset.action;
  if (action === "logout") {
    logoutDemo();
    return;
  }
  if (state.busy && ["clear-chat", "confirm-reset", "reset-now"].includes(action)) {
    toast("Wait for the current change or answer before clearing this session.");
    return;
  }
  if (action === "open-plan") {
    state.billTab = "plan";
    setView("bills");
    calculatePlan();
  }
  if (action === "recalculate-plan") calculatePlan();
  if (action === "add-transaction") addTransactionDialog();
  if (action === "retry-transactions") loadTransactions();
  if (action === "clear-filters") {
    state.tx = transactionFilters();
    renderTransactions();
  }
  if (action === "close-dialog") $("app-dialog").close();
  if (action === "retry-chat" && state.failed) sendMessage(state.failed.text, true);
  if (action === "toggle-factors") {
    $("health-factors").hidden = !$("health-factors").hidden;
    b.setAttribute("aria-expanded", String(!$("health-factors").hidden));
  }
  if (action === "help-voice") {
    $("app-dialog").close();
    if (innerWidth <= 1060) toggleChat(true);
    voice.startInline();
  }
  if (action === "voice-settings") {
    $("app-dialog").close();
    voice.open(true);
  }
  if (action === "settings-plan") {
    $("app-dialog").close();
    state.billTab = "plan";
    setView("bills");
  }
  if (action === "confirm-reset")
    openDialog(
      "Start fresh?",
      `<p class="dialog-copy">This will remove this session’s confirmed demo changes, pending changes, and conversation, then restore the original account. Other sessions will not be affected.</p><div class="dialog-actions"><button class="button secondary" data-action="close-dialog">Keep my workspace</button><button class="button coral" data-action="reset-now" data-busy-lock>Yes, reset demo</button></div>`,
      "A CLEAN SLATE",
    );
  if (action === "reset-now") resetDemo();
  if (action === "retry-bootstrap") bootstrap();
  if (action === "profile-settings") showSettings();
  if (action === "download-chat") {
    download(
      state.messages
        .map(
          (m) =>
            `${m.role === "user" ? "YOU" : "SOLVRA"}\n${m.content}${m.sources?.length ? "\nSources: " + m.sources.map((s) => s.label + ": " + s.detail).join("; ") : ""}`,
        )
        .join("\n\n"),
      "solvra-conversation.txt",
    );
    toast("Conversation downloaded.");
  }
  if (action === "clear-chat") {
    const epoch = state.epoch;
    voice?.stopAll();
    setBusy(true);
    try {
      await api("clear_chat");
      voice?.clearProfile();
      state.messages = [];
      state.failed = null;
      $("app-dialog").close();
      renderChat(false);
      toast("Conversation cleared. Account changes are kept.");
    } catch (e) {
      toast(e.message, true);
    } finally {
      if (epoch === state.epoch) {
        setBusy(false);
        renderChat(false);
      }
    }
  }
});
root.addEventListener("keydown", (event) => {
  if (event.target.matches("[data-tx]") && (event.key === "Enter" || event.key === " ")) {
    event.preventDefault();
    showTransaction(event.target.dataset.tx);
  }
});
root.addEventListener("input", (event) => {
  if (event.target.id === "tx-search") {
    state.tx.search = event.target.value;
    state.tx.page = 1;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadTransactions, 250);
  }
  if (event.target.id === "chat-input") storeSet("solvra.draft", event.target.value);
});
root.addEventListener("change", (event) => {
  const fields = {
    "tx-period": "period",
    "tx-category": "category",
    "tx-account": "account",
    "tx-direction": "direction",
  };
  if (fields[event.target.id]) {
    state.tx[fields[event.target.id]] = event.target.value;
    state.tx.page = 1;
    loadTransactions();
  }
  if (event.target.name === "kind" && event.target.form?.id === "add-transaction-form") {
    const cat = event.target.form.elements.category;
    cat.disabled = event.target.value === "income";
  }
});
root.addEventListener("submit", async (event) => {
  const form = event.target;
  if (form.id === "plan-form") {
    event.preventDefault();
    calculatePlan();
  }
  if (form.id === "simulate-form") {
    event.preventDefault();
    const button = form.querySelector("button"),
      output = $("simulation-output");
    button.disabled = true;
    try {
      const r = await api("simulate", {
        bill_id: $("sim-bill").value,
        days: Number($("sim-days").value),
      });
      const s = r.simulation;
      if (output.isConnected)
        output.innerHTML = `<div class="simulation-result"><b>${esc(s.bill)}, ${s.days} days late (${date(s.date)})</b><br>Modeled late fee: ${money(s.late_fees)} · interest: ${money(s.interest)}.<br>${s.risk ? esc(s.consequence) + "." : "No modeled service-risk deadline is crossed."}<br>Verify ${esc(s.provider)}’s terms. This is not an approved extension. Nothing has changed.</div>`;
    } catch (e) {
      toast(e.message, true);
    } finally {
      button.disabled = false;
    }
  }
  if (["add-transaction-form", "record-payment-form"].includes(form.id)) {
    event.preventDefault();
    if (state.busy) return toast("Wait for the current answer before recording a change.");
    const epoch = state.epoch;
    setBusy(true);
    const button = form.querySelector("button[type=submit],button:not([type])");
    button.disabled = true;
    const args = Object.fromEntries(new FormData(form));
    try {
      const res = await api(
        form.id === "record-payment-form" ? "stage_payment" : "stage_transaction",
        { ...args, request_id: uid() },
      );
      if (form.isConnected) $("app-dialog").close();
      acceptStagedResponse(
        res,
        form.id === "record-payment-form"
          ? `Record ${money(args.amount)} already paid toward a bill.`
          : `Record ${money(args.amount)} ${args.kind} for ${args.merchant}.`,
      );
    } catch (e) {
      const err = form.querySelector(".form-error");
      if (form.isConnected && err) {
        err.textContent = e.message;
        err.hidden = false;
      } else toast(e.message, true);
    } finally {
      button.disabled = false;
      if (epoch === state.epoch) {
        setBusy(false);
        renderChat();
      }
    }
  }
});
$("demo-login-form").addEventListener("submit", (e) => {
  e.preventDefault();
  loginDemo();
});
$("demo-person").addEventListener("change", previewPerson);
$("chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  sendMessage($("chat-input").value);
});
$("chat-input").value = storeGet("solvra.draft") || "";
$("chat-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    sendMessage(e.currentTarget.value);
  }
});
$("global-search-form").addEventListener("submit", (e) => {
  e.preventDefault();
  setView("transactions", {
    search: $("global-search").value,
    period: "all",
  });
});
$("global-search-form").addEventListener("click", (event) => {
  if (innerWidth <= 760 || event.target.closest("#global-search-toggle")) {
    $("global-search-form").classList.add("expanded");
    $("global-search").focus();
  }
});
$("global-search-form").addEventListener("focusout", (event) => {
  if (!event.currentTarget.contains(event.relatedTarget))
    event.currentTarget.classList.remove("expanded");
});
$("reporting-period").addEventListener("change", async (e) => {
  const select = e.target,
    revision = state.revision;
  select.disabled = true;
  try {
    const r = await api("dashboard", { period: select.value });
    if (revision !== state.revision) return;
    updateDashboard(r.dashboard);
    renderView();
  } catch (err) {
    if (revision !== state.revision) return;
    toast(err.message, true);
    select.value = state.period;
  } finally {
    select.disabled = false;
  }
});
$("export-button").addEventListener("click", downloadExport);
$("close-dialog").addEventListener("click", () => $("app-dialog").close());
$("expand-chat").addEventListener("click", () => toggleChat());
$("mobile-chat").addEventListener("click", () => toggleChat(true));
function setNavigation(open) {
  const nav = $("main-navigation"),
    menu = $("mobile-menu");
  if (!open && innerWidth <= 760 && nav.contains(document.activeElement)) menu.focus();
  root.classList.toggle("nav-open", open);
  menu.setAttribute("aria-expanded", String(open));
  menu.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
  nav.inert = innerWidth <= 760 && !open;
}
$("mobile-menu").addEventListener("click", () =>
  setNavigation(!root.classList.contains("nav-open")),
);
$("nav-backdrop").addEventListener("click", () => setNavigation(false));
const responsiveChange = () => {
  setNavigation(false);
  if (state.dashboard && state.view === "overview") renderOverview();
};
const navQuery = matchMedia("(max-width:760px)"),
  chartQuery = matchMedia("(max-width:500px)");
navQuery.addEventListener("change", responsiveChange);
chartQuery.addEventListener("change", responsiveChange);
setNavigation(false);
$("settings-button").addEventListener("click", () => state.dashboard && showSettings());
$("about-button").addEventListener("click", showHelp);
$("workspace-switch").addEventListener("click", showHelp);
$("profile-button").addEventListener("click", () => {
  if (!state.dashboard) return;
  openDialog(
    `${state.profile.name}’s demo space.`,
    `<div class="dialog-copy"><p><b>${esc(state.profile.role)} · ${esc(state.profile.household)}</b><br>${esc(state.profile.story)}</p><p>This is a fictional household, not your real bank account. All figures are anchored to <b>${date(state.dashboard.as_of, true)}</b>.</p><p><b>${num(state.dashboard.transaction_count)} ledger entries</b><br>Checking ${money(state.dashboard.checking)} · Savings ${money(state.dashboard.savings)}</p><p>Goal: ${esc(state.profile.goal)}</p><p>Each person’s finances and chat stay separate in this tab. Use Settings to log out. No real identity or bank details are required.</p></div><div class="dialog-actions"><button class="button secondary" data-action="profile-settings">Open settings ${icon("settings")}</button></div>`,
    "DEMO HOUSEHOLD",
  );
});
$("notifications-button").addEventListener("click", () => {
  if (!state.dashboard) return;
  openDialog(
    "A few dates for your diary.",
    `<div class="bills-mini">${state.dashboard.bills.slice(0, 6).map(billMini).join("") || '<p class="dialog-copy">You have no open bills.</p>'}</div><p class="form-note">Reminders from the demo bill register. No notifications are sent outside this app.</p>`,
    "UPCOMING REMINDERS",
  );
});
$("chat-options").addEventListener("click", () =>
  openDialog(
    "Your conversation.",
    `<div class="dialog-copy"><p>Keep a copy of the working, or start a new conversation. Clearing chat will not undo confirmed ledger changes.</p></div><div class="dialog-actions"><button class="button secondary" data-action="download-chat">${icon("download")}Download</button><button class="button secondary" data-action="clear-chat" data-busy-lock>${icon("refresh")}Clear chat</button><button class="button secondary" data-action="voice-settings">${icon("volume")}Voice settings</button><button class="button secondary" data-action="ai-settings">${icon("sparkles")}Grok AI settings</button></div>`,
    "MAKE IT YOURS",
  ),
);
for (const id of ["app-dialog", "voice-dialog"]) {
  $(id).addEventListener("click", (e) => {
    if (e.target === e.currentTarget) {
      const rect = e.currentTarget.getBoundingClientRect();
      if (
        e.clientX < rect.left ||
        e.clientX > rect.right ||
        e.clientY < rect.top ||
        e.clientY > rect.bottom
      )
        e.currentTarget.close();
    }
  });
}
const shortcuts = (e) => {
  if (!state.profile) return;
  if ((e.ctrlKey || e.metaKey) && e.key === "k") {
    e.preventDefault();
    $("global-search-form").classList.add("expanded");
    $("global-search").focus();
  }
  if (e.key === "Escape") setNavigation(false);
};
window.addEventListener("keydown", shortcuts);
icons();
// The appended voice module initializes the controller, then starts the workspace.
