"""Point d'entree racine : permet `python main.py run|golden <corpus> --config ...`
sans installation prealable (ajoute src/ au chemin d'import)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from cqg.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
