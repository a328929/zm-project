(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const uiLang = $("uiLang");
  const langSelect = $("langSelect");
  const modelSelect = $("modelSelect");
  const fileInput = $("fileInput");
  const dropZone = $("dropZone");
  const pickedFile = $("pickedFile");
  const startBtn = $("startBtn");
  const cancelBtn = $("cancelBtn");
  const notice = $("notice");
  const logBox = $("logBox");
  const bar = $("bar");
  const progText = $("progText");
  const downloadBtn = $("downloadBtn");

  const checkBalanceBtn = $("checkBalanceBtn");
  const projectIdInput = $("projectIdInput");
  const balanceBox = $("balanceBox");

  const optPunctuate = $("optPunctuate");
  const optSmartFormat = $("optSmartFormat");
  const optUtteranceSplit = $("optUtteranceSplit");
  const optVadProfile = $("optVadProfile");
  const optVadNoiseDb = $("optVadNoiseDb");
  const apiTokenInput = $("apiTokenInput");

  const LS_KEY = "zmv6_ui_pref";
  const ALLOWED_VAD_PROFILES = ["balanced", "general", "asmr"];

  let pollTimer = null;
  let currentJobId = null;
  let since = 0;
  let startBalance = null;

  const i18n = {
    zh: {
      title: "极简语音识别字幕工坊",
      subtitle: "上传音视频 → 物理 VAD 切片 → 高精度识别 → 下载 SRT 字幕",
      cfgTitle: "识别设置",
      langLabel: "语音语言",
      langHint: "仅支持：中文、英文、日语",
      modelLabel: "模型选择",
      modelHint: "默认: nova-2-general；另含 nova-3-general、whisper-large 与日语专精模型",
      fileLabel: "上传文件",
      dropText: "拖拽到这里，或点击选择",
      fileHint: "支持 mp3/wav/m4a/mp4 等，后端会自动处理",
      advSummary: "官方参数调节 (高级)",
      labelUttSplit: "语音停顿检测 (秒)",
      uttSplitDesc: "控制切段灵敏度：小=切更碎；大=更连贯。建议通用 0.45~0.7，ASMR 0.7~1.2。",
      labelVadProfile: "活动语音分段模式",
      vadProfileDesc: "balanced/general 适合通用音频；asmr 更保留耳语细节。",
      labelVadNoise: "VAD 噪声阈值 (dB)",
      vadNoiseDesc: "范围 -70~-10。更低更保留弱语音；更高更偏强过滤。",
      startBtn: "开始识别并生成 SRT",
      cancelBtn: "取消当前任务",
      progTitle: "识别进度",
      balTitle: "API 余额检查",
      projectLabel: "Project ID（可选）",
      projectHint: "用于验证 API Key 是否可用",
      checkBalanceBtn: "查看当前 API 余额",
      balResult: "当前余额 ${amt} 美元",
      costResult: "💰 本次任务消耗: $${cost} 美元",
      downloadBtn: "下载字幕 .srt",
      noFile: "请先选择一个文件",
      starting: "正在提交任务...",
      startFailed: "提交失败：",
      polling: "任务已创建，开始轮询状态...",
      done: "任务完成，可下载字幕。",
      failed: "任务失败：",
      cancelled: "任务已取消。",
      networkErr: "网络错误：",
      modelJP: "提示：你选择了日语专精模型，建议语言设为 ja 以获得最佳准确率。",
      savePref: "✅ 已自动保存参数",
      cancelSent: "🛑 取消请求已发送",
      cancelFailed: "取消失败：",
      uttSplitInvalid: "utterance_split 必须在 0.1 到 5 之间",
      vadNoiseInvalid: "vad_noise_db 必须在 -70 到 -10 之间",
      authTip: "此服务启用了接口鉴权，请填写访问令牌",
      statusErr: "状态查询失败："
    },
    en: {
      title: "Ultra-Stable STT Studio",
      subtitle: "Upload media → Physical VAD Splitting → High-precision STT → Download SRT",
      cfgTitle: "Transcription Settings",
      langLabel: "Spoken Language",
      langHint: "Supported: Chinese, English, Japanese",
      modelLabel: "Model Selection",
      modelHint: "Default: nova-2-general; plus nova-3-general, whisper-large, JP-specialized model",
      fileLabel: "Upload File",
      dropText: "Drag file here, or click to select",
      fileHint: "Supports mp3/wav/m4a/mp4 and more.",
      advSummary: "Official Parameters (Advanced)",
      labelUttSplit: "Silence Threshold (sec)",
      uttSplitDesc: "Segmentation sensitivity: lower=more splits, higher=more continuity. General 0.45~0.7, ASMR 0.7~1.2.",
      labelVadProfile: "VAD Profile",
      vadProfileDesc: "balanced/general for typical audio; asmr preserves low-energy whisper details.",
      labelVadNoise: "VAD Noise Threshold (dB)",
      vadNoiseDesc: "Range -70~-10. Lower keeps weak speech, higher filters more aggressively.",
      startBtn: "Start Transcription",
      cancelBtn: "Cancel Current Job",
      progTitle: "Progress",
      balTitle: "API Balance Check",
      projectLabel: "Project ID (optional)",
      projectHint: "Validate API key and project",
      checkBalanceBtn: "Check Balance",
      balResult: "Current Balance: ${amt} USD",
      costResult: "💰 Cost: $${cost} USD",
      downloadBtn: "Download .srt Subtitle",
      noFile: "Please select a file first",
      starting: "Submitting job...",
      startFailed: "Submit failed: ",
      polling: "Job created. Polling status...",
      done: "Job completed.",
      failed: "Job failed: ",
      cancelled: "Job cancelled.",
      networkErr: "Network error: ",
      modelJP: "Hint: Japanese model selected. Set language to ja for best accuracy.",
      savePref: "✅ Preferences auto-saved",
      cancelSent: "🛑 Cancel request sent",
      cancelFailed: "Cancel failed: ",
      uttSplitInvalid: "utterance_split must be between 0.1 and 5",
      vadNoiseInvalid: "vad_noise_db must be between -70 and -10",
      authTip: "This service requires API token",
      statusErr: "Status query failed: "
    },
    ja: {
      title: "極簡音声認識字幕工房",
      subtitle: "音声/動画アップロード → 物理VAD切断 → 高精度認識 → SRTダウンロード",
      cfgTitle: "認識設定",
      langLabel: "音声言語",
      langHint: "対応: 中国語・英語・日本語",
      modelLabel: "モデル選択",
      modelHint: "既定: nova-2-general。他には nova-3 / whisper-large / 日本語特化",
      fileLabel: "ファイルアップロード",
      dropText: "ここにドラッグ、またはクリックして選択",
      fileHint: "mp3/wav/m4a/mp4 などに対応",
      advSummary: "詳細パラメータ (Advanced)",
      labelUttSplit: "音声停止検出 (秒)",
      uttSplitDesc: "分割感度：小さいほど細かく分割、大きいほど連続。一般 0.45~0.7、ASMR 0.7~1.2 推奨。",
      labelVadProfile: "VADプロファイル",
      vadProfileDesc: "balanced/general は汎用向け、asmr は低音量ささやき保持向け。",
      labelVadNoise: "VADノイズ閾値 (dB)",
      vadNoiseDesc: "範囲 -70~-10。低いほど弱い音声を残しやすく、高いほど強く除去。",
      startBtn: "認識開始してSRTを生成",
      cancelBtn: "現在のジョブを中止",
      progTitle: "進捗状況",
      balTitle: "API残高チェック",
      projectLabel: "プロジェクトID (任意)",
      projectHint: "APIキーの有効性を確認",
      checkBalanceBtn: "現在の残高を見る",
      balResult: "現在の残高: ${amt} USD",
      costResult: "💰 今回の消費: $${cost} USD",
      downloadBtn: "字幕 .srt をダウンロード",
      noFile: "ファイルを選択してください",
      starting: "ジョブ送信中...",
      startFailed: "送信失敗: ",
      polling: "ジョブ作成完了。状態を監視します...",
      done: "完了。字幕をダウンロードできます。",
      failed: "失敗: ",
      cancelled: "ジョブはキャンセルされました。",
      networkErr: "ネットワークエラー: ",
      modelJP: "ヒント: 日本語特化モデル選択中。ja を推奨します。",
      savePref: "✅ 設定を自動保存しました",
      cancelSent: "🛑 キャンセル要求を送信しました",
      cancelFailed: "キャンセル失敗: ",
      uttSplitInvalid: "utterance_split は 0.1〜5 の範囲で指定してください",
      vadNoiseInvalid: "vad_noise_db は -70〜-10 の範囲で指定してください",
      authTip: "このサービスは API トークン認証が有効です",
      statusErr: "ステータス取得失敗: "
    }
  };

  function t(key) {
    const lang = uiLang.value || "zh";
    return (i18n[lang] && i18n[lang][key]) || i18n.zh[key] || key;
  }

  function setText(id, key) {
    const el = $(id);
    if (el) el.textContent = t(key);
  }

  function applyI18n() {
    ["title", "subtitle", "cfgTitle", "langLabel", "langHint", "modelLabel", "modelHint", "fileLabel", "dropText", "fileHint", "advSummary", "labelUttSplit", "uttSplitDesc", "labelVadProfile", "vadProfileDesc", "labelVadNoise", "vadNoiseDesc", "startBtn", "cancelBtn", "progTitle", "balTitle", "projectLabel", "projectHint", "checkBalanceBtn"].forEach((k) => setText(k, k));
    downloadBtn.textContent = t("downloadBtn");
    updateNoticeForModel();
  }

  function updateNoticeForModel() {
    const m = modelSelect.value;
    notice.textContent = (m === "kotoba-tech/kotoba-whisper-v2.2") ? t("modelJP") : "";
  }

  function addLog(msg, timestamp) {
    const timeStr = timestamp || new Date().toLocaleTimeString();
    const line = `[${timeStr}] ${msg}\n`;
    logBox.textContent += line;
    if (logBox.textContent.length > 250000) {
      logBox.textContent = logBox.textContent.slice(-200000);
    }
    logBox.scrollTop = logBox.scrollHeight;
  }

  function setProgress(v) {
    const n = Math.max(0, Math.min(100, Number(v || 0)));
    bar.style.width = `${n}%`;
    progText.textContent = `${n.toFixed(1)}%`;
  }

  function setBusy(busy) {
    startBtn.disabled = !!busy;
    cancelBtn.disabled = !busy;
    fileInput.disabled = !!busy;
    modelSelect.disabled = !!busy;
    langSelect.disabled = !!busy;
  }

  function clearStateForNewJob() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
    currentJobId = null;
    since = 0;
    setProgress(0);
    logBox.textContent = "";
    downloadBtn.classList.add("hidden");
    downloadBtn.href = "#";
  }

  function getAuthHeaders() {
    const token = (apiTokenInput && apiTokenInput.value || "").trim();
    if (!token) return {};
    return { "X-API-Token": token };
  }

  function collectOptions() {
    let utt = Number(optUtteranceSplit.value || 0.5);
    if (!Number.isFinite(utt) || utt < 0.1 || utt > 5) {
      throw new Error(t("uttSplitInvalid"));
    }

    let vadNoise = Number(optVadNoiseDb.value || -35);
    if (!Number.isFinite(vadNoise) || vadNoise < -70 || vadNoise > -10) {
      throw new Error(t("vadNoiseInvalid"));
    }

    const vadProfile = (optVadProfile.value || "balanced").trim().toLowerCase();

    return {
      smart_format: !!optSmartFormat.checked,
      punctuate: !!optPunctuate.checked,
      utterance_split: Number(utt.toFixed(2)),
      vad_profile: ALLOWED_VAD_PROFILES.includes(vadProfile) ? vadProfile : "balanced",
      vad_noise_db: Number(vadNoise.toFixed(1))
    };
  }

  function persistPref() {
    const pref = {
      uiLang: uiLang.value,
      lang: langSelect.value,
      model: modelSelect.value,
      opt: {
        punctuate: !!optPunctuate.checked,
        smart_format: !!optSmartFormat.checked,
        utterance_split: Number(optUtteranceSplit.value || 0.5),
        vad_profile: (optVadProfile.value || "balanced"),
        vad_noise_db: Number(optVadNoiseDb.value || -35)
      }
    };
    try { localStorage.setItem(LS_KEY, JSON.stringify(pref)); } catch (_) {}
  }

  function restorePref() {
    let pref = null;
    try { pref = JSON.parse(localStorage.getItem(LS_KEY) || "null"); } catch (_) {}
    if (!pref || typeof pref !== "object") return;

    if (pref.uiLang) uiLang.value = pref.uiLang;
    if (pref.lang) langSelect.value = pref.lang;
    if (pref.model) modelSelect.value = pref.model;

    if (pref.opt) {
      optPunctuate.checked = !!pref.opt.punctuate;
      optSmartFormat.checked = !!pref.opt.smart_format;
      if (Number.isFinite(Number(pref.opt.utterance_split))) {
        optUtteranceSplit.value = String(pref.opt.utterance_split);
      }
      if (typeof pref.opt.vad_profile === "string") {
        const pv = String(pref.opt.vad_profile).toLowerCase();
        optVadProfile.value = ALLOWED_VAD_PROFILES.includes(pv) ? pv : "balanced";
      }
      if (Number.isFinite(Number(pref.opt.vad_noise_db))) {
        optVadNoiseDb.value = String(pref.opt.vad_noise_db);
      }
    }
  }

  async function loadServerConfig() {
    try {
      const res = await fetch("/api/config", { headers: getAuthHeaders() });
      const data = await res.json();
      if (!res.ok || !data.ok) return;

      const vd = data.vad_defaults || {};
      const minSilence = Number(vd.min_silence);
      if (Number.isFinite(minSilence)) {
        optUtteranceSplit.value = String(minSilence);
      }

      const noiseDb = Number(vd.noise_db);
      if (Number.isFinite(noiseDb)) {
        optVadNoiseDb.value = String(noiseDb);
      }

      const profile = String(vd.profile || "").toLowerCase();
      if (ALLOWED_VAD_PROFILES.includes(profile)) {
        optVadProfile.value = profile;
      }

      const profiles = Array.isArray(vd.profiles) ? vd.profiles.map((x) => String(x).toLowerCase()) : [];
      if (profiles.length > 0) {
        const current = optVadProfile.value;
        optVadProfile.innerHTML = "";
        profiles.forEach((p) => {
          if (!ALLOWED_VAD_PROFILES.includes(p)) return;
          const op = document.createElement("option");
          op.value = p;
          op.textContent = p === "balanced" ? "balanced（默认）" : (p === "general" ? "general（通用强化）" : "asmr（耳语保留）");
          optVadProfile.appendChild(op);
        });
        if ([...optVadProfile.options].some((x) => x.value === current)) optVadProfile.value = current;
      }
    } catch (_) {
      // ignore; keep local defaults
    }
  }

  async function getFastBalance() {
    try {
      const r = await fetch("/api/balance", { headers: getAuthHeaders() });
      const d = await r.json();
      return d.ok ? Number(d.total) : null;
    } catch (_) {
      return null;
    }
  }

  async function startJob() {
    const f = fileInput.files && fileInput.files[0];
    if (!f) {
      addLog("⚠️ " + t("noFile"));
      return;
    }

    clearStateForNewJob();
    setBusy(true);
    addLog("⏳ " + t("starting"));

    startBalance = null;
    getFastBalance().then((v) => { startBalance = v; });

    const fd = new FormData();
    fd.append("file", f);
    fd.append("language", langSelect.value);
    fd.append("model", modelSelect.value);

    let opts;
    try {
      opts = collectOptions();
    } catch (err) {
      addLog("❌ " + String(err.message || err));
      setBusy(false);
      return;
    }
    fd.append("options", JSON.stringify(opts));

    try {
      const res = await fetch("/api/start", { method: "POST", body: fd, headers: getAuthHeaders() });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || res.statusText);

      currentJobId = data.job_id;
      addLog("✅ " + t("polling"));
      pollTimer = setTimeout(pollStatus, 1000);
    } catch (err) {
      addLog("❌ " + t("startFailed") + String(err.message || err));
      setBusy(false);
    }
  }

  async function cancelJob() {
    if (!currentJobId) return;
    try {
      const res = await fetch(`/api/cancel/${encodeURIComponent(currentJobId)}`, {
        method: "POST",
        headers: getAuthHeaders()
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || res.statusText);
      addLog(t("cancelSent"));
    } catch (err) {
      addLog("❌ " + t("cancelFailed") + String(err.message || err));
    }
  }

  async function pollStatus() {
    if (!currentJobId) return;
    try {
      const res = await fetch(`/api/status/${encodeURIComponent(currentJobId)}?since=${since}`, {
        headers: getAuthHeaders()
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        addLog("❌ " + t("statusErr") + (data.error || res.statusText));
        stopPolling();
        setBusy(false);
        return;
      }

      const logs = data.logs || [];
      for (const item of logs) {
        addLog(item.msg || "", item.ts);
      }
      since = Number(data.next_since || since);
      setProgress(data.progress);

      if (data.status === "done") {
        addLog("✅ " + t("done"));

        const endBalance = await getFastBalance();
        if (startBalance !== null && endBalance !== null) {
          const cost = Math.max(0, startBalance - endBalance);
          if (cost > 0) addLog(t("costResult").replace("${cost}", cost.toFixed(6)));
        }

        if (data.download_url) {
          downloadBtn.href = data.download_url;
          downloadBtn.classList.remove("hidden");
        }
        stopPolling();
        setBusy(false);
      } else if (data.status === "error") {
        addLog("❌ " + t("failed") + (data.error || data.status));
        stopPolling();
        setBusy(false);
      } else if (data.status === "cancelled") {
        addLog("🛑 " + t("cancelled"));
        stopPolling();
        setBusy(false);
      } else {
        pollTimer = setTimeout(pollStatus, 1200);
      }
    } catch (err) {
      addLog("❌ " + t("networkErr") + String(err.message || err));
      stopPolling();
      setBusy(false);
    }
  }

  function stopPolling() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  function updatePickedFile() {
    const f = fileInput.files && fileInput.files[0];
    if (!f) {
      pickedFile.textContent = "";
      return;
    }
    pickedFile.textContent = `📎 ${f.name} (${(f.size / 1024 / 1024).toFixed(2)} MB)`;
  }

  async function checkBalance() {
    balanceBox.textContent = "...";
    const pid = (projectIdInput.value || "").trim();
    let url = "/api/balance";
    if (pid) url += `?project_id=${encodeURIComponent(pid)}`;

    try {
      const res = await fetch(url, { headers: getAuthHeaders() });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        balanceBox.textContent = `❌ ${data.error || res.statusText}`;
        return;
      }
      balanceBox.textContent = t("balResult").replace("${amt}", Number(data.total || 0).toFixed(4));
    } catch (err) {
      balanceBox.textContent = `❌ ${String(err.message || err)}`;
    }
  }

  // Drag & Drop
  ["dragenter", "dragover"].forEach((ev) => {
    dropZone.addEventListener(ev, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.add("drag");
    });
  });

  ["dragleave", "drop"].forEach((ev) => {
    dropZone.addEventListener(ev, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove("drag");
    });
  });

  dropZone.addEventListener("drop", (e) => {
    const files = e.dataTransfer && e.dataTransfer.files;
    if (files && files.length > 0) {
      fileInput.files = files;
      updatePickedFile();
    }
  });

  dropZone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });

  // Bindings
  uiLang.addEventListener("change", () => {
    applyI18n();
    persistPref();
  });
  modelSelect.addEventListener("change", () => {
    updateNoticeForModel();
    persistPref();
  });
  langSelect.addEventListener("change", persistPref);
  fileInput.addEventListener("change", updatePickedFile);

  [optPunctuate, optSmartFormat, optUtteranceSplit, optVadProfile, optVadNoiseDb].forEach((el) => {
    el.addEventListener("change", persistPref);
  });

  startBtn.addEventListener("click", startJob);
  cancelBtn.addEventListener("click", cancelJob);
  checkBalanceBtn.addEventListener("click", checkBalance);

  // 初始化语言
  restorePref();
  loadServerConfig().finally(() => persistPref());
  if (!uiLang.value) {
    const navLang = (navigator.language || "").toLowerCase();
    if (navLang.startsWith("en")) uiLang.value = "en";
    else if (navLang.startsWith("ja")) uiLang.value = "ja";
    else uiLang.value = "zh";
  }

  applyI18n();
  updatePickedFile();
  setBusy(false);
})();
