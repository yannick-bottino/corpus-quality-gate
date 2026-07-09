import sys

BANNED = {"pyiqa", "marker-pdf", "maverick-coref", "pymupdf4llm", "pymupdf"}


def forbidden_packages(installed: list[str]) -> list[str]:
    return [p for p in installed if p.lower() in BANNED]


def _installed_names() -> list[str]:
    from importlib import metadata

    return [d.metadata["Name"] for d in metadata.distributions()]


if __name__ == "__main__":
    bad = forbidden_packages(_installed_names())
    if bad:
        print(f"Licences interdites detectees: {bad}")
        sys.exit(1)
    print("Licences OK")
