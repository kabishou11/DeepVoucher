from core.config.settings import Settings
from core.schemas.models import VoucherExportPayload, VoucherLine


def build_empty_payload(settings: Settings) -> dict:
    return {
        "query": {
            "lb": str(settings.default_lb),
            "orgnow": settings.default_orgnow,
            "menu": str(settings.default_menu),
            "sys": str(settings.default_sys),
        },
        "body": {
            "fdzs": "0",
            "dt": "",
            "pzks": [],
            "id": None,
        },
    }


def build_voucher_payload(settings: Settings, voucher_date: str, attachment_count: int, lines: list[VoucherLine]) -> dict:
    payload = VoucherExportPayload(
        fdzs=str(attachment_count),
        dt=voucher_date,
        pzks=lines,
        id=None,
    )
    return {
        "query": {
            "lb": str(settings.default_lb),
            "orgnow": settings.default_orgnow,
            "menu": str(settings.default_menu),
            "sys": str(settings.default_sys),
        },
        "body": payload.model_dump(),
    }
