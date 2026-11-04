import unittest
from io import BytesIO

import pandas as pd

from route_tracker import match_tracker_cycles, parse_tracker_report


def tracker_workbook() -> bytes:
    rows = [
        [None, "Relatório de ignição", None, None, None, None, None],
        [None, "Placa", "Ign", "Data/Hora Inicial", "Data/Hora Final", None, "Distância Percorrida (KM)"],
        [None, "AAA-1A11", "Desligado", "05/11/2026 05:00:00", "05/11/2026 06:00:00", "Av. Marginal - Divinópolis-MG", "0,00"],
        [None, "AAA-1A11", "Ligado", "05/11/2026 06:00:00", "05/11/2026 07:00:00", "MG-050 - Carmo do Cajuru - MG", "50,00"],
        [None, "AAA-1A11", "Desligado", "05/11/2026 07:00:00", "05/11/2026 08:00:00", "MG-050 - Carmo do Cajuru - MG", "0,00"],
        [None, "AAA-1A11", "Ligado", "05/11/2026 08:00:00", "05/11/2026 17:00:00", "Rua Teste - Uberlândia-MG", "100,00"],
        [None, "AAA-1A11", "Desligado", "05/11/2026 17:00:00", "06/11/2026 08:00:00", "Rua Teste - Uberlândia-MG", "0,00"],
        [None, "AAA-1A11", "Ligado", "06/11/2026 08:00:00", "06/11/2026 12:00:00", "Rua Jundiaí - Divinópolis-MG", "150,00"],
        [None, "AAA-1A11", "Desligado", "06/11/2026 12:00:00", "06/11/2026 18:00:00", "Rua Jundiaí - Divinópolis-MG", "0,00"],
    ]
    buffer = BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False, header=False, engine="openpyxl")
    return buffer.getvalue()


def tracker_workbook_with_initial_and_final_locations() -> bytes:
    rows = [
        [None, "Relatório completo", None, None, None, None, None, None],
        [
            None,
            "Placa",
            "Ign",
            "Data/Hora Inicial",
            "Localização Inicial",
            "Data/Hora Final",
            "Localização Final",
            "Distância Percorrida (KM)",
        ],
        [None, "BBB-2B22", "Desligado", "07/11/2026 05:00:00", "Av. Marginal - Divinópolis-MG", "07/11/2026 06:00:00", "Av. Marginal - Divinópolis-MG", "0,00"],
        [None, "BBB-2B22", "Ligado", "07/11/2026 06:00:00", "Av. Marginal - Divinópolis-MG", "07/11/2026 08:00:00", "Cliente A - Pará de Minas-MG", "80,00"],
        [None, "BBB-2B22", "Desligado", "07/11/2026 08:00:00", "Cliente A - Pará de Minas-MG", "07/11/2026 08:30:00", "Cliente A - Pará de Minas-MG", "0,00"],
        [None, "BBB-2B22", "Ligado", "07/11/2026 08:30:00", "Cliente A - Pará de Minas-MG", "07/11/2026 10:00:00", "Av. Marginal - Divinópolis-MG", "75,00"],
        [None, "BBB-2B22", "Ligado", "07/11/2026 13:00:00", "Av. Marginal - Divinópolis-MG", "07/11/2026 14:00:00", "Cliente B - Itaúna-MG", "40,00"],
        # A chegada pode aparecer em uma linha desligada e com KM zero.
        [None, "BBB-2B22", "Desligado", "07/11/2026 14:00:00", "Cliente B - Itaúna-MG", "07/11/2026 15:00:00", "Av. Marginal - Divinópolis-MG", "0,00"],
    ]
    buffer = BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False, header=False, engine="openpyxl")
    return buffer.getvalue()


class RouteTrackerTests(unittest.TestCase):
    def test_tracker_builds_daily_journeys_without_counting_the_night(self):
        cycles, events, warnings = parse_tracker_report(tracker_workbook(), "rastreador.xlsx")
        self.assertEqual(len(events), 7)
        self.assertEqual(warnings, [])
        self.assertEqual(len(cycles), 1)
        cycle = cycles[0]
        self.assertTrue(cycle["Completa"])
        self.assertEqual(cycle["Placa"], "AAA1A11")
        self.assertEqual(cycle["KM total"], 300.0)
        self.assertEqual(cycle["Dias"], 2)
        self.assertAlmostEqual(cycle["Tempo viagem h"], 30.0)
        self.assertAlmostEqual(cycle["Horas trabalhadas"], 15.0)
        self.assertEqual(cycle["Jornadas"][0]["saida"], "2026-11-05T06:00:00")
        self.assertEqual(cycle["Jornadas"][0]["parada"], "2026-11-05T17:00:00")
        self.assertEqual(cycle["Jornadas"][1]["saida"], "2026-11-06T08:00:00")
        self.assertEqual(cycle["Jornadas"][1]["parada"], "2026-11-06T12:00:00")

    def test_tracker_matches_only_pending_routes_and_splits_trip_km(self):
        cycles, _events, _warnings = parse_tracker_report(tracker_workbook())
        routes = pd.DataFrame(
            [
                {"Rota ID": "r1", "Status": "Pendente", "PLACA": "AAA1A11", "Data": "2026-11-05", "Rota": "ROTA A", "Carga": "1"},
                {"Rota ID": "r2", "Status": "Pendente", "PLACA": "AAA-1A11", "Data": "2026-11-05", "Rota": "ROTA B", "Carga": "2"},
                {"Rota ID": "r3", "Status": "Concluída", "PLACA": "AAA1A11", "Data": "2026-11-05", "Rota": "ROTA ANTIGA", "Carga": "3"},
            ]
        )
        matches = match_tracker_cycles(cycles, routes)
        self.assertEqual(len(matches), 1)
        self.assertTrue(matches[0]["Pode importar"])
        self.assertEqual(matches[0]["Rota IDs"], ["r1", "r2"])
        self.assertEqual(matches[0]["Quantidade rotas"], 2)
        self.assertEqual(matches[0]["KM por rota"], 150.0)
        self.assertNotIn("r3", matches[0]["Rota IDs"])

    def test_tracker_uses_both_locations_and_consolidates_same_day_departures(self):
        cycles, events, warnings = parse_tracker_report(tracker_workbook_with_initial_and_final_locations())
        self.assertEqual(warnings, [])
        self.assertIn("LocalizacaoInicial", events.columns)
        self.assertIn("LocalizacaoFinal", events.columns)
        self.assertEqual(len(cycles), 1)
        cycle = cycles[0]
        self.assertEqual(cycle["Placa"], "BBB2B22")
        self.assertEqual(cycle["Saida"], pd.Timestamp("2026-11-07 06:00:00"))
        self.assertEqual(cycle["Retorno"], pd.Timestamp("2026-11-07 15:00:00"))
        self.assertEqual(cycle["KM total"], 195.0)
        self.assertEqual(cycle["Dias"], 1)
        self.assertAlmostEqual(cycle["Horas trabalhadas"], 9.0)
        self.assertIn("2 saída(s)", cycle["Situação"])


if __name__ == "__main__":
    unittest.main()
