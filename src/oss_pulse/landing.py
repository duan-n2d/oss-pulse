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
