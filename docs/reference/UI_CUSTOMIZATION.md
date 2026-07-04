# UI customization reference

OpenHarness keeps presentation choices separate from engine conversation state. Settings are loaded
by the Python runtime and projected to the React terminal through `AppState` and frontend config.

## Themes

`themes/schema.py::ThemeConfig` defines colors, borders, icons, and layout. Built-ins live in
`themes/builtin.py`; custom themes are loaded from the OpenHarness config root by
`themes/loader.py::load_custom_themes()`.

- `/theme` lists, previews, shows, or persists a theme.
- Root `--theme` also persists the selected setting; it is not merely a one-run override.
- The React launcher resolves the effective theme into `OPENHARNESS_FRONTEND_CONFIG`.

Invalid or missing custom themes should fall back through loader behavior rather than crashing the
engine.

## Output styles

`output_styles/loader.py::load_output_styles()` combines built-in/default presentation instructions
with user style files. `/output-style` updates the setting used for prompt/rendering behavior.
Output style affects presentation and model guidance; it must not change permission or persistence
semantics.

## Keybindings

`keybindings/loader.py` reads user overrides, `parser.py` parses mappings, and
`resolver.py::resolve_keybindings()` overlays them on `default_bindings.py`. `/keybindings` shows
the resolved mapping that the backend exports in `AppState`.

Python and TypeScript must agree on action names. A keybinding can be syntactically valid yet unused
if the frontend does not implement the action.

## Vim mode

`vim/transitions.py::toggle_vim_mode()` changes persisted mode state; the React input components own
the actual editing transitions. `/vim` is therefore a configuration/diagnostic command, not an
independent editor implementation in Python.

## Voice mode

`voice/voice_mode.py::inspect_voice_capabilities()` combines provider metadata with local feature
availability. `toggle_voice_mode()` persists the flag. `stream_stt.py::transcribe_stream()` is a
current capability boundary rather than a general speech service, and `keyterms.py` extracts simple
terms from recognized text.

Provider “voice supported” metadata does not prove end-to-end microphone, transcription, or playback
support on a given host. `/voice` diagnostics should be treated as capability hints.

## Testing changes

- Theme/output/keybinding loader tests belong under config/command/UI tests.
- Protocol/AppState field changes require Python backend and TypeScript type/handler updates.
- Keyboard behavior needs frontend component or terminal E2E validation; typechecking alone does not
  prove escape-sequence behavior.
- Custom files in personal config roots must never be read by normal tests.
