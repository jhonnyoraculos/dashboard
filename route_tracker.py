from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from io import BytesIO
from typing import Iterable

import pandas as pd


TRACKER_BUILD_VERSION = "ciclo-base-estrito-v5"


def _ascii(value: object) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", text).strip().upper()


def normalize_tracker_plate(value: object) -> str:
    plate = re.sub(r"[^A-Z0-9]", "", _ascii(value))
    # A mesma placa pode vir do rastreador no padrão antigo ABC-1234 e
    # dos manifestos no padrão Mercosul ABC1C34. O segundo algarismo do
    # bloco numérico é convertido de 0..9 para A..J.
    if re.fullmatch(r"[A-Z]{3}[0-9]{4}", plate):
        digit_to_letter = "ABCDEFGHIJ"
        plate = f"{plate[:4]}{digit_to_letter[int(plate[4])]}{plate[5:]}"
    return plate


def _number(value: object) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0.0
    if isinstance(value, (int, float)):
        return max(float(value), 0.0)
    text = str(value).strip().replace(" ", "")
    if not text:
        return 0.0
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return max(float(text), 0.0)
    except ValueError:
        return 0.0


def _find_header_row(raw: pd.DataFrame) -> int:
    for index, row in raw.head(30).iterrows():
        values = [_ascii(value).replace("/", "") for value in row.tolist()]
        joined = " | ".join(values)
        if "PLACA" in values and "IGN" in values and "DATAHORA INICIAL" in joined:
            return int(index)
    raise ValueError("Não foi encontrado o cabeçalho Placa, Ign e Data/Hora Inicial no relatório.")


def _column_index(headers: list[str], predicate, label: str) -> int:
    for index, value in enumerate(headers):
        if predicate(value):
            return index
    raise ValueError(f"Não foi encontrada a coluna {label} no relatório.")


def _is_on(value: object) -> bool:
    return _ascii(value).startswith("LIGADO")


def _is_home_city(value: object) -> bool:
    text = _ascii(value)
    # Mesmo relatórios com acentuação danificada preservam o início DIVIN.
    return "DIVIN" in text


def _is_base(value: object) -> bool:
    text = _ascii(value)
    compact = re.sub(r"[^A-Z0-9]", "", text)
    return "AVMARGINAL" in compact or "AVENIDAMARGINAL" in compact


def _is_exit_reference(value: object) -> bool:
    compact = re.sub(r"[^A-Z0-9]", "", _ascii(value))
    return "MG050" in compact


def _daily_journeys(movements: list[dict]) -> list[dict]:
    by_day: dict[pd.Timestamp, list[tuple[pd.Timestamp, pd.Timestamp]]] = defaultdict(list)
    for movement in movements:
        start = pd.Timestamp(movement["Inicio"])
        stop = pd.Timestamp(movement["Fim"])
        cursor = start.normalize()
        final_day = stop.normalize()
        while cursor <= final_day:
            next_day = cursor + pd.Timedelta(days=1)
            segment_start = max(start, cursor)
            segment_stop = min(stop, next_day - pd.Timedelta(microseconds=1))
            if segment_stop > segment_start:
                by_day[cursor].append((segment_start, segment_stop))
            cursor = next_day

    journeys: list[dict] = []
    for day, intervals in sorted(by_day.items()):
        start = min(interval[0] for interval in intervals)
        stop = max(interval[1] for interval in intervals)
        journeys.append(
            {
                "data": day.date().isoformat(),
                "saida": start.isoformat(),
                "parada": stop.isoformat(),
                "horas": round((stop - start).total_seconds() / 3600.0, 4),
            }
        )
    return journeys


def _finish_cycle(active: dict, *, complete: bool, reason: str) -> dict:
    movements = active["movements"]
    departure = pd.Timestamp(movements[0]["Inicio"])
    return_time = pd.Timestamp(movements[-1]["Fim"])
    journeys = _daily_journeys(movements)
    worked_hours = sum(float(row["horas"]) for row in journeys)
    return {
        "Placa": active["plate"],
        "Saida": departure,
        "Retorno": return_time,
        "Data rota": departure.normalize(),
        "KM total": round(sum(float(row["KM"]) for row in movements), 3),
        "Tempo viagem h": round((return_time - departure).total_seconds() / 3600.0, 4),
        "Horas trabalhadas": round(worked_hours, 4),
        "Dias": len(journeys),
        "Jornadas": journeys,
        "Local saída": movements[0]["Localizacao"],
        "Local retorno": movements[-1]["Localizacao"],
        "Locais": [row["Localizacao"] for row in movements],
        "Completa": bool(complete),
        "Situação": reason,
        "_Movements": movements,
    }


def _extract_cycles(events: pd.DataFrame) -> list[dict]:
    cycles: list[dict] = []
    for plate, group in events.groupby("Placa", sort=True):
        active: dict | None = None
        previous_location = ""
        seen_home = False
        for _, row in group.sort_values(["Inicio", "Fim"]).iterrows():
            initial_location = str(row.get("LocalizacaoInicial") or "").strip()
            location = str(row.get("LocalizacaoFinal") or row.get("Localizacao") or "").strip()
            distance = float(row.get("KM") or 0.0)
            moving = _is_on(row.get("Ign")) and distance > 0.01
            starts_moving = _is_on(row.get("Ign")) and distance >= 0.5
            has_explicit_locations = bool(initial_location)
            previous_is_home = (
                _is_base(previous_location)
                or _is_home_city(previous_location)
                or (seen_home and _is_exit_reference(previous_location))
            )
            initial_is_base = _is_base(initial_location)
            initial_is_exit = _is_exit_reference(initial_location)
            destination_is_base = _is_base(location)
            destination_is_home = _is_home_city(location)

            if active is None:
                starts_at_home = (
                    (initial_is_base and not destination_is_base)
                    if has_explicit_locations
                    else (previous_is_home and not destination_is_base)
                )
                starts_at_exit = (
                    seen_home and initial_is_exit and not destination_is_base
                    if has_explicit_locations
                    else (seen_home and not previous_location and _is_exit_reference(location))
                )
                if starts_moving and (starts_at_home or starts_at_exit):
                    movement = row.to_dict()
                    active = {
                        "plate": plate,
                        "movements": [movement],
                        "left_home": not destination_is_home or _is_exit_reference(location),
                    }
                if destination_is_base or destination_is_home:
                    seen_home = True
                previous_location = location or previous_location
                continue

            if moving:
                active["movements"].append(row.to_dict())
                if not destination_is_home or _is_exit_reference(location):
                    active["left_home"] = True

            returned_from_outside = bool(active["left_home"] and destination_is_home)
            returned_local_to_base = bool(not active["left_home"] and destination_is_base)
            returned = (
                destination_is_base
                if has_explicit_locations
                else (returned_from_outside or returned_local_to_base)
            )
            if returned and active["movements"]:
                # Alguns rastreadores registram a chegada à Av. Marginal na linha
                # "Desligado", com KM zero. A linha ainda determina o retorno real.
                if not moving:
                    active["movements"].append(row.to_dict())
                cycles.append(_finish_cycle(active, complete=True, reason="Retorno à base identificado"))
                active = None
            if destination_is_base or destination_is_home:
                seen_home = True
            previous_location = location or previous_location

        if active is not None:
            cycles.append(_finish_cycle(active, complete=False, reason="Sem retorno à base no relatório"))
    return cycles


def _merge_same_day_cycles(cycles: list[dict]) -> list[dict]:
    """Consolida as várias saídas da mesma placa em uma operação diária."""
    grouped: dict[tuple[str, pd.Timestamp], list[dict]] = defaultdict(list)
    incomplete: list[dict] = []
    for cycle in cycles:
        if not cycle.get("Completa"):
            incomplete.append(cycle)
            continue
        key = (str(cycle.get("Placa") or ""), pd.Timestamp(cycle["Data rota"]).normalize())
        grouped[key].append(cycle)

    merged: list[dict] = []
    for (_plate, _day), day_cycles in grouped.items():
        day_cycles.sort(key=lambda row: pd.Timestamp(row["Saida"]))
        if len(day_cycles) == 1:
            merged.append(day_cycles[0])
            continue
        movements = [
            movement
            for cycle in day_cycles
            for movement in list(cycle.get("_Movements") or [])
        ]
        merged.append(
            _finish_cycle(
                {"plate": day_cycles[0]["Placa"], "movements": movements},
                complete=True,
                reason=f"{len(day_cycles)} saída(s) da base consolidadas no dia",
            )
        )
    return sorted(
        [*merged, *incomplete],
        key=lambda row: (str(row.get("Placa") or ""), pd.Timestamp(row["Saida"])),
    )


def _extend_returns_to_exact_base(cycles: list[dict], events: pd.DataFrame) -> list[dict]:
    """Inclui o último trecho urbano quando a Av. Marginal vem logo após a chegada."""
    extended: list[dict] = []
    for cycle in cycles:
        movements = list(cycle.get("_Movements") or [])
        if not cycle.get("Completa") or not movements or _is_base(movements[-1].get("Localizacao")):
            extended.append(cycle)
            continue
        plate = str(cycle.get("Placa") or "")
        returned_at = pd.Timestamp(cycle["Retorno"])
        limit = returned_at + pd.Timedelta(hours=2)
        candidates = events.loc[
            events["Placa"].eq(plate)
            & events["Inicio"].ge(returned_at)
            & events["Inicio"].le(limit)
        ].sort_values(["Inicio", "Fim"])
        additions: list[dict] = []
        reached_exact_base = False
        for _, row in candidates.iterrows():
            if not (_is_on(row.get("Ign")) and float(row.get("KM") or 0.0) > 0.01):
                continue
            location = row.get("Localizacao")
            if not (_is_home_city(location) or _is_base(location)):
                break
            additions.append(row.to_dict())
            if _is_base(location):
                reached_exact_base = True
                break
        if reached_exact_base:
            cycle = _finish_cycle(
                {"plate": plate, "movements": [*movements, *additions]},
                complete=True,
                reason="Retorno à Av. Marginal identificado",
            )
        extended.append(cycle)
    return extended


def parse_tracker_report(content: bytes, file_name: str = "relatorio.xlsx") -> tuple[list[dict], pd.DataFrame, list[str]]:
    if not content:
        raise ValueError("O relatório do rastreador está vazio.")
    raw = pd.read_excel(BytesIO(content), sheet_name=0, header=None, dtype=object)
    if raw.empty:
        raise ValueError("O relatório do rastreador não possui linhas.")
    header_row = _find_header_row(raw)
    headers = [_ascii(value).replace("/", "") for value in raw.iloc[header_row].tolist()]
    plate_index = _column_index(headers, lambda value: value == "PLACA", "Placa")
    ignition_index = _column_index(headers, lambda value: value == "IGN", "Ign")
    start_index = _column_index(headers, lambda value: "DATAHORA INICIAL" in value, "Data/Hora Inicial")
    stop_index = _column_index(headers, lambda value: "DATAHORA FINAL" in value, "Data/Hora Final")
    distance_index = _column_index(headers, lambda value: "DIST" in value and "KM" in value, "Distância Percorrida")
    initial_location_index = next(
        (index for index, value in enumerate(headers) if "LOCALIZACAO INICIAL" in value),
        None,
    )
    final_location_index = next(
        (index for index, value in enumerate(headers) if "LOCALIZACAO FINAL" in value),
        None,
    )
    legacy_location_index = distance_index - 1
    if final_location_index is None and legacy_location_index <= stop_index:
        raise ValueError("Não foi possível identificar a coluna de localização.")

    body = raw.iloc[header_row + 1 :].copy()
    events = pd.DataFrame(
        {
            "Placa": body.iloc[:, plate_index].map(normalize_tracker_plate),
            "Ign": body.iloc[:, ignition_index].astype("string").fillna(""),
            "Inicio": pd.to_datetime(body.iloc[:, start_index], dayfirst=True, errors="coerce"),
            "Fim": pd.to_datetime(body.iloc[:, stop_index], dayfirst=True, errors="coerce"),
            "LocalizacaoInicial": (
                body.iloc[:, initial_location_index].astype("string").fillna("").replace("<NA>", "")
                if initial_location_index is not None
                else ""
            ),
            "LocalizacaoFinal": (
                body.iloc[:, final_location_index].astype("string").fillna("").replace("<NA>", "")
                if final_location_index is not None
                else body.iloc[:, legacy_location_index].astype("string").fillna("").replace("<NA>", "")
            ),
            "KM": body.iloc[:, distance_index].map(_number),
        }
    )
    events["Localizacao"] = events["LocalizacaoFinal"]
    events = events.loc[
        events["Placa"].ne("")
        & events["Inicio"].notna()
        & events["Fim"].notna()
        & events["Fim"].gt(events["Inicio"])
    ].sort_values(["Placa", "Inicio", "Fim"]).reset_index(drop=True)
    if events.empty:
        raise ValueError("Nenhum evento válido foi encontrado no relatório.")

    cycles = _merge_same_day_cycles(_extend_returns_to_exact_base(_extract_cycles(events), events))
    warnings: list[str] = []
    incomplete = sum(not bool(cycle.get("Completa")) for cycle in cycles)
    if incomplete:
        warnings.append(
            f"{incomplete} deslocamento(s) começaram no período, mas não retornaram à base; não serão importados."
        )
    first_event = events.iloc[0]
    first_location = first_event.get("LocalizacaoInicial") or first_event.get("Localizacao")
    if not (_is_base(first_location) or _is_home_city(first_location)):
        warnings.append(
            "O relatório começa com o veículo fora de Divinópolis. O trecho inicial foi tratado como viagem parcial."
        )
    if not cycles:
        warnings.append("Nenhum ciclo completo de saída e retorno à base foi identificado.")
    for cycle in cycles:
        cycle.pop("_Movements", None)
    return cycles, events, warnings


def match_tracker_cycles(cycles: Iterable[dict], routes: pd.DataFrame) -> list[dict]:
    route_frame = routes.copy()
    if route_frame.empty:
        route_frame = pd.DataFrame(columns=["Rota ID", "Status", "PLACA", "Data", "Previsao", "Rota", "Carga"])
    status = route_frame.get("Status", pd.Series("", index=route_frame.index)).astype("string").fillna("")
    route_frame = route_frame.loc[status.str.strip().str.casefold().eq("pendente")].copy()
    route_frame["_Placa"] = route_frame.get("PLACA", pd.Series("", index=route_frame.index)).map(normalize_tracker_plate)
    route_dates = pd.to_datetime(route_frame.get("Data"), errors="coerce")
    if "Previsao" in route_frame.columns:
        route_dates = route_dates.fillna(pd.to_datetime(route_frame["Previsao"], errors="coerce"))
    route_frame["_Data"] = route_dates.dt.normalize()

    cycle_list = list(cycles)
    matches: list[dict] = []
    for cycle in cycle_list:
        plate = str(cycle.get("Placa") or "")
        departure_date = pd.Timestamp(cycle["Saida"]).normalize()
        candidates = route_frame.loc[
            route_frame["_Placa"].eq(plate) & route_frame["_Data"].eq(departure_date)
        ].copy()
        complete = bool(cycle.get("Completa"))
        if not complete:
            correspondence = "Viagem parcial — sem retorno à base"
            candidates = candidates.iloc[0:0]
        elif candidates.empty:
            correspondence = "Nenhuma rota pendente para a placa na data de saída da base"
        else:
            correspondence = f"{len(candidates)} rota(s) pendente(s) encontrada(s) na saída da base"

        route_ids = candidates.get("Rota ID", pd.Series(dtype="string")).astype("string").tolist()
        route_names = candidates.get("Rota", pd.Series(dtype="string")).astype("string").tolist()
        loads = candidates.get("Carga", pd.Series(dtype="string")).astype("string").tolist()
        matches.append(
            {
                **cycle,
                "Rota IDs": route_ids,
                "Rotas encontradas": " • ".join(value for value in route_names if value and value != "<NA>"),
                "Cargas": " • ".join(value for value in loads if value and value != "<NA>"),
                "Quantidade rotas": len(route_ids),
                "KM por rota": round(float(cycle.get("KM total") or 0.0) / len(route_ids), 3) if route_ids else None,
                "Correspondência": correspondence,
                "Pode importar": bool(route_ids and complete),
            }
        )
    return matches
