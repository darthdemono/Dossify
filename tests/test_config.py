from pathlib import Path

from dossify.config import load_config


def test_private_paths_resolve_beside_toml(tmp_path: Path) -> None:
    config_path = tmp_path / "dossify.toml"
    config_path.write_text(
        '\n'.join(
            [
                'people_file = "People.json"',
                'output_dir = "."',
                '',
                '[journal]',
                'workspace_root = ".."',
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.people_file == tmp_path / "People.json"
    assert config.output_dir == tmp_path
    assert config.journal.workspace_root == tmp_path.parent
