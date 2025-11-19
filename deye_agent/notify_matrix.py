
import http.client
import json
from urllib.parse import urlparse
from .i18n import _

def send_matrix_message(config, message, debug=False):

    homeserver = config.get("NOTIFY_MATRIX_HOMESERVER")
    access_token = config.get("NOTIFY_MATRIX_ACCESS_TOKEN")
    room_id = config.get("NOTIFY_MATRIX_ROOM_ID")

    if not homeserver or not access_token or not room_id:
        raise ValueError(_("Matrix config parameters missing"))

    if debug:
        print(_("Sending Matrix message to room {} on server {}").format(room_id, homeserver))

    # Parsing the host URL and schema
    url = urlparse(homeserver)
    if url.scheme == "https":
        conn = http.client.HTTPSConnection(url.netloc)
    else:
        conn = http.client.HTTPConnection(url.netloc)

    path = f"/_matrix/client/r0/rooms/{room_id}/send/m.room.message"
    # For uniqueness of event_id we add timestamp
    import time
    event_id = f"m{int(time.time() * 1000)}"

    # Message body
    body = {
        "msgtype": "m.text",
        "body": message
    }

    # Authorization headers
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    # Query parameters (event_id in path)
    full_path = f"{path}/{event_id}"

    if debug:
        print(_("POST {}").format(full_path))
        print(_("Payload: {}").format(body))

    try:
        conn.request("PUT", full_path, body=json.dumps(body), headers=headers)
        response = conn.getresponse()
        resp_data = response.read().decode()

        if debug:
            print(_("Response status: {}").format(response.status))
            print(_("Response data: {}").format(resp_data))

        if response.status != 200:
            raise Exception(_("Matrix server returned status {}: {}").format(response.status, resp_data))

    finally:
        conn.close()
