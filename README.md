# Caramel App Repository

Static, signed Android application repository for first-party Caramel Vanilla
releases. The published directory is both an F-Droid binary repository and a
small pinned index consumed by the Caramel Store AAOS app.

The repository currently admits only:

* `com.radiosound.caramelstore`, signed by the dedicated Caramel Store key.
* `net.osmand.dev`, signed by the dedicated Caramel OsmAnd key.

The builder rejects an APK whose package name or signing-certificate SHA-256
does not match `apps.json`. APK signing keys, the F-Droid repository keystore,
the detached-index private key, passwords, and object-storage credentials must
never be committed or copied to the public web server.

## Build

Install the pinned repository tooling in a virtual environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Set the F-Droid keystore variables and build from already signed release APKs:

```sh
export ANDROID_HOME=/path/to/android-sdk
export FDROID_KEYSTORE=/secure/caramel-app-repository/fdroid-repository.p12
export FDROID_KEY_STORE_PASS="$(tr -d '\n' </secure/caramel-app-repository/fdroid-repository.pass)"
export FDROID_KEY_PASS="$FDROID_KEY_STORE_PASS"

python3 tools/build_repository.py \
  --aapt2 "$ANDROID_HOME/build-tools/36.0.0/aapt2" \
  --apksigner "$ANDROID_HOME/build-tools/36.0.0/apksigner" \
  --index-private-key /secure/caramel-app-repository/caramel-index-signing.pem \
  --index-key-password-file /secure/caramel-app-repository/caramel-index-signing.pass \
  --index-public-key keys/caramel-index-signing-public.pem \
  --apk com.radiosound.caramelstore=/path/to/CaramelStore.apk \
  --apk net.osmand.dev=/path/to/OsmAnd.apk

python3 tools/verify_repository.py build/repo \
  --public-key keys/caramel-index-signing-public.pem
```

`build/repo/` is the complete static publication unit. APKs use immutable
versioned names. App names, descriptions, icons, and Automotive screenshots
under `metadata/<package>/en-US/` are copied into both the F-Droid index and
the signed Caramel index. Signed index and media files are revalidated
frequently.

## Publish

`tools/publish_repository.sh` accepts only scoped S3-compatible publisher
credentials. It creates or reuses the `caramel-apps` bucket, grants anonymous
download access only to `fdroid/repo`, and uploads the static output:

```sh
export CARAMEL_S3_ENDPOINT=https://publisher.example.invalid
export CARAMEL_S3_ACCESS_KEY=...
export CARAMEL_S3_SECRET_KEY=...
tools/publish_repository.sh
```

For an administrator-only local `kubectl port-forward`, set
`CARAMEL_S3_INSECURE=true` because the service certificate does not cover
`localhost`. Production publishers must use the verified internal publisher
endpoint and leave this disabled.

Production reads are served at:

```text
https://caramel-vanilla-store.apps.radiosound.com/fdroid/repo/
```

The signing keys remain on the controlled release workstation/build host.
Kubernetes and the public object store contain only public keys and signed
artifacts.

## Private deployment repositories

Keep GitHub Actions that can access release keys and production upload
credentials out of this public repository. The setup pattern for a private
polling publisher, including the `OsmAnd@caramel-vanilla-osmand-aaos` seam and
dedicated self-hosted runner, is documented in
[`docs/private-deployment-repository.md`](docs/private-deployment-repository.md).

## Release policy

Every release must increase Android `versionCode`, pass the app's tests, pass
`apksigner verify`, and retain its package-specific signer. Upstream OsmAnd
changes are update candidates, not automatic releases: rebase, build, and test
the Automotive entry point and full parked UI before publication.

`upstreams.json` records the upstream branch and commit last reviewed for each
maintained fork. The daily `check upstream applications` GitHub Actions
workflow compares those pins with GitHub and creates or refreshes one review
issue when a branch moves. It never downloads an APK, invokes a release key,
builds a package, or publishes repository content. After a reviewed rebase,
update `last_reviewed_commit` in the same change that records the test result.
The repository or organization must enable GitHub Actions before the scheduled
workflow can run; `workflow_dispatch` is available for an initial smoke test.

Run the same check locally with:

```sh
python3 tools/check_upstreams.py
```

Run the repository tests with:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
```
