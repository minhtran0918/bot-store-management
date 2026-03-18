"""Interactive CLI menu using InquirerPy with in-place rendering."""
from __future__ import annotations

import os
import sys
from InquirerPy import inquirer
from InquirerPy.separator import Separator

# ANSI
BOLD = "\033[1m"
RESET = "\033[0m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
DIM = "\033[2m"
WHITE = "\033[97m"

# Cursor control
CLEAR_LINE = "\033[2K"
MOVE_UP = "\033[A"

APP_TITLE = "Bot Process Order"

# Track lines printed so we can overwrite
_last_lines = 0


def _width() -> int:
    try:
        return min(os.get_terminal_size().columns, 64)
    except OSError:
        return 64


def _box_line(char_l: str, fill: str, char_r: str, color: str = CYAN) -> str:
    w = _width()
    return f"  {color}{char_l}{fill * (w - 2)}{char_r}{RESET}"


def _box_text(text: str, visible_len: int, color: str = CYAN) -> str:
    w = _width()
    pad = w - 4 - visible_len
    if pad < 0:
        pad = 0
    return f"  {color}|{RESET} {text}{' ' * pad} {color}|{RESET}"


def _clear_last() -> None:
    """Move cursor up and clear all lines from the previous step."""
    global _last_lines
    for _ in range(_last_lines):
        sys.stdout.write(f"{MOVE_UP}{CLEAR_LINE}\r")
    sys.stdout.flush()
    _last_lines = 0


def _print_and_track(*lines: str) -> None:
    """Print lines and track count for later clearing."""
    global _last_lines
    for line in lines:
        print(line)
        _last_lines += 1


def show_banner() -> None:
    """Print the app title banner."""
    global _last_lines
    w = _width()
    inner = w - 4

    title = f">> {APP_TITLE} <<"
    visible_len = len(title)
    left_pad = (inner - visible_len) // 2
    right_pad = inner - visible_len - left_pad

    print()
    print(_box_line("+", "-", "+", CYAN))
    print(f"  {CYAN}|{RESET}{' ' * left_pad}{BOLD}{YELLOW}{title}{RESET}{' ' * right_pad}{CYAN}|{RESET}")
    print(_box_line("+", "-", "+", CYAN))
    print()
    _last_lines = 0  # don't clear the banner


def _show_step_header(step: int, total: int, title: str) -> None:
    """Print a step header line."""
    step_text = f"[{step}/{total}]"
    _print_and_track(f"  {DIM}{step_text}{RESET} {BOLD}{WHITE}{title}{RESET}")


def _show_done_line(step: int, total: int, title: str, value: str) -> None:
    """Print a completed step as a single compact line (not tracked for clearing)."""
    global _last_lines
    step_text = f"[{step}/{total}]"
    print(f"  {GREEN}{step_text}{RESET} {WHITE}{title}:{RESET} {BOLD}{value}{RESET}")
    # don't increment _last_lines — done lines stay permanently


def select(message: str, choices: list[dict], step: int, total: int, default: str | None = None) -> str:
    """Arrow-key select menu with step indicator."""
    _clear_last()
    _show_step_header(step, total, message)
    # InquirerPy prints its own lines — estimate for clearing
    prompt_lines_estimate = len(choices) + 2
    result = inquirer.select(
        message=f" {message}:",
        choices=choices,
        default=default,
        pointer=">",
        show_cursor=False,
        mandatory=True,
    ).execute()
    # After selection, InquirerPy collapses to ~1 line, but we need to clear header + that
    global _last_lines
    _last_lines += 1  # the collapsed prompt line
    _clear_last()
    # Show the permanent done line
    display_value = result
    for c in choices:
        if c.get("value") == result:
            display_value = c.get("name", result)
            break
    _show_done_line(step, total, message, display_value)
    return result


def text_input(message: str, step: int, total: int, default: str = "") -> str:
    """Text input with step indicator."""
    _clear_last()
    _show_step_header(step, total, message)
    result = inquirer.text(message=f" {message}:", default=default).execute().strip()
    global _last_lines
    _last_lines += 1
    _clear_last()
    _show_done_line(step, total, message, result)
    return result


def show_summary(selections: list[tuple[str, str]]) -> None:
    """Print a boxed summary of all selections."""
    w = _width()
    inner = w - 4

    max_label = max(len(label) for label, _ in selections)

    print()
    print(_box_line("+", "-", "+", GREEN))

    title = "[v] Selected Options"
    title_vis = len(title)
    left_pad = (inner - title_vis) // 2
    right_pad = inner - title_vis - left_pad
    print(f"  {GREEN}|{RESET}{' ' * left_pad}{BOLD}{GREEN}{title}{RESET}{' ' * right_pad}{GREEN}|{RESET}")

    print(_box_line("+", "-", "+", GREEN))

    for label, value in selections:
        padded_label = label.ljust(max_label)
        text = f"{WHITE}{padded_label}{RESET}  {BOLD}{value}{RESET}"
        text_vis = max_label + 2 + len(value)
        pad = inner - text_vis - 1
        if pad < 0:
            pad = 0
        print(f"  {GREEN}|{RESET}  {text}{' ' * pad}{GREEN}|{RESET}")

    print(_box_line("+", "-", "+", GREEN))
    print()
