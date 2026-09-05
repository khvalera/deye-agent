import os

from .config import DEFAULT_PROFILE, PROFILES_DIR, REGISTERS_FILE


PROFILE_DEFINITIONS = {
    "single_phase_storage": {
        "filename": "single_phase_storage.yaml",
        "family": "Single-phase storage inverter",
        "status": "hardware-validated",
        "supported": True,
        # V118 documents normal/register-pack data through 809 and a
        # 500-word read-only memory/fault-history table at 1000..1499.
        # Inventory intentionally includes the 810..999 discovery gap too.
        "inventory_ranges": [[0, 1499]],
        "settings_supported": True,
        "settings_range": [197, 296],
        "extended_settings_range": [326, 416],
        "system_status_supported": True,
        "system_status_range": [417, 499],
        "snapshot_supported": True,
        "metrics_supported": True,
    },
    "three_phase_storage": {
        "filename": "three_phase_storage.yaml",
        "family": "Three-phase storage inverter",
        "status": "reference-only",
        "supported": False,
        "inventory_ranges": [],
        "settings_supported": False,
        "settings_range": [],
        "extended_settings_range": [],
        "system_status_supported": False,
        "system_status_range": [],
        "snapshot_supported": False,
        "metrics_supported": False,
    },
}


def list_profiles():
    """Return protocol profile metadata in stable name order."""
    result = []

    for name in sorted(PROFILE_DEFINITIONS):
        item = dict(PROFILE_DEFINITIONS[name])
        item["name"] = name
        result.append(item)

    return result


def get_profile(name):
    """Return one known profile definition or raise a clear error."""
    if not name:
        name = DEFAULT_PROFILE

    profile = PROFILE_DEFINITIONS.get(name)

    if profile is None:
        raise ValueError(
            "Unknown protocol profile '{}'. Available profiles: {}".format(
                name,
                ", ".join(sorted(PROFILE_DEFINITIONS))
            )
        )

    result = dict(profile)
    result["name"] = name
    return result


def get_profile_path(name, profiles_dir=PROFILES_DIR):
    """Resolve a supported profile to its YAML path."""
    profile = get_profile(name)

    if not profile["supported"]:
        raise ValueError(
            "Protocol profile '{}' is {} and cannot be used for runtime "
            "polling yet.".format(
                name,
                profile["status"]
            )
        )

    return os.path.join(profiles_dir, profile["filename"])


def resolve_registers_source(
        config,
        cli_registers=None,
        cli_profile=None,
        profiles_dir=PROFILES_DIR,
        legacy_default=REGISTERS_FILE):
    """Resolve the register map while preserving legacy configuration.

    Precedence:
      1. --registers explicit file
      2. --profile explicit profile
      3. PROFILE from config
      4. REGISTERS_FILE from config
      5. legacy default /etc/deye-agent/registers.yaml

    Returns:
        (registers_file, profile_name_or_none, source_name)
    """
    if cli_registers:
        return cli_registers, None, "cli-registers"

    if cli_profile:
        return (
            get_profile_path(cli_profile, profiles_dir),
            cli_profile,
            "cli-profile"
        )

    config_profile = str(config.get("PROFILE", "")).strip()
    if config_profile:
        return (
            get_profile_path(config_profile, profiles_dir),
            config_profile,
            "config-profile"
        )

    config_registers = str(config.get("REGISTERS_FILE", "")).strip()
    if config_registers:
        return config_registers, None, "config-registers"

    return legacy_default, None, "legacy-default"
