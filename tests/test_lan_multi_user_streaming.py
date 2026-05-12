"""Tests for LAN multi-user streaming: skills dir resolution, env lock scope, MCP discovery placement.

These are runtime-focused tests verifying:
  1. _resolve_skills_dir() returns the shared skills dir in multi-user mode.
  2. _resolve_skills_dir() returns profile_home / "skills" in legacy mode.
  3. SKILLS_DIR patching inside _ENV_LOCK uses _resolve_skills_dir().
  4. MCP discovery runs inside the _ENV_LOCK window (source-level proof).
  5. _ENV_LOCK is NOT held during the agent run (source-level proof).
"""

import inspect
import os
import threading
from pathlib import Path
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# 1. _resolve_skills_dir — multi-user mode returns shared dir
# ---------------------------------------------------------------------------

class TestResolveSkillsDirMultiUser:
    """When is_multi_user_mode() is True, _resolve_skills_dir returns the
    shared skills directory."""

    def test_returns_shared_skills_dir_in_multi_user_mode(self, tmp_path):
        """is_multi_user_mode() == True => returns get_shared_skills_dir()."""
        shared = tmp_path / "shared_skills"
        shared.mkdir()

        with mock.patch("api.users.is_multi_user_mode", return_value=True), \
             mock.patch("api.users.get_shared_skills_dir", return_value=shared):
            from api.streaming import _resolve_skills_dir
            result = _resolve_skills_dir(str(tmp_path / "profile"))

        assert result.resolve() == shared.resolve()

    def test_shared_dir_called_from_multi_user(self, tmp_path):
        """Verify the helper actually calls get_shared_skills_dir in multi-user mode."""
        shared = tmp_path / "enterprise_skills"
        shared.mkdir()

        with mock.patch("api.users.is_multi_user_mode", return_value=True), \
             mock.patch("api.users.get_shared_skills_dir", return_value=shared) as mock_gssd:
            from api.streaming import _resolve_skills_dir
            _resolve_skills_dir(str(tmp_path / "some_profile"))

        mock_gssd.assert_called_once()


# ---------------------------------------------------------------------------
# 2. _resolve_skills_dir — legacy/single-user mode returns profile_home/skills
# ---------------------------------------------------------------------------

class TestResolveSkillsDirLegacy:
    """When is_multi_user_mode() is False (or fails), _resolve_skills_dir
    returns profile_home / 'skills'."""

    def test_returns_profile_skills_in_legacy_mode(self, tmp_path):
        profile_home = str(tmp_path / "my_profile")
        expected = Path(profile_home) / "skills"

        with mock.patch("api.users.is_multi_user_mode", return_value=False):
            from api.streaming import _resolve_skills_dir
            result = _resolve_skills_dir(profile_home)

        assert result == expected

    def test_returns_profile_skills_when_import_fails(self, tmp_path):
        """If api.users is unavailable, fall back to profile_home / 'skills'."""
        profile_home = str(tmp_path / "fallback_profile")
        expected = Path(profile_home) / "skills"

        with mock.patch("api.users.is_multi_user_mode", side_effect=ImportError("no module")):
            from api.streaming import _resolve_skills_dir
            result = _resolve_skills_dir(profile_home)

        assert result == expected

    def test_returns_profile_skills_when_users_check_raises(self, tmp_path):
        """If is_multi_user_mode() raises, fall back to profile_home / 'skills'."""
        profile_home = str(tmp_path / "error_profile")
        expected = Path(profile_home) / "skills"

        with mock.patch("api.users.is_multi_user_mode", side_effect=RuntimeError("db locked")):
            from api.streaming import _resolve_skills_dir
            result = _resolve_skills_dir(profile_home)

        assert result == expected


# ---------------------------------------------------------------------------
# 3. Skills tool SKILLS_DIR patching uses _resolve_skills_dir()
# ---------------------------------------------------------------------------

class TestSkillsPatchingUsesResolveSkillsDir:
    """Verify that the env-lock section in _run_agent_streaming patches
    SKILLS_DIR with the value from _resolve_skills_dir, not a hardcoded
    profile / 'skills'."""

    def test_source_uses_resolve_skills_dir_not_hardcoded(self):
        """Read the source of _run_agent_streaming and verify the patching
        calls _resolve_skills_dir() instead of hardcoding `_ph / 'skills'`."""
        source = inspect.getsource(
            __import__("api.streaming", fromlist=["_run_agent_streaming"])
            ._run_agent_streaming
        )
        # The source must call _resolve_skills_dir
        assert "_resolve_skills_dir" in source, (
            "Expected _run_agent_streaming to call _resolve_skills_dir()"
        )
        # And the old hardcoded _ph / 'skills' must NOT be used for SKILLS_DIR assignment
        # (it's fine if _ph is used for HERMES_HOME, but SKILLS_DIR should use _skills_dir)
        # Check that the SKILLS_DIR lines reference _skills_dir
        lines = source.split("\n")
        for line in lines:
            stripped = line.strip()
            if "SKILLS_DIR" in stripped and "=" in stripped and "old" not in stripped:
                # This is a SKILLS_DIR assignment line
                assert "_skills_dir" in stripped or "SKILLS_DIR" not in stripped or "old" in stripped, (
                    f"SKILLS_DIR assignment should use _skills_dir, got: {stripped}"
                )


# ---------------------------------------------------------------------------
# 4. MCP discovery runs INSIDE _ENV_LOCK window
# ---------------------------------------------------------------------------

class TestMCPDiscoveryInsideEnvLock:
    """Verify that discover_mcp_tools() is called inside the _ENV_LOCK
    block, not after it."""

    def test_mcp_discovery_inside_lock_window(self):
        """Source-level proof: discover_mcp_tools() must appear between
        'with _ENV_LOCK:' and 'Lock released'."""
        source = inspect.getsource(
            __import__("api.streaming", fromlist=["_run_agent_streaming"])
            ._run_agent_streaming
        )

        # Find the with _ENV_LOCK block
        lines = source.split("\n")
        in_lock = False
        found_mcp_in_lock = False
        found_lock_released = False

        for line in lines:
            stripped = line.strip()
            if "with _ENV_LOCK:" in stripped:
                in_lock = True
                continue
            if in_lock:
                if "Lock released" in stripped:
                    # MCP must have been found before this
                    found_lock_released = True
                    break
                if "discover_mcp_tools" in stripped:
                    found_mcp_in_lock = True

        assert found_mcp_in_lock, (
            "discover_mcp_tools() must be called inside the _ENV_LOCK block"
        )
        assert found_lock_released, (
            "Test structure error: 'Lock released' comment not found"
        )


# ---------------------------------------------------------------------------
# 5. _ENV_LOCK is NOT held during the agent run
# ---------------------------------------------------------------------------

class TestEnvLockNotHeldDuringAgentRun:
    """Verify the _ENV_LOCK is released before agent.run_conversation() is
    called.  This is critical for multi-user concurrency — if the lock
    were held for the entire agent run, only one user could run at a time."""

    def test_lock_released_before_agent_run(self):
        """Source-level proof: 'Lock released' comment appears before
        run_conversation."""
        source = inspect.getsource(
            __import__("api.streaming", fromlist=["_run_agent_streaming"])
            ._run_agent_streaming
        )

        lines = source.split("\n")
        lock_released_line = None
        run_conversation_line = None

        for i, line in enumerate(lines):
            stripped = line.strip()
            if "Lock released" in stripped and lock_released_line is None:
                lock_released_line = i
            if "run_conversation" in stripped and run_conversation_line is None:
                run_conversation_line = i

        assert lock_released_line is not None, "Lock released comment not found"
        assert run_conversation_line is not None, "run_conversation not found"
        assert lock_released_line < run_conversation_line, (
            f"_ENV_LOCK must be released before run_conversation. "
            f"Lock released at line {lock_released_line}, "
            f"run_conversation at line {run_conversation_line}"
        )


# ---------------------------------------------------------------------------
# 6. _resolve_skills_dir uses real shared skills dir from api.users
# ---------------------------------------------------------------------------

class TestResolveSkillsDirIntegration:
    """Integration test: _resolve_skills_dir imports from api.users and
    returns the actual shared skills dir path."""

    def test_multi_user_returns_state_dir_shared_skills(self, tmp_path):
        """When HERMES_SHARED_SKILLS_DIR is unset, shared skills default to
        STATE_DIR / 'shared_skills'. _resolve_skills_dir should return that."""
        fake_state_dir = tmp_path / "state"
        expected_shared = (fake_state_dir / "shared_skills").resolve()

        with mock.patch("api.users.STATE_DIR", fake_state_dir), \
             mock.patch("api.users.is_multi_user_mode", return_value=True):
            from api.streaming import _resolve_skills_dir
            result = _resolve_skills_dir(str(tmp_path / "profile"))

        assert result == expected_shared

    def test_legacy_returns_profile_skills(self, tmp_path):
        """In legacy mode, result is always profile_home / 'skills'."""
        ph = str(tmp_path / "alice")
        with mock.patch("api.users.is_multi_user_mode", return_value=False):
            from api.streaming import _resolve_skills_dir
            result = _resolve_skills_dir(ph)
        assert result == Path(ph) / "skills"


# ---------------------------------------------------------------------------
# 7. Source-level: _resolve_skills_dir is a helper defined in streaming.py
# ---------------------------------------------------------------------------

class TestResolveSkillsDirDefined:
    """_resolve_skills_dir must be importable from api.streaming."""

    def test_importable(self):
        from api.streaming import _resolve_skills_dir
        assert callable(_resolve_skills_dir)

    def test_signature(self):
        from api.streaming import _resolve_skills_dir
        sig = inspect.signature(_resolve_skills_dir)
        params = list(sig.parameters.keys())
        assert "profile_home" in params, (
            f"_resolve_skills_dir should accept profile_home, got: {params}"
        )
