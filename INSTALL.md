# Bot Store Management — Windows Installation Guide

## Requirements

- Windows 10 or later
- Internet connection during first-time setup

---

## Step 1 — Install Python

1. Go to: **https://www.python.org/downloads/windows/**
2. Click the yellow **"Download Python 3.x.x"** button at the top
3. Run the downloaded installer
4. **Important:** Check the box **"Add python.exe to PATH"** before clicking Install

> pip is included automatically with the standard Python installer — no extra steps needed.

---

## Step 2 — First-time Setup

1. Open the `bot-store-management\` folder
2. **Double-click `install.bat`**
3. Wait for the installation to finish (requires internet, takes about 2–5 minutes)

When you see **"Setup complete!"** you are ready to go.

---

## Step 3 — Run the Bot

Each time you want to use the bot:

1. **Double-click `run.bat`**
2. Follow the on-screen prompts to select a feature and campaign

---

## Configuration (`config.yaml`)

Open `config.yaml` with Notepad to adjust settings:

| Key | Description |
|-----|-------------|
| `credentials.username` | Login phone number |
| `credentials.password` | Login password |
| `headless` | `false` = show browser, `true` = run hidden |
| `debug.keep_open` | `true` = keep browser open after the bot finishes |
| `keywords.pickup` | Vietnamese phrases in order notes indicating in-store pickup |

---

## Output Files

All output files are saved in the `data\` folder:

| File | Contents |
|------|----------|
| `orders_*.csv` | Collected order list |
| `actions_*.csv` | Bot action audit log |
| `error\` | Screenshots and error logs (if any failures occur) |

---

## Troubleshooting

**"Python not found"**
→ Make sure you checked **"Add python.exe to PATH"** during installation. If not, uninstall Python and reinstall with that option enabled.

**"Dependency installation failed"**
→ Check your internet connection and run `install.bat` again.

**Browser does not open**
→ Run `install.bat` again to reinstall Chromium.

**Bot stops mid-run and there are files in `data\error\`**
→ Open the `.png` screenshot or `.log` file inside `data\error\` to see the error details.
