const state = {
  sessionId: localStorage.getItem("packDesignSession") || crypto.randomUUID(),
  apiKey: "",
  latestImageId: null,
  latestImageData: null,
  session: null,
  activeScreen: 1,
};
const BASELINE_MIN_DELAY_MS = 3000;
const BASELINE_DECISION_MESSAGES = new Set([
  "Searching for a similar baseline design…",
  "No close baseline found. Creating a new concept.",
]);
const DEFAULT_CAD_SHEET_PROMPT =
  "Use the provided product image as reference and generate a professional mechanical CAD engineering drawing sheet of the object. Analyze the geometry, proportions, symmetry, and structure from the image and convert it into a precise technical drafting layout suitable for manufacturing documentation.\n\nDrawing Requirements:\n1. Generate complete orthographic projections:\n- Front View\n- Top View\n- Right Side View\n- Sectional View (cut through central axis if applicable)\n- Exploded View (if the object has multiple components)\n2. Include engineering detailing:\n- Centerlines\n- Hidden lines\n- Dimension lines with arrowheads\n- Proper scaling\n- Units in millimeters\n- Thread representation (if applicable)\n- Wall thickness callouts (if hollow)\n- Material labels (estimated from visual cues)\n- Standard tolerances (±0.1 mm unless otherwise required)\n3. Layout Specifications:\n- A3 engineering sheet format\n- Third-angle projection\n- Title block at bottom-right\n- Drawing name: Based on detected object\n- Scale: 1:1 (or appropriate estimated scale)\n- Clean mechanical drafting style\n- Black/gray linework\n- White or beige blueprint-style background\n- Proper borders and alignment\n4. If exact dimensions are not visible:\n- Infer realistic proportional dimensions based on object type\n- Maintain accurate relative proportions\n- Clearly mark inferred values as estimated\n5. Output:\n- High-resolution engineering drawing sheet\n- Manufacturing-ready visual format\n- Clean CAD blueprint style (not artistic sketch)\nStyle Reference: Industrial mechanical drafting / technical blueprint / SolidWorks drawing sheet style.";
localStorage.setItem("packDesignSession", state.sessionId);
state.apiKey = localStorage.getItem(`straiveUserApiKey:${state.sessionId}`) || "";

const el = {
  stepBadge: document.getElementById("stepBadge"),
  tab1: document.getElementById("tab1"),
  tab2: document.getElementById("tab2"),
  tab3: document.getElementById("tab3"),
  tab4: document.getElementById("tab4"),
  openKeyModalBtn: document.getElementById("openKeyModalBtn"),
  keyStateBadge: document.getElementById("keyStateBadge"),
  keyModal: document.getElementById("keyModal"),
  apiKeyPopupInput: document.getElementById("apiKeyPopupInput"),
  saveKeyPopupBtn: document.getElementById("saveKeyPopupBtn"),
  clearKeyPopupBtn: document.getElementById("clearKeyPopupBtn"),
  closeKeyModalBtn: document.getElementById("closeKeyModalBtn"),
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
  continueBaselineBtn: document.getElementById("continueBaselineBtn"),
  baselineCandidates: document.getElementById("baselineCandidates"),
  baselineMatch: document.getElementById("baselineMatch"),
  baselinePreview: document.getElementById("baselinePreview"),
  baselineSummary: document.getElementById("baselineSummary"),
  baselineSkipBtn: document.getElementById("baselineSkipBtn"),
  baselineProgress: document.getElementById("baselineProgress"),
  baselineProgressFill: document.getElementById("baselineProgressFill"),
  generate2dBtn: document.getElementById("generate2dBtn"),
  manualEdit: document.getElementById("manualEdit"),
  applyManualBtn: document.getElementById("applyManualBtn"),
  recCount: document.getElementById("recCount"),
  recList: document.getElementById("recList"),
  opProgress: document.getElementById("opProgress"),
  opProgressText: document.getElementById("opProgressText"),
  cadSheetPrompt: document.getElementById("cadSheetPrompt"),
  generateCadSheetBtn: document.getElementById("generateCadSheetBtn"),
  cadSheetProgress: document.getElementById("cadSheetProgress"),
  cadSheetProgressText: document.getElementById("cadSheetProgressText"),
  cadSheetPreview: document.getElementById("cadSheetPreview"),
  generate3dPreviewBtn: document.getElementById("generate3dPreviewBtn"),
  open3dPreviewLink: document.getElementById("open3dPreviewLink"),
  preview3dProgress: document.getElementById("preview3dProgress"),
  preview3dProgressText: document.getElementById("preview3dProgressText"),
  approvedImagePreview: document.getElementById("approvedImagePreview"),
  approvalStatus: document.getElementById("approvalStatus"),
  threeDText: document.getElementById("threeDText"),
  modelViewer: document.getElementById("modelViewer"),
  indexAssetsBtn: document.getElementById("indexAssetsBtn"),
  indexStatusBox: document.getElementById("indexStatusBox"),
  uploadBriefBtn: document.getElementById("uploadBriefBtn"),
  briefFileInput: document.getElementById("briefFileInput"),
  clearSessionBtn: document.getElementById("clearSessionBtn"),
  mainPreview: document.getElementById("mainPreview"),
  previewPlaceholder: document.getElementById("previewPlaceholder"),
  thumbs: document.getElementById("thumbs"),
  refreshCatalogBtn: document.getElementById("refreshCatalogBtn"),
  catalogCount: document.getElementById("catalogCount"),
  assetCatalogList: document.getElementById("assetCatalogList"),
};
let operationInFlight = false;
let baselineLoadingInProgress = false;
let indexProgressTimer = null;
let indexProgressStartTs = 0;
const activeScreenStorageKey = `packDesignActiveScreen:${state.sessionId}`;
const storedActiveScreen = Number(sessionStorage.getItem(activeScreenStorageKey) || "1");
if ([1, 2, 3, 4].includes(storedActiveScreen)) {
  state.activeScreen = storedActiveScreen;
}

function reloadAfterImageUpdate() {
  window.location.reload();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function setBaselineLoading(isLoading) {
  baselineLoadingInProgress = isLoading;
  el.baselineProgress.hidden = !isLoading;
  if (isLoading) {
    el.baselineProgressFill.style.transition = "none";
    el.baselineProgressFill.style.width = "0%";
    void el.baselineProgressFill.offsetWidth;
    el.baselineProgressFill.style.transition = `width ${BASELINE_MIN_DELAY_MS}ms linear`;
    el.baselineProgressFill.style.width = "100%";
  } else {
    el.baselineProgressFill.style.transition = "none";
    el.baselineProgressFill.style.width = "0%";
  }
}

function nowTimeLabel() {
  const d = new Date();
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

function setIndexStatus(lines) {
  if (!el.indexStatusBox) return;
  el.indexStatusBox.value = lines.join("\n");
  el.indexStatusBox.scrollTop = el.indexStatusBox.scrollHeight;
}

function appendIndexStatus(line) {
  if (!el.indexStatusBox) return;
  const existing = el.indexStatusBox.value ? el.indexStatusBox.value.split("\n") : [];
  existing.push(`[${nowTimeLabel()}] ${line}`);
  setIndexStatus(existing);
}

function startIndexProgressTicker() {
  stopIndexProgressTicker();
  indexProgressStartTs = Date.now();
  appendIndexStatus("Indexing started...");
  appendIndexStatus("Scanning assets folder...");
  indexProgressTimer = window.setInterval(() => {
    const elapsed = Date.now() - indexProgressStartTs;
    const pct = Math.min(95, Math.max(3, Math.floor(elapsed / 180)));
    appendIndexStatus(`Indexing in progress... ${pct}%`);
  }, 900);
}

function stopIndexProgressTicker() {
  if (indexProgressTimer) {
    window.clearInterval(indexProgressTimer);
    indexProgressTimer = null;
  }
}

function canRunEditNow() {
  const s = state.session;
  if (!s) return false;
  const hasImages = Boolean(s.images && s.images.length);
  return hasImages && !s.lock_confirmed && !operationInFlight;
}

function applyActionAvailability() {
  const s = state.session;
  if (!s) return;
  const hasImages = Boolean(s.images && s.images.length);
  const canGenerate2D = s.step >= 3 && !hasImages;
  const canGenerateCadSheet = Boolean(s.approved_image_version && !operationInFlight);
  const canGenerate3D = Boolean(s.approved_image_version && !operationInFlight);

  el.generate2dBtn.disabled = operationInFlight || !canGenerate2D;
  // Keep Run Edit clickable so click handler can always provide deterministic feedback.
  el.applyManualBtn.disabled = false;
  el.applyManualBtn.classList.toggle("pseudo-disabled", !canRunEditNow());
  el.generateCadSheetBtn.disabled = !canGenerateCadSheet;
  el.generate3dPreviewBtn.disabled = !canGenerate3D;
}

function renderApprovedImage(sessionState) {
  const approvedVersion = sessionState.approved_image_version;
  if (!approvedVersion || !Array.isArray(sessionState.images)) {
    el.approvedImagePreview.hidden = true;
    return;
  }
  const match = sessionState.images.find((i) => i.version === approvedVersion);
  if (!match) {
    el.approvedImagePreview.hidden = true;
    return;
  }
  el.approvedImagePreview.src = normalizeImageSource(match.image_url_or_base64);
  el.approvedImagePreview.hidden = false;
}

function render3DViewer(previewFile) {
  if (!previewFile) {
    el.modelViewer.style.display = "none";
    el.modelViewer.removeAttribute("src");
    return;
  }
  if (previewFile.toLowerCase().endsWith(".glb")) {
    el.modelViewer.src = previewFile;
    el.modelViewer.style.display = "block";
    return;
  }
  el.modelViewer.style.display = "none";
}

function renderCadSheetPreview(src) {
  if (!src) {
    el.cadSheetPreview.hidden = true;
    el.cadSheetPreview.removeAttribute("src");
    return;
  }
  el.cadSheetPreview.src = normalizeImageSource(src);
  el.cadSheetPreview.hidden = false;
}

function addMessage(role, content) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = `${role.toUpperCase()}: ${content}`;
  el.messages.appendChild(div);
  el.messages.scrollTop = el.messages.scrollHeight;
}

function renderKeyBadge() {
  el.keyStateBadge.textContent = state.apiKey ? "Key: Set" : "Key: Not Set";
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
    const tile = document.createElement("div");
    tile.className = "thumb-card";
    tile.innerHTML = `
      <button type="button" class="thumb">
        <img src="${normalizeImageSource(img.image_url_or_base64)}" alt="v${img.version}" />
        <span>v${img.version}</span>
      </button>
      <button type="button" class="btn tiny secondary thumb-approve">Approve v${img.version}</button>
    `;
    tile.querySelector(".thumb").addEventListener("click", () => {
      state.latestImageId = img.image_id;
      state.latestImageData = normalizeImageSource(img.image_url_or_base64);
      renderMainImage(state.latestImageData);
    });
    tile.querySelector(".thumb-approve").addEventListener("click", async () => {
      await approveVersion(img);
    });
    el.thumbs.appendChild(tile);
  });
}

async function approveVersion(img) {
  state.latestImageId = img.image_id;
  state.latestImageData = normalizeImageSource(img.image_url_or_base64);
  renderMainImage(state.latestImageData);
  addMessage("system", `Approving v${img.version} for 3D conversion...`);
  const data = await apiPost("/api/version/approve", {
    session_id: state.sessionId,
    version: img.version,
  });
  addMessage("assistant", data.message);
  await refreshSession();
  setActiveScreen(3);
}

function renderBaselineMatch(match) {
  if (!match || !match.asset_rel_path) {
    el.baselineMatch.hidden = true;
    return;
  }
  el.baselineMatch.hidden = false;
  el.baselinePreview.src = `/asset-files/${encodeURIComponent(match.asset_rel_path).replace(/%2F/g, "/")}`;
  const score = Number.isFinite(match.score) ? match.score : "-";
  const typeVal = match.product_type || "-";
  const materialVal = match.material || "-";
  const closureVal = match.closure_type || "-";
  const styleVal = match.design_style || "-";
  const sizeVal = match.size_or_volume || "-";
  el.baselineSummary.textContent = `Score: ${score} | Type: ${typeVal} | Material: ${materialVal} | Closure: ${closureVal} | Style: ${styleVal} | Size/Volume: ${sizeVal}`;
}

function renderBaselineCandidates(matches, selectedRelPath) {
  el.baselineCandidates.innerHTML = "";
  if (baselineLoadingInProgress) {
    const row = document.createElement("div");
    row.className = "list-item";
    row.textContent = "Searching and scoring baseline assets...";
    el.baselineCandidates.appendChild(row);
    return;
  }
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
    const score = Number.isFinite(m.score) ? m.score : "-";
    const typeVal = m.product_type || "-";
    const materialVal = m.material || "-";
    const closureVal = m.closure_type || "-";
    const styleVal = m.design_style || "-";
    const sizeVal = m.size_or_volume || "-";
    row.innerHTML = `
      <strong>#${idx + 1}${isSelected ? " (Selected)" : ""}</strong>
      <img class="candidate-thumb" src="${previewSrc}" alt="Baseline candidate preview" />
      <div class="list-meta baseline-meta-score">Score: ${score}</div>
      <div class="list-meta baseline-meta-attrs">Type: ${typeVal} | Material: ${materialVal} | Closure: ${closureVal}</div>
      <div class="list-meta">Style: ${styleVal} | Size/Volume: ${sizeVal}</div>
    `;
    const actions = document.createElement("div");
    actions.className = "inline-actions";
    const selectBtn = document.createElement("button");
    selectBtn.type = "button";
    selectBtn.className = "btn tiny";
    selectBtn.textContent = isSelected ? "Selected" : "Select & Continue";
    selectBtn.disabled = Boolean(isSelected);
    selectBtn.addEventListener("click", async () => {
      await adoptBaselineCandidate(m);
    });
    actions.appendChild(selectBtn);
    row.appendChild(actions);
    el.baselineCandidates.appendChild(row);
  });
}

async function adoptBaselineCandidate(match) {
  try {
    await apiPost("/api/image/adopt-baseline", {
      session_id: state.sessionId,
      asset_rel_path: match.asset_rel_path,
    });
    await refreshSession();
    setActiveScreen(2);
    addMessage("system", "Baseline selected. Reloading...");
    reloadAfterImageUpdate();
  } catch (err) {
    addMessage("system", err.message);
  }
}

function setActiveScreen(screenNumber) {
  state.activeScreen = screenNumber;
  sessionStorage.setItem(activeScreenStorageKey, String(screenNumber));
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
  function cleanValue(v) {
    if (v === null || v === undefined) return "-";
    const t = String(v).trim();
    if (!t) return "-";
    return t;
  }

  el.assetCatalogList.innerHTML = "";
  el.catalogCount.textContent = `Total assets: ${items.length}`;
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "list-item";
    empty.textContent = "No indexed assets found. Click Index Asset Metadata first.";
    el.assetCatalogList.appendChild(empty);
    return;
  }
  items.forEach((item, idx) => {
    const card = document.createElement("div");
    card.className = "list-item";
    const previewSrc = `/asset-files/${encodeURIComponent(item.asset_rel_path).replace(/%2F/g, "/")}`;
    const typeVal = cleanValue(item.product_type);
    const materialVal = cleanValue(item.material);
    const closureVal = cleanValue(item.closure_type);
    const styleVal = cleanValue(item.design_style);
    const sizeVal = cleanValue(item.size_or_volume);
    const updatedVal = cleanValue(item.updated_at);

    card.innerHTML = `
      <strong>${idx + 1}</strong>
      <img class="candidate-thumb" src="${previewSrc}" alt="Asset preview" />
      <div class="list-meta">Type: ${typeVal}</div>
      <div class="list-meta">Material: ${materialVal}</div>
      <div class="list-meta">Closure: ${closureVal}</div>
      <div class="list-meta">Style: ${styleVal}</div>
      <div class="list-meta">Size/Volume: ${sizeVal}</div>
      <div class="list-meta">Updated: ${updatedVal}</div>
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

async function apiPostForm(url, formData) {
  const headers = {};
  if (state.apiKey) headers["X-Straive-Api-Key"] = state.apiKey;
  const res = await fetch(url, {
    method: "POST",
    headers,
    body: formData,
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
  applyActionAvailability();
}

function updateFromSession(s) {
  state.session = s;
  el.stepBadge.textContent = `Workflow Step: ${s.step}`;
  el.specSummary.textContent = formatSpec(s.spec);
  el.missingInfo.textContent = (s.required_questions || []).length ? `Missing info: ${(s.required_questions || []).join(" ")}` : "";

  const baselineDecision = s.baseline_decision || "Baseline decision pending.";
  el.baselineStatus.textContent = baselineDecision;
  renderBaselineCandidates(s.baseline_matches || [], s.baseline_asset?.asset_rel_path || null);
  if (baselineLoadingInProgress) {
    el.baselineMatch.hidden = true;
  } else {
    renderBaselineMatch(s.baseline_asset);
  }
  const hasBaselineMatch = Boolean((s.baseline_matches || []).length);
  el.baselineSkipBtn.hidden = !(s.step >= 3 && !s.images?.length);
  el.continueBaselineBtn.hidden = !(s.step >= 3 && !s.images?.length && hasBaselineMatch);

  renderThumbs(s.images || []);
  if (s.images && s.images.length) {
    const latest = s.images[s.images.length - 1];
    state.latestImageId = latest.image_id;
    state.latestImageData = normalizeImageSource(latest.image_url_or_base64);
    renderMainImage(state.latestImageData);
  } else {
    renderMainImage("");
  }

  applyActionAvailability();

  if (s.lock_confirmed) {
    el.approvalStatus.textContent = "A design lock state is present.";
  } else if (s.approved_image_version) {
    el.approvalStatus.textContent = `Approved version: v${s.approved_image_version}`;
  } else {
    el.approvalStatus.textContent = "No version approved yet.";
  }
  renderApprovedImage(s);
  el.cadSheetPrompt.value = s.cad_sheet_prompt || DEFAULT_CAD_SHEET_PROMPT;
  renderCadSheetPreview(s.cad_sheet_image_url_or_base64);

  el.threeDText.textContent = s.preview_3d_file
    ? `3D preview is ready from approved version v${s.approved_image_version || "-"}.`
    : "Approve a version, then run TripoSR 2D->3D conversion.";
  el.open3dPreviewLink.hidden = !s.preview_3d_file;
  if (s.preview_3d_file) {
    el.open3dPreviewLink.href = s.preview_3d_file;
  }
  render3DViewer(s.preview_3d_file);

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

async function refreshSessionWithBaselineDelay() {
  const start = Date.now();
  setBaselineLoading(true);
  await refreshSession();
  const elapsed = Date.now() - start;
  const remain = Math.max(0, BASELINE_MIN_DELAY_MS - elapsed);
  if (remain > 0) {
    await sleep(remain);
  }
  setBaselineLoading(false);
  if (state.session) {
    updateFromSession(state.session);
  }
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
  const msg = (data.assistant_message || "").trim();
  if (BASELINE_DECISION_MESSAGES.has(msg)) {
    await refreshSessionWithBaselineDelay();
  } else {
    await refreshSession();
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
  let shouldReload = false;
  try {
    const res = await apiPost("/api/image/generate", { session_id: state.sessionId, prompt });
    // Update local state immediately so Run Edit unlocks even before a full session refetch.
    if (state.session) {
      const newImage = {
        image_id: res.image_id,
        image_url_or_base64: res.image_url_or_base64,
        version: res.version,
        prompt,
      };
      const existing = Array.isArray(state.session.images) ? state.session.images : [];
      state.session.images = [...existing, newImage];
      state.session.step = 4;
      state.session.lock_confirmed = false;
      state.session.lock_question_asked = false;
      state.session.design_summary = null;
      state.session.preview_3d_file = null;
      state.session.approved_image_id = null;
      state.session.approved_image_version = null;
      state.session.approved_image_local_path = null;
      state.latestImageId = res.image_id;
      state.latestImageData = normalizeImageSource(res.image_url_or_base64);
      updateFromSession(state.session);
    }
    addMessage("system", `Generated concept image version v${res.version}.`);
    try {
      await refreshSession();
    } catch (err) {
      // Keep UI usable if sync call fails; user can still proceed with edit.
      addMessage("system", `Session refresh warning: ${err.message}`);
    }
    shouldReload = true;
  } finally {
    setOperationLoading(false);
    if (shouldReload) {
      setTimeout(() => reloadAfterImageUpdate(), 120);
    }
  }
}

async function runManualEdit() {
  if (!canRunEditNow()) {
    addMessage("system", "Run Edit is currently unavailable. Ensure an image exists and design is not locked.");
    return;
  }
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
  let shouldReload = false;
  try {
    const res = await apiPost("/api/image/edit", {
      session_id: state.sessionId,
      image_id: state.latestImageId,
      instruction_prompt: instruction,
    });
    addMessage("system", `Created iteration version v${res.version}.`);
    await refreshSession();
    shouldReload = true;
  } finally {
    setOperationLoading(false);
    if (shouldReload) {
      setTimeout(() => reloadAfterImageUpdate(), 120);
    }
  }
}

function setPreview3DLoading(isLoading, text = "Generating 3D preview...") {
  el.preview3dProgress.hidden = !isLoading;
  if (isLoading) {
    el.preview3dProgressText.textContent = text;
  }
}

function setCadSheetLoading(isLoading, text = "Generating CAD drawing sheet...") {
  el.cadSheetProgress.hidden = !isLoading;
  if (isLoading) {
    el.cadSheetProgressText.textContent = text;
  }
}

async function generateCadSheet() {
  if (!state.session?.approved_image_version) {
    addMessage("system", "Approve a version first before generating CAD drawing sheet.");
    return;
  }
  const prompt = (el.cadSheetPrompt.value || "").trim();
  if (!prompt) {
    addMessage("system", "CAD prompt cannot be empty.");
    return;
  }
  setOperationLoading(true, "Generating CAD drawing sheet...");
  setCadSheetLoading(true, "Generating CAD drawing sheet...");
  addMessage("system", "Generating CAD drawing sheet from approved image...");
  try {
    const res = await apiPost("/api/cad-sheet/generate", {
      session_id: state.sessionId,
      prompt,
    });
    addMessage("assistant", res.message);
    renderCadSheetPreview(res.image_url_or_base64);
    await refreshSession();
  } finally {
    setOperationLoading(false);
    setCadSheetLoading(false);
  }
}

async function generate3DPreview() {
  setOperationLoading(true, "Preparing 3D generation...");
  setPreview3DLoading(true, "Generating 3D preview using TripoSR...");
  addMessage("system", "Generating 3D preview from approved version...");
  try {
    const res = await apiPost("/api/preview3d/generate", { session_id: state.sessionId });
    addMessage("assistant", `${res.message}`);
    await refreshSession();
  } finally {
    setOperationLoading(false);
    setPreview3DLoading(false);
  }
}

async function indexAssetMetadata({ forceReindex = false, source = "Index Asset Metadata" } = {}) {
  el.indexAssetsBtn.disabled = true;
  startIndexProgressTicker();
  try {
    appendIndexStatus(`${source}: request sent to backend indexer.`);
    const res = await apiPost("/api/assets/index", { force_reindex: forceReindex });
    stopIndexProgressTicker();
    appendIndexStatus(`Metadata extraction completed: 100%`);
    appendIndexStatus(`Processed assets: ${res.total_assets}`);
    for (let i = 1; i <= res.total_assets; i += 1) {
      appendIndexStatus(`Processed file ${i}/${res.total_assets}`);
    }
    appendIndexStatus(`Updated in this run: ${res.indexed_count}`);
    appendIndexStatus("Indexing finished successfully.");
    addMessage("system", `Indexed ${res.indexed_count} assets out of ${res.total_assets}.`);
    await refreshSession();
    await refreshAssetCatalog();
  } catch (err) {
    stopIndexProgressTicker();
    appendIndexStatus(`Indexing failed: ${err.message}`);
    throw err;
  } finally {
    el.indexAssetsBtn.disabled = false;
  }
}

async function clearSessionState() {
  await apiPost("/api/session/clear", { session_id: state.sessionId });
  el.messages.innerHTML = "";
  el.manualEdit.value = "";
  state.latestImageId = null;
  state.latestImageData = null;
  addMessage("system", "Session cleared. Start with packaging requirements.");
  await refreshSession();
  setActiveScreen(1);
}

async function uploadMarketingBrief(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".pdf")) {
    addMessage("system", "Please select a PDF file.");
    return;
  }
  setOperationLoading(true, "Extracting design spec from marketing brief...");
  addMessage("system", `Uploading marketing brief: ${file.name}`);
  try {
    const formData = new FormData();
    formData.append("session_id", state.sessionId);
    formData.append("file", file);
    const res = await apiPostForm("/api/brief/upload", formData);
    addMessage("assistant", `${res.message}\n${res.spec_summary}`);
    if (res.required_questions && res.required_questions.length) {
      addMessage("system", `Missing info: ${res.required_questions.join(" ")}`);
    }
    await refreshSession();
  } finally {
    setOperationLoading(false);
    el.briefFileInput.value = "";
  }
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

el.generate3dPreviewBtn.addEventListener("click", async () => {
  try {
    await generate3DPreview();
  } catch (err) {
    addMessage("system", err.message);
  }
});
el.generateCadSheetBtn.addEventListener("click", async () => {
  try {
    await generateCadSheet();
  } catch (err) {
    addMessage("system", err.message);
  }
});
el.indexAssetsBtn.addEventListener("click", async () => {
  try {
    await indexAssetMetadata({ forceReindex: false, source: "Index Asset Metadata" });
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

el.uploadBriefBtn.addEventListener("click", () => {
  el.briefFileInput.click();
});

el.briefFileInput.addEventListener("change", async (e) => {
  const file = e.target.files && e.target.files[0];
  try {
    await uploadMarketingBrief(file);
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

el.continueBaselineBtn.addEventListener("click", async () => {
  const matches = state.session?.baseline_matches || [];
  if (!matches.length) {
    addMessage("system", "No baseline matches are available yet.");
    return;
  }
  const selectedPath = state.session?.baseline_asset?.asset_rel_path || matches[0].asset_rel_path;
  const selectedMatch = matches.find((m) => m.asset_rel_path === selectedPath) || matches[0];
  await adoptBaselineCandidate(selectedMatch);
});

el.refreshCatalogBtn.addEventListener("click", async () => {
  try {
    await indexAssetMetadata({ forceReindex: true, source: "Refresh Catalog" });
    await refreshAssetCatalog();
  } catch (err) {
    addMessage("system", err.message);
  }
});

(async function init() {
  el.keyModal.hidden = true;
  el.apiKeyPopupInput.value = state.apiKey;
  renderKeyBadge();
  addMessage("system", "Session initialized. Start with packaging requirements.");
  try {
    await refreshSession();
    await refreshAssetCatalog();
  } catch (err) {
    addMessage("system", "Unable to restore previous session state.");
  }
})();

el.openKeyModalBtn.addEventListener("click", () => {
  el.apiKeyPopupInput.value = state.apiKey;
  el.keyModal.hidden = false;
});

el.closeKeyModalBtn.addEventListener("click", () => {
  el.keyModal.hidden = true;
});

el.keyModal.addEventListener("click", (e) => {
  if (e.target === el.keyModal) {
    el.keyModal.hidden = true;
  }
});

el.saveKeyPopupBtn.addEventListener("click", async () => {
  state.apiKey = el.apiKeyPopupInput.value.trim();
  const scopedKeyStorageId = `straiveUserApiKey:${state.sessionId}`;
  if (state.apiKey) {
    localStorage.setItem(scopedKeyStorageId, state.apiKey);
  } else {
    localStorage.removeItem(scopedKeyStorageId);
  }
  renderKeyBadge();
  el.keyModal.hidden = true;
  addMessage("system", state.apiKey ? "User API key saved for this browser." : "No key entered.");
});

el.clearKeyPopupBtn.addEventListener("click", async () => {
  state.apiKey = "";
  const scopedKeyStorageId = `straiveUserApiKey:${state.sessionId}`;
  localStorage.removeItem(scopedKeyStorageId);
  el.apiKeyPopupInput.value = "";
  renderKeyBadge();
  el.keyModal.hidden = true;
  addMessage("system", "User API key cleared.");
});
