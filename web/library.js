const $ = (id) => document.getElementById(id);
const audio = $("audio");
if ("audioSession" in navigator) {
  try { navigator.audioSession.type = "playback"; } catch {}
}
const panel = $("panel");
const notes = $("notes");
let expandedDraft = null;
const cap = (name) => name[0].toUpperCase() + name.slice(1);
const fmt = (n) =>
  Math.floor(n / 60) + ":" + String(Math.floor(n % 60)).padStart(2, "0");
function read(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function write(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {}
}
let episodes = [],
  current,
  seekOnLoad = null,
  startOnLoad = false;
let metadataReady = false,
  stamp = "",
  lastSave = 0;
const deep = new URLSearchParams(location.search);
function make(tag, text) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  return el;
}
function positionKey(id) {
  return "margin-radio/library/" + id + "/position";
}
function saveTime() {
  if (current && metadataReady)
    write(positionKey(current.id), String(audio.ended ? 0 : audio.currentTime));
}
function setLink(ep) {
  const u = new URL(location.href);
  u.searchParams.set("episode", ep.id);
  history.replaceState(null, "", u);
}
function renderShelf() {
  const rows = [];
  for (const ep of episodes) {
    const id = ep.id;
    const row = make("li");
    const button = make("button");
    button.type = "button";
    button.className = "episode";
    button.dataset.draft = id;
    const content = make("span");
    const name = make("strong", ep.title);
    name.className = "episode-name";
    const meta = make("span");
    meta.className = "episode-meta";
    const format = ep.mode === "audiobook" ? "有声书" : ep.mode === "podcast" ? "中文播客" : "听稿";
    const duration = make("span", fmt(ep.duration));
    duration.className = "episode-duration";
    meta.append(make("span", format), make("span", ep.voice), make("span", ep.chapters.length + " 章"), duration);
    content.append(name, meta);
    const arrow = make("span");
    arrow.className = "chevron";
    arrow.setAttribute("aria-hidden", "true");
    const body = make("div");
    body.id = "draft-" + id;
    button.setAttribute("aria-controls", body.id);
    button.append(content, arrow);
    button.onclick = () => {
      if (id !== current?.id) {
        choose(ep, true);
      } else {
        expandedDraft = expandedDraft === id ? null : id;
        syncShelf();
      }
    };
    row.append(button, body);
    rows.push(row);
  }
  $("list").replaceChildren(...rows);
  $("count").textContent = episodes.length + " 期";
  syncShelf();
}
function syncShelf() {
  notes.hidden = expandedDraft === null;
  for (const button of $("list").querySelectorAll(".episode")) {
    const id = button.dataset.draft;
    const expanded = id === expandedDraft;
    const body = button.nextElementSibling;
    button.setAttribute("aria-expanded", String(expanded));
    if (current?.id === id) {
      button.setAttribute("aria-current", "true");
      button.querySelector(".episode-duration").textContent = fmt(current.duration);
    } else {
      button.removeAttribute("aria-current");
    }
    body.hidden = !expanded;
    if (expanded && notes.parentElement !== body) body.append(notes);
  }
}
function chaptersUI() {
  const list = $("chapters");
  list.replaceChildren();
  $("summary").textContent = current.summary || "";
  $("materials").hidden = !current.summary && !current.readings?.length;
  $("materials").open = false;
  const readings = $("readings");
  readings.replaceChildren();
  for (const source of current.readings || []) {
    const details = make("details");
    details.append(make("summary", "中文材料 · " + source.label), make("p", source.chinese));
    if (/^https?:\/\//i.test(source.locator)) {
      const link = make("a", "打开原始材料 ↗");
      link.href = source.locator;
      link.target = "_blank";
      link.rel = "noreferrer";
      details.append(link);
    } else {
      details.append(make("small", source.locator));
    }
    readings.append(details);
  }
  for (const chapter of current.chapters) {
    const details = make("details");
    details.className = "chapter";
    const head = make("summary");
    const time = make("span", fmt(chapter.start));
    time.className = "stamp";
    head.append(time, make("span", chapter.title));
    const jump = make("button", "从此章播放");
    jump.type = "button";
    jump.onclick = () => {
      if (!metadataReady) {
        seekOnLoad = chapter.start;
        startOnLoad = true;
      } else {
        audio.currentTime = chapter.start;
        play();
      }
    };
    jump.className = "chapter-play";
    const prose = make("div");
    prose.className = "prose";
    prose.append(make("p", chapter.text), jump);
    details.append(head, prose);
    if (chapter.sources?.length)
      prose.append(make("small", "来源 · " + chapter.sources.join(" / ")));
    list.append(details);
  }
}
async function play() {
  try {
    await audio.play();
  } catch (e) {
    if (e.name !== "AbortError") message("暂时无法播放，可尝试下载 MP3。");
  }
}
function message(text = "") {
  $("status").textContent = text;
  $("status").hidden = !text;
}
function choose(ep, updateURL, at = null, autoplay = false, expand = true) {
  if (!ep) return;
  saveTime();
  metadataReady = false;
  audio.pause();
  current = ep;
  expandedDraft = expand ? ep.id : null;
  seekOnLoad = at;
  startOnLoad = autoplay;
  audio.src = ep.src;
  audio.defaultPlaybackRate = Number($("speed").value);
  $("player").hidden = false;
  $("title").textContent = ep.title;
  $("title").title = ep.title;
  $("download").href = ep.src;
  $("download").download = ep.title + "-" + cap(ep.voice) + ".mp3";
  chaptersUI();
  syncShelf();
  if (updateURL) setLink(ep);
  write("margin-radio/last-episode", ep.id);
  if ("mediaSession" in navigator && "MediaMetadata" in window) {
    navigator.mediaSession.metadata = new MediaMetadata({
      title: ep.title,
      artist: "页边电台 · " + cap(ep.voice),
      album: "我的节目库",
    });
  }
}
audio.addEventListener("loadedmetadata", () => {
  if (
    !current ||
    audio.currentSrc !== new URL(current.src, location.origin).href
  )
    return;
  const saved = Number(read(positionKey(current.id)));
  const at =
    seekOnLoad ?? (saved >= 1 && saved < audio.duration - 1 ? saved : 0);
  audio.currentTime = Math.max(0, Math.min(at, audio.duration));
  audio.playbackRate = Number($("speed").value);
  metadataReady = true;
  seekOnLoad = null;
  if (startOnLoad) {
    startOnLoad = false;
    play();
  }
});
audio.addEventListener("timeupdate", () => {
  if (Date.now() - lastSave > 1000) {
    saveTime();
    lastSave = Date.now();
  }
});
for (const e of ["pause", "seeked", "ended"])
  audio.addEventListener(e, saveTime);
audio.addEventListener("error", () =>
  message("音频读取失败，请确认仍连接节目库。"),
);
window.addEventListener("pagehide", saveTime);
$("speed").onchange = () => {
  audio.playbackRate = audio.defaultPlaybackRate = Number($("speed").value);
};
if ("mediaSession" in navigator) {
  const actions = {
    play,
    pause: () => audio.pause(),
    seekto: (e) => {
      if (metadataReady)
        audio.currentTime = Math.min(audio.duration, Math.max(0, e.seekTime));
    },
    seekbackward: (e) => {
      if (metadataReady)
        audio.currentTime = Math.max(
          0,
          audio.currentTime - (e.seekOffset || 10),
        );
    },
    seekforward: (e) => {
      if (metadataReady)
        audio.currentTime = Math.min(
          audio.duration,
          audio.currentTime + (e.seekOffset || 10),
        );
    },
  };
  for (const [name, cb] of Object.entries(actions)) {
    try {
      navigator.mediaSession.setActionHandler(name, cb);
    } catch {}
  }
}
let refreshing = false, revision = "";
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const res = await fetch("/api/episodes", {headers: revision ? {"If-None-Match": revision} : {}});
    if (res.status === 304) {
      if ($("status").textContent.includes("重试")) message();
      return;
    }
    if (!res.ok) throw new Error("读取节目库失败，稍后会自动重试。");
    const data = await res.json();
    revision = res.headers.get("etag") || "";
    const nextStamp = data.episodes.map((x) => x.id).join(",");
    if (stamp === nextStamp && current) {
      if ($("status").textContent.includes("重试")) message();
      return;
    }
    stamp = nextStamp;
    episodes = data.episodes;
    renderShelf();
    if (!current) {
      const requested = deep.get("episode");
      const explicit = episodes.find((ep) => ep.id === requested);
      const last = episodes.find(
        (ep) => ep.id === read("margin-radio/last-episode"),
      );
      const initial =
        explicit ||
        last ||
        episodes[0];
      choose(initial, false, null, false, Boolean(explicit));
      message(
        requested && !explicit
          ? "该节目尚未发布或链接有误，可先从节目库选择。"
          : episodes.length ? "" : "还没有节目。可在「使用方法」查看如何制作第一期。",
      );
    }
  } catch (e) {
    message("读取节目库失败，稍后会自动重试。");
  } finally {
    refreshing = false;
  }
}

refresh();
setInterval(() => {
  if (!document.hidden) refresh();
}, 5000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refresh();
  else saveTime();
});

$("how").onclick = () => panel.showModal();
$("close").onclick = () => panel.close();
$("compose").onsubmit = async (event) => {
  event.preventDefault();
  const submit = event.currentTarget.querySelector("button");
  submit.disabled = true;
  $("job").textContent = "正在本机配音…";
  try {
    const title = $("draft-title").value.trim();
    const text = $("draft-text").value.trim();
    const response = await fetch("/api/drafts", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({title, chapters: [{title, text}]}),
    });
    if (!response.ok) throw Error((await response.json()).error || "制作失败。");
    let job = await response.json();
    while (["rendering", "queued"].includes(job.status)) {
      await new Promise((resolve) => setTimeout(resolve, 800));
      const poll = await fetch("/api/jobs/" + encodeURIComponent(job.episode_id));
      if (!poll.ok) throw Error("读取制作进度失败。");
      job = await poll.json();
    }
    if (job.status !== "ready") throw Error(job.error || "配音失败。");
    await refresh();
    const link = make("a", "打开刚做好的节目");
    link.href = "/?episode=" + encodeURIComponent(job.episode_id);
    $("job").replaceChildren(link);
  } catch (error) {
    $("job").textContent = error.message;
  } finally {
    submit.disabled = false;
  }
};
