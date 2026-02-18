const state = {
  sessionId: localStorage.getItem("packDesignSession") || crypto.randomUUID(),
  apiKey: "",
  latestImageId: null,
  latestImageData: null,
  cadCode: null,
  session: null,
  activeScreen: 1,
};
localStorage.setItem("packDesignSession", state.sessionId);
state.apiKey = localStorage.getItem(`straiveUserApiKey:${state.sessionId}`) || "";

const el = {
  stepBadge: document.getElementById("stepBadge"),
  tab1: document.getElementById("tab1"),
  tab2: document.getElementById("tab2"),
  tab3: document.getElementById("tab3"),
  tab4: document.getElementById("tab4"),
  apiKeyInput: document.getElementById("apiKeyInput"),
  saveKeyBtn: document.getElementById("saveKeyBtn"),
  clearKeyBtn: document.getElementById("clearKeyBtn"),
  screen1: document.getElementById("screen1"),
  screen2: document.getElementById("screen2"),
  screen3: document.getElementById("screen3"),
  screen4: document.getElementById("screen4"),
  messages: document.getElementById("messages"),
  chatForm: document.getElementById("chatForm"),
  chatInput: document.getElementById("chatInput"),
  specSummary: document.getElementById("specSummary"),
  missingInfo: document.getElementById("missingInfo"),
  baselineStatus: document.getElementById("baselineStatus"),
  baselineCandidates: document.getElementById("baselineCandidates"),
  baselineMatch: document.getElementById("baselineMatch"),
  baselinePreview: document.getElementById("baselinePreview"),
  baselineSummary: document.getElementById("baselineSummary"),
  baselineSkipBtn: document.getElementById("baselineSkipBtn"),
  generate2dBtn: document.getElementById("generate2dBtn"),
  manualEdit: document.getElementById("manualEdit"),
  applyManualBtn: document.getElementById("applyManualBtn"),
  recCount: document.getElementById("recCount"),
  recList: document.getElementById("recList"),
  opProgress: document.getElementById("opProgress"),
  opProgressText: document.getElementById("opProgressText"),
  downloadCadBtn: document.getElementById("downloadCadBtn"),
  lockBtn: document.getElementById("lockBtn"),
  approvalStatus: document.getElementById("approvalStatus"),
  threeDText: document.getElementById("threeDText"),
  indexAssetsBtn: document.getElementById("indexAssetsBtn"),
  clearSessionBtn: document.getElementById("clearSessionBtn"),
  mainPreview: document.getElementById("mainPreview"),
  previewPlaceholder: document.getElementById("previewPlaceholder"),
  thumbs: document.getElementById("thumbs"),
  refreshCatalogBtn: document.getElementById("refreshCatalogBtn"),
  catalogCount: document.getElementById("catalogCount"),
  assetCatalogList: document.getElementById("assetCatalogList"),
};
let operationInFlight = false;

function addMessage(role, content) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = `${role.toUpperCase()}: ${content}`;
  el.messages.appendChild(div);
  el.messages.scrollTop = el.messages.scrollHeight;
}

function normalizeImageSource(value) {
  if (!value) return "";
  if (value.startsWith("http") || value.startsWith("data:image")) return value;
  return `data:image/png;base64,${value}`;
}

function renderMainImage(src) {
  if (!src) {
    el.mainPreview.style.display = "none";
    el.previewPlaceholder.style.display = "grid";
    return;
  }
  el.mainPreview.src = src;
  el.mainPreview.style.display = "block";
  el.previewPlaceholder.style.display = "none";
}

function renderThumbs(images) {
  el.thumbs.innerHTML = "";
  images.forEach((img) => {
    const tile = document.createElement("button");
    tile.type = "button";
    tile.className = "thumb";
    tile.innerHTML = `<img src="${normalizeImageSource(img.image_url_or_base64)}" alt="v${img.version}" /><span>v${img.version}</span>`;
    tile.addEventListener("click", () => {
      state.latestImageId = img.image_id;
      state.latestImageData = normalizeImageSource(img.image_url_or_base64);
      renderMainImage(state.latestImageData);
    });
    el.thumbs.appendChild(tile);
  });
}

function renderBaselineMatch(match) {
  if (!match || !match.asset_rel_path) {
    el.baselineMatch.hidden = true;
    return;
  }
  el.baselineMatch.hidden = false;
  el.baselinePreview.src = `/asset-files/${encodeURIComponent(match.asset_rel_path).replace(/%2F/g, "/")}`;
  el.baselineSummary.textContent = `${match.filename} | ${match.summary || "Matched baseline asset"} | score ${match.score}`;
}

function renderBaselineCandidates(matches, selectedRelPath) {
  el.baselineCandidates.innerHTML = "";
  if (!matches || !matches.length) {
    const row = document.createElement("div");
    row.className = "list-item";
    row.textContent = "No baseline candidates found yet.";
    el.baselineCandidates.appendChild(row);
    return;
  }

  matches.forEach((m, idx) => {
    const row = document.createElement("div");
    row.className = "list-item";
    const previewSrc = `/asset-files/${encodeURIComponent(m.asset_rel_path).replace(/%2F/g, "/")}`;
    const isSelected = selectedRelPath && selectedRelPath === m.asset_rel_path;
    row.innerHTML = `
      <strong>#${idx + 1} ${m.filename} ${isSelected ? "(Selected)" : ""}</strong>
      <img class="candidate-thumb" src="${previewSrc}" alt="${m.filename}" />
      <div class="list-meta">Score ${m.score} | ${m.summary || "Baseline candidate"}</div>
      <div class="list-meta">Type ${m.product_type || "-"} | Material ${m.material || "-"} | Closure ${m.closure_type || "-"}</div>
    `;
    const actions = document.createElement("div");
    actions.className = "inline-actions";
    const selectBtn = document.createElement("button");
    selectBtn.type = "button";
    selectBtn.className = "btn tiny";
    selectBtn.textContent = isSelected ? "Selected" : "Select & Continue";
    selectBtn.disabled = Boolean(isSelected);
    selectBtn.addEventListener("click", async () => {
      try {
        await apiPost("/api/image/adopt-baseline", {
          session_id: state.sessionId,
          asset_rel_path: m.asset_rel_path,
        });
        await refreshSession();
        setActiveScreen(2);
        addMessage("system", `Baseline selected: ${m.filename}. Continue in Edit Studio.`);
      } catch (err) {
        addMessage("system", err.message);
      }
    });
    actions.appendChild(selectBtn);
    row.appendChild(actions);
    el.baselineCandidates.appendChild(row);
  });
}

function setActiveScreen(screenNumber) {
  state.activeScreen = screenNumber;
  [el.tab1, el.tab2, el.tab3, el.tab4].forEach((tab, i) => tab.classList.toggle("active", i + 1 === screenNumber));
  [el.screen1, el.screen2, el.screen3, el.screen4].forEach((screen, i) => screen.classList.toggle("active", i + 1 === screenNumber));
}

function computeAllowedScreen(step, hasBaselineMatch = false) {
  if (step === 3 && hasBaselineMatch) return 2;
  if (step <= 3) return 1;
  if (step <= 5) return 2;
  return 3;
}

function renderAssetCatalog(items) {
  el.assetCatalogList.innerHTML = "";
  el.catalogCount.textContent = `Total assets: ${items.length}`;
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "list-item";
    empty.textContent = "No indexed assets found. Click Index Asset Metadata first.";
    el.assetCatalogList.appendChild(empty);
    return;
  }
  items.forEach((item) => {
    const card = document.createElement("div");
    card.className = "list-item";
    const previewSrc = `/asset-files/${encodeURIComponent(item.asset_rel_path).replace(/%2F/g, "/")}`;
    card.innerHTML = `
      <strong>${item.filename}</strong>
      <img class="candidate-thumb" src="${previewSrc}" alt="${item.filename}" />
      <div class="list-meta">${item.summary || "No summary"}</div>
      <div class="list-meta">Type: ${item.product_type || "-"} | Material: ${item.material || "-"} | Closure: ${item.closure_type || "-"}</div>
      <div class="list-meta">Style: ${item.design_style || "-"} | Size/Volume: ${item.size_or_volume || "-"}</div>
      <div class="list-meta">Tags: ${item.tags || "-"}</div>
      <div class="list-meta">Updated: ${item.updated_at}</div>
    `;
    el.assetCatalogList.appendChild(card);
  });
}


function formatSpec(spec) {
  const line = [
    `Product Type: ${spec.product_type || "Not provided"}`,
    `Approx Size/Volume: ${spec.size_or_volume || "Not provided"}`,
    `Intended Material: ${spec.intended_material || "Not provided"}`,
    `Closure Type: ${spec.closure_type || "Not provided"}`,
    `Design Style: ${spec.design_style || "Not provided"}`,
  ];
  if (spec.dimensions && Object.keys(spec.dimensions).length) {
    line.push(
      `Dimensions: ${Object.entries(spec.dimensions)
        .map(([k, v]) => `${k}=${v} mm`)
        .join(", ")}`,
    );
  }
  return line.join(" | ");
}

async function apiPost(url, body) {
  const headers = { "Content-Type": "application/json" };
  if (state.apiKey) headers["X-Straive-Api-Key"] = state.apiKey;
  const res = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Request failed");
  return data;
}

async function apiGet(url) {
  const headers = {};
  if (state.apiKey) headers["X-Straive-Api-Key"] = state.apiKey;
  const res = await fetch(url, { headers });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Request failed");
  return data;
}

function setOperationLoading(isLoading, text = "Processing...") {
  operationInFlight = isLoading;
  el.opProgress.hidden = !isLoading;
  if (isLoading) {
    el.opProgressText.textContent = text;
  }
  const locked = Boolean(isLoading);
  el.generate2dBtn.disabled = locked || el.generate2dBtn.disabled;
  el.applyManualBtn.disabled = locked || el.applyManualBtn.disabled;
  el.lockBtn.disabled = locked || el.lockBtn.disabled;
}

function updateFromSession(s) {
  state.session = s;
  el.stepBadge.textContent = `Workflow Step: ${s.step}`;
  el.specSummary.textContent = formatSpec(s.spec);
  el.missingInfo.textContent = (s.required_questions || []).length ? `Missing info: ${(s.required_questions || []).join(" ")}` : "";

  const baselineDecision = s.baseline_decision || "Baseline decision pending.";
  el.baselineStatus.textContent = baselineDecision;
  renderBaselineCandidates(s.baseline_matches || [], s.baseline_asset?.asset_rel_path || null);
  renderBaselineMatch(s.baseline_asset);
  const hasBaselineMatch = Boolean((s.baseline_matches || []).length);
  el.baselineSkipBtn.hidden = !(s.step >= 3 && !s.images?.length);

  renderThumbs(s.images || []);
  if (s.images && s.images.length) {
    const latest = s.images[s.images.length - 1];
    state.latestImageId = latest.image_id;
    state.latestImageData = normalizeImageSource(latest.image_url_or_base64);
    renderMainImage(state.latestImageData);
  } else {
    renderMainImage("");
  }

  el.generate2dBtn.disabled = !(s.step >= 3 && (!s.images || s.images.length === 0));
  el.applyManualBtn.disabled = !(s.step >= 4 && s.images && s.images.length && !s.lock_confirmed);
  el.lockBtn.disabled = !(s.step === 5 && s.lock_question_asked);
  if (operationInFlight) {
    setOperationLoading(true, el.opProgressText.textContent || "Processing...");
  }

  if (s.lock_confirmed) {
    el.approvalStatus.textContent = "Design locked. CAD generation in progress or completed.";
  } else if (s.step === 5) {
    el.approvalStatus.textContent = "Ready for approval. Confirm lock to generate CAD.";
  } else {
    el.approvalStatus.textContent = "Design not locked yet.";
  }

  if (s.cadquery_code) {
    state.cadCode = s.cadquery_code;
    el.downloadCadBtn.disabled = false;
    el.threeDText.textContent = "3D CAD generated. STEP export is supported from the provided CadQuery code.";
  } else {
    el.downloadCadBtn.disabled = true;
    el.threeDText.textContent = "3D CAD preview is available after lock + CAD generation.";
  }

  const allowed = computeAllowedScreen(s.step, hasBaselineMatch);
  el.tab2.disabled = allowed < 2;
  el.tab3.disabled = allowed < 3;
  const nextScreen = state.activeScreen === 4 ? 4 : Math.min(state.activeScreen, allowed);
  setActiveScreen(nextScreen || allowed);
}

async function refreshSession() {
  const data = await apiGet(`/api/session/${encodeURIComponent(state.sessionId)}`);
  updateFromSession(data.state);
  await refreshRecommendations();
}

async function refreshAssetCatalog() {
  const data = await apiGet("/api/assets/catalog");
  renderAssetCatalog(data.items || []);
}

async function refreshRecommendations() {
  if (!state.session || state.session.step < 4) {
    el.recCount.textContent = "0";
    el.recList.innerHTML = "";
    return;
  }
  const data = await apiGet(`/api/recommendations/${encodeURIComponent(state.sessionId)}`);
  el.recCount.textContent = String(data.count);
  el.recList.innerHTML = "";
  data.recommendations.forEach((rec) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "rec-item";
    btn.textContent = rec;
    btn.addEventListener("click", () => {
      el.manualEdit.value = rec;
      addMessage("system", "Recommendation copied to manual edit. Click Run Edit to apply.");
    });
    el.recList.appendChild(btn);
  });
}

async function sendChat(message) {
  addMessage("user", message);
  const data = await apiPost("/api/chat", { session_id: state.sessionId, user_message: message });
  addMessage("assistant", data.assistant_message);
  await refreshSession();

  if (data.can_generate_cad) {
    await generateCad();
  }
}

function build2DPromptFromSession() {
  const s = state.session || {};
  const spec = s.spec || {};
  const parts = [
    "Industrial packaging concept render, clean white background, studio lighting, front 3/4 view",
    `product type: ${spec.product_type || "not specified"}`,
    `size/volume: ${spec.size_or_volume || "not specified"}`,
    `material: ${spec.intended_material || "not specified"}`,
    `closure: ${spec.closure_type || "not specified"}`,
    `style: ${spec.design_style || "not specified"}`,
  ];
  if (spec.dimensions && Object.keys(spec.dimensions).length) {
    parts.push(
      "dimensions(mm): " +
        Object.entries(spec.dimensions)
          .map(([k, v]) => `${k}=${v}`)
          .join(", "),
    );
  }
  if (s.baseline_asset && s.baseline_asset.summary) {
    parts.push(`reference baseline: ${s.baseline_asset.summary}`);
  }
  return parts.join("; ");
}

async function generate2D() {
  const defaultPrompt = build2DPromptFromSession();
  const prompt = window.prompt("Enter 2D concept prompt", defaultPrompt);
  if (!prompt) return;
  setOperationLoading(true, "Generating 2D concept...");
  addMessage("system", "Generating 2D concept...");
  try {
    const res = await apiPost("/api/image/generate", { session_id: state.sessionId, prompt });
    addMessage("system", `Generated concept image version v${res.version}.`);
    await refreshSession();
  } finally {
    setOperationLoading(false);
  }
}

async function runManualEdit() {
  if (!state.latestImageId) {
    addMessage("system", "No baseline image found. Generate 2D concept first.");
    return;
  }
  const instruction = el.manualEdit.value.trim();
  if (!instruction) {
    addMessage("system", "Type a manual edit instruction first.");
    return;
  }
  setOperationLoading(true, "Applying edit to current design...");
  addMessage("system", "Applying edit...");
  try {
    const res = await apiPost("/api/image/edit", {
      session_id: state.sessionId,
      image_id: state.latestImageId,
      instruction_prompt: instruction,
    });
    addMessage("system", `Created iteration version v${res.version}.`);
    await refreshSession();
  } finally {
    setOperationLoading(false);
  }
}

async function lockDesign() {
  await sendChat("Yes, lock the design and proceed with 3D CAD generation.");
}

async function generateCad() {
  setOperationLoading(true, "Generating CAD code...");
  try {
    const res = await apiPost("/api/cad/generate", { session_id: state.sessionId });
    state.cadCode = res.cadquery_code;
    addMessage("assistant", `Final design summary: ${res.design_summary}\nSTEP export is supported from the provided CadQuery code.`);
    await refreshSession();
  } finally {
    setOperationLoading(false);
  }
}

function downloadCadCode() {
  if (!state.cadCode) return;
  const blob = new Blob([state.cadCode], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "pack_design.cq.py";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

async function indexAssetMetadata() {
  const res = await apiPost("/api/assets/index", { force_reindex: false });
  addMessage("system", `Indexed ${res.indexed_count} assets out of ${res.total_assets}.`);
  await refreshSession();
  await refreshAssetCatalog();
}

async function clearSessionState() {
  await apiPost("/api/session/clear", { session_id: state.sessionId });
  el.messages.innerHTML = "";
  el.manualEdit.value = "";
  state.latestImageId = null;
  state.latestImageData = null;
  state.cadCode = null;
  addMessage("system", "Session cleared. Start with packaging requirements.");
  await refreshSession();
  setActiveScreen(1);
}

el.chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = el.chatInput.value.trim();
  if (!message) return;
  el.chatInput.value = "";
  try {
    await sendChat(message);
  } catch (err) {
    addMessage("system", err.message);
  }
});

el.generate2dBtn.addEventListener("click", async () => {
  try {
    await generate2D();
  } catch (err) {
    addMessage("system", err.message);
  }
});

el.applyManualBtn.addEventListener("click", async () => {
  try {
    await runManualEdit();
  } catch (err) {
    addMessage("system", err.message);
  }
});

el.lockBtn.addEventListener("click", async () => {
  try {
    await lockDesign();
  } catch (err) {
    addMessage("system", err.message);
  }
});

el.downloadCadBtn.addEventListener("click", downloadCadCode);
el.indexAssetsBtn.addEventListener("click", async () => {
  try {
    await indexAssetMetadata();
  } catch (err) {
    addMessage("system", err.message);
  }
});

el.clearSessionBtn.addEventListener("click", async () => {
  try {
    await clearSessionState();
  } catch (err) {
    addMessage("system", err.message);
  }
});

el.tab1.addEventListener("click", () => setActiveScreen(1));
el.tab2.addEventListener("click", () => {
  if (!el.tab2.disabled) setActiveScreen(2);
});
el.tab3.addEventListener("click", () => {
  if (!el.tab3.disabled) setActiveScreen(3);
});
el.tab4.addEventListener("click", async () => {
  setActiveScreen(4);
  try {
    await refreshAssetCatalog();
  } catch (err) {
    addMessage("system", err.message);
  }
});

el.baselineSkipBtn.addEventListener("click", async () => {
  try {
    await apiPost("/api/baseline/skip", { session_id: state.sessionId });
    await refreshSession();
    setActiveScreen(2);
    addMessage("system", "Proceeding without baseline. Generate 2D concept to start design.");
  } catch (err) {
    addMessage("system", err.message);
  }
});

el.refreshCatalogBtn.addEventListener("click", async () => {
  try {
    await refreshAssetCatalog();
  } catch (err) {
    addMessage("system", err.message);
  }
});

(async function init() {
  el.apiKeyInput.value = state.apiKey;
  addMessage("system", "Session initialized. Start with packaging requirements.");
  try {
    await refreshSession();
    await refreshAssetCatalog();
  } catch (err) {
    addMessage("system", "Unable to restore previous session state.");
  }
})();

el.saveKeyBtn.addEventListener("click", async () => {
  state.apiKey = el.apiKeyInput.value.trim();
  const scopedKeyStorageId = `straiveUserApiKey:${state.sessionId}`;
  if (state.apiKey) {
    localStorage.setItem(scopedKeyStorageId, state.apiKey);
  }
  addMessage("system", state.apiKey ? "User API key saved for this browser." : "No key entered.");
});

el.clearKeyBtn.addEventListener("click", async () => {
  state.apiKey = "";
  const scopedKeyStorageId = `straiveUserApiKey:${state.sessionId}`;
  localStorage.removeItem(scopedKeyStorageId);
  el.apiKeyInput.value = "";
  addMessage("system", "User API key cleared.");
});
