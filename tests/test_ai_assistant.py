import unittest
from types import SimpleNamespace
from unittest.mock import patch

import ai_assistant as ai


def fake_response(content="", tool_calls=None, prompt_tokens=10, completion_tokens=5, finish_reason="stop"):
    message = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


class FakeAPIError(RuntimeError):
    def __init__(self, status_code):
        super().__init__(f"status {status_code}")
        self.status_code = status_code
        self.response = SimpleNamespace(headers={})


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


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
        self.assertEqual(config.fallback_model, "openai/gpt-oss-20b")

    def test_configuration_accepts_nested_streamlit_groq_section(self):
        config = ai.AssistantConfig.from_sources(
            environment={},
            secrets={"groq": {"api_key": "nested-key", "model": "openai/gpt-oss-120b"}},
        )
        self.assertEqual(config.api_key, "nested-key")
        self.assertEqual(config.model, "openai/gpt-oss-120b")

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

    def test_transient_primary_failure_uses_fallback_model(self):
        client = FakeClient(
            [
                FakeAPIError(503),
                FakeAPIError(503),
                FakeAPIError(503),
                fake_response(content="Resposta pelo modelo de contingência."),
            ]
        )
        config = ai.AssistantConfig(
            api_key="test",
            global_daily_request_limit=100_000,
            global_daily_token_limit=10_000_000,
        )
        assistant = ai.GroqDashboardAssistant(config, client=client)

        with patch("ai_assistant.time.sleep"):
            result = assistant.answer("Teste", history=[], page_context={}, tool_executor=lambda *_: {})

        models = [call["model"] for call in client.chat.completions.calls]
        self.assertEqual(models[:3], ["openai/gpt-oss-120b"] * 3)
        self.assertEqual(models[3], "openai/gpt-oss-20b")
        self.assertIn("contingência", result.answer)

    def test_authentication_error_is_actionable_and_has_no_fallback(self):
        client = FakeClient([FakeAPIError(401)])
        assistant = ai.GroqDashboardAssistant(
            ai.AssistantConfig(api_key="test", global_daily_request_limit=100_000),
            client=client,
        )

        with self.assertRaisesRegex(ai.AssistantError, "chave GROQ_API_KEY foi recusada"):
            assistant.answer("Teste", history=[], page_context={}, tool_executor=lambda *_: {})
        self.assertEqual(len(client.chat.completions.calls), 1)

    def test_length_limited_answer_is_continued_and_joined(self):
        client = FakeClient(
            [
                fake_response(content="Primeira parte incompleta:", finish_reason="length"),
                fake_response(content="continuação e conclusão.", finish_reason="stop"),
            ]
        )
        assistant = ai.GroqDashboardAssistant(
            ai.AssistantConfig(api_key="test", global_daily_request_limit=100_000),
            client=client,
        )

        result = assistant.answer("Faça um cálculo futuro", history=[], page_context={}, tool_executor=lambda *_: {})

        self.assertEqual(result.answer, "Primeira parte incompleta:\n\ncontinuação e conclusão.")
        self.assertEqual(len(client.chat.completions.calls), 2)
        continuation_messages = client.chat.completions.calls[1]["messages"]
        self.assertTrue(
            any(
                "Continue exatamente de onde parou" in message.get("content", "")
                for message in continuation_messages
                if message.get("role") == "user"
            )
        )

    def test_tools_never_expose_sql_or_code_execution(self):
        names = {tool["function"]["name"] for tool in ai.TOOL_SCHEMAS}
        self.assertNotIn("execute_sql", names)
        self.assertNotIn("execute_python", names)
        self.assertIn("get_dashboard_metrics", names)
        self.assertIn("get_site_wide_overview", names)
        self.assertEqual(ai.normalize_page("ranking"), "frota")
        self.assertIn("até 250 palavras", ai.SYSTEM_PROMPT)
        self.assertIn("no máximo cinco tópicos", ai.SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
