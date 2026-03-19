from pathlib import Path

from core.knowledge.parsers import bootstrap_knowledge, knowledge_summary, search_accounts


def knowledge_sources(root: str | Path) -> dict[str, str]:
    base = Path(root)
    return {
        "institution_pdf": str(base / "knowledge" / "raw" / "农村集体经济组织会计制度.pdf"),
        "account_chart_xls": str(base / "knowledge" / "raw" / "会计科目表 (1).xls"),
        "format_reference_xls": str(base / "reference" / "凭证列表 (2).xls"),
    }


__all__ = ["bootstrap_knowledge", "knowledge_sources", "knowledge_summary", "search_accounts"]
