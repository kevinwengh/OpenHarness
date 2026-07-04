# Reference index

Reference documents answer “what exactly exists?” They are exhaustive or table-oriented and should
be updated from source rather than inferred from marketing examples.

| Reference | Use it for | Source of truth |
| --- | --- | --- |
| [Configuration](CONFIGURATION.md) | settings shape, precedence, secrets, rebuild behavior | `config/settings.py`, CLI/runtime |
| [Environment variables](ENVIRONMENT_VARIABLES.md) | public and internal environment controls | `config`, tools, services, scripts |
| [Provider capabilities](PROVIDER_CAPABILITIES.md) | client-family features and compatibility layers | API clients and runtime selection |
| [State and persisted formats](STATE_AND_PERSISTED_FORMATS.md) | paths, formats, locks, recovery, versions | path/storage owners |
| [Tools and slash commands](TOOLS_AND_COMMANDS.md) | built-in model tools and local command surface | tool and command registries |
| [Channels](CHANNELS.md) | adapter configuration, authority, threading, media, support level | channel schema/implementations |
| [UI customization](UI_CUSTOMIZATION.md) | themes, output styles, keybindings, Vim, voice | UI/config subsystems |
| [Glossary](GLOSSARY.md) | consistent terminology | architecture and public contracts |

Provider wire details live under [`docs/developer/providers`](../developer/providers/README.md), and
extension authoring lives in [`docs/EXTENDING.md`](../EXTENDING.md).

## Maintenance rule

When possible, validate counts, names, defaults, and paths mechanically. Dynamic tools, commands,
skills, plugins, and MCP capabilities must be described as runtime-dependent rather than frozen in
a static count.
