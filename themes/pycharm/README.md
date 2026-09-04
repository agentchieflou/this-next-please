# PyCharm colour schemes

Three editor colour schemes in JetBrains `.icls` format, each read from a screenshot of another editor and
rebuilt for PyCharm's Python attribute keys (`PY.*` inherit from the `DEFAULT_*` roles where PyCharm expects it).

| File | Read from | Ground | Note |
|---|---|---|---|
| `Crimson Studio.icls` | Visual Studio 2022, red colourization | `#400000` | Red ground, so errors underline in yellow and warnings in amber. |
| `Pastel Lavender.icls` | Pastel lavender editor mock-up | `#7D75D1` | Mid-tone ground; the pale frame in the mock-up is a UI theme, not part of an `.icls`. |
| `Canopy.icls` | VS Code over a forest wallpaper | `#1E2822` | Teal keywords, chartreuse functions, bark-tan strings, lime TODOs. |

All three declare `parent_scheme="Darcula"` (light text on a dark or mid ground), set JetBrains Mono 13 pt with
ligatures, and cover editor colours, Python syntax, inspections, debugger, console/ANSI, diff and coverage.

## Install

Settings › Editor › Color Scheme › gear › **Import Scheme…**, or copy the file into the colours folder and
restart PyCharm:

- Windows: `%APPDATA%\JetBrains\PyCharm2025.2\colors\`
- macOS: `~/Library/Application Support/JetBrains/PyCharm2025.2/colors/`
- Linux: `~/.config/JetBrains/PyCharm2025.2/colors/`

An `.icls` governs the editor only. The IDE frame (menus, tool windows, tabs) comes from Settings › Appearance ›
Theme; pair these with the built-in Dark theme, or Light for Pastel Lavender.
