(() => {
  const field = (id) => document.getElementById(id);
  const panel = field("voice-panel");
  let listing;

  function populate(saved) {
    const provider = saved?.provider || field("provider").value;
    const preset = listing.presets[provider];
    field("provider").value = provider;
    field("profile-name").value = saved?.name || preset.label;
    for (const key of ["endpoint", "model", "voice"]) field(key).value = saved?.[key] ?? preset[key];
    field("endpoint").readOnly = !!preset.endpoint;
    field("voices").replaceChildren(...preset.voices.map((name) => new Option(name, name)));
    field("api-key").value = "";
    field("key-hint").textContent = saved?.has_key
      ? "此配置已保存密钥。同一端点留空沿用，填写新值即可更换。"
      : "密钥保存在这台电脑上。自定义免密接口可以留空。";
    field("settings-result").textContent = "";
  }

  function display(data) {
    listing = data;
    field("provider").replaceChildren(...Object.entries(data.presets).map(([id, p]) => new Option(p.label, id)));
    field("saved-profile").replaceChildren(new Option("新建配置", ""), ...data.profiles.map((p) => new Option(p.name, p.id)));
    field("saved-profile").value = data.active || "";
    const current = data.profiles.find((p) => p.id === data.active);
    populate(current);
    field("active-voice").textContent = current
      ? [current.name, current.model, current.voice].join(" · ")
      : "首次制作请打开「配音设置」，选择供应商、模型和音色。";
  }

  async function load() {
    const response = await fetch("/api/tts-profiles");
    if (!response.ok) throw Error("读取配音配置失败。");
    display(await response.json());
  }

  async function open() {
    panel.showModal();
    field("voice-form").hidden = true;
    try {
      await load();
      field("voice-form").hidden = false;
    } catch {
      field("settings-result").textContent = "读取配音配置失败，请关闭后重试。";
    }
  }
  field("settings").onclick = open;
  field("voice-close").onclick = () => panel.close();
  panel.onclose = () => { field("api-key").value = ""; };
  field("provider").onchange = () => populate(null);
  field("saved-profile").onchange = () => populate(listing.profiles.find((p) => p.id === field("saved-profile").value));
  field("voice-form").onsubmit = async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      const payload = {id:field("saved-profile").value, name:field("profile-name").value, token:field("api-key").value};
      for (const key of ["provider", "endpoint", "model", "voice"]) payload[key] = field(key).value;
      const response = await fetch("/api/tts-profiles", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
      const data = await response.json();
      if (!response.ok) throw Error(data.error || "保存失败。");
      display(data);
      field("settings-result").textContent = "已保存，将使用此配置制作节目。";
    } catch (error) {
      field("settings-result").textContent = error.message;
    } finally {
      button.disabled = false;
    }
  };
  if (location.hash === "#settings") open();
  else load().catch(() => { field("active-voice").textContent = "读取配音配置失败，请打开「配音设置」重试。"; });
})();
