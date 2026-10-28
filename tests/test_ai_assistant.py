import unittest
from types import SimpleNamespace

import ai_assistant as ai


def fake_response(content="", tool_calls=None, prompt_tokens=10, completion_tokens=5):
    message = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))


class AssistantTests(unittest.TestCase):
    def test_configuration_uses_environment_without_exposing_defaults(self):
        config = ai.AssistantConfig.from_sources(
            {
                "GROQ_API_KEY": "test-key",
                "GROQ_MODEL": "openai/gpt-oss-120b",
                "AI_SESSION_MESSAGE_LIMIT": "12",
                "GROQ_MAX_OUTPUT_TOKENS": "900",
            }
        )
        self.assertEqual(config.api_key, "test-key")
        self.assertEqual(config.session_message_limit, 12)
        self.assertEqual(config.max_output_tokens, 900)

    def test_compact_data_removes_sensitive_and_detailed_fields(self):
        compact = ai.compact_data(
            {
                "custo_total": 1250,
                "Telefone": "31999999999",
                "Endereco cliente": "Rua interna",
                "entregas_detalhes": [{"Pedido": "1"}],
                "ranking": list(range(30)),
            },
            max_items=5,
        )
        self.assertEqual(compact["custo_total"], 1250)
        self.assertNotIn("Telefone", compact)
        self.assertNotIn("Endereco cliente", compact)
        self.assertNotIn("entregas_detalhes", compact)
        self.assertLessEqual(len(compact["ranking"]), 6)

    def test_dashboard_summary_keeps_aggregates_and_drops_raw_rows(self):
        summary = ai.dashboard_summary_payload(
            "rotas",
            {
                "total_rotas": 8,
                "km_total": 450,
                "ranking_motoristas": [{"Motorista": "A", "Pontuacao": 90}],
                "rotas_detalhes": [{"Rota ID": "segredo"}],
            },
        )
        self.assertEqual(summary["metricas"]["total_rotas"], 8.0)
        self.assertIn("ranking_motoristas", summary)
        self.assertNotIn("rotas_detalhes", summary)

    def test_agent_executes_read_only_tool_loop(self):
        tool_call = SimpleNamespace(
            id="call-1",
            function=SimpleNamespace(name="get_current_page_context", arguments="{}"),
        )
        client = FakeClient(
            [
                fake_response(tool_calls=[tool_call], prompt_tokens=11, completion_tokens=3),
                fake_response(content="O custo foi R$ 1.250, conforme o contexto.", prompt_tokens=13, completion_tokens=7),
            ]
        )
        config = ai.AssistantConfig(api_key="test", global_daily_request_limit=100_000, global_daily_token_limit=10_000_000)
        assistant = ai.GroqDashboardAssistant(config, client=client)
        called = []

        result = assistant.answer(
            "Qual foi o custo?",
            history=[],
            page_context={"pagina": "rotas"},
            tool_executor=lambda name, arguments: called.append((name, arguments)) or {"custo": 1250},
        )

        self.assertEqual(called, [("get_current_page_context", {})])
        self.assertIn("1.250", result.answer)
        self.assertEqual(result.tool_calls, 1)
        self.assertEqual(result.prompt_tokens, 24)
        second_messages = client.chat.completions.calls[1]["messages"]
        tool_messages = [message for message in second_messages if message["role"] == "tool"]
        self.assertEqual(len(tool_messages), 1)
        self.assertIn("1250", tool_messages[0]["content"])

    def test_agent_is_optional_when_key_is_missing(self):
        assistant = ai.GroqDashboardAssistant(ai.AssistantConfig(api_key=""), client=None)
        self.assertFalse(assistant.available)
        with self.assertRaises(ai.AssistantError):
            assistant.answer("teste", history=[], page_context={}, tool_executor=lambda *_: {})

    def test_tools_never_expose_sql_or_code_execution(self):
        names = {tool["function"]["name"] for tool in ai.TOOL_SCHEMAS}
        self.assertNotIn("execute_sql", names)
        self.assertNotIn("execute_python", names)
        self.assertIn("get_dashboard_metrics", names)
        self.assertEqual(ai.normalize_page("ranking"), "frota")


if __name__ == "__main__":
    unittest.main()
