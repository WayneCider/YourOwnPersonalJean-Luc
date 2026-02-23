"""PDF reading tool for YOPJ."""

import os


def pdf_read(path: str, pages: str = "") -> str:
    """Read a PDF file and extract text content.

    Args:
        path: Path to the PDF file
        pages: Optional page range (e.g. "1-5", "3", "1,3,5")

    Returns:
        Extracted text with [PAGE N] markers
    """
    try:
        import pdfplumber
    except ImportError:
        return "Error: pdfplumber is not installed. Run: pip install pdfplumber"

    if not os.path.exists(path):
        return f"Error: File not found: {path}"

    if not path.lower().endswith('.pdf'):
        return f"Error: Not a PDF file: {path}"

    try:
        with pdfplumber.open(path) as pdf:
            total_pages = len(pdf.pages)
            if total_pages == 0:
                return f"Error: PDF has no pages (may be encrypted/locked): {path}"

            if pages:
                page_indices = _parse_page_range(pages, total_pages)
            else:
                page_indices = list(range(total_pages))

            output = []
            for i in page_indices:
                page = pdf.pages[i]
                text = page.extract_text() or ""

                if not text.strip():
                    tables = page.extract_tables()
                    if tables:
                        for table in tables:
                            for row in table:
                                text += "\t".join(
                                    str(cell) if cell else "" for cell in row
                                ) + "\n"

                if not text.strip():
                    text = "[No extractable text — this page may be a scanned image]"

                output.append(f"[PAGE {i + 1}]\n{text}")

            result = (
                f"[PDF: {os.path.basename(path)} — {total_pages} pages]\n\n"
                + "\n\n".join(output)
            )

            if len(result) > 200000:
                result = result[:200000] + "\n\n[OUTPUT TRUNCATED at 200,000 characters]"

            return result

    except Exception as e:
        return f"Error reading PDF: {type(e).__name__}: {e}"


def _parse_page_range(pages: str, total: int) -> list:
    """Parse a page range string into a list of 0-based page indices."""
    indices = []
    for part in pages.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            start = max(1, int(start.strip()))
            end = min(total, int(end.strip()))
            indices.extend(range(start - 1, end))
        else:
            page = int(part.strip())
            if 1 <= page <= total:
                indices.append(page - 1)
    return sorted(set(indices))


def register_tools(registry):
    """Register pdf_read as an optional YOPJ tool."""
    registry.register_tool(
        "pdf_read",
        pdf_read,
        "Read PDF file content"
    )
