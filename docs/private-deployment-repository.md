# Private deployment repository pattern

Keep release automation separate from public Android source repositories. The
reference implementation is the private
[`radiosound-com/caramel-app-publisher`](https://github.com/radiosound-com/caramel-app-publisher)
repository. It consumes these public refs without adding deployment workflows
to them:

* `radiosound-com/android_packages_apps_Caramel_Store@main`
* `radiosound-com/OsmAnd@caramel-vanilla-osmand-aaos`

This is especially useful for the OsmAnd fork: the public branch stays easy to
review and contribute upstream, while the private deployment repository owns
the Automotive build task, dedicated Caramel signing, versioning, and upload.

## Setup outline

1. Create a private deployment repository from this repository's builder,
   schemas, `apps.json`, metadata, and public signing key.
2. Add a private workflow that polls the approved public refs, records their
   SHAs in a private state branch, and serializes the build/publish job.
3. Register a repository-scoped self-hosted runner with labels such as
   `caramel-release`, `macos`, and `arm64`. Do not attach it to public source
   repositories or fork-triggered workflows.
4. Create a protected `production-release` environment and add the release
   keystores/passwords, detached-index private key/password, and narrowly
   scoped object-store publisher credential as environment secrets.
5. Build Caramel Store with its release script. Build OsmAnd with
   `:OsmAnd:assembleNightlyFreeOpenglFatAutomotive`, then sign the resulting
   `net.osmand.dev` APK with its approved Caramel certificate before invoking
   `tools/build_repository.py`.
6. Download unchanged first-party APKs from the current catalog, assemble both
   packages into one output directory, run `tools/verify_repository.py`, and
   publish the complete directory atomically.

The publisher should run on main pushes, release tags, manual dispatch, and a
short schedule such as every five minutes. It must publish only when the
tracked source SHA changes, or when an explicit manual `force` input is set.
Use a separate state branch or another non-triggering state store so a state
update cannot recursively start another release.

## Secret and runner rules

Never commit a keystore, password, Kubernetes kubeconfig, object-store
credential, or private index key. Keep signing certificates and expected
certificate SHA-256 values in the public manifest; keep private key material
only in the private deployment environment. The publisher credential should be
limited to the one bucket and the `fdroid/repo` prefix.

The final publication unit is `build/repo/`: it contains the APKs, F-Droid
indexes and metadata, Caramel's detached signed index, icons, and screenshots.
Verify this directory before upload so the web UI and native store consume the
same catalog and media.
