from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from io import BytesIO

from pypdf import PdfReader


_DOCUMENT_RE = re.compile(r"^\d+-\d+$")


def _plain(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return text.encode("ascii", "ignore").decode("ascii").strip().casefold()


def _pdf_literal_bytes(value: bytes) -> bytes:
    output = bytearray()
    index = 0
    escapes = {
        ord("n"): b"\n",
        ord("r"): b"\r",
        ord("t"): b"\t",
        ord("b"): b"\b",
        ord("f"): b"\f",
        ord("("): b"(",
        ord(")"): b")",
        ord("\\"): b"\\",
    }
    while index < len(value):
        current = value[index]
        if current != 0x5C:
            output.append(current)
            index += 1
            continue
        index += 1
        if index >= len(value):
            break
        escaped = value[index]
        if escaped in escapes:
            output.extend(escapes[escaped])
            index += 1
            continue
        if escaped in (10, 13):
            if escaped == 13 and index + 1 < len(value) and value[index + 1] == 10:
                index += 1
            index += 1
            continue
        if 48 <= escaped <= 55:
            octal = bytes([escaped])
            index += 1
            for _ in range(2):
                if index < len(value) and 48 <= value[index] <= 55:
                    octal += bytes([value[index]])
                    index += 1
                else:
                    break
            output.append(int(octal, 8))
            continue
        output.append(escaped)
        index += 1
    return bytes(output)


def _page_tokens(page) -> list[str]:
    contents = page.get_contents()
    if contents is None:
        return []
    data = contents.get_data()
    literals = re.findall(rb"\(((?:\\.|[^\\)])*)\)\s*Tj", data, flags=re.DOTALL)
    tokens: list[str] = []
    for literal in literals:
        raw = _pdf_literal_bytes(literal)
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError:
            decoded = raw.decode("cp1252", errors="replace")
        decoded = re.sub(r"\s+", " ", decoded).strip()
        if decoded:
            tokens.append(decoded)
    if tokens:
        return tokens
    fallback = page.extract_text() or ""
    return [line.strip() for line in fallback.splitlines() if line.strip()]


def _number(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = re.sub(r"[^\d,.-]", "", text)
    if not text or text in {"-", ".", ","}:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def _datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    for pattern in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


def _value_after(tokens: list[str], label: str, *, default: str = "") -> str:
    target = re.sub(r"[^a-z0-9]", "", _plain(label))
    for index, token in enumerate(tokens):
        if re.sub(r"[^a-z0-9]", "", _plain(token)) == target and index + 1 < len(tokens):
            return tokens[index + 1].strip()
    return default


def _value_before(tokens: list[str], label: str, *, default: str = "") -> str:
    target = re.sub(r"[^a-z0-9]", "", _plain(label))
    for index, token in enumerate(tokens):
        if re.sub(r"[^a-z0-9]", "", _plain(token)) == target and index:
            return tokens[index - 1].strip()
    return default


def _first_prefixed(tokens: list[str], prefix: str) -> str:
    target = _plain(prefix)
    for token in tokens:
        if _plain(token).startswith(target):
            return token.split(":", 1)[1].strip() if ":" in token else token.strip()
    return ""


def _split_code_name(value: str) -> tuple[str, str]:
    parts = re.split(r"\s+-\s+", str(value or "").strip(), maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return "", str(value or "").strip()


def _block_value(block: list[str], label: str) -> str:
    value = _value_after(block, label)
    if value and not value.endswith(":"):
        return value
    return ""


def parse_route_pdf(data: bytes, filename: str, plate_categories: dict[str, str] | None = None) -> tuple[dict, list[dict], list[str]]:
    """Extrai manifesto de rota. O PDF e tratado apenas como fonte de dados."""
    reader = PdfReader(BytesIO(data))
    pages = [_page_tokens(page) for page in reader.pages]
    tokens = [token for page in pages for token in page]
    if not tokens:
        raise ValueError("O PDF nao possui texto extraivel.")

    warnings: list[str] = []
    first_page = pages[0]
    timestamp = _datetime(first_page[0]) if first_page else None
    emissao = _datetime(_value_after(first_page, "Emissao")) or timestamp
    previsao = _datetime(_value_after(first_page, "Previsao"))
    saida = None
    for index, token in enumerate(first_page):
        if re.sub(r"[^a-z0-9]", "", _plain(token)) != "saida":
            continue
        for candidate in first_page[index + 1 : index + 4]:
            if re.sub(r"[^a-z0-9]", "", _plain(candidate)) == "pesocarga":
                break
            saida = _datetime(candidate)
            if saida:
                break
        break

    motorista = _value_before(first_page, "Motorista")
    placa = re.sub(r"[^A-Za-z0-9]", "", _value_before(first_page, "Veiculo")).upper()
    veiculo = _value_after(first_page, "Veiculo")
    rota_raw = ""
    for index, token in enumerate(first_page):
        if re.sub(r"[^a-z0-9]", "", _plain(token)) == "carga" and index >= 2:
            rota_raw = first_page[index - 2].strip()
            break
    if not rota_raw:
        for token in first_page:
            if re.match(r"^(?:D\+|\d+\s+-\s+)", token, flags=re.IGNORECASE):
                rota_raw = token
                break
    codigo_rota, nome_rota = _split_code_name(rota_raw)
    peso_carga = _number(_value_before(first_page, "Carga"))
    carga = _value_after(first_page, "Carga")
    telefone = _value_before(first_page, "Telefone")
    empresa = first_page[1] if len(first_page) > 1 else ""

    source_hash = hashlib.sha256(data).hexdigest()
    route_seed = f"{carga}|{placa}|{previsao}|{rota_raw}" if carga else source_hash
    route_id = "ROTA-" + hashlib.sha256(route_seed.encode("utf-8")).hexdigest()[:16].upper()
    categoria = (plate_categories or {}).get(placa, "Transporte")

    deliveries: list[dict] = []
    sequence = 0
    for page_number, page_tokens in enumerate(pages, start=1):
        starts = [index for index, token in enumerate(page_tokens) if _DOCUMENT_RE.fullmatch(token.strip())]
        for position, start in enumerate(starts):
            end = starts[position + 1] if position + 1 < len(starts) else len(page_tokens)
            block = page_tokens[start:end]
            if len(block) < 2:
                continue
            document = block[0].strip()
            client_code, client_name = _split_code_name(block[1])
            pedido_full = _block_value(block, "Pedido")
            pedido_parts = [part.strip() for part in pedido_full.split("|", 1)]
            pedido_filial = pedido_parts[0] if pedido_parts else ""
            pedido = pedido_parts[1] if len(pedido_parts) > 1 else pedido_full
            payment = next((item for item in block if _plain(item).startswith("duplicata a receber")), "")
            payment_match = re.search(r"Duplicata a Receber\s*(.*?)\s*Valor:\s*R\$\s*(.*)$", payment, re.IGNORECASE)
            endereco = _first_prefixed(block, "Endereco:")
            if not endereco:
                endereco = _first_prefixed(block, "Endereço:")
            sequence += 1
            delivery_id = f"{route_id}-{document}-{sequence:03d}"
            raw_block = "\n".join(block)
            deliveries.append(
                {
                    "Entrega ID": delivery_id,
                    "Rota ID": route_id,
                    "Carga": carga,
                    "Documento": document,
                    "Cliente Codigo": client_code,
                    "Cliente": client_name,
                    "Pedido Filial": pedido_filial,
                    "Pedido": pedido,
                    "Vendedor": _block_value(block, "Vendedor/Usuario") or _block_value(block, "Vendedor/Usuário"),
                    "Ordem": _number(_block_value(block, "Ordem")),
                    "Carrinho": _block_value(block, "Carrrinho") or _block_value(block, "Carrinho"),
                    "Cidade": _block_value(block, "Cidade"),
                    "Endereco": endereco,
                    "Telefone": telefone,
                    "Observacao": _block_value(block, "Obs"),
                    "Peso Pedido": _number(_value_before(block, "Peso Pedido")),
                    "Valor Nota": _number(_block_value(block, "Total da Nota")),
                    "Forma Recebimento": payment_match.group(1).strip() if payment_match else "",
                    "Valor Recebimento": _number(payment_match.group(2)) if payment_match else None,
                    "Corte": any(_plain(item) == "corte" for item in block),
                    "Pagina": page_number,
                    "Texto Extraido": raw_block,
                }
            )

    if not carga:
        warnings.append("Numero da carga nao identificado.")
    if not placa:
        warnings.append("Placa nao identificada.")
    if not motorista:
        warnings.append("Motorista nao identificado.")
    if not deliveries:
        warnings.append("Nenhuma entrega foi identificada.")
    delivery_weight = sum(float(item.get("Peso Pedido") or 0) for item in deliveries)

    route = {
        "Rota ID": route_id,
        "Hash PDF": source_hash,
        "Arquivo": filename,
        "Data": previsao or emissao,
        "Mes": (previsao or emissao).strftime("%Y-%m") if (previsao or emissao) else None,
        "Emissao": emissao,
        "Previsao": previsao,
        "Saida": saida,
        "Retorno": None,
        "Codigo Rota": codigo_rota,
        "Rota": rota_raw or nome_rota,
        "Carga": carga,
        "PLACA": placa,
        "Categoria": categoria,
        "Veiculo": veiculo,
        "Motorista": motorista,
        "Peso Carga": delivery_weight,
        "Peso Manifesto": peso_carga,
        "Telefone": telefone,
        "Empresa": empresa,
        "KM Rodados": None,
        "Status": "Pendente",
        "Paginas": len(pages),
        "Entregas": len(deliveries),
        "Observacao": "",
        "Texto Extraido": "\n".join(tokens),
        "Importado Em": datetime.now(),
        "Atualizado Em": datetime.now(),
    }
    return route, deliveries, warnings

