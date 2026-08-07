#!/bin/sh
set -eu

: "${CARAMEL_S3_ENDPOINT:?set CARAMEL_S3_ENDPOINT}"
: "${CARAMEL_S3_ACCESS_KEY:?set CARAMEL_S3_ACCESS_KEY}"
: "${CARAMEL_S3_SECRET_KEY:?set CARAMEL_S3_SECRET_KEY}"
: "${CARAMEL_S3_BUCKET:=caramel-apps}"
: "${CARAMEL_REPOSITORY_DIR:=build/repo}"
: "${CARAMEL_S3_INSECURE:=false}"

if [ ! -f "$CARAMEL_REPOSITORY_DIR/caramel-index-v1.json" ]; then
  echo "repository index is missing: $CARAMEL_REPOSITORY_DIR" >&2
  exit 1
fi

alias_name="caramel-publish-$$"
mc_run() {
  if [ "$CARAMEL_S3_INSECURE" = "true" ]; then
    mc --insecure "$@"
  else
    mc "$@"
  fi
}
cleanup() {
  mc_run alias remove "$alias_name" >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM

mc_run alias set "$alias_name" "$CARAMEL_S3_ENDPOINT" \
  "$CARAMEL_S3_ACCESS_KEY" "$CARAMEL_S3_SECRET_KEY" >/dev/null
bucket_result=""
if ! bucket_result=$(mc_run mb --ignore-existing \
  "$alias_name/$CARAMEL_S3_BUCKET" 2>&1); then
  case "$bucket_result" in
    *TooManyBuckets*)
      # The production publisher is limited to its one pre-existing bucket
      # and cannot list it. Subsequent scoped operations prove ownership.
      ;;
    *)
      echo "$bucket_result" >&2
      exit 1
      ;;
  esac
fi
mc_run anonymous set download "$alias_name/$CARAMEL_S3_BUCKET/fdroid/repo" >/dev/null

find "$CARAMEL_REPOSITORY_DIR" -type f -name '*.apk' -print | while IFS= read -r file; do
  relative=${file#"$CARAMEL_REPOSITORY_DIR"/}
  mc_run cp --attr 'Cache-Control=public,max-age=31536000,immutable' "$file" \
    "$alias_name/$CARAMEL_S3_BUCKET/fdroid/repo/$relative" >/dev/null
done
find "$CARAMEL_REPOSITORY_DIR" -type f ! -name '*.apk' -print | while IFS= read -r file; do
  relative=${file#"$CARAMEL_REPOSITORY_DIR"/}
  mc_run cp --attr 'Cache-Control=public,max-age=300,must-revalidate' "$file" \
    "$alias_name/$CARAMEL_S3_BUCKET/fdroid/repo/$relative" >/dev/null
done

echo "published $CARAMEL_REPOSITORY_DIR to $CARAMEL_S3_BUCKET/fdroid/repo"
