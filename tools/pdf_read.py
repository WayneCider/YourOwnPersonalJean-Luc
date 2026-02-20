"""Read PDF file contents with page markers and metadata.

Extracts text from PDF files using pdfplumber, returning page-delimited text
that the model can reference by page number. Handles encrypted PDFs, scan-only
PDFs, tables, and large documents gracefully.

Security: validates path against sandbox (confinement, symlink, size limits).
Requires: pip install pdfplumber
"""

import os
from pathlib import Path

from core.sandbox import get_sandbox

# Max pages to extract text from (context erosion defense)
MAX_PDF_PAGES = 200

# Max total characters to return (prevents context overflow)
MAX_PDF_CHARS = 200_000

# Max file size for PDFs (50 MB)
MAX_PDF_SIZE = 50 * 1024 * 1024


def pdf_read(path: str, pages: str = "") -> dict:
    """Read a PDF file and extract text with page markers.

    Args:
        path: Absolute or relative path to a PDF file.
        pages: Optional page range (e.g. "1-5", "3", "10-20"). 1-indexed.
               Empty string = all pages.

    Returns:
        dict with ok, content, page_count, total_chars, metadata, or ok=False with error.
    """
    # Normalize model-generated LaTeX escaping
    import re as _re
    if not os.path.exists(path):
        normalized = _re.sub(r'(?<=[A-Za-z])\\_(?=[A-Za-z])', '_', path)
        normalized = _re.sub(r'(?<=[A-Za-z])\\~(?=[A-Za-z])', '~', normalized)
        if normalized != path:
            path = normalized

    sandbox = get_sandbox()

    # Security check
    check = sandbox.validate_path(path, operation="read")
    if not check["ok"]:
        return {"ok": False, "error": check["error"]}

    p = Path(path)

    if not p.exists():
        return {"ok": False, "error": f"File not found: {path}"}

    if not p.is_file():
        return {"ok": False, "error": f"Not a file: {path}"}

    # Extension check
    if p.suffix.lower() != ".pdf":
        return {"ok": False, "error": f"Not a PDF file (extension: {p.suffix}): {path}"}

    # Size check
    try:
        size = p.stat().st_size
        if size > MAX_PDF_SIZE:
            return {
                "ok": False,
                "error": f"PDF too large ({size:,} bytes, max {MAX_PDF_SIZE:,}): {path}",
            }
        if size == 0:
            return {"ok": False, "error": f"Empty file: {path}"}
    except OSError as e:
        return {"ok": False, "error": f"Cannot stat file: {e}"}

    # Import pdfplumber (deferred so YOPJ still works without it installed)
    try:
        import pdfplumber
    except ImportError:
        return {
            "ok": False,
            "error": "pdfplumber is not installed. Run: pip install pdfplumber",
        }

    # Open and extract
    try:
        with pdfplumber.open(str(p)) as pdf:
            total_pages = len(pdf.pages)

            if total_pages == 0:
                return {"ok": False, "error": f"PDF has no pages: {path}"}

            # Parse page range
            page_indices = _parse_page_range(pages, total_pages)
            if isinstance(page_indices, str):
                # Error message returned
                return {"ok": False, "error": page_indices}

            # Extract metadata
            metadata = {}
            if pdf.metadata:
                for key in ("Title", "Author", "Creator", "Producer", "CreationDate"):
                    val = pdf.metadata.get(key)
                    if val:
                        metadata[key.lower()] = str(val)

            # Extract text page by page
            page_texts = []
            total_chars = 0
            warnings = []

            for idx in page_indices:
                if total_chars >= MAX_PDF_CHARS:
                    warnings.append(
                        f"Output truncated at {MAX_PDF_CHARS:,} chars "
                        f"(reached page {idx + 1} of {total_pages})"
                    )
                    break

                page = pdf.pages[idx]
                page_num = idx + 1  # 1-indexed for display

                # Extract text
                text = page.extract_text() or ""

                # Try table extraction if text is sparse
                if len(text.strip()) < 20:
                    tables = page.extract_tables()
                    if tables:
                        table_text = _format_tables(tables)
                        if table_text:
                            text = text + "\n" + table_text if text.strip() else table_text

                # Truncate if adding this page would exceed limit
                remaining = MAX_PDF_CHARS - total_chars
                if len(text) > remaining:
                    text = text[:remaining]
                    warnings.append(f"Page {page_num} truncated to fit character limit")

                page_texts.append(f"[PAGE {page_num}]\n{text}")
                total_chars += len(text)

            # Check for scan-only PDF
            if total_chars < 100 and total_pages > 0:
                warnings.append(
                    "Very little text extracted — this may be a scanned/image-only PDF. "
                    "OCR is not supported."
                )

            content = "\n\n".join(page_texts)

            result = {
                "ok": True,
                "content": content,
                "page_count": total_pages,
                "pages_extracted": len(page_texts),
                "total_chars": total_chars,
            }

            if metadata:
                result["metadata"] = metadata
            if warnings:
                result["warnings"] = warnings
            if pages:
                result["page_range"] = pages

            return result

    except Exception as e:
        err_str = str(e)
        # pdfplumber raises various exceptions for encrypted/corrupt PDFs
        if "password" in err_str.lower() or "encrypted" in err_str.lower():
            return {"ok": False, "error": f"Encrypted/password-protected PDF: {path}"}
        if "invalid" in err_str.lower() or "corrupt" in err_str.lower():
            return {"ok": False, "error": f"Corrupt or invalid PDF: {path}"}
        return {"ok": False, "error": f"PDF read error: {err_str}"}


def _parse_page_range(pages_str: str, total_pages: int) -> list[int] | str:
    """Parse a page range string into 0-indexed page indices.

    Args:
        pages_str: e.g. "1-5", "3", "10-20", "" (all pages)
        total_pages: total number of pages in the PDF

    Returns:
        list of 0-indexed page indices, or error string
    """
    if not pages_str or not pages_str.strip():
        # All pages, capped
        count = min(total_pages, MAX_PDF_PAGES)
        return list(range(count))

    pages_str = pages_str.strip()

    # Single page: "5"
    if pages_str.isdigit():
        page = int(pages_str)
        if page < 1 or page > total_pages:
            return f"Page {page} out of range (PDF has {total_pages} pages)"
        return [page - 1]

    # Range: "5-10"
    if "-" in pages_str:
        parts = pages_str.split("-", 1)
        try:
            start = int(parts[0].strip())
            end = int(parts[1].strip())
        except ValueError:
            return f"Invalid page range: {pages_str} (use e.g. '1-5' or '3')"

        if start < 1:
            start = 1
        if end > total_pages:
            end = total_pages
        if start > end:
            return f"Invalid page range: start ({start}) > end ({end})"

        count = end - start + 1
        if count > MAX_PDF_PAGES:
            end = start + MAX_PDF_PAGES - 1

        return list(range(start - 1, end))

    return f"Invalid page range: {pages_str} (use e.g. '1-5' or '3')"


def _format_tables(tables: list) -> str:
    """Format extracted tables as pipe-delimited text."""
    if not tables:
        return ""

    parts = []
    for table in tables:
        if not table:
            continue
        rows = []
        for row in table:
            cells = [str(cell or "").strip() for cell in row]
            rows.append("| " + " | ".join(cells) + " |")
        if rows:
            parts.append("\n".join(rows))

    return "\n\n".join(parts)
