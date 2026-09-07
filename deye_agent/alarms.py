import os
import re

import yaml

from .config import ALARMS_FILE


ALARM_SCHEMA_VERSION = 1
SUPPORTED_OPERATORS = ("le", "ge")
_RULE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

_cache_path = None
_cache_signature = None
_cache_rules = []
_cache_error = None


def _is_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
    )


def _normalize_message(rule_id, field_name, value):
    if value is None:
        return ""

    if not isinstance(value, str):
        raise ValueError(
            "alarm rule '{}' field '{}' must be a string".format(
                rule_id,
                field_name
            )
        )

    if len(value) > 2048:
        raise ValueError(
            "alarm rule '{}' field '{}' is too long".format(
                rule_id,
                field_name
            )
        )

    return value


def _normalize_rule(rule_id, raw_rule):
    if not isinstance(rule_id, str) or not _RULE_ID_RE.match(rule_id):
        raise ValueError(
            "alarm rule id '{}' is invalid".format(rule_id)
        )

    if not isinstance(raw_rule, dict):
        raise ValueError(
            "alarm rule '{}' must be a mapping".format(rule_id)
        )

    enabled = raw_rule.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError(
            "alarm rule '{}' field 'enabled' must be true or false".format(
                rule_id
            )
        )

    metric = raw_rule.get("metric")
    if not isinstance(metric, str) or not metric.strip():
        raise ValueError(
            "alarm rule '{}' requires a non-empty metric".format(rule_id)
        )
    metric = metric.strip()

    operator = str(raw_rule.get("operator", "le")).strip().lower()
    if operator not in SUPPORTED_OPERATORS:
        raise ValueError(
            "alarm rule '{}' operator must be one of: {}".format(
                rule_id,
                ", ".join(SUPPORTED_OPERATORS)
            )
        )

    alarm_threshold = raw_rule.get("alarm")
    cancel_threshold = raw_rule.get("cancel")

    if not _is_number(alarm_threshold):
        raise ValueError(
            "alarm rule '{}' field 'alarm' must be numeric".format(rule_id)
        )

    if not _is_number(cancel_threshold):
        raise ValueError(
            "alarm rule '{}' field 'cancel' must be numeric".format(rule_id)
        )

    if operator == "le" and cancel_threshold <= alarm_threshold:
        raise ValueError(
            "alarm rule '{}' with operator 'le' requires cancel > alarm".format(
                rule_id
            )
        )

    if operator == "ge" and cancel_threshold >= alarm_threshold:
        raise ValueError(
            "alarm rule '{}' with operator 'ge' requires cancel < alarm".format(
                rule_id
            )
        )

    return {
        "id": rule_id,
        "enabled": enabled,
        "metric": metric,
        "operator": operator,
        "alarm": alarm_threshold,
        "cancel": cancel_threshold,
        "message": _normalize_message(
            rule_id,
            "message",
            raw_rule.get("message", "")
        ),
        "clear_message": _normalize_message(
            rule_id,
            "clear_message",
            raw_rule.get("clear_message", "")
        ),
    }


def load_alarm_rules(path=ALARMS_FILE):
    """Load and validate threshold notification rules from alarms.yaml."""
    if not os.path.isfile(path):
        return []

    with open(path, "r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}

    if not isinstance(document, dict):
        raise ValueError("alarms file root must be a mapping")

    version = document.get("version", ALARM_SCHEMA_VERSION)
    if version != ALARM_SCHEMA_VERSION:
        raise ValueError(
            "unsupported alarms schema version {}; expected {}".format(
                version,
                ALARM_SCHEMA_VERSION
            )
        )

    raw_rules = document.get("alarms", {})
    if raw_rules is None:
        raw_rules = {}

    if not isinstance(raw_rules, dict):
        raise ValueError("alarms must be a mapping")

    rules = []
    for rule_id, raw_rule in raw_rules.items():
        rules.append(_normalize_rule(rule_id, raw_rule))

    return rules


def _file_signature(path):
    try:
        stat_result = os.stat(path)
    except OSError:
        return ("missing",)

    return (
        stat_result.st_ino,
        stat_result.st_mtime,
        stat_result.st_size,
    )


def get_alarm_rules(path=ALARMS_FILE):
    """Return cached rules and re-read the file when it changes.

    The return value is (rules, error, changed). Invalid files fail closed for
    threshold notifications while the main inverter polling loop can continue.
    """
    global _cache_path
    global _cache_signature
    global _cache_rules
    global _cache_error

    signature = _file_signature(path)

    if _cache_path == path and _cache_signature == signature:
        return list(_cache_rules), _cache_error, False

    try:
        rules = load_alarm_rules(path)
        error = None
    except Exception as exc:
        rules = []
        error = str(exc)

    _cache_path = path
    _cache_signature = signature
    _cache_rules = list(rules)
    _cache_error = error

    return list(_cache_rules), _cache_error, True
