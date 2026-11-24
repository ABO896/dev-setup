# dev-setup

A C/C++ setup for the [Zed](https://zed.dev) editor on **macOS** and **Windows**:
one command (or a wizard inside Zed) creates a CMake project with code intelligence,
linting, formatting, sanitizers and debugging already wired up.

## What's here

| File | What it does |
|---|---|
| `new-cpp` | Creates a project: `CMakeLists.txt` (auto-collects `src/`, strict warnings, ASan/UBSan in debug), `CMakePresets.json` (debug / release / lint / test), `.clangd`, `.clang-tidy`, `.clang-format`, and Zed tasks + a CodeLLDB debug config. Run with no arguments for an interactive wizard. |
| `zed/tasks.mac.json`, `zed/tasks.windows.json` | Global Zed tasks: the new-project wizard (+ "run current file" for single C/C++ files on Mac). |
| `install.py` | Puts the files above in place. Never touches Zed's `settings.json`. |

## 1. Install the toolchain

**macOS (Apple Silicon)**
```sh
xcode-select --install
brew install llvm cmake ninja
```
Then put Homebrew's LLVM on your PATH. In fish: `fish_add_path /opt/homebrew/opt/llvm/bin`.
In zsh: add `export PATH="/opt/homebrew/opt/llvm/bin:$PATH"` to `~/.zshrc`.

**Windows (x64)**, in PowerShell:
```powershell
winget install -e --id ZedIndustries.Zed
winget install -e --id MartinStorsjo.LLVM-MinGW.UCRT
winget install -e --id Kitware.CMake
winget install -e --id Ninja-build.Ninja
winget install -e --id Git.Git
winget install -e --id Python.Python.3.13
winget install -e --id Microsoft.PowerShell
```
llvm-mingw provides clang, clangd, clang-tidy and lldb; PowerShell 7 is needed because
the generated tasks chain commands with `&&`.

## 2. Install this repo

```sh
git clone https://github.com/<owner>/dev-setup.git ~/dev-setup
cd ~/dev-setup
python3 install.py          # Windows: python install.py   (in pwsh)
```

Then, once:
- **Mac:** make sure `~/.local/bin` is on your PATH (fish: `fish_add_path ~/.local/bin`).
- **Windows:** add the `new-cpp` command to PowerShell:
  ```powershell
  if (!(Test-Path $PROFILE)) { New-Item -ItemType File -Force $PROFILE | Out-Null }
  Add-Content $PROFILE 'function new-cpp { python "$HOME\.local\bin\new-cpp" @args }'
  ```

## 3. Zed settings (add by hand)

Settings aren't installed, since they're personal. These are the C/C++ parts that matter:

**Mac**
```json
"lsp": { "clangd": { "binary": { "path": "/opt/homebrew/opt/llvm/bin/clangd" } } },
"languages": {
  "C":   { "tab_size": 4, "format_on_save": "on", "language_servers": ["clangd", "!sourcekit-lsp", "..."] },
  "C++": { "tab_size": 4, "format_on_save": "on", "language_servers": ["clangd", "!sourcekit-lsp", "..."] }
}
```
`!sourcekit-lsp` stops a second language server from duplicating every diagnostic.

**Windows**
```json
"languages": {
  "C":   { "tab_size": 4, "format_on_save": "on" },
  "C++": { "tab_size": 4, "format_on_save": "on" }
}
```
No clangd path needed: Zed uses llvm-mingw's clangd from PATH, which survives `winget upgrade`.

## Use

- **New project:** in Zed, `task: spawn` → **C/C++: new project (wizard)**,
  or in a terminal: `new-cpp name --open` (`--lang c`, `--std 23`, `--here`, `--no-git`).
- **In a project:** `task: spawn` → **run (debug)**, **test**, **lint**, **format**, **clean**;
  breakpoints in the gutter, then `debugger: start` → **Debug &lt;name&gt;**.
- **Check clangd sees your headers:** `clangd --check=src/main.cpp`.
- **Existing Makefile project (Mac):** keep the Makefile as is and run
  `brew install bear make`, then `gmake clean; bear -- gmake` to generate the
  `compile_commands.json` clangd needs.

## Notes

- **Windows:** llvm-mingw's runtime DLLs aren't on PATH, so the generated CMake copies
  them next to each `.exe` after every build.
- **Sanitizers:** the debug preset builds with AddressSanitizer + UBSan. LeakSanitizer
  is disabled when running under the debugger (it can't work under ptrace).
- **Updating:** edit files in this repo, commit, `git pull` on other machines. On Windows,
  re-run `python install.py` after pulling. Projects already created don't change.
