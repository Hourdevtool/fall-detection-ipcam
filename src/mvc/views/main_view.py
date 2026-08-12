import flet as ft
import os

# 1x1 transparent GIF — used as placeholder when no frame is available yet
TRANSPARENT_PIXEL = "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"

def is_valid_ip(ip_str):
    if not isinstance(ip_str, str):
        return False
    parts = ip_str.split('.')
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)

class MainView:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "AI Security Center"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.window.maximized = True
        self.page.bgcolor = "black"

        # Title with settings and code buttons
        self.header_title = ft.Text("AI Security Center", size=30, weight=ft.FontWeight.BOLD, color="white")
        
        self.show_code_button = ft.IconButton(
            icon=ft.Icons.QR_CODE,
            icon_color="amber",
            icon_size=24,
            tooltip="แสดงรหัสเชื่อมต่อ (Pairing Code)",
            visible=False,
            on_click=None
        )
        
        self.intruder_toggle = ft.Switch(label="Intruder Detection", value=False, label_position=ft.LabelPosition.LEFT)
        self.register_button = ft.ElevatedButton("Register Family", icon=ft.Icons.PERSON_ADD, on_click=None)
        
        self.settings_button = ft.IconButton(
            icon=ft.Icons.SETTINGS,
            icon_color="white",
            icon_size=24,
            tooltip="ตั้งค่า Username & Password",
            on_click=None
        )
        self.header_row = ft.Row(
            controls=[self.header_title, ft.Row([self.intruder_toggle, self.register_button, self.show_code_button, self.settings_button])],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN
        )
        
        # Grid for cameras
        self.camera_grid = ft.GridView(
            expand=1,
            runs_count=5,
            max_extent=640,
            child_aspect_ratio=1.77, # 16:9 roughly
            spacing=10,
            run_spacing=10,
        )
        
        # A status message when no cameras are found yet
        self.status_text = ft.Text("Radar Scanning...", size=24, color="white54")
        
        # Container for the grid vs status
        self.content_container = ft.Container(
            content=self.status_text,
            alignment=ft.Alignment(0, 0), # center

            expand=True
        )

        # Pairing code container (initially hidden or visible)
        self.pair_code_text = ft.Text("", size=40, weight=ft.FontWeight.W_900, color="amber400")
        self.pairing_banner = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.PHONELINK_SETUP, color="amber400", size=28),
                    ft.Text("รหัสสำหรับเชื่อมต่อแอปมือถือ (Pairing Code)", size=18, color="white", weight=ft.FontWeight.BOLD),
                ], alignment=ft.MainAxisAlignment.CENTER),
                ft.Container(
                    content=self.pair_code_text,
                    bgcolor="black45",
                    padding=15,
                    border_radius=8,
                ),
                ft.Text("นำรหัส 6 หลักนี้ไปกรอกใน Web App เพื่อดูภาพจากกล้อง", size=14, color="white70"),
            ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
            bgcolor="#1A1A1A",
            border=ft.Border(
                top=ft.BorderSide(2, "amber700"),
                right=ft.BorderSide(2, "amber700"),
                bottom=ft.BorderSide(2, "amber700"),
                left=ft.BorderSide(2, "amber700")
            ),
            border_radius=15,
            padding=20,
            margin=ft.Margin(left=10, right=10, bottom=20, top=10),
            visible=False # Hidden by default, controller will show if not paired
        )

        self.page.add(
            ft.Column([
                ft.Container(content=self.header_row, padding=10),
                self.pairing_banner,
                self.content_container
            ], expand=True)
        )

        # Dictionary to store Image controls per IP
        self.camera_images = {}
        self.camera_overlays = {}

    def show_pairing_code(self, code):
        self.pair_code_text.value = f" {code} "
        self.pairing_banner.visible = True
        self.page.update()

    def hide_pairing_code(self):
        self.pairing_banner.visible = False
        self.page.update()


    def update_grid(self, base64_frames, active_cameras, camera_names):
        needs_page_update = False

        # Clean up any non-IP keys (such as MAC addresses) that might be in self.camera_images
        invalid_keys = [k for k in list(self.camera_images.keys()) if not is_valid_ip(k)]
        if invalid_keys:
            for k in invalid_keys:
                del self.camera_images[k]
                if k in self.camera_overlays:
                    del self.camera_overlays[k]
            self.camera_grid.controls.clear()
            self.camera_images.clear()
            self.camera_overlays.clear()
            needs_page_update = True

        # Only iterate over actual IP addresses
        valid_active = {ip for ip in active_cameras.keys() if is_valid_ip(ip)}
        valid_names = {ip for ip in camera_names.keys() if is_valid_ip(ip)}
        all_ips = valid_active | valid_names

        for ip in all_ips:
            b64 = base64_frames.get(ip)
            is_active = active_cameras.get(ip, False)
            cam_name = camera_names.get(ip, ip)

            if ip not in self.camera_images:
                # Create a new Image control
                # If there's no frame yet, use a 1x1 transparent GIF base64
                img_src = f"data:image/jpeg;base64,{b64}" if b64 else f"data:image/gif;base64,{TRANSPARENT_PIXEL}"
                img = ft.Image(src=img_src, fit="contain", gapless_playback=True) # type: ignore
                
                offline_overlay = ft.Container(
                    content=ft.Column([
                        ft.ProgressRing(width=30, height=30, stroke_width=3, color="amber"),
                        ft.Text("กำลังเชื่อมต่อใหม่...", color="amber", size=12, weight=ft.FontWeight.BOLD)
                    ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    bgcolor="#B0000000", # semi-transparent black
                    alignment=ft.Alignment(0, 0),
                    visible=not is_active or not b64
                )
                
                card = ft.Container(
                    content=ft.Stack([
                        img,
                        offline_overlay,
                        ft.Container(
                            content=ft.Text(f"{cam_name} ({ip})", color="white", size=12, weight=ft.FontWeight.BOLD),
                            bgcolor="#80000000",
                            padding=5,
                            border_radius=5,
                            alignment=ft.Alignment(-1, -1) # top_left
                        )
                    ]),
                    border_radius=10,
                    bgcolor="#212121",
                    padding=5
                )
                self.camera_images[ip] = img
                self.camera_overlays[ip] = offline_overlay
                self.camera_grid.controls.append(card)
                needs_page_update = True
                
                # Switch content container from text to grid if this is the first camera
                if self.content_container.content != self.camera_grid:
                    self.content_container.content = self.camera_grid
                    self.content_container.alignment = None
            else:
                # Update existing image and visibility of overlay
                if b64:
                    self.camera_images[ip].src = f"data:image/jpeg;base64,{b64}"
                    try:
                        self.camera_images[ip].update()
                    except Exception:
                        pass
                
                show_offline = not is_active or not b64
                if self.camera_overlays[ip].visible != show_offline:
                    self.camera_overlays[ip].visible = show_offline
                    needs_page_update = True

        if needs_page_update:
            self.page.update()

    def show_naming_dialog(self, ip, temp_image_path, on_save_callback, on_cancel_callback=None):
        # We need a text field for the name
        name_input = ft.TextField(
            label=f"ตั้งชื่อกล้อง IP: {ip}",
            hint_text="เช่น ห้องนั่งเล่น, โรงจอดรถ",
            width=300,
        )

        def save_clicked(e):
            cam_name = name_input.value.strip() if name_input.value else ip
            try:
                self.page.pop_dialog()
            except Exception:
                pass
            if temp_image_path and os.path.exists(temp_image_path):
                try:
                    os.remove(temp_image_path)
                except:
                    pass
            on_save_callback(ip, cam_name)

        def cancel_clicked(e):
            try:
                self.page.pop_dialog()
            except Exception:
                pass
            if temp_image_path and os.path.exists(temp_image_path):
                try:
                    os.remove(temp_image_path)
                except:
                    pass
            if on_cancel_callback:
                on_cancel_callback(ip)

        preview_img = ft.Image(
            src=temp_image_path,
            width=400,
            height=250,
            fit=ft.BoxFit.CONTAIN,
            border_radius=10,
        ) if temp_image_path else ft.Container(height=250)

        dialog = ft.AlertDialog(
            title=ft.Text("🛡️ ตรวจพบกล้องใหม่!"),
            content=ft.Column([
                ft.Text("กรุณาระบุตำแหน่ง/ชื่อของกล้องตัวนี้ เพื่อการแจ้งเตือนที่ชัดเจน"),
                preview_img,
                name_input
            ], tight=True, alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            actions=[
                ft.TextButton("ข้าม / ตั้งทีหลัง", on_click=cancel_clicked),
                ft.ElevatedButton("บันทึกชื่อกล้อง", on_click=save_clicked)
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            modal=True
        )

        self.page.show_dialog(dialog)

    def show_settings_dialog(self, current_username, current_password, current_line_token, current_line_group, on_save_callback):
        username_field = ft.TextField(
            label="Username",
            hint_text="เช่น admin",
            value=current_username,
            prefix_icon=ft.Icons.PERSON,
            border_color="white24",
            focused_border_color="blue",
            text_style=ft.TextStyle(color="white"),
            label_style=ft.TextStyle(color="white54"),
            hint_style=ft.TextStyle(color="white30"),
            expand=True
        )

        def toggle_password_visibility(e):
            password_field.password = not password_field.password
            eye_button.icon = ft.Icons.VISIBILITY_OFF if password_field.password else ft.Icons.VISIBILITY
            self.page.update()

        eye_button = ft.IconButton(
            icon=ft.Icons.VISIBILITY_OFF,
            icon_color="white54",
            on_click=toggle_password_visibility
        )

        password_field = ft.TextField(
            label="Password",
            value=current_password,
            prefix_icon=ft.Icons.LOCK,
            password=True,
            can_reveal_password=False,
            border_color="white24",
            focused_border_color="blue",
            text_style=ft.TextStyle(color="white"),
            label_style=ft.TextStyle(color="white54"),
            suffix=eye_button,
            expand=True
        )

        line_token_field = ft.TextField(
            label="LINE Channel Access Token",
            hint_text="ใส่ Token ของ Messaging API",
            value=current_line_token,
            prefix_icon=ft.Icons.CHAT,
            border_color="white24",
            focused_border_color="green",
            text_style=ft.TextStyle(color="white"),
            label_style=ft.TextStyle(color="white54"),
            hint_style=ft.TextStyle(color="white30"),
            expand=True
        )

        line_group_field = ft.TextField(
            label="LINE Group ID / User ID",
            hint_text="เช่น Cxxxxxx หรือ Uxxxxxx",
            value=current_line_group,
            prefix_icon=ft.Icons.GROUP,
            border_color="white24",
            focused_border_color="green",
            text_style=ft.TextStyle(color="white"),
            label_style=ft.TextStyle(color="white54"),
            hint_style=ft.TextStyle(color="white30"),
            expand=True
        )

        def save_clicked(e):
            user = username_field.value.strip() if username_field.value else ""
            pwd = password_field.value.strip() if password_field.value else ""
            l_token = line_token_field.value.strip() if line_token_field.value else ""
            l_group = line_group_field.value.strip() if line_group_field.value else ""

            if not user or not pwd:
                snack_bar = ft.SnackBar(
                    content=ft.Text("❌ กรุณากรอก Username และ Password ให้ครบถ้วน", color="white"),
                    bgcolor="#D32F2F"
                )
                self.page.overlay.append(snack_bar)
                snack_bar.open = True
                self.page.update()
                return

            try:
                self.page.pop_dialog()
            except Exception:
                pass

            on_save_callback(user, pwd, l_token, l_group)
            
            snack_bar = ft.SnackBar(
                content=ft.Text("💾 บันทึกการตั้งค่าสำเร็จ ตัวสแกนจะใช้บัญชีใหม่นี้ทันที", color="white"),
                bgcolor="#388E3C"
            )
            self.page.overlay.append(snack_bar)
            snack_bar.open = True
            self.page.update()

        def cancel_clicked(e):
            try:
                self.page.pop_dialog()
            except Exception:
                pass

        dialog = ft.AlertDialog(
            title=ft.Row([
                ft.Icon(ft.Icons.SETTINGS, color="blue", size=28),
                ft.Text("ตั้งค่าบัญชีกล้อง IP Camera", size=20, weight=ft.FontWeight.BOLD, color="white")
            ], spacing=10),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(
                        "ระบุ Username และ Password สำหรับสแกนและดึงสตรีมภาพของกล้องในเครือข่ายวง LAN เดียวกันผ่าน ONVIF/RTSP",
                        size=14,
                        color="white70"
                    ),
                    ft.Container(height=10),
                    username_field,
                    ft.Container(height=10),
                    password_field,
                    ft.Divider(color="white24"),
                    ft.Text(
                        "ตั้งค่าการแจ้งเตือน LINE Messaging API",
                        size=14,
                        color="white70"
                    ),
                    ft.Container(height=10),
                    line_token_field,
                    ft.Container(height=10),
                    line_group_field,
                ], tight=True, width=420),
                padding=10
            ),
            actions=[
                ft.TextButton("ยกเลิก", on_click=cancel_clicked, style=ft.ButtonStyle(color="white54")),
                ft.ElevatedButton("บันทึก", on_click=save_clicked, style=ft.ButtonStyle(color="white", bgcolor="blue")),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            modal=True
        )

        self.page.show_dialog(dialog)

    def show_registration_dialog(self, start_webcam_callback, capture_callback, close_callback):
        transparent_pixel = "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
        self.reg_image = ft.Image(
            src=f"data:image/gif;base64,{transparent_pixel}",
            width=640,
            height=480,
            fit="contain",
            gapless_playback=True
        ) # type: ignore
        self.reg_name_input = ft.TextField(label="ชื่อสมาชิกครอบครัว", hint_text="ระบุชื่อ (ภาษาอังกฤษ/ไทย)")
        self.reg_phone_input = ft.TextField(label="เบอร์โทรศัพท์", hint_text="เช่น 0812345678")
        self.reg_gender_dropdown = ft.Dropdown(
            label="เพศ",
            options=[
                ft.dropdown.Option("ชาย"),
                ft.dropdown.Option("หญิง"),
                ft.dropdown.Option("อื่นๆ")
            ],
            width=200
        )
        self.reg_status_text = ft.Text("")
        
        def on_capture(angle):
            name = self.reg_name_input.value.strip() if self.reg_name_input.value else ""
            phone = self.reg_phone_input.value.strip() if self.reg_phone_input.value else ""
            gender = self.reg_gender_dropdown.value if self.reg_gender_dropdown.value else ""
            if not name:
                self.reg_status_text.value = "กรุณาระบุชื่อก่อนบันทึกภาพ"
                self.reg_status_text.color = "red"
                self.page.update()
                return
            capture_callback(name, angle, self.reg_status_text, phone, gender)
            
        def on_close(e):
            try:
                self.page.pop_dialog()
            except Exception:
                pass
            close_callback()

        dialog = ft.AlertDialog(
            title=ft.Text("ลงทะเบียนสมาชิกครอบครัว"),
            content=ft.Column([
                self.reg_name_input,
                ft.Row([self.reg_phone_input, self.reg_gender_dropdown], alignment=ft.MainAxisAlignment.CENTER),
                self.reg_image,
                self.reg_status_text,
                ft.Row([
                    ft.ElevatedButton("ถ่ายภาพใบหน้า (Capture)", on_click=lambda e: on_capture("front"))
                ], alignment=ft.MainAxisAlignment.CENTER)
            ], tight=True, alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            actions=[
                ft.TextButton("ปิด", on_click=on_close)
            ],
            on_dismiss=on_close,
            modal=True
        )
        self.page.show_dialog(dialog)
        start_webcam_callback(self.reg_image)
