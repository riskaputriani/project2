"""Minimal Camoufox addon writer that stores scripts inside the workspace."""

import hashlib
import json
from pathlib import Path
from typing import List

import aiofiles

LOCAL_ADDON_DIR = Path(__file__).resolve().parent / "addon"
LOCAL_SCRIPTS_DIR = LOCAL_ADDON_DIR / "scripts"


def _ensure_dirs() -> None:
    LOCAL_SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)


def get_addon_path() -> str:
    """Return the local addon path that Camoufox should load."""
    _ensure_dirs()
    return str(LOCAL_ADDON_DIR.resolve())


async def add_init_script(js_script_string: str, addon_path: str | Path | None = None) -> str:
    """Save JavaScript snippets to the workspace addon so they can be injected later."""

    addon_path = Path(addon_path) if addon_path else LOCAL_ADDON_DIR
    scripts_dir = addon_path / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    script_hash = hashlib.md5(js_script_string.encode("utf-8")).hexdigest()
    script_filename = f"script_{script_hash}.js"
    script_path = scripts_dir / script_filename

    async with aiofiles.open(script_path, "w", encoding="utf-8") as handle:
        await handle.write(js_script_string)

    registry_path = scripts_dir / "registry.json"
    registry: List[str] = []

    if registry_path.exists():
        async with aiofiles.open(registry_path, "r", encoding="utf-8") as handle:
            payload = await handle.read()
            registry = json.loads(payload) if payload else []

    if script_filename not in registry:
        registry.append(script_filename)

    async with aiofiles.open(registry_path, "w", encoding="utf-8") as handle:
        await handle.write(json.dumps(registry, indent=2))

    return script_filename


def clean_scripts(addon_path: str | Path | None = None) -> None:
    """Remove locally stored scripts so the registry can refresh."""

    addon_path = Path(addon_path) if addon_path else LOCAL_ADDON_DIR
    scripts_dir = addon_path / "scripts"
    if not scripts_dir.exists():
        return

    for child in scripts_dir.iterdir():
        if child.is_file():
            child.unlink(missing_ok=True)
