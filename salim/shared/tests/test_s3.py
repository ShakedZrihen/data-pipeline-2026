from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from salim.shared.s3 import download, getClient, get_client, ls, upload


class S3HelpersTests(TestCase):
    @patch("salim.shared.s3.boto3.client")
    def test_get_client_reads_project_environment(self, boto_client):
        with patch.dict(
            "os.environ",
            {
                "S3_ENDPOINT_URL": "https://project.supabase.co/storage/v1/s3",
                "S3_ACCESS_KEY": "access",
                "S3_SECRET_KEY": "secret",
                "S3_REGION": "eu-central-1",
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

    def test_ls_collects_all_pages_and_handles_empty_page(self):
        client = MagicMock()
        client.get_paginator.return_value.paginate.return_value = [
            {"Contents": [{"Key": "raw/a.xml"}, {"Key": "raw/b.xml"}]},
            {},
            {"Contents": [{"Key": "raw/c.xml"}]},
        ]

        self.assertEqual(ls(client, "bucket", "raw/"), ["raw/a.xml", "raw/b.xml", "raw/c.xml"])
        client.get_paginator.assert_called_once_with("list_objects_v2")
        client.get_paginator.return_value.paginate.assert_called_once_with(
            Bucket="bucket", Prefix="raw/"
        )
