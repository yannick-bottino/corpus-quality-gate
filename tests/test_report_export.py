import json, os
from cqg.registry.loader import load_registry
from cqg.models import DocScore, CriterionScore
from cqg.report import write_doc_json, write_corpus_report

def _ds(doc_id):
    crit = CriterionScore(id="1.3", tag="D", weight=1, status="scored",
                          score=2, justification="faible", evidence="p.1")
    return DocScore(doc_id=doc_id, global_pct=65.0, level="Insuffisant",
                    coverage_pct=80.0, dimensions={"1": 65.0}, criteria=[crit],
                    worst_sections=[], flags=[], config_hash="h")

def test_write_doc_json(tmp_path):
    path = write_doc_json(_ds("d1"), str(tmp_path))
    assert json.loads(open(path, encoding="utf-8").read())["doc_id"] == "d1"

def test_write_corpus_report(tmp_path):
    paths = write_corpus_report([_ds("d1"), _ds("d2")], load_registry(), str(tmp_path))
    assert os.path.exists(paths["xlsx"])
    assert "d1" in open(paths["csv_synthese"], encoding="utf-8").read()
    # remediation : critere score<=2 present
    assert "1.3" in open(paths["csv_remediation"], encoding="utf-8").read()

def test_csv_escapes_special_chars(tmp_path):
    import csv as _csvmod
    crit = CriterionScore(id="1.3", tag="D", weight=1, status="scored", score=2,
                          justification="faible; voir page 1\nligne 2", evidence="p.1")
    ds = DocScore(doc_id="d;x", global_pct=65.0, level="Insuffisant", coverage_pct=80.0,
                  dimensions={"1": 65.0}, criteria=[crit], worst_sections=[], flags=[], config_hash="h")
    paths = write_corpus_report([ds], load_registry(), str(tmp_path))
    with open(paths["csv_detail"], encoding="utf-8-sig", newline="") as f:
        rows = list(_csvmod.reader(f, delimiter=";"))
    header, data = rows[0], rows[1]
    assert len(data) == len(header)
    assert any("faible; voir page 1" in cell for cell in data)

def test_csv_neutralizes_formula_injection(tmp_path):
    import csv as _csvmod
    crit = CriterionScore(id="1.3", tag="D", weight=1, status="scored", score=2,
                          justification="=SUM(A1:A9)", evidence="p.1")
    ds = DocScore(doc_id="d1", global_pct=65.0, level="Insuffisant", coverage_pct=80.0,
                  dimensions={"1": 65.0}, criteria=[crit], worst_sections=[], flags=[], config_hash="h")
    paths = write_corpus_report([ds], load_registry(), str(tmp_path))
    with open(paths["csv_detail"], encoding="utf-8-sig", newline="") as f:
        rows = list(_csvmod.reader(f, delimiter=";"))
    assert any(cell.startswith("'=SUM") for cell in rows[1])
