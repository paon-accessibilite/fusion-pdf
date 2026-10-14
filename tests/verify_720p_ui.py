"""Manual smoke check for the compact 720p layout."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import FusionPdfApp


class Scaled720pApp(FusionPdfApp):
    def winfo_screenwidth(self) -> int:
        return 1093

    def winfo_screenheight(self) -> int:
        return 576

    def _maximize(self) -> None:
        pass


app = Scaled720pApp()
try:
    app.update()
    root_height = app.winfo_height()
    checks = {}
    for name, button in (
        ("fusionner", app.merge_button),
        ("fusionner_et_editer", app.merge_edit_button),
    ):
        bottom = button.winfo_rooty() - app.winfo_rooty() + button.winfo_height()
        checks[name] = button.winfo_ismapped() and 0 <= bottom <= root_height
    print(
        f"COMPACT={app.compact_ui} WINDOW={app.winfo_width()}x{root_height} "
        f"FUSIONNER={checks['fusionner']} EDITER={checks['fusionner_et_editer']}"
    )
    if not all(checks.values()):
        raise SystemExit(1)
finally:
    app.destroy()
