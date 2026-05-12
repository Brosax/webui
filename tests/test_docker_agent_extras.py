from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
INIT_SCRIPT = (REPO / "docker_init.bash").read_text(encoding="utf-8")
ENV_EXAMPLE = (REPO / ".env.docker.example").read_text(encoding="utf-8")
DOCKER_DOCS = (REPO / "docs" / "docker.md").read_text(encoding="utf-8")
README = (REPO / "README.md").read_text(encoding="utf-8")


def test_docker_init_does_not_default_to_agent_all_extra():
    """Docker startup should not let one optional provider dependency block boot."""
    assert 'uv pip install "$_agent_src[all]"' not in INIT_SCRIPT
    assert "HERMES_WEBUI_AGENT_EXTRAS" in INIT_SCRIPT
    assert "-- Installing hermes-agent base dependencies only" in INIT_SCRIPT


def test_docker_agent_extras_are_documented():
    for src in (ENV_EXAMPLE, DOCKER_DOCS, README):
        assert "HERMES_WEBUI_AGENT_EXTRAS" in src
