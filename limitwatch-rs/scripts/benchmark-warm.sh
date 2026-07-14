#!/usr/bin/env bash
# Repeated warm benchmark. Output is deliberately limited to timings and
# executable metadata; command output (including quota payloads) is discarded.
set -euo pipefail

usage() {
    echo "usage: $0 --offline|--live [--samples N]" >&2
    exit 2
}

mode=
samples=9
while (($#)); do
    case "$1" in
        --offline|--live)
            [[ -z "$mode" ]] || usage
            mode=${1#--}
            shift
            ;;
        --samples)
            (($# >= 2)) || usage
            samples=$2
            shift 2
            ;;
        *) usage ;;
    esac
done
[[ -n "$mode" && "$samples" =~ ^[1-9][0-9]*$ ]] || usage

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"
source "$HOME/.cargo/env"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

now_ns() { date +%s%N; }

# Arguments after the label are executed without eval. Their output is never
# copied to benchmark output, even when a provider returns an error.
measure() {
    local label=$1 i start end elapsed
    shift
    : >"$tmp/$label.samples"
    for ((i = 1; i <= samples; i++)); do
        start=$(now_ns)
        if ! "$@" >"$tmp/$label.stdout" 2>"$tmp/$label.stderr"; then
            echo "benchmark command failed: $label (output suppressed)" >&2
            return 1
        fi
        end=$(now_ns)
        elapsed=$(((end - start) / 1000000))
        echo "$elapsed" >>"$tmp/$label.samples"
    done
    awk -v label="$label" '
        { value[NR]=$1; sum+=$1 }
        END {
            n=NR
            for (i=1; i<=n; i++) for (j=i+1; j<=n; j++)
                if (value[i] > value[j]) { t=value[i]; value[i]=value[j]; value[j]=t }
            if (n % 2) median=value[(n+1)/2]
            else median=(value[n/2]+value[n/2+1])/2
            printf "%s: median=%.1fms spread=%d..%dms samples=%d\n", label, median, value[1], value[n], n
        }
    ' "$tmp/$label.samples"
}

echo "method: one discarded warm-up, then repeated process wall time; spread=min..max"
echo "pre-change evidence: rust=2.03s python=1.43s (not measured by this run)"

if [[ "$mode" == offline ]]; then
    echo "mode: offline"
    echo "workload: concurrent SharedHttp requests to credential-free local HTTP server; asserts pooled connection reuse"
    cargo build --quiet --release --example offline_shared_http
    offline_bin="$root/target/release/examples/offline_shared_http"
    "$offline_bin" >"$tmp/offline-warm.stdout" 2>"$tmp/offline-warm.stderr"
    measure offline "$offline_bin"
    exit
fi

python_bin=$(command -v limitwatch || true)
[[ -n "$python_bin" ]] || { echo "installed Python limitwatch not found" >&2; exit 1; }
rust_bin="$root/target/release/limitwatch"

echo "mode: live (explicit opt-in; history recording is disabled)"
echo "rust command: $rust_bin --no-record"
echo "python command: $python_bin --no-record"
cargo build --quiet --release
echo "rust version: $($rust_bin --version 2>/dev/null | head -n 1)"
echo "python version: $($python_bin --version 2>/dev/null | head -n 1)"

"$rust_bin" --no-record >"$tmp/rust-warm.stdout" 2>"$tmp/rust-warm.stderr" || {
    echo "live warm-up failed: rust (output suppressed)" >&2; exit 1;
}
"$python_bin" --no-record >"$tmp/python-warm.stdout" 2>"$tmp/python-warm.stderr" || {
    echo "live warm-up failed: python (output suppressed)" >&2; exit 1;
}
measure rust-live "$rust_bin" --no-record
measure python-live "$python_bin" --no-record
