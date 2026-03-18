from __future__ import annotations

import json
from pathlib import Path
from time import monotonic

from .auth import _load_saved_access_token, _seed_token_in_browser_storage

LOGIN_WAIT_TIMEOUT_SECONDS = 300


def is_login_page(page) -> bool:
	if "login" in page.url.lower():
		return True
	return page.locator("input[type='password']").count() > 0


def wait_until_logged_in(page, timeout_seconds: int = LOGIN_WAIT_TIMEOUT_SECONDS) -> bool:
	deadline = monotonic() + timeout_seconds
	while monotonic() < deadline:
		if not is_login_page(page):
			return True
		page.wait_for_timeout(1000)
	return False


def _first_existing(page, selectors: list[str]):
	for selector in selectors:
		locator = page.locator(selector).first
		if locator.count() > 0:
			return locator
	return None


def _fill_input(locator, value: str) -> bool:
	try:
		locator.click(timeout=2000)
		locator.fill("")
		locator.fill(value, timeout=3000)
		if locator.input_value().strip() == value:
			return True

		# Fallback for pages that ignore fill() during hydration.
		locator.fill("")
		locator.type(value, delay=40)
		return locator.input_value().strip() == value
	except Exception:
		return False


def try_auto_login(page, config: dict) -> bool:
	username = config.get("credentials", {}).get("username", "").strip()
	password = config.get("credentials", {}).get("password", "").strip()
	if not username or not password:
		return False

	try:
		page.wait_for_selector("input[formcontrolname='UserName'], #tds-input-0", timeout=8000)
	except Exception:
		pass

	username_input = _first_existing(page, [
		"input[formcontrolname='UserName']:visible",
		"input[placeholder='Nhập tài khoản']:visible",
		"#tds-input-0:visible",
		"input[formcontrolname='UserName']",
		"input[placeholder='Nhập tài khoản']",
		"#tds-input-0",
		"input[name='username']",
		"input[name='email']",
		"input[type='email']",
		"input[autocomplete='username']",
	])
	password_input = _first_existing(page, [
		"input[formcontrolname='Password']:visible",
		"input[placeholder='Nhập mật khẩu']:visible",
		"#tds-input-1:visible",
		"input[formcontrolname='Password']",
		"input[placeholder='Nhập mật khẩu']",
		"#tds-input-1",
		"input[name='password']",
		"input[type='password']",
		"input[autocomplete='current-password']",
	])

	if not username_input or not password_input:
		print("Auto-login: username/password input not found.")
		return False

	if not _fill_input(username_input, username):
		print("Auto-login: failed to fill username.")
		return False

	if not _fill_input(password_input, password):
		print("Auto-login: failed to fill password.")
		return False

	submit_button = _first_existing(page, [
		"button:has(div:has-text('Đăng nhập'))",
		"button:has-text('Đăng nhập')",
		"[role='button']:has-text('Đăng nhập')",
		"div[role='button']:has-text('Đăng nhập')",
		"div.flex:has-text('Đăng nhập')",
		"button:has-text('Dang nhap')",
		"button:has-text('Login')",
		"button[type='submit']",
		"text=Đăng nhập",
	])
	if not submit_button:
		print("Auto-login: submit button not found.")
		return False

	try:
		submit_button.click(timeout=4000)
	except Exception:
		submit_button.click(force=True)
	page.wait_for_timeout(3000)
	return not is_login_page(page)


def try_login_with_saved_token(page, config: dict, base_dir: Path, log_console) -> bool:
	auth_cfg = config.get("auth", {})
	if not bool(auth_cfg.get("bootstrap_from_token", True)):
		return False

	token, token_meta, token_state = _load_saved_access_token(config, base_dir)
	if token_state == "expired":
		return False
	if not token:
		return False

	base_url = str(config.get("base_url", "")).rstrip("/")
	dashboard_url = str(auth_cfg.get("dashboard_url", "")).strip() or f"{base_url}/#/dashboard"

	log_console(f"[NAV] Open base page: {base_url}")
	page.goto(base_url)
	page.wait_for_load_state("domcontentloaded")
	_seed_token_in_browser_storage(page, config, token, token_meta)

	log_console(f"[NAV] Open dashboard page: {dashboard_url}")
	page.goto(dashboard_url)
	page.wait_for_load_state("domcontentloaded")
	page.wait_for_timeout(1500)
	ok = not is_login_page(page)
	log_console(f"[NAV] Dashboard check after token login: {'ok' if ok else 'redirected to login'} | current={page.url}")
	return ok


def ensure_login(context, page, config: dict, base_dir: Path, session_file: Path, log_console) -> bool:
	base_url = config.get("base_url", "").rstrip("/")
	login_url = str(config.get("auth", {}).get("login_url", "")).strip()
	dashboard_url = str(config.get("auth", {}).get("dashboard_url", "")).strip()
	if try_login_with_saved_token(page, config, base_dir=base_dir, log_console=log_console):
		log_console(f"[NAV] Login by saved token succeeded. Current page: {page.url}")
		context.storage_state(path=str(session_file))
		return True

	target_url = login_url or dashboard_url or base_url
	log_console(f"[NAV] Open login page: {target_url}")
	page.goto(target_url)
	page.wait_for_load_state("domcontentloaded")
	log_console(f"[NAV] Loaded page: {page.url}")

	if not is_login_page(page):
		log_console(f"[NAV] Already authenticated. Current page: {page.url}")
		return True

	if try_auto_login(page, config) and not is_login_page(page):
		log_console(f"[NAV] Auto-login succeeded. Current page: {page.url}")
		context.storage_state(path=str(session_file))
		return True

	log_console("Login required. Please sign in in the browser; the bot will keep waiting...")
	if not wait_until_logged_in(page):
		return False

	log_console(f"[NAV] Manual login completed. Current page: {page.url}")

	page.wait_for_timeout(1000)
	context.storage_state(path=str(session_file))
	return True


def _is_valid_storage_state_file(path: Path) -> bool:
	if not path.exists() or path.stat().st_size == 0:
		return False

	try:
		payload = json.loads(path.read_text(encoding="utf-8"))
	except Exception:
		return False

	if not isinstance(payload, dict):
		return False

	cookies = payload.get("cookies")
	origins = payload.get("origins")
	return isinstance(cookies, list) and isinstance(origins, list)


def _quarantine_bad_session(path: Path) -> None:
	if not path.exists():
		return
	bad_path = path.with_name(f"{path.stem}.bad{path.suffix}")
	try:
		path.replace(bad_path)
	except Exception:
		# Best effort only; if rename fails we still continue with a fresh context.
		pass


def new_context(browser, session_file: Path):
	if session_file.exists() and _is_valid_storage_state_file(session_file):
		try:
			return browser.new_context(storage_state=str(session_file))
		except Exception as exc:
			print(f"Session restore failed, fallback to new session: {exc}")
			_quarantine_bad_session(session_file)
			return browser.new_context()

	if session_file.exists():
		print("Session file is invalid or empty, starting with a fresh session.")
		_quarantine_bad_session(session_file)

	return browser.new_context()

