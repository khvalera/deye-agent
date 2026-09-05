(() => {
  "use strict";

  const overviewEndpoint = "/api/v1/overview";
  const historyEndpoint = "/api/v1/history";
  const refreshMs = 3000;
  const supportedLanguages = ["en", "uk", "pl", "de"];

  let dictionary = {};
  let currentLanguage = "en";
  let lastOverview = null;
  let lastHistory = null;

  const byId = (id) => document.getElementById(id);

  const t = (key) => dictionary[key] || key;

  const set = (id, value) => {
    const el = byId(id);
    if (!el) return;
    el.textContent = value === null || value === undefined ? "—" : String(value);
  };

  const formatNumber = (value, decimals) => {
    if (value === null || value === undefined) return "—";

    const number = Number(value);
    if (!Number.isFinite(number)) return "—";

    return new Intl.NumberFormat(currentLanguage, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
      useGrouping: false
    }).format(number);
  };

  const setNumber = (id, value, decimals) => {
    set(id, formatNumber(value, decimals));
  };

  const valueWithUnit = (value, unit, decimals = null) => {
    if (value === null || value === undefined) return "—";

    const formatted = decimals === null
      ? String(value)
      : formatNumber(value, decimals);

    return `${formatted} ${unit}`;
  };

  const boolText = (value) => {
    if (value === null || value === undefined) return "—";
    return value ? t("present") : t("none");
  };

  const localizeKnownValue = (value) => {
    const map = {
      "Normal": "normal",
      "Closed": "closed",
      "Disconnected": "disconnected",
      "On": "on"
    };
    return map[value] ? t(map[value]) : value;
  };

  function detectLanguage() {
    const saved = window.localStorage.getItem("deye-agent-language");
    if (supportedLanguages.includes(saved)) return saved;

    const browserLanguage = (navigator.language || "en").toLowerCase();
    const shortCode = browserLanguage.split("-")[0];

    return supportedLanguages.includes(shortCode) ? shortCode : "en";
  }

  async function loadLanguage(language) {
    if (!supportedLanguages.includes(language)) language = "en";

    const response = await fetch(`/i18n/${language}.json`, { cache: "no-store" });
    if (!response.ok) throw new Error(`i18n HTTP ${response.status}`);

    dictionary = await response.json();
    currentLanguage = language;
    document.documentElement.lang = language;
    window.localStorage.setItem("deye-agent-language", language);

    const select = byId("languageSelect");
    if (select) select.value = language;

    document.querySelectorAll("[data-i18n]").forEach((element) => {
      const key = element.getAttribute("data-i18n");
      if (dictionary[key]) element.textContent = dictionary[key];
    });

    if (lastOverview) renderOverview(lastOverview);
    if (lastHistory) renderHistory(lastHistory);
  }

  function renderOverview(data) {
    lastOverview = data;

    const device = data.device || {};
    const status = data.operating_status || {};
    const grid = data.grid || {};
    const inverter = data.inverter || {};
    const load = data.load || {};
    const pv = data.pv || {};
    const pv1 = pv.pv1 || {};
    const pv2 = pv.pv2 || {};
    const battery = data.battery || {};
    const bms = battery.bms || {};
    const energy = data.energy_today || {};
    const generator = data.generator || {};
    const acquisition = data.acquisition || {};

    set("deviceSubtitle", `${device.type || "Inverter"} · ${device.rated_power_w || "—"} W`);
    set("ageText", acquisition.age_seconds == null ? "—" : `${acquisition.age_seconds}s ${t("old")}`);

    const badge = byId("statusBadge");
    const statusText = data.status || "unknown";
    badge.textContent = statusText === "ok" ? "ok" : statusText;
    badge.className = "badge " + (
      statusText === "ok" ? "badge-ok" :
      statusText === "partial" ? "badge-warning" :
      statusText === "error" ? "badge-error" :
      "badge-neutral"
    );

    setNumber("gridPower", grid.power_w, 0);
    setNumber("gridVoltage", grid.voltage_v, 1);
    setNumber("gridCurrent", grid.current_a, 2);
    setNumber("gridFrequency", grid.frequency_hz, 2);
    set("gridRelay", localizeKnownValue(grid.relay_status) || "—");

    setNumber("loadPower", load.power_w, 0);
    setNumber("inverterVoltage", inverter.output_voltage_v, 1);
    setNumber("loadCurrent", load.current_a, 2);
    setNumber("loadFrequency", load.frequency_hz, 2);

    setNumber("batterySoc", battery.soc_percent, 0);
    setNumber("batteryVoltage", battery.voltage_v, 2);
    setNumber("batteryCurrent", battery.current_a, 2);
    setNumber("batteryPower", battery.power_w, 0);

    setNumber("pvTotalPower", pv.total_power_w, 0);
    setNumber("pv1Power", pv1.power_w, 0);
    setNumber("pv2Power", pv2.power_w, 0);

    set("inverterPower", valueWithUnit(inverter.output_power_w, "W", 0));
    set("inverterFrequency", valueWithUnit(inverter.output_frequency_hz, "Hz", 2));
    set("igbtTemp", valueWithUnit(inverter.igbt_temperature_c, "°C", 1));

    set("bmsVoltage", valueWithUnit(bms.realtime_voltage_v, "V", 1));
    set("bmsCurrent", valueWithUnit(bms.realtime_current_a, "A", 0));
    set("bmsTemp", valueWithUnit(bms.temperature_c, "°C", 1));
    set("bmsType", bms.type);

    set("runState", localizeKnownValue(status.run_state));
    set("warningState", boolText(status.has_warning));
    set("faultState", boolText(status.has_fault));
    set("sdState", localizeKnownValue(status.sd_card));

    set("generatorRelay", localizeKnownValue(generator.relay_status));
    set("generatorSwitch", localizeKnownValue(generator.switch_signal));
    set("generatorFrequency", valueWithUnit(generator.frequency_hz, "Hz", 2));

    set("energyGridBuy", valueWithUnit(energy.grid_buy_kwh, "kWh", 1));
    set("energyGridSell", valueWithUnit(energy.grid_sell_kwh, "kWh", 1));
    set("energyLoad", valueWithUnit(energy.load_kwh, "kWh", 1));
    set("energyPv", valueWithUnit(energy.pv_kwh, "kWh", 1));
    set("energyBatteryCharge", valueWithUnit(energy.battery_charge_kwh, "kWh", 1));
    set("energyBatteryDischarge", valueWithUnit(energy.battery_discharge_kwh, "kWh", 1));

    set("serialNumber", device.serial_number);
    set("deviceType", device.type);
    set("ratedPower", valueWithUnit(device.rated_power_w, "W", 0));
    set("protocolVersion", device.protocol_version);
    set("profileName", data.profile);
    set("generation", data.generation);

    set("footerUpdate", acquisition.last_update ? `${t("last_update")}: ${acquisition.last_update}` : t("no_data"));
  }

  function resizeCanvas(canvas) {
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(320, canvas.clientWidth || 320);
    const height = 220;

    canvas.width = Math.floor(width * ratio);
    canvas.height = Math.floor(height * ratio);

    const ctx = canvas.getContext("2d");
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);

    return { ctx, width, height };
  }

  function drawChart(canvasId, samples, series, unit, options = {}) {
    const canvas = byId(canvasId);
    if (!canvas) return;

    const { ctx, width, height } = resizeCanvas(canvas);
    const padding = { left: 48, right: 14, top: 14, bottom: 30 };
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;

    ctx.clearRect(0, 0, width, height);

    const allValues = [];
    series.forEach((entry) => {
      samples.forEach((sample) => {
        const value = sample[entry.field];
        if (typeof value === "number" && Number.isFinite(value)) allValues.push(value);
      });
    });

    if (!allValues.length) {
      ctx.globalAlpha = 0.65;
      ctx.fillStyle = getComputedStyle(document.body).color;
      ctx.font = "13px system-ui";
      ctx.fillText(t("no_data"), padding.left, padding.top + 20);
      ctx.globalAlpha = 1;
      return;
    }

    let min = Math.min(...allValues);
    let max = Math.max(...allValues);

    const minSpan = Number(options.minSpan || 0);

    if (min === max) {
      const fallbackSpan = minSpan > 0
        ? minSpan
        : (Math.abs(min || 1) * 0.10 || 1);

      min -= fallbackSpan / 2;
      max += fallbackSpan / 2;
    }

    let valueSpan = max - min;

    if (minSpan > 0 && valueSpan < minSpan) {
      const center = (min + max) / 2;
      min = center - minSpan / 2;
      max = center + minSpan / 2;
      valueSpan = max - min;
    } else {
      min -= valueSpan * 0.08;
      max += valueSpan * 0.08;
      valueSpan = max - min;
    }

    if (typeof options.clampMin === "number") {
      min = Math.max(options.clampMin, min);
    }

    if (typeof options.clampMax === "number") {
      max = Math.min(options.clampMax, max);
    }

    if (max <= min) {
      max = min + (minSpan > 0 ? minSpan : 1);
    }

    valueSpan = max - min;

    const textColor = getComputedStyle(document.body).color;
    const mutedColor = getComputedStyle(document.documentElement).getPropertyValue("--chart-muted").trim() || textColor;

    ctx.strokeStyle = mutedColor;
    ctx.fillStyle = mutedColor;
    ctx.lineWidth = 1;
    ctx.font = "11px system-ui";

    for (let i = 0; i <= 4; i += 1) {
      const y = padding.top + (plotHeight * i / 4);
      ctx.globalAlpha = 0.22;
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(width - padding.right, y);
      ctx.stroke();
      ctx.globalAlpha = 1;

      const value = max - ((max - min) * i / 4);
      const decimals = Number.isInteger(options.decimals)
        ? options.decimals
        : 1;
      ctx.fillText(`${value.toFixed(decimals)} ${unit}`, 2, y + 4);
    }

    const count = samples.length;
    const denominator = Math.max(1, count - 1);

    series.forEach((entry, index) => {
      ctx.strokeStyle = textColor;
      ctx.lineWidth = index === 0 ? 2.2 : 1.6;
      ctx.setLineDash(entry.dash || []);
      ctx.globalAlpha = Math.max(0.38, 1 - index * 0.12);
      ctx.beginPath();

      let started = false;

      samples.forEach((sample, sampleIndex) => {
        const value = sample[entry.field];
        if (typeof value !== "number" || !Number.isFinite(value)) return;

        const x = padding.left + (plotWidth * sampleIndex / denominator);
        const y = padding.top + ((max - value) / (max - min)) * plotHeight;

        if (!started) {
          ctx.moveTo(x, y);
          started = true;
        } else {
          ctx.lineTo(x, y);
        }
      });

      ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.setLineDash([]);
    });

    if (samples.length) {
      const first = new Date(samples[0].timestamp);
      const last = new Date(samples[samples.length - 1].timestamp);
      const formatter = new Intl.DateTimeFormat(currentLanguage, {
        hour: "2-digit",
        minute: "2-digit"
      });

      ctx.fillStyle = mutedColor;
      ctx.fillText(formatter.format(first), padding.left, height - 8);

      const lastText = formatter.format(last);
      const measured = ctx.measureText(lastText).width;
      ctx.fillText(lastText, width - padding.right - measured, height - 8);
    }
  }

  function renderPowerLegend() {
    const legend = byId("powerLegend");
    if (!legend) return;

    const items = [
      ["grid_power", ""],
      ["load_power", "legend-dashed"],
      ["inverter_power", "legend-dotted"],
      ["pv_power", "legend-dashed"],
      ["battery_power", "legend-dotted"]
    ];

    legend.innerHTML = "";

    items.forEach(([key, cssClass]) => {
      const item = document.createElement("span");
      item.className = "legend-item";

      const line = document.createElement("span");
      line.className = `legend-line ${cssClass}`.trim();

      const text = document.createElement("span");
      text.textContent = t(key);

      item.appendChild(line);
      item.appendChild(text);
      legend.appendChild(item);
    });
  }

  function renderHistory(data) {
    lastHistory = data;
    const samples = data.samples || [];

    renderPowerLegend();

    drawChart("powerChart", samples, [
      { field: "grid_power_w", dash: [] },
      { field: "load_power_w", dash: [8, 4] },
      { field: "inverter_power_w", dash: [2, 3] },
      { field: "pv_power_w", dash: [12, 4] },
      { field: "battery_power_w", dash: [1, 4] }
    ], "W", {
      minSpan: 200,
      decimals: 0
    });

    drawChart("socChart", samples, [
      { field: "battery_soc_percent", dash: [] }
    ], "%", {
      minSpan: 10,
      decimals: 0,
      clampMin: 0,
      clampMax: 100
    });

    drawChart("gridVoltageChart", samples, [
      { field: "grid_voltage_v", dash: [] }
    ], "V", {
      minSpan: 5,
      decimals: 1
    });

    drawChart("batteryVoltageChart", samples, [
      { field: "battery_voltage_v", dash: [] }
    ], "V", {
      minSpan: 0.20,
      decimals: 2
    });


    drawChart("inverterVoltageChart", samples, [
      { field: "inverter_voltage_v", dash: [] }
    ], "V", {
      minSpan: 5,
      decimals: 1
    });

    set("historyStatus", `${t("history_samples")}: ${data.sample_count || 0}`);
  }

  async function refreshOverview() {
    try {
      const response = await fetch(overviewEndpoint, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      renderOverview(await response.json());
    } catch (error) {
      const badge = byId("statusBadge");
      badge.textContent = t("offline");
      badge.className = "badge badge-error";
      set("ageText", t("api_unavailable"));
      console.error("Deye Agent overview refresh failed:", error);
    }
  }

  async function refreshHistory() {
    const range = byId("historyRange");
    const minutes = range ? range.value : "60";

    try {
      const response = await fetch(`${historyEndpoint}?minutes=${encodeURIComponent(minutes)}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      renderHistory(await response.json());
    } catch (error) {
      set("historyStatus", t("history_unavailable"));
      console.error("Deye Agent history refresh failed:", error);
    }
  }

  async function initialize() {
    const language = detectLanguage();

    try {
      await loadLanguage(language);
    } catch (error) {
      console.error("Deye Agent language load failed:", error);
    }

    const languageSelect = byId("languageSelect");
    if (languageSelect) {
      languageSelect.addEventListener("change", async () => {
        try {
          await loadLanguage(languageSelect.value);
        } catch (error) {
          console.error("Deye Agent language switch failed:", error);
        }
      });
    }

    const historyRange = byId("historyRange");
    if (historyRange) {
      historyRange.addEventListener("change", refreshHistory);
    }

    await Promise.all([refreshOverview(), refreshHistory()]);

    window.setInterval(refreshOverview, refreshMs);
    window.setInterval(refreshHistory, 15000);
  }

  window.addEventListener("resize", () => {
    if (lastHistory) renderHistory(lastHistory);
  });

  initialize();
})();
