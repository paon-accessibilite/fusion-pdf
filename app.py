from __future__ import annotations

import os
import queue
import tempfile
import threading
import base64
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk
from tkinterdnd2 import DND_FILES, TkinterDnD

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError
import pymupdf


APP_NAME = "Fusion PDF"
CONTACT_EMAIL = "francois.defaye@ac-limoges.fr"
BG = "#F4F6F8"
SURFACE = "#FFFFFF"
INK = "#17202A"
MUTED = "#667085"
ACCENT = "#315EFB"
ACCENT_DARK = "#2449CB"
SUCCESS = "#12805C"
ERROR = "#C43232"
BORDER = "#DDE2E8"


class RoundedButton(tk.Canvas):
    """Small canvas-backed button with rounded corners and ttk-like state methods."""

    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        command: object = None,
        style: str = "Secondary.TButton",
        state: str = "normal",
        width: int | None = None,
        **kwargs: object,
    ) -> None:
        self._text = text
        self._command = command
        self._state = state
        self._primary = style.startswith("Primary")
        self._hovered = False
        self._explicit_width = width
        canvas_bg = self._parent_background(parent)
        height = 40 if self._primary else 36
        computed_width = self._button_width()
        super().__init__(
            parent,
            width=computed_width,
            height=height,
            bg=canvas_bg,
            highlightthickness=0,
            borderwidth=0,
            takefocus=1,
            cursor="hand2" if state != "disabled" else "arrow",
        )
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<Button-1>", self._click)
        self.bind("<Return>", self._click)
        self.bind("<space>", self._click)
        self.bind("<FocusIn>", lambda _e: self._draw(focused=True))
        self.bind("<FocusOut>", lambda _e: self._draw())
        self._draw()

    @staticmethod
    def _parent_background(parent: tk.Misc) -> str:
        for option in ("background", "bg"):
            try:
                value = parent.cget(option)
                if value:
                    return str(value)
            except tk.TclError:
                pass
        try:
            style_name = parent.cget("style")
            value = ttk.Style(parent).lookup(style_name, "background")
            if value:
                return str(value)
        except tk.TclError:
            pass
        return BG

    def _button_width(self) -> int:
        if self._explicit_width is not None:
            return max(34, self._explicit_width)
        return max(72, len(self._text) * 7 + (34 if self._primary else 28))

    def _draw(self, focused: bool = False) -> None:
        self.delete("all")
        width = int(self.cget("width"))
        height = int(self.cget("height"))
        disabled = self._state == "disabled"
        if disabled:
            fill, outline, foreground = "#E5E8EF", "#D6DAE2", "#98A2B3"
        elif self._primary:
            fill = ACCENT_DARK if self._hovered else ACCENT
            outline, foreground = fill, "white"
        else:
            fill = "#EDF1F5" if self._hovered else SURFACE
            outline, foreground = ACCENT if focused else BORDER, INK
        radius = 10
        self._rounded_rectangle(1, 1, width - 1, height - 1, radius, outline)
        self._rounded_rectangle(2, 2, width - 2, height - 2, radius - 1, fill)
        self.create_text(width / 2, height / 2, text=self._text, fill=foreground, font=("Segoe UI Semibold" if self._primary else "Segoe UI", 9))
        super().configure(cursor="arrow" if disabled else "hand2")

    def _rounded_rectangle(self, x1: int, y1: int, x2: int, y2: int, radius: int, fill: str) -> None:
        """Draw a mathematically regular rounded rectangle from four quarter-circles."""
        diameter = radius * 2
        self.create_rectangle(x1 + radius, y1, x2 - radius, y2, fill=fill, outline=fill)
        self.create_rectangle(x1, y1 + radius, x2, y2 - radius, fill=fill, outline=fill)
        self.create_arc(x1, y1, x1 + diameter, y1 + diameter, start=90, extent=90, style="pieslice", fill=fill, outline=fill)
        self.create_arc(x2 - diameter, y1, x2, y1 + diameter, start=0, extent=90, style="pieslice", fill=fill, outline=fill)
        self.create_arc(x1, y2 - diameter, x1 + diameter, y2, start=180, extent=90, style="pieslice", fill=fill, outline=fill)
        self.create_arc(x2 - diameter, y2 - diameter, x2, y2, start=270, extent=90, style="pieslice", fill=fill, outline=fill)

    def _enter(self, _event: object) -> None:
        if self._state != "disabled":
            self._hovered = True
            self._draw()

    def _leave(self, _event: object) -> None:
        self._hovered = False
        self._draw()

    def _click(self, _event: object = None) -> str:
        if self._state != "disabled" and callable(self._command):
            self._command()
        return "break"

    def configure(self, cnf: object = None, **kwargs: object) -> object:
        if cnf:
            return super().configure(cnf, **kwargs)
        if "text" in kwargs:
            self._text = str(kwargs.pop("text"))
        if "state" in kwargs:
            self._state = str(kwargs.pop("state"))
        if "command" in kwargs:
            self._command = kwargs.pop("command")
        if self._explicit_width is None and hasattr(self, "_w"):
            kwargs["width"] = self._button_width()
        result = super().configure(**kwargs) if kwargs else None
        if hasattr(self, "_w"):
            self._draw()
        return result

    config = configure

    def cget(self, key: str) -> object:
        if key == "text":
            return self._text
        if key == "state":
            return self._state
        return super().cget(key)

    def state(self) -> tuple[str, ...]:
        return ("disabled",) if self._state == "disabled" else ()


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("o", "Ko", "Mo", "Go"):
        if value < 1024 or unit == "Go":
            return f"{value:.0f} {unit}" if unit in {"o", "Ko"} else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} o"


def collect_dropped_pdfs(raw_paths: list[str]) -> list[Path]:
    """Return unique PDFs from dropped files and top-level folders."""
    collected: list[Path] = []
    seen: set[Path] = set()
    for raw_path in raw_paths:
        path = Path(raw_path)
        candidates = (
            sorted(path.glob("*.pdf"), key=lambda candidate: candidate.name.casefold())
            if path.is_dir()
            else [path]
        )
        for candidate in candidates:
            if candidate.is_file() and candidate.suffix.casefold() == ".pdf":
                resolved = candidate.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    collected.append(candidate)
    return collected


@dataclass
class PdfItem:
    path: Path
    pages: int
    size: int
    selected_pages: set[int] = field(default_factory=set)


@dataclass(frozen=True)
class WindowMetrics:
    width: int
    height: int
    min_width: int
    min_height: int
    compact: bool


def window_metrics(screen_width: int, screen_height: int) -> WindowMetrics:
    """Choose a window size that stays inside small or DPI-scaled displays."""
    available_width = max(640, screen_width - 24)
    available_height = max(420, screen_height - 72)
    width = min(1180, available_width)
    height = min(760, available_height)
    return WindowMetrics(
        width=width,
        height=height,
        min_width=min(940, width),
        min_height=min(640, height),
        compact=height < 700,
    )


def inspect_pdf(path: Path) -> PdfItem:
    try:
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            result = reader.decrypt("")
            if not result:
                raise ValueError("PDF protégé par un mot de passe")
        pages = len(reader.pages)
    except (PdfReadError, OSError, ValueError, TypeError) as exc:
        raise ValueError(f"Impossible de lire ce PDF : {exc}") from exc
    if pages == 0:
        raise ValueError("Ce PDF ne contient aucune page")
    return PdfItem(
        path=path.resolve(),
        pages=pages,
        size=path.stat().st_size,
        selected_pages=set(range(pages)),
    )


def merge_pdfs(
    paths: list[Path],
    destination: Path,
    page_selections: list[list[int]] | None = None,
) -> int:
    """Merge PDFs to destination atomically and return the page count."""
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    total = 0
    temp_path: Path | None = None
    try:
        if page_selections is not None and len(page_selections) != len(paths):
            raise ValueError("La sélection de pages ne correspond pas aux documents")
        for document_index, path in enumerate(paths):
            reader = PdfReader(str(path), strict=False)
            if reader.is_encrypted and not reader.decrypt(""):
                raise ValueError(f"{path.name} est protégé par un mot de passe")
            page_indices = (
                page_selections[document_index]
                if page_selections is not None
                else list(range(len(reader.pages)))
            )
            for page_index in page_indices:
                if not 0 <= page_index < len(reader.pages):
                    raise ValueError(f"Page {page_index + 1} introuvable dans {path.name}")
                writer.add_page(reader.pages[page_index])
                total += 1
        if total == 0:
            raise ValueError("Aucune page n’a été sélectionnée")
        writer.add_metadata({"/Title": destination.stem, "/Creator": APP_NAME})
        fd, raw_temp = tempfile.mkstemp(prefix=".fusion-pdf-", suffix=".pdf", dir=destination.parent)
        os.close(fd)
        temp_path = Path(raw_temp)
        with temp_path.open("wb") as stream:
            writer.write(stream)
        os.replace(temp_path, destination)
        temp_path = None
        return total
    finally:
        writer.close()
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def reorder_pdf(
    source: Path,
    destination: Path,
    page_order: list[int],
    rotations: dict[int, int] | None = None,
) -> int:
    """Create an atomically written reordered and rotated copy of one PDF."""
    source = source.resolve()
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(source), strict=False)
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError(f"{source.name} est protégé par un mot de passe")
    writer = PdfWriter()
    temp_path: Path | None = None
    rotations = rotations or {}
    try:
        for page_index in page_order:
            if not 0 <= page_index < len(reader.pages):
                raise ValueError(f"Page {page_index + 1} introuvable dans {source.name}")
            page = reader.pages[page_index]
            rotation = rotations.get(page_index, 0) % 360
            if rotation:
                page.rotate(rotation)
            writer.add_page(page)
        if not page_order:
            raise ValueError("Aucune page n’a été sélectionnée")
        writer.add_metadata({"/Title": destination.stem, "/Creator": APP_NAME})
        fd, raw_temp = tempfile.mkstemp(prefix=".fusion-pdf-", suffix=".pdf", dir=destination.parent)
        os.close(fd)
        temp_path = Path(raw_temp)
        with temp_path.open("wb") as stream:
            writer.write(stream)
        os.replace(temp_path, destination)
        temp_path = None
        return len(page_order)
    finally:
        writer.close()
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def move_page_to_slot(order: list[int], source_index: int, slot: int) -> tuple[list[int], int]:
    """Move one page to a boundary slot ranging from 0 to len(order)."""
    if not 0 <= source_index < len(order):
        raise IndexError("Page source introuvable")
    if not 0 <= slot <= len(order):
        raise IndexError("Position d’insertion introuvable")
    result = order.copy()
    page = result.pop(source_index)
    insertion_index = slot - 1 if slot > source_index else slot
    result.insert(insertion_index, page)
    return result, insertion_index


def render_page_thumbnail(
    path: Path,
    page_index: int,
    max_width: int = 240,
    max_height: int = 300,
) -> bytes:
    """Render one page to a PNG thumbnail without leaving temporary files."""
    with pymupdf.open(path) as document:
        if not 0 <= page_index < document.page_count:
            raise ValueError(f"Page {page_index + 1} introuvable")
        page = document[page_index]
        rect = page.rect
        zoom = min(max_width / rect.width, max_height / rect.height, 2.0)
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return pixmap.tobytes("png")


def render_first_page(path: Path, max_width: int = 240, max_height: int = 300) -> bytes:
    return render_page_thumbnail(path, 0, max_width, max_height)


class FusionPdfApp(TkinterDnD.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.window_metrics = window_metrics(self.winfo_screenwidth(), self.winfo_screenheight())
        self.geometry(f"{self.window_metrics.width}x{self.window_metrics.height}")
        self.minsize(self.window_metrics.min_width, self.window_metrics.min_height)
        self.compact_ui = self.window_metrics.compact
        self.configure(bg=BG)
        self.items: list[PdfItem] = []
        self.last_output: Path | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.preview_token = 0
        self.preview_photos: dict[int, tk.PhotoImage] = {}
        self.preview_labels: dict[int, tk.Label] = {}
        self.preview_vars: dict[int, tk.BooleanVar] = {}
        self.current_preview_item: PdfItem | None = None
        self.editor_source: Path | None = None
        self.editor_order: list[int] = []
        self.editor_rotations: dict[int, int] = {}
        self.editor_history: list[tuple[list[int], dict[int, int]]] = []
        self.editor_future: list[tuple[list[int], dict[int, int]]] = []
        self.editor_selected: int | None = None
        self.editor_drag_index: int | None = None
        self.editor_drop_target: int | None = None
        self.editor_drop_indicator: tk.Frame | None = None
        self.editor_token = 0
        self.editor_photos: dict[int, tk.PhotoImage] = {}
        self.editor_cards: dict[int, tk.Frame] = {}
        self.editor_image_labels: dict[int, tk.Label] = {}
        self.editor_columns = 0
        self.editor_resize_job: str | None = None
        self.editor_zoom_job: str | None = None
        self.editor_zoom_var = tk.DoubleVar(value=1.0)
        self.editor_temp_source: Path | None = None
        self.help_window: tk.Toplevel | None = None
        self.help_page_index = 0
        self.help_expanded_sections: set[tuple[int, int]] = set()
        self._temp_dir = Path(tempfile.mkdtemp(prefix="fusion-pdf-"))
        self._configure_style()
        self._build_ui()
        self._build_editor_ui()
        self.bind("<ButtonRelease-1>", self._editor_drag_release, add="+")
        self.bind("<B1-Motion>", self._editor_drag_motion, add="+")
        self.bind("<Escape>", lambda _e: self._cancel_editor_drag())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.drop_target_register(DND_FILES)
        self.dnd_bind("<<DropEnter>>", self._drop_enter)
        self.dnd_bind("<<DropLeave>>", self._drop_leave)
        self.dnd_bind("<<Drop>>", self._on_drop)
        self.after_idle(self._maximize)
        self.after(100, self._poll_events)

    def _maximize(self) -> None:
        try:
            self.state("zoomed")
        except tk.TclError:
            pass

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("App.TFrame", background=BG)
        style.configure("Surface.TFrame", background=SURFACE)
        style.configure("Title.TLabel", background=BG, foreground=INK, font=("Segoe UI Semibold", 24))
        style.configure("Subtitle.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 10))
        style.configure("CardTitle.TLabel", background=SURFACE, foreground=INK, font=("Segoe UI Semibold", 12))
        style.configure("CardText.TLabel", background=SURFACE, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Status.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Primary.TButton", background=ACCENT, foreground="white", borderwidth=0, padding=(18, 11), font=("Segoe UI Semibold", 10))
        style.map("Primary.TButton", background=[("active", ACCENT_DARK), ("disabled", "#AEBBE8")])
        style.configure("Secondary.TButton", background=SURFACE, foreground=INK, bordercolor=BORDER, borderwidth=1, padding=(13, 9), font=("Segoe UI", 9))
        style.map("Secondary.TButton", background=[("active", "#EDF1F5")])
        style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE, foreground=INK, rowheight=38, borderwidth=0, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background="#F8F9FB", foreground=MUTED, relief="flat", padding=(8, 9), font=("Segoe UI Semibold", 9))
        style.map("Treeview", background=[("selected", "#E7ECFF")], foreground=[("selected", INK)])
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor="#E3E7EE", borderwidth=0)

    def _build_ui(self) -> None:
        outer_padding = (18, 10, 18, 10) if self.compact_ui else (32, 26, 32, 22)
        outer = ttk.Frame(self, style="App.TFrame", padding=outer_padding)
        self.main_view = outer
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        head = ttk.Frame(outer, style="App.TFrame")
        head.grid(row=0, column=0, sticky="ew", pady=(0, 8 if self.compact_ui else 22))
        title_block = ttk.Frame(head, style="App.TFrame")
        title_block.pack(side="left")
        ttk.Label(title_block, text="Fusion PDF", style="Title.TLabel").pack(anchor="w")
        ttk.Label(title_block, text="Assemblez vos documents sur votre ordinateur — rien n’est envoyé en ligne.", style="Subtitle.TLabel").pack(anchor="w", pady=(4, 0))
        head_actions = ttk.Frame(head, style="App.TFrame")
        head_actions.pack(side="right", anchor="n", pady=4)
        privacy = tk.Label(head_actions, text="●  100 % local", bg="#E5F6EF", fg=SUCCESS, padx=12, pady=7, font=("Segoe UI Semibold", 9))
        privacy.pack(side="left")
        RoundedButton(head_actions, text="?", width=36, command=self.open_help).pack(side="left", padx=(9, 0))

        card = ttk.Frame(outer, style="Surface.TFrame", padding=1)
        card.grid(row=1, column=0, sticky="nsew")
        card.columnconfigure(0, weight=1)
        card.rowconfigure(2, weight=1)
        toolbar_padding = (12, 8) if self.compact_ui else (18, 16)
        toolbar = ttk.Frame(card, style="Surface.TFrame", padding=toolbar_padding)
        toolbar.grid(row=0, column=0, sticky="ew")
        RoundedButton(toolbar, text="＋  Ajouter des PDF", style="Primary.TButton", command=self.add_files).pack(side="left")
        RoundedButton(toolbar, text="Ajouter un dossier", command=self.add_folder).pack(side="left", padx=(10, 0))
        RoundedButton(toolbar, text="Modifier un PDF", command=self.open_existing_editor).pack(side="left", padx=(10, 0))
        self.clear_button = RoundedButton(toolbar, text="Tout retirer", command=self.clear_all, state="disabled")
        self.clear_button.pack(side="right")

        self.drop_hint = tk.Label(
            card,
            text="↓  Glissez-déposez ici vos PDF ou un dossier",
            bg="#EEF2FF",
            fg=ACCENT,
            padx=14,
            pady=8,
            font=("Segoe UI Semibold", 9),
        )
        self.drop_hint.grid(row=1, column=0, sticky="ew", padx=12 if self.compact_ui else 18, pady=(0, 6 if self.compact_ui else 12))

        content = ttk.Panedwindow(card, orient="horizontal")
        content.grid(row=2, column=0, sticky="nsew", padx=12 if self.compact_ui else 18)
        table_frame = ttk.Frame(content, style="Surface.TFrame")
        preview = ttk.Frame(content, style="Surface.TFrame", width=360, padding=(18, 4, 4, 4))
        content.add(table_frame, weight=4)
        content.add(preview, weight=1)
        columns = ("order", "name", "pages", "size")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("order", text="#")
        self.tree.heading("name", text="DOCUMENT")
        self.tree.heading("pages", text="PAGES RETENUES")
        self.tree.heading("size", text="TAILLE")
        self.tree.column("order", width=45, minwidth=45, stretch=False, anchor="center")
        self.tree.column("name", width=520, minwidth=250)
        self.tree.column("pages", width=90, minwidth=75, stretch=False, anchor="center")
        self.tree.column("size", width=100, minwidth=85, stretch=False, anchor="e")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<Delete>", lambda _e: self.remove_selected())
        self.tree.bind("<Double-1>", lambda _e: self.open_selected())
        self.tree.bind("<<TreeviewSelect>>", self._selection_changed)

        self.empty = tk.Frame(self.tree, bg=SURFACE)
        tk.Label(self.empty, text="PDF", bg="#EEF1F5", fg=ACCENT, width=5, height=2, font=("Segoe UI Semibold", 13)).pack(pady=(0, 13))
        tk.Label(self.empty, text="Ajoutez les documents à fusionner", bg=SURFACE, fg=INK, font=("Segoe UI Semibold", 11)).pack()
        tk.Label(self.empty, text="Vous pourrez ensuite modifier leur ordre.", bg=SURFACE, fg=MUTED, font=("Segoe UI", 9)).pack(pady=(5, 0))
        self.empty.place(relx=.5, rely=.48, anchor="center")

        preview_head = ttk.Frame(preview, style="Surface.TFrame")
        preview_head.pack(fill="x", pady=(0, 8))
        ttk.Label(preview_head, text="PAGES À INCLURE", style="CardText.TLabel").pack(side="left")
        self.select_all_button = RoundedButton(preview_head, text="Toutes", command=lambda: self._set_all_pages(True), state="disabled")
        self.select_all_button.pack(side="right")
        self.select_none_button = RoundedButton(preview_head, text="Aucune", command=lambda: self._set_all_pages(False), state="disabled")
        self.select_none_button.pack(side="right", padx=(0, 6))

        self.preview_name = ttk.Label(preview, text="Aucun document sélectionné", style="CardTitle.TLabel", wraplength=330)
        self.preview_name.pack(anchor="w", fill="x", pady=(0, 2))
        self.preview_details = ttk.Label(preview, text="", style="CardText.TLabel")
        self.preview_details.pack(anchor="w", pady=(0, 10))

        self.preview_box = tk.Frame(
            preview,
            bg="#EDF0F4",
            width=330,
            height=150 if self.compact_ui else 360,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        self.preview_box.pack(fill="both", expand=True)
        self.preview_canvas = tk.Canvas(self.preview_box, bg="#EDF0F4", highlightthickness=0, borderwidth=0)
        preview_scrollbar = ttk.Scrollbar(self.preview_box, orient="vertical", command=self.preview_canvas.yview)
        self.preview_canvas.configure(yscrollcommand=preview_scrollbar.set)
        preview_scrollbar.pack(side="right", fill="y")
        self.preview_canvas.pack(side="left", fill="both", expand=True)
        self.preview_pages = tk.Frame(self.preview_canvas, bg="#EDF0F4")
        self.preview_window = self.preview_canvas.create_window((0, 0), window=self.preview_pages, anchor="nw")
        self.preview_pages.bind("<Configure>", lambda _e: self.preview_canvas.configure(scrollregion=self.preview_canvas.bbox("all")))
        self.preview_canvas.bind("<Configure>", lambda e: self.preview_canvas.itemconfigure(self.preview_window, width=e.width))
        self.preview_canvas.bind("<MouseWheel>", self._scroll_preview)
        self.preview_empty = tk.Label(self.preview_pages, text="Sélectionnez un document\npour afficher toutes ses pages", bg="#EDF0F4", fg=MUTED, justify="center", font=("Segoe UI", 9))
        self.preview_empty.pack(fill="both", expand=True, padx=12, pady=80)

        actions_padding = (12, 8, 12, 10) if self.compact_ui else (18, 14, 18, 18)
        actions = ttk.Frame(card, style="Surface.TFrame", padding=actions_padding)
        actions.grid(row=3, column=0, sticky="ew")
        self.up_button = RoundedButton(actions, text="↑  Monter", command=lambda: self.move(-1), state="disabled")
        self.up_button.pack(side="left")
        self.down_button = RoundedButton(actions, text="↓  Descendre", command=lambda: self.move(1), state="disabled")
        self.down_button.pack(side="left", padx=(8, 0))
        self.remove_button = RoundedButton(actions, text="Retirer", command=self.remove_selected, state="disabled")
        self.remove_button.pack(side="left", padx=(8, 0))
        self.merge_button = RoundedButton(actions, text="Fusionner les PDF", style="Primary.TButton", command=self.start_merge, state="disabled")
        self.merge_button.pack(side="right")
        self.merge_edit_button = RoundedButton(actions, text="Fusionner et éditer", command=self.start_merge_and_edit, state="disabled")
        self.merge_edit_button.pack(side="right", padx=(0, 10))

        bottom = ttk.Frame(outer, style="App.TFrame")
        bottom.grid(row=2, column=0, sticky="ew", pady=(6 if self.compact_ui else 14, 0))
        self.status = ttk.Label(bottom, text="Prêt", style="Status.TLabel")
        self.status.pack(side="left")
        self.open_button = RoundedButton(bottom, text="Ouvrir le dernier fichier", command=self.open_output, state="disabled")
        self.open_button.pack(side="right")
        self.progress = ttk.Progressbar(bottom, mode="indeterminate", length=150)

    def _build_editor_ui(self) -> None:
        self.editor_view = ttk.Frame(self, style="App.TFrame", padding=(28, 22, 28, 20))

        header = ttk.Frame(self.editor_view, style="App.TFrame")
        header.pack(fill="x", pady=(0, 16))
        RoundedButton(header, text="←  Retour à la fusion", command=self.close_editor).pack(side="left", padx=(0, 16))
        title_block = ttk.Frame(header, style="App.TFrame")
        title_block.pack(side="left", fill="x", expand=True)
        ttk.Label(title_block, text="Organiser les pages", style="Title.TLabel").pack(anchor="w")
        self.editor_subtitle = ttk.Label(title_block, text="", style="Subtitle.TLabel")
        self.editor_subtitle.pack(anchor="w", pady=(3, 0))
        RoundedButton(header, text="?", width=36, command=self.open_help).pack(side="right", padx=(10, 0))
        self.editor_save_button = RoundedButton(header, text="Enregistrer une copie", style="Primary.TButton", command=self.save_editor_pdf)
        self.editor_save_button.pack(side="right")

        toolbar = ttk.Frame(self.editor_view, style="Surface.TFrame", padding=(14, 12))
        toolbar.pack(fill="x", pady=(0, 12))
        action_row = ttk.Frame(toolbar, style="Surface.TFrame")
        action_row.pack(fill="x")
        self.editor_left_button = RoundedButton(action_row, text="←  Déplacer", command=lambda: self._editor_move(-1))
        self.editor_left_button.pack(side="left")
        self.editor_right_button = RoundedButton(action_row, text="Déplacer  →", command=lambda: self._editor_move(1))
        self.editor_right_button.pack(side="left", padx=(8, 0))
        self.editor_delete_button = RoundedButton(action_row, text="Supprimer la page", command=self._editor_delete)
        self.editor_delete_button.pack(side="left", padx=(8, 0))
        self.editor_rotate_left_button = RoundedButton(action_row, text="↶  90°", command=lambda: self._editor_rotate(-90))
        self.editor_rotate_left_button.pack(side="left", padx=(8, 0))
        self.editor_rotate_right_button = RoundedButton(action_row, text="90°  ↷", command=lambda: self._editor_rotate(90))
        self.editor_rotate_right_button.pack(side="left", padx=(8, 0))
        ttk.Separator(action_row, orient="vertical").pack(side="left", fill="y", padx=14)
        self.editor_undo_button = RoundedButton(action_row, text="Annuler", command=self._editor_undo)
        self.editor_undo_button.pack(side="left")
        self.editor_redo_button = RoundedButton(action_row, text="Rétablir", command=self._editor_redo)
        self.editor_redo_button.pack(side="left", padx=(8, 0))
        zoom = ttk.Frame(toolbar, style="Surface.TFrame")
        zoom.pack(fill="x", pady=(10, 0))
        ttk.Label(zoom, text="Taille des vignettes", style="CardText.TLabel").pack(side="left", padx=(0, 8))
        self.editor_zoom_scale = ttk.Scale(zoom, from_=0.60, to=1.65, variable=self.editor_zoom_var, command=self._editor_zoom_requested, length=160)
        self.editor_zoom_scale.pack(side="left")
        self.editor_zoom_label = ttk.Label(zoom, text="100 %", style="CardText.TLabel", width=7, anchor="e")
        self.editor_zoom_label.pack(side="left", padx=(7, 0))

        grid_shell = tk.Frame(self.editor_view, bg="#E9EDF2", highlightthickness=1, highlightbackground=BORDER)
        grid_shell.pack(fill="both", expand=True)
        self.editor_canvas = tk.Canvas(grid_shell, bg="#E9EDF2", highlightthickness=0, borderwidth=0)
        editor_scrollbar = ttk.Scrollbar(grid_shell, orient="vertical", command=self.editor_canvas.yview)
        self.editor_canvas.configure(yscrollcommand=editor_scrollbar.set)
        editor_scrollbar.pack(side="right", fill="y")
        self.editor_canvas.pack(side="left", fill="both", expand=True)
        self.editor_grid = tk.Frame(self.editor_canvas, bg="#E9EDF2")
        self.editor_window = self.editor_canvas.create_window((0, 0), window=self.editor_grid, anchor="nw")
        self.editor_grid.bind("<Configure>", lambda _e: self.editor_canvas.configure(scrollregion=self.editor_canvas.bbox("all")))
        self.editor_canvas.bind("<Configure>", self._editor_canvas_resized)
        self.editor_canvas.bind("<MouseWheel>", self._scroll_editor)

        footer = ttk.Frame(self.editor_view, style="App.TFrame")
        footer.pack(fill="x", pady=(12, 0))
        self.editor_status = ttk.Label(footer, text="", style="Status.TLabel")
        self.editor_status.pack(side="left")
        self.editor_progress = ttk.Progressbar(footer, mode="indeterminate", length=160)

    def open_help(self) -> None:
        if self.help_window and self.help_window.winfo_exists():
            self.help_window.deiconify()
            self.help_window.lift()
            self.help_window.focus_force()
            return

        window = tk.Toplevel(self)
        self.help_window = window
        self.help_page_index = 0
        window.title("Notice - Fusion PDF")
        window.geometry("760x600")
        window.minsize(680, 520)
        window.configure(bg=BG)
        window.transient(self)
        window.protocol("WM_DELETE_WINDOW", self._close_help)
        window.bind("<Escape>", lambda _e: self._close_help())
        window.bind("<Left>", lambda _e: self._change_help_page(-1))
        window.bind("<Right>", lambda _e: self._change_help_page(1))

        shell = tk.Frame(window, bg=BG, padx=28, pady=24)
        shell.pack(fill="both", expand=True)
        top = tk.Frame(shell, bg=ACCENT, padx=24, pady=20)
        top.pack(fill="x")
        tk.Label(top, text="NOTICE", bg=ACCENT, fg="#DCE4FF", font=("Segoe UI Semibold", 9)).pack(anchor="w")
        self.help_title = tk.Label(top, text="", bg=ACCENT, fg="white", font=("Segoe UI Semibold", 22))
        self.help_title.pack(anchor="w", pady=(5, 0))
        self.help_subtitle = tk.Label(top, text="", bg=ACCENT, fg="#E9EDFF", font=("Segoe UI", 10), wraplength=650, justify="left")
        self.help_subtitle.pack(anchor="w", pady=(6, 0))

        content_frame = tk.Frame(shell, bg=SURFACE, padx=26, pady=18, highlightthickness=1, highlightbackground=BORDER)
        content_frame.pack(fill="both", expand=True)
        self.help_content = tk.Text(
            content_frame,
            bg=SURFACE,
            fg=INK,
            relief="flat",
            borderwidth=0,
            wrap="word",
            cursor="arrow",
            font=("Segoe UI", 10),
            padx=2,
            pady=2,
        )
        help_scrollbar = ttk.Scrollbar(content_frame, orient="vertical", command=self.help_content.yview)
        self.help_content.configure(yscrollcommand=help_scrollbar.set)
        help_scrollbar.pack(side="right", fill="y")
        self.help_content.pack(side="left", fill="both", expand=True)
        self.help_content.tag_configure("heading", font=("Segoe UI Semibold", 12), foreground=INK, spacing1=10, spacing3=4)
        self.help_content.tag_configure("hint", font=("Segoe UI", 9, "italic"), foreground=MUTED, spacing3=5)
        self.help_content.tag_configure("body", font=("Segoe UI", 10), foreground=MUTED, lmargin1=20, lmargin2=20, spacing3=8)
        self.help_content.tag_configure("detail", font=("Segoe UI", 10), foreground=INK, background="#F5F7FA", lmargin1=30, lmargin2=30, rmargin=12, spacing1=4, spacing3=12)
        self.help_content.tag_configure("compare_title", font=("Segoe UI Semibold", 11), foreground=ACCENT, spacing1=7, spacing3=2)
        self.help_content.tag_configure("compare_body", font=("Segoe UI", 10), foreground=INK, background="#EEF2FF", lmargin1=22, lmargin2=22, rmargin=12, spacing3=8)
        self.help_content.tag_configure("contact", font=("Segoe UI Semibold", 10, "underline"), foreground=ACCENT, spacing1=12)
        self.help_content.tag_bind("contact", "<Button-1>", lambda _e: self._open_contact_email())
        self.help_content.tag_bind("contact", "<Enter>", lambda _e: self.help_content.configure(cursor="hand2"))
        self.help_content.tag_bind("contact", "<Leave>", lambda _e: self.help_content.configure(cursor="arrow"))

        navigation = tk.Frame(shell, bg=BG, pady=14)
        navigation.pack(fill="x")
        self.help_counter = tk.Label(navigation, text="", bg=BG, fg=MUTED, font=("Segoe UI Semibold", 9))
        self.help_counter.pack(side="left")
        self.help_compare_button = RoundedButton(navigation, text="Comparer les 2 modes", command=self._show_help_comparison)
        self.help_compare_button.pack(side="left", padx=(12, 0))
        RoundedButton(navigation, text="Fermer", command=self._close_help).pack(side="right")
        self.help_next = RoundedButton(navigation, text="Suivant  →", style="Primary.TButton", command=lambda: self._change_help_page(1))
        self.help_next.pack(side="right", padx=(0, 8))
        self.help_previous = RoundedButton(navigation, text="←  Précédent", command=lambda: self._change_help_page(-1))
        self.help_previous.pack(side="right", padx=(0, 8))

        self._render_help_page()
        window.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - window.winfo_width()) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - window.winfo_height()) // 2)
        window.geometry(f"+{x}+{y}")
        window.grab_set()
        window.focus_force()

    def _help_pages(self) -> list[tuple[str, str, list[tuple[str, str, str]]]]:
        return [
            (
                "Bienvenue dans Fusion PDF",
                "Une application simple pour travailler sur vos PDF sans envoyer aucun document sur Internet.",
                [
                    (
                        "Vos documents restent privés",
                        "Toutes les opérations sont réalisées localement sur votre ordinateur.",
                        "Aucun PDF, aperçu ou nom de fichier n’est envoyé sur Internet. La lecture, les miniatures et la création du résultat sont effectuées par l’application sur votre poste. Les fichiers temporaires utilisés par l’éditeur sont placés dans un dossier local privé puis supprimés automatiquement à la fermeture.",
                    ),
                    (
                        "Pour commencer",
                        "Glissez vos PDF ou un dossier dans la fenêtre, ou utilisez les boutons d’ajout.",
                        "Vous pouvez déposer plusieurs fichiers en une fois, même si leurs noms contiennent des espaces. Les doublons sont ignorés, les PDF d’un dossier sont ajoutés par ordre alphabétique et chaque fichier est contrôlé avant d’apparaître dans la liste. Un document illisible ou protégé est signalé sans bloquer les autres.",
                    ),
                    (
                        "Contact",
                        f"Pour toute remarque ou suggestion, écrivez-moi à : {CONTACT_EMAIL}",
                        "Cliquez directement sur l’adresse pour préparer un nouveau message dans votre logiciel de messagerie. Si aucun logiciel n’est configuré, l’adresse est copiée dans le presse-papiers.",
                    ),
                ],
            ),
            (
                "Préparer les documents",
                "Contrôlez précisément les fichiers et les pages à conserver avant de lancer la fusion.",
                [
                    (
                        "Organiser les PDF",
                        "Sélectionnez les documents puis utilisez Monter, Descendre ou Retirer.",
                        "L’ordre vertical de la liste devient l’ordre du document final : le premier fichier fournit les premières pages, puis vient le deuxième, et ainsi de suite. Plusieurs documents peuvent être sélectionnés ensemble ; leurs positions relatives sont conservées pendant le déplacement. Un double-clic ouvre le PDF source pour une vérification complète.",
                    ),
                    (
                        "Choisir les pages",
                        "Cliquez sur un document pour afficher toutes ses pages, cochées par défaut.",
                        "Décochez individuellement les pages inutiles ou utilisez Toutes et Aucune pour agir sur tout le document. Les choix sont mémorisés lorsque vous passez d’un fichier à l’autre. Un document entièrement décoché reste dans la liste mais est simplement ignoré lors de la fusion.",
                    ),
                    (
                        "Vérifier rapidement",
                        "La colonne Pages retenues affiche le nombre de pages incluses.",
                        "Par exemple, « 3 / 8 » signifie que trois pages sur huit seront conservées. Le compteur se met à jour immédiatement après chaque coche. Les boutons de fusion restent désactivés tant qu’aucune page n’est retenue, ce qui évite de produire accidentellement un document vide.",
                    ),
                ],
            ),
            (
                "Fusionner ou fusionner et éditer",
                "Deux parcours sont disponibles selon le niveau de contrôle souhaité.",
                [
                    (
                        "Fusionner les PDF",
                        "Crée immédiatement le fichier final et reste sur l’écran principal.",
                        "Étapes : 1) cliquez sur Fusionner les PDF ; 2) choisissez tout de suite le nom et l’emplacement ; 3) attendez la confirmation de création.\n\nChoisissez ce parcours lorsque l’ordre des documents et les pages cochées constituent déjà le résultat définitif. Le fichier est immédiatement utilisable et l’application reste sur l’écran principal. Pour le modifier ensuite, il faudra l’ouvrir avec Modifier un PDF.",
                    ),
                    (
                        "Fusionner et éditer",
                        "Ouvre d’abord le résultat dans l’éditeur, sans demander où l’enregistrer.",
                        "Étapes : 1) cliquez sur Fusionner et éditer ; 2) le résultat temporaire s’ouvre automatiquement ; 3) déplacez ou supprimez les pages ; 4) cliquez sur Enregistrer une copie seulement lorsque le résultat vous convient.\n\nAucun nom de fichier n’est demandé au début et rien n’est conservé définitivement tant que vous n’avez pas enregistré. La copie temporaire reste strictement locale et disparaît lorsque vous quittez l’éditeur.",
                    ),
                    (
                        "En résumé : lequel choisir ?",
                        "Fusionner pour aller vite ; Fusionner et éditer pour contrôler le résultat page par page.",
                        "Les deux boutons utilisent exactement la même liste, le même ordre de documents et les mêmes pages cochées.\n\nUtilisez Fusionner les PDF pour un résultat prêt à diffuser en un clic. Utilisez Fusionner et éditer si vous avez besoin d’un contrôle visuel final, d’un ordre page par page ou de suppressions supplémentaires. La différence concerne donc le moment de l’enregistrement, pas la qualité du PDF produit.",
                    ),
                    (
                        "Modifier un PDF existant",
                        "Ouvre un document unique dans l’éditeur sans effectuer de fusion.",
                        "Cette fonction est adaptée aux gros PDF déjà constitués. Sélectionnez le fichier, attendez la génération progressive des miniatures, puis réordonnez ou supprimez les pages souhaitées. Le curseur de zoom facilite la lecture sans modifier le document. Enregistrer une copie crée un nouveau PDF et préserve toujours l’original.",
                    ),
                ],
            ),
            (
                "Organiser les pages",
                "Affinez le résultat avec les miniatures de l’éditeur.",
                [
                    (
                        "Déplacer",
                        "Glissez une page jusqu’à la barre verte située entre deux vignettes.",
                        "Cliquez sur une vignette, maintenez le bouton de la souris et déplacez-la. Une barre verte indique précisément la future position entre deux pages, y compris avant la première ou après la dernière. Relâchez lorsque la barre est au bon endroit. Pour un déplacement d’une seule position, les boutons Déplacer peuvent être plus rapides.",
                    ),
                    (
                        "Faire pivoter",
                        "Tournez la page sélectionnée de 90° vers la gauche ou vers la droite.",
                        "Sélectionnez une vignette puis utilisez ↶ 90° ou 90° ↷. Plusieurs clics permettent d’obtenir une rotation de 180° ou 270°. La miniature est recalculée immédiatement, la rotation peut être annulée ou rétablie, et elle sera inscrite dans la copie enregistrée.",
                    ),
                    (
                        "Supprimer et corriger",
                        "Supprimez la page sélectionnée, puis utilisez Annuler ou Rétablir si nécessaire.",
                        "L’historique conserve tous les déplacements et suppressions de la session. Annuler remonte d’une étape ; Rétablir réapplique une action annulée. Dès qu’une nouvelle modification est effectuée, la branche de rétablissement précédente est effacée. Une page supprimée n’est retirée que de la future copie : le document source reste intact.",
                    ),
                    (
                        "Zoom et enregistrement",
                        "Ajustez la taille des vignettes, puis choisissez Enregistrer une copie.",
                        "Déplacez le curseur de 60 % à 165 % selon le nombre de pages et la précision nécessaire. Les miniatures sont recalculées pour rester nettes ; ce zoom modifie uniquement l’affichage, jamais la qualité du PDF. Enregistrer une copie recrée le document dans l’ordre visible et impose un nouveau nom afin de préserver l’original.",
                    ),
                ],
            ),
        ]

    def _render_help_page(self) -> None:
        pages = self._help_pages()
        self.help_page_index = max(0, min(self.help_page_index, len(pages) - 1))
        title, subtitle, sections = pages[self.help_page_index]
        self.help_title.configure(text=title)
        self.help_subtitle.configure(text=subtitle)
        self.help_content.configure(state="normal")
        self.help_content.delete("1.0", "end")
        if self.help_page_index == 2:
            self.help_content.insert("end", "FUSIONNER LES PDF\n", "compare_title")
            self.help_content.insert(
                "end",
                "Enregistrement immédiat  •  Nom du fichier demandé avant la fusion  •  Retour à l’écran principal\n"
                "À choisir lorsque la liste et les pages cochées constituent déjà votre résultat définitif.\n",
                "compare_body",
            )
            self.help_content.insert("end", "FUSIONNER ET ÉDITER\n", "compare_title")
            self.help_content.insert(
                "end",
                "Aucun enregistrement immédiat  •  Ouverture d’une copie temporaire  •  Réorganisation et suppression possibles\n"
                "À choisir lorsque vous souhaitez contrôler et corriger le résultat page par page avant de l’enregistrer.\n\n",
                "compare_body",
            )
        self.help_content.insert("end", "Cliquez sur une rubrique pour afficher ou masquer les détails.\n", "hint")
        for section_index, (heading, body, detail) in enumerate(sections):
            section_key = (self.help_page_index, section_index)
            expanded = section_key in self.help_expanded_sections
            section_tag = f"section_{section_index}"
            arrow = "▼" if expanded else "▶"
            self.help_content.insert("end", f"{arrow}  {heading}\n", ("heading", section_tag))
            self.help_content.tag_bind(section_tag, "<Button-1>", lambda _e, index=section_index: self._toggle_help_section(index))
            self.help_content.tag_bind(section_tag, "<Enter>", lambda _e: self.help_content.configure(cursor="hand2"))
            self.help_content.tag_bind(section_tag, "<Leave>", lambda _e: self.help_content.configure(cursor="arrow"))
            if heading == "Contact":
                prefix, email = body.rsplit(" ", 1)
                self.help_content.insert("end", prefix + " ", "body")
                self.help_content.insert("end", email + "\n", "contact")
            else:
                self.help_content.insert("end", body + "\n", "body")
            if expanded:
                self.help_content.insert("end", detail + "\n", "detail")
        self.help_content.configure(state="disabled")
        self.help_content.yview_moveto(0)
        self.help_counter.configure(text=f"Page {self.help_page_index + 1} sur {len(pages)}")
        self.help_previous.configure(state="normal" if self.help_page_index > 0 else "disabled")
        self.help_next.configure(state="normal" if self.help_page_index < len(pages) - 1 else "disabled")

    def _toggle_help_section(self, section_index: int) -> None:
        key = (self.help_page_index, section_index)
        if key in self.help_expanded_sections:
            self.help_expanded_sections.remove(key)
        else:
            self.help_expanded_sections.add(key)
        self._render_help_page()

    def _change_help_page(self, direction: int) -> None:
        target = self.help_page_index + direction
        if 0 <= target < len(self._help_pages()):
            self.help_page_index = target
            self._render_help_page()

    def _show_help_comparison(self) -> None:
        self.help_page_index = 2
        for section_index in range(len(self._help_pages()[2][2])):
            self.help_expanded_sections.add((2, section_index))
        self._render_help_page()

    def _open_contact_email(self) -> None:
        try:
            os.startfile(f"mailto:{CONTACT_EMAIL}")  # type: ignore[attr-defined]
        except OSError:
            self.clipboard_clear()
            self.clipboard_append(CONTACT_EMAIL)

    def _close_help(self) -> None:
        if self.help_window and self.help_window.winfo_exists():
            try:
                self.help_window.grab_release()
            except tk.TclError:
                pass
            self.help_window.destroy()
        self.help_window = None

    def open_existing_editor(self) -> None:
        selected = filedialog.askopenfilename(title="Choisir le PDF à modifier", filetypes=[("Document PDF", "*.pdf")])
        if selected:
            try:
                inspect_pdf(Path(selected))
                self.open_editor(Path(selected))
            except ValueError as exc:
                messagebox.showerror(APP_NAME, str(exc))

    def open_editor(self, source: Path, temporary: bool = False, display_name: str | None = None) -> None:
        try:
            page_count = len(PdfReader(str(source), strict=False).pages)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Impossible d’ouvrir ce PDF : {exc}")
            return
        self.editor_token += 1
        token = self.editor_token
        self.editor_source = source.resolve()
        self.editor_temp_source = self.editor_source if temporary else None
        self.editor_order = list(range(page_count))
        self.editor_rotations = {}
        self.editor_history.clear()
        self.editor_future.clear()
        self.editor_selected = 0 if page_count else None
        self.editor_drag_index = None
        self.editor_photos.clear()
        self.editor_columns = 0
        self.editor_zoom_var.set(1.0)
        self.editor_zoom_label.configure(text="100 %")
        self.editor_subtitle.configure(text=f"{display_name or source.name}  •  {page_count} page(s)")
        self.editor_status.configure(text="Cliquez pour sélectionner, ou glissez une page entre deux vignettes")
        self.main_view.pack_forget()
        self.editor_view.pack(fill="both", expand=True)
        self.after_idle(self._render_editor_grid)
        self._update_editor_actions()
        threading.Thread(target=self._editor_render_worker, args=(self.editor_source, token, 170, 220, self.editor_rotations.copy()), daemon=True).start()

    def close_editor(self) -> None:
        self.editor_token += 1
        self.editor_view.pack_forget()
        self.main_view.pack(fill="both", expand=True)
        self._remove_editor_temp()

    def _editor_render_worker(
        self,
        source: Path,
        token: int,
        width: int,
        height: int,
        rotations: dict[int, int],
    ) -> None:
        try:
            with pymupdf.open(source) as document:
                for page_index in range(document.page_count):
                    if token != self.editor_token:
                        return
                    page = document[page_index]
                    rect = page.rect
                    rotation = rotations.get(page_index, 0) % 360
                    rotated_width, rotated_height = (rect.height, rect.width) if rotation in {90, 270} else (rect.width, rect.height)
                    zoom = min(width / rotated_width, height / rotated_height, 3.0)
                    matrix = pymupdf.Matrix(zoom, zoom).prerotate(rotation)
                    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                    self.events.put(("editor_preview", (token, page_index, rotation, pixmap.tobytes("png"))))
        except Exception as exc:
            self.events.put(("editor_preview_error", (token, str(exc))))

    def _editor_render_one_worker(
        self,
        source: Path,
        token: int,
        page_index: int,
        width: int,
        height: int,
        rotation: int,
    ) -> None:
        try:
            with pymupdf.open(source) as document:
                page = document[page_index]
                rect = page.rect
                rotation %= 360
                rotated_width, rotated_height = (rect.height, rect.width) if rotation in {90, 270} else (rect.width, rect.height)
                zoom = min(width / rotated_width, height / rotated_height, 3.0)
                matrix = pymupdf.Matrix(zoom, zoom).prerotate(rotation)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                self.events.put(("editor_preview", (token, page_index, rotation, pixmap.tobytes("png"))))
        except Exception as exc:
            self.events.put(("editor_preview_error", (token, str(exc))))

    def _editor_canvas_resized(self, event: tk.Event) -> None:
        self.editor_canvas.itemconfigure(self.editor_window, width=event.width)
        card_width = int(205 * self.editor_zoom_var.get())
        columns = max(1, event.width // max(card_width, 140))
        if columns != self.editor_columns:
            self.editor_columns = columns
            if self.editor_resize_job:
                self.after_cancel(self.editor_resize_job)
            self.editor_resize_job = self.after(80, self._render_editor_grid)

    def _render_editor_grid(self) -> None:
        self.editor_resize_job = None
        for child in self.editor_grid.winfo_children():
            child.destroy()
        self.editor_drop_indicator = None
        self.editor_cards.clear()
        self.editor_image_labels.clear()
        if not self.editor_order:
            tk.Label(
                self.editor_grid,
                text="Toutes les pages ont été supprimées.\nUtilisez Annuler pour en restaurer.",
                bg="#E9EDF2",
                fg=MUTED,
                justify="center",
                font=("Segoe UI", 11),
            ).grid(row=0, column=0, padx=30, pady=80)
            self._update_editor_actions()
            return
        scale = self.editor_zoom_var.get()
        thumb_width = int(170 * scale)
        thumb_height = int(220 * scale)
        card_width = int(205 * scale)
        columns = self.editor_columns or max(1, self.editor_canvas.winfo_width() // max(card_width, 140))
        for column in range(columns):
            self.editor_grid.grid_columnconfigure(column, weight=1)
        for position, source_page in enumerate(self.editor_order):
            selected = position == self.editor_selected
            card = tk.Frame(
                self.editor_grid,
                bg=SURFACE,
                highlightthickness=3 if selected else 1,
                highlightbackground=ACCENT if selected else BORDER,
                cursor="hand2",
            )
            card.grid(row=position // columns, column=position % columns, padx=9, pady=9, sticky="n")
            self.editor_cards[position] = card
            rotation = self.editor_rotations.get(source_page, 0) % 360
            rotation_label = ""
            if rotation == 90:
                rotation_label = "  ·  ↷ 90°"
            elif rotation == 180:
                rotation_label = "  ·  ↷ 180°"
            elif rotation == 270:
                rotation_label = "  ·  ↶ 90°"
            heading = tk.Label(card, text=f"Page {position + 1}  ·  source {source_page + 1}{rotation_label}", bg=SURFACE, fg=INK, font=("Segoe UI Semibold", 9), padx=8, pady=7)
            heading.pack(fill="x")
            photo = self.editor_photos.get(source_page)
            image = tk.Label(
                card,
                image=photo if photo else "",
                text="" if photo else "Chargement…",
                bg="#F7F8FA",
                fg=MUTED,
                width=thumb_width if photo else max(16, int(22 * scale)),
                height=thumb_height if photo else max(8, int(12 * scale)),
            )
            image.pack(padx=8, pady=(0, 8))
            self.editor_image_labels[source_page] = image
            for widget in (card, heading, image):
                setattr(widget, "editor_position", position)
                widget.bind("<ButtonPress-1>", lambda _e, pos=position: self._editor_drag_start(pos))
                widget.bind("<B1-Motion>", self._editor_drag_motion)
                widget.bind("<ButtonRelease-1>", self._editor_drag_release)
                widget.bind("<MouseWheel>", self._scroll_editor)
        self._update_editor_actions()

    def _editor_zoom_requested(self, value: str) -> None:
        percent = round(float(value) * 100)
        self.editor_zoom_label.configure(text=f"{percent} %")
        if self.editor_zoom_job:
            self.after_cancel(self.editor_zoom_job)
        self.editor_zoom_job = self.after(300, self._apply_editor_zoom)

    def _apply_editor_zoom(self) -> None:
        self.editor_zoom_job = None
        if self.editor_source is None or not self.editor_view.winfo_ismapped():
            return
        self.editor_token += 1
        token = self.editor_token
        scale = self.editor_zoom_var.get()
        width = int(170 * scale)
        height = int(220 * scale)
        self.editor_photos.clear()
        self.editor_columns = 0
        self._render_editor_grid()
        self.editor_status.configure(text=f"Actualisation des aperçus à {round(scale * 100)} %…")
        threading.Thread(target=self._editor_render_worker, args=(self.editor_source, token, width, height, self.editor_rotations.copy()), daemon=True).start()

    def _editor_drag_start(self, position: int) -> None:
        self.editor_selected = position
        self.editor_drag_index = position
        self.editor_drop_target = None
        self.configure(cursor="fleur")
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self._highlight_editor_selection()
        self._update_editor_actions()
        self.editor_status.configure(text=f"Page {position + 1} saisie — glissez-la entre deux pages")

    def _editor_position_at(self, x_root: int, y_root: int) -> int | None:
        widget = self.winfo_containing(x_root, y_root)
        while widget is not None:
            candidate = getattr(widget, "editor_position", None)
            if candidate is not None:
                return int(candidate)
            widget = widget.master
        return None

    def _editor_slot_at(self, x_root: int, y_root: int) -> int | None:
        if not self.editor_cards:
            return None
        grid_x = self.editor_grid.winfo_rootx()
        grid_y = self.editor_grid.winfo_rooty()
        if not (grid_x <= x_root <= grid_x + self.editor_grid.winfo_width() and grid_y <= y_root <= grid_y + self.editor_grid.winfo_height()):
            return None
        nearest_position = min(
            self.editor_cards,
            key=lambda position: (
                self.editor_cards[position].winfo_rootx() + self.editor_cards[position].winfo_width() / 2 - x_root
            ) ** 2
            + (
                self.editor_cards[position].winfo_rooty() + self.editor_cards[position].winfo_height() / 2 - y_root
            ) ** 2,
        )
        card = self.editor_cards[nearest_position]
        midpoint = card.winfo_rootx() + card.winfo_width() / 2
        return nearest_position if x_root < midpoint else nearest_position + 1

    def _show_editor_drop_slot(self, slot: int | None) -> None:
        if self.editor_drop_indicator:
            self.editor_drop_indicator.place_forget()
        if slot is None or not self.editor_cards:
            return
        if self.editor_drop_indicator is None:
            self.editor_drop_indicator = tk.Frame(self.editor_grid, bg=SUCCESS, width=6)
        if slot >= len(self.editor_order):
            anchor = self.editor_cards[len(self.editor_order) - 1]
            x = anchor.winfo_x() + anchor.winfo_width() + 5
        else:
            anchor = self.editor_cards[slot]
            x = anchor.winfo_x() - 7
        self.editor_drop_indicator.place(x=x, y=anchor.winfo_y() - 2, width=6, height=anchor.winfo_height() + 4)
        self.editor_drop_indicator.lift()

    def _describe_editor_slot(self, slot: int) -> str:
        if slot == 0:
            return "Insérer avant la première page"
        if slot == len(self.editor_order):
            return "Insérer après la dernière page"
        return f"Insérer entre les pages {slot} et {slot + 1}"

    def _editor_drag_motion(self, event: tk.Event) -> None:
        if self.editor_drag_index is None:
            return
        slot = self._editor_slot_at(event.x_root, event.y_root)
        if slot != self.editor_drop_target:
            self.editor_drop_target = slot
            self._show_editor_drop_slot(slot)
            if slot is not None:
                self.editor_status.configure(text=self._describe_editor_slot(slot))

    def _editor_drag_release(self, event: tk.Event) -> None:
        if self.editor_drag_index is None or not self.editor_view.winfo_ismapped():
            return
        source = self.editor_drag_index
        self.editor_drag_index = None
        slot = self.editor_drop_target
        if slot is None:
            slot = self._editor_slot_at(event.x_root, event.y_root)
        self.editor_drop_target = None
        self._show_editor_drop_slot(None)
        self.configure(cursor="")
        try:
            self.grab_release()
        except tk.TclError:
            pass
        if slot is None:
            self._highlight_editor_selection()
            self.editor_status.configure(text=f"Page {source + 1} sélectionnée")
            return
        new_order, new_position = move_page_to_slot(self.editor_order, source, slot)
        if new_order == self.editor_order:
            self._highlight_editor_selection()
            self.editor_status.configure(text=f"Page {source + 1} conservée à sa position")
            return
        self._editor_commit(new_order, new_position)

    def _cancel_editor_drag(self) -> None:
        if self.editor_drag_index is None:
            return
        self.editor_drag_index = None
        self.editor_drop_target = None
        self._show_editor_drop_slot(None)
        self.configure(cursor="")
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self._highlight_editor_selection()

    def _highlight_editor_selection(self) -> None:
        for position, card in self.editor_cards.items():
            selected = position == self.editor_selected
            card.configure(
                highlightthickness=3 if selected else 1,
                highlightbackground=ACCENT if selected else BORDER,
            )

    def _editor_commit(
        self,
        new_order: list[int],
        selected: int | None,
        new_rotations: dict[int, int] | None = None,
        rerender_pages: set[int] | None = None,
    ) -> None:
        self.editor_history.append((self.editor_order.copy(), self.editor_rotations.copy()))
        self.editor_future.clear()
        self.editor_order = new_order
        if new_rotations is not None:
            self.editor_rotations = new_rotations
        self.editor_selected = selected
        if rerender_pages:
            self._editor_rerender_pages(rerender_pages)
        else:
            self._render_editor_grid()
        self.editor_status.configure(text=f"{len(self.editor_order)} page(s) dans le document")

    def _editor_move(self, direction: int) -> None:
        if self.editor_selected is None:
            return
        target = self.editor_selected + direction
        if not 0 <= target < len(self.editor_order):
            return
        new_order = self.editor_order.copy()
        new_order[self.editor_selected], new_order[target] = new_order[target], new_order[self.editor_selected]
        self._editor_commit(new_order, target)

    def _editor_delete(self) -> None:
        if self.editor_selected is None:
            return
        new_order = self.editor_order.copy()
        new_order.pop(self.editor_selected)
        selected = min(self.editor_selected, len(new_order) - 1) if new_order else None
        self._editor_commit(new_order, selected)

    def _editor_rotate(self, delta: int) -> None:
        if self.editor_selected is None or self.editor_source is None:
            return
        source_page = self.editor_order[self.editor_selected]
        rotations = self.editor_rotations.copy()
        rotation = (rotations.get(source_page, 0) + delta) % 360
        if rotation:
            rotations[source_page] = rotation
        else:
            rotations.pop(source_page, None)
        self._editor_commit(self.editor_order.copy(), self.editor_selected, rotations, {source_page})
        direction = "droite" if delta > 0 else "gauche"
        self.editor_status.configure(text=f"Page {self.editor_selected + 1} tournée de 90° vers la {direction}")

    def _editor_rerender_pages(self, page_indices: set[int]) -> None:
        if self.editor_source is None:
            return
        scale = self.editor_zoom_var.get()
        width = int(170 * scale)
        height = int(220 * scale)
        for page_index in page_indices:
            self.editor_photos.pop(page_index, None)
        self._render_editor_grid()
        token = self.editor_token
        for page_index in page_indices:
            rotation = self.editor_rotations.get(page_index, 0)
            threading.Thread(
                target=self._editor_render_one_worker,
                args=(self.editor_source, token, page_index, width, height, rotation),
                daemon=True,
            ).start()

    def _editor_undo(self) -> None:
        if not self.editor_history:
            return
        self.editor_future.append((self.editor_order.copy(), self.editor_rotations.copy()))
        previous_order, previous_rotations = self.editor_history.pop()
        changed_rotations = {
            page_index
            for page_index in set(self.editor_rotations) | set(previous_rotations)
            if self.editor_rotations.get(page_index, 0) != previous_rotations.get(page_index, 0)
        }
        self.editor_order = previous_order
        self.editor_rotations = previous_rotations
        self.editor_selected = min(self.editor_selected or 0, len(self.editor_order) - 1) if self.editor_order else None
        if changed_rotations:
            self._editor_rerender_pages(changed_rotations)
        else:
            self._render_editor_grid()

    def _editor_redo(self) -> None:
        if not self.editor_future:
            return
        self.editor_history.append((self.editor_order.copy(), self.editor_rotations.copy()))
        next_order, next_rotations = self.editor_future.pop()
        changed_rotations = {
            page_index
            for page_index in set(self.editor_rotations) | set(next_rotations)
            if self.editor_rotations.get(page_index, 0) != next_rotations.get(page_index, 0)
        }
        self.editor_order = next_order
        self.editor_rotations = next_rotations
        self.editor_selected = min(self.editor_selected or 0, len(self.editor_order) - 1) if self.editor_order else None
        if changed_rotations:
            self._editor_rerender_pages(changed_rotations)
        else:
            self._render_editor_grid()

    def _update_editor_actions(self) -> None:
        selected = self.editor_selected
        count = len(self.editor_order)
        self.editor_left_button.configure(state="normal" if selected is not None and selected > 0 else "disabled")
        self.editor_right_button.configure(state="normal" if selected is not None and selected < count - 1 else "disabled")
        self.editor_delete_button.configure(state="normal" if selected is not None else "disabled")
        self.editor_rotate_left_button.configure(state="normal" if selected is not None else "disabled")
        self.editor_rotate_right_button.configure(state="normal" if selected is not None else "disabled")
        self.editor_undo_button.configure(state="normal" if self.editor_history else "disabled")
        self.editor_redo_button.configure(state="normal" if self.editor_future else "disabled")
        self.editor_save_button.configure(state="normal" if count else "disabled")

    def _scroll_editor(self, event: tk.Event) -> str:
        self.editor_canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def save_editor_pdf(self) -> None:
        if self.editor_source is None or not self.editor_order:
            return
        suggested = self.editor_source.with_name(f"{self.editor_source.stem}_modifie.pdf")
        selected = filedialog.asksaveasfilename(
            title="Enregistrer le PDF modifié",
            defaultextension=".pdf",
            initialfile=suggested.name,
            initialdir=str(suggested.parent),
            filetypes=[("Document PDF", "*.pdf")],
        )
        if not selected:
            return
        destination = Path(selected).resolve()
        if destination == self.editor_source:
            messagebox.showerror(APP_NAME, "Enregistrez le résultat sous un nouveau nom afin de préserver le document source.")
            return
        self.editor_save_button.configure(state="disabled", text="Enregistrement…")
        self.editor_progress.pack(side="right")
        self.editor_progress.start(12)
        self.editor_status.configure(text="Création du PDF modifié…")
        source = self.editor_source
        order = self.editor_order.copy()
        rotations = self.editor_rotations.copy()
        threading.Thread(target=self._editor_save_worker, args=(source, destination, order, rotations), daemon=True).start()

    def _editor_save_worker(self, source: Path, destination: Path, order: list[int], rotations: dict[int, int]) -> None:
        try:
            pages = reorder_pdf(source, destination, order, rotations)
            self.events.put(("editor_saved", (destination, pages)))
        except Exception as exc:
            self.events.put(("editor_save_error", str(exc)))

    def add_files(self) -> None:
        selected = filedialog.askopenfilenames(title="Choisir les PDF", filetypes=[("Documents PDF", "*.pdf")])
        if selected:
            self._load_paths([Path(path) for path in selected])

    def add_folder(self) -> None:
        selected = filedialog.askdirectory(title="Choisir un dossier contenant des PDF")
        if selected:
            paths = sorted(Path(selected).glob("*.pdf"), key=lambda p: p.name.casefold())
            if not paths:
                messagebox.showinfo(APP_NAME, "Ce dossier ne contient aucun fichier PDF.")
            else:
                self._load_paths(paths)

    def _drop_enter(self, event: object) -> str:
        self.drop_hint.configure(bg="#DDE5FF", text="Relâchez pour ajouter les documents")
        return getattr(event, "action", "copy")

    def _drop_leave(self, event: object) -> str:
        self._reset_drop_hint()
        return getattr(event, "action", "copy")

    def _on_drop(self, event: object) -> str:
        self._reset_drop_hint()
        data = getattr(event, "data", "")
        raw_paths = list(self.tk.splitlist(data)) if data else []
        paths = collect_dropped_pdfs(raw_paths)
        if paths:
            self._load_paths(paths)
        else:
            self.status.configure(text="Le dépôt ne contient aucun fichier PDF")
        return getattr(event, "action", "copy")

    def _reset_drop_hint(self) -> None:
        self.drop_hint.configure(bg="#EEF2FF", text="↓  Glissez-déposez ici vos PDF ou un dossier")

    def _load_paths(self, paths: list[Path]) -> None:
        existing = {item.path for item in self.items}
        errors: list[str] = []
        added = 0
        for path in paths:
            resolved = path.resolve()
            if resolved in existing:
                continue
            try:
                self.items.append(inspect_pdf(path))
                existing.add(resolved)
                added += 1
            except ValueError as exc:
                errors.append(f"• {path.name} — {exc}")
        self._refresh()
        if errors:
            messagebox.showwarning("Certains fichiers ont été ignorés", "\n".join(errors[:8]))
        self.status.configure(text=f"{added} document(s) ajouté(s)" if added else "Aucun nouveau document ajouté")

    def _refresh(self, selected_indices: list[int] | None = None) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(self.items):
            self.tree.insert("", "end", iid=str(index), values=(index + 1, item.path.name, f"{len(item.selected_pages)} / {item.pages}", human_size(item.size)))
        has_items = bool(self.items)
        state = "normal" if has_items else "disabled"
        self.clear_button.configure(state=state)
        self.up_button.configure(state=state)
        self.down_button.configure(state=state)
        self.remove_button.configure(state=state)
        self._update_merge_state()
        if has_items:
            self.empty.place_forget()
        else:
            self.empty.place(relx=.5, rely=.48, anchor="center")
        if selected_indices:
            for index in selected_indices:
                if 0 <= index < len(self.items):
                    self.tree.selection_add(str(index))
        if not self.tree.selection():
            self._clear_preview()

    def _selected_page_count(self) -> int:
        return sum(len(item.selected_pages) for item in self.items)

    def _update_merge_state(self) -> None:
        state = "normal" if self._selected_page_count() else "disabled"
        self.merge_button.configure(state=state)
        self.merge_edit_button.configure(state=state)

    def _selection_changed(self, _event: object = None) -> None:
        selection = self.tree.selection()
        if not selection:
            self._clear_preview()
            return
        item = self.items[int(selection[0])]
        self.preview_token += 1
        token = self.preview_token
        self.current_preview_item = item
        self.preview_photos.clear()
        self.preview_labels.clear()
        self.preview_vars.clear()
        for child in self.preview_pages.winfo_children():
            child.destroy()
        self.preview_name.configure(text=item.path.name)
        self._update_preview_details()
        self.select_all_button.configure(state="normal")
        self.select_none_button.configure(state="normal")
        for page_index in range(item.pages):
            card = tk.Frame(self.preview_pages, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
            card.pack(fill="x", padx=8, pady=(8, 0))
            variable = tk.BooleanVar(value=page_index in item.selected_pages)
            self.preview_vars[page_index] = variable
            check = tk.Checkbutton(
                card,
                text=f"Page {page_index + 1}",
                variable=variable,
                command=lambda i=page_index, doc=item: self._toggle_page(doc, i),
                bg=SURFACE,
                activebackground=SURFACE,
                fg=INK,
                selectcolor=SURFACE,
                anchor="w",
                padx=9,
                pady=7,
                font=("Segoe UI Semibold", 9),
            )
            check.pack(fill="x")
            label = tk.Label(card, text="Chargement…", bg="#F7F8FA", fg=MUTED, height=12, font=("Segoe UI", 9))
            label.pack(fill="x", padx=9, pady=(0, 9))
            for widget in (card, check, label):
                widget.bind("<MouseWheel>", self._scroll_preview)
            self.preview_labels[page_index] = label
        self.preview_canvas.yview_moveto(0)
        threading.Thread(target=self._preview_worker, args=(item.path, token), daemon=True).start()

    def _preview_worker(self, path: Path, token: int) -> None:
        try:
            with pymupdf.open(path) as document:
                for page_index in range(document.page_count):
                    if token != self.preview_token:
                        return
                    page = document[page_index]
                    rect = page.rect
                    zoom = min(240 / rect.width, 300 / rect.height, 2.0)
                    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
                    self.events.put(("preview_page", (token, page_index, pixmap.tobytes("png"))))
        except Exception as exc:
            self.events.put(("preview_error", (token, str(exc))))

    def _toggle_page(self, item: PdfItem, page_index: int) -> None:
        variable = self.preview_vars.get(page_index)
        if variable and variable.get():
            item.selected_pages.add(page_index)
        else:
            item.selected_pages.discard(page_index)
        self._update_item_row(item)
        self._update_preview_details()
        self._update_merge_state()

    def _set_all_pages(self, selected: bool) -> None:
        item = self.current_preview_item
        if item is None:
            return
        item.selected_pages = set(range(item.pages)) if selected else set()
        for page_index, variable in self.preview_vars.items():
            variable.set(page_index in item.selected_pages)
        self._update_item_row(item)
        self._update_preview_details()
        self._update_merge_state()

    def _update_item_row(self, item: PdfItem) -> None:
        try:
            index = self.items.index(item)
        except ValueError:
            return
        self.tree.item(str(index), values=(index + 1, item.path.name, f"{len(item.selected_pages)} / {item.pages}", human_size(item.size)))

    def _update_preview_details(self) -> None:
        item = self.current_preview_item
        if item is not None:
            self.preview_details.configure(text=f"{len(item.selected_pages)} sur {item.pages} page(s) sélectionnée(s)  •  {human_size(item.size)}")

    def _scroll_preview(self, event: tk.Event) -> str:
        self.preview_canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _clear_preview(self) -> None:
        self.preview_token += 1
        self.current_preview_item = None
        self.preview_photos.clear()
        self.preview_labels.clear()
        self.preview_vars.clear()
        for child in self.preview_pages.winfo_children():
            child.destroy()
        self.preview_empty = tk.Label(self.preview_pages, text="Sélectionnez un document\npour afficher toutes ses pages", bg="#EDF0F4", fg=MUTED, justify="center", font=("Segoe UI", 9))
        self.preview_empty.pack(fill="both", expand=True, padx=12, pady=80)
        self.preview_name.configure(text="Aucun document sélectionné")
        self.preview_details.configure(text="")
        self.select_all_button.configure(state="disabled")
        self.select_none_button.configure(state="disabled")

    def move(self, direction: int) -> None:
        selected = sorted(int(i) for i in self.tree.selection())
        if not selected:
            return
        order = selected if direction < 0 else list(reversed(selected))
        moved: list[int] = []
        selected_set = set(selected)
        for index in order:
            target = index + direction
            if 0 <= target < len(self.items) and target not in selected_set:
                self.items[index], self.items[target] = self.items[target], self.items[index]
                selected_set.remove(index)
                selected_set.add(target)
                moved.append(target)
        self._refresh(sorted(selected_set))

    def remove_selected(self) -> None:
        selected = sorted((int(i) for i in self.tree.selection()), reverse=True)
        for index in selected:
            self.items.pop(index)
        self._refresh()
        self.status.configure(text=f"{len(self.items)} document(s) dans la liste")

    def clear_all(self) -> None:
        self.items.clear()
        self._refresh()
        self.status.configure(text="Liste vidée")

    def open_selected(self) -> None:
        selection = self.tree.selection()
        if selection:
            os.startfile(self.items[int(selection[0])].path)  # type: ignore[attr-defined]

    def start_merge(self) -> None:
        suggested = str(self.items[0].path.with_name("documents_fusionnes.pdf"))
        selected = filedialog.asksaveasfilename(title="Enregistrer le PDF fusionné", defaultextension=".pdf", initialfile=Path(suggested).name, initialdir=str(Path(suggested).parent), filetypes=[("Document PDF", "*.pdf")])
        if not selected:
            return
        destination = Path(selected)
        inputs = [item.path for item in self.items]
        page_selections = [sorted(item.selected_pages) for item in self.items]
        if destination.resolve() in inputs:
            messagebox.showerror(APP_NAME, "Le fichier de destination ne peut pas être l’un des PDF sources.")
            return
        self._set_busy(True, editing=False)
        threading.Thread(target=self._merge_worker, args=(inputs, page_selections, destination, False), daemon=True).start()

    def start_merge_and_edit(self) -> None:
        if not self._selected_page_count():
            return
        inputs = [item.path for item in self.items]
        page_selections = [sorted(item.selected_pages) for item in self.items]
        fd, raw_path = tempfile.mkstemp(prefix="fusion-a-editer-", suffix=".pdf", dir=self._temp_dir)
        os.close(fd)
        destination = Path(raw_path)
        self._set_busy(True, editing=True)
        threading.Thread(target=self._merge_worker, args=(inputs, page_selections, destination, True), daemon=True).start()

    def _merge_worker(self, inputs: list[Path], page_selections: list[list[int]], destination: Path, open_editor: bool) -> None:
        try:
            pages = merge_pdfs(inputs, destination, page_selections)
            self.events.put(("edit_ready" if open_editor else "success", (destination, pages)))
        except Exception as exc:  # surface unexpected parser/write failures cleanly
            if open_editor:
                destination.unlink(missing_ok=True)
            self.events.put(("error", str(exc)))

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "preview_page":
                    token, page_index, png = payload  # type: ignore[misc]
                    if token == self.preview_token:
                        encoded = base64.b64encode(png).decode("ascii")
                        photo = tk.PhotoImage(data=encoded)
                        self.preview_photos[page_index] = photo
                        label = self.preview_labels.get(page_index)
                        if label:
                            label.configure(image=photo, text="", height=0)
                elif kind == "preview_error":
                    token, _error = payload  # type: ignore[misc]
                    if token == self.preview_token:
                        for label in self.preview_labels.values():
                            if not label.cget("image"):
                                label.configure(text="Aperçu indisponible")
                elif kind == "editor_preview":
                    token, source_page, rotation, png = payload  # type: ignore[misc]
                    if token == self.editor_token and rotation == self.editor_rotations.get(source_page, 0) % 360:
                        encoded = base64.b64encode(png).decode("ascii")
                        photo = tk.PhotoImage(data=encoded)
                        self.editor_photos[source_page] = photo
                        label = self.editor_image_labels.get(source_page)
                        if label:
                            scale = self.editor_zoom_var.get()
                            label.configure(image=photo, text="", width=int(170 * scale), height=int(220 * scale))
                elif kind == "editor_preview_error":
                    token, error = payload  # type: ignore[misc]
                    if token == self.editor_token:
                        self.editor_status.configure(text=f"Certains aperçus sont indisponibles : {error}")
                elif kind == "editor_saved":
                    destination, pages = payload  # type: ignore[misc]
                    self.editor_progress.stop()
                    self.editor_progress.pack_forget()
                    self.editor_save_button.configure(state="normal", text="Enregistrer une copie")
                    self.last_output = destination
                    self.open_button.configure(state="normal")
                    self.editor_status.configure(text=f"Copie enregistrée — {pages} page(s) : {destination.name}")
                    messagebox.showinfo("PDF enregistré", f"Le PDF modifié a été créé :\n\n{destination}")
                elif kind == "editor_save_error":
                    self.editor_progress.stop()
                    self.editor_progress.pack_forget()
                    self.editor_save_button.configure(state="normal", text="Enregistrer une copie")
                    self.editor_status.configure(text="L’enregistrement a échoué")
                    messagebox.showerror("Erreur pendant l’enregistrement", str(payload))
                elif kind == "success":
                    self._set_busy(False)
                    destination, pages = payload  # type: ignore[misc]
                    self.last_output = destination
                    self.open_button.configure(state="normal")
                    self.status.configure(text=f"Fusion terminée — {pages} pages")
                    messagebox.showinfo("Fusion terminée", f"Le fichier a été créé avec succès :\n\n{destination}")
                elif kind == "edit_ready":
                    self._set_busy(False)
                    destination, pages = payload  # type: ignore[misc]
                    self.open_editor(destination, temporary=True, display_name="Fusion non enregistrée")
                    self.editor_status.configure(text=f"Fusion temporaire prête — {pages} page(s). Organisez-les puis enregistrez une copie.")
                else:
                    self._set_busy(False)
                    self.status.configure(text="La fusion a échoué", foreground=ERROR)
                    messagebox.showerror("Erreur pendant la fusion", str(payload))
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _set_busy(self, busy: bool, editing: bool = False) -> None:
        if busy:
            self.merge_button.configure(state="disabled", text="Fusion en cours…" if not editing else "Fusionner les PDF")
            self.merge_edit_button.configure(state="disabled", text="Préparation…" if editing else "Fusionner et éditer")
            self.status.configure(text="Création du document…", foreground=MUTED)
            self.progress.pack(side="right", padx=(0, 12))
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.pack_forget()
            state = "normal" if self._selected_page_count() else "disabled"
            self.merge_button.configure(state=state, text="Fusionner les PDF")
            self.merge_edit_button.configure(state=state, text="Fusionner et éditer")
            self.status.configure(foreground=MUTED)

    def open_output(self) -> None:
        if self.last_output and self.last_output.exists():
            os.startfile(self.last_output)  # type: ignore[attr-defined]
        else:
            self.open_button.configure(state="disabled")

    def _remove_editor_temp(self) -> None:
        path = self.editor_temp_source
        self.editor_temp_source = None
        if path is None:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    def _on_close(self) -> None:
        self.preview_token += 1
        self.editor_token += 1
        self._cancel_editor_drag()
        shutil.rmtree(self._temp_dir, ignore_errors=True)
        self.destroy()


def main() -> None:
    app = FusionPdfApp()
    app.mainloop()


if __name__ == "__main__":
    main()
