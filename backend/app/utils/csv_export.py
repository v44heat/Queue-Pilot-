"""CSV building for reports.

Spreadsheet programs execute cells that start with = + - @ (or a tab/CR) as formulas, and report cells include
text typed by users (service names, counter names). Such strings are prefixed with an apostrophe so they are
shown as text ("CSV injection" protection). Numbers are written as numbers."""
import csv
import io

from flask import Response

_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, str) and value.startswith(_DANGEROUS):
        return "'" + value
    return value


def csv_response(filename: str, columns: list[tuple[str, str]], rows: list[dict]) -> Response:
    """columns = [(key, header)]. UTF-8 with a BOM so Excel reads non-ASCII names correctly."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([safe_cell(h) for _, h in columns])
    for row in rows:
        writer.writerow([safe_cell(row.get(key)) for key, _ in columns])
    body = "\ufeff" + buf.getvalue()
    return Response(
        body.encode("utf-8"), mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )
