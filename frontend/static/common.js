const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast show" + (err ? " err" : "");
  clearTimeout(toast.t); toast.t = setTimeout(() => (t.className = "toast"), 3800);
}

async function api(path, opts = {}) {
  const r = await fetch(path, { credentials: "same-origin", ...opts });
  if (r.status === 401 && !path.startsWith("/api/auth/")) { location.href = "/login"; throw new Error("Session expired"); }
  if (!r.ok) {
    let d = r.statusText;
    try { const j = await r.json(); d = typeof j.detail === "string" ? j.detail : j.detail?.map((x) => x.msg).join("; ") || d; } catch {}
    throw new Error(d);
  }
  return r.status === 204 ? null : r.json();
}
const jsonOpts = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const guard = (fn) => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message, true); } };
const fmtDate = (d) => new Date(d).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });

async function logout() { try { await api("/api/auth/logout", { method: "POST" }); } finally { location.href = "/login"; } }

// sidebar: "Dashboard" shows all tiles, other entries show one tile full-width
function initNav(onShow) {
  const grid = $(".bento");
  $$("nav a").forEach((a) => a.addEventListener("click", () => {
    $$("nav a").forEach((x) => x.classList.toggle("on", x === a));
    const tile = a.dataset.view;
    grid.classList.toggle("single", tile !== "all");
    $$(".card", grid).forEach((c) => c.classList.toggle("show", c.dataset.tile === tile));
    onShow?.(tile);
  }));
  $("#logoutBtn").addEventListener("click", logout);
}

function dropzone(zone, input, onPick) {
  zone.addEventListener("click", () => input.click());
  ["dragover", "dragenter"].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => zone.addEventListener(ev, () => zone.classList.remove("over")));
  zone.addEventListener("drop", (e) => { e.preventDefault(); input.files = e.dataTransfer.files; onPick(); });
  input.addEventListener("change", onPick);
}
