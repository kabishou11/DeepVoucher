from pathlib import Path

from core.llm.extractors import AttachmentFactExtractor


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    attachment_path = root / "ai验证" / "附件" / "1.jpg"
    attachment = {
        "attachment_id": "att-001",
        "file_name": attachment_path.name,
        "file_path": str(attachment_path),
    }
    extractor = AttachmentFactExtractor()
    payload = extractor.extract_from_attachment(attachment)
    print(payload)
