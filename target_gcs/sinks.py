"""GCS target sink class, which handles writing streams.
Opens an I/O stream pointed to a blob in the GCS bucket
As messages are received from the source, they are streamed to the bucket. As the max batch size is reached, the queue is emptied and written to the I/O streams

"""
import time
from collections import defaultdict
from datetime import datetime
from io import FileIO
from typing import Optional

import orjson
import smart_open
from google.cloud.storage import Client
from singer_sdk.sinks import RecordSink


class GCSSink(RecordSink):
    """GCS target sink class."""

    max_size = 1000  # Max records to write in one batch

    def __init__(self, target, stream_name, schema, key_properties):
        super().__init__(
            target=target,
            stream_name=stream_name,
            schema=schema,
            key_properties=key_properties,
        )
        self._gcs_write_handle: Optional[FileIO] = None
        self._key_name: str = ""

    @property
    def key_name(self) -> str:
        """Return the key name."""
        if not self._key_name:
            extraction_timestamp = round(time.time())
            base_key_name = self.config.get(
                "key_naming_convention",
                f"{self.stream_name}_{extraction_timestamp}.{self.output_format}",
            )
            prefixed_key_name = (
                f'{self.config.get("key_prefix", "")}/{base_key_name}'.replace(
                    "//", "/"
                )
            ).lstrip("/")
            date = datetime.today().strftime(self.config.get("date_format", "%Y-%m-%d"))
            self._key_name = prefixed_key_name.format_map(
                defaultdict(
                    str,
                    stream=self.stream_name,
                    date=date,
                    timestamp=extraction_timestamp,
                )
            )
        return self._key_name

    @property
    def gcs_write_handle(self) -> FileIO:
        """Opens a stream for writing to the target cloud object"""
        if not self._gcs_write_handle:
            credentials_path = self.config.get("credentials_file")
            self._gcs_write_handle = smart_open.open(
                f'gs://{self.config.get("bucket_name")}/{self.key_name}',
                "wb",
                transport_params=dict(
                    client=Client.from_service_account_json(credentials_path)
                ),
            )
        return self._gcs_write_handle

    @property
    def output_format(self) -> str:
        """In the future maybe we will support more formats"""
        return "jsonl"

    def process_record(self, record: dict, context: dict) -> None:
        """Process the record.

        Developers may optionally read or write additional markers within the
        passed `context` dict from the current batch.
        """
        if self.config.get("transformation_timestamp"):
            record.update({"transformation_timestamp": datetime.utcnow()})

        clean_record = {}
        for key, value in record.items():
            clean_record[self.create_valid_bigquery_field_name(key)] = value

        self.gcs_write_handle.write(
            orjson.dumps(clean_record, option=orjson.OPT_APPEND_NEWLINE)
        )

    @staticmethod
    def create_valid_bigquery_field_name(field_name: str) -> str:
        """
        Clean up / prettify field names, make sure they match BigQuery naming conventions.

        Fields must:
            • contain only
                -letters,
                -numbers, and
                -underscores,
            • start with a
                -letter or
                -underscore, and
            • be at most 300 characters long

        :param field_name:
        :param key: JSON field name
        :return: cleaned up JSON field name
        """

        cleaned_up_field_name = ""

        # if char is alphanumeric (either letters or numbers), append char to our string
        for char in field_name:
            if char.isalnum():
                cleaned_up_field_name += char
            else:
                # otherwise, replace it with underscore
                if char == '€':
                    cleaned_up_field_name += "euro"
                elif char == '$':
                    cleaned_up_field_name += "money"
                elif char == '%':
                    cleaned_up_field_name += "avg"
                else:
                    cleaned_up_field_name += "_"

        # if field starts with digit, prepend it with underscore
        if cleaned_up_field_name[0].isdigit():
            cleaned_up_field_name = "_%s" % cleaned_up_field_name

        return cleaned_up_field_name[:300]  # trim the string to the first x chars
