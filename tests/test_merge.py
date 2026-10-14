from pathlib import Path

import pymupdf
from pypdf import PdfReader, PdfWriter

from app import CONTACT_EMAIL, collect_dropped_pdfs, human_size, inspect_pdf, merge_pdfs, move_page_to_slot, render_first_page, reorder_pdf, window_metrics


def make_pdf(path: Path, pages: int) -> None:
    writer = PdfWriter()
    for index in range(pages):
        writer.add_blank_page(width=200 + index, height=300)
    with path.open("wb") as stream:
        writer.write(stream)


def test_merge_preserves_order_and_page_count(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    output = tmp_path / "merged.pdf"
    make_pdf(first, 2)
    make_pdf(second, 3)

    assert merge_pdfs([first, second], output) == 5
    assert len(PdfReader(output).pages) == 5


def test_merge_only_selected_pages(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    output = tmp_path / "selection.pdf"
    make_pdf(first, 3)
    make_pdf(second, 2)

    assert merge_pdfs([first, second], output, [[0, 2], [1]]) == 3
    result = PdfReader(output)
    assert len(result.pages) == 3
    assert [float(page.mediabox.width) for page in result.pages] == [200.0, 202.0, 201.0]


def test_reorder_and_delete_pages(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "reordered.pdf"
    make_pdf(source, 4)

    assert reorder_pdf(source, output, [3, 1, 0]) == 3
    result = PdfReader(output)
    assert [float(page.mediabox.width) for page in result.pages] == [203.0, 201.0, 200.0]


def test_reorder_and_rotate_pages(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "rotated.pdf"
    make_pdf(source, 3)

    assert reorder_pdf(source, output, [2, 0], {2: 90, 0: 270}) == 2
    result = PdfReader(output)
    assert [page.rotation for page in result.pages] == [90, 270]
    with pymupdf.open(output) as rendered:
        assert (round(rendered[0].rect.width), round(rendered[0].rect.height)) == (300, 202)
        assert (round(rendered[1].rect.width), round(rendered[1].rect.height)) == (300, 200)


def test_move_page_between_pages() -> None:
    order = [0, 1, 2, 3]
    assert move_page_to_slot(order, 0, 3) == ([1, 2, 0, 3], 2)
    assert move_page_to_slot(order, 3, 1) == ([0, 3, 1, 2], 1)
    assert move_page_to_slot(order, 1, 2) == (order, 1)


def test_contact_email_is_correct() -> None:
    assert CONTACT_EMAIL == "francois.defaye@ac-limoges.fr"


def test_inspect_and_size(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 1)
    item = inspect_pdf(source)
    assert item.pages == 1
    assert item.selected_pages == {0}
    assert item.path == source.resolve()
    assert human_size(2048) == "2 Ko"


def test_first_page_preview_is_png(tmp_path: Path) -> None:
    source = tmp_path / "preview.pdf"
    make_pdf(source, 1)
    thumbnail = render_first_page(source)
    assert thumbnail.startswith(b"\x89PNG\r\n\x1a\n")


def test_collect_dropped_files_and_folder(tmp_path: Path) -> None:
    folder = tmp_path / "dossier avec espaces"
    folder.mkdir()
    first = folder / "B.pdf"
    second = folder / "a.PDF"
    ignored = folder / "notes.txt"
    first.touch()
    second.touch()
    ignored.touch()

    result = collect_dropped_pdfs([str(folder), str(first), str(ignored)])
    assert [path.name for path in result] == ["a.PDF", "B.pdf"]


def test_window_fits_720p_and_dpi_scaled_displays() -> None:
    native = window_metrics(1366, 720)
    scaled = window_metrics(1093, 576)

    assert native.height == 648
    assert native.min_height == 640
    assert native.compact
    assert scaled.width == 1069
    assert scaled.height == 504
    assert scaled.min_height == 504
    assert scaled.compact
