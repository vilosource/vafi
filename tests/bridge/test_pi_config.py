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
    def test_writes_settings_json(self, tmp_path):
        with patch.dict(os.environ, {}, clear=False):
            with patch("pi_config.Path.home", return_value=tmp_path):
                pi_config.main()
        settings = json.loads((tmp_path / ".pi" / "agent" / "settings.json").read_text())
        assert settings == {"packages": []}

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
