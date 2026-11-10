#!/usr/bin/env python3
"""Updates issuance.wasm and presentation.wasm prebuilts from a Kokoro/Fusion URL.

Usage:
  python3 update_wasm.py <FUSION_URL_OR_GCS_URI> [--dry-run]
"""

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.parse


def find_prebuilts_root(start_dir: str) -> str:
    """Finds the root of prebuilts/androidx/credentials."""
    current = os.path.abspath(start_dir)
    while current and current != os.path.dirname(current):
        if os.path.isdir(os.path.join(current, "wasm", "issuance")):
            return current
        current = os.path.dirname(current)
    return os.path.abspath(start_dir)


def extract_fusion_info(url_or_uri: str) -> tuple[str, str] | None:
    """Parses a Fusion URL using urllib.parse to extract the job name and activity UUID."""
    parsed = urllib.parse.urlparse(url_or_uri)
    path_segments = [seg for seg in parsed.path.split("/") if seg]

    job = None
    uuid = None

    for i, segment in enumerate(path_segments):
        if segment.startswith("prod:"):
            job = urllib.parse.unquote(segment[len("prod:") :])
        elif segment == "activity" and i + 1 < len(path_segments):
            uuid = path_segments[i + 1]

    if job and uuid:
        return job, uuid
    return None


def resolve_gcs_build_dir(job: str, uuid: str) -> tuple[str, str]:
    pattern = f"gs://wasm-build-artifacts/prod/{job}/**/{uuid}.intoto.jsonl"
    print(f"Resolving GCS directory for UUID {uuid}...")
    res = subprocess.run(
        ["gcloud", "storage", "ls", pattern],
        capture_output=True,
        text=True,
        check=True,
    )
    lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
    if not lines:
        raise ValueError(
            f"No provenance file found on GCS matching pattern: {pattern}"
        )
    intoto_path = lines[0]
    build_dir = os.path.dirname(intoto_path)
    return build_dir, intoto_path


def parse_intoto_digests(intoto_path: str) -> dict[str, str]:
    print(f"Reading provenance from {intoto_path}...")
    res = subprocess.run(
        ["gcloud", "storage", "cat", intoto_path],
        capture_output=True,
        text=True,
        check=True,
    )
    digests = {}
    for line in res.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            payload_bytes = base64.b64decode(entry["payload"])
            statement = json.loads(payload_bytes)
            for subject in statement.get("subject", []):
                name = os.path.basename(subject["name"])
                sha256 = subject["digest"].get("sha256")
                if name and sha256:
                    digests[name] = sha256
        except Exception:
            continue
    return digests


def main():
    parser = argparse.ArgumentParser(
        description="Update AndroidX Credential WASM prebuilts from Fusion build"
    )
    parser.add_argument("url", help="Kokoro/Fusion URL or GCS build directory")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Download into /tmp and verify SHA-256 checksums without modifying repository files",
    )
    args = parser.parse_args()

    # Locate prebuilts/androidx/credentials repository root
    script_dir = os.path.dirname(os.path.abspath(__file__))
    prebuilts_dir = find_prebuilts_root(script_dir)

    fusion_info = extract_fusion_info(args.url)
    if fusion_info:
        job, uuid = fusion_info
        build_dir, intoto_path = resolve_gcs_build_dir(job, uuid)
        fusion_url = args.url
    elif args.url.startswith("gs://"):
        build_dir = args.url.rstrip("/")
        intoto_res = subprocess.run(
            ["gcloud", "storage", "ls", f"{build_dir}/*.intoto.jsonl"],
            capture_output=True,
            text=True,
            check=True,
        )
        lines = [
            line.strip() for line in intoto_res.stdout.splitlines() if line.strip()
        ]
        if not lines:
            raise ValueError(f"No .intoto.jsonl found in {build_dir}")
        intoto_path = lines[0]
        uuid = os.path.basename(intoto_path).replace(".intoto.jsonl", "")
        fusion_url = f"http://fusion2/ci/kokoro/prod:android-passkeys%2Fwasm%2Frbe%2Fcontinuous/activity/{uuid}/summary?pli=1"
    else:
        print(f"Error: Unrecognized URL or URI format: {args.url}", file=sys.stderr)
        sys.exit(1)

    parts = build_dir.rstrip("/").split("/")
    build_id = parts[-2] if len(parts) >= 2 else "unknown"

    print(f"\nTarget Build ID: {build_id}")
    print(f"GCS Build Directory: {build_dir}")
    print(f"Fusion URL: {fusion_url}\n")

    expected_digests = parse_intoto_digests(intoto_path)

    matcher_rs_base = f"{build_dir}/github/wasm/CredentialProvider/wasm/matcher-rs/target/wasm32-unknown-unknown/release"

    targets = [
        (
            f"{matcher_rs_base}/issuance.wasm",
            os.path.join(
                prebuilts_dir, "wasm", "issuance", "assets", "issuance.wasm"
            ),
            "issuance.wasm",
        ),
        (
            f"{matcher_rs_base}/THIRD_PARTY_LICENSES",
            os.path.join(prebuilts_dir, "wasm", "issuance", "LICENSE"),
            "THIRD_PARTY_LICENSES",
        ),
        (
            f"{matcher_rs_base}/presentation.wasm",
            os.path.join(
                prebuilts_dir,
                "wasm",
                "presentation",
                "assets",
                "presentation.wasm",
            ),
            "presentation.wasm",
        ),
        (
            f"{matcher_rs_base}/THIRD_PARTY_LICENSES",
            os.path.join(prebuilts_dir, "wasm", "presentation", "LICENSE"),
            "THIRD_PARTY_LICENSES",
        ),
    ]

    with tempfile.TemporaryDirectory(prefix="wasm_dry_run_") as tmpdir:
        dest_desc = "[Dry Run -> /tmp]" if args.dry_run else "Downloading files"
        print(f"\n{dest_desc}...")

        for gcs_src, local_dst, digest_key in targets:
            rel_dst = os.path.relpath(local_dst, prebuilts_dir)
            download_dst = (
                os.path.join(tmpdir, digest_key) if args.dry_run else local_dst
            )

            os.makedirs(os.path.dirname(download_dst), exist_ok=True)
            print(f"Downloading {digest_key} ({gcs_src})...")
            subprocess.run(
                ["gcloud", "storage", "cp", gcs_src, download_dst], check=True
            )

            with open(download_dst, "rb") as f:
                local_hash = hashlib.sha256(f.read()).hexdigest()

            expected_hash = expected_digests.get(digest_key)
            if expected_hash and local_hash != expected_hash:
                print(
                    f"Error: Hash mismatch for {digest_key}!\nExpected: {expected_hash}\nActual:   {local_hash}",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(f"  Verified SHA-256 ({rel_dst}): {local_hash}")

    if args.dry_run:
        print(
            "\n[Dry Run Completed] All downloads and SHA-256 checks succeeded. No repository files were modified."
        )
    else:
        print("\nAll WASM prebuilts and licenses successfully updated and verified!")

    print(f"\nSuggested Commit Message:\n{'='*40}")
    print(
        f"Update issuance.wasm and presentation.wasm prebuilts to build {build_id}\n\n"
        f"Update prebuilt issuance.wasm and presentation.wasm matcher binaries\n"
        f"from verified continuous build {build_id}:\n{fusion_url}\n\n"
        f"Test: ./gradlew :credentials:registry:registry-digitalcredentials-openid:connectedAndroidTest\n"
        f"TAG=agy\nCONV=<conversation_id>"
    )
    print("=" * 40)


if __name__ == "__main__":
    main()
