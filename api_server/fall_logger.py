import cv2
import os
import time
import threading

from api_server.database import insert_fall_event, ensure_snapshots_dir

SNAPSHOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fall_snapshots")

# Cooldown to prevent duplicate events for the same fall
_last_log_time: dict[str, float] = {}
_log_lock = threading.Lock()
COOLDOWN_SECONDS = 30


def log_fall_event(camera_ip: str, camera_name: str, frame, detected_at: float | None = None):
    """
    Log a fall event: save snapshot JPEG + insert into database.
    Thread-safe with cooldown to prevent spam.
    
    Args:
        camera_ip: IP address of the camera
        camera_name: Human-readable camera name
        frame: numpy array (BGR) of the fall frame
        detected_at: timestamp of detection (defaults to now)
    """
    now = time.time()
    if detected_at is None:
        detected_at = now

    with _log_lock:
        last_time = _last_log_time.get(camera_ip, 0)
        if now - last_time < COOLDOWN_SECONDS:
            return  # Skip — cooldown active
        _last_log_time[camera_ip] = now

    ensure_snapshots_dir()

    # Generate filename
    time_str = time.strftime("%Y%m%d_%H%M%S", time.localtime(detected_at))
    safe_ip = camera_ip.replace(".", "_")
    filename = f"{time_str}_{safe_ip}.jpg"
    filepath = os.path.join(os.path.abspath(SNAPSHOTS_DIR), filename)

    # Save snapshot
    try:
        if frame is not None:
            cv2.imwrite(filepath, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            print(f"📸 Fall snapshot saved: {filepath}")
        else:
            filename = ""
            print(f"⚠️ No frame to save for fall event at {camera_name}")
    except Exception as e:
        print(f"❌ Error saving snapshot: {e}")
        filename = ""

    # Insert into database
    try:
        event = insert_fall_event(
            camera_ip=camera_ip,
            camera_name=camera_name,
            snapshot_filename=filename,
            detected_at=detected_at,
            duration_seconds=0.0,
        )
        print(f"🗃️ Fall event logged: #{event['id']} — {camera_name} at {time_str}")
        
        # Send LINE Alert
        send_line_alert(camera_name, time_str)
    except Exception as e:
        print(f"❌ Error logging fall event: {e}")

def send_line_alert(camera_name, time_str):
    import json
    import os
    from linebot import LineBotApi
    from linebot.models import TextSendMessage
    from linebot.exceptions import LineBotApiError

    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "config.json")
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config = json.load(f)
            bot_token = config.get("line_bot_token", "").strip()
            group_id = config.get("line_group_id", "").strip()
    except Exception:
        return

    if not bot_token or not group_id:
        return

    line_bot_api = LineBotApi(bot_token)
    try:
        line_bot_api.push_message(
            group_id,
            TextSendMessage(text=f"🚨 แจ้งเตือนการล้ม!\nกล้อง: {camera_name}\nเวลา: {time_str}")
        )
    except LineBotApiError as e:
        print(f"❌ LineBotApiError: {e}")
    except Exception as e:
        print(f"❌ Error sending LINE alert: {e}")
