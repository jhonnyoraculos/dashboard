import json
import os
import unittest
import zipfile
from datetime import date
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
        self.assertEqual(quote["freighter_days"], 1.5)
        self.assertEqual(quote["freighter_daily_rate"], 800)
        self.assertEqual(quote["freighter_daily_cost"], 1_200)
        self.assertEqual(quote["freighter_excess_km"], 210)
        self.assertEqual(quote["freighter_excess_cost"], 1_050)
        self.assertEqual(quote["freighter_cost"], 2_250)
        self.assertEqual(quote["vehicle_component"], 2_250)
        self.assertEqual(quote["assistant_days"], 1.5)
        self.assertEqual(quote["assistant_daily_rate"], 32)
        self.assertEqual(quote["assistant_cost"], 48)
        self.assertEqual(quote["distance_component"], 0)
        self.assertEqual(quote["estimated_cost"], 2_298)
        self.assertEqual(quote["suggested_freight"], 2_527.8)

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
        }
        comparison = dashboard._freight_plate_comparison(
            ["FRT1A11", "TRP1A11"],
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

        self.assertEqual(comparison.loc["FRT1A11", "Custo do veículo"], 2_250)
        self.assertEqual(comparison.loc["FRT1A11", "Ajudante"], 48)
        self.assertEqual(comparison.loc["TRP1A11", "Custo do veículo"], 1_980)
        self.assertEqual(comparison.loc["TRP1A11", "Motorista"], 0)
        self.assertEqual(comparison.loc["TRP1A11", "Ajudante"], 0)
        self.assertEqual(comparison.loc["TRP1A11", "Diferença para o menor"], 0)
        self.assertEqual(comparison.loc["FRT1A11", "Diferença para o menor"], 318)

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
        routes = pd.DataFrame(
            [
                {"Rota": "ROTA CONCLUIDA", "Status": "Concluída"},
                {"Rota": "ROTA PENDENTE", "Status": "Pendente"},
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
        routes = pd.DataFrame(
            [
                {"Rota ID": "ok", "Status": "Concluída"},
                {"Rota ID": "pending", "Status": "Pendente"},
                {"Rota ID": "blank", "Status": ""},
            ]
        )
        completed = backend._completed_route_rows(routes)
        self.assertEqual(completed["Rota ID"].tolist(), ["ok"])

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
                ]
            }
        )
        mapped = cities.set_index("Cidade")["Localizada"].to_dict()
        self.assertTrue(mapped["Divinópolis - MG"])
        self.assertTrue(mapped["Uberlândia - MG"])
        self.assertFalse(mapped["Cidade sem cadastro"])
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

    def test_route_summary_preserves_operational_result_name(self):
        summary = dashboard._route_summary_table(dashboard._route_financial_frame(sample_payload()))
        worst = summary.iloc[0]
        self.assertEqual(worst["Rota"], "ROTA CARA")
        self.assertEqual(worst["Situação"], "Não vale a pena")
        self.assertAlmostEqual(float(worst["Resultado operacional"]), -1_000.0)

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
