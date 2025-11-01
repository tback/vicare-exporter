import datetime
import json
import os
import secrets
from pathlib import Path

from PyViCare.PyViCare import PyViCare

from vicare_exporter.metrics import ViCareCollector

TEST_GATEWAY_ID = "123456789"
TEST_TIMESTAMP = "2024-04-01T01:02:03.456Z"


def anonymize(data):
    for feature in data:
        feature["gatewayId"] = TEST_GATEWAY_ID
        feature["uri"] = "<unused>"
        feature["timestamp"] = TEST_TIMESTAMP
        feature["commands"] = {}
        if feature["feature"].endswith("serial"):
            feature["properties"] = {}
    return data


if __name__ == "__main__":
    import dotenv

    dotenv.load_dotenv()
    vicare = PyViCare()

    username = os.environ["VICARE_USERNAME"]
    client_id = os.environ["VICARE_CLIENT_ID"]
    password = os.environ["VICARE_PASSWORD"]
    vicare.initWithCredentials(
        username=username,
        password=password,
        client_id=client_id,
        token_file=".vicare_token",
    )
    collector = ViCareCollector(vicare=vicare, ignore_devices=[])
    collector._fetch_features()

    test_data_folder = Path(__file__).parent / "data"
    test_data_folder.mkdir(parents=True, exist_ok=True)

    prefix = secrets.token_urlsafe(4)
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    anon_data = {}
    for i, (k, v) in enumerate(collector._data.items(), start=1):
        anon_data[str(i)] = {"data": anonymize(v["data"])}

    with open(test_data_folder / f"{prefix}_data.json", "w") as fp:
        json.dump(anon_data, fp, indent=True)
