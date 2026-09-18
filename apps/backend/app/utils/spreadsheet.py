"""Geração do modelo de planilha por faixa e leitura de planilhas enviadas
(CSV ou XLSX), sem depender de pandas."""

import csv
import io

from openpyxl import Workbook, load_workbook

REQUIRED_COLUMNS = ["nome", "celular"]


def build_model_columns(variable_internal_names: list[str]) -> list[str]:
    columns = list(REQUIRED_COLUMNS)
    for name in variable_internal_names:
        if name not in columns:
            columns.append(name)
    return columns


def build_model_csv(variable_internal_names: list[str]) -> bytes:
    columns = build_model_columns(variable_internal_names)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    return buffer.getvalue().encode("utf-8-sig")


def build_model_xlsx(variable_internal_names: list[str]) -> bytes:
    columns = build_model_columns(variable_internal_names)
    wb = Workbook()
    ws = wb.active
    ws.title = "modelo"
    ws.append(columns)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def parse_uploaded_spreadsheet(filename: str, content: bytes) -> list[dict[str, str]]:
    """Retorna uma lista de linhas como dicts {coluna: valor}, a partir de um
    CSV ou XLSX enviado pelo usuário."""

    lower = filename.lower()
    if lower.endswith(".xlsx"):
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(h).strip() if h is not None else "" for h in rows[0]]
        result = []
        for row in rows[1:]:
            if row is None or all(cell is None for cell in row):
                continue
            record = {
                headers[i]: ("" if row[i] is None else str(row[i]).strip())
                for i in range(len(headers))
                if i < len(row)
            }
            result.append(record)
        return result

    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    return [
        {k.strip(): (v or "").strip() for k, v in row.items() if k is not None}
        for row in reader
    ]
