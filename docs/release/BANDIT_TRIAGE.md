# Bandit backend triage

Snapshot: 2026-08-04 (local checkout)

## Scope and command

The shipping Python surface is the tracked root-level Python modules plus
`backend/`. Tests, tools, docs, the Electron app, and the generated
`.betterfingers/` runtime tree are outside this scan. Bandit was installed in
the existing ignored `.venv` for this run:

```text
$ .venv/bin/bandit --version
bandit 1.9.4
  python version = 3.12.3 (main, Jun 19 2026, 12:46:00) [GCC 13.3.0]

$ .venv/bin/bandit -q -c .bandit -r backend *.py -f json -o /tmp/betterfingers-bandit-backend.json
```

The command returned exit status `1` before the inline suppression because
Bandit reports findings as a non-zero result. The JSON report contained 107
findings: 106 low, 1 medium, and 0 high. Confidence was 100 high and 7
medium. The medium/high finding list was:

| Severity | Confidence | ID | Location | Resolution |
|---|---|---|---|---|
| Medium | High | B103 `set_bad_file_permissions` | `model_manager.py:1098` | False positive; suppressed inline with `# nosec B103` and a reason. |

## Resolution and test evidence

`safe_extract_runtime_archive()` validates the runtime archive in a private
staging directory, checks its required-member allowlist, promotes only after
validation, and then sets the required runtime executable to `0o755`. That
permission is necessary for the downloaded `llama-server` to launch on POSIX;
changing it would break runtime provisioning. The direct test
`test_valid_archive_promotes_and_chmods_executable` in
`tests/test_supply_chain_existing_verify.py` asserts the promoted executable
has execute permission.

After the suppression, the same scoped command was re-run. Bandit still
returned `1` because the pre-existing low-severity baseline remains, but the
medium/high counts are zero:

```text
$ .venv/bin/bandit -q -c .bandit -r backend *.py -f json -o /tmp/betterfingers-bandit-backend.json
total_results=106
severity_counts={'LOW': 106}
confidence_counts={'HIGH': 99, 'MEDIUM': 7}
medium_or_high_count=0
bandit exit status: 1
medium: 0
high: 0
```

Targeted test:

```text
$ .venv/bin/python -m pytest -q tests/test_supply_chain_existing_verify.py
................                                                         [100%]
16 passed in 0.14s
PYTEST_EXIT=0
```

## Residual risk

The scan is clean for medium/high findings in the tracked shipping backend;
106 low-severity findings remain and are not part of this ticket. The inline
exception is limited to the validated runtime executable's launch permission
and is protected by the direct archive-promotion test.
