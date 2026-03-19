import json
from pathlib import Path

from core.knowledge import parsers
from core.knowledge.parsers import (
    bootstrap_knowledge,
    build_lancedb_indexes,
    knowledge_summary,
    parse_account_chart,
    parse_institution_pdf,
    search_accounts,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_parse_account_chart_builds_paths() -> None:
    records = parse_account_chart(PROJECT_ROOT / "ai验证" / "会计科目表 (1).xls")
    item = next(row for row in records if row["code"] == "1020101")
    assert item["path"] == "银行存款/基本账户/基本户"
    assert item["is_leaf"] is True


def test_parse_institution_pdf_extracts_articles() -> None:
    chunks = parse_institution_pdf(PROJECT_ROOT / "ai验证" / "农村集体经济组织会计制度.pdf")
    assert chunks
    assert any("第一条" in chunk["article"] for chunk in chunks)


def test_bootstrap_knowledge_writes_outputs() -> None:
    result = bootstrap_knowledge(PROJECT_ROOT)
    assert Path(result["parsed"]["account_chart_json"]).exists()
    assert Path(result["parsed"]["institution_chunks_json"]).exists()
    assert result["indexes"]["backend"] == "lancedb"
    assert "available" in result["indexes"]


def test_search_accounts_records_status() -> None:
    bootstrap_knowledge(PROJECT_ROOT)
    query = "社区活动"
    search_accounts(PROJECT_ROOT, query, limit=2)
    status_path = PROJECT_ROOT / "knowledge" / "parsed" / "search_status.json"
    assert status_path.exists()
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["query"] == query
    assert status["backend"] in {"lancedb", "lancedb_fts", "lancedb_vector", "lancedb_hybrid", "json_fallback"}
    summary = knowledge_summary(PROJECT_ROOT)
    assert summary["search_status"]["query"] == query


def test_knowledge_summary_exposes_embedding_and_vector_flags(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.knowledge.parsers._embedding_runtime_status",
        lambda: {
            "available": True,
            "model_path": "F:/models/modelscope/models/Xorbits/bge-m3",
            "dimension": 1024,
            "error": "",
        },
    )
    parsed_dir = PROJECT_ROOT / "knowledge" / "parsed"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    (parsed_dir / "manifest.json").write_text(
        json.dumps({"account_count": 1, "institution_chunk_count": 1}, ensure_ascii=False),
        encoding="utf-8",
    )
    (parsed_dir / "account_chart.json").write_text("[]", encoding="utf-8")
    (parsed_dir / "index_status.json").write_text(
        json.dumps({"available": True, "vector_ready": True}, ensure_ascii=False),
        encoding="utf-8",
    )

    summary = knowledge_summary(PROJECT_ROOT)

    assert summary["embedding_runtime_ready"] is True
    assert summary["vector_search_ready"] is True


def test_search_accounts_merges_lancedb_fts_and_vector(monkeypatch) -> None:
    table = _FakeSearchTable(
        fts_rows=[
            _account_row("514070404", "社区活动支出", "公益支出/福利支出/文教医疗卫生/社区活动支出", score=0.91),
            _account_row("1020101", "基本户", "银行存款/基本账户/基本户", score=0.63, nature="贷"),
        ],
        vector_rows=[
            _account_row("514070404", "社区活动支出", "公益支出/福利支出/文教医疗卫生/社区活动支出", distance=0.02),
            _account_row("5140199", "其他", "公益支出/环境整治及长效管护/其他", distance=0.08),
        ],
    )
    monkeypatch.setattr(parsers, "connect", lambda _path: _FakeSearchDb(table))
    monkeypatch.setattr(
        parsers,
        "_embedding_runtime_status",
        lambda: {
            "backend": "sentence_transformers",
            "available": True,
            "model_path": "F:/models/modelscope/models/Xorbits/bge-m3",
            "dimension": 2,
            "error": "",
        },
    )
    monkeypatch.setattr(parsers, "_encode_texts", lambda texts: [[0.8, 0.2] for _ in texts])

    results, status = parsers._search_accounts_with_status(PROJECT_ROOT, "村公厕修理配件", limit=3)

    assert status["backend"] == "lancedb_hybrid"
    assert status["search_mode"] == "fts_plus_vector"
    assert status["vector_used"] is True
    assert results[0]["code"] == "514070404"
    assert set(results[0]["search_sources"]) == {"fts", "vector"}


def test_search_accounts_uses_fts_when_vector_runtime_is_unavailable(monkeypatch) -> None:
    table = _FakeSearchTable(
        fts_rows=[
            _account_row("1020101", "基本户", "银行存款/基本账户/基本户", score=0.88, nature="贷"),
        ],
        vector_rows=[],
    )
    monkeypatch.setattr(parsers, "connect", lambda _path: _FakeSearchDb(table))
    monkeypatch.setattr(
        parsers,
        "_embedding_runtime_status",
        lambda: {
            "backend": "sentence_transformers",
            "available": False,
            "model_path": "F:/models/modelscope/models/Xorbits/bge-m3",
            "dimension": 0,
            "error": "sentence-transformers missing",
        },
    )

    results, status = parsers._search_accounts_with_status(PROJECT_ROOT, "银行存款", limit=2)

    assert status["backend"] == "lancedb_fts"
    assert status["search_mode"] == "fts_only"
    assert status["vector_ready"] is False
    assert "missing" in status["vector_error"]
    assert results[0]["code"] == "1020101"


def test_search_accounts_falls_back_to_json_when_lancedb_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(parsers, "connect", lambda _path: (_ for _ in ()).throw(RuntimeError("rename denied")))
    monkeypatch.setattr(
        parsers,
        "_load_json_account_records",
        lambda _project_root: [
            {
                "code": "5140199",
                "name": "其他",
                "path": "公益支出/环境整治及长效管护/其他",
                "nature": "借",
                "is_leaf": True,
            },
            {
                "code": "1020101",
                "name": "基本户",
                "path": "银行存款/基本账户/基本户",
                "nature": "贷",
                "is_leaf": True,
            },
        ],
    )

    results, status = parsers._search_accounts_with_status(PROJECT_ROOT, "环境整治", limit=2)

    assert status["backend"] == "json_fallback"
    assert status["search_mode"] == "json_fallback"
    assert status["result_count"] == 2
    assert results[0]["code"] == "5140199"
    assert results[0]["search_sources"] == ["json_fallback"]


def test_build_lancedb_indexes_tracks_vector_capability(monkeypatch) -> None:
    account_table = _FakeIndexTable()
    institution_table = _FakeIndexTable()
    db = _FakeIndexDb(account_table, institution_table)
    monkeypatch.setattr(parsers, "connect", lambda _path: db)
    monkeypatch.setattr(
        parsers,
        "_embedding_runtime_status",
        lambda: {
            "backend": "sentence_transformers",
            "available": True,
            "model_path": "F:/models/modelscope/models/Xorbits/bge-m3",
            "dimension": 0,
            "error": "",
        },
    )
    monkeypatch.setattr(parsers, "_encode_texts", lambda texts: [[0.1, 0.2] for _ in texts])

    result = build_lancedb_indexes(
        PROJECT_ROOT,
        account_records=[
            {
                "code": "1020101",
                "name": "基本户",
                "path": "银行存款/基本账户/基本户",
                "nature": "贷",
                "is_leaf": True,
            }
        ],
        institution_chunks=[
            {
                "chunk_id": "article-0001",
                "chapter": "第一章",
                "article": "第一条",
                "page": 1,
                "text": "制度内容",
            }
        ],
    )

    assert result["available"] is True
    assert result["vector_ready"] is True
    assert result["vector_dimension"] == 2
    assert account_table.rows[0]["vector"] == [0.1, 0.2]
    assert account_table.vector_indexes[0]["vector_column_name"] == "vector"


class _FakeQueryResult:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self._limit = len(rows)

    def limit(self, value: int) -> "_FakeQueryResult":
        self._limit = value
        return self

    def to_list(self) -> list[dict]:
        return self.rows[: self._limit]


class _FakeSearchTable:
    def __init__(
        self,
        *,
        fts_rows: list[dict],
        vector_rows: list[dict],
    ) -> None:
        self.fts_rows = fts_rows
        self.vector_rows = vector_rows

    def search(self, query, query_type="auto", vector_column_name=None, fts_columns=None):
        if query_type == "fts":
            assert isinstance(query, str)
            assert fts_columns == "text"
            return _FakeQueryResult(self.fts_rows)
        if query_type == "vector":
            assert vector_column_name == "vector"
            assert isinstance(query, list)
            return _FakeQueryResult(self.vector_rows)
        raise AssertionError(f"unexpected query_type: {query_type}")


class _FakeSearchDb:
    def __init__(self, table: _FakeSearchTable) -> None:
        self.table = table

    def open_table(self, name: str) -> _FakeSearchTable:
        assert name == "account_chart"
        return self.table


class _FakeIndexTable:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.fts_indexes: list[dict] = []
        self.vector_indexes: list[dict] = []

    def create_fts_index(self, column: str, replace: bool = True, with_position: bool = True) -> None:
        self.fts_indexes.append(
            {
                "column": column,
                "replace": replace,
                "with_position": with_position,
            }
        )

    def create_index(self, **kwargs) -> None:
        self.vector_indexes.append(kwargs)


class _FakeIndexDb:
    def __init__(self, account_table: _FakeIndexTable, institution_table: _FakeIndexTable) -> None:
        self.account_table = account_table
        self.institution_table = institution_table

    def create_table(self, name: str, rows: list[dict], mode: str):
        assert mode == "overwrite"
        if name == "account_chart":
            self.account_table.rows = rows
            return self.account_table
        if name == "institution_chunks":
            self.institution_table.rows = rows
            return self.institution_table
        raise AssertionError(f"unexpected table name: {name}")


def _account_row(
    code: str,
    name: str,
    path: str,
    *,
    nature: str = "借",
    is_leaf: bool = True,
    score: float | None = None,
    distance: float | None = None,
) -> dict:
    row = {
        "code": code,
        "name": name,
        "path": path,
        "nature": nature,
        "is_leaf": is_leaf,
    }
    if score is not None:
        row["_score"] = score
    if distance is not None:
        row["_distance"] = distance
    return row
