from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from botocore.exceptions import EndpointConnectionError

from salim.shared.s3 import (
    StorageProvider,
    download,
    getClient,
    get_client,
    iter_keys,
    iter_object_pages,
    iter_objects,
    ls,
    upload,
)


class S3HelpersTests(TestCase):
    @patch("salim.shared.s3.boto3.client")
    def test_get_client_requires_explicit_provider_and_reads_environment(self, boto_client):
        with patch.dict(
            "os.environ",
            {
                "S3_PROVIDER": "supabase",
                "S3_ENDPOINT_URL": "https://project.supabase.co/storage/v1/s3",
                "S3_ACCESS_KEY": "access",
                "S3_SECRET_KEY": "secret",
                "S3_REGION": "eu-central-1",
                "S3_CONNECT_TIMEOUT": "7",
                "S3_READ_TIMEOUT": "90",
                "S3_TOTAL_MAX_ATTEMPTS": "4",
            },
            clear=True,
        ):
            client = get_client()

        self.assertIs(client, boto_client.return_value)
        _, kwargs = boto_client.call_args
        self.assertEqual(kwargs["endpoint_url"], "https://project.supabase.co/storage/v1/s3")
        self.assertEqual(kwargs["aws_access_key_id"], "access")
        self.assertEqual(kwargs["aws_secret_access_key"], "secret")
        self.assertEqual(kwargs["region_name"], "eu-central-1")
        self.assertEqual(kwargs["config"].connect_timeout, 7)
        self.assertEqual(kwargs["config"].read_timeout, 90)
        self.assertEqual(kwargs["config"].retries["total_max_attempts"], 4)

    def test_get_client_refuses_implicit_aws_or_invalid_configuration(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "S3 provider is required"):
                get_client()
            with self.assertRaisesRegex(ValueError, "S3_ENDPOINT_URL is required"):
                get_client(StorageProvider.MINIO)
            with self.assertRaisesRegex(ValueError, "must be omitted"):
                get_client(StorageProvider.AWS, endpoint_url="http://minio:9000")
            with self.assertRaisesRegex(ValueError, "provided together"):
                get_client(StorageProvider.AWS, access_key="only-one")

    @patch("salim.shared.s3.get_client")
    def test_camel_case_alias_is_supported(self, create_client):
        self.assertIs(getClient(), create_client.return_value)

    def test_upload_uses_explicit_or_filename_key(self):
        client = MagicMock()
        self.assertEqual(upload(client, "bucket", "/tmp/report.xml"), "report.xml")
        client.upload_file.assert_called_once_with("/tmp/report.xml", "bucket", "report.xml")

        self.assertEqual(upload(client, "bucket", "/tmp/report.xml", "raw/report.xml"), "raw/report.xml")
        client.upload_file.assert_called_with("/tmp/report.xml", "bucket", "raw/report.xml")

    def test_download_creates_parent_directory(self):
        client = MagicMock()
        with TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "nested" / "report.xml"
            self.assertEqual(download(client, "bucket", "raw/report.xml", destination), destination)
            self.assertTrue(destination.parent.is_dir())
            client.download_file.assert_called_once_with("bucket", "raw/report.xml", str(destination))

    def test_iter_objects_is_lazy_and_yields_metadata_page_by_page(self):
        client = MagicMock()
        now = datetime.now(timezone.utc)
        client.list_objects_v2.side_effect = [
            {
                "Contents": [{"Key": "raw/a.xml", "ETag": "a", "Size": 1, "LastModified": now}],
                "IsTruncated": True,
                "NextContinuationToken": "page-2",
            },
            {"Contents": [{"Key": "raw/b.xml", "ETag": "b", "Size": 2}], "IsTruncated": False},
        ]

        objects = iter_objects(client, "bucket", "raw/", page_size=1)
        self.assertEqual(next(objects)["Key"], "raw/a.xml")
        self.assertEqual(client.list_objects_v2.call_count, 1)
        self.assertEqual(next(objects)["Size"], 2)
        self.assertEqual(client.list_objects_v2.call_count, 2)
        with self.assertRaises(StopIteration):
            next(objects)

    def test_incremental_scan_exposes_resume_token_and_max_items(self):
        client = MagicMock()
        client.list_objects_v2.side_effect = [
            {
                "Contents": [{"Key": "a"}, {"Key": "b"}],
                "IsTruncated": True,
                "NextContinuationToken": "resume-here",
            }
        ]

        pages = list(iter_object_pages(client, "bucket", page_size=100, max_items=2))
        self.assertEqual([item["Key"] for item in pages[0].objects], ["a", "b"])
        self.assertEqual(pages[0].next_token, "resume-here")
        client.list_objects_v2.assert_called_once_with(Bucket="bucket", Prefix="", MaxKeys=2)

    def test_ls_remains_compatible_and_uses_lazy_listing(self):
        client = MagicMock()
        client.list_objects_v2.return_value = {
            "Contents": [{"Key": "raw/a.xml"}, {"Key": "raw/b.xml"}],
            "IsTruncated": False,
        }
        self.assertEqual(list(iter_keys(client, "bucket", "raw/")), ["raw/a.xml", "raw/b.xml"])
        self.assertEqual(ls(client, "bucket", "raw/"), ["raw/a.xml", "raw/b.xml"])

    def test_exhausted_transient_failure_is_not_swallowed(self):
        client = MagicMock()
        error = EndpointConnectionError(endpoint_url="http://minio:9000")
        client.list_objects_v2.side_effect = error
        with self.assertRaises(EndpointConnectionError):
            list(iter_objects(client, "bucket"))
