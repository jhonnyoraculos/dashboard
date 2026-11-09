from __future__ import annotations

import calendar
import re
from collections import Counter
from datetime import date
from io import BytesIO

from pypdf import PdfReader


PLATE_PATTERN = re.compile(r"\b[A-Z]{3}[0-9][A-Z0-9][0-9]{2}\b")
DATE_PATTERN = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
INSTALLMENT_PATTERN = re.compile(
    r"IPVA\s*[-–]?\s*(\d+)\s+([0-9][0-9.]*,[0-9]{2})",
    re.IGNORECASE,
)
TOTAL_PATTERN = re.compile(
    r"TOTAL\s*:\s*R\$[^0-9]*([0-9][0-9.]*,[0-9]{2})",
    re.IGNORECASE,
)


def _parse_brl(value: str) -> float:
    return float(value.replace(".", "").replace(",", "."))


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def parse_ipva_text(text: str, *, filename: str = "") -> dict:
    normalized = re.sub(r"[ \t]+", " ", str(text or ""))
    plate_match = re.search(r"Placa\s*:\s*([A-Z0-9-]+)", normalized, re.IGNORECASE)
    if plate_match:
        plate = re.sub(r"[^A-Z0-9]", "", plate_match.group(1).upper())
    else:
        plate_candidates = PLATE_PATTERN.findall(normalized.upper())
        plate = Counter(plate_candidates).most_common(1)[0][0] if plate_candidates else ""
    if not PLATE_PATTERN.fullmatch(plate):
        raise ValueError("Não foi possível identificar a placa no PDF do IPVA.")

    installment_matches = INSTALLMENT_PATTERN.findall(normalized)
    if installment_matches:
        installment_number = int(installment_matches[-1][0])
        installment_value = _parse_brl(installment_matches[-1][1])
    else:
        # O DAE repete o TOTAL na via do contribuinte e na via do banco. Valores
        # iguais são deduplicados para que um único boleto nunca seja somado duas vezes.
        total_values = [_parse_brl(value) for value in TOTAL_PATTERN.findall(normalized)]
        unique_totals = sorted({round(value, 2) for value in total_values if value > 0})
        if len(unique_totals) != 1:
            raise ValueError("Não foi possível identificar um único valor de parcela no PDF do IPVA.")
        installment_number = 1
        installment_value = unique_totals[0]

    raw_dates = DATE_PATTERN.findall(normalized)
    if not raw_dates:
        raise ValueError("Não foi possível identificar o vencimento no PDF do IPVA.")
    due_text = Counter(raw_dates).most_common(1)[0][0]
    day, month, year = (int(part) for part in due_text.split("/"))
    due_date = date(year, month, day)

    return {
        "Arquivo": filename,
        "PLACA": plate,
        "Parcela PDF": installment_number,
        "Valor Parcela": round(installment_value, 2),
        "Primeiro Vencimento": due_date,
    }


def parse_ipva_pdf(data: bytes, filename: str = "") -> dict:
    reader = PdfReader(BytesIO(data))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if not text.strip():
        raise ValueError("O PDF do IPVA não possui texto legível.")
    return parse_ipva_text(text, filename=filename)


def ipva_three_installment_rows(
    parsed: dict,
    categoria: str,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict]:
    plate = str(parsed.get("PLACA") or "").strip().upper()
    installment_value = round(float(parsed.get("Valor Parcela") or 0.0), 2)
    pdf_due = parsed.get("Primeiro Vencimento")
    first_due = start_date or pdf_due
    last_due = end_date or (_add_months(first_due, 2) if isinstance(first_due, date) else None)
    if not plate or installment_value <= 0 or not isinstance(first_due, date) or not isinstance(last_due, date):
        raise ValueError("Dados incompletos para gerar as parcelas do IPVA.")
    month_distance = (last_due.year - first_due.year) * 12 + last_due.month - first_due.month
    if month_distance != 2:
        raise ValueError("O período deve abranger exatamente 3 meses, da 1ª à 3ª parcela.")

    due_dates = [first_due, _add_months(first_due, 1), last_due]
    total_value = round(installment_value * 3, 2)
    return [
        {
            "Data": due_date,
            "Inicio": due_dates[0],
            "Fim": due_dates[-1],
            "Mes": due_date.strftime("%Y-%m"),
            "PLACA": plate,
            "Categoria": categoria,
            "Tipo": "IPVA",
            "Valor Total": total_value,
            "Custo": installment_value,
        }
        for due_date in due_dates
    ]
