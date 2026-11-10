---
name: update_credential_wasm
description: Download, verify, test, and upload verified issuance.wasm and presentation.wasm matcher prebuilts in prebuilts/androidx/credentials from a Kokoro/Fusion URL.
---

# Updating WASM Matcher Prebuilts in AndroidX

Workflow for updating `issuance.wasm` and `presentation.wasm` matcher binaries in `prebuilts/androidx/credentials` from a Kokoro continuous build URL.

---

## 1. Automated Prebuilt Update

Run the update script with the Kokoro Fusion URL:

```bash
cd <android_root>/prebuilts/androidx/credentials/.agents/skills/update_credential_wasm/scripts
python3 update_wasm.py "http://fusion2/ci/kokoro/prod:android-passkeys%2Fwasm%2Frbe%2Fcontinuous/activity/<UUID>/summary?pli=1"
```

The script will automatically:
1. Parse the job name and activity UUID using standard URL parsing.
2. Locate the GCS build directory (`gs://wasm-build-artifacts/prod/...`).
3. Fetch the `.intoto.jsonl` provenance and verify SLSA L1 SHA-256 digests.
4. Download `issuance.wasm`, `presentation.wasm`, and `THIRD_PARTY_LICENSES`.
5. Update `wasm/issuance/` and `wasm/presentation/` and verify SHA-256 checksums against attested values.

---

## 2. Prepare Branch in `prebuilts/androidx/credentials`

Always start a fresh branch from `aosp/androidx-main`:
```bash
cd <android_root>/prebuilts/androidx/credentials
repo start update-wasm-build-<BUILD_ID> .
```

---

## 3. Run Verification Tests in `frameworks/support`

Verify that AndroidX Credential Manager tests pass against the new WASM binaries:
```bash
cd <android_root>/frameworks/support
PROJECT_PREFIX=:credentials ./gradlew \
  :credentials:registry:registry-digitalcredentials-openid:checkApi \
  :credentials:registry:registry-digitalcredentials-openid:ktCheck \
  :credentials:registry:registry-digitalcredentials-openid:test
```

---

## 4. Commit and Upload

### 4.1 Stage and Commit (Standard Git Commands)
```bash
cd <android_root>/prebuilts/androidx/credentials
git add wasm/issuance/assets/issuance.wasm wasm/presentation/assets/presentation.wasm

git commit -m "Update issuance.wasm and presentation.wasm prebuilts to build <BUILD_ID>

Update prebuilt issuance.wasm and presentation.wasm matcher binaries
from verified continuous build <BUILD_ID>:
http://fusion2/ci/kokoro/prod:android-passkeys%2Fwasm%2Frbe%2Fcontinuous/activity/<UUID>/summary?pli=1

Test: ./gradlew :credentials:registry:registry-digitalcredentials-openid:connectedAndroidTest
TAG=agy
CONV=<conversation_id>"
```

### 4.2 Upload to Gerrit
```bash
repo upload --cbr --topic=update-wasm-build-<BUILD_ID> .
```
