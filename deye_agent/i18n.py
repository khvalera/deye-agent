
import gettext
import os

def get_system_lang():
    if "LANG_OVERRIDE" in os.environ:
        return os.environ["LANG_OVERRIDE"]

    lang = os.environ.get("LANG", "en")
    lang = lang.split(".")[0]
    lang = lang.split("_")[0]
    return lang

def setup_i18n():
    lang = get_system_lang()
    try:
        translation = gettext.translation(
            "deye-agent",
            localedir=os.path.join(os.path.dirname(__file__), "..", "locale"),
            languages=[lang]
        )
        translation.install()
        _ = translation.gettext
    except Exception:
        gettext.install("deye-agent")
        _ = gettext.gettext

    return _

_ = setup_i18n()
