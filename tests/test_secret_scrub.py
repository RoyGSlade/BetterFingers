"""Credential scrubbing helpers (Phase 0 items 4, 9, 10)."""
import re

from backend.privacy.secret_scrub import (
    CHILD_ENV_ALLOWLIST,
    REDACTED,
    redact_args,
    redact_secrets,
    scrubbed_child_env,
)

TOKEN = "a1b2c3d4" * 8  # 64 hex chars, the shape of this app's own token


def test_child_env_keeps_only_allowlisted_names():
    base = {
        "PATH": "/usr/bin", "HOME": "/home/u", "LANG": "en_US.UTF-8", "LC_ALL": "C",
        "BETTERFINGERS_AUTH_TOKEN": TOKEN, "BETTERFINGERS_APPROVAL_KEY": "k" * 64,
        "ANTHROPIC_API_KEY": "sk-ant-abcdefghijkl", "OPENAI_API_KEY": "sk-" + "x" * 30,
        "GITHUB_TOKEN": "ghp_" + "y" * 30, "AWS_SECRET_ACCESS_KEY": "zzz",
        "LLAMA_ARG_HOST": "0.0.0.0", "MY_PASSWORD": "hunter2",
    }
    env = scrubbed_child_env(base)
    assert env == {"PATH": "/usr/bin", "HOME": "/home/u", "LANG": "en_US.UTF-8", "LC_ALL": "C"}


def test_child_env_allowlist_is_case_insensitive_for_windows_names():
    env = scrubbed_child_env({"Path": "C:\\Windows", "SystemRoot": "C:\\Windows", "Temp": "C:\\t", "Secret": "x"})
    assert set(env) == {"Path", "SystemRoot", "Temp"}


def test_child_env_applies_explicit_extra_but_never_the_apps_own_credentials():
    env = scrubbed_child_env(
        {"PATH": "/bin"},
        {"MY_SERVER_KEY": "wanted", "BETTERFINGERS_AUTH_TOKEN": TOKEN, "betterfingers_approval_key": "k"},
    )
    assert env["MY_SERVER_KEY"] == "wanted"
    assert not any(name.upper().startswith("BETTERFINGERS_") for name in env)


def test_child_env_drop_prefixes_removes_even_explicit_values():
    env = scrubbed_child_env({"PATH": "/bin"}, {"LLAMA_ARG_HOST": "0.0.0.0", "LLAMA_CACHE": "/c"},
                             drop_prefixes=("LLAMA_ARG_",))
    assert "LLAMA_ARG_HOST" not in env
    assert env["LLAMA_CACHE"] == "/c"


def test_allowlist_contains_no_credential_looking_names():
    for name in CHILD_ENV_ALLOWLIST:
        assert not re.search(r"TOKEN|KEY|SECRET|PASSWORD", name), name


def test_redact_bearer_and_authorization_headers():
    for text in (f"Authorization: Bearer {TOKEN}", f"authorization=Bearer {TOKEN}", f"Bearer {TOKEN}"):
        out = redact_secrets(text)
        assert TOKEN not in out, text
        assert REDACTED in out


def test_redact_query_string_tokens():
    line = f'INFO: 127.0.0.1:5000 - "GET /ws/voice_status?token={TOKEN}&x=1 HTTP/1.1" 101'
    out = redact_secrets(line)
    assert TOKEN not in out
    assert "x=1" in out and "HTTP/1.1" in out
    assert "access_token=abcdef123456" not in redact_secrets("GET /a?access_token=abcdef123456")
    assert "api_key=sk" not in redact_secrets("POST /x?api_key=skabc123")


def test_redact_auth_frame_and_env_assignment_and_key_shapes():
    assert TOKEN not in redact_secrets(f"auth:{TOKEN}")
    assert TOKEN not in redact_secrets(f"BETTERFINGERS_AUTH_TOKEN={TOKEN}")
    assert "sk-ant-abcdefgh12345" not in redact_secrets("key sk-ant-abcdefgh12345 leaked")
    assert TOKEN not in redact_secrets(f"the token was {TOKEN} ok")
    assert "ghp_" + "y" * 30 not in redact_secrets("ghp_" + "y" * 30)


def test_redaction_leaves_ordinary_log_text_alone():
    for text in (
        "Loaded model base.en in 1.2s", "token_count=5", "max_token_limit=1100", "author=bob",
        "GET /runtime/status 200", "preset=True Janitor",
    ):
        assert redact_secrets(text) == text


def test_redaction_is_idempotent_and_tolerates_none():
    once = redact_secrets(f"Bearer {TOKEN}")
    assert redact_secrets(once) == once
    assert redact_secrets(None) == ""


def test_redact_args_masks_secret_flags_and_values():
    args = ["srv.py", "--api-key", "supersecretvalue", "--token=abc12345", "--port", "8", f"{TOKEN}", "API_KEY=zzzz1234"]
    out = redact_args(args)
    assert out[:2] == ["srv.py", "--api-key"]
    assert out[2] == REDACTED
    assert out[3] == f"--token={REDACTED}"
    assert out[4:6] == ["--port", "8"]
    assert out[6] == REDACTED
    assert "zzzz1234" not in out[7]
