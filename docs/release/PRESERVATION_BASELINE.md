# Gate 0 preservation baseline

Recorded 2026-07-28 against one already-running local model process. The
canonical lossless structural evidence is
[PRESERVATION_BASELINE.json](PRESERVATION_BASELINE.json). Neither artifact
contains probe text, model output, prompts, or user content.

## Binding result

| Axis | Current numeric snapshot | Release state |
|---|---:|---|
| Delivery | `PASS 3/3` | Qualified, but `use_delivery_signals=false`; enabling remains a separate owner decision. |
| Audience | `PASS 3/3` | Qualified, but `use_audience_context=false`; enabling also requires its release UI/control work. |
| Traits | Corrected production protocol: three consecutive suites, each `PASS 3/3` | **Unavailable.** `use_persona_traits=false` until a future director-approved repeated qualification policy reconciles the historical failure and invalid prior methodology. |

The corrected traits results replace the earlier Wave 0 numbers as the current
numeric snapshot. They do not qualify the feature. The 2026-07-27
`FAIL_TRAITS 0/3` remains a valid historical record in
[the traits design](../PERSONA_TRAITS_DESIGN.md). Earlier Wave 0 observations
of `2/3`, `3/3`, and `3/3` used the wrong preset name, temperature `0.3`, and
omitted the production True Janitor absolute rule. Those observations are
methodologically invalid and are not evidence for or against qualification.

## Runtime and corpus identity

- Endpoint `http://127.0.0.1:8080`; health returned `{"status":"ok"}`.
- Existing process start `2026-07-28T07:56:42Z`; this task did not start,
  reload, or stop it.
- Model `gemma-4-12b-it-Q4_K_M.gguf`, size `7,121,860,000` bytes, SHA-256
  `43fec98c5102b1c446b4ddd0a9439f1db3a2e1f2e0b8cd143ce1ea619a9403d6`.
- Host Linux Mint 22.3, kernel `7.0.0-28-generic`, x86_64; repository `.venv`
  CPython `3.12.3`.
- Corpus identifiers: `explicit-high-intensity`, `explicit-low-intensity`,
  and `negated-intensity`.
- Canonical corpus serialization:

```python
json.dumps(
    {"probes": PROBES, "warm_traits": WARM_TRAITS, "blunt_traits": BLUNT_TRAITS},
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
```

- Corpus SHA-256:
  `e5bf5dc2d0d0feea4a8f2f0c5bc1bbd0e1ad4c68e5ecc529749275f0e4abc956`.
- Source and model hashes, including
  `backend/services/message_rescue.py`, are recorded in the JSON.

## Delivery and audience

```text
.venv/bin/python tools/delivery_preservation.py --json
```

UTC `2026-07-28T08:27:18Z`–`08:27:42Z`; exit `0`; wall `23.57 s`;
peak RSS `32,168 KiB`. Delivery and audience each passed all three probes.
The JSON preserves the runner reports field-for-field, including
`empty_outputs`, attribution, fact categories, leaks, addressing, ratios,
counts, timings, and gate notes.

## Corrected traits protocol

The protocol was declared before results: exactly three consecutive suites,
with no result-dependent change between them. Every variant patched only the
persona returned by `get_persona_runtime`, then called:

```python
engine.process_fast_lane(
    text,
    "True Janitor",
    include_traits=traits is not None,
)
```

This literal preset applies the production True Janitor absolute rule and,
because the normalized probe persona has no temperature override, the
production strict temperature `0.05`.

Exact process invocation:

```text
.venv/bin/python -
```

Exact stdin adapter (SHA-256
`1e7cd32ca799230aa3729cfb8fcbf75d4660525b057645b1065178da6f254af1`):

```python
import json
from unittest.mock import patch
import llm_engine
from delivery_preservation import run_traits_preservation_suite
from persona_traits import neutral_traits

if not llm_engine.is_server_running():
    print(json.dumps({"overall": "UNAVAILABLE", "reason": "llama-server is not running"}, indent=2))
    raise SystemExit(2)

engine = llm_engine.LLMEngine()
base_prompt = llm_engine._DEFAULT_PERSONAS["True Janitor"]

def process_fn(text, traits=None):
    persona = llm_engine.normalize_persona({
        "prompt": base_prompt,
        "traits": traits if traits is not None else neutral_traits(),
    })
    with patch.object(llm_engine, "get_persona_runtime", return_value=persona):
        return engine.process_fast_lane(
            text,
            "True Janitor",
            include_traits=traits is not None,
        )

report = run_traits_preservation_suite(process_fn)
print(json.dumps(report, indent=2))
raise SystemExit(0 if report["overall"] == "PASS" else 1)
```

| Trial | UTC | Exit | Wall | Result |
|---:|---|---:|---:|---:|
| 1 | `08:42:42Z`–`08:42:55Z` | 0 | `12.88 s` | `PASS 3/3` |
| 2 | `08:43:07Z`–`08:43:20Z` | 0 | `12.51 s` | `PASS 3/3` |
| 3 | `08:43:30Z`–`08:43:44Z` | 0 | `13.92 s` | `PASS 3/3` |

All three field-for-field reports are in the JSON. This is a green corrected
numeric snapshot, not a qualification decision. Traits stays unavailable
until a director defines and approves a repeated evaluation policy that
reconciles the historical result, sampling behavior, corpus scope, and
acceptance threshold.
