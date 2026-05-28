# Installing NADOC — Step by Step

This guide assumes **no prior Linux or command-line experience**. If you can
copy-paste a line and press Enter, you can do this.

NADOC has two pieces that run on your own computer:

- an **engine** (the backend) that does all the DNA-origami math, and
- a **web page** (the frontend) you open in your browser to actually use it.

You install everything **once** with a single command, then start it whenever
you want with a single command. You do **not** need to install Python, Node, or
anything else by hand — the setup script does all of that for you.

There are three short steps:

1. Get your operating system ready (this is the only part that differs per OS).
2. Download NADOC.
3. Run `./setup.sh`, then `./start.sh`.

---

## Step 1 — Get your operating system ready

Pick the section for your computer. **Do only your section**, then jump to Step 2.

### 🪟 Windows

NADOC runs on Windows through **WSL2** — a built-in feature that runs a small
Ubuntu Linux inside Windows. You'll do all NADOC work inside an Ubuntu window.
This is the standard, well-supported way to run scientific software on Windows.

1. Click the Start menu, type **PowerShell**, right-click **Windows PowerShell**,
   and choose **Run as administrator**.
2. In the blue window, type this and press Enter:

   ```powershell
   wsl --install
   ```

   This installs WSL2 and Ubuntu. It may take several minutes.
3. **Restart your computer** when it asks.
4. After restart, an **Ubuntu** window opens automatically (if not, open the
   Start menu and click **Ubuntu**). The first time, it asks you to create a
   username and password — pick anything and **remember the password** (you'll
   type it occasionally; the screen stays blank while you type — that's normal).

You now have an **Ubuntu terminal**. Every NADOC command from here on goes in
**this Ubuntu window**, *not* PowerShell.

Install git (used to download NADOC) by pasting this and pressing Enter:

```bash
sudo apt update && sudo apt install -y git
```

(It will ask for the password you just created.)

➡️ Now continue to **Step 2**. Everything else is the same as Linux.

> If `wsl --install` says it's not recognized, your Windows is too old. Update
> Windows (Settings → Windows Update), or see Microsoft's WSL install guide:
> https://learn.microsoft.com/windows/wsl/install

### 🍎 macOS

1. Open the **Terminal** app (press ⌘-Space, type "Terminal", press Enter).
2. Install Apple's command-line tools (this gives you `git`). Paste and press Enter:

   ```bash
   xcode-select --install
   ```

   A dialog pops up — click **Install** and wait for it to finish. (If it says
   the tools are already installed, great — skip it.)

That's all. The setup script installs everything else (including Homebrew).

➡️ Continue to **Step 2**.

### 🐧 Linux

Open your **Terminal** and make sure `git` and `curl` are present:

```bash
sudo apt update && sudo apt install -y git curl
```

(On Fedora/Arch use `dnf`/`pacman` instead of `apt`.)

➡️ Continue to **Step 2**.

---

## Step 2 — Download NADOC

In your terminal (the **Ubuntu** window on Windows), paste these one at a time:

```bash
cd ~
git clone https://github.com/DNA-origamicon/NADOC.git
cd NADOC
```

This downloads NADOC into a folder called `NADOC` in your home directory and
moves you into it.

> **Windows note:** cloning into `~` (your Linux home) is important — it runs
> much faster than the Windows `C:` drive. Stay inside the Ubuntu window.

---

## Step 3 — Install and run

### Install everything (once)

```bash
./setup.sh
```

This installs `uv` (a Python manager), Node.js, and `just`, then sets up a
private Python environment and installs every dependency. **It can take several
minutes** the first time — that's normal. It's safe to run again if anything
gets interrupted.

> If you see `permission denied`, run `chmod +x setup.sh start.sh` once, then
> retry `./setup.sh`.

### Start NADOC

```bash
./start.sh
```

Leave this window open — it's running the app. After a few seconds, open your
web browser and go to:

**http://localhost:5173**

To **stop** NADOC, click the terminal window and press **Ctrl-C**.

---

## Step 4 — Try it out

Once the page loads, open one of the included example designs to confirm
everything works: click **File → Open File…** in the top menu and pick a file
from the `Examples/` folder, e.g. `Examples/6hb_test.nadoc` or
`Examples/multi_domain_test.nadoc`. You should see a 3D DNA-origami structure.

---

## Starting it again next time

You only run `./setup.sh` once. After that, every time you want to use NADOC:

```bash
cd ~/NADOC
./start.sh
```

then open **http://localhost:5173**.

## Getting the latest version later

```bash
cd ~/NADOC
git pull
./setup.sh      # picks up any new dependencies
```

---

## Troubleshooting

**The browser page won't load / "can't connect."**
Give it 10–20 seconds after `./start.sh` — the first launch is slow. Make sure
the `./start.sh` window is still open and didn't show an error. Confirm you used
`http://localhost:5173` (not `https`, not port 8000).

**Windows/WSL2: `localhost:5173` does nothing.**
On older WSL2 versions, `localhost` isn't forwarded. Two options:

- *Quick:* in the Ubuntu window run `ip addr show eth0 | grep 'inet '`, take the
  number after `inet` (e.g. `172.24.31.208`), and open `http://THAT-NUMBER:5173`.
- *Permanent (Windows 11):* create a file `C:\Users\<you>\.wslconfig` containing:

  ```ini
  [wsl2]
  networkingMode=mirrored
  ```

  Then, in PowerShell, run `wsl --shutdown`, reopen Ubuntu, and `localhost` will
  work from then on.

**`command not found: just` (or `uv`).**
The setup added these tools to your account but the current terminal hadn't
picked it up yet. Close the terminal, open a new one, `cd ~/NADOC`, and retry.

**`port 8000` or `5173` already in use.**
NADOC is probably already running in another window. Close that one (Ctrl-C),
or just reuse it.

**`./setup.sh` fails while installing a Python package.**
Re-run `./setup.sh` — transient network errors are common and it resumes safely.
If it keeps failing on the same package, copy the error and send it to Josh.

**Everything is broken and I want a clean slate.**
Delete the project's environment and reinstall:

```bash
cd ~/NADOC
rm -rf .venv frontend/node_modules
./setup.sh
```

---

## What about the heavy simulation features?

Atomistic export, NAMD, GROMACS, and the OpenMM checker need extra external
tools that are **not** required to design origami and try out NADOC. Ignore
them for now — the core app works without them.
