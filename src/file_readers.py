"""
Turn downloaded Seafile files into content Claude can read.

- Text files are decoded and returned as text.
- PDFs return their text layer. Pages without one (scans) are rendered to
  images so Claude can read them with vision.
- Images are downscaled and returned as images, so Claude reads them
  directly instead of going through OCR.

These functions are CPU-bound and synchronous; call them from a worker thread.
"""

import io
import os

import pypdfium2 as pdfium
from mcp.server.mcpserver import Image
from PIL import Image as PILImage
from PIL import ImageOps
from pypdf import PdfReader
from pypdf.errors import PdfReadError

# Longest side of images sent to Claude. Larger images are downscaled by the
# model anyway, so sending more pixels only costs bandwidth and tokens.
MAX_IMAGE_SIDE = 1568

# Cap on text returned in one call, so a huge PDF or log file can't flood the context
MAX_TEXT_CHARS = int(os.getenv("MAX_TEXT_CHARS", "100000"))

# Max scanned pages rendered to images in one call
MAX_SCANNED_PAGES = 5

# A page with less extracted text than this is treated as scanned
MIN_TEXT_CHARS_PER_PAGE = 20

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}


class UnsupportedFileError(Exception):
    """Raised when a file can't be turned into text or images."""


def detect_kind(path: str, data: bytes) -> str:
    """Classify a file as "pdf", "image" or "text" from its bytes and extension."""
    ext = os.path.splitext(path)[1].lower()
    if data.startswith(b"%PDF") or ext == ".pdf":
        return "pdf"
    if ext in IMAGE_EXTENSIONS or data.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"BM")) or data[8:12] == b"WEBP":
        return "image"
    return "text"


def read_text(data: bytes) -> str:
    """Decode a text file, rejecting binary files."""
    if b"\x00" in data[:8192]:
        raise UnsupportedFileError("This looks like a binary file. Use get_file_download_link to download it instead.")
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("latin-1")
    return truncate(text, "Use get_file_download_link to get the full file.")


def read_image(data: bytes) -> Image:
    """Downscale an image and re-encode it for Claude."""
    try:
        img = PILImage.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
    except (OSError, PILImage.DecompressionBombError) as e:
        raise UnsupportedFileError(f"Could not open image: {e}")
    return encode_image(img)


def read_pdf(data: bytes, page_start: int, max_pages: int) -> list[str | Image]:
    """Extract text from a range of PDF pages; render text-less pages as images."""
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise UnsupportedFileError("This PDF is password-protected.")
        total = len(reader.pages)
    except PdfReadError as e:
        raise UnsupportedFileError(f"Could not read PDF: {e}")

    if total == 0:
        return ["PDF has no pages."]
    first = max(1, page_start)
    if first > total:
        raise UnsupportedFileError(f"page_start {first} is past the end of the PDF ({total} pages).")
    last = min(total, first + max(1, max_pages) - 1)

    texts = {}
    for number in range(first, last + 1):
        try:
            texts[number] = (reader.pages[number - 1].extract_text() or "").strip()
        except Exception:
            texts[number] = ""

    scanned = [n for n, text in texts.items() if len(text) < MIN_TEXT_CHARS_PER_PAGE]
    rendered = scanned[:MAX_SCANNED_PAGES]

    header = f"PDF with {total} pages. Showing pages {first}-{last}."
    if last < total:
        header += f" Call again with page_start={last + 1} for more."
    if rendered:
        header += f" Pages {', '.join(map(str, rendered))} have no text layer and are included as images."
    if len(scanned) > len(rendered):
        skipped = scanned[len(rendered):]
        header += f" Scanned pages {', '.join(map(str, skipped))} were not rendered; request them with page_start."

    body = "\n\n".join(f"--- Page {n} ---\n{text}" for n, text in texts.items() if n not in scanned)
    content: list[str | Image] = [header]
    if body:
        content.append(truncate(body, "Use page_start and max_pages to read the rest."))
    if rendered:
        content.extend(render_pdf_pages(data, rendered))
    return content


def render_pdf_pages(data: bytes, page_numbers: list[int]) -> list[str | Image]:
    """Render PDF pages (1-based) to images, each preceded by a page label."""
    pdf = pdfium.PdfDocument(data)
    try:
        content: list[str | Image] = []
        for number in page_numbers:
            page = pdf[number - 1]
            width, height = page.get_size()
            scale = MAX_IMAGE_SIDE / max(width, height)
            content.append(f"--- Page {number} (image) ---")
            content.append(encode_image(page.render(scale=scale).to_pil()))
        return content
    finally:
        pdf.close()


def encode_image(img: PILImage.Image) -> Image:
    """Downscale to MAX_IMAGE_SIDE and encode as JPEG (or PNG when transparent)."""
    if getattr(img, "is_animated", False):
        img.seek(0)
    img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    buf = io.BytesIO()
    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    if has_alpha:
        img.save(buf, format="PNG", optimize=True)
        return Image(data=buf.getvalue(), format="png")
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    return Image(data=buf.getvalue(), format="jpeg")


def truncate(text: str, hint: str) -> str:
    """Cut text to MAX_TEXT_CHARS with a note saying so."""
    if len(text) <= MAX_TEXT_CHARS:
        return text
    return text[:MAX_TEXT_CHARS] + f"\n\n[Truncated at {MAX_TEXT_CHARS} of {len(text)} characters. {hint}]"
