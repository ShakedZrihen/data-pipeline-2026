# Shared Python dependencies

Services importing modules from `salim/shared` must install
`salim/shared/requirements.txt` in addition to their service-specific
requirements. Docker builds must use `salim/` as their build context so both
dependency files are available.

The extractor image demonstrates this contract in
`services/extractor/Dockerfile`.

## S3 provider configuration

Provider selection is mandatory; the client never silently falls back to AWS.

| Variable | Description |
|---|---|
| `S3_PROVIDER` | `minio`, `supabase`, or the explicit AWS opt-in `aws` |
| `S3_ENDPOINT_URL` | Required for MinIO and Supabase; forbidden for AWS |
| `S3_ACCESS_KEY`, `S3_SECRET_KEY` | Optional credentials, but supplied together |
| `S3_REGION` | Provider region |
| `S3_CONNECT_TIMEOUT` | Connection timeout in seconds; default `5` |
| `S3_READ_TIMEOUT` | Read timeout in seconds; default `60` |
| `S3_TOTAL_MAX_ATTEMPTS` | Total attempts including the first; default `3` |
| `S3_RETRY_MODE` | Botocore retry mode; default `standard` |

## Tests

Unit tests do not require external services:

```bash
python -m unittest salim.shared.tests.test_s3 -v
```

The MinIO integration test covers bucket creation, upload, paginated listing,
download, and byte-for-byte content verification:

```bash
cd salim
docker compose --profile integration up --build --abort-on-container-exit
```
