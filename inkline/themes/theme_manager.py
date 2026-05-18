from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Theme:
    name: str
    bg: str
    fg: str
    sidebar_bg: str
    panel_bg: str
    accent: str
    muted: str
    cursor: str


THEMES: dict[str, Theme] = {
    "Light": Theme("Light", "#f4f4f4", "#111111", "#e8e8e8", "#ffffff", "#0078d4", "#666666", "#111111"),
    "Dark": Theme("Dark", "#202124", "#f0f0f0", "#2b2d31", "#25262a", "#4f9cff", "#a9a9a9", "#f0f0f0"),
    "AMOLED": Theme("AMOLED", "#000000", "#eaeaea", "#070707", "#0f0f0f", "#4f9cff", "#888888", "#ffffff"),
    "Neon Purple": Theme("Neon Purple", "#190a26", "#f8e9ff", "#2b123f", "#33144a", "#ff4fe1", "#b98ac6", "#ff79ea"),
    "Ocean Blue": Theme("Ocean Blue", "#102235", "#e6f4ff", "#163049", "#1b3a57", "#4ec2ff", "#9dc8e8", "#d7f0ff"),
    "Retro Terminal": Theme("Retro Terminal", "#000c00", "#60ff60", "#001300", "#001a00", "#0fff0f", "#2ea82e", "#60ff60"),
}


class ThemeManager:
    def __init__(self, settings: dict):
        self.settings = settings

    def current(self) -> Theme:
        return THEMES.get(self.settings.get("theme", "Dark"), THEMES["Dark"])

    def set_theme(self, name: str) -> Theme:
        if name in THEMES:
            self.settings["theme"] = name
        return self.current()

    def set_accent(self, accent: str) -> Theme:
        theme = self.current()
        theme.accent = accent
        self.settings["accent"] = accent
        return theme
