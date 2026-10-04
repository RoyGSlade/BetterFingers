"""Stage pinned base.en bytes. Run from the repo root: python -m tools.bundle_models."""
import argparse
import sys

from backend.stt.bundle_staging import stage_bundled_model


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, help="Exact model directory, e.g. build/models/base.en")
    parser.add_argument("--from", dest="source_dir", help="Existing pinned snapshot directory")
    parser.add_argument("--allow-download", action="store_true", help="Explicitly permit a pinned Hub fetch")
    args = parser.parse_args(argv)
    try:
        output = stage_bundled_model(args.output_dir, source_dir=args.source_dir, allow_download=args.allow_download)
    except (OSError, ValueError) as exc:
        print(f"Bundled model staging refused: {exc}", file=sys.stderr)
        return 1
    print(f"Verified bundled model staged: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
