from orchestrated_loop.gate_secret_sweep import secret_sweep_violation


def test_harmless_inputs_return_none():
    assert secret_sweep_violation({"command": "echo hello"}) is None
    assert secret_sweep_violation({"command": "git status"}) is None
    assert (
        secret_sweep_violation(
            {"file_path": "src/app.py", "content": "print(1)"}
        )
        is None
    )


def test_detects_anthropic_api_key():
    reason = secret_sweep_violation(
        {"content": "sk-ant-abcdefghijklmnopqrstuvwxyz"}
    )

    assert reason == "anthropic api key"


def test_detects_openai_style_api_key():
    reason = secret_sweep_violation(
        {"content": "sk-abcdefghijklmnopqrstuvwxyz123456"}
    )

    assert reason == "openai-style api key"


def test_openai_style_api_key_does_not_catch_anthropic_key():
    reason = secret_sweep_violation(
        {"content": "sk-ant-abcdefghijklmnopqrstuvwxyz"}
    )

    assert reason != "openai-style api key"


def test_detects_github_token():
    reason = secret_sweep_violation(
        {"content": "ghp_abcdefghijklmnopqrstuvwxyz"}
    )

    assert reason == "github token"


def test_detects_aws_access_key_id():
    reason = secret_sweep_violation({"content": "AKIAABCDEFGHIJKLMNOP"})

    assert reason == "aws access key id"


def test_detects_private_key_block():
    reason = secret_sweep_violation(
        {
            "content": (
                "-----BEGIN RSA PRIVATE KEY-----\n"
                "abc123\n"
                "-----END RSA PRIVATE KEY-----"
            )
        }
    )

    assert reason == "private key block"


def test_detects_secret_assignment():
    reason = secret_sweep_violation({"content": "TOKEN=abcdefghijkl"})

    assert reason == "secret assignment"


def test_detects_secret_in_nested_structure():
    reason = secret_sweep_violation(
        {"messages": [{"meta": {"content": "PASSWORD=abcdefghijkl"}}]}
    )

    assert reason == "secret assignment"


def test_non_string_values_are_ignored():
    assert secret_sweep_violation({"x": 5, "y": None, "z": True}) is None
