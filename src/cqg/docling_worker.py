"""Docling worker isolated in a subprocess: an OOM (SIGKILL 137) kills the worker without
bringing down the parent pipeline, which detects the returncode and switches to legacy.

Usage: python -m cqg.docling_worker <pdf_path> <out_markdown_path> [start] [end]
start/end: 1-based inclusive page range (batch processing). Absent = whole document.
Exit 0 on success, non-zero on any error.
"""
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) not in (3, 5):
        return 2
    pdf_path, out_path = argv[1], argv[2]
    page_range = (int(argv[3]), int(argv[4])) if len(argv) == 5 else None
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions

    opts = PdfPipelineOptions()
    opts.do_ocr = False
    opts.do_table_structure = True
    opts.generate_page_images = False
    opts.generate_picture_images = False
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
    if page_range is not None:
        result = converter.convert(pdf_path, page_range=page_range)
    else:
        result = converter.convert(pdf_path)
    Path(out_path).write_text(result.document.export_to_markdown(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception:
        sys.exit(1)
