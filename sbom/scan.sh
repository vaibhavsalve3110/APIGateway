#!/usr/bin/env bash
# Scans every SBOM in this folder against the vulnerability feeds.
#
#   ./scan.sh              summary per document, then every fixable High or Critical
#   ./scan.sh --all        also lists Medium
#   ./scan.sh --json <dir> keeps the raw grype JSON in <dir> as well
#
# Run ./generate.sh first, or this scans a build nobody is running. Nothing is installed: Grype runs
# from its own image, with its feed database cached in a Docker volume so it is downloaded once
# rather than once per document.
#
# ---------------------------------------------------------------------------- what the exit code means
#
# Non-zero when a **fixable** High or Critical exists — one where the feed names a version that
# resolves it. That is the line worth failing a build on, and it is deliberately not "any High":
#
#   * A Debian base image carries a long tail of advisories with no fixed version available. They
#     are real, they are mostly unreachable from this service (mount helpers, terminfo tools, Perl
#     archive parsing), and nothing in this repository can clear them. Failing on those means the
#     gate is red permanently, which is the same as having no gate.
#   * A finding with a fix is a decision someone has to make today: take the upgrade, or write down
#     why not.
#
# When the base image's own tail grows long, the fix is to move to a newer base, not to widen this
# rule. That is why backend-python moved from bookworm to trixie.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

list_medium=0
json_dir=""
while [ $# -gt 0 ]; do
  case "$1" in
    --all)  list_medium=1; shift ;;
    --json) json_dir="${2:-}"; shift 2 ;;
    *)      echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

GRYPE_IMAGE="anchore/grype:latest"
# Git Bash rewrites container paths that look like Unix paths; this leaves them alone.
export MSYS_NO_PATHCONV=1

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Docker Desktop needs a Windows path. Without this the bind mount silently resolves inside the
# Docker VM instead: every scan reports success, the results are written somewhere this script
# cannot see, and the summary comes out empty — which reads exactly like "no vulnerabilities".
work_mount="$work"
sbom_mount="$here"
if command -v cygpath >/dev/null 2>&1; then
  work_mount="$(cygpath -m "$work")"
  sbom_mount="$(cygpath -m "$here")"
fi

docker volume create apigw-grype-db >/dev/null 2>&1

scan() {  # scan <document name>
  docker run --rm \
    -v "$sbom_mount:/sbom:ro" \
    -v "$work_mount:/out" \
    -v apigw-grype-db:/.cache/grype \
    -e GRYPE_DB_CACHE_DIR=/.cache/grype \
    "$GRYPE_IMAGE" "sbom:/sbom/$1.cdx.json" -o json --file "/out/$1.json" -q >/dev/null 2>&1
}

names=()
for f in "$here"/*.cdx.json; do
  names+=("$(basename "$f" .cdx.json)")
done

echo "Scanning ${#names[@]} documents (the feed database is cached; the first run downloads it)"
for name in "${names[@]}"; do
  printf '  %-32s ' "$name"
  if scan "$name"; then echo "ok"; else echo "FAILED"; fi
done

if [ -n "$json_dir" ]; then
  mkdir -p "$json_dir" && cp "$work"/*.json "$json_dir"/ 2>/dev/null
  echo
  echo "Raw results in $json_dir"
fi

echo
# $work_mount, not $work: on Windows the interpreter on PATH is Windows Python, which reads Git
# Bash's /tmp/... as C:\tmp\... — a directory that does not exist. It would then find no result
# files and print a clean report, which is the worst possible way for a scanner to fail.
LIST_MEDIUM="$list_medium" python - "$work_mount" <<'PY'
import json, os, pathlib, sys

work = pathlib.Path(sys.argv[1])
list_medium = os.environ.get("LIST_MEDIUM") == "1"
order = ["Critical", "High", "Medium", "Low", "Negligible", "Unknown"]
listed = {"Critical", "High"} | ({"Medium"} if list_medium else set())

results = sorted(work.glob("*.json"))
if not results:
    # Refuse to print a clean report from no data. Every earlier version of this script that got
    # the work directory wrong said "no vulnerabilities" and exited 0.
    print(f"ERROR: no scan results in {work} — every scan failed, or the mount is wrong",
          file=sys.stderr)
    sys.exit(2)

summary, fixable, unfixable_high = {}, [], {}
for path in results:
    name = path.stem
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:                       # a scan that failed above
        summary[name] = f"could not be read ({exc})"
        continue
    counts = dict.fromkeys(order, 0)
    for match in report.get("matches", []):
        vuln, art = match["vulnerability"], match["artifact"]
        severity = vuln.get("severity", "Unknown")
        counts[severity] = counts.get(severity, 0) + 1
        fixed_in = ", ".join(vuln.get("fix", {}).get("versions", []) or [])
        row = (severity, name, art["type"], art["name"], art["version"], vuln["id"], fixed_in)
        if fixed_in and severity in listed:
            fixable.append(row)
        elif not fixed_in and severity in ("Critical", "High"):
            unfixable_high[(name, art["type"])] = unfixable_high.get((name, art["type"]), 0) + 1
    summary[name] = counts

print(f"{'document':<32} {'crit':>5} {'high':>5} {'med':>5} {'low':>5} {'negl':>5}")
for name, counts in summary.items():
    if isinstance(counts, str):
        print(f"{name:<32} {counts}")
        continue
    print(f"{name:<32} {counts['Critical']:>5} {counts['High']:>5} {counts['Medium']:>5} "
          f"{counts['Low']:>5} {counts['Negligible']:>5}")

print()
if fixable:
    print(f"FIXABLE — {len(fixable)} finding(s) with a published fix:")
    rank = {s: i for i, s in enumerate(order)}
    for severity, doc, kind, pkg, version, vid, fixed_in in sorted(
        fixable, key=lambda r: (rank.get(r[0], 9), r[1], r[3])
    ):
        print(f"  {severity:<9} {doc:<28} {kind:<7} {pkg} {version} -> {fixed_in}   {vid}")
else:
    print("FIXABLE — none. Every High or Critical left is one the feed has no fixed version for.")

if unfixable_high:
    print()
    print("No fix available (base images and OS packages — recorded, not actionable here):")
    for (doc, kind), count in sorted(unfixable_high.items()):
        print(f"  {count:>4} High/Critical   {doc} ({kind})")

sys.exit(1 if fixable else 0)
PY
