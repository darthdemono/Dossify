# Private JSON schemas

`People.schema.json` validates the identity map that belongs in a private `People.json`. `schema.json` is the small catalog schema. Everything else a source needs lives as options in `dossify.toml`; `docs/PROVIDERS.md` lists them.

The schemas are documentation and editor-validation contracts. Dossify still validates the data it consumes at runtime, and it never writes the private files back.
