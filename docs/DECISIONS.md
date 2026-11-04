# Decisions

- Implement and merge Phase 0 separately, then wait for the user's next-phase
  confirmation. No Phase 1 inference, UI, API, or subtitle dependency yet.
- Python 3.11.9 on Windows is the initial verified environment. Freeze resolved
  runtime and development dependencies into requirements.lock; installation of
  the project itself uses editable mode with --no-deps after the lock.
- Use TOML configuration via the Python standard library, with Pydantic validation.
  CLI flags override file fields; file fields override defaults.
- Validate language codes against the pinned faster-whisper tokenizer metadata;
  Babel supplies display names. This private backend metadata dependency is
  covered by tests and should be checked when upgrading faster-whisper.
- Restrict models to known multilingual Whisper variants, excluding English-only
  and turbo models. Per-model language capabilities (notably Cantonese support)
  must be enforced against a loaded model in Phase 1 before inference.
- Models are only downloaded by the explicit preparation command. Offline checks
  use local_files_only. No media leaves the machine.
- Preserve the user's ignored plan directory. Generated media, outputs, virtual
  environments, and Python caches remain outside source control.
- Checked upstream faster-whisper and CTranslate2 installation documentation.
  CPU is the tested path; CUDA discovery and DLL/model execution are distinct.
