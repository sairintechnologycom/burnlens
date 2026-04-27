"""Tests for burnlens.patch — SDK monkey-patching."""
from __future__ import annotations

import os
from unittest import mock

import pytest


class TestPatchGoogle:
    """Tests for patch_google()."""

    def test_configures_correct_endpoint(self):
        """patch_google() should call genai.configure with the proxy endpoint."""
        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
            fake_genai = mock.MagicMock()
            with mock.patch.dict("sys.modules", {"google.generativeai": fake_genai}):
                # Re-import to pick up the mocked module
                import importlib
                import burnlens.patch
                importlib.reload(burnlens.patch)

                burnlens.patch.patch_google()

                fake_genai.configure.assert_called_once_with(
                    api_key="test-key",
                    client_options={"api_endpoint": "http://127.0.0.1:8420/proxy/google"},
                    transport="rest",
                )

    def test_respects_burnlens_proxy_env_var(self):
        """patch_google() should use BURNLENS_PROXY when set."""
        env = {"GOOGLE_API_KEY": "k", "BURNLENS_PROXY": "http://10.0.0.1:9999"}
        with mock.patch.dict(os.environ, env):
            fake_genai = mock.MagicMock()
            with mock.patch.dict("sys.modules", {"google.generativeai": fake_genai}):
                import importlib
                import burnlens.patch
                importlib.reload(burnlens.patch)

                burnlens.patch.patch_google()

                call_kwargs = fake_genai.configure.call_args[1]
                assert call_kwargs["client_options"]["api_endpoint"] == "http://10.0.0.1:9999/proxy/google"

    def test_accepts_explicit_proxy_arg(self):
        """An explicit proxy= argument takes precedence over env var."""
        env = {"GOOGLE_API_KEY": "k", "BURNLENS_PROXY": "http://ignored:1234"}
        with mock.patch.dict(os.environ, env):
            fake_genai = mock.MagicMock()
            with mock.patch.dict("sys.modules", {"google.generativeai": fake_genai}):
                import importlib
                import burnlens.patch
                importlib.reload(burnlens.patch)

                burnlens.patch.patch_google(proxy="http://custom:5555")

                call_kwargs = fake_genai.configure.call_args[1]
                assert call_kwargs["client_options"]["api_endpoint"] == "http://custom:5555/proxy/google"


class TestPatchAll:
    """Tests for patch_all()."""

    def test_runs_without_error(self):
        """patch_all() should not raise even if google-generativeai is missing."""
        with mock.patch("burnlens.patch.patch_google", side_effect=ImportError):
            from burnlens.patch import patch_all
            # Should not raise
            patch_all()

    def test_calls_patch_google(self):
        """patch_all() delegates to patch_google()."""
        with mock.patch("burnlens.patch.patch_google") as m:
            from burnlens.patch import patch_all
            patch_all(proxy="http://x:1")
            m.assert_called_once_with(proxy="http://x:1")
