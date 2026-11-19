// Slideshow: poll /state, crossfade to the new photo, tap right = next, tap left = previous.
const q = new URLSearchParams(location.search);
const key = q.get("key") || "";
const device = q.get("device") || "default";

const $ = (id) => document.getElementById(id);
const imgs = [$("a"), $("b")];
let front = 1, shownId = null, url = null, failures = 0, timer = null, stopped = false, running = null, again = false;

// One common factor keeps the screen's shape; w and h each end up within 320-4096.
function size() {
  const w = innerWidth * devicePixelRatio, h = innerHeight * devicePixelRatio;
  const f = Math.max(320 / Math.min(w, h), Math.min(1, 4096 / Math.max(w, h)));
  return `w=${Math.round(w * f)}&h=${Math.round(h * f)}`;  // extreme aspect ratios can still exceed 4096: the server refuses them
}
const call = (path, method = "GET") =>
  fetch(path + (path.includes("?") ? "&" : "?") + "device=" + encodeURIComponent(device),
    { method, headers: { Authorization: "Bearer " + key }, signal: AbortSignal.timeout ? AbortSignal.timeout(30000) : undefined });  // no timeout on older tablets, which lack AbortSignal.timeout

async function check(r) {
  if (r.ok) return r;
  if (r.status === 401) { stopped = true; say("Key not accepted"); }
  else if (r.status === 422 || r.status === 503) say((await r.json().catch(() => ({}))).detail || (r.status === 503 ? "Waiting for photos" : "Request refused"));
  throw new Error(String(r.status));
}

function say(text) { $("msg").textContent = text; $("msg").hidden = !text; }

async function show(id) {
  const blob = await (await check(await call("/image.jpg?" + size()))).blob();
  const next = URL.createObjectURL(blob);
  const img = imgs[1 - front];
  img.src = next;
  await img.decode();
  img.classList.add("on");
  imgs[front].classList.remove("on");
  front = 1 - front;
  if (url) URL.revokeObjectURL(url);
  url = next;
  shownId = id;
}

async function run() {
  let delay = 30000;
  try {
    const s = await (await check(await call("/state"))).json();
    if (s.asset_id && s.asset_id !== shownId) await show(s.asset_id);
    $("caption").textContent = s.caption || "";
    failures = 0;
    $("dot").hidden = true;
    say("");
    if (s.next_change_at) delay = Math.min(delay, Math.max(1000, Date.parse(s.next_change_at) - Date.now() + 500));
  } catch (e) {
    if (stopped) return;
    failures++;
    $("dot").hidden = failures < 5;
    delay = Math.min(300000, 5000 * 2 ** (failures - 1));
  }
  clearTimeout(timer);
  timer = setTimeout(tick, delay);
}

// One poll at a time; a tap or timer that fires meanwhile just asks for one more run afterwards.
function tick() {
  if (running) { again = true; return; }
  clearTimeout(timer);
  running = run().finally(() => { running = null; if (again) { again = false; tick(); } });
}

addEventListener("click", async (e) => {
  if (stopped) return;
  try { await check(await call(e.clientX > innerWidth / 2 ? "/next" : "/previous", "POST")); }
  catch (err) { if (String(err.message) !== "409") return; }  // 409: no history, nothing to do
  tick();
});

tick();
