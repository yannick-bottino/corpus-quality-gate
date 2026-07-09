from scripts.check_licenses import forbidden_packages


def test_flags_banned_packages():
    installed = ["docling", "pymupdf4llm", "semhash", "pyiqa", "pymupdf"]
    assert set(forbidden_packages(installed)) == {"pymupdf4llm", "pyiqa", "pymupdf"}


def test_clean_env_returns_empty():
    assert forbidden_packages(["docling", "semhash", "openpyxl"]) == []


def test_new_parsing_deps_not_banned():
    installed = ["pdfminer.six", "pdfplumber", "pypdfium2", "pillow", "pypdf"]
    assert forbidden_packages(installed) == []


def test_docling_removed_from_declared_deps():
    import tomllib
    import pathlib

    data = tomllib.loads(pathlib.Path("pyproject.toml").read_text(encoding="utf-8"))
    assert not any(d.lower().startswith("docling") for d in data["project"]["dependencies"])
