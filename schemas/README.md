# Private JSON schemas

`People.schema.json` validates the identity map that belongs in a private `People.json`. `Journal Rules.schema.json` validates the installation-specific rules that belong in a private `Journal Rules.json`. `schema.json` is the small catalog schema covering either document shape.

The schemas are documentation and editor-validation contracts. Dossify still validates the data it consumes at runtime, and it never writes the private files back.
