/* OSS Pulse dashboard: renders site/data/*.json with Observable Plot. */
"use strict";

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const fmtInt = d3.format(",");
const fmtPct = (v) => (v == null ? "n/a" : d3.format(".0%")(v));
const fmtHours = (h) => {
  if (h == null) return "n/a";
  if (h < 1) return `${Math.round(h * 60)} min`;
  if (h < 48) return `${h.toFixed(1)} h`;
  return `${(h / 24).toFixed(1)} d`;
};
const shortRepo = (r) => r.split("/")[1];

async function load(name) {
  const res = await fetch(`data/${name}.json`);
  if (!res.ok) throw new Error(`data/${name}.json: ${res.status}`);
  return res.json();
}

function width(el) {
  return Math.max(320, Math.min(el.clientWidth || 960, 1040));
}

/* ---------- sortable table ---------- */
function renderTable(table, rows, columns) {
  let sortKey = null;
  let sortDir = -1;
  const draw = () => {
    const sorted = sortKey
      ? [...rows].sort((a, b) => {
          const x = a[sortKey], y = b[sortKey];
          if (x == null) return 1;
          if (y == null) return -1;
          return (x < y ? -1 : x > y ? 1 : 0) * sortDir;
        })
      : rows;
    table.innerHTML = "";
    const head = table.createTHead().insertRow();
    for (const col of columns) {
      const th = document.createElement("th");
      th.textContent = col.label;
      th.title = col.title || "";
      if (col.key === sortKey) th.setAttribute("aria-sort", sortDir > 0 ? "ascending" : "descending");
      th.addEventListener("click", () => {
        sortDir = sortKey === col.key ? -sortDir : (col.asc ? 1 : -1);
        sortKey = col.key;
        draw();
      });
      head.appendChild(th);
    }
    const body = table.createTBody();
    for (const row of sorted) {
      const tr = body.insertRow();
      for (const col of columns) {
        const td = tr.insertCell();
        const v = row[col.key];
        const text = col.fmt ? col.fmt(v, row) : v ?? "";
        if (col.cls) td.className = col.cls(v, row);
        td.textContent = text;
      }
    }
  };
  draw();
}

/* ---------- sections ---------- */
function renderMeta(meta) {
  document.getElementById("meta").textContent =
    `As of ${meta.as_of} · ${meta.repos} repositories · ${fmtInt(meta.prs_in_window)} PRs in the ` +
    `365-day window · ${fmtInt(meta.human_contributors)} pseudonymised contributors · ` +
    `generated ${meta.generated_at.replace("T", " ").replace("+00:00", " UTC")}`;
}

function renderScorecard(rows) {
  renderTable(document.getElementById("scorecard-table"), rows, [
    { key: "repo", label: "Repository", asc: true },
    { key: "prs_opened", label: "PRs", fmt: fmtInt },
    { key: "merge_rate", label: "Merge rate", fmt: fmtPct },
    { key: "median_hours_to_first_response", label: "Median 1st response", fmt: fmtHours, asc: true },
    { key: "share_responded_within_24h", label: "Answered < 24 h", fmt: fmtPct },
    { key: "share_unanswered_7d", label: "Unanswered 7 d", fmt: fmtPct, asc: true },
    { key: "median_hours_to_merge", label: "Median to merge", fmt: fmtHours, asc: true },
    { key: "merger_bus_factor", label: "Merger bus factor", fmt: (v) => v ?? "n/a" },
    { key: "newcomer_return_rate_90d", label: "Newcomers return", fmt: fmtPct,
      title: "Newcomers who opened another PR within 90 days" },
    { key: "downloads_last_30d", label: "PyPI 30 d", fmt: (v) => (v == null ? "n/a" : d3.format(".3s")(v)) },
    { key: "downloads_growth_30d", label: "vs prev 30 d", fmt: (v) => (v == null ? "n/a" : d3.format("+.0%")(v)) },
  ]);
}

function renderLatency(rows) {
  const el = document.getElementById("latency-chart");
  const data = rows.filter((d) => d.median_hours_to_first_response != null);
  const order = d3.sort(data, (d) => d.median_hours_to_first_response).map((d) => d.repo);
  el.replaceChildren(
    Plot.plot({
      width: width(el),
      height: 28 * data.length + 60,
      marginLeft: 230,
      x: { type: "log", label: "hours to first human response →", grid: true },
      y: { domain: order, label: null },
      marks: [
        Plot.barX(data, { y: "repo", x1: 0.01, x2: "median_hours_to_first_response", fill: css("--accent"),
          title: (d) => `${d.repo}\nmedian ${fmtHours(d.median_hours_to_first_response)}\np90 ${fmtHours(d.p90_hours_to_first_response)}` }),
        Plot.tickX(data, { y: "repo", x: "p90_hours_to_first_response", stroke: css("--accent-2"), strokeWidth: 2 }),
        Plot.ruleX([24], { stroke: css("--muted"), strokeDasharray: "3,3" }),
      ],
    })
  );
}

function renderDistribution(rows) {
  const el = document.getElementById("distribution-chart");
  const buckets = d3.sort(d3.groups(rows, (d) => d.bucket), ([, v]) => v[0].bucket_order).map(([b]) => b);
  const fast = d3.rollup(rows.filter((d) => d.bucket_order <= 3), (v) => d3.sum(v, (d) => d.share), (d) => d.repo);
  const order = d3.sort([...new Set(rows.map((d) => d.repo))], (r) => -(fast.get(r) || 0));
  el.replaceChildren(
    Plot.plot({
      width: width(el),
      height: 28 * order.length + 80,
      marginLeft: 230,
      x: { label: "share of PRs →", tickFormat: "%" },
      y: { domain: order, label: null },
      color: { domain: buckets, scheme: "RdYlBu", reverse: true, legend: true },
      marks: [
        Plot.barX(rows, { y: "repo", x: "share", fill: "bucket", order: buckets,
          title: (d) => `${d.repo}\n${d.bucket}: ${fmtPct(d.share)} (${fmtInt(d.prs)} PRs)` }),
      ],
    })
  );
}

function renderNewcomers(rows) {
  const el = document.getElementById("newcomer-chart");
  const data = rows.filter((d) => d.median_hours_to_first_response != null && d.prs_opened >= 10);
  const order = d3.sort(
    d3.groups(data, (d) => d.repo),
    ([, v]) => -(v.find((d) => d.contributor_type === "newcomer")?.median_hours_to_first_response ?? 0)
  ).map(([r]) => r);
  el.replaceChildren(
    Plot.plot({
      width: width(el),
      height: 28 * order.length + 80,
      marginLeft: 230,
      x: { type: "log", label: "median hours to first response →", grid: true },
      y: { domain: order, label: null },
      color: { domain: ["maintainer", "returning_contributor", "newcomer"],
        range: [css("--good"), css("--accent"), css("--accent-2")], legend: true },
      marks: [
        Plot.ruleY(order, { stroke: css("--line") }),
        Plot.dot(data, { y: "repo", x: "median_hours_to_first_response", fill: "contributor_type", r: 5,
          title: (d) => `${d.repo} · ${d.contributor_type}\n${fmtHours(d.median_hours_to_first_response)} · ${fmtInt(d.prs_opened)} PRs · merge rate ${fmtPct(d.merge_rate)}` }),
      ],
    })
  );
}

function renderActivity(rows) {
  const select = document.getElementById("activity-repo");
  const repos = [...new Set(rows.map((d) => d.repo))].sort();
  select.replaceChildren(...repos.map((r) => new Option(r, r)));
  select.value = repos.includes("apache/airflow") ? "apache/airflow" : repos[0];
  const el = document.getElementById("activity-chart");
  const draw = () => {
    const data = rows.filter((d) => d.repo === select.value).flatMap((d) => [
      { week: new Date(d.week), series: "opened", n: d.prs_opened },
      { week: new Date(d.week), series: "merged", n: d.prs_merged },
      { week: new Date(d.week), series: "closed unmerged", n: d.prs_closed_unmerged },
    ]);
    el.replaceChildren(
      Plot.plot({
        width: width(el),
        height: 300,
        y: { label: "PRs per week", grid: true },
        x: { label: null },
        color: { domain: ["opened", "merged", "closed unmerged"],
          range: [css("--accent"), css("--good"), css("--accent-2")], legend: true },
        marks: [Plot.lineY(data, { x: "week", y: "n", stroke: "series", strokeWidth: 2 }), Plot.ruleY([0])],
      })
    );
  };
  select.addEventListener("change", draw);
  draw();
}

function renderDownloads(rows) {
  const el = document.getElementById("downloads-chart");
  const data = rows.map((d) => ({ ...d, week: new Date(d.week) }));
  const last = d3.rollup(data, (v) => d3.greatest(v, (d) => d.week), (d) => d.package);
  el.replaceChildren(
    Plot.plot({
      width: width(el),
      height: 420,
      marginRight: 130,
      y: { type: "log", label: "downloads per week", grid: true, tickFormat: "~s" },
      x: { label: null },
      color: { scheme: "tableau10" },
      marks: [
        Plot.lineY(data, { x: "week", y: "downloads", stroke: "package", strokeWidth: 1.6 }),
        Plot.text([...last.values()], { x: "week", y: "downloads", text: "package", fill: "package",
          dx: 6, textAnchor: "start", fontSize: 11 }),
      ],
    })
  );
}

function renderHealth(freshness, anomalies, coverage) {
  renderTable(document.getElementById("freshness-table"), freshness, [
    { key: "source_name", label: "Source", asc: true },
    { key: "latest_loaded_at", label: "Latest", fmt: (v) => (v ? v.replace("T", " ").slice(0, 16) : "never") },
    { key: "lag_hours", label: "Lag", fmt: fmtHours },
    { key: "row_count", label: "Rows", fmt: fmtInt },
    { key: "status", label: "Status", cls: (v) => `status-${v}` },
  ]);
  renderTable(document.getElementById("anomaly-table"), anomalies, [
    { key: "obs_date", label: "Date" },
    { key: "series", label: "Series", asc: true },
    { key: "entity", label: "Entity", asc: true },
    { key: "value", label: "Value", fmt: (v) => d3.format(",.0f")(v) },
    { key: "trailing_mean", label: "Trailing mean", fmt: (v) => d3.format(",.0f")(v) },
    { key: "ratio_to_trailing", label: "Ratio", fmt: (v) => (v == null ? "n/a" : d3.format(".2f")(v)) },
    { key: "direction", label: "Direction" },
  ]);
  const el = document.getElementById("coverage-chart");
  const data = coverage.map((d) => ({ ...d, date: new Date(d.volume_date) }));
  el.replaceChildren(
    Plot.plot({
      width: width(el),
      height: 280,
      y: { type: "log", label: "public events per hour", grid: true, tickFormat: "~s" },
      x: { label: null },
      marks: [
        Plot.lineY(data, { x: "date", y: "avg_events_per_hour", stroke: css("--muted") }),
        Plot.dot(data, { x: "date", y: "avg_events_per_hour",
          fill: (d) => (d.coverage_ratio != null && d.coverage_ratio < 0.2 ? css("--bad") : css("--accent")),
          title: (d) => `${d.volume_date}: ${fmtInt(Math.round(d.avg_events_per_hour))} events/hour over ${d.hours_loaded} h` }),
      ],
    })
  );
}

/* ---------- locate a PR (client-side, GitHub REST) ---------- */
const BOT = /(\[bot\]|-bot)$/i;
const KNOWN_BOTS = new Set(["asfgit", "codecov-commenter", "github-actions", "dependabot", "renovate",
  "pre-commit-ci", "sonarcloud", "netlify", "vercel", "boring-cyborg", "polars-bot"]);
const isBot = (user) => !user || user.type === "Bot" || BOT.test(user.login) || KNOWN_BOTS.has(user.login.toLowerCase());

async function gh(path) {
  const res = await fetch(`https://api.github.com/${path}`, { headers: { Accept: "application/vnd.github+json" } });
  if (res.status === 403 || res.status === 429) throw new Error("GitHub API rate limit reached; try again later.");
  if (!res.ok) throw new Error(`GitHub API ${res.status} for ${path}`);
  return res.json();
}

function setupLocate(quantiles) {
  const byRepo = new Map(quantiles.map((q) => [q.repo, q]));
  const out = document.getElementById("locate-result");
  document.getElementById("locate-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const url = document.getElementById("locate-url").value.trim();
    const m = url.match(/github\.com\/([^/]+\/[^/]+)\/pull\/(\d+)/);
    if (!m) { out.textContent = "That does not look like a GitHub pull request URL."; return; }
    const [, repo, number] = m;
    const q = byRepo.get(repo);
    if (!q) { out.textContent = `${repo} is not one of the tracked repositories.`; return; }
    out.textContent = "Asking GitHub…";
    try {
      const [pr, reviews, comments] = await Promise.all([
        gh(`repos/${repo}/pulls/${number}`),
        gh(`repos/${repo}/pulls/${number}/reviews?per_page=100`),
        gh(`repos/${repo}/issues/${number}/comments?per_page=100`),
      ]);
      const opened = new Date(pr.created_at);
      const author = pr.user?.login;
      const times = [
        ...reviews.filter((r) => r.submitted_at).map((r) => ({ at: r.submitted_at, user: r.user })),
        ...comments.map((c) => ({ at: c.created_at, user: c.user })),
      ]
        .filter((e) => !isBot(e.user) && e.user.login !== author && new Date(e.at) >= opened)
        .map((e) => new Date(e.at));
      const scorecard = window.__scorecard.find((r) => r.repo === repo);
      if (!times.length) {
        out.textContent = `${repo}#${number} has no human response yet (opened ${pr.created_at.slice(0, 10)}). ` +
          `In this repo ${fmtPct(q.share_unanswered)} of PRs in the window never got one; the median wait is ` +
          `${fmtHours(scorecard?.median_hours_to_first_response)}.`;
        return;
      }
      const hours = (d3.min(times) - opened) / 36e5;
      const faster = q.quantiles.filter((v) => v < hours).length / q.quantiles.length;
      const rank = faster * (1 - q.share_unanswered);
      out.textContent = `${repo}#${number}: first human response after ${fmtHours(hours)}. ` +
        `That is slower than about ${fmtPct(rank)} of the ${fmtInt(q.prs)} PRs opened in the window ` +
        `(repo median ${fmtHours(scorecard?.median_hours_to_first_response)}; ` +
        `${fmtPct(q.share_unanswered)} have no human response yet).`;
    } catch (err) {
      out.textContent = err.message;
    }
  });
}

/* ---------- boot ---------- */
(async function main() {
  try {
    const names = ["meta", "scorecard", "distribution", "latency_by_type", "weekly_activity",
      "weekly_downloads", "freshness", "anomalies", "gharchive_coverage", "response_quantiles"];
    const data = Object.fromEntries(await Promise.all(names.map(async (n) => [n, await load(n)])));
    window.__scorecard = data.scorecard;
    renderMeta(data.meta);
    renderScorecard(data.scorecard);
    renderLatency(data.scorecard);
    renderDistribution(data.distribution);
    renderNewcomers(data.latency_by_type);
    renderActivity(data.weekly_activity);
    renderDownloads(data.weekly_downloads);
    renderHealth(data.freshness, data.anomalies, data.gharchive_coverage);
    setupLocate(data.response_quantiles);
  } catch (err) {
    document.getElementById("meta").textContent = `Could not load data: ${err.message}`;
  }
})();
