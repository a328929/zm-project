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
  const optVadPreset = $("optVadPreset");
  const optVadThreshold = $("optVadThreshold");
  const optVadMinSilenceMs = $("optVadMinSilenceMs");
  const optVadMinSpeechMs = $("optVadMinSpeechMs");
  const optVadSpeechPadMs = $("optVadSpeechPadMs");
  const apiTokenInput = $("apiTokenInput");

  const LS_KEY = "zmv6_ui_pref";

  let pollTimer = null;
  let currentJobId = null;
  let since = 0;
  let startBalance = null;

  const i18n = {
    zh: {
      title: "极简语音识别字幕工坊",
      subtitle: "上传音视频 → Silero VAD 神经切片 → 高精度识别 → 下载 SRT 字幕",
      cfgTitle: "识别设置",
      langLabel: "语音语言",
      langHint: "仅支持：中文、英文、日语",
      modelLabel: "模型选择",
      modelHint: "默认: nova-2-general；另含 nova-3-general、whisper-large 与日语专精模型",
      fileLabel: "上传文件",
      dropText: "拖拽到这里，或点击选择",
      fileHint: "支持 mp3/wav/m4a/mp4 等，后端会自动处理",
      advSummary: "官方参数调节 (高级)",
      labelVadPreset: "VAD 预设方案",
      vadPresetDesc: "general=通用；asmr=耳语；mixed=混合折中。下方参数可继续微调。",
      labelVadThreshold: "Silero 检测阈值",
      vadThresholdDesc: "范围 0.1~0.95。低=召回高，高=更保守。",
      labelVadMinSilence: "最小静音时长 (ms)",
      vadMinSilenceDesc: "范围 50~3000。越大切段越少。",
      labelVadMinSpeech: "最小语音时长 (ms)",
      vadMinSpeechDesc: "范围 50~3000。过滤瞬时噪声。",
      labelVadSpeechPad: "语音边界补偿 (ms)",
      vadSpeechPadDesc: "范围 0~1000。为首尾补上下文。",
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
      vadThresholdInvalid: "vad_threshold 必须在 0.1 到 0.95 之间",
      vadMinSilenceInvalid: "vad_min_silence_ms 必须在 50 到 3000 之间",
      vadMinSpeechInvalid: "vad_min_speech_ms 必须在 50 到 3000 之间",
      vadSpeechPadInvalid: "vad_speech_pad_ms 必须在 0 到 1000 之间",
      authTip: "此服务启用了接口鉴权，请填写访问令牌",
      statusErr: "状态查询失败："
    },
    en: {
      title: "Ultra-Stable STT Studio",
      subtitle: "Upload media → Silero Neural VAD Segmentation → High-precision STT → Download SRT",
      cfgTitle: "Transcription Settings",
      langLabel: "Spoken Language",
      langHint: "Supported: Chinese, English, Japanese",
      modelLabel: "Model Selection",
      modelHint: "Default: nova-2-general; plus nova-3-general, whisper-large, JP-specialized model",
      fileLabel: "Upload File",
      dropText: "Drag file here, or click to select",
      fileHint: "Supports mp3/wav/m4a/mp4 and more.",
      advSummary: "Official Parameters (Advanced)",
      labelVadPreset: "VAD Preset",
      vadPresetDesc: "general = generic, asmr = whisper-focused, mixed = balanced hybrid. You can still fine-tune below.",
      labelVadThreshold: "Silero VAD Threshold",
      vadThresholdDesc: "Range 0.1~0.95. Lower = higher recall, higher = stricter speech detection.",
      labelVadMinSilence: "Min Silence Duration (ms)",
      vadMinSilenceDesc: "Range 50~3000. Higher values create fewer, longer segments.",
      labelVadMinSpeech: "Min Speech Duration (ms)",
      vadMinSpeechDesc: "Range 50~3000. Filters impulsive noise-like fragments.",
      labelVadSpeechPad: "Speech Padding (ms)",
      vadSpeechPadDesc: "Range 0~1000. Adds context around speech boundaries.",
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
      vadThresholdInvalid: "vad_threshold must be between 0.1 and 0.95",
      vadMinSilenceInvalid: "vad_min_silence_ms must be between 50 and 3000",
      vadMinSpeechInvalid: "vad_min_speech_ms must be between 50 and 3000",
      vadSpeechPadInvalid: "vad_speech_pad_ms must be between 0 and 1000",
      authTip: "This service requires API token",
      statusErr: "Status query failed: "
    },
    ja: {
      title: "極簡音声認識字幕工房",
      subtitle: "音声/動画アップロード → SileroニューラルVAD分割 → 高精度認識 → SRTダウンロード",
      cfgTitle: "認識設定",
      langLabel: "音声言語",
      langHint: "対応: 中国語・英語・日本語",
      modelLabel: "モデル選択",
      modelHint: "既定: nova-2-general。他には nova-3 / whisper-large / 日本語特化",
      fileLabel: "ファイルアップロード",
      dropText: "ここにドラッグ、またはクリックして選択",
      fileHint: "mp3/wav/m4a/mp4 などに対応",
      advSummary: "詳細パラメータ (Advanced)",
      labelVadPreset: "VADプリセット",
      vadPresetDesc: "general=汎用、asmr=ささやき重視、mixed=混合向け。下の値で微調整可能。",
      labelVadThreshold: "Silero VADしきい値",
      vadThresholdDesc: "範囲 0.1~0.95。低いほど検出しやすく、高いほど厳格。",
      labelVadMinSilence: "最小無音長 (ms)",
      vadMinSilenceDesc: "範囲 50~3000。大きいほど分割数が減る。",
      labelVadMinSpeech: "最小発話長 (ms)",
      vadMinSpeechDesc: "範囲 50~3000。瞬間ノイズ片を除去。",
      labelVadSpeechPad: "音声境界パディング (ms)",
      vadSpeechPadDesc: "範囲 0~1000。前後に文脈を追加。",
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
      vadThresholdInvalid: "vad_threshold は 0.1〜0.95 の範囲で指定してください",
      vadMinSilenceInvalid: "vad_min_silence_ms は 50〜3000 の範囲で指定してください",
      vadMinSpeechInvalid: "vad_min_speech_ms は 50〜3000 の範囲で指定してください",
      vadSpeechPadInvalid: "vad_speech_pad_ms は 0〜1000 の範囲で指定してください",
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
    ["title", "subtitle", "cfgTitle", "langLabel", "langHint", "modelLabel", "modelHint", "fileLabel", "dropText", "fileHint", "advSummary", "labelVadPreset", "vadPresetDesc", "labelVadThreshold", "vadThresholdDesc", "labelVadMinSilence", "vadMinSilenceDesc", "labelVadMinSpeech", "vadMinSpeechDesc", "labelVadSpeechPad", "vadSpeechPadDesc", "startBtn", "cancelBtn", "progTitle", "balTitle", "projectLabel", "projectHint", "checkBalanceBtn"].forEach((k) => setText(k, k));
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

  async function parseApiResponse(res) {
    const raw = await res.text();
    if (!raw) return {};

    try {
      return JSON.parse(raw);
    } catch (_) {
      const compact = raw
        .replace(/<[^>]+>/g, " ")
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 160);
      throw new Error(`服务器返回了非 JSON 响应 (HTTP ${res.status})${compact ? `: ${compact}` : ""}`);
    }
  }

  function collectOptions() {
    const threshold = Number(optVadThreshold.value || 0.5);
    if (!Number.isFinite(threshold) || threshold < 0.1 || threshold > 0.95) {
      throw new Error(t("vadThresholdInvalid"));
    }

    const minSilence = Number(optVadMinSilenceMs.value || 400);
    if (!Number.isFinite(minSilence) || minSilence < 50 || minSilence > 3000) {
      throw new Error(t("vadMinSilenceInvalid"));
    }

    const minSpeech = Number(optVadMinSpeechMs.value || 220);
    if (!Number.isFinite(minSpeech) || minSpeech < 50 || minSpeech > 3000) {
      throw new Error(t("vadMinSpeechInvalid"));
    }

    const speechPad = Number(optVadSpeechPadMs.value || 120);
    if (!Number.isFinite(speechPad) || speechPad < 0 || speechPad > 1000) {
      throw new Error(t("vadSpeechPadInvalid"));
    }

    const preset = (optVadPreset.value || "general").trim().toLowerCase();

    return {
      smart_format: !!optSmartFormat.checked,
      punctuate: !!optPunctuate.checked,
      vad_preset: ["general", "asmr", "mixed"].includes(preset) ? preset : "general",
      vad_threshold: Number(threshold.toFixed(2)),
      vad_min_silence_ms: Math.round(minSilence),
      vad_min_speech_ms: Math.round(minSpeech),
      vad_speech_pad_ms: Math.round(speechPad)
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
        vad_preset: (optVadPreset.value || "general"),
        vad_threshold: Number(optVadThreshold.value || 0.5),
        vad_min_silence_ms: Number(optVadMinSilenceMs.value || 400),
        vad_min_speech_ms: Number(optVadMinSpeechMs.value || 220),
        vad_speech_pad_ms: Number(optVadSpeechPadMs.value || 120)
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
      if (typeof pref.opt.vad_preset === "string") {
        const pp = String(pref.opt.vad_preset).toLowerCase();
        optVadPreset.value = ["general", "asmr", "mixed"].includes(pp) ? pp : "general";
      }
      if (Number.isFinite(Number(pref.opt.vad_threshold))) {
        optVadThreshold.value = String(pref.opt.vad_threshold);
      }
      if (Number.isFinite(Number(pref.opt.vad_min_silence_ms))) {
        optVadMinSilenceMs.value = String(pref.opt.vad_min_silence_ms);
      }
      if (Number.isFinite(Number(pref.opt.vad_min_speech_ms))) {
        optVadMinSpeechMs.value = String(pref.opt.vad_min_speech_ms);
      }
      if (Number.isFinite(Number(pref.opt.vad_speech_pad_ms))) {
        optVadSpeechPadMs.value = String(pref.opt.vad_speech_pad_ms);
      }
    }
  }

  async function loadServerConfig() {
    try {
      const res = await fetch("/api/config", { headers: getAuthHeaders() });
      const data = await parseApiResponse(res);
      if (!res.ok || !data.ok) return;

      const vd = data.vad_defaults || {};

      const preset = String(vd.vad_preset || "").toLowerCase();
      if (["general", "asmr", "mixed"].includes(preset)) optVadPreset.value = preset;

      const presets = vd.vad_presets || {};
      if (presets && typeof presets === "object") {
        const current = optVadPreset.value || "general";
        optVadPreset.innerHTML = "";
        ["general", "asmr", "mixed"].forEach((k) => {
          if (!presets[k]) return;
          const op = document.createElement("option");
          op.value = k;
          op.textContent = `${k}（${(presets[k].label || k)}）`;
          optVadPreset.appendChild(op);
        });
        if ([...optVadPreset.options].some((x) => x.value === current)) optVadPreset.value = current;
      }

      const threshold = Number(vd.vad_threshold);
      if (Number.isFinite(threshold)) optVadThreshold.value = String(threshold);

      const minSilence = Number(vd.vad_min_silence_ms);
      if (Number.isFinite(minSilence)) optVadMinSilenceMs.value = String(minSilence);

      const minSpeech = Number(vd.vad_min_speech_ms);
      if (Number.isFinite(minSpeech)) optVadMinSpeechMs.value = String(minSpeech);

      const speechPad = Number(vd.vad_speech_pad_ms);
      if (Number.isFinite(speechPad)) optVadSpeechPadMs.value = String(speechPad);
    } catch (_) {
      // ignore; keep local defaults
    }
  }

  async function getFastBalance() {
    try {
      const r = await fetch("/api/balance", { headers: getAuthHeaders() });
      const d = await parseApiResponse(r);
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
      const data = await parseApiResponse(res);
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
      const data = await parseApiResponse(res);
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
      const data = await parseApiResponse(res);
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
      const data = await parseApiResponse(res);
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

  [optPunctuate, optSmartFormat, optVadPreset, optVadThreshold, optVadMinSilenceMs, optVadMinSpeechMs, optVadSpeechPadMs].forEach((el) => {
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
