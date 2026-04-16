"""Tests for pi_config.py — Pi agent config file writer."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "images" / "agent"))
import pi_config


class TestPiConfig:
    def test_writes_settings_json_with_mcp_adapter(self, tmp_path):
        with patch.dict(os.environ, {}, clear=False):
            with patch("pi_config.Path.home", return_value=tmp_path):
                pi_config.main()
        settings = json.loads((tmp_path / ".pi" / "agent" / "settings.json").read_text())
        assert "npm:pi-mcp-adapter" in settings["packages"]

    def test_preserves_existing_packages(self, tmp_path):
        """Don't overwrite packages already registered (e.g. by `pi install` at image build)."""
        settings_path = tmp_path / ".pi" / "agent" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(json.dumps({"packages": ["npm:pi-mcp-adapter", "npm:other"]}))
        with patch.dict(os.environ, {}, clear=False):
            with patch("pi_config.Path.home", return_value=tmp_path):
                pi_config.main()
        settings = json.loads(settings_path.read_text())
        assert "npm:pi-mcp-adapter" in settings["packages"]
        assert "npm:other" in settings["packages"]

    def test_idempotent_settings(self, tmp_path):
        """Running twice doesn't duplicate pi-mcp-adapter entry."""
        with patch.dict(os.environ, {}, clear=False):
            with patch("pi_config.Path.home", return_value=tmp_path):
                pi_config.main()
                pi_config.main()
        settings = json.loads((tmp_path / ".pi" / "agent" / "settings.json").read_text())
        assert settings["packages"].count("npm:pi-mcp-adapter") == 1

    def test_writes_models_json_defaults(self, tmp_path):
        with patch.dict(os.environ, {"ANTHROPIC_BASE_URL": ""}, clear=False):
            with patch("pi_config.Path.home", return_value=tmp_path):
                pi_config.main()
        models = json.loads((tmp_path / ".pi" / "agent" / "models.json").read_text())
        assert "anthropic" in models["providers"]
        cfg = models["providers"]["anthropic"]
        assert cfg["api"] == "anthropic-messages"
        assert cfg["models"][0]["id"] == "claude-sonnet-4-20250514"
        assert "baseUrl" not in cfg

    def test_writes_models_json_with_base_url(self, tmp_path):
        with patch.dict(os.environ, {"ANTHROPIC_BASE_URL": "https://proxy.example.com"}, clear=False):
            with patch("pi_config.Path.home", return_value=tmp_path):
                pi_config.main()
        models = json.loads((tmp_path / ".pi" / "agent" / "models.json").read_text())
        assert models["providers"]["anthropic"]["baseUrl"] == "https://proxy.example.com"

    def test_writes_mcp_json_when_urls_set(self, tmp_path):
        with patch.dict(os.environ, {
            "VF_VTF_MCP_URL": "http://vtf-mcp:8002/mcp",
            "VF_CXDB_MCP_URL": "http://cxdb-mcp:8090/mcp",
        }, clear=False):
            with patch("pi_config.Path.home", return_value=tmp_path):
                pi_config.main()
        mcp = json.loads((tmp_path / ".pi" / "agent" / "mcp.json").read_text())
        assert mcp["mcpServers"]["vtf"]["url"] == "http://vtf-mcp:8002/mcp"
        assert mcp["mcpServers"]["cxdb"]["url"] == "http://cxdb-mcp:8090/mcp"

    def test_mcp_json_vtf_auth_headers(self, tmp_path):
        """vtf MCP requires Authorization: Token <key>; optionally X-VTF-Project."""
        with patch.dict(os.environ, {
            "VF_VTF_MCP_URL": "http://vtf-mcp:8002/mcp",
            "VF_VTF_TOKEN": "secret-token-abc",
            "VTF_PROJECT_SLUG": "my-project",
        }, clear=False):
            with patch("pi_config.Path.home", return_value=tmp_path):
                pi_config.main()
        mcp = json.loads((tmp_path / ".pi" / "agent" / "mcp.json").read_text())
        vtf = mcp["mcpServers"]["vtf"]
        assert vtf["headers"]["Authorization"] == "Token secret-token-abc"
        assert vtf["headers"]["X-VTF-Project"] == "my-project"

    def test_mcp_json_vtf_no_headers_without_token(self, tmp_path):
        """URL without token writes no headers (fails open — caller sees 401)."""
        with patch.dict(os.environ, {
            "VF_VTF_MCP_URL": "http://vtf-mcp:8002/mcp",
            "VF_VTF_TOKEN": "",
        }, clear=False):
            with patch("pi_config.Path.home", return_value=tmp_path):
                pi_config.main()
        mcp = json.loads((tmp_path / ".pi" / "agent" / "mcp.json").read_text())
        assert "headers" not in mcp["mcpServers"]["vtf"]

    def test_no_mcp_json_when_no_urls(self, tmp_path):
        with patch.dict(os.environ, {"VF_VTF_MCP_URL": "", "VF_CXDB_MCP_URL": ""}, clear=False):
            with patch("pi_config.Path.home", return_value=tmp_path):
                pi_config.main()
        assert not (tmp_path / ".pi" / "agent" / "mcp.json").exists()

    def test_custom_provider_and_model(self, tmp_path):
        with patch.dict(os.environ, {
            "VF_PI_PROVIDER": "custom",
            "VF_PI_MODEL": "my-model-v2",
        }, clear=False):
            with patch("pi_config.Path.home", return_value=tmp_path):
                pi_config.main()
        models = json.loads((tmp_path / ".pi" / "agent" / "models.json").read_text())
        assert "custom" in models["providers"]
        assert models["providers"]["custom"]["models"][0]["id"] == "my-model-v2"
