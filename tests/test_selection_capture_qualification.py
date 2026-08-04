from pathlib import Path

from tools.selection_capture_qualification import (
    SENTINEL_TEXT,
    build_evidence,
    collect_metadata,
    detect_environment,
    initial_checks,
    main,
    metadata_checks,
    render_markdown,
    WORKFLOW_CHECK_NAMES,
)


def _which(*available):
    available = set(available)

    def lookup(name):
        return f"/usr/bin/{name}" if name in available else None

    return lookup


def _target_checks(status="PASS", names=WORKFLOW_CHECK_NAMES):
    return [
        {"name": name, "status": status, "detail": "observed"}
        for name in names
    ]


def _complete_targets(environment):
    environment["representative_apps"] = ["Target A", "Target B"]
    return [
        {"target": target, "checks": _target_checks()}
        for target in environment["representative_apps"]
    ]


def test_detects_x11_backend_and_tools_without_desktop_side_effects():
    environment = detect_environment(
        system="Linux",
        environ={"XDG_SESSION_TYPE": "x11", "DISPLAY": ":99"},
        which=_which("xclip", "xdotool"),
    )

    assert environment["platform"] == "linux"
    assert environment["session_type"] == "x11"
    assert environment["clipboard_backend"] == {
        "name": "xclip",
        "available": True,
        "required": ["xclip"],
    }
    assert environment["typing_backend"]["name"] == "xdotool"
    assert all(check["status"] != "FAIL" for check in initial_checks(environment))


def test_detects_wayland_prerequisites_and_does_not_assume_global_hotkeys():
    environment = detect_environment(
        system="Linux",
        environ={"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"},
        which=_which("wl-copy", "wl-paste", "wtype"),
    )

    assert environment["session_type"] == "wayland"
    assert environment["clipboard_backend"]["available"] is True
    assert environment["hotkey_backend"]["available"] is False
    assert environment["hotkey_backend"]["name"] == "global-hotkey-unknown-on-wayland"
    assert environment["typing_backend"]["name"] == "wtype"


def test_wayland_typing_without_tools_has_actionable_requirement():
    environment = detect_environment(
        system="Linux",
        environ={"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"},
        which=_which("wl-copy", "wl-paste"),
    )

    assert environment["typing_backend"] == {
        "name": "none",
        "available": False,
        "required": ["wtype or ydotool"],
    }


def test_wayland_typing_without_tools_requires_display_and_actionable_tool():
    environment = detect_environment(
        system="Linux",
        environ={"XDG_SESSION_TYPE": "wayland"},
        which=_which("wl-copy", "wl-paste"),
    )

    assert environment["typing_backend"] == {
        "name": "none",
        "available": False,
        "required": ["WAYLAND_DISPLAY", "wtype or ydotool"],
    }


def test_macos_hotkey_backend_has_single_selection_support_requirement():
    environment = detect_environment(system="Darwin", environ={}, which=_which())

    assert environment["hotkey_backend"] == {
        "name": "unsupported-on-macos",
        "available": False,
        "required": ["macOS selection capture support"],
    }


def test_wayland_display_precedes_stale_x11_session_type():
    environment = detect_environment(
        system="Linux",
        environ={
            "XDG_SESSION_TYPE": "x11",
            "DISPLAY": ":99",
            "WAYLAND_DISPLAY": "wayland-0",
        },
        which=_which("wl-copy", "wl-paste", "wtype", "xclip", "xdotool"),
    )

    assert environment["session_type"] == "wayland"
    assert environment["clipboard_backend"]["name"] == "wl-clipboard"
    assert environment["hotkey_backend"]["name"] == "global-hotkey-unknown-on-wayland"


def test_missing_x11_clipboard_is_explicit_failure():
    environment = detect_environment(
        system="Linux",
        environ={"XDG_SESSION_TYPE": "x11", "DISPLAY": ":99"},
        which=_which(),
    )

    checks = initial_checks(environment)
    clipboard = next(check for check in checks if check["name"] == "clipboard backend available")
    assert clipboard["status"] == "FAIL"
    assert "xclip" in clipboard["detail"]


def test_x11_capabilities_require_display_even_when_tools_are_present():
    environment = detect_environment(
        system="Linux",
        environ={"XDG_SESSION_TYPE": "x11"},
        which=_which("xclip", "xdotool"),
    )

    assert environment["display_present"] is False
    for name in ("clipboard_backend", "copy_trigger_backend", "hotkey_backend", "typing_backend"):
        assert environment[name]["available"] is False
    assert all(
        check["status"] != "PASS"
        for check in initial_checks(environment)
        if check["name"] in {
            "clipboard backend available",
            "copy trigger backend available",
            "global hotkey path available",
            "typing/injection path available",
        }
    )
    checks = _complete_targets(environment)
    assert build_evidence(environment, checks)["overall"] == "UNTESTED"


def test_wayland_capabilities_require_wayland_display_even_when_tools_are_present():
    environment = detect_environment(
        system="Linux",
        environ={"XDG_SESSION_TYPE": "wayland"},
        which=_which("wl-copy", "wl-paste", "wtype"),
    )

    assert environment["display_present"] is False
    for name in ("clipboard_backend", "copy_trigger_backend", "typing_backend"):
        assert environment[name]["available"] is False
    assert build_evidence(environment, _complete_targets(environment))["overall"] == "UNTESTED"


def test_linux_without_any_display_cannot_authorize_complete_workflow():
    environment = detect_environment(system="Linux", environ={}, which=_which())

    assert environment["display_present"] is False
    assert build_evidence(environment, _complete_targets(environment))["overall"] == "UNTESTED"


def test_windows_uses_native_paths():
    environment = detect_environment(system="Windows", environ={}, which=_which())

    assert environment["platform"] == "windows"
    assert environment["session_type"] == "windows-desktop"
    assert environment["clipboard_backend"]["name"] == "native"
    assert environment["hotkey_backend"]["available"] is True


def test_evidence_and_markdown_are_privacy_safe():
    environment = detect_environment(system="Linux", environ={}, which=_which())
    checks = [
        {"name": "selected-text capture", "status": "PASS", "detail": "observed"},
        {"name": "rewrite opens review-only draft", "status": "PASS", "detail": "observed"},
        {"name": "clipboard is restored", "status": "PASS", "detail": "observed"},
        {"name": "no automatic send occurs", "status": "PASS", "detail": "observed"},
    ]

    evidence = build_evidence(environment, checks)
    markdown = render_markdown(evidence)

    assert evidence["overall"] == "UNTESTED"  # missing platform prerequisites block qualification
    assert evidence["sentinel"]["text_recorded"] is False
    assert evidence["privacy"]["clipboard_contents_recorded"] is False
    assert SENTINEL_TEXT not in markdown
    assert evidence["sentinel"]["sha256"] in markdown
    assert "/usr/bin" not in markdown


def test_all_observed_workflow_checks_pass_only_on_ready_native_environment():
    environment = detect_environment(system="Windows", environ={}, which=_which())
    checks = _complete_targets(environment)

    assert build_evidence(environment, checks)["overall"] == "PASS"


def test_wayland_complete_observation_can_pass_but_hotkey_capability_stays_untested():
    environment = detect_environment(
        system="Linux",
        environ={"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"},
        which=_which("wl-copy", "wl-paste", "wtype"),
    )
    checks = _complete_targets(environment)

    assert next(
        check for check in initial_checks(environment)
        if check["name"] == "global hotkey path available"
    )["status"] == "UNTESTED"
    assert build_evidence(environment, checks)["overall"] == "PASS"


def test_observed_workflow_failure_is_never_downgraded_to_untested():
    environment = detect_environment(system="Windows", environ={}, which=_which())
    checks = [
        {"name": "selected-text capture", "status": "FAIL", "detail": "observed failure"},
        {"name": "rewrite opens review-only draft", "status": "UNTESTED", "detail": "stopped"},
        {"name": "clipboard is restored", "status": "UNTESTED", "detail": "stopped"},
        {"name": "no automatic send occurs", "status": "UNTESTED", "detail": "stopped"},
    ]

    assert build_evidence(environment, checks)["overall"] == "FAIL"


def test_non_interactive_cli_emits_json_and_markdown_without_clipboard(tmp_path, capsys):
    output_dir = Path(tmp_path) / "evidence"

    result = main(["--non-interactive", "--output-dir", str(output_dir)])

    assert result == 0
    assert (output_dir / "selection-capture-qualification.json").exists()
    assert (output_dir / "selection-capture-qualification.md").exists()
    output = capsys.readouterr().out
    assert "No clipboard reads/writes or synthetic key presses" in output
    assert "Overall: UNTESTED" in output


def test_evidence_separates_capabilities_and_per_target_workflow(tmp_path):
    artifact = tmp_path / "BetterFingers.AppImage"
    artifact.write_bytes(b"artifact bytes")
    environment = detect_environment(system="Windows", environ={}, which=_which())
    metadata = collect_metadata(
        artifact=artifact,
        model_identifier="model@test",
        runtime_identifier="runtime@test",
    )
    environment["representative_apps"] = ["Notepad", "Browser"]
    checks = [
        {
            "target": "Notepad",
            "checks": [
                {"name": name, "status": "PASS", "detail": "observed"}
                for name in ("selected-text capture", "rewrite opens review-only draft", "clipboard is restored", "no automatic send occurs")
            ],
        },
        {
            "target": "Browser",
            "checks": [
                {"name": "selected-text capture", "status": "UNTESTED", "detail": "not run"},
            ],
        },
    ]

    evidence = build_evidence({**environment, "metadata": metadata}, checks)

    assert evidence["overall"] == "UNTESTED"
    assert evidence["capability_checks"]
    assert len(evidence["workflow_targets"]) == 2
    assert evidence["observed_check_count"] == 4
    assert evidence["metadata"]["artifact"]["size_bytes"] == len(b"artifact bytes")
    assert len(evidence["metadata"]["artifact"]["sha256"]) == 64
    assert evidence["metadata"]["model_identifier"] == "model@test"
    assert evidence["metadata"]["runtime_identifier"] == "runtime@test"


def test_missing_operator_metadata_is_unTested_not_guessed():
    checks = metadata_checks({})

    assert checks
    assert all(check["status"] == "UNTESTED" for check in checks)


def test_aggregate_legacy_passes_cannot_authorize_overall_pass():
    environment = detect_environment(system="Windows", environ={}, which=_which())
    checks = _target_checks()

    assert build_evidence(environment, checks)["overall"] == "UNTESTED"


def test_malformed_two_target_records_cannot_authorize_pass():
    environment = detect_environment(system="Windows", environ={}, which=_which())
    environment["representative_apps"] = ["Target A", "Target B"]
    cases = [
        [{"target": "Target A", "checks": _target_checks()}],
        [
            {"target": "Target A", "checks": _target_checks()},
            {"target": "Target B", "checks": _target_checks(names=(*WORKFLOW_CHECK_NAMES[:-1], "made-up check"))},
        ],
        [
            {"target": "Target A", "checks": _target_checks()},
            {"target": "Target B", "checks": _target_checks()[:-1]},
        ],
        [
            {"target": "Target A", "checks": _target_checks()},
            {"target": "Target B", "checks": _target_checks(names=(*WORKFLOW_CHECK_NAMES[:-1], WORKFLOW_CHECK_NAMES[0]))},
        ],
        [
            {"target": "Target A", "checks": _target_checks()},
            {"target": "Target B", "checks": []},
        ],
    ]

    assert all(build_evidence(environment, case)["overall"] == "UNTESTED" for case in cases)


def test_fail_remains_fail_for_malformed_workflow_input():
    environment = detect_environment(system="Windows", environ={}, which=_which())
    environment["representative_apps"] = ["Target A", "Target B"]
    checks = [
        {"target": "Target A", "checks": _target_checks(status="FAIL")},
        {"target": "Target B", "checks": []},
    ]

    assert build_evidence(environment, checks)["overall"] == "FAIL"
