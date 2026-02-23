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
  "You are generating a technical mechanical CAD drawing sheet.\n\nUse the provided product image as geometry reference only.\nDo NOT recreate the photo.\nConvert the object into a formal engineering drawing sheet.\n\nSHEET FORMAT (STRICT):\nA3 landscape (420mm × 297mm)\nAspect ratio locked\n20mm outer border\nWhite background\nBlack thin drafting lines only\nEntire sheet must be fully visible\nOrthographic straight camera\nNo perspective\nNo zoom\nNo cropping\n\nLAYOUT (DO NOT CHANGE):\n\nTop Row:\nLeft: Front View\nCenter: Right Side View\nRight: Exploded View\n\nBottom Row:\nLeft: Top View\nCenter: Section A-A (vertical center cut)\nRight: Isometric View\n\nViews must stay inside their grid areas.\nNo overlapping.\nNo dynamic repositioning.\n\nENGINEERING DETAILS:\n• Centerlines\n• Hidden lines\n• Dimension lines with arrowheads\n• Units in millimeters\n• Wall thickness callouts if hollow\n• Thread representation if applicable\n• Material labels inferred from image\n• Standard tolerance ±0.1 mm\n• Third-angle projection symbol\n• Title block bottom-right\n• Scale 1:1\n\nIMPORTANT:\nLayout must remain fixed.\nOnly geometry changes per object.\nThe entire A3 sheet must be visible inside the image frame.\nThe entire sheet must be rendered as a fully visible flat document, centered in the frame with clear white space surrounding all four edges. Absolutely no cropping, zooming, clipping, edge-touching, or partial cutoff is permitted — the full outer border, title block, and all margins must remain completely visible inside the image boundaries.";
const DEFAULT_STEP_CAD_PROMPT =
  "You are a senior mechanical CAD engineer and geometric reconstruction specialist.\n\nYour task is to analyze the provided product image and generate a fully parametric, manufacturable 3D CAD model exported as a STEP (.stp / .step) file.\n\nCRITICAL RULES:\n- Do NOT recreate the image.\n- Convert visible geometry into engineering solids.\n- No mesh or STL triangulation.\n- Only closed BREP solids.\n- Real-world manufacturable geometry only.\n\nSTEP 1 — GEOMETRY ANALYSIS\n- Identify object type\n- Detect symmetry (axial / planar / none)\n- Identify primitives (cylinder, cone, revolve, loft, extrude)\n- Detect grooves, ribs, fillets, chamfers\n- Detect hollow areas\n- Detect threads if present\n- Detect assembly parts\n- Infer realistic industrial dimensions if scale is unknown\n\nSTEP 2 — PARAMETRIC MODEL CREATION\nCreate parametric variables for overall height, outer diameter/width, wall thickness, groove depth, fillet radius, chamfer size, thread pitch.\nAll units in mm. Tolerance ±0.1 mm.\n\nSTEP 3 — ADVANCED FEATURES\nIf grooves visible, model using revolved cuts/sweeps.\nIf threads visible, use helical thread with clearance.\nIf hollow, maintain minimum wall thickness 2 mm.\nIf multipart, create separate solids.\n\nSTEP 4 — VALIDATION\nEnsure closed solids, no non-manifold edges, manufacturable wall thickness.\n\nSTEP 5 — OUTPUT\nReturn only executable CadQuery Python script that exports a STEP file.";
const STEP_PROMPT_STORAGE_KEY = "stepCadPromptGlobal";
const INTEL_DATA = {
  cost: {
    estimatedUnit: 8.4,
    target: 7.0,
    moq: 25000,
    breakdown: [
      { label: "Material", value: 4.1, pct: 48 },
      { label: "Manufacturing", value: 2.8, pct: 33 },
      { label: "Closure", value: 1.2, pct: 14 },
      { label: "Margin Buffer", value: 0.3, pct: 5 },
    ],
    recommendations: [
      {
        title: "Standardize neck finish tolerance stack",
        savingsPct: "4.2%",
        risk: "Low",
        projectedCost: "$8.05",
      },
      {
        title: "Shift cap resin to high-flow PP copolymer",
        savingsPct: "6.0%",
        risk: "Medium",
        projectedCost: "$7.89",
      },
      {
        title: "Consolidate two molding operations to one tool family",
        savingsPct: "7.8%",
        risk: "Medium",
        projectedCost: "$7.74",
      },
      {
        title: "Optimize wall thickness by ribbing and draft correction",
        savingsPct: "5.4%",
        risk: "Low",
        projectedCost: "$7.95",
      },
      {
        title: "Move to regional secondary supplier for closure insert",
        savingsPct: "3.1%",
        risk: "Low",
        projectedCost: "$8.14",
      },
      {
        title: "Batch decoration with inline QA sampling",
        savingsPct: "2.7%",
        risk: "Low",
        projectedCost: "$8.18",
      },
    ],
  },
  sentiment: {
    reviews: [
      "Premium finish appreciated, but closure feels tight.",
      "Customers request refillable options.",
      "Luxury positioning well received among metro buyers.",
    ],
    social: [
      "⬆ Rising interest in sustainable packaging",
      "⬆ Demand for minimalist aesthetic",
      "⬆ Increasing price sensitivity in mid-tier segment",
      "⬇ Declining preference for heavy glass in travel formats",
    ],
    cloud: ["sustainable", "minimal", "refillable", "premium", "lightweight", "cost", "ergonomic", "shelf-impact"],
  },
};
localStorage.setItem("packDesignSession", state.sessionId);
state.apiKey = localStorage.getItem(`straiveUserApiKey:${state.sessionId}`) || "";

const el = {
  stepBadge: document.getElementById("stepBadge"),
  tab1: document.getElementById("tab1"),
  tab2: document.getElementById("tab2"),
  tab3: document.getElementById("tab3"),
  tab4: document.getElementById("tab4"),
  tab5: document.getElementById("tab5"),
  openKeyModalBtn: document.getElementById("openKeyModalBtn"),
  intelligenceHubBtn: document.getElementById("intelligenceHubBtn"),
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
  screen5: document.getElementById("screen5"),
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
  cadApprovalStatus: document.getElementById("cadApprovalStatus"),
  cadApprovedImagePreview: document.getElementById("cadApprovedImagePreview"),
  approveCurrentForCadBtn: document.getElementById("approveCurrentForCadBtn"),
  cadSheetPrompt: document.getElementById("cadSheetPrompt"),
  openCadPromptModalBtn: document.getElementById("openCadPromptModalBtn"),
  cadPromptModal: document.getElementById("cadPromptModal"),
  specTargetVolume: document.getElementById("specTargetVolume"),
  specOverallHeight: document.getElementById("specOverallHeight"),
  specOuterDiameter: document.getElementById("specOuterDiameter"),
  specOuterWidth: document.getElementById("specOuterWidth"),
  specOuterDepth: document.getElementById("specOuterDepth"),
  specWallThickness: document.getElementById("specWallThickness"),
  specBaseThickness: document.getElementById("specBaseThickness"),
  saveCadPromptModalBtn: document.getElementById("saveCadPromptModalBtn"),
  closeCadPromptModalBtn: document.getElementById("closeCadPromptModalBtn"),
  generateCadSheetBtn: document.getElementById("generateCadSheetBtn"),
  proceedTo3dBtn: document.getElementById("proceedTo3dBtn"),
  downloadCadSheetBtn: document.getElementById("downloadCadSheetBtn"),
  cadSheetProgress: document.getElementById("cadSheetProgress"),
  cadSheetProgressText: document.getElementById("cadSheetProgressText"),
  cadSheetPreview: document.getElementById("cadSheetPreview"),
  cadSheetPlaceholder: document.getElementById("cadSheetPlaceholder"),
  generateStepCadBtn: document.getElementById("generateStepCadBtn"),
  stopStepCadBtn: document.getElementById("stopStepCadBtn"),
  downloadCadCodeBtn: document.getElementById("downloadCadCodeBtn"),
  downloadStepBtn: document.getElementById("downloadStepBtn"),
  cadAttemptDetails: document.getElementById("cadAttemptDetails"),
  stepCadAttemptText: document.getElementById("stepCadAttemptText"),
  stepCadAttemptPills: document.getElementById("stepCadAttemptPills"),
  stepCadUnresolvedBanner: document.getElementById("stepCadUnresolvedBanner"),
  cadErrorText: document.getElementById("cadErrorText"),
  copyCadErrorBtn: document.getElementById("copyCadErrorBtn"),
  toggleCadCodeBtn: document.getElementById("toggleCadCodeBtn"),
  cadCodeWrap: document.getElementById("cadCodeWrap"),
  fixCadCodeTextarea: document.getElementById("fixCadCodeTextarea"),
  stepCadProgress: document.getElementById("stepCadProgress"),
  stepCadProgressText: document.getElementById("stepCadProgressText"),
  stepViewerFrame: document.getElementById("stepViewerFrame"),
  stepFileBrowseInput: document.getElementById("stepFileBrowseInput"),
  openStepPromptModalBtn: document.getElementById("openStepPromptModalBtn"),
  stepPromptModal: document.getElementById("stepPromptModal"),
  stepPromptTextarea: document.getElementById("stepPromptTextarea"),
  saveStepPromptBtn: document.getElementById("saveStepPromptBtn"),
  clearStepPromptBtn: document.getElementById("clearStepPromptBtn"),
  closeStepPromptBtn: document.getElementById("closeStepPromptBtn"),
  approvedImagePreview: document.getElementById("approvedImagePreview"),
  approvalStatus: document.getElementById("approvalStatus"),
  threeDText: document.getElementById("threeDText"),
  indexAssetsBtn: document.getElementById("indexAssetsBtn"),
  indexStatusBox: document.getElementById("indexStatusBox"),
  uploadBriefBtn: document.getElementById("uploadBriefBtn"),
  briefFileInput: document.getElementById("briefFileInput"),
  clearCacheBtn: document.getElementById("clearCacheBtn"),
  clearSessionBtn: document.getElementById("clearSessionBtn"),
  mainPreview: document.getElementById("mainPreview"),
  previewPlaceholder: document.getElementById("previewPlaceholder"),
  thumbs: document.getElementById("thumbs"),
  refreshCatalogBtn: document.getElementById("refreshCatalogBtn"),
  catalogCount: document.getElementById("catalogCount"),
  assetCatalogList: document.getElementById("assetCatalogList"),
  intelligenceHubPage: document.getElementById("intelligenceHubPage"),
  runIntelBtn: document.getElementById("runIntelBtn"),
  closeIntelBtn: document.getElementById("closeIntelBtn"),
  intelLoading: document.getElementById("intelLoading"),
  intelContent: document.getElementById("intelContent"),
  costEstimatedUnit: document.getElementById("costEstimatedUnit"),
  costTarget: document.getElementById("costTarget"),
  costGap: document.getElementById("costGap"),
  costMoq: document.getElementById("costMoq"),
  costBreakdownGrid: document.getElementById("costBreakdownGrid"),
  costRecommendations: document.getElementById("costRecommendations"),
  mockReviews: document.getElementById("mockReviews"),
  socialInsights: document.getElementById("socialInsights"),
  wordCloud: document.getElementById("wordCloud"),
};
let operationInFlight = false;
let baselineLoadingInProgress = false;
let indexProgressTimer = null;
let indexProgressStartTs = 0;
let intelGenerated = false;
let currentStepCadPrompt = "";
let cadAttemptStates = Array.from({ length: 10 }, () => ({
  status: "inactive",
  errorText: "",
  fullError: "",
  codeText: "",
}));
let stepCadLoopStopRequested = false;
let stepCadLoopRunning = false;
const cadSpecState = {
  target_volume_ml: "",
  Soverall_height_mm: "",
  outer_diameter_mm: "",
  outer_width_mm: "",
  outer_depth_mm: "",
  wall_thickness_mm: "",
  base_thickness_mm: "",
};
const activeScreenStorageKey = `packDesignActiveScreen:${state.sessionId}`;
const storedActiveScreen = Number(sessionStorage.getItem(activeScreenStorageKey) || "1");
if ([1, 2, 3, 4, 5].includes(storedActiveScreen)) {
  state.activeScreen = storedActiveScreen;
}

function reloadAfterImageUpdate() {
  window.location.reload();
}

function renderIntelHubData() {
  const gap = (INTEL_DATA.cost.estimatedUnit - INTEL_DATA.cost.target).toFixed(2);
  const gapPositive = Number(gap) > 0;
  el.costEstimatedUnit.textContent = `$${INTEL_DATA.cost.estimatedUnit.toFixed(2)}`;
  el.costTarget.textContent = `$${INTEL_DATA.cost.target.toFixed(2)}`;
  el.costGap.innerHTML = `<span class="${gapPositive ? "kpi-bad" : "kpi-good"}">${gapPositive ? "+" : ""}$${gap}</span>`;
  el.costMoq.textContent = `${INTEL_DATA.cost.moq.toLocaleString()} units`;

  el.costBreakdownGrid.innerHTML = INTEL_DATA.cost.breakdown
    .map((i) => `<div class="hub-kpi"><h4>${i.label}</h4><strong>$${i.value.toFixed(2)} (${i.pct}%)</strong></div>`)
    .join("");
  el.costRecommendations.innerHTML = INTEL_DATA.cost.recommendations
    .map(
      (r) => `<div class="rec-card">
        <h5>${r.title}</h5>
        <div class="rec-meta">Estimated Savings: ${r.savingsPct}</div>
        <div class="rec-meta">Risk Level: ${r.risk}</div>
        <div class="rec-meta">Projected New Cost: ${r.projectedCost}</div>
        <button class="btn tiny">Apply</button>
      </div>`,
    )
    .join("");
  el.mockReviews.innerHTML = INTEL_DATA.sentiment.reviews.map((r) => `<li>${r}</li>`).join("");
  el.socialInsights.innerHTML = INTEL_DATA.sentiment.social.map((r) => `<li>${r}</li>`).join("");
  el.wordCloud.innerHTML = INTEL_DATA.sentiment.cloud
    .map((w, idx) => `<span class="word-chip" style="font-size:${0.78 + (idx % 4) * 0.08}rem">${w}</span>`)
    .join("");
}

function getSavedStepCadPrompt() {
  const saved = localStorage.getItem(STEP_PROMPT_STORAGE_KEY) || "";
  return saved.trim() || DEFAULT_STEP_CAD_PROMPT;
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

function canGenerateStepCadNow() {
  const s = state.session;
  if (!s) return false;
  return Boolean(s.approved_image_version) && !operationInFlight && !stepCadLoopRunning;
}

function applyActionAvailability() {
  const s = state.session;
  if (!s) return;
  const hasImages = Boolean(s.images && s.images.length);
  const canApproveCurrent = hasImages && !operationInFlight;
  const canGenerate2D = s.step >= 3 && !hasImages;
  const canGenerateCadSheet = Boolean(s.approved_image_version && !operationInFlight);
  const canProceedTo3D = Boolean(s.cad_sheet_image_url_or_base64);

  el.generate2dBtn.disabled = operationInFlight || !canGenerate2D;
  // Keep Run Edit clickable so click handler can always provide deterministic feedback.
  el.applyManualBtn.disabled = false;
  el.applyManualBtn.classList.toggle("pseudo-disabled", !canRunEditNow());
  el.approveCurrentForCadBtn.disabled = !canApproveCurrent;
  el.generateCadSheetBtn.disabled = !canGenerateCadSheet;
  el.proceedTo3dBtn.disabled = !canProceedTo3D;
  // Keep Generate STEP CAD clickable so click handler can provide deterministic feedback.
  el.generateStepCadBtn.disabled = false;
  el.generateStepCadBtn.classList.toggle("pseudo-disabled", !canGenerateStepCadNow());
}

function renderApprovedImage(sessionState) {
  const approvedVersion = sessionState.approved_image_version;
  if (!approvedVersion || !Array.isArray(sessionState.images)) {
    el.approvedImagePreview.hidden = true;
    el.cadApprovedImagePreview.hidden = true;
    return;
  }
  const match = sessionState.images.find((i) => i.version === approvedVersion);
  if (!match) {
    el.approvedImagePreview.hidden = true;
    el.cadApprovedImagePreview.hidden = true;
    return;
  }
  const src = normalizeImageSource(match.image_url_or_base64);
  el.approvedImagePreview.src = src;
  el.cadApprovedImagePreview.src = src;
  el.approvedImagePreview.hidden = false;
  el.cadApprovedImagePreview.hidden = false;
}

function renderStepViewer(stepFile) {
  if (!stepFile) {
    el.stepViewerFrame.hidden = true;
    el.downloadStepBtn.hidden = true;
    el.downloadCadCodeBtn.hidden = true;
    el.downloadStepBtn.removeAttribute("href");
    el.downloadCadCodeBtn.removeAttribute("href");
    return;
  }
  el.stepViewerFrame.hidden = false;
  el.downloadStepBtn.hidden = false;
  el.downloadStepBtn.href = stepFile;
  // Ensure iframe receives load command once it is ready.
  const msg = { type: "load-step", url: stepFile };
  try {
    el.stepViewerFrame.contentWindow?.postMessage(msg, "*");
  } catch (err) {
    // no-op; onload handler below will retry
  }
  el.stepViewerFrame.onload = () => {
    el.stepViewerFrame.contentWindow?.postMessage(msg, "*");
  };
}

function errorSummary(text) {
  const t = String(text || "").trim();
  if (!t) return "";
  return t.split("\n")[0].slice(0, 140);
}

function renderAttemptPills() {
  el.stepCadAttemptPills.innerHTML = "";
  cadAttemptStates.forEach((attempt, idx) => {
    const pill = document.createElement("div");
    pill.className = `attempt-pill ${attempt.status}`;
    pill.textContent = String(idx + 1);
    if (attempt.status === "success") {
      pill.title = "Success";
    } else if (attempt.status === "failed") {
      pill.title = errorSummary(attempt.errorText || attempt.fullError || "Failed");
    } else if (attempt.status === "running") {
      pill.title = "Running";
    } else if (attempt.status === "cancelled") {
      pill.title = "Cancelled";
    } else {
      pill.title = "Inactive";
    }
    el.stepCadAttemptPills.appendChild(pill);
  });
}

function resetCadAttemptsUi() {
  cadAttemptStates = Array.from({ length: 10 }, () => ({
    status: "inactive",
    errorText: "",
    fullError: "",
    codeText: "",
  }));
  el.stepCadAttemptText.textContent = "Attempt 0 of 10";
  el.stepCadUnresolvedBanner.hidden = true;
  renderAttemptPills();
}

function updateAttemptStatus(index, patch) {
  if (index < 0 || index >= cadAttemptStates.length) return;
  cadAttemptStates[index] = { ...cadAttemptStates[index], ...patch };
  renderAttemptPills();
}

function renderCadExecutionIssue(errorText, cadCode) {
  el.cadAttemptDetails.hidden = false;
  el.cadAttemptDetails.open = true;
  el.cadErrorText.value = (errorText || "").trim();
  el.fixCadCodeTextarea.value = cadCode || "";
  el.cadCodeWrap.hidden = true;
  el.toggleCadCodeBtn.textContent = "Show Code";
}

function hideCadExecutionIssue() {
  el.cadAttemptDetails.hidden = true;
  el.cadAttemptDetails.open = false;
  el.cadErrorText.value = "";
  el.fixCadCodeTextarea.value = "";
}

function renderCadSheetPreview(src) {
  if (!src) {
    el.cadSheetPreview.hidden = true;
    el.cadSheetPreview.style.display = "none";
    el.cadSheetPreview.onload = null;
    el.cadSheetPreview.removeAttribute("src");
    el.cadSheetPlaceholder.hidden = false;
    el.cadSheetPlaceholder.style.display = "";
    el.downloadCadSheetBtn.hidden = true;
    el.downloadCadSheetBtn.removeAttribute("href");
    return;
  }
  const normalized = normalizeImageSource(src);
  el.cadSheetPreview.onload = () => {
    el.cadSheetPreview.hidden = false;
    el.cadSheetPreview.style.display = "block";
    // Ensure placeholder occupies no space after successful image render.
    el.cadSheetPlaceholder.hidden = true;
    el.cadSheetPlaceholder.style.display = "none";
  };
  el.cadSheetPreview.src = normalized;
  el.downloadCadSheetBtn.href = normalized;
  el.downloadCadSheetBtn.hidden = false;
}

function buildCadPromptFromSpec(spec) {
  const provided = Object.entries(spec).filter(([, v]) => String(v || "").trim() !== "");
  if (!provided.length) return DEFAULT_CAD_SHEET_PROMPT;
  const lines = provided.map(([k, v]) => `"${k}": "${String(v).trim()}"`);
  return `${DEFAULT_CAD_SHEET_PROMPT}\n\nUse these provided engineering inputs if applicable; if not provided, infer from image:\n${lines.join("\n")}`;
}

function syncCadSpecFormFromState() {
  el.specTargetVolume.value = cadSpecState.target_volume_ml || "";
  el.specOverallHeight.value = cadSpecState.Soverall_height_mm || "";
  el.specOuterDiameter.value = cadSpecState.outer_diameter_mm || "";
  el.specOuterWidth.value = cadSpecState.outer_width_mm || "";
  el.specOuterDepth.value = cadSpecState.outer_depth_mm || "";
  el.specWallThickness.value = cadSpecState.wall_thickness_mm || "";
  el.specBaseThickness.value = cadSpecState.base_thickness_mm || "";
}

function captureCadSpecFormToState() {
  cadSpecState.target_volume_ml = (el.specTargetVolume.value || "").trim();
  cadSpecState.Soverall_height_mm = (el.specOverallHeight.value || "").trim();
  cadSpecState.outer_diameter_mm = (el.specOuterDiameter.value || "").trim();
  cadSpecState.outer_width_mm = (el.specOuterWidth.value || "").trim();
  cadSpecState.outer_depth_mm = (el.specOuterDepth.value || "").trim();
  cadSpecState.wall_thickness_mm = (el.specWallThickness.value || "").trim();
  cadSpecState.base_thickness_mm = (el.specBaseThickness.value || "").trim();
  el.cadSheetPrompt.value = buildCadPromptFromSpec(cadSpecState);
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

async function approveCurrentForCad() {
  const images = state.session?.images || [];
  if (!images.length) {
    addMessage("system", "No image available to approve.");
    return;
  }
  const latest = images[images.length - 1];
  await approveVersion(latest);
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
  [el.tab1, el.tab2, el.tab3, el.tab4, el.tab5].forEach((tab, i) => tab.classList.toggle("active", i + 1 === screenNumber));
  [el.screen1, el.screen2, el.screen3, el.screen4, el.screen5].forEach((screen, i) => screen.classList.toggle("active", i + 1 === screenNumber));
}

function computeAllowedScreen(step, hasBaselineMatch = false, hasImages = false, hasApproved = false) {
  if (step === 3 && hasBaselineMatch) return 2;
  if (step <= 3) return 1;
  if (!hasImages) return 2;
  if (!hasApproved) return 3;
  return 4;
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
  const hasImages = Boolean(s.images && s.images.length);
  const hasApproved = Boolean(s.approved_image_version);
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
    el.cadApprovalStatus.textContent = `Approved version: v${s.approved_image_version}`;
  } else {
    el.approvalStatus.textContent = "No version approved yet.";
    el.cadApprovalStatus.textContent = "No approved version yet.";
  }
  renderApprovedImage(s);
  el.cadSheetPrompt.value = buildCadPromptFromSpec(cadSpecState);
  renderCadSheetPreview(s.cad_sheet_image_url_or_base64);

  if (s.cad_model_code_path) {
    el.downloadCadCodeBtn.href = s.cad_model_code_path;
    el.downloadCadCodeBtn.hidden = false;
  } else {
    el.downloadCadCodeBtn.hidden = true;
    el.downloadCadCodeBtn.removeAttribute("href");
  }
  if (s.cad_step_file) {
    el.downloadStepBtn.href = s.cad_step_file;
    el.downloadStepBtn.hidden = false;
    hideCadExecutionIssue();
  } else {
    el.downloadStepBtn.hidden = true;
    el.downloadStepBtn.removeAttribute("href");
    if (s.cad_model_last_error || s.cad_model_code) {
      renderCadExecutionIssue(s.cad_model_last_error || "", s.cad_model_code || "");
    } else {
      hideCadExecutionIssue();
    }
  }
  if (s.cad_model_prompt && !localStorage.getItem(STEP_PROMPT_STORAGE_KEY)) {
    currentStepCadPrompt = s.cad_model_prompt;
  }
  renderStepViewer(s.cad_step_file);

  el.threeDText.textContent = s.cad_step_file
    ? `STEP model is ready from approved version v${s.approved_image_version || "-"}.`
    : "Approve a version, then generate STEP CAD.";

  const allowed = computeAllowedScreen(s.step, hasBaselineMatch, hasImages, hasApproved);
  el.tab2.disabled = allowed < 2;
  el.tab3.disabled = allowed < 3;
  el.tab4.disabled = allowed < 4;
  el.tab5.disabled = false;
  const nextScreen = state.activeScreen === 5 ? 5 : Math.min(state.activeScreen, allowed);
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

function setStepCadLoading(isLoading, text = "Generating CAD code and STEP file...") {
  el.stepCadProgress.hidden = !isLoading;
  if (isLoading) {
    el.stepCadProgressText.textContent = text;
  }
}

function setCadSheetLoading(isLoading, text = "Generating CAD drawing sheet...") {
  el.cadSheetProgress.hidden = !isLoading;
  if (isLoading) {
    el.cadSheetProgressText.textContent = text;
  }
}

async function generateStepCad() {
  if (!canGenerateStepCadNow()) {
    if (!state.session?.approved_image_version) {
      addMessage("system", "Approve a version first before generating STEP CAD.");
    } else if (operationInFlight) {
      addMessage("system", "Another operation is running. Please wait.");
    } else {
      addMessage("system", "STEP CAD generation is not available yet.");
    }
    return;
  }
  const prompt = (currentStepCadPrompt || "").trim();
  if (!prompt) {
    addMessage("system", "CAD Query prompt cannot be empty.");
    return;
  }
  let currentCode = "";
  let currentError = "";
  let success = false;
  stepCadLoopStopRequested = false;
  stepCadLoopRunning = true;
  el.stopStepCadBtn.hidden = false;
  setOperationLoading(true, "Running STEP CAD attempts...");
  setStepCadLoading(true, "Attempt 1 of 10...");
  resetCadAttemptsUi();
  el.downloadStepBtn.hidden = true;
  el.downloadStepBtn.removeAttribute("href");
  addMessage("system", "Starting STEP CAD auto-fix attempts (max 10).");

  try {
    for (let i = 0; i < 10; i += 1) {
      if (stepCadLoopStopRequested) {
        updateAttemptStatus(i, { status: "cancelled" });
        el.stepCadAttemptText.textContent = `Attempt ${i + 1} of 10 (Cancelled)`;
        addMessage("system", "STEP CAD attempt loop cancelled.");
        break;
      }
      el.stepCadAttemptText.textContent = `Attempt ${i + 1} of 10`;
      setStepCadLoading(true, `Attempt ${i + 1} of 10...`);
      updateAttemptStatus(i, { status: "running", errorText: "", fullError: "", codeText: "" });

      let res;
      if (i === 0) {
        res = await apiPost("/api/cad/model/generate", {
          session_id: state.sessionId,
          prompt,
        });
      } else {
        res = await apiPost("/api/cad/model/fix-code", {
          session_id: state.sessionId,
          cad_code: currentCode,
          error_detail: currentError,
          prompt,
        });
      }

      if (res.success && res.step_file) {
        success = true;
        el.stepCadAttemptText.textContent = `Attempt ${i + 1} of 10 (Success)`;
        updateAttemptStatus(i, { status: "success", errorText: "Success", fullError: "", codeText: res.cad_code || "" });
        addMessage("assistant", `${res.message}${res.cached ? " (cache hit)" : ""}`);
        el.downloadCadCodeBtn.href = res.code_file;
        el.downloadCadCodeBtn.hidden = false;
        el.downloadStepBtn.href = res.step_file;
        el.downloadStepBtn.hidden = false;
        renderStepViewer(res.step_file);
        hideCadExecutionIssue();
        break;
      }

      currentCode = (res.cad_code || currentCode || "").trim();
      currentError = (res.error_detail || "CAD execution failed.").trim();
      updateAttemptStatus(i, {
        status: "failed",
        errorText: errorSummary(currentError),
        fullError: currentError,
        codeText: currentCode,
      });
      renderCadExecutionIssue(currentError, currentCode);
    }

    if (!success && !stepCadLoopStopRequested) {
      el.stepCadUnresolvedBanner.hidden = false;
      addMessage("system", "Unresolved after 10 attempts.");
      el.downloadStepBtn.hidden = true;
      el.downloadStepBtn.removeAttribute("href");
    }

    await refreshSession();
  } finally {
    stepCadLoopRunning = false;
    el.stopStepCadBtn.hidden = true;
    setOperationLoading(false);
    setStepCadLoading(false);
    applyActionAvailability();
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

async function clearServerCache() {
  const res = await apiPost("/api/cache/clear", {});
  addMessage("system", `${res.message} Removed entries: ${res.removed_files}.`);
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

el.generateStepCadBtn.addEventListener("click", async () => {
  try {
    await generateStepCad();
  } catch (err) {
    addMessage("system", err.message);
  }
});
el.stopStepCadBtn.addEventListener("click", () => {
  if (!stepCadLoopRunning) return;
  stepCadLoopStopRequested = true;
  addMessage("system", "Stopping after current attempt...");
});
el.copyCadErrorBtn.addEventListener("click", async () => {
  const txt = (el.cadErrorText.value || "").trim();
  if (!txt) {
    addMessage("system", "No error text to copy.");
    return;
  }
  try {
    await navigator.clipboard.writeText(txt);
    addMessage("system", "CAD error copied to clipboard.");
  } catch (err) {
    addMessage("system", "Unable to copy error text.");
  }
});
el.toggleCadCodeBtn.addEventListener("click", () => {
  const willShow = el.cadCodeWrap.hidden;
  el.cadCodeWrap.hidden = !willShow;
  el.toggleCadCodeBtn.textContent = willShow ? "Hide Code" : "Show Code";
});
el.stepFileBrowseInput.addEventListener("change", (e) => {
  const file = e.target.files && e.target.files[0];
  if (!file) return;
  const name = (file.name || "").toLowerCase();
  if (!(name.endsWith(".step") || name.endsWith(".stp"))) {
    addMessage("system", "Please select a .step or .stp file.");
    el.stepFileBrowseInput.value = "";
    return;
  }
  const blobUrl = URL.createObjectURL(file);
  renderStepViewer(blobUrl);
  el.threeDText.textContent = `Loaded local STEP file: ${file.name}`;
});
el.generateCadSheetBtn.addEventListener("click", async () => {
  try {
    await generateCadSheet();
  } catch (err) {
    addMessage("system", err.message);
  }
});
el.proceedTo3dBtn.addEventListener("click", () => {
  if (el.proceedTo3dBtn.disabled) {
    addMessage("system", "Generate CAD drawing sheet first, then proceed to 3D.");
    return;
  }
  setActiveScreen(4);
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

el.clearCacheBtn.addEventListener("click", async () => {
  try {
    await clearServerCache();
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
  if (el.tab4.disabled) return;
  setActiveScreen(4);
});
el.tab5.addEventListener("click", async () => {
  setActiveScreen(5);
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

el.approveCurrentForCadBtn.addEventListener("click", async () => {
  try {
    await approveCurrentForCad();
  } catch (err) {
    addMessage("system", err.message);
  }
});

el.openCadPromptModalBtn.addEventListener("click", () => {
  syncCadSpecFormFromState();
  el.cadPromptModal.hidden = false;
});

el.saveCadPromptModalBtn.addEventListener("click", () => {
  captureCadSpecFormToState();
  el.cadPromptModal.hidden = true;
  addMessage("system", "CAD spec updated.");
});

el.closeCadPromptModalBtn.addEventListener("click", () => {
  el.cadPromptModal.hidden = true;
});

el.cadPromptModal.addEventListener("click", (e) => {
  if (e.target === el.cadPromptModal) {
    el.cadPromptModal.hidden = true;
  }
});

el.intelligenceHubBtn.addEventListener("click", () => {
  el.intelligenceHubPage.hidden = false;
});

el.closeIntelBtn.addEventListener("click", () => {
  el.intelligenceHubPage.hidden = true;
});

el.runIntelBtn.addEventListener("click", async () => {
  el.runIntelBtn.disabled = true;
  el.intelContent.hidden = true;
  el.intelLoading.hidden = false;
  await sleep(2000);
  renderIntelHubData();
  el.intelLoading.hidden = true;
  el.intelContent.hidden = false;
  intelGenerated = true;
  el.runIntelBtn.disabled = false;
});

document.querySelectorAll(".hub-module-head").forEach((btn) => {
  btn.addEventListener("click", () => {
    const section = btn.closest(".hub-module");
    if (!section) return;
    section.classList.toggle("collapsed");
    const toggle = btn.querySelector(".hub-toggle");
    if (toggle) toggle.textContent = section.classList.contains("collapsed") ? "Expand" : "Collapse";
  });
});

(async function init() {
  el.keyModal.hidden = true;
  el.intelligenceHubPage.hidden = true;
  resetCadAttemptsUi();
  hideCadExecutionIssue();
  currentStepCadPrompt = getSavedStepCadPrompt();
  if (el.stepPromptTextarea) {
    el.stepPromptTextarea.value = currentStepCadPrompt;
  }
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

el.openStepPromptModalBtn.addEventListener("click", () => {
  el.stepPromptTextarea.value = currentStepCadPrompt || getSavedStepCadPrompt();
  el.stepPromptModal.hidden = false;
});

el.saveStepPromptBtn.addEventListener("click", () => {
  const next = (el.stepPromptTextarea.value || "").trim();
  if (!next) {
    addMessage("system", "Prompt is empty. Use Clear Prompt to reset or enter text.");
    return;
  }
  currentStepCadPrompt = next;
  localStorage.setItem(STEP_PROMPT_STORAGE_KEY, next);
  el.stepPromptModal.hidden = true;
  addMessage("system", "CAD prompt saved. It will be reused in next sessions.");
});

el.clearStepPromptBtn.addEventListener("click", () => {
  localStorage.removeItem(STEP_PROMPT_STORAGE_KEY);
  currentStepCadPrompt = DEFAULT_STEP_CAD_PROMPT;
  el.stepPromptTextarea.value = currentStepCadPrompt;
  addMessage("system", "CAD prompt reset to default.");
});

el.closeStepPromptBtn.addEventListener("click", () => {
  el.stepPromptModal.hidden = true;
});

el.stepPromptModal.addEventListener("click", (e) => {
  if (e.target === el.stepPromptModal) {
    el.stepPromptModal.hidden = true;
  }
});

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
