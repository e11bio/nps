"""
List all labels of an nps run with more than --max-points sampled points.

pocaduck's optimizer holds every label entirely in memory as Python objects,
so a single giant segment (e.g. a 300M-point glia or merge error) exceeds any
reasonable job memory limit. optimize_worker.py skips the labels in this list.

The output is a tab-separated file (label, point count), largest first, with a
header comment line. Excluded labels will not be in the optimized index, so
pocaduck's Query returns no points for them.

Usage: python find_large_labels.py BASE_PATH MAX_POINTS OUTPUT
       (BASE_PATH is <output-dir>/points, which holds unified_index.db)
"""

import os
import sys

import duckdb


def main():
    base_path, max_points, output = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    con = duckdb.connect(os.path.join(base_path, "unified_index.db"), read_only=True)
    rows = con.execute(
        """
        SELECT label, sum(point_count)::UBIGINT AS points
        FROM point_cloud_index
        GROUP BY label
        HAVING sum(point_count) > ?
        ORDER BY points DESC
        """,
        [max_points],
    ).fetchall()
    con.close()

    # Write-then-rename so workers never read a half-written list.
    with open(output + ".tmp", "w") as f:
        f.write(f"# labels with more than {max_points} points\tpoints\n")
        f.writelines(f"{label}\t{points}\n" for label, points in rows)
    os.replace(output + ".tmp", output)

    print(f"{len(rows)} labels with more than {max_points:,} points -> {output}")
    for label, points in rows:
        print(f"  {label}\t{points:,}")


if __name__ == "__main__":
    main()
