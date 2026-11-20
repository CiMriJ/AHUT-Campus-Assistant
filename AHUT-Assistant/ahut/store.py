"""本地持久化：配置、登录 Cookie、数据缓存、密码加密。"""
import json
import os
import time
from pathlib import Path

from cryptography.fernet import Fernet


def _data_dir() -> Path:
    env_dir = os.environ.get("AHUT_DATA_DIR")
    if env_dir:
        d = Path(env_dir)
    elif os.name == "nt" or os.environ.get("LOCALAPPDATA"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        d = Path(base) / "AHUT-Assistant"
    else:
        # Android / Linux：用隐藏目录，避免和项目目录重名
        d = Path(os.path.expanduser("~")) / ".ahut-assistant"
    d.mkdir(parents=True, exist_ok=True)
    return d


DATA_DIR = _data_dir()
CONFIG_FILE = DATA_DIR / "config.json"
COOKIE_FILE = DATA_DIR / "cookies.json"
CACHE_FILE = DATA_DIR / "cache.json"
KEY_FILE = DATA_DIR / "secret.key"
DEBUG_DIR = DATA_DIR / "debug"

DEFAULT_CONFIG = {
    "username": "",
    "password_enc": "",
    "remember_password": False,
    "term_start": "",          # 本学期第一周周一，格式 YYYY-MM-DD
    "semester": "",            # 形如 2026-2027-1
    "total_weeks": 20,
}


def _read_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(default, dict):
            merged = dict(default)
            merged.update(data)
            return merged
        return data
    except Exception:
        return default


def _write_json(path: Path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_config() -> dict:
    return _read_json(CONFIG_FILE, DEFAULT_CONFIG)


def save_config(cfg: dict):
    _write_json(CONFIG_FILE, cfg)


def save_cookies(jar) -> None:
    cookies = []
    for c in jar:
        cookies.append({
            "name": c.name, "value": c.value, "domain": c.domain,
            "path": c.path, "secure": c.secure,
            "expires": c.expires,
        })
    _write_json(COOKIE_FILE, cookies)


def load_cookies() -> list:
    return _read_json(COOKIE_FILE, [])


def clear_cookies():
    try:
        COOKIE_FILE.unlink()
    except FileNotFoundError:
        pass


def save_cache(data: dict):
    _write_json(CACHE_FILE, {"ts": time.time(), "data": data})


def load_cache() -> tuple:
    raw = _read_json(CACHE_FILE, {})
    if not raw or "data" not in raw:
        return {}, 0
    return raw.get("data", {}), raw.get("ts", 0)


# ---------- 密码加密存储 ----------

def _fernet() -> Fernet:
    if not KEY_FILE.exists():
        KEY_FILE.write_bytes(Fernet.generate_key())
        try:
            os.chmod(KEY_FILE, 0o600)
        except Exception:
            pass
    return Fernet(KEY_FILE.read_bytes())


def encrypt_password(password: str) -> str:
    if not password:
        return ""
    return _fernet().encrypt(password.encode("utf-8")).decode()


def decrypt_password(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except Exception:
        return ""
