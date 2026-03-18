from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable


def log_console(message: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(f"[{ts}] {message}")


def append_error_log(error_dir: Path, error_log_file: Path, context: str, exc: Exception) -> None:
    error_dir.mkdir(parents=True, exist_ok=True)
    trace = traceback.format_exc().strip()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    with error_log_file.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {context}\n")
        f.write(f"error={repr(exc)}\n")
        if trace:
            f.write(trace)
            f.write("\n")
        f.write("-" * 80)
        f.write("\n")


def is_target_closed_error(exc: Exception) -> bool:
    return "Target page, context or browser has been closed" in str(exc)


def build_exception_logger(error_dir: Path, error_log_file: Path, logger: Callable[[str], None]) -> Callable[[str, Exception], None]:
    def _log_exception_trace(context: str, exc: Exception) -> None:
        logger(f"[ERROR] {context}: {exc}")
        trace = traceback.format_exc().strip()
        if trace:
            print(trace)
        append_error_log(error_dir, error_log_file, context, exc)
        logger(f"[ERROR] Error detail appended: {error_log_file.resolve()}")

    return _log_exception_trace


def safe_close(resource, name: str, logger: Callable[[str], None]) -> None:
    if resource is None:
        return
    try:
        resource.close()
        logger(f"[SHUTDOWN] Closed {name}")
    except Exception as exc:
        logger(f"[SHUTDOWN] Skip closing {name}: {exc}")


def keep_browser_open_for_debug(
    page,
    config: dict,
    reason: str,
    logger: Callable[[str], None],
    log_exception_trace: Callable[[str, Exception], None],
) -> None:
    debug_cfg = config.get("debug", {})
    keep_open = bool(debug_cfg.get("keep_open", True))
    keep_open_seconds = int(debug_cfg.get("keep_open_seconds", 120))
    if not keep_open or keep_open_seconds <= 0:
        return

    try:
        if page is None or page.is_closed():
            logger("[SHUTDOWN] Skip keep-open: page is already closed")
            return

        print(f"{reason}. Keeping browser open for {keep_open_seconds}s...")
        page.wait_for_timeout(keep_open_seconds * 1000)
    except Exception as exc:
        if is_target_closed_error(exc):
            logger("[SHUTDOWN] Skip keep-open: browser/page/context already closed")
            return
        log_exception_trace("keep_browser_open_for_debug", exc)


def flush_stdio() -> None:
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass

