import json
import os
import subprocess
import unittest
from unittest import mock

from bert_excitation_train.scripts.novel_generation_v2.qwen_transport import (
    call_openai_compatible_via_curl,
    call_qwen_via_curl,
    list_openai_compatible_models_via_curl,
)


class QwenTransportTests(unittest.TestCase):
    def test_openai_compatible_models_endpoint_returns_ids(self):
        def fake_run(command, **kwargs):
            output_path = command[command.index("--output") + 1]
            with open(output_path, "w", encoding="utf-8") as handle:
                json.dump({"data": [{"id": "model-a"}, {"id": "model-b"}]}, handle)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with mock.patch(
            "bert_excitation_train.scripts.novel_generation_v2.qwen_transport.subprocess.run", side_effect=fake_run,
        ):
            models = list_openai_compatible_models_via_curl(
                api_key="test-key", endpoint="https://example.test/v1/models",
            )
        self.assertEqual(models, ["model-a", "model-b"])

    def test_openai_compatible_transport_uses_chat_completion_shape(self):
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = list(command)
            request_path = command[command.index("--data-binary") + 1][1:]
            output_path = command[command.index("--output") + 1]
            with open(request_path, encoding="utf-8") as handle:
                captured["payload"] = json.load(handle)
            with open(output_path, "w", encoding="utf-8") as handle:
                json.dump({"choices": [{"message": {"content": "好"}}]}, handle)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with mock.patch(
            "bert_excitation_train.scripts.novel_generation_v2.qwen_transport.subprocess.run",
            side_effect=fake_run,
        ):
            response = call_openai_compatible_via_curl(
                [{"role": "user", "content": "test"}], api_key="test-key",
                model="llama-test", endpoint="https://example.test/v1/chat/completions",
                max_tokens=123,
            )
        self.assertEqual(captured["payload"]["model"], "llama-test")
        self.assertEqual(captured["payload"]["max_completion_tokens"], 123)
        self.assertEqual(response["choices"][0]["message"]["content"], "好")

    def test_gpt_oss_transport_uses_low_reasoning_effort_for_json_capacity(self):
        captured = {}

        def fake_run(command, **kwargs):
            request_path = command[command.index("--data-binary") + 1][1:]
            output_path = command[command.index("--output") + 1]
            with open(request_path, encoding="utf-8") as handle:
                captured["payload"] = json.load(handle)
            with open(output_path, "w", encoding="utf-8") as handle:
                json.dump({"choices": [{"message": {"content": "{}"}}]}, handle)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with mock.patch(
            "bert_excitation_train.scripts.novel_generation_v2.qwen_transport.subprocess.run",
            side_effect=fake_run,
        ):
            call_openai_compatible_via_curl(
                [{"role": "user", "content": "test"}], api_key="test-key",
                model="openai/gpt-oss-20b",
                endpoint="https://example.test/v1/chat/completions",
            )
        self.assertEqual(captured["payload"]["reasoning_effort"], "low")

    def test_qwen3_transport_disables_reasoning_for_json_capacity(self):
        captured = {}

        def fake_run(command, **kwargs):
            request_path = command[command.index("--data-binary") + 1][1:]
            output_path = command[command.index("--output") + 1]
            with open(request_path, encoding="utf-8") as handle:
                captured["payload"] = json.load(handle)
            with open(output_path, "w", encoding="utf-8") as handle:
                json.dump({"choices": [{"message": {"content": "{}"}}]}, handle)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with mock.patch(
            "bert_excitation_train.scripts.novel_generation_v2.qwen_transport.subprocess.run",
            side_effect=fake_run,
        ):
            call_openai_compatible_via_curl(
                [{"role": "user", "content": "test"}], api_key="test-key",
                model="qwen/qwen3.6-27b",
                endpoint="https://example.test/v1/chat/completions",
            )
        self.assertEqual(captured["payload"]["reasoning_effort"], "none")
        self.assertEqual(captured["payload"]["response_format"], {"type": "json_object"})
        self.assertNotIn("enable_thinking", captured["payload"])

    def test_llama_transport_enables_json_object_mode(self):
        captured = {}

        def fake_run(command, **kwargs):
            request_path = command[command.index("--data-binary") + 1][1:]
            output_path = command[command.index("--output") + 1]
            with open(request_path, encoding="utf-8") as handle:
                captured["payload"] = json.load(handle)
            with open(output_path, "w", encoding="utf-8") as handle:
                json.dump({"choices": [{"message": {"content": "{}"}}]}, handle)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with mock.patch(
            "bert_excitation_train.scripts.novel_generation_v2.qwen_transport.subprocess.run",
            side_effect=fake_run,
        ):
            call_openai_compatible_via_curl(
                [{"role": "user", "content": "return JSON"}], api_key="test-key",
                model="llama-3.3-70b-versatile",
                endpoint="https://example.test/v1/chat/completions",
            )
        self.assertEqual(captured["payload"]["response_format"], {"type": "json_object"})

    def test_openai_compatible_proxy_is_forwarded_to_chat_and_models(self):
        captured = []

        def fake_run(command, **kwargs):
            captured.append(list(command))
            output_path = command[command.index("--output") + 1]
            payload = (
                {"data": []}
                if command[command.index("--request") + 1] == "GET"
                else {"choices": []}
            )
            with open(output_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with mock.patch.dict(
            os.environ,
            {"OPENAI_COMPATIBLE_CURL_PROXY": "http://127.0.0.1:7897"},
            clear=False,
        ), mock.patch(
            "bert_excitation_train.scripts.novel_generation_v2.qwen_transport.subprocess.run",
            side_effect=fake_run,
        ):
            call_openai_compatible_via_curl(
                [{"role": "user", "content": "test"}], api_key="test-key",
                model="model-a", endpoint="https://example.test/v1/chat/completions",
            )
            list_openai_compatible_models_via_curl(
                api_key="test-key", endpoint="https://example.test/v1/models",
            )

        self.assertEqual(len(captured), 2)
        for command in captured:
            self.assertEqual(
                command[command.index("--proxy") + 1], "http://127.0.0.1:7897",
            )

    def test_optional_network_route_arguments_are_forwarded_to_curl(self):
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = list(command)
            output_path = command[command.index("--output") + 1]
            with open(output_path, "w", encoding="utf-8") as handle:
                json.dump({"output": {"choices": [{"message": {"content": "好"}}]}}, handle)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        env = {
            "DASHSCOPE_CURL_INTERFACE": "192.0.2.10",
            "DASHSCOPE_CURL_RESOLVE": "dashscope.example:443:192.0.2.20",
            "DASHSCOPE_CURL_PROXY": "socks5://127.0.0.1:1080",
            "DASHSCOPE_HTTP_ENDPOINT": "https://dashscope.example/generation",
        }
        with mock.patch.dict(os.environ, env, clear=False), mock.patch(
            "bert_excitation_train.scripts.novel_generation_v2.qwen_transport.subprocess.run",
            side_effect=fake_run,
        ):
            response = call_qwen_via_curl(
                [{"role": "user", "content": "test"}],
                api_key="test-key",
                max_tokens=2,
            )

        command = captured["command"]
        self.assertEqual(command[command.index("--interface") + 1], "192.0.2.10")
        self.assertEqual(
            command[command.index("--resolve") + 1],
            "dashscope.example:443:192.0.2.20",
        )
        self.assertEqual(
            command[command.index("--proxy") + 1],
            "socks5://127.0.0.1:1080",
        )
        self.assertEqual(
            command[command.index("--request") + 2],
            "https://dashscope.example/generation",
        )
        self.assertEqual(response["output"]["choices"][0]["message"]["content"], "好")

    def test_optional_network_route_arguments_are_absent_by_default(self):
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = list(command)
            output_path = command[command.index("--output") + 1]
            with open(output_path, "w", encoding="utf-8") as handle:
                json.dump({"output": {"choices": []}}, handle)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        cleared = {
            "DASHSCOPE_CURL_INTERFACE": "",
            "DASHSCOPE_CURL_RESOLVE": "",
            "DASHSCOPE_CURL_PROXY": "",
        }
        with mock.patch.dict(os.environ, cleared, clear=False), mock.patch(
            "bert_excitation_train.scripts.novel_generation_v2.qwen_transport.subprocess.run",
            side_effect=fake_run,
        ):
            call_qwen_via_curl([{"role": "user", "content": "test"}], api_key="test-key")

        command = captured["command"]
        self.assertNotIn("--interface", command)
        self.assertNotIn("--resolve", command)
        self.assertNotIn("--proxy", command)


if __name__ == "__main__":
    unittest.main()
