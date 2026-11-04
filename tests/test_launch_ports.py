"""
Project: 3D Printing Model Prompt
File: /home/user/3d-printing-model-prompt/tests/test_launch_ports.py
Description: launch.py must never publish a port wider than the host allows: it keeps the host's
    docker-compose.override.yml, a pinned "127.0.0.1:<port>" stays as-is, and a taken default moves to the
    next free port. It also checks bundled vs host Ollama mode detection.
Inputs: none (temporary compose/.env files in a temp dir).
Outputs: pytest results.
Troubleshooting:
    - A failure in the compose test means docker-compose.yml went back to a
      literal "8000:8000" / "11434:11434"; use the ${*_HOST_PORT} form.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import launch  # noqa: E402


class LaunchPortSafetyTests(unittest.TestCase):
    """Port pinning, override file and free-port probing."""

    def setUp(self) -> None:
        """Point launch.py at a temp compose file and registry."""
        self.tmp = Path(tempfile.mkdtemp(prefix="launch-ports-"))
        self.compose = self.tmp / launch.COMPOSE_FILE.name
        self.compose.write_text("services: {}\n", encoding="utf-8")
        self._orig = (launch.COMPOSE_FILE, launch.REGISTRY_PATH)
        launch.COMPOSE_FILE = self.compose
        launch.REGISTRY_PATH = self.tmp / "ports.json"
        self.service = launch.APP
        self.var = "APP_HOST_PORT"
        self._env = patch.dict(os.environ, {}, clear=False)
        self._env.start()
        for name in ("APP_HOST_PORT", "OLLAMA_HOST_PORT", "OLLAMA_HOST", "LLM_PROVIDER"):
            os.environ.pop(name, None)

    def tearDown(self) -> None:
        """Restore launch.py's paths and the environment."""
        self._env.stop()
        launch.COMPOSE_FILE, launch.REGISTRY_PATH = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_override_file_is_passed_when_present(self) -> None:
        """The host's override file is added back when it exists."""
        self.assertEqual(launch._compose_files(), ["-f", str(self.compose)])
        override = self.tmp / "docker-compose.override.yml"
        override.write_text("services: {}\n", encoding="utf-8")
        self.assertEqual(launch._compose_files(), ["-f", str(self.compose), "-f", str(override)])

    def test_env_file_host_ip_pin_is_kept(self) -> None:
        """A pin with a host IP in .env is used as-is."""
        (self.tmp / ".env").write_text(f"{self.var}=127.0.0.1:47123\n", encoding="utf-8")
        self.assertEqual(launch._pinned_host_port(self.service), "127.0.0.1:47123")
        self.assertEqual(launch.resolve_port(self.service, {}), 47123)

    def test_environment_pin_beats_env_file(self) -> None:
        """The process environment wins over .env."""
        (self.tmp / ".env").write_text(f"{self.var}=127.0.0.1:47123\n", encoding="utf-8")
        os.environ[self.var] = "192.0.2.10:47124"
        self.assertEqual(launch._pinned_host_port(self.service), "192.0.2.10:47124")

    def test_unpinned_still_probes(self) -> None:
        """With no pin, a port is probed."""
        self.assertIsNone(launch._pinned_host_port(self.service))
        self.assertIsInstance(launch.resolve_port(self.service, {}), int)

    def test_a_taken_default_moves_to_the_next_free_port(self) -> None:
        """A busy default port moves to the next free one."""
        taken = self.service["default_port"]
        with patch.object(launch, "_is_port_free", side_effect=lambda port, host="127.0.0.1": port != taken):
            self.assertEqual(launch.resolve_port(self.service, {}), taken + 1)

    def test_compose_publishes_through_the_env_vars(self) -> None:
        """docker-compose.yml reads both host ports from the env vars."""
        compose = Path(__file__).resolve().parents[1].joinpath("docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn('"${APP_HOST_PORT:-8000}:8000"', compose)
        self.assertIn('"${OLLAMA_HOST_PORT:-11434}:11434"', compose)
        self.assertNotIn('"8000:8000"', compose)
        self.assertNotIn('"11434:11434"', compose)
        self.assertEqual(launch._env_var_name(launch.OLLAMA["key"]), "OLLAMA_HOST_PORT")

    def test_bundled_mode_by_default(self) -> None:
        """No OLLAMA_HOST and no Claude provider: bundled stack, both services."""
        self.assertFalse(launch.host_ollama_mode())
        self.assertEqual(launch.services_for(False), [launch.APP, launch.OLLAMA])

    def test_bundled_service_url_is_still_bundled(self) -> None:
        """OLLAMA_HOST pointing at the compose service keeps bundled mode."""
        (self.tmp / ".env").write_text("OLLAMA_HOST=http://ollama:11434\n", encoding="utf-8")
        self.assertFalse(launch.host_ollama_mode())

    def test_host_ollama_from_env_file(self) -> None:
        """OLLAMA_HOST elsewhere means host mode: the app only."""
        (self.tmp / ".env").write_text("OLLAMA_HOST=http://host.docker.internal:11434\n", encoding="utf-8")
        self.assertTrue(launch.host_ollama_mode())
        self.assertEqual(launch.services_for(True), [launch.APP])

    def test_claude_provider_skips_ollama(self) -> None:
        """LLM_PROVIDER=claude needs no Ollama."""
        os.environ["LLM_PROVIDER"] = "Claude"
        self.assertTrue(launch.host_ollama_mode())

    def test_flags_override_detection(self) -> None:
        """--bundled-ollama and --host-ollama beat what .env says."""
        os.environ["LLM_PROVIDER"] = "claude"
        self.assertFalse(launch.host_ollama_mode(force_bundled=True))
        os.environ.pop("LLM_PROVIDER")
        self.assertTrue(launch.host_ollama_mode(force_host=True))


if __name__ == "__main__":
    unittest.main()
