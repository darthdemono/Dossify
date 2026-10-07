# dossify-adapter-api

The public contract an external Dossify adapter implements: `Fact`, `AdapterManifest`, `ExecutionPlan`, `AdapterResult`, `Provenance`, `Coverage` and friends. It depends only on pydantic, so an adapter package never needs the whole Dossify engine.

Register an adapter in your package's entry points and run `dossify conformance` against it:

```toml
[project.entry-points."dossify.adapters"]
my_provider = "my_package:ADAPTER"
```

An adapter has a `manifest`, a pydantic `config_model`, a `plan(config)` that lists intended reads without parsing them, and an `execute(config, plan, fingerprints)` that returns an `AdapterResult`. It never writes journals and never touches paths the plan did not declare. Dossify loads an external adapter only when the owner lists its name under `[adapters] external` in their private configuration.
