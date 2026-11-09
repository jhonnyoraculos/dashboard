import json
import os
import unittest
import zipfile
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import patch

import pandas as pd

os.environ.setdefault("JR_SKIP_WARM_CACHE", "1")

import app as backend
import streamlit_app as dashboard


def sample_payload() -> dict:
    return {
        "total_rotas": 2,
        "entregas_total": 30,
        "peso_total": 18_000,
        "km_total": 800,
        "custos": {
            "total_custo": 8_500,
            "total_ganho": 11_000,
            "resultado": 2_500,
            "rotas": [
                {
                    "Rota ID": "r1", "Rota": "ROTA CARA", "PLACA": "AAA1A11",
                    "Combustivel": 5_000, "Manutencao": 1_000, "Pedagio": 500,
                    "Hoteis": 300, "Salarios": 200, "Freteiro": 0,
                    "Custo total": 7_000, "Ganho entregas": 6_000,
                    "Resultado": -1_000, "Custo sobre ganho %": 116.67,
                },
                {
                    "Rota ID": "r2", "Rota": "ROTA BOA", "PLACA": "BBB2B22",
                    "Combustivel": 1_000, "Manutencao": 200, "Pedagio": 100,
                    "Hoteis": 0, "Salarios": 200, "Freteiro": 0,
                    "Custo total": 1_500, "Ganho entregas": 5_000,
                    "Resultado": 3_500, "Custo sobre ganho %": 30,
                },
            ],
        },
        "tempos_rotas": [
            {"Rota ID": "r1", "Entregas": 10, "KM Rodados": 500, "Peso Carga": 10_000, "Dias Rota": 2, "Tempo Viagem Horas": 34, "Horas Trabalhadas": 20},
            {"Rota ID": "r2", "Entregas": 20, "KM Rodados": 300, "Peso Carga": 8_000, "Dias Rota": 1, "Tempo Viagem Horas": 10, "Horas Trabalhadas": 10},
        ],
        "rotas_detalhes": [],
        "entregas_detalhes": [],
        "ranking_motoristas": [],
        "ranking_placas": [],
        "alertas": [],
    }


class RoutesDashboardTests(unittest.TestCase):
    def test_dashboard_authentication_accepts_only_the_configured_credentials(self):
        with patch.dict(
            os.environ,
            {"DASHBOARD_USERNAME": "usuario-teste", "DASHBOARD_PASSWORD": "senha-teste-forte"},
            clear=False,
        ):
            self.assertTrue(dashboard._auth_credentials_valid("usuario-teste", "senha-teste-forte"))
            self.assertFalse(dashboard._auth_credentials_valid("usuario-teste", "senha-incorreta"))
            self.assertFalse(dashboard._auth_credentials_valid("outro-usuario", "senha-teste-forte"))

    def test_dashboard_password_hash_rejects_invalid_salt(self):
        self.assertEqual(dashboard._password_hash("senha", "sal-invalido", 600_000), "")

    def test_remember_token_is_signed_expires_and_rejects_tampering(self):
        issued_at = datetime(2026, 11, 5, tzinfo=timezone.utc)
        with patch.dict(
            os.environ,
            {"DASHBOARD_USERNAME": "usuario-teste", "DASHBOARD_COOKIE_SECRET": "segredo-de-teste-longo"},
            clear=False,
        ):
            token = dashboard._make_remember_token("usuario-teste", now=issued_at)
            self.assertEqual(
                dashboard._verify_remember_token(token, now=issued_at + timedelta(days=1)),
                "usuario-teste",
            )
            self.assertEqual(dashboard._verify_remember_token(token + "x", now=issued_at), "")
            self.assertEqual(
                dashboard._verify_remember_token(token, now=issued_at + timedelta(days=31)),
                "",
            )

    def test_overview_ranking_totals_include_delivery_gain(self):
        with patch.object(
            backend,
            "data_frota",
            return_value={"totais": {"total": 250.0, "valor_peso": 1000.0}},
        ):
            totals = backend._overview_transport_ranking_totals(
                ano=2026,
                meses=[10],
                periodos=["2026-10"],
                fallback=99.0,
            )

        self.assertEqual(totals["total"], 250.0)
        self.assertEqual(totals["ganho_entregas"], 1000.0)

    def test_database_read_skips_schema_ddl_when_table_is_available(self):
        frame = pd.DataFrame([{"PLACA": "AAA1A11", "Categoria": "Transporte", "Diaria": 0.0}])
        with (
            patch.object(backend, "_db_engine", return_value=object()),
            patch.object(pd, "read_sql_query", return_value=frame) as read_query,
            patch.object(backend, "_ensure_dataset_table_for_read") as ensure_schema,
            patch.object(backend, "_db_metadata", return_value=[]),
        ):
            result = backend._read_database_table("placas", backend._PLACAS_COLUMNS)

        self.assertEqual(len(result), 1)
        self.assertEqual(read_query.call_count, 1)
        ensure_schema.assert_not_called()

    def test_database_read_repairs_schema_only_after_read_failure(self):
        frame = pd.DataFrame([{"PLACA": "AAA1A11", "Categoria": "Transporte", "Diaria": 0.0}])
        with (
            patch.object(backend, "_db_engine", return_value=object()),
            patch.object(pd, "read_sql_query", side_effect=[RuntimeError("missing"), frame]) as read_query,
            patch.object(backend, "_ensure_dataset_table_for_read") as ensure_schema,
            patch.object(backend, "_db_metadata", return_value=[]),
        ):
            result = backend._read_database_table("placas", backend._PLACAS_COLUMNS)

        self.assertEqual(len(result), 1)
        self.assertEqual(read_query.call_count, 2)
        ensure_schema.assert_called_once()

    def test_rdv_parser_uses_only_footer_total(self):
        text = """
        RELATÓRIO DE DESPESAS DE VIAGEM - RDV - AJUDANTE DE MOTORISTA
        NOME: EDER SILVA
        DATA QUINZENA (INÍCIO E FINAL): 12/10/2026 a 24/10/2026
        HOUVE ADIANTAMENTO DE DIÁRIA? SIM NO VALOR DE R$ 1.000,00
        13/10/2026 OURO PRETO HOTEL R$ 180,00 DIÁRIA R$ 100,00
        TOTAL DA QUINZENA EM R$ -----> R$ 732,00
        """
        parsed = dashboard._parse_rdv_total_text(text, file_name="rdv.jpg")
        self.assertEqual(parsed["Colaborador"], "EDER SILVA")
        self.assertEqual(parsed["Funcao"], "Ajudante de motorista")
        self.assertEqual(parsed["Inicio"], date(2026, 10, 12))
        self.assertEqual(parsed["Fim"], date(2026, 10, 24))
        self.assertEqual(parsed["Mes"], "2026-10")
        self.assertEqual(parsed["Valor"], 732.0)

    def test_rdv_parser_recovers_common_handwritten_total_ocr(self):
        base = (
            "RELATÓRIO RDV AJUDANTE DE MOTORISTA NOME: TESTE DA SILVA "
            "DATA QUINZENA (INÍCIO E FINAL): 12/10/2026 a 24/10/2026 "
            "TOTAL DA QUINZENA EM R$ > R$ {value} LOCAL/DATA: DIVINÓPOLIS"
        )
        self.assertEqual(dashboard._parse_rdv_total_text(base.format(value="8OO"))["Valor"], 800.0)
        self.assertEqual(dashboard._parse_rdv_total_text(base.format(value="79H"))["Valor"], 794.0)
        self.assertEqual(dashboard._parse_rdv_total_text(base.format(value="2&8O"))["Valor"], 288.0)
        compact_label = base.replace(
            "TOTAL DA QUINZENA EM R$ > R$ {value}",
            "TOTALDA QUINZENAEMR$>R$288Q",
        ).format(value="ignored")
        self.assertEqual(dashboard._parse_rdv_total_text(compact_label)["Valor"], 288.0)

    def test_rdv_parser_prioritizes_typed_header_name_and_reversed_period(self):
        text = """
        ASSINATURA DO COLABORADOR
        Leandro Coelho Pimentel
        TOTAL DA QUINZENA EM R$ > R$ 632,00
        24/10/2026
        23/10/2026
        13/10/2026
        12/10/2026
        NOME: LEANDRO COELHO PIMENTEL
        RELATÓRIO DE DESPESAS DE VIAGEM - RDV - AJUDANTE DE MOTORISTA
        """
        parsed = dashboard._parse_rdv_total_text(text)
        self.assertEqual(parsed["Colaborador"], "LEANDRO COELHO PIMENTEL")
        self.assertEqual(parsed["Inicio"], date(2026, 10, 12))
        self.assertEqual(parsed["Fim"], date(2026, 10, 24))
        self.assertEqual(parsed["Valor"], 632.0)

    def test_rdv_import_accepts_blank_collaborator(self):
        rows = pd.DataFrame(
            [{
                "Inicio": date(2026, 10, 12),
                "Fim": date(2026, 10, 24),
                "Colaborador": "",
                "Valor": 632.0,
            }]
        )
        self.assertTrue(dashboard._rdv_import_valid_mask(rows).iloc[0])

    def test_diarias_spreadsheet_reads_multiple_fortnights_and_zero_values(self):
        from openpyxl import Workbook

        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Diarias"
        worksheet["C2"] = "13/10 a 23/10"
        worksheet["C3"] = "Colaborador"
        worksheet["D3"] = "Valor Recarregar (Ev. 1624)"
        worksheet["C4"] = "Pessoa Um"
        worksheet["D4"] = 392
        worksheet["C5"] = "Pessoa Zero"
        worksheet["D5"] = 0
        worksheet["C7"] = "28/09 a 09/10"
        worksheet["C8"] = "Colaborador"
        worksheet["D8"] = "Valor"
        worksheet["C9"] = "Pessoa Dois"
        worksheet["D9"] = 864
        worksheet["C11"] = "17/08 28/08"
        worksheet["C12"] = "Colaborador"
        worksheet["D12"] = "Valor"
        worksheet["C13"] = "Pessoa Sem Separador"
        worksheet["D13"] = 500
        buffer = BytesIO()
        workbook.save(buffer)

        result = dashboard._read_diarias_spreadsheet(buffer.getvalue(), "diarias.xlsx", 2026)

        self.assertEqual(result["periods"], 3)
        self.assertEqual(result["warnings"], [])
        self.assertEqual(len(result["rows"]), 4)
        self.assertEqual(sum(row["Valor"] for row in result["rows"]), 1756.0)
        self.assertEqual(result["rows"][0]["Inicio"], date(2026, 10, 13))
        self.assertEqual(result["rows"][0]["Fim"], date(2026, 10, 23))
        self.assertEqual(result["rows"][1]["Valor"], 0.0)
        self.assertEqual(result["rows"][2]["Mes"], "2026-10")
        self.assertEqual(result["rows"][3]["Inicio"], date(2026, 8, 17))
        self.assertEqual(result["rows"][3]["Fim"], date(2026, 8, 28))

    def test_replace_diarias_spreadsheet_replaces_only_imported_periods_in_one_transaction(self):
        executed = []
        progress_updates = []

        class Result:
            rowcount = 1

        class Connection:
            def execute(self, statement, params=None):
                executed.append((str(statement), params or {}))
                return Result()

        class BeginContext:
            def __enter__(self):
                return Connection()

            def __exit__(self, exc_type, exc, traceback):
                return False

        class Engine:
            def begin(self):
                return BeginContext()

        rows = [
            {"Inicio": date(2026, 10, 13), "Fim": date(2026, 10, 23), "Colaborador": "PESSOA A", "Valor": 392},
            {"Inicio": date(2026, 10, 13), "Fim": date(2026, 10, 23), "Colaborador": "PESSOA B", "Valor": 0},
            {"Inicio": date(2026, 9, 28), "Fim": date(2026, 10, 9), "Colaborador": "PESSOA C", "Valor": 864},
        ]
        with (
            patch.object(backend, "_db_engine", return_value=Engine()),
            patch.object(backend, "_ensure_dataset_table"),
            patch.object(backend, "_write_metadata"),
            patch.object(backend, "_clear_dataset_cache"),
        ):
            saved_rows, saved_periods = backend.replace_diarias_equipe_periods(
                rows,
                progress_callback=lambda fraction, stage: progress_updates.append((fraction, stage)),
            )

        deletes = [statement for statement, _ in executed if statement.lstrip().upper().startswith("DELETE")]
        inserts = [statement for statement, _ in executed if statement.lstrip().upper().startswith("INSERT")]
        self.assertEqual((saved_rows, saved_periods), (3, 2))
        self.assertEqual(len(deletes), 2)
        self.assertEqual(len(inserts), 3)
        self.assertTrue(all('CAST("Inicio" AS DATE) <=' in statement for statement in deletes))
        self.assertTrue(all('CAST("Fim" AS DATE) >=' in statement for statement in deletes))
        self.assertTrue(progress_updates)
        self.assertEqual(progress_updates[-1][0], 1.0)
        self.assertEqual(progress_updates[-1][1], "Atualizando os dashboards")
        self.assertEqual(
            [fraction for fraction, _ in progress_updates],
            sorted(fraction for fraction, _ in progress_updates),
        )

    def test_replace_seguro_placa_replaces_selected_plate_from_start_month(self):
        executed = []

        class Result:
            rowcount = 2

        class Connection:
            def execute(self, statement, params=None):
                executed.append((str(statement), params or {}))
                return Result()

        class BeginContext:
            def __enter__(self):
                return Connection()

            def __exit__(self, exc_type, exc, traceback):
                return False

        class Engine:
            def begin(self):
                return BeginContext()

        with (
            patch.object(backend, "_db_engine", return_value=Engine()),
            patch.object(backend, "_ensure_dataset_table"),
            patch.object(backend, "_write_metadata"),
            patch.object(backend, "_clear_dataset_cache"),
        ):
            result = backend.replace_pedagio_seguro_placa(
                "abc-1d23",
                "Transporte",
                350.0,
                date(2026, 11, 9),
                date(2027, 1, 20),
            )

        deletes = [(statement, params) for statement, params in executed if statement.lstrip().upper().startswith("DELETE")]
        insurance_inserts = [
            (statement, params)
            for statement, params in executed
            if statement.lstrip().upper().startswith("INSERT") and '"Tipo"' in statement
        ]
        self.assertEqual(len(deletes), 1)
        self.assertEqual(deletes[0][1]["placa"], "ABC1D23")
        self.assertEqual(deletes[0][1]["start_mes"], "2026-11")
        self.assertIn('"PLACA" = :placa', deletes[0][0])
        self.assertNotIn('"Mes" <=', deletes[0][0])
        self.assertEqual(len(insurance_inserts), 3)
        self.assertEqual([params["mes"] for _, params in insurance_inserts], ["2026-11", "2026-12", "2027-01"])
        self.assertTrue(all(params["custo"] == 350.0 for _, params in insurance_inserts))
        self.assertTrue(all(params["inicio"] == date(2026, 11, 9) for _, params in insurance_inserts))
        self.assertTrue(all(params["fim"] == date(2027, 1, 20) for _, params in insurance_inserts))
        self.assertEqual(insurance_inserts[0][1]["data"], date(2026, 11, 9))
        self.assertEqual(insurance_inserts[1][1]["data"], date(2026, 12, 1))
        self.assertEqual(result["deleted"], 2)
        self.assertEqual(result["inserted"], 3)

    def test_replace_seguro_placa_rejects_invalid_period_or_value(self):
        with self.assertRaises(ValueError):
            backend.replace_pedagio_seguro_placa("ABC1D23", "Transporte", 100, date(2027, 2, 1), date(2027, 1, 31))
        with self.assertRaises(ValueError):
            backend.replace_pedagio_seguro_placa("ABC1D23", "Transporte", 0, "2027-01", "2027-02")

    def test_rdv_target_total_recovers_handwritten_currency(self):
        self.assertEqual(dashboard._parse_rdv_target_total_text("R$ 288100"), 288.0)
        self.assertEqual(dashboard._parse_rdv_target_total_text("R$ 63200"), 632.0)
        self.assertEqual(dashboard._parse_rdv_target_total_text("R$ SOO"), 500.0)
        self.assertEqual(dashboard._parse_rdv_target_total_text("R$ 704"), 704.0)
        self.assertEqual(dashboard._parse_rdv_target_total_text("MR$Rs732/C0\n23\nde"), 732.0)
        self.assertEqual(dashboard._parse_rdv_target_total_text("EM R$ > R$ 392\nDivinópolis\n23 de"), 392.0)
        self.assertEqual(dashboard._parse_rdv_target_total_text("900\nM R$ > R$\n23 de"), 900.0)
        self.assertIsNone(dashboard._parse_rdv_target_total_text("23 de 10 de 2026"))

    def test_rdv_vision_totals_accepts_only_valid_json_values(self):
        parsed = dashboard._parse_rdv_vision_totals(
            '{"totais":[288.0, "632,00", null, 99999]}', 5
        )
        self.assertEqual(parsed, [288.0, 632.0, None, None, None])

    def test_ai_broken_inline_table_is_normalized_for_chat(self):
        raw = "## Projeção | Métrica |---| Valor observado | **Conclusão** custo estável"
        normalized = dashboard._normalize_ai_markdown(raw)
        self.assertIn("### Projeção", normalized)
        self.assertNotIn("|", normalized)
        self.assertNotIn("---", normalized)
        self.assertIn("**Conclusão**", normalized)

    def test_ai_general_question_uses_every_dashboard_with_shared_period(self):
        self.assertTrue(dashboard._ai_is_general_question("Como está o desempenho geral de custo sobre ganho?"))
        self.assertTrue(dashboard._ai_is_general_question("Mostre o site inteiro"))
        self.assertFalse(dashboard._ai_is_general_question("Qual placa gastou mais combustível?"))
        self.assertFalse(dashboard._ai_is_general_question("Faça uma análise geral desta página"))

        context = {"filtros_ativos": {"data_inicio": "2026-10-01", "data_fim": "2026-10-27"}}
        with patch.object(
            dashboard,
            "_ai_dashboard_payload",
            side_effect=lambda name, filters: {"total": 10, "filtro_recebido": filters},
        ) as payload:
            overview = dashboard._ai_site_wide_overview(context)

        self.assertEqual(overview["escopo"], "site_inteiro")
        self.assertEqual(set(overview["dashboards_consultados"]), set(dashboard.AI_SITE_DASHBOARDS))
        self.assertEqual(payload.call_count, len(dashboard.AI_SITE_DASHBOARDS))
        self.assertEqual(overview["areas"]["combustivel"]["filtros"], {"ano": 2026, "mes": [10]})
        self.assertEqual(
            overview["areas"]["rotas"]["filtros"],
            {"data_inicio": "2026-10-01", "data_fim": "2026-10-27"},
        )

        compact_routes = dashboard._ai_global_dashboard_summary("rotas", sample_payload())
        self.assertEqual(compact_routes["custos"]["total_custo"], 8_500)
        self.assertEqual(compact_routes["custos"]["total_ganho"], 11_000)
        self.assertNotIn("rotas", compact_routes["custos"])

    def test_ai_chart_context_is_structured_and_filters_are_whitelisted(self):
        figure = dashboard.go.Figure(dashboard.go.Bar(x=["jan", "fev"], y=[10, 15], name="Custo"))
        snapshot = dashboard._ai_chart_snapshot("Custo mensal", figure)
        self.assertEqual(snapshot["grafico"], "Custo mensal")
        self.assertEqual(snapshot["series"][0]["x"], ["jan", "fev"])
        self.assertEqual(snapshot["series"][0]["y"], [10, 15])

        filters = dashboard._ai_sanitize_filters(
            "combustivel",
            {"ano": 2026, "placa": "ABC1D23", "sql": "DROP TABLE", "senha": "x"},
        )
        self.assertEqual(filters, {"ano": 2026, "placa": "ABC1D23"})

    def test_decimal_days_are_shown_as_days_plus_extra_hours(self):
        self.assertEqual(dashboard._format_days_hours(1.3), "1 dia + 7 horas")
        self.assertEqual(dashboard._format_days_hours(2.0), "2 dias")
        self.assertEqual(dashboard._format_days_hours(0.5), "12 horas")

        gauge = dashboard._route_gauge(
            1.3,
            "Dias para entregar",
            maximum=3,
            target=1,
            inverse=True,
            display_text=dashboard._format_days_hours(1.3),
            reference_text=f"Referência: {dashboard._format_days_hours(1)}",
        )
        annotations = [annotation["text"] for annotation in gauge.layout.annotations]
        self.assertIn("<b>1 dia + 7 horas</b>", annotations)
        self.assertIn("Referência: 1 dia", annotations)

    def test_route_freight_profile_uses_route_averages_and_hotel_history(self):
        data = {
            "tempos_rotas": [
                {"Rota ID": "r1", "Rota": "ROTA TESTE", "Peso Carga": 8_000, "KM Rodados": 400, "Dias Rota": 1},
                {"Rota ID": "r2", "Rota": "ROTA TESTE", "Peso Carga": 12_000, "KM Rodados": 600, "Dias Rota": 2},
            ],
            "custos": {
                "rotas": [
                    {"Rota ID": "r1", "Rota": "ROTA TESTE", "Hoteis": 0},
                    {"Rota ID": "r2", "Rota": "ROTA TESTE", "Hoteis": 220},
                ]
            },
        }

        profile = dashboard._route_freight_profile(data)

        self.assertEqual(profile["route"], "ROTA TESTE")
        self.assertEqual(profile["trip_count"], 2)
        self.assertEqual(profile["average_weight_kg"], 10_000)
        self.assertEqual(profile["average_distance_km"], 500)
        self.assertEqual(profile["average_trip_days"], 1.5)
        self.assertTrue(profile["has_hotel"])
        self.assertEqual(profile["hotel_trips"], 1)

    def test_route_freight_profile_calculates_unload_productivity_from_completed_routes(self):
        data = {
            "tempos_rotas": [
                {
                    "Rota ID": "r1", "Rota": "ROTA TESTE", "Peso Carga": 2_000,
                    "KM Rodados": 160, "Horas Trabalhadas": 6,
                },
                {
                    "Rota ID": "r2", "Rota": "ROTA TESTE", "Peso Carga": 3_000,
                    "KM Rodados": 240, "Horas Trabalhadas": 9,
                },
            ],
            "custos": {"rotas": []},
        }

        profile = dashboard._route_freight_profile(data)

        # Deslocamento: 5 h no total. Descarga estimada: 10 h. 5.000 kg / 10 h.
        self.assertEqual(profile["unload_sample_count"], 2)
        self.assertEqual(profile["unload_hours_observed"], 10)
        self.assertEqual(profile["unload_kg_per_hour"], 500)
        self.assertIn("horas trabalhadas", profile["unload_productivity_source"])

    def test_freight_quote_uses_editable_unload_rate_and_individual_trip_has_no_helper(self):
        quote = dashboard._calculate_freight_quote(
            {"rate_per_km": 5.0, "hotel_daily_rate": 0.0, "is_freighter": False},
            weight_kg=1_000,
            distance_km=80,
            employees=1,
            employee_hourly_rate=0,
            driver_hourly_rate=20,
            helper_hourly_rate=10,
            driver_daily_rate=100,
            assistant_daily_rate=100,
            unload_kg_per_hour=500,
            margin_percent=0,
            include_hotels=False,
        )

        self.assertEqual(quote["unload_kg_per_hour"], 500)
        self.assertEqual(quote["unload_hours"], 2)
        self.assertEqual(quote["total_operation_hours"], 3)
        self.assertEqual(quote["helper_count"], 0)
        self.assertEqual(quote["helper_salary_cost"], 0)
        self.assertEqual(quote["helper_daily_cost"], 0)
        self.assertEqual(quote["driver_salary_cost"], 60)

    def test_daily_charges_each_started_ten_hour_workday(self):
        quote = dashboard._calculate_freight_quote(
            {
                "rate_per_km": 5.0,
                "hotel_daily_rate": 200.0,
                "is_freighter": False,
            },
            weight_kg=1_000,
            distance_km=2_960,
            employees=2,
            employee_hourly_rate=0,
            driver_hourly_rate=0,
            helper_hourly_rate=0,
            driver_daily_rate=100,
            assistant_daily_rate=100,
            unload_kg_per_hour=500,
            own_trip_days=2,
            margin_percent=0,
            include_hotels=True,
        )

        self.assertEqual(quote["total_operation_hours"], 39)
        self.assertEqual(quote["own_days"], 4)
        self.assertEqual(quote["assistant_days"], 4)
        self.assertEqual(quote["driver_daily_cost"], 400)
        self.assertEqual(quote["helper_daily_cost"], 400)
        self.assertEqual(quote["hotel_days"], 3)
        self.assertEqual(quote["hotel_cost"], 600)

    def test_selected_plate_families_start_with_350_kg_per_hour(self):
        for plate in ("HMF9A43", "OQH-1A23", "SYT0B06"):
            with self.subTest(plate=plate):
                self.assertEqual(dashboard._freight_default_unload_rate(plate, 612.5), 350)

        self.assertEqual(dashboard._freight_default_unload_rate("HAM3C53", 612.5), 612.5)
        self.assertEqual(dashboard._freight_default_unload_rate(None, 480), 480)

    def test_freight_calculator_without_route_uses_only_selected_plate_history(self):
        no_route = "Sem rota — usar média da placa"

        plate_params = dashboard._route_freight_history_params(no_route, no_route, "ABC1D23")
        fleet_params = dashboard._route_freight_history_params(no_route, no_route, None)
        route_params = dashboard._route_freight_history_params("10 - DIVINÓPOLIS", no_route, "ABC1D23")

        self.assertEqual(plate_params["placa"], ["ABC1D23"])
        self.assertNotIn("rota", plate_params)
        self.assertTrue(plate_params["incluir_custos"])
        self.assertNotIn("placa", fleet_params)
        self.assertFalse(fleet_params["incluir_custos"])
        self.assertEqual(route_params["rota"], ["10 - DIVINÓPOLIS"])
        self.assertNotIn("placa", route_params)
        self.assertFalse(route_params["incluir_detalhes"])

    def test_freight_profile_counts_simultaneous_manifests_as_one_trip(self):
        data = {
            "tempos_rotas": [
                {
                    "Rota ID": "r1", "Rota": "ROTA A", "PLACA": "ABC1D23",
                    "Saida": "2026-10-10T07:00:00", "Retorno": "2026-10-10T17:00:00",
                    "Peso Carga": 1_000, "KM Rodados": 40, "Horas Trabalhadas": 5, "Dias Rota": 0.5,
                },
                {
                    "Rota ID": "r2", "Rota": "ROTA B", "PLACA": "ABC1D23",
                    "Saida": "2026-10-10T07:00:00", "Retorno": "2026-10-10T17:00:00",
                    "Peso Carga": 2_000, "KM Rodados": 40, "Horas Trabalhadas": 5, "Dias Rota": 0.5,
                },
            ],
            "custos": {"rotas": []},
        }

        profile = dashboard._route_freight_profile(data)

        self.assertEqual(profile["trip_count"], 1)
        self.assertEqual(profile["average_weight_kg"], 3_000)
        self.assertEqual(profile["average_distance_km"], 80)
        self.assertEqual(profile["average_trip_days"], 1)
        self.assertEqual(profile["unload_hours_observed"], 9)
        self.assertAlmostEqual(profile["unload_kg_per_hour"], 3_000 / 9)

    def test_freighter_quote_uses_daily_rate_and_route_average_days(self):
        reference = dashboard._freight_plate_reference(
            {
                "categoria": "Freteiro",
                "diaria": 750,
                "dias_trabalhados": 3,
                "gasto_diarias": 2_250,
                "km_total": 0,
            },
            {"rate_per_km": 6.5, "hotel_daily_rate": 220, "rate_per_employee_hour": 0},
        )

        quote = dashboard._calculate_freight_quote(
            reference,
            weight_kg=4_000,
            distance_km=330,
            employees=2,
            employee_hourly_rate=0,
            margin_percent=10,
            include_hotels=False,
            freighter_trip_days=1.5,
            freighter_daily_rate_override=800,
            freighter_excess_km_rate=5,
            assistant_daily_rate=32,
        )

        self.assertTrue(reference["is_freighter"])
        self.assertEqual(reference["freighter_daily_rate"], 750)
        self.assertEqual(reference["rate_per_km"], 0)
        self.assertEqual(quote["freighter_days"], 2)
        self.assertEqual(quote["freighter_daily_rate"], 800)
        self.assertEqual(quote["freighter_daily_cost"], 1_600)
        self.assertEqual(quote["freighter_excess_km"], 210)
        self.assertEqual(quote["freighter_excess_cost"], 1_050)
        self.assertEqual(quote["freighter_cost"], 2_650)
        self.assertEqual(quote["vehicle_component"], 2_650)
        self.assertEqual(quote["assistant_days"], 2)
        self.assertEqual(quote["assistant_daily_rate"], 32)
        self.assertEqual(quote["assistant_cost"], 64)
        self.assertEqual(quote["distance_component"], 0)
        self.assertEqual(quote["estimated_cost"], 2_714)
        self.assertEqual(quote["suggested_freight"], 2_985.4)

    def test_assistant_daily_rate_recognizes_city_inside_route_name(self):
        self.assertEqual(dashboard._freight_assistant_daily_rate("10 - DIVINÓPOLIS"), 32)
        self.assertEqual(dashboard._freight_assistant_daily_rate("D+0,5 DIVINOPOLIS FERRAGENS"), 32)
        self.assertEqual(dashboard._freight_assistant_daily_rate("EXTRA CARMO DO CAJURU"), 32)
        self.assertEqual(dashboard._freight_assistant_daily_rate("D+0,5 CARMO DOO CAJURU"), 32)
        self.assertEqual(dashboard._freight_assistant_daily_rate("404 - ITABIRA - GUANHÃES"), 100)

    def test_plate_comparison_uses_same_scenario_and_each_vehicle_rule(self):
        rows_by_plate = {
            "FRT1A11": {
                "categoria": "Freteiro", "diaria": 750, "dias_trabalhados": 2,
                "gasto_diarias": 1_500, "km_total": 0,
            },
            "TRP1A11": {
                "categoria": "Transporte", "total": 600, "salario_transporte": 0,
                "km_total": 100, "dias_servico": 1,
            },
            "SEM1A11": {
                "categoria": "Transporte", "total": 0, "salario_transporte": 0,
                "km_total": 0, "dias_servico": 1,
            },
        }
        comparison = dashboard._freight_plate_comparison(
            ["FRT1A11", "TRP1A11", "SEM1A11"],
            rows_by_plate,
            {"rate_per_km": 8, "hotel_daily_rate": 0, "rate_per_employee_hour": 0},
            quote_inputs={
                "weight_kg": 0, "distance_km": 330, "employees": 2,
                "employee_hourly_rate": 0, "margin_percent": 0, "include_hotels": False,
            },
            average_trip_days=1.5,
            excess_km_rate=5,
            assistant_daily_rate=32,
            selected_plate="FRT1A11",
            selected_daily_rate=800,
        ).set_index("Placa")

        self.assertEqual(comparison.loc["FRT1A11", "Custo do veículo"], 2_650)
        self.assertEqual(comparison.loc["FRT1A11", "Diária ajudante - custo"], 64)
        self.assertEqual(comparison.loc["TRP1A11", "Custo do veículo"], 1_980)
        self.assertEqual(comparison.loc["TRP1A11", "Salário motorista"], 0)
        self.assertEqual(comparison.loc["TRP1A11", "Salário ajudante"], 0)
        self.assertEqual(comparison.loc["TRP1A11", "Diferença para o menor"], 0)
        self.assertEqual(comparison.loc["FRT1A11", "Diferença para o menor"], 670)
        self.assertFalse(bool(comparison.loc["SEM1A11", "Base calculável"]))
        self.assertTrue(pd.isna(comparison.loc["SEM1A11", "Diferença para o menor"]))

        recommendation = dashboard._freight_economic_recommendation(
            comparison.reset_index(),
            ["FRT1A11"],
        )
        self.assertEqual(recommendation["plate"], "TRP1A11")
        self.assertEqual(recommendation["selected_plate"], "FRT1A11")
        self.assertEqual(recommendation["savings"], 670)

    def test_salary_and_daily_are_separate_for_own_fleet_and_freighter(self):
        own_quote = dashboard._calculate_freight_quote(
            {"rate_per_km": 5.0, "hotel_daily_rate": 0.0, "is_freighter": False},
            weight_kg=3_500,
            distance_km=80,
            employees=2,
            employee_hourly_rate=0,
            driver_hourly_rate=20,
            helper_hourly_rate=10,
            driver_daily_rate=150,
            assistant_daily_rate=32,
            own_trip_days=1.5,
            margin_percent=0,
            include_hotels=False,
        )
        operation_hours = 11.0
        self.assertEqual(own_quote["driver_salary_cost"], operation_hours * 20)
        self.assertEqual(own_quote["helper_salary_cost"], operation_hours * 10)
        self.assertEqual(own_quote["driver_daily_cost"], 2 * 150)
        self.assertEqual(own_quote["helper_daily_cost"], 2 * 32)
        self.assertEqual(own_quote["estimated_cost"], 400 + 220 + 110 + 300 + 64)

        freighter_quote = dashboard._calculate_freight_quote(
            {"is_freighter": True, "freighter_daily_rate": 800, "hotel_daily_rate": 0.0},
            weight_kg=3_500,
            distance_km=80,
            employees=2,
            employee_hourly_rate=0,
            driver_hourly_rate=20,
            helper_hourly_rate=10,
            driver_daily_rate=150,
            assistant_daily_rate=32,
            freighter_trip_days=1.5,
            margin_percent=0,
            include_hotels=False,
        )
        self.assertEqual(freighter_quote["driver_salary_cost"], 0)
        self.assertEqual(freighter_quote["driver_daily_cost"], 0)
        self.assertEqual(freighter_quote["helper_salary_cost"], operation_hours * 10)
        self.assertEqual(freighter_quote["helper_daily_cost"], 2 * 32)
        self.assertEqual(freighter_quote["estimated_cost"], 1_600 + 110 + 64)

    def test_fleet_cost_over_revenue_uses_aggregated_plate_totals(self):
        financial = pd.DataFrame(
            [
                {"Rota ID": "a1", "PLACA": "AAA1A11", "Entregas": 10, "KM Rodados": 100, "Custo total": 200, "Ganho entregas": 400, "Peso Carga": 1_000},
                {"Rota ID": "a2", "PLACA": "AAA1A11", "Entregas": 10, "KM Rodados": 100, "Custo total": 100, "Ganho entregas": 100, "Peso Carga": 1_000},
                {"Rota ID": "b1", "PLACA": "BBB1B11", "Entregas": 5, "KM Rodados": 50, "Custo total": 300, "Ganho entregas": 200, "Peso Carga": 500},
                {"Rota ID": "c1", "PLACA": "CCC1C11", "Entregas": 1, "KM Rodados": 0, "Custo total": 50, "Ganho entregas": 0, "Peso Carga": 100},
            ]
        )

        fleet = dashboard._route_fleet_cost_summary(financial).set_index("PLACA")

        self.assertEqual(fleet.loc["AAA1A11", "Custo/receita %"], 60.0)
        self.assertEqual(fleet.loc["BBB1B11", "Custo/receita %"], 150.0)
        self.assertTrue(pd.api.types.is_float_dtype(fleet["Custo por km"]))
        self.assertTrue(pd.api.types.is_float_dtype(fleet["Custo/receita %"]))
        self.assertTrue(pd.isna(fleet.loc["CCC1C11", "Custo por km"]))
        self.assertTrue(pd.isna(fleet.loc["CCC1C11", "Custo/receita %"]))
        self.assertTrue(bool(fleet.loc["CCC1C11", "Sem receita"]))

        chart_data = fleet.dropna(subset=["Custo/receita %"]).reset_index()
        chart = dashboard._route_fleet_cost_revenue_chart(chart_data)
        self.assertTrue(all("R$" in label and "%" in label for label in chart.data[0].text))
        self.assertIn("Receita atribuída", chart.data[0].hovertemplate)
        self.assertIn("Resultado", chart.data[0].hovertemplate)

    def test_route_without_hotel_keeps_simulated_hotel_at_zero(self):
        data = {
            "tempos_rotas": [
                {"Rota ID": "r1", "Rota": "ROTA SEM HOTEL", "Peso Carga": 10_000, "KM Rodados": 800}
            ],
            "custos": {"rotas": [{"Rota ID": "r1", "Rota": "ROTA SEM HOTEL", "Hoteis": 0}]},
        }
        profile = dashboard._route_freight_profile(data)
        quote = dashboard._calculate_freight_quote(
            {"rate_per_km": 5.0, "hotel_daily_rate": 220.0},
            weight_kg=10_000,
            distance_km=800,
            employees=2,
            employee_hourly_rate=15.0,
            margin_percent=10.0,
            include_hotels=bool(profile["has_hotel"]),
        )

        self.assertFalse(profile["has_hotel"])
        self.assertGreater(quote["total_operation_hours"], 10)
        self.assertAlmostEqual(quote["driver_labor_cost"], quote["total_operation_hours"] * 15)
        self.assertAlmostEqual(quote["helper_labor_cost"], quote["total_operation_hours"] * 15)
        self.assertAlmostEqual(
            quote["team_cost"],
            quote["driver_labor_cost"] + quote["helper_labor_cost"],
        )
        self.assertEqual(quote["hotel_days"], 0)
        self.assertEqual(quote["hotel_cost"], 0)

    def test_freight_context_keeps_hotel_out_of_truck_km_rate(self):
        base_payload = {
            "totais": {"total": 1_000, "km_total": 100, "salario_transporte": 0},
            "ranking": [],
        }
        hotel_payload = {
            "totais": {
                "total": 1_200,
                "km_total": 100,
                "hoteis": 200,
                "hoteis_reservas": 1,
                "hoteis_media_reserva": 200,
            },
            "ranking": [],
        }
        with patch.object(dashboard, "route_json", side_effect=[base_payload, hotel_payload]):
            historical, reference = dashboard._freight_historical_context()

        self.assertIs(historical, base_payload)
        self.assertEqual(reference["rate_per_km"], 10)
        self.assertEqual(reference["hotel_daily_rate"], 200)

    def test_gauge_context_identifies_result_and_reference_status(self):
        context = dashboard._route_gauge_context_html(
            [("Melhor", "MOTORISTA TESTE"), ("Menor pontuação", "OUTRO MOTORISTA")],
            value=82.0,
            target=80.0,
            inverse=False,
        )
        self.assertIn("MOTORISTA TESTE", context)
        self.assertIn("OUTRO MOTORISTA", context)
        self.assertIn("Refer&#234;ncia atingida", context)

        city_context = dashboard._route_gauge_context_html(
            [("Maior volume", "CARMO DO CAJURU")],
            value=526,
            target=5,
            inverse=False,
            positive_text="Acima da mediana",
            attention_text="Abaixo da mediana",
        )
        city_gauge = dashboard._route_gauge(
            526, "Maior cidade", maximum=632, target=5, suffix=" ent."
        )
        self.assertIn("Acima da mediana", city_context)
        self.assertEqual(city_gauge.data[0]["number"]["valueformat"], ".0f")
        self.assertEqual(city_gauge.data[0]["number"]["suffix"], " ent.")

        density_gauge = dashboard._route_gauge(
            0.0684, "Entregas por KM", maximum=1, target=0.09, suffix=" ent/km"
        )
        self.assertEqual(density_gauge.data[0]["number"]["valueformat"], ".2f")
        self.assertIn("0,09 ent/km", density_gauge.layout.annotations[0]["text"])

    def test_driver_ranking_adds_linear_score_indicators(self):
        frame = dashboard._route_driver_ranking_frame(
            [
                {"Motorista": "VERDE", "Pontuacao": 85.0, "Posicao": 1},
                {"Motorista": "AMARELO", "Pontuacao": 72.0, "Posicao": 2},
                {"Motorista": "LARANJA", "Pontuacao": 60.0, "Posicao": 3},
                {"Motorista": "VERMELHO", "Pontuacao": 40.0, "Posicao": 4},
            ]
        )
        self.assertEqual(frame.columns[:4].tolist(), ["Motorista", "Indicador", "Posicao", "Pontuacao"])
        indicators = frame.set_index("Motorista")["Indicador"].to_dict()
        self.assertIn("🟩", indicators["VERDE"])
        self.assertIn("🟨", indicators["AMARELO"])
        self.assertIn("🟧", indicators["LARANJA"])
        self.assertIn("🟥", indicators["VERMELHO"])

        plates = dashboard._route_ranking_indicator_frame(
            [{"PLACA": "AAA1A11", "Pontuacao": 90.0}], entity_column="PLACA"
        )
        routes = dashboard._route_ranking_indicator_frame(
            [{"Rota": "ROTA TESTE", "Pontuacao": 70.0}], entity_column="Rota"
        )
        cities = dashboard._route_ranking_indicator_frame(
            [
                {"Cidade": "MAIOR", "Entregas": 100},
                {"Cidade": "MENOR", "Entregas": 25},
            ],
            entity_column="Cidade",
            volume=True,
        )
        self.assertIn("🟩", plates.iloc[0]["Indicador"])
        self.assertIn("🟨", routes.iloc[0]["Indicador"])
        self.assertIn("Muito alto", cities.iloc[0]["Indicador"])
        self.assertIn("Baixo", cities.iloc[1]["Indicador"])

    def test_route_staff_image_uses_second_date_and_matches_existing_route(self):
        def box(center_x, center_y, width=80, height=16):
            return [
                [center_x - width / 2, center_y - height / 2],
                [center_x + width / 2, center_y - height / 2],
                [center_x + width / 2, center_y + height / 2],
                [center_x - width / 2, center_y + height / 2],
            ]

        texts = [
            "CARREGAMENTOS: sexta-feira, 9 de outubro de 2026",
            "ROTAS: terça-feira, 13 de outubro de 2026",
            "Nº ROTA", "PLACAS", "MOTORISTA", "OBSS.",
            "10", "HAM-3C53", "DIVINÓPOLIS", "RONALDO PEREIRA", "CAIQUE LACERDA DOS SANTOS",
        ]
        positions = [
            (520, 25), (520, 55), (40, 95), (150, 95), (520, 95), (930, 95),
            (40, 135), (150, 135), (300, 135), (520, 135), (760, 135),
        ]
        ocr = {
            "text": "\n".join(texts),
            "width": 1000,
            "height": 400,
            "detections": [
                {"text": text, "box": box(x, y), "score": 0.99}
                for text, (x, y) in zip(texts, positions)
            ],
        }
        route_date, parsed = dashboard._parse_route_collaborator_ocr(ocr)
        self.assertEqual(route_date, date(2026, 10, 13))
        self.assertEqual(parsed[0]["Nº rota"], "10")
        self.assertEqual(parsed[0]["PLACA lida"], "HAM3C53")
        self.assertEqual(parsed[0]["Ajudante"], "CAIQUE LACERDA DOS SANTOS")

        routes = pd.DataFrame(
            [
                {
                    "Rota ID": "route-10", "Codigo Rota": "10", "Rota": "10 - DIVINOPOLIS",
                    "PLACA": "HAM3C53", "Data": "2026-10-14", "Previsao": "2026-10-14",
                    "Emissao": "2026-10-13", "Saida": None, "Status": "Concluída",
                    "Motorista": "ANTIGO", "Ajudante": "",
                }
            ]
        )
        matched = dashboard._match_route_collaborators(parsed, routes)
        self.assertEqual(matched[0]["Correspondência"], "Encontrada")
        self.assertEqual(matched[0]["Rota ID"], "route-10")
        self.assertEqual(matched[0]["Status atual"], "Concluída")

    def test_route_staff_image_removes_observation_joined_to_helper_name(self):
        def box(center_x, center_y, width=80, height=16):
            return [
                [center_x - width / 2, center_y - height / 2],
                [center_x + width / 2, center_y - height / 2],
                [center_x + width / 2, center_y + height / 2],
                [center_x - width / 2, center_y + height / 2],
            ]

        texts = [
            "CARREGAMENTOS: sexta-feira, 9 de outubro de 2026",
            "ROTAS: terça-feira, 13 de outubro de 2026",
            "Nº ROTA", "PLACAS", "MOTORISTA", "OBSS.",
            "30", "NYC6H24", "ITAGUARA 2", "RICARDO DE OLIVEIRA",
            "GABRIEL ENRIQUE DE SOUZA CARVALHO ROTA 2 DIAS",
        ]
        positions = [
            (520, 25), (520, 55), (40, 95), (150, 95), (520, 95), (930, 95),
            (40, 135), (150, 135), (300, 135), (520, 135), (760, 135),
        ]
        ocr = {
            "text": "\n".join(texts),
            "width": 1000,
            "height": 400,
            "detections": [
                {"text": text, "box": box(x, y), "score": 0.99}
                for text, (x, y) in zip(texts, positions)
            ],
        }

        _, parsed = dashboard._parse_route_collaborator_ocr(ocr)

        self.assertEqual(parsed[0]["Motorista"], "RICARDO DE OLIVEIRA")
        self.assertEqual(parsed[0]["Ajudante"], "GABRIEL ENRIQUE DE SOUZA CARVALHO")

    def test_collaborator_ranking_includes_driver_and_helper(self):
        source = pd.DataFrame(
            [
                {
                    "Rota ID": "r1", "Rota": "ROTA 1", "Motorista": "MOTORISTA A", "Ajudante": "AJUDANTE B",
                    "Entregas": 10, "Peso Carga": 5000, "KM Rodados": 100, "Tempo Viagem Horas": 10,
                    "Horas Trabalhadas": 8, "Dias Rota": 1, "_Qualidade": 100,
                }
            ]
        )
        ranking = backend._route_collaborator_ranking(source)
        self.assertEqual(set(ranking["Colaborador"]), {"MOTORISTA A", "AJUDANTE B"})
        roles = ranking.set_index("Colaborador")["Função"].to_dict()
        self.assertEqual(roles["MOTORISTA A"], "Motorista")
        self.assertEqual(roles["AJUDANTE B"], "Ajudante")

    def test_collaborator_daily_alerts_sum_day_and_do_not_duplicate_overlapping_routes(self):
        source = pd.DataFrame(
            [
                {
                    "Rota ID": "r1", "Data": "2026-10-13", "Rota": "ROTA 10", "Carga": "1001",
                    "PLACA": "AAA1A11", "Motorista": "MOTORISTA A", "Ajudante": "AJUDANTE B",
                    "Saida": "2026-10-13 07:00", "Retorno": "2026-10-13 15:00",
                    "Horas Trabalhadas": 8,
                },
                {
                    "Rota ID": "r2", "Data": "2026-10-13", "Rota": "ROTA 11", "Carga": "1002",
                    "PLACA": "AAA1A11", "Motorista": "MOTORISTA A", "Ajudante": "AJUDANTE B",
                    "Saida": "2026-10-13 07:00", "Retorno": "2026-10-13 15:00",
                    "Horas Trabalhadas": 8,
                },
            ]
        )

        alerts = backend._route_collaborator_daily_alerts(source)

        self.assertEqual(set(alerts["Colaborador"]), {"MOTORISTA A", "AJUDANTE B"})
        self.assertTrue(alerts["Horas cumpridas"].eq(8.0).all())
        self.assertTrue(alerts["Horas faltantes"].eq(1.0).all())
        self.assertTrue(alerts["Quantidade de rotas"].eq(2).all())
        self.assertTrue(alerts["Rotas"].str.contains("ROTA 10").all())
        self.assertTrue(alerts["Rotas"].str.contains("ROTA 11").all())

    def test_collaborator_daily_alerts_use_each_multiday_journey(self):
        journeys = json.dumps(
            [
                {"saida": "2026-10-13T07:00:00", "parada": "2026-10-13T17:00:00"},
                {"saida": "2026-10-14T08:00:00", "parada": "2026-10-14T16:00:00"},
            ]
        )
        source = pd.DataFrame(
            [
                {
                    "Rota ID": "r1", "Data": "2026-10-13", "Rota": "ROTA 10", "Carga": "1001",
                    "PLACA": "AAA1A11", "Motorista": "MOTORISTA A", "Ajudante": "",
                    "Jornadas": journeys, "Horas Trabalhadas": 18,
                }
            ]
        )

        alerts = backend._route_collaborator_daily_alerts(source)

        self.assertEqual(len(alerts), 1)
        self.assertEqual(pd.to_datetime(alerts.iloc[0]["Data"]).date(), date(2026, 10, 14))
        self.assertEqual(alerts.iloc[0]["Horas cumpridas"], 8.0)

    def test_collaborator_performance_supports_total_individual_weekly_and_monthly(self):
        rows = pd.DataFrame(
            [
                {
                    "Rota ID": "r1", "Data": "2026-10-05", "Motorista": "MOTORISTA A", "Ajudante": "AJUDANTE B",
                    "Entregas": 10, "Peso Carga": 5000, "KM Rodados": 100, "Horas Trabalhadas": 10,
                },
                {
                    "Rota ID": "r2", "Data": "2026-10-07", "Motorista": "MOTORISTA C", "Ajudante": "AJUDANTE B",
                    "Entregas": 8, "Peso Carga": 3000, "KM Rodados": 80, "Horas Trabalhadas": 8,
                },
                {
                    "Rota ID": "r3", "Data": "2026-10-14", "Motorista": "MOTORISTA A", "Ajudante": "",
                    "Entregas": 12, "Peso Carga": 6000, "KM Rodados": 120, "Horas Trabalhadas": 10,
                },
            ]
        )

        total_weekly = dashboard._route_collaborator_performance_frame(rows, cadence="Semanal")
        helper_weekly = dashboard._route_collaborator_performance_frame(
            rows, collaborator="AJUDANTE B", cadence="Semanal"
        )
        driver_monthly = dashboard._route_collaborator_performance_frame(
            rows, collaborator="MOTORISTA A", cadence="Mensal"
        )

        self.assertEqual(len(total_weekly), 2)
        self.assertEqual(total_weekly["Rotas"].sum(), 3)
        self.assertEqual(len(helper_weekly), 1)
        self.assertEqual(helper_weekly.iloc[0]["Entregas"], 18)
        self.assertEqual(helper_weekly.iloc[0]["Entregas por hora"], 1.0)
        self.assertEqual(len(driver_monthly), 1)
        self.assertEqual(driver_monthly.iloc[0]["Rotas"], 2)
        self.assertEqual(driver_monthly.iloc[0]["Peso transportado (t)"], 11.0)

    def test_collaborator_alias_resolves_variants_and_chains(self):
        aliases = {
            backend._collaborator_name_key("JOSE DA SILVA"): "JOSÉ DA SILVA",
            backend._collaborator_name_key("ZE DA SILVA"): "JOSE DA SILVA",
        }

        self.assertEqual(
            backend._canonical_collaborator_name("  ze   da silva ", aliases),
            "JOSÉ DA SILVA",
        )
        self.assertEqual(
            backend._canonical_collaborator_name("JOSÉ DA SILVA", aliases),
            "JOSÉ DA SILVA",
        )

        with patch.object(backend, "_collaborator_aliases", return_value=aliases):
            prepared = backend._prepare_insert_row(
                "rotas",
                {"Rota ID": "r1", "Motorista": "ZE DA SILVA", "Ajudante": "JOSE DA SILVA"},
            )
        self.assertEqual(prepared["Motorista"], "JOSÉ DA SILVA")
        self.assertEqual(prepared["Ajudante"], "JOSÉ DA SILVA")

    def test_collaborator_name_summary_counts_all_related_sources(self):
        routes = pd.DataFrame(
            [
                {"Motorista": "NOME A", "Ajudante": "NOME B"},
                {"Motorista": "NOME A", "Ajudante": ""},
            ]
        )
        hotels = pd.DataFrame([{"Motorista": "NOME A", "Ajudante": "NOME B"}])
        speed = pd.DataFrame([{"Motorista": "NOME A"}])

        with (
            patch.object(backend, "load_rotas", return_value=routes),
            patch.object(backend, "load_hoteis", return_value=hotels),
            patch.object(backend, "load_velocidade", return_value=speed),
        ):
            summary = pd.DataFrame(backend.collaborator_name_summary()).set_index("Nome")

        self.assertEqual(summary.loc["NOME A", "Rotas como motorista"], 2)
        self.assertEqual(summary.loc["NOME A", "Hotéis como motorista"], 1)
        self.assertEqual(summary.loc["NOME A", "Registros de velocidade"], 1)
        self.assertEqual(summary.loc["NOME A", "Total de ocorrências"], 4)
        self.assertEqual(summary.loc["NOME B", "Total de ocorrências"], 2)

    def test_merge_collaborator_names_updates_all_name_fields_and_saves_alias(self):
        executed = []

        class Result:
            rowcount = 1

        class Connection:
            def execute(self, statement, params=None):
                executed.append((str(statement), params or {}))
                return Result()

        class BeginContext:
            def __enter__(self):
                return Connection()

            def __exit__(self, exc_type, exc, traceback):
                return False

        class Engine:
            def begin(self):
                return BeginContext()

        with (
            patch.object(backend, "_db_engine", return_value=Engine()),
            patch.object(backend, "_ensure_dataset_table"),
            patch.object(backend, "_write_metadata") as write_metadata,
            patch.object(backend, "_clear_dataset_cache"),
            patch.object(backend, "_collaborator_aliases", return_value={}),
        ):
            result = backend.merge_collaborator_names("NOME DUPLICADO", "NOME CORRETO")

        update_statements = [statement for statement, _ in executed if statement.lstrip().upper().startswith("UPDATE")]
        self.assertEqual(len(update_statements), 5)
        self.assertEqual(result["updated_fields"], 5)
        self.assertEqual(result["canonical"], "NOME CORRETO")
        alias_calls = [
            call for call in write_metadata.call_args_list
            if call.args[1] == backend.COLLABORATOR_ALIASES_METADATA_KEY
        ]
        self.assertEqual(len(alias_calls), 1)
        saved_aliases = alias_calls[0].args[2]
        self.assertEqual(saved_aliases[backend._collaborator_name_key("NOME DUPLICADO")], "NOME CORRETO")

    def test_merge_multiple_collaborator_names_in_one_operation(self):
        executed = []

        class Result:
            rowcount = 2

        class Connection:
            def execute(self, statement, params=None):
                executed.append((str(statement), params or {}))
                return Result()

        class BeginContext:
            def __enter__(self):
                return Connection()

            def __exit__(self, exc_type, exc, traceback):
                return False

        class Engine:
            def begin(self):
                return BeginContext()

        with (
            patch.object(backend, "_db_engine", return_value=Engine()),
            patch.object(backend, "_ensure_dataset_table"),
            patch.object(backend, "_write_metadata") as write_metadata,
            patch.object(backend, "_clear_dataset_cache"),
            patch.object(backend, "_collaborator_aliases", return_value={}),
        ):
            result = backend.merge_collaborator_names_bulk(
                ["LUCAS.A", "LUCAS A", "LUCAS.A"], "LUCAS ALMEIDA"
            )

        update_calls = [item for item in executed if item[0].lstrip().upper().startswith("UPDATE")]
        self.assertEqual(len(update_calls), 5)
        self.assertTrue(all(" IN " in statement for statement, _ in update_calls))
        self.assertEqual(result["sources"], ["LUCAS.A", "LUCAS A"])
        self.assertEqual(result["updated_fields"], 10)
        alias_call = next(
            call for call in write_metadata.call_args_list
            if call.args[1] == backend.COLLABORATOR_ALIASES_METADATA_KEY
        )
        saved_aliases = alias_call.args[2]
        self.assertEqual(saved_aliases[backend._collaborator_name_key("LUCAS.A")], "LUCAS ALMEIDA")
        self.assertEqual(saved_aliases[backend._collaborator_name_key("LUCAS A")], "LUCAS ALMEIDA")

    def test_merge_multiple_route_names_and_save_aliases(self):
        executed = []

        class Result:
            rowcount = 2

        class Connection:
            def execute(self, statement, params=None):
                executed.append((str(statement), params or {}))
                return Result()

        class BeginContext:
            def __enter__(self):
                return Connection()

            def __exit__(self, exc_type, exc, traceback):
                return False

        class Engine:
            def begin(self):
                return BeginContext()

        with (
            patch.object(backend, "_db_engine", return_value=Engine()),
            patch.object(backend, "_ensure_dataset_table"),
            patch.object(backend, "_write_metadata") as write_metadata,
            patch.object(backend, "_clear_dataset_cache"),
            patch.object(backend, "_route_aliases", return_value={}),
        ):
            result = backend.merge_route_names_bulk(
                ["10 - DIVINOPOLIS", "ROTA 10 DIVINOPOLIS"], "10 - DIVINOPOLIS FERRAGENS"
            )

        update_calls = [item for item in executed if item[0].lstrip().upper().startswith("UPDATE")]
        self.assertEqual(len(update_calls), 4)
        self.assertTrue(all('SET "Rota" = :target' in statement for statement, _ in update_calls))
        self.assertEqual(result["updated_records"], 8)
        alias_call = next(
            call for call in write_metadata.call_args_list
            if call.args[1] == backend.ROUTE_ALIASES_METADATA_KEY
        )
        saved_aliases = alias_call.args[2]
        self.assertEqual(
            saved_aliases[backend._route_name_key("10 - DIVINOPOLIS")],
            "10 - DIVINOPOLIS FERRAGENS",
        )
        self.assertEqual(
            saved_aliases[backend._route_name_key("ROTA 10 DIVINOPOLIS")],
            "10 - DIVINOPOLIS FERRAGENS",
        )

    def test_route_merge_allows_correction_that_differs_only_by_accent(self):
        class Result:
            rowcount = 1

        class Connection:
            def execute(self, statement, params=None):
                return Result()

        class BeginContext:
            def __enter__(self):
                return Connection()

            def __exit__(self, exc_type, exc, traceback):
                return False

        class Engine:
            def begin(self):
                return BeginContext()

        with (
            patch.object(backend, "_db_engine", return_value=Engine()),
            patch.object(backend, "_ensure_dataset_table"),
            patch.object(backend, "_write_metadata") as write_metadata,
            patch.object(backend, "_clear_dataset_cache"),
            patch.object(backend, "_route_aliases", return_value={}),
        ):
            result = backend.merge_route_names_bulk(
                ["D+0,5 DIVINOPOLIS"], "D+0,5 DIVINÓPOLIS"
            )

        self.assertEqual(result["canonical"], "D+0,5 DIVINÓPOLIS")
        alias_call = next(
            call for call in write_metadata.call_args_list
            if call.args[1] == backend.ROUTE_ALIASES_METADATA_KEY
        )
        saved_aliases = alias_call.args[2]
        self.assertEqual(
            saved_aliases[backend._route_name_key("D+0,5 DIVINOPOLIS")],
            "D+0,5 DIVINÓPOLIS",
        )

    def test_future_route_import_uses_saved_canonical_name(self):
        aliases = {backend._route_name_key("ROTA ANTIGA"): "ROTA CORRETA"}
        with patch.object(backend, "_route_aliases", return_value=aliases):
            prepared = backend._prepare_insert_row("rotas", {"Rota": "Rota Antiga"})
        self.assertEqual(prepared["Rota"], "ROTA CORRETA")

    def test_route_name_summary_only_lists_completed_routes(self):
        complete_fields = {
            "Rota ID": "r1", "Data": "2026-10-13", "PLACA": "AAA1A11",
            "Motorista": "MOTORISTA A", "Categoria": "Transporte",
            "Saida": "2026-10-13 07:00", "Retorno": "2026-10-13 17:00",
            "Tempo Viagem Horas": 10, "Horas Trabalhadas": 10, "Dias Rota": 1,
            "KM Rodados": 100, "Entregas": 2, "Peso Carga": 1000,
        }
        routes = pd.DataFrame(
            [
                {**complete_fields, "Rota": "ROTA CONCLUIDA", "Status": "Concluída"},
                {**complete_fields, "Rota ID": "r2", "Rota": "ROTA PENDENTE", "Status": "Pendente"},
            ]
        )
        peso = pd.DataFrame(
            [
                {"Rota": "ROTA CONCLUIDA"},
                {"Rota": "ROTA PENDENTE"},
            ]
        )
        empty = pd.DataFrame(columns=["Rota"])
        with (
            patch.object(backend, "load_rotas", return_value=routes),
            patch.object(backend, "load_peso", return_value=peso),
            patch.object(backend, "load_rodagem_rota", return_value=empty),
            patch.object(backend, "load_velocidade", return_value=empty),
        ):
            summary = backend.route_name_summary()

        self.assertEqual([row["Rota"] for row in summary], ["ROTA CONCLUIDA"])
        self.assertEqual(summary[0]["Rotas concluídas"], 1)
        self.assertEqual(summary[0]["Registros de peso"], 1)

    def test_hotel_is_linked_to_specific_route_by_day_and_either_role(self):
        hotels = pd.DataFrame(
            [
                {
                    "Data": "2026-10-13", "Valor": 220.0, "Motorista": "PESSOA X",
                    "Ajudante": "", "Hotel": "HOTEL TESTE", "Cidade": "CIDADE TESTE",
                }
            ]
        )
        route_days = pd.DataFrame(
            [
                {
                    "Rota ID": "r1", "Data": "2026-10-13", "Rota": "ROTA 10", "PLACA": "AAA1A11",
                    "Motorista": "OUTRA PESSOA", "Ajudante": "PESSOA X", "Categoria": "Transporte",
                }
            ]
        )

        allocations, audit = backend._route_hotel_allocations_by_person_day(hotels, route_days)

        self.assertEqual(len(allocations), 1)
        self.assertEqual(allocations.iloc[0]["Rota ID"], "r1")
        self.assertEqual(allocations.iloc[0]["Valor Alocado"], 220.0)
        self.assertEqual(audit[0]["Nome encontrado"], "PESSOA X")
        self.assertIn("motorista ou ajudante", audit[0]["Critério"])

    def test_hotel_can_identify_unique_collaborator_by_first_two_names(self):
        hotels = pd.DataFrame(
            [{"Data": "2026-10-13", "Valor": 220.0, "Motorista": "RONALDO PEREIRA", "Ajudante": ""}]
        )
        route_days = pd.DataFrame(
            [
                {
                    "Rota ID": "r1", "Data": "2026-10-13", "Rota": "ROTA 10", "PLACA": "AAA1A11",
                    "Motorista": "OUTRA PESSOA", "Ajudante": "RONALDO PEREIRA CORDEIRO",
                    "Categoria": "Transporte",
                }
            ]
        )

        allocations, audit = backend._route_hotel_allocations_by_person_day(hotels, route_days)

        self.assertEqual(len(allocations), 1)
        self.assertEqual(allocations.iloc[0]["Rota ID"], "r1")
        self.assertEqual(audit[0]["Nome encontrado"], "RONALDO PEREIRA CORDEIRO")
        self.assertIn("dois primeiros nomes", audit[0]["Critério"])

    def test_hotel_does_not_guess_when_first_two_names_are_ambiguous(self):
        hotels = pd.DataFrame(
            [{"Data": "2026-10-13", "Valor": 220.0, "Motorista": "JOAO SILVA", "Ajudante": ""}]
        )
        route_days = pd.DataFrame(
            [
                {
                    "Rota ID": "r1", "Data": "2026-10-13", "Rota": "ROTA 10", "PLACA": "AAA1A11",
                    "Motorista": "JOAO SILVA SANTOS", "Ajudante": "", "Categoria": "Transporte",
                },
                {
                    "Rota ID": "r2", "Data": "2026-10-13", "Rota": "ROTA 20", "PLACA": "BBB1B11",
                    "Motorista": "JOAO SILVA SOUZA", "Ajudante": "", "Categoria": "Transporte",
                },
            ]
        )

        allocations, audit = backend._route_hotel_allocations_by_person_day(hotels, route_days)

        self.assertTrue(allocations.empty)
        self.assertEqual(audit[0]["Status"], "Sem vínculo")
        self.assertIn("dois primeiros nomes", audit[0]["Critério"])

    def test_hotel_prefers_multiday_route_and_legacy_method_remains_available(self):
        hotels = pd.DataFrame(
            [{"Data": "2026-10-13", "Valor": 240.0, "Motorista": "MOTORISTA A", "Ajudante": ""}]
        )
        route_days = pd.DataFrame(
            [
                {
                    "Rota ID": "curta", "Data": "2026-10-13", "Rota": "ROTA CURTA", "PLACA": "AAA1A11",
                    "Motorista": "MOTORISTA A", "Ajudante": "", "Categoria": "Transporte",
                },
                {
                    "Rota ID": "longa", "Data": "2026-10-13", "Rota": "ROTA LONGA", "PLACA": "BBB1B11",
                    "Motorista": "MOTORISTA A", "Ajudante": "", "Categoria": "Transporte",
                },
                {
                    "Rota ID": "longa", "Data": "2026-10-14", "Rota": "ROTA LONGA", "PLACA": "BBB1B11",
                    "Motorista": "MOTORISTA A", "Ajudante": "", "Categoria": "Transporte",
                },
            ]
        )

        allocations, audit = backend._route_hotel_allocations_by_person_day(hotels, route_days)
        legacy_allocations, _ = backend._legacy_route_hotel_allocations(hotels, route_days)

        self.assertEqual(allocations.iloc[0]["Rota ID"], "longa")
        self.assertEqual(allocations.iloc[0]["Valor Alocado"], 240.0)
        self.assertEqual(audit[0]["Candidatas"], 2)
        self.assertEqual(set(legacy_allocations["Rota ID"]), {"curta", "longa"})
        self.assertTrue(legacy_allocations["Valor Alocado"].eq(120.0).all())
        self.assertFalse(backend.USE_LEGACY_ROUTE_HOTEL_ALLOCATION)

    def test_pending_routes_never_enter_completed_scope(self):
        complete_fields = {
            "Data": "2026-10-13", "Rota": "ROTA COMPLETA", "PLACA": "AAA1A11",
            "Motorista": "MOTORISTA A", "Categoria": "Transporte",
            "Saida": "2026-10-13 07:00", "Retorno": "2026-10-13 17:00",
            "Tempo Viagem Horas": 10, "Horas Trabalhadas": 10, "Dias Rota": 1,
            "KM Rodados": 100, "Entregas": 2, "Peso Carga": 1000,
        }
        routes = pd.DataFrame(
            [
                {**complete_fields, "Rota ID": "ok", "Status": "Concluída"},
                {**complete_fields, "Rota ID": "pending", "Status": "Pendente"},
                {**complete_fields, "Rota ID": "blank", "Status": ""},
            ]
        )
        completed = backend._completed_route_rows(routes)
        self.assertEqual(completed["Rota ID"].tolist(), ["ok"])

    def test_completed_graph_scope_requires_real_operational_data(self):
        base = {
            "Data": "2026-10-13", "Rota": "ROTA", "PLACA": "AAA1A11",
            "Motorista": "MOTORISTA A", "Categoria": "Transporte", "Status": "Concluída",
            "Saida": "2026-10-13 07:00", "Retorno": "2026-10-13 17:00",
            "Tempo Viagem Horas": 10, "Horas Trabalhadas": 10, "Dias Rota": 1,
            "KM Rodados": 100, "Entregas": 2, "Peso Carga": 1000,
        }
        routes = pd.DataFrame(
            [
                {**base, "Rota ID": "complete"},
                {**base, "Rota ID": "without-km", "KM Rodados": 0},
                {**base, "Rota ID": "without-orders", "Entregas": 0},
                {**base, "Rota ID": "freighter", "Categoria": "Freteiro", "KM Rodados": 0},
            ]
        )

        completed = backend._completed_route_rows(routes)

        self.assertEqual(completed["Rota ID"].tolist(), ["complete", "freighter"])

    def test_financial_indicators_use_real_route_values(self):
        frame = dashboard._route_financial_frame(sample_payload())
        expensive = frame.loc[frame["Rota ID"].eq("r1")].iloc[0]
        self.assertEqual(expensive["Situação"], "Não vale a pena")
        self.assertAlmostEqual(float(expensive["Custo por entrega"]), 700.0)
        self.assertAlmostEqual(float(expensive["Custo por km"]), 14.0)
        self.assertAlmostEqual(float(expensive["Intervalos e noites"]), 14.0)

    def test_route_profitability_states_if_route_paid_for_itself(self):
        paid = dashboard._route_profitability_snapshot(
            pd.DataFrame(
                [
                    {"Rota ID": "r1", "Custo total": 700.0, "Ganho entregas": 1_000.0},
                    {"Rota ID": "r2", "Custo total": 100.0, "Ganho entregas": 200.0},
                ]
            )
        )
        loss = dashboard._route_profitability_snapshot(
            pd.DataFrame([{"Rota ID": "r3", "Custo total": 1_200.0, "Ganho entregas": 900.0}])
        )
        self.assertTrue(paid["se_pagou"])
        self.assertEqual(paid["situacao"], "Se pagou")
        self.assertAlmostEqual(float(paid["resultado"]), 400.0)
        self.assertFalse(loss["se_pagou"])
        self.assertEqual(loss["situacao"], "Não se pagou")
        self.assertAlmostEqual(float(loss["resultado"]), -300.0)

    def test_unprofitable_trips_are_listed_from_biggest_loss(self):
        losses = dashboard._route_unprofitable_trips(
            dashboard._route_financial_frame(sample_payload())
        )
        self.assertEqual(losses["Rota"].tolist(), ["ROTA CARA"])
        self.assertAlmostEqual(float(losses.iloc[0]["Faltou para se pagar"]), 1_000.0)
        self.assertAlmostEqual(float(losses.iloc[0]["Custo/receita %"]), 116.666666, places=4)

    def test_operational_map_uses_real_city_metrics_and_known_coordinates(self):
        cities = dashboard._route_city_map_frame(
            {
                "ranking_cidades": [
                    {"Cidade": "Divinópolis - MG", "Rotas": 3, "Entregas": 12, "Peso kg": 5000, "Valor Notas": 9000},
                    {"Cidade": "Uberlândia - MG", "Rotas": 2, "Entregas": 5, "Peso kg": 1000, "Valor Notas": 2500},
                    {"Cidade": "Cidade sem cadastro", "Rotas": 1, "Entregas": 2, "Peso kg": 200, "Valor Notas": 500},
                ],
                "entregas_detalhes": [
                    {"Entrega ID": "e1", "Rota ID": "r1", "Cidade": "Divinópolis - MG", "Valor Nota": 800},
                    {"Entrega ID": "e2", "Rota ID": "r1", "Cidade": "Uberlândia - MG", "Valor Nota": 200},
                    {"Entrega ID": "e3", "Rota ID": "r2", "Cidade": "Uberlândia - MG", "Valor Nota": 1000},
                ],
            },
            pd.DataFrame(
                [
                    {"Rota ID": "r1", "Custo total": 1000},
                    {"Rota ID": "r2", "Custo total": 500},
                ]
            ),
        )
        indexed = cities.set_index("Cidade")
        mapped = indexed["Localizada"].to_dict()
        self.assertTrue(mapped["Divinópolis - MG"])
        self.assertTrue(mapped["Uberlândia - MG"])
        self.assertFalse(mapped["Cidade sem cadastro"])
        self.assertEqual(float(indexed.loc["Divinópolis - MG", "Gasto operacional"]), 800.0)
        self.assertEqual(float(indexed.loc["Uberlândia - MG", "Gasto operacional"]), 700.0)
        self.assertEqual(float(cities["Entregas"].sum()), 19.0)
        self.assertTrue(dashboard.MAP_PLOTLY_CONFIG["scrollZoom"])

    def test_weekly_forecast_and_cost_explanation_use_completed_weeks(self):
        weeks = pd.date_range("2026-09-14", periods=6, freq="7D")
        data = {
            "tempos_rotas": [
                {"Rota ID": f"r{index}", "Data": week, "Entregas": 10 + index, "KM Rodados": 100 + index * 10}
                for index, week in enumerate(weeks)
            ]
        }
        financial = pd.DataFrame(
            [
                {
                    "Rota ID": f"r{index}", "Data": week, "Custo total": 1000 + index * 100,
                    "Combustivel": 600 + index * 80, "Manutencao": 100 + index * 20,
                    "Pedagio": 100, "Hoteis": 100, "Salarios": 100, "Freteiro": 0,
                }
                for index, week in enumerate(weeks)
            ]
        )
        weekly = dashboard._route_weekly_history(data, financial, today=pd.Timestamp("2026-10-27"))
        forecast = dashboard._route_forecast(weekly)
        change = dashboard._route_cost_change_snapshot(financial, today=pd.Timestamp("2026-10-27"))
        self.assertEqual(len(weekly), 6)
        self.assertEqual(len(forecast), 12)
        self.assertEqual(set(forecast["Métrica"]), {"Entregas", "KM", "Custos"})
        self.assertTrue(change["disponivel"])
        self.assertAlmostEqual(float(change["variacao"]), 100.0)
        self.assertEqual(change["contribuicoes"][0]["Categoria"], "Combustível")

    def test_fuel_cost_uses_plate_history_per_km(self):
        fuel = pd.DataFrame(
            [
                {"Data": "2026-01-05", "PLACA": "AAA1A11", "Custo": 1_000.0},
                {"Data": "2099-01-05", "PLACA": "AAA1A11", "Custo": 9_999.0},
            ]
        )
        mileage = pd.DataFrame(
            [
                {"Mes": "2026-01", "PLACA": "AAA1A11", "Km Rodados": 400.0},
                {"Mes": "2099-01", "PLACA": "AAA1A11", "Km Rodados": 1.0},
            ]
        )
        rates = backend._historical_plate_fuel_rates(
            fuel, mileage, cutoff=pd.Timestamp("2026-10-27")
        )
        self.assertEqual(len(rates), 1)
        self.assertAlmostEqual(float(rates.iloc[0]["Combustivel R$/km"]), 2.5)
        allocated, warnings = backend._route_fuel_costs_from_history(
            pd.DataFrame(
                [{"Rota ID": "r1", "Rota": "ROTA TESTE", "PLACA": "AAA1A11", "Km Rodados": 100.0}]
            ),
            rates,
        )
        self.assertEqual(warnings, [])
        self.assertAlmostEqual(float(allocated.iloc[0]["Custo"]), 250.0)

        routes = pd.DataFrame(
            [
                {
                    "Rota ID": "r1", "Data": pd.Timestamp("2026-10-20"),
                    "Saida": pd.Timestamp("2026-10-20 07:00"),
                    "Retorno": pd.Timestamp("2026-10-20 17:00"), "Mes": "2026-10",
                    "Rota": "ROTA TESTE", "PLACA": "AAA1A11", "Motorista": "TESTE",
                    "Categoria": "Transporte", "KM Rodados": 100.0,
                }
            ]
        )
        deliveries = pd.DataFrame([{"Rota ID": "r1", "Valor Nota": 1_000.0}])
        empty_costs = pd.DataFrame(columns=["Data", "Mes", "PLACA", "Custo"])
        empty_salary = pd.DataFrame(columns=["Mes", "Valor"])
        empty_hotels = pd.DataFrame(columns=["Data", "Valor", "Motorista", "Ajudante"])
        with (
            patch.object(backend, "load_combustivel", return_value=fuel),
            patch.object(backend, "load_combustivel_km", return_value=mileage),
            patch.object(backend, "load_manutencao", return_value=empty_costs),
            patch.object(backend, "load_pedagio", return_value=empty_costs),
            patch.object(backend, "load_salarios_transporte", return_value=empty_salary),
            patch.object(backend, "load_hoteis", return_value=empty_hotels),
            patch.object(backend, "_ranking_freighter_daily_rates", return_value={}),
            patch.object(backend, "_apply_plate_categories", side_effect=lambda frame: frame),
        ):
            result = backend._route_cost_breakdown(routes, routes, deliveries)
        route_cost = result["rotas"][0]
        self.assertAlmostEqual(float(route_cost["Combustivel R$/km"]), 2.5)
        self.assertAlmostEqual(float(route_cost["Combustivel"]), 250.0)
        self.assertEqual(float(route_cost["Diaria Motorista"]), 100.0)
        self.assertEqual(float(route_cost["Diaria Ajudante"]), 100.0)
        self.assertEqual(float(route_cost["Diarias Equipe"]), 200.0)
        self.assertEqual(float(route_cost["Custo total"]), 450.0)

    def test_general_route_cost_adds_staff_daily_by_route_day_and_category(self):
        routes = pd.DataFrame(
            [
                {
                    "Rota ID": "own", "Data": pd.Timestamp("2026-10-20"),
                    "Saida": pd.Timestamp("2026-10-20 07:00"),
                    "Retorno": pd.Timestamp("2026-10-21 17:00"), "Mes": "2026-10",
                    "Rota": "D+0,5 DIVINOPOLIS FERRAGENS", "PLACA": "AAA1A11",
                    "Motorista": "MOTORISTA A", "Ajudante": "AJUDANTE A",
                    "Categoria": "Transporte", "KM Rodados": 0.0, "Horas Trabalhadas": 10.0,
                },
                {
                    "Rota ID": "freight", "Data": pd.Timestamp("2026-10-20"),
                    "Saida": pd.Timestamp("2026-10-20 07:00"),
                    "Retorno": pd.Timestamp("2026-10-21 17:00"), "Mes": "2026-10",
                    "Rota": "404 - ITABIRA - GUANHAES", "PLACA": "FRT1A11",
                    "Motorista": "MOTORISTA F", "Ajudante": "AJUDANTE F",
                    "Categoria": "Freteiro", "KM Rodados": 0.0, "Horas Trabalhadas": 10.0,
                },
            ]
        )
        empty_fuel = pd.DataFrame(columns=["Data", "Mes", "PLACA", "Custo"])
        empty_mileage = pd.DataFrame(columns=["Mes", "PLACA", "Km Rodados"])
        empty_salary = pd.DataFrame(columns=["Mes", "Valor"])
        empty_hotels = pd.DataFrame(columns=["Data", "Valor", "Motorista", "Ajudante"])
        with (
            patch.object(backend, "load_combustivel", return_value=empty_fuel),
            patch.object(backend, "load_combustivel_km", return_value=empty_mileage),
            patch.object(backend, "load_manutencao", return_value=empty_fuel),
            patch.object(backend, "load_pedagio", return_value=empty_fuel),
            patch.object(backend, "load_salarios_transporte", return_value=empty_salary),
            patch.object(backend, "load_hoteis", return_value=empty_hotels),
            patch.object(backend, "_ranking_freighter_daily_rates", return_value={"FRT1A11": 700.0}),
            patch.object(backend, "_apply_plate_categories", side_effect=lambda frame: frame),
        ):
            result = backend._route_cost_breakdown(routes, routes, pd.DataFrame())
            salary_result = backend._route_cost_breakdown(
                routes,
                routes,
                pd.DataFrame(),
                staff_costs={
                    "include_dailies": False,
                    "include_salaries": True,
                    "driver_hourly_rate": 20.0,
                    "helper_hourly_rate": 10.0,
                },
            )

        costs = {row["Rota ID"]: row for row in result["rotas"]}
        self.assertEqual(costs["own"]["Diaria Motorista"], 64.0)
        self.assertEqual(costs["own"]["Diaria Ajudante"], 64.0)
        self.assertEqual(costs["own"]["Custo total"], 128.0)
        self.assertEqual(costs["freight"]["Diaria Motorista"], 0.0)
        self.assertEqual(costs["freight"]["Diaria Ajudante"], 200.0)
        self.assertEqual(costs["freight"]["Freteiro"], 1_400.0)
        self.assertEqual(costs["freight"]["Custo total"], 1_600.0)

        salary_costs = {row["Rota ID"]: row for row in salary_result["rotas"]}
        self.assertEqual(salary_costs["own"]["Diarias Equipe"], 0.0)
        self.assertEqual(salary_costs["own"]["Salario Motorista"], 200.0)
        self.assertEqual(salary_costs["own"]["Salario Ajudante"], 100.0)
        self.assertEqual(salary_costs["own"]["Salarios"], 300.0)
        self.assertEqual(salary_costs["freight"]["Salario Motorista"], 0.0)
        self.assertEqual(salary_costs["freight"]["Salario Ajudante"], 100.0)
        self.assertEqual(salary_costs["freight"]["Salarios"], 100.0)

    def test_shared_plate_interval_counts_hours_and_team_cost_only_once(self):
        routes = pd.DataFrame(
            [
                {
                    "Rota ID": "r1", "Data": pd.Timestamp("2026-10-20"),
                    "Saida": pd.Timestamp("2026-10-20 07:00"), "Retorno": pd.Timestamp("2026-10-20 17:00"),
                    "Mes": "2026-10", "Rota": "ROTA 1", "PLACA": "AAA1A11", "Motorista": "MOTORISTA A",
                    "Ajudante": "AJUDANTE A", "Categoria": "Transporte", "KM Rodados": 50.0,
                    "Tempo Viagem Horas": 10.0, "Horas Trabalhadas": 10.0, "Dias Rota": 1,
                    "Entregas": 2, "Peso Carga": 1_000.0,
                },
                {
                    "Rota ID": "r2", "Data": pd.Timestamp("2026-10-20"),
                    "Saida": pd.Timestamp("2026-10-20 07:00"), "Retorno": pd.Timestamp("2026-10-20 17:00"),
                    "Mes": "2026-10", "Rota": "ROTA 2", "PLACA": "AAA1A11", "Motorista": "MOTORISTA A",
                    "Ajudante": "AJUDANTE A", "Categoria": "Transporte", "KM Rodados": 50.0,
                    "Tempo Viagem Horas": 10.0, "Horas Trabalhadas": 10.0, "Dias Rota": 1,
                    "Entregas": 3, "Peso Carga": 2_000.0,
                },
            ]
        )
        metrics = backend._route_metric_source(routes, pd.DataFrame())
        self.assertEqual(float(metrics["Horas Trabalhadas"].sum()), 10.0)
        self.assertEqual(float(metrics["Tempo Viagem Horas"].sum()), 10.0)
        self.assertEqual(float(metrics["Dias Rota"].sum()), 1.0)
        self.assertEqual(float(metrics["Entregas"].sum()), 5.0)
        self.assertTrue(metrics["Rotas na Operacao"].eq(2.0).all())

        empty_costs = pd.DataFrame(columns=["Data", "Mes", "PLACA", "Custo"])
        empty_salary = pd.DataFrame(columns=["Mes", "Valor"])
        empty_hotels = pd.DataFrame(columns=["Data", "Valor", "Motorista", "Ajudante"])
        with (
            patch.object(backend, "load_combustivel", return_value=empty_costs),
            patch.object(backend, "load_combustivel_km", return_value=pd.DataFrame(columns=["Mes", "PLACA", "Km Rodados"])),
            patch.object(backend, "load_manutencao", return_value=empty_costs),
            patch.object(backend, "load_pedagio", return_value=empty_costs),
            patch.object(backend, "load_salarios_transporte", return_value=empty_salary),
            patch.object(backend, "load_hoteis", return_value=empty_hotels),
            patch.object(backend, "_ranking_freighter_daily_rates", return_value={}),
            patch.object(backend, "_apply_plate_categories", side_effect=lambda frame: frame),
        ):
            daily_result = backend._route_cost_breakdown(routes, routes, pd.DataFrame())
            salary_result = backend._route_cost_breakdown(
                routes,
                routes,
                pd.DataFrame(),
                staff_costs={
                    "include_dailies": False,
                    "include_salaries": True,
                    "driver_hourly_rate": 20.0,
                    "helper_hourly_rate": 10.0,
                },
            )

        self.assertEqual(sum(row["Diaria Motorista"] for row in daily_result["rotas"]), 100.0)
        self.assertEqual(sum(row["Diaria Ajudante"] for row in daily_result["rotas"]), 100.0)
        self.assertEqual(sum(row["Salario Motorista"] for row in salary_result["rotas"]), 200.0)
        self.assertEqual(sum(row["Salario Ajudante"] for row in salary_result["rotas"]), 100.0)

    def test_maintenance_uses_plate_daily_average_and_splits_shared_day(self):
        routes = pd.DataFrame(
            [
                {
                    "Rota ID": "r1", "Data": pd.Timestamp("2026-10-01"),
                    "Saida": pd.Timestamp("2026-10-01 07:00"),
                    "Retorno": pd.Timestamp("2026-10-01 17:00"), "Mes": "2026-10",
                    "Rota": "ROTA 1", "PLACA": "AAA1A11", "Motorista": "MOTORISTA A",
                    "Ajudante": "AJUDANTE A", "Categoria": "Transporte", "KM Rodados": 0.0,
                },
                {
                    "Rota ID": "r2", "Data": pd.Timestamp("2026-10-01"),
                    "Saida": pd.Timestamp("2026-10-01 07:00"),
                    "Retorno": pd.Timestamp("2026-10-01 17:00"), "Mes": "2026-10",
                    "Rota": "ROTA 2", "PLACA": "AAA1A11", "Motorista": "MOTORISTA A",
                    "Ajudante": "AJUDANTE A", "Categoria": "Transporte", "KM Rodados": 0.0,
                },
                {
                    "Rota ID": "r3", "Data": pd.Timestamp("2026-11-02"),
                    "Saida": pd.Timestamp("2026-11-02 07:00"),
                    "Retorno": pd.Timestamp("2026-11-02 17:00"), "Mes": "2026-11",
                    "Rota": "ROTA 3", "PLACA": "AAA1A11", "Motorista": "MOTORISTA A",
                    "Ajudante": "AJUDANTE A", "Categoria": "Transporte", "KM Rodados": 0.0,
                },
            ]
        )
        maintenance = pd.DataFrame(
            [
                {"Data": "2026-10-15", "Mes": "2026-10", "PLACA": "AAA1A11", "Custo": 900.0},
                {"Data": "2026-11-15", "Mes": "2026-11", "PLACA": "AAA1A11", "Custo": 100.0},
            ]
        )
        empty_fuel = pd.DataFrame(columns=["Data", "Mes", "PLACA", "Custo"])
        empty_mileage = pd.DataFrame(columns=["Mes", "PLACA", "Km Rodados"])
        empty_hotels = pd.DataFrame(columns=["Data", "Valor", "Motorista", "Ajudante"])
        with (
            patch.object(backend, "load_combustivel", return_value=empty_fuel),
            patch.object(backend, "load_combustivel_km", return_value=empty_mileage),
            patch.object(backend, "load_manutencao", return_value=maintenance),
            patch.object(backend, "load_pedagio", return_value=empty_fuel),
            patch.object(backend, "load_hoteis", return_value=empty_hotels),
            patch.object(backend, "_ranking_freighter_daily_rates", return_value={}),
            patch.object(backend, "_apply_plate_categories", side_effect=lambda frame: frame),
        ):
            result = backend._route_cost_breakdown(
                routes,
                routes,
                pd.DataFrame(),
                staff_costs={"include_dailies": False, "include_salaries": False},
            )

        costs = {row["Rota ID"]: row for row in result["rotas"]}
        self.assertEqual(result["metodo_manutencao"], "media_mensal_diaria_por_placa")
        self.assertEqual(costs["r1"]["Manutencao R$/dia"], 900.0)
        self.assertEqual(costs["r1"]["Manutencao"], 450.0)
        self.assertEqual(costs["r2"]["Manutencao"], 450.0)
        self.assertEqual(costs["r3"]["Manutencao R$/dia"], 100.0)
        self.assertEqual(costs["r3"]["Manutencao"], 100.0)
        self.assertEqual(sum(row["Manutencao"] for row in costs.values()), 1_000.0)

    def test_route_summary_preserves_operational_result_name(self):
        summary = dashboard._route_summary_table(dashboard._route_financial_frame(sample_payload()))
        worst = summary.iloc[0]
        self.assertEqual(worst["Rota"], "ROTA CARA")
        self.assertEqual(worst["Situação"], "Não vale a pena")
        self.assertAlmostEqual(float(worst["Resultado operacional"]), -1_000.0)

    def test_route_status_colors_the_entire_row(self):
        frame = pd.DataFrame(
            [
                {"Rota": "BOA", "Situação": "Saudável"},
                {"Rota": "ATENCAO", "Situação": "Atenção"},
                {"Rota": "CRITICA", "Situação": "Não vale a pena"},
            ]
        )
        healthy = dashboard._route_status_row_style(frame.iloc[0])
        attention = dashboard._route_status_row_style(frame.iloc[1])
        critical = dashboard._route_status_row_style(frame.iloc[2])
        self.assertTrue(all("#BBF7D0" in css for css in healthy))
        self.assertTrue(all("#FED7AA" in css for css in attention))
        self.assertTrue(all("#FECACA" in css for css in critical))

    def test_period_presets_are_deterministic(self):
        minimum, maximum = date(2026, 1, 1), date(2026, 10, 27)
        start, end = dashboard._route_period_dates("Todo o período", minimum, maximum, None)
        self.assertEqual((start, end), (minimum, maximum))
        start, end = dashboard._route_period_dates(
            "Intervalo personalizado", minimum, maximum, (date(2026, 10, 1), date(2026, 10, 15))
        )
        self.assertEqual((start, end), (date(2026, 10, 1), date(2026, 10, 15)))

    def test_management_exports_are_valid_files(self):
        raw = json.dumps(sample_payload(), ensure_ascii=False, default=str, sort_keys=True)
        workbook = dashboard._route_management_workbook(raw)
        report = dashboard._route_management_pdf(raw, "01/10/2026 — 27/10/2026")
        self.assertTrue(zipfile.is_zipfile(BytesIO(workbook)))
        self.assertTrue(report.startswith(b"%PDF-"))


if __name__ == "__main__":
    unittest.main()
