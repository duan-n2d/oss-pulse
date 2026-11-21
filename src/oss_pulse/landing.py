"""Write landed records as Parquet, one file per partition, overwritten on rerun."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def write_partition(table: pa.Table, path: Path) -> Path:
    """Atomically replace `path` with `table` so a rerun never duplicates rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    pq.write_table(table, tmp, compression="zstd")
    tmp.replace(path)
    return path


def write_bot_keys(raw_dir: Path, salt: str) -> Path:
    """Refresh raw/bot_keys so newly listed bots apply to data landed earlier."""
    from .privacy import bot_keys

    return write_partition(
        pa.Table.from_pylist(bot_keys(salt)), raw_dir / "bot_keys" / "bot_keys.parquet"
    )
