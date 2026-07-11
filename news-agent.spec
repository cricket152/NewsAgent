# =============================================================================
# NewsAgent PyInstaller spec
#
# Entry points:
#   - NewsAgent.exe       → news_agent.main:main   (tray + WebView2 GUI)
#   - NewsAgentWorker.exe → news_agent.worker:main  (CLI curator, no GUI)
#
# Mode:        onedir  (fast startup; two EXEs sharing one COLLECT dir)
# Runtime:     Windows x64, WebView2 Evergreen recommended
#              (Evergreen Bootstrapper optional — auto-installed if absent)
#
# Build:       pyinstaller news-agent.spec --noconfirm
# Output:      dist/NewsAgent/
# =============================================================================

import sys

sys.setrecursionlimit(5000)

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# ---------------------------------------------------------------------------
# Project paths  (relative to this spec file's location)
# ---------------------------------------------------------------------------
SPEC_DIR = Path(__file__).parent.resolve()
SRC_DIR = SPEC_DIR / "src"

# Entry-point scripts (absolute)
ENTRY_MAIN = SRC_DIR / "news_agent" / "main.py"
ENTRY_WORKER = SRC_DIR / "news_agent" / "worker.py"

# Data files
TEMPLATE_DAILY = SRC_DIR / "news_agent" / "templates" / "daily.html"
CONFIG_EXAMPLE = SPEC_DIR / "config.yaml.example"

# Executable names (displayed in Task Manager / Explorer)
NAME_MAIN = "NewsAgent"
NAME_WORKER = "NewsAgentWorker"

# ---------------------------------------------------------------------------
# webview  —  collect hooks + explicit WebView2 runtime DLLs
# ---------------------------------------------------------------------------
# collect_all pulls webview's Python modules, data, and binaries.
# However, on some systems the WebView2 native DLLs are missed (Metis
# constraint), so we add them explicitly with Path.exists() guards.
webview_datas, webview_binaries, webview_hidden = collect_all("webview")

# Locate webview package directory dynamically at build time
try:
    import webview

    _WV_DIR = Path(webview.__file__).parent
except ImportError:
    _WV_DIR = None

appended_binaries: list[tuple[str, str]] = []

if _WV_DIR is not None:
    # Microsoft.Web.WebView2.Core.dll — sits directly in webview/lib/
    _wv2_core = _WV_DIR / "lib" / "Microsoft.Web.WebView2.Core.dll"
    if _wv2_core.exists():
        appended_binaries.append((str(_wv2_core), "."))

    # WebView2Loader.dll — architecture-specific, buried in runtimes/
    _wv2_loader = _WV_DIR / "lib" / "runtimes" / "win-x64" / "native" / "WebView2Loader.dll"
    if not _wv2_loader.exists():
        # Fallback: older pywebview layouts
        _wv2_loader = _WV_DIR / "lib" / "win-x64" / "WebView2Loader.dll"
    if _wv2_loader.exists():
        appended_binaries.append((str(_wv2_loader), "."))

    # Additional WinForms interop DLLs (bundled by pywebview on Windows)
    _wf_interop = _WV_DIR / "lib" / "Microsoft.Web.WebView2.WinForms.dll"
    if _wf_interop.exists():
        appended_binaries.append((str(_wf_interop), "."))

# Merge explicit DLLs into the collect_all binaries list
all_webview_binaries = webview_binaries + appended_binaries

# ---------------------------------------------------------------------------
# Shared Analysis kwargs  (used by both Analysis blocks)
# ---------------------------------------------------------------------------
_SHARED_KW = dict(
    pathex=[str(SRC_DIR)],
    hiddenimports=[
        # pythonnet / WinForms backend for pywebview on Windows
        "clr",
        "webview.platforms.winforms",
        # pystray Windows backend
        "pystray._win32",
        # Pillow (PIL) — tray icon rendering
        "PIL",
        "PIL.Image",
        # pynput global hotkeys
        "pynput",
        "pynput.keyboard",
        "pynput.keyboard._win32",
    ],
    excludes=[
        # We only use the WinForms backend — exclude all other GUI toolkits
        # to trim the frozen distribution.
        "tkinter",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
    ],
    hookspath=[],
    runtime_hooks=[],
    noarchive=False,
)

# ---------------------------------------------------------------------------
# Datas  —  Jinja2 template + optional config example
# ---------------------------------------------------------------------------
datas_shared: list[tuple[str, str]] = []

if TEMPLATE_DAILY.exists():
    datas_shared.append(
        (str(TEMPLATE_DAILY), "news_agent/templates")
    )

if CONFIG_EXAMPLE.exists():
    datas_shared.append(
        (str(CONFIG_EXAMPLE), ".")
    )

# ---------------------------------------------------------------------------
# Analysis → EXE → COLLECT pipeline
# ---------------------------------------------------------------------------

# --- NewsAgent.exe (GUI tray + WebView2) ---
analysis_main = Analysis(
    [str(ENTRY_MAIN)],
    datas=webview_datas + datas_shared,
    binaries=all_webview_binaries,
    **_SHARED_KW,
)

pyz_main = PYZ(analysis_main.pure)

exe_main = EXE(
    pyz_main,
    analysis_main.scripts,
    [],
    exclude_binaries=True,
    name=NAME_MAIN,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

# --- NewsAgentWorker.exe (CLI curator — no GUI imports) ---
analysis_worker = Analysis(
    [str(ENTRY_WORKER)],
    datas=datas_shared,
    # Worker does not need GUI libs or webview — keep it slim.
    # webview DLLs are irrelevant here; the collector only picks
    # what the worker actually imports.
    **_SHARED_KW,
)

pyz_worker = PYZ(analysis_worker.pure)

exe_worker = EXE(
    pyz_worker,
    analysis_worker.scripts,
    [],
    exclude_binaries=True,
    name=NAME_WORKER,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

# --- Shared COLLECT  (one output dir for both EXEs) ---
coll = COLLECT(
    exe_main,
    analysis_main.binaries,
    analysis_main.datas,
    exe_worker,
    analysis_worker.binaries,
    analysis_worker.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=NAME_MAIN,  # dist/NewsAgent/
)

# =============================================================================
# Build instructions
#
#   python -m pyinstaller news-agent.spec --noconfirm
#
# The frozen distribution lands in:
#
#   dist/NewsAgent/
#   ├── NewsAgent.exe          ← tray + WebView2 GUI
#   ├── NewsAgentWorker.exe    ← CLI curator (run via Task Scheduler)
#   ├── *.dll                  ← Python + WebView2 native DLLs
#   ├── _internal/             ← Python stdlib + site-packages
#   └── news_agent/            ← bundled data files (templates, config)
#
# Optional:  install the WebView2 Evergreen Bootstrapper on target machines
#            if not already present (pywebview auto-prompts for it on first
#            launch, or deploy via "MicrosoftEdgeWebview2Setup.exe").
# =============================================================================
