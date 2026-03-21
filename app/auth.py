from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from pathlib import Path

from runtime.process_logger import log_console as _log


def _extract_bearer_from_text(text: str) -> str | None:
    if not text:
        return None

    raw = text.strip().strip('"').strip("'")
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()

    parts = raw.split(".")
    if len(parts) == 3 and all(parts):
        return raw
    return None


def _extract_auth_payload(value):
    """Normalize auth payload from raw string/object to a dict when possible."""
    if value is None:
        return None

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return None
        return _extract_auth_payload(parsed)

    if not isinstance(value, dict):
        return None

    if isinstance(value.get("value"), dict):
        return value["value"]
    return value


def _extract_bearer_from_value(value) -> str | None:
    if value is None:
        return None

    if isinstance(value, str):
        direct = _extract_bearer_from_text(value)
        if direct:
            return direct
        try:
            parsed = json.loads(value)
        except Exception:
            parsed = None
        if parsed is None:
            return None
        return _extract_bearer_from_value(parsed)

    if isinstance(value, dict):
        for candidate_key in ("token", "access_token", "accessToken", "bearer", "jwt", "value"):
            token_candidate = _extract_bearer_from_value(value.get(candidate_key))
            if token_candidate:
                return token_candidate
        return None

    if isinstance(value, list):
        for item in value:
            token_candidate = _extract_bearer_from_value(item)
            if token_candidate:
                return token_candidate

    return None


def _extract_token_metadata(value) -> dict:
    payload = _extract_auth_payload(value) or {}
    token_type = str(payload.get("token_type", "Bearer")).strip() or "Bearer"

    expires_in = payload.get("expires_in")
    try:
        expires_in = int(expires_in) if expires_in is not None else None
    except Exception:
        expires_in = None

    return {
        "token_type": token_type,
        "expires_in_seconds": expires_in,
        "issued_at_raw": str(payload.get(".issued", "")).strip() or None,
        "expires_at_raw": str(payload.get(".expires", "")).strip() or None,
        "has_refresh_token": bool(payload.get("refresh_token")),
    }


def _decode_jwt_exp(token: str) -> int | None:
    try:
        payload_b64 = token.split(".")[1]
        padding = "=" * ((4 - len(payload_b64) % 4) % 4)
        payload_json = base64.urlsafe_b64decode(payload_b64 + padding).decode("utf-8")
        payload = json.loads(payload_json)
        exp = payload.get("exp")
        return int(exp) if exp is not None else None
    except Exception:
        return None


def _parse_datetime_to_utc(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None

    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _saved_token_expiry_unix(payload: dict, token: str) -> int | None:
    expires_at_unix = payload.get("expires_at_unix")
    try:
        if expires_at_unix is not None:
            return int(expires_at_unix)
    except Exception:
        pass

    jwt_exp = _decode_jwt_exp(token)
    if jwt_exp is not None:
        return int(jwt_exp)

    expires_raw = _parse_datetime_to_utc(str(payload.get("expires_at_raw", "")))
    if expires_raw is not None:
        return int(expires_raw.timestamp())

    captured_at = _parse_datetime_to_utc(str(payload.get("captured_at", "")))
    expires_in = payload.get("expires_in_seconds")
    try:
        expires_in = int(expires_in) if expires_in is not None else None
    except Exception:
        expires_in = None
    if captured_at is not None and expires_in is not None:
        return int(captured_at.timestamp()) + max(0, expires_in)

    return None


def _is_saved_token_expired(payload: dict, token: str, skew_seconds: int = 60) -> bool:
    expiry_unix = _saved_token_expiry_unix(payload, token)
    if expiry_unix is None:
        return False
    now_unix = int(datetime.now(timezone.utc).timestamp())
    return now_unix >= (expiry_unix - max(0, skew_seconds))


def _token_file_from_config(config: dict, base_dir: Path) -> Path:
    auth_cfg = config.get("auth", {})
    token_file_raw = str(auth_cfg.get("token_file", "data/auth_token.json"))
    token_path = Path(token_file_raw)
    if not token_path.is_absolute():
        token_path = base_dir / token_path
    return token_path


def _clear_saved_token_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        path.unlink()
    except Exception:
        try:
            path.write_text("", encoding="utf-8")
        except Exception:
            pass


def _load_saved_access_token(config: dict, base_dir: Path) -> tuple[str | None, dict, str]:
    token_path = _token_file_from_config(config, base_dir)

    if not token_path.exists() or token_path.stat().st_size == 0:
        return None, {}, "missing"

    try:
        payload = json.loads(token_path.read_text(encoding="utf-8"))
    except Exception:
        return None, {}, "invalid"

    if not isinstance(payload, dict):
        return None, {}, "invalid"

    token = _extract_bearer_from_value(payload.get("access_token"))
    if not token:
        return None, payload, "invalid"

    if _is_saved_token_expired(payload, token):
        _clear_saved_token_file(token_path)
        _log("Saved token is expired; token file was cleared.")
        return None, payload, "expired"

    return token, payload, "ok"


def _seed_token_in_browser_storage(page, config: dict, token: str, token_meta: dict | None = None) -> None:
    auth_cfg = config.get("auth", {})
    token_key = str(auth_cfg.get("indexeddb_token_key", "TpageBearerToken")).strip() or "TpageBearerToken"

    expires_in = None
    if token_meta and token_meta.get("expires_in_seconds") is not None:
        try:
            expires_in = int(token_meta.get("expires_in_seconds"))
        except Exception:
            expires_in = None

    envelope = {
        "date": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "value": {
            "access_token": token,
            "token_type": str(token_meta.get("token_type", "bearer")) if token_meta else "bearer",
            "expires_in": expires_in,
        },
    }

    page.evaluate(
        """
        async ({ tokenKey, envelope, token }) => {
          const rawEnvelope = JSON.stringify(envelope);

          try { window.localStorage.setItem(tokenKey, rawEnvelope); } catch (_) {}
          try { window.sessionStorage.setItem(tokenKey, rawEnvelope); } catch (_) {}
          try { window.localStorage.setItem("Authorization", `Bearer ${token}`); } catch (_) {}
          try { window.sessionStorage.setItem("Authorization", `Bearer ${token}`); } catch (_) {}

          if (!window.indexedDB) {
            return;
          }

          const dbInfos = indexedDB.databases ? await indexedDB.databases() : [];
          const fallbackNames = ["localforage", "keyval-store", "tpage", "tpos", "app-db"];
          const dbNames = new Set([...(dbInfos || []).map((x) => x.name).filter(Boolean), ...fallbackNames]);

          const openDb = (name) => new Promise((resolve) => {
            try {
              const req = indexedDB.open(name);
              req.onsuccess = () => resolve(req.result);
              req.onerror = () => resolve(null);
              req.onblocked = () => resolve(null);
            } catch (_) {
              resolve(null);
            }
          });

          const putByKey = (db, storeName, key, value) => new Promise((resolve) => {
            try {
              const tx = db.transaction(storeName, "readwrite");
              const store = tx.objectStore(storeName);
              const req = store.put(value, key);
              req.onsuccess = () => resolve(true);
              req.onerror = () => resolve(false);
            } catch (_) {
              resolve(false);
            }
          });

          for (const dbName of dbNames) {
            const db = await openDb(dbName);
            if (!db) {
              continue;
            }
            try {
              const stores = Array.from(db.objectStoreNames || []);
              for (const storeName of stores) {
                await putByKey(db, storeName, tokenKey, envelope);
                await putByKey(db, storeName, tokenKey, rawEnvelope);
              }
            } finally {
              db.close();
            }
          }
        }
        """,
        {"tokenKey": token_key, "envelope": envelope, "token": token},
    )


def _capture_bearer_from_indexeddb(page, token_key: str) -> tuple[str | None, str | None, dict]:
    records = page.evaluate(
        """
        async ({ tokenKey }) => {
          if (!window.indexedDB) {
            return [];
          }

          const openDb = (name) => new Promise((resolve) => {
            try {
              const req = indexedDB.open(name);
              req.onsuccess = () => resolve(req.result);
              req.onerror = () => resolve(null);
              req.onblocked = () => resolve(null);
            } catch (_) {
              resolve(null);
            }
          });

          const getByKey = (db, storeName, key) => new Promise((resolve) => {
            try {
              const tx = db.transaction(storeName, "readonly");
              const store = tx.objectStore(storeName);
              const req = store.get(key);
              req.onsuccess = () => resolve(req.result);
              req.onerror = () => resolve(undefined);
            } catch (_) {
              resolve(undefined);
            }
          });

          const scanByCursor = (db, storeName, lookupKey) => new Promise((resolve) => {
            const found = [];
            try {
              const tx = db.transaction(storeName, "readonly");
              const store = tx.objectStore(storeName);
              const req = store.openCursor();
              req.onsuccess = (event) => {
                const cursor = event.target.result;
                if (!cursor) {
                  resolve(found);
                  return;
                }
                const keyText = String(cursor.key || "");
                if (keyText.toLowerCase().includes(String(lookupKey || "").toLowerCase())) {
                  found.push({ dbName: db.name, storeName, key: keyText, value: cursor.value });
                }
                cursor.continue();
              };
              req.onerror = () => resolve(found);
            } catch (_) {
              resolve(found);
            }
          });

          let dbNames = [];
          if (indexedDB.databases) {
            try {
              const infos = await indexedDB.databases();
              dbNames = infos.map((x) => x.name).filter(Boolean);
            } catch (_) {
              dbNames = [];
            }
          }

          const fallbackNames = ["localforage", "keyval-store", "tpage", "tpos", "app-db"];
          const seen = new Set();
          for (const name of [...dbNames, ...fallbackNames]) {
            if (name && !seen.has(name)) {
              seen.add(name);
            }
          }

          const results = [];
          for (const dbName of Array.from(seen)) {
            const db = await openDb(dbName);
            if (!db) {
              continue;
            }

            try {
              const stores = Array.from(db.objectStoreNames || []);
              for (const storeName of stores) {
                const direct = await getByKey(db, storeName, tokenKey);
                if (direct !== undefined && direct !== null) {
                  results.push({ dbName, storeName, key: tokenKey, value: direct });
                }

                const cursorMatches = await scanByCursor(db, storeName, tokenKey);
                for (const item of cursorMatches) {
                  results.push(item);
                }
              }
            } finally {
              db.close();
            }
          }

          return results;
        }
        """,
        {"tokenKey": token_key},
    )

    for item in records:
        token = _extract_bearer_from_value(item.get("value"))
        if token:
            source = f"indexedDB:{item.get('dbName', 'unknown')}/{item.get('storeName', 'unknown')}/{item.get('key', token_key)}"
            return token, source, _extract_token_metadata(item.get("value"))

    return None, None, {}


def capture_bearer_token(page, config: dict) -> tuple[str | None, str | None, dict]:
    storage_items = page.evaluate(
        """
        () => {
          const dump = (storage, scope) => {
            const out = [];
            for (let i = 0; i < storage.length; i++) {
              const key = storage.key(i);
              out.push({ scope, key, value: storage.getItem(key) || "" });
            }
            return out;
          };
          return [...dump(window.localStorage, "localStorage"), ...dump(window.sessionStorage, "sessionStorage")];
        }
        """
    )

    for item in storage_items:
        value = str(item.get("value", ""))
        direct = _extract_bearer_from_value(value)
        if direct:
            return direct, str(item.get("key", "")), _extract_token_metadata(value)

    token_key = str(config.get("auth", {}).get("indexeddb_token_key", "TpageBearerToken"))
    return _capture_bearer_from_indexeddb(page, token_key)


def save_auth_token(token: str, source_key: str | None, config: dict, base_dir: Path, metadata: dict | None = None) -> Path:
    auth_cfg = config.get("auth", {})
    token_file_raw = auth_cfg.get("token_file", "data/auth_token.json")
    token_path = Path(token_file_raw)
    if not token_path.is_absolute():
        token_path = base_dir / token_path
    token_path.parent.mkdir(parents=True, exist_ok=True)

    now_iso = datetime.now().isoformat()
    safe_meta = metadata or {}
    payload = {
        "token_type": str(safe_meta.get("token_type", "Bearer")),
        "access_token": token,
        "captured_at": now_iso,
        "source_key": source_key or "unknown",
        "expires_at_unix": _decode_jwt_exp(token),
        "token_fingerprint": sha256(token.encode("utf-8")).hexdigest()[:16],
        "expires_in_seconds": safe_meta.get("expires_in_seconds"),
        "issued_at_raw": safe_meta.get("issued_at_raw"),
        "expires_at_raw": safe_meta.get("expires_at_raw"),
        "has_refresh_token": bool(safe_meta.get("has_refresh_token")),
    }
    token_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return token_path


def capture_and_save_auth_token(page, config: dict, base_dir: Path, log_action) -> None:
    auth_cfg = config.get("auth", {})
    if not bool(auth_cfg.get("capture_enabled", True)):
        return

    token, source, metadata = capture_bearer_token(page, config)

    if not token:
        dashboard_url = str(auth_cfg.get("dashboard_url", "")).strip()
        if dashboard_url:
            page.goto(dashboard_url)
            page.wait_for_load_state("networkidle")
            token, source, metadata = capture_bearer_token(page, config)

    if token:
        saved_path = save_auth_token(token, source, config, base_dir=base_dir, metadata=metadata)
        log_action("auth", "capture_token", "ok", f"saved token metadata to {saved_path.name}")
    else:
        log_action("auth", "capture_token", "warning", "bearer token not found in browser storage")

