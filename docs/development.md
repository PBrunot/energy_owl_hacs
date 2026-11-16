# Development and validation

Use Python 3.14 on Linux/WSL. Production Home Assistant is on a separate machine.
The minimum HA version belongs in `hacs.json` and the README requirements table;
`homeassistant` and `diagnostics` are not valid HA manifest keys. Diagnostics are
discovered from diagnostics.py. `script/validate_metadata.py` checks local metadata
consistency, and hassfest validates HA schemas and translations.

## Test stacks

| Stack | Home Assistant | pytest plugin | Requirements |
| --- | --- | --- | --- |
| minimum | 2026.5.2 | 0.13.331 | requirements-test-min.txt |
| baseline | 2026.10.4 | 0.13.375 | requirements-test.txt |
| current runtime smoke | 2026.11.1 | none | requirements-runtime-current.txt |

The latest published pytest-homeassistant-custom-component still pins HA 2026.10.4.
An attempted override to 2026.11.1 fails during fixture import because the plugin
expects the removed private logger helper `_clear_logger_overwrites` (and pytest
startup also requires HA's newer HTTP-client alias ordering). Do not shim HA internals
to turn this into a passing suite. The current job therefore exercises real runtime
imports, constructors and action registration without pytest; full current-version
pytest coverage remains pending an updated fixture package.

Update these pins deliberately and run both full suites plus the current smoke check
after changes. This is a pinned compatibility matrix, not a complete transitive
lockfile; automated checks can expose changes in transitive dependencies.
The runtime OWL dependency stays pinned to 0.7.2 in manifest.json and both base stacks.

Run from the repository root:

```sh
PYTHON_BIN=python3.14 TEST_STACK=minimum bash run_tests.sh
PYTHON_BIN=python3.14 TEST_STACK=baseline bash run_tests.sh
```

For a separate current-runtime environment:

```sh
python3.14 -m venv .venv-current
.venv-current/bin/pip install uv==0.9.28
.venv-current/bin/uv pip install --python .venv-current/bin/python -r requirements-runtime-current.txt
.venv-current/bin/python script/check_runtime.py
```

Each full-test stack gets its own `.venv-<stack>` directory. Override `TEST_VENV_DIR` to use
another location. The runner reinstalls the pinned requirements each time; it does
not silently reuse an old stack. Run it with Bash so an executable bit is unnecessary.

Tests replace serial I/O only. The actual OWL package, integration loader,
coordinator, platforms, HA Store and Recorder APIs are exercised locally.
Hardware clock accuracy and production database repair require separate validation.

## Metadata and lint

```sh
python3.14 -m pip install -r requirements-lint.txt
ruff check custom_components/energy_owl
python3.14 script/validate_metadata.py
git diff --check
```

Ruff is pinned in requirements-lint.txt. `.github/workflows/validate.yml` runs it
alongside hassfest and HACS validation. The HACS job disables PR commenting and
skips only `brands`, whose registration is tracked in quality-scale.md. HACS checks
repository metadata through GitHub; it is not a substitute for local tests.

For local hassfest, use the [official action](https://github.com/home-assistant/actions/tree/master/hassfest)
or the [HA Core script](https://contributors.home-assistant.io/core/development/linters/)
with a matching HA environment:

```sh
# Run from a Home Assistant Core source checkout with its tooling installed:
python3 -m script.hassfest --integration-path /absolute/path/to/custom_components/energy_owl
```

The CI validation actions follow their upstream branches to catch schema changes;
the test stacks and lint version are pinned. Never add a quality-scale tier to the
manifest merely because tests or hassfest pass. See quality-scale.md for the audit.

## Version and publishing

The integration release version lives only in manifest.json. It is not a CM160
firmware version and is not exposed as one on device metadata. Release notes and
tags are updated only for an explicitly requested release. Version 0.9.3 includes
the packaging/validation improvements and interleaved-history fixes.
