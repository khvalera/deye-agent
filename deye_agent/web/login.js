(() => {
  "use strict";

  const supportedLanguages = ["en", "uk", "pl", "de"];
  let dictionary = {};

  function detectLanguage() {
    const saved = window.localStorage.getItem("deye-agent-language");
    if (supportedLanguages.includes(saved)) return saved;

    const browserLanguage = (navigator.language || "en").toLowerCase();
    const shortCode = browserLanguage.split("-")[0];

    return supportedLanguages.includes(shortCode) ? shortCode : "en";
  }

  async function loadLanguage(language) {
    if (!supportedLanguages.includes(language)) language = "en";

    const response = await fetch(`/i18n/${language}.json`, {
      cache: "no-store"
    });

    if (!response.ok) throw new Error(`i18n HTTP ${response.status}`);

    dictionary = await response.json();
    document.documentElement.lang = language;
    window.localStorage.setItem("deye-agent-language", language);

    const select = document.getElementById("languageSelect");
    if (select) select.value = language;

    document.querySelectorAll("[data-i18n]").forEach((element) => {
      const key = element.getAttribute("data-i18n");
      if (dictionary[key]) element.textContent = dictionary[key];
    });
  }

  async function initialize() {
    const language = detectLanguage();

    try {
      await loadLanguage(language);
    } catch (error) {
      console.error("Deye Agent login language load failed:", error);
    }

    const select = document.getElementById("languageSelect");

    if (select) {
      select.addEventListener("change", async () => {
        try {
          await loadLanguage(select.value);
        } catch (error) {
          console.error("Deye Agent language switch failed:", error);
        }
      });
    }

    const query = new URLSearchParams(window.location.search);
    const error = document.getElementById("loginError");

    if (error && query.get("error") === "1") {
      error.hidden = false;
    }
  }

  initialize();
})();
