# Quality-scale self-audit

Reviewed 2026-11-15 against the [Home Assistant rule list](https://contributors.home-assistant.io/core/quality-scale/rules/).
This is a repository self-audit, not certification or a claim of Bronze compliance.
The rules target Core integrations and official documentation; evidence here refers
to this custom integration and its README. Outstanding work is explicit below.

| Bronze rule | Assessment and evidence |
| --- | --- |
| action-setup | Implemented: async_setup registers services independently of entries; loader/action tests cover it. |
| appropriate-polling | Implemented: coordinator polls every 30 seconds; receipt timestamps distinguish cached data. |
| brands | Outstanding: no verified registration in home-assistant/brands. Local icons.json is not brand registration. HACS CI skips only this check. |
| common-modules | Implemented: shared constants, coordinator, entity base and energy helpers. |
| config-flow | Implemented: UI setup, options and port reconfiguration; no YAML configuration. |
| config-flow-test-coverage | Partial: success, duplicate, refusal and options tests exist; full branch coverage has not been demonstrated. |
| dependency-transparency | Implemented: serial I/O lives in pinned owlsensor; README names the dependency. |
| docs-actions | Implemented locally: README documents all four actions, targets, parameters and responses. |
| docs-conditions | Not applicable: no custom conditions. |
| docs-high-level-description | Implemented locally: README describes the monitor and estimated measurements. |
| docs-installation-instructions | Implemented locally: HACS/manual installation, serial permissions and requirements. |
| docs-removal-instructions | Implemented locally: README covers entry removal, uninstall and retained data. |
| docs-triggers | Not applicable: no custom automation triggers. The completion event is documented separately. |
| entity-event-setup | Implemented: CoordinatorEntity subscribes in its lifecycle; importer registers after platform setup and unsubscribes on close. |
| entity-unique-id | Implemented: four stable IDs, preserved when the same adapter changes ports. |
| has-entity-name | Implemented: entity base sets has_entity_name; translation keys supply names. |
| runtime-data | Implemented: typed EnergyOwlData on the config entry. |
| test-before-configure | Implemented: validate_input opens the serial connection and rejects False results. |
| test-before-setup | Implemented: first refresh precedes platform forwarding; refusal is tested through the loader. |
| unique-config-entry | Implemented for configured port strings; checked before opening serial. Aliases referring to the same physical port cannot be identified reliably without hardware identity. |

## Additional limits

The remaining Silver/Gold/Platinum rules have not received a complete audit, and no
higher-tier claim is made. Fully typed third-party APIs, complete branch coverage,
brand registration and hardware-independent identity remain follow-up work.
Pinned dependencies and CI results establish tested compatibility, not certification.
HA 2026.11.1 receives a runtime smoke check. Full pytest coverage on that version
is outstanding because the published fixture package imports a removed private HA
logger helper. See development.md for the reproduced failure; no HA shims are used.
