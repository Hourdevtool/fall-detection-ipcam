import flet as ft
import os

class MainView:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "AI Security Center"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.window.maximized = True
        self.page.bgcolor = "black"

        # Title with settings button
        self.header_title = ft.Text("AI Security Center", size=30, weight=ft.FontWeight.BOLD, color="white")
        self.settings_button = ft.IconButton(
            icon="settings",
            icon_color="white",
            icon_size=24,
            tooltip="ตั้งค่า Username & Password",
            on_click=None
        )
        self.header_row = ft.Row(
            controls=[self.header_title, self.settings_button],
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

        self.page.add(
            ft.Column([
                ft.Container(content=self.header_row, padding=10),
                self.content_container
            ], expand=True)
        )

        # Dictionary to store Image controls per IP
        self.camera_images = {}

    def update_grid(self, base64_frames):
        needs_page_update = False

        for ip, b64 in base64_frames.items():
            if ip not in self.camera_images:
                # Create a new Image control
                img = ft.Image(src=f"data:image/jpeg;base64,{b64}", fit="contain", gapless_playback=True) # type: ignore
                card = ft.Container(
                    content=ft.Stack([
                        img,
                        ft.Container(
                            content=ft.Text(f"IP: {ip}", color="white", size=12),
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
                self.camera_grid.controls.append(card)
                needs_page_update = True
                
                # Switch content container from text to grid if this is the first camera
                if self.content_container.content != self.camera_grid:
                    self.content_container.content = self.camera_grid
                    self.content_container.alignment = None
            else:
                # Update existing image
                self.camera_images[ip].src = f"data:image/jpeg;base64,{b64}"

        # อัพเดต UI — เมื่อ run บน Flet event loop (page.run_task) จะ push ไป client ทันที
        self.page.update()

    def show_naming_dialog(self, ip, temp_image_path, on_save_callback):
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
                ft.TextButton("บันทึกชื่อกล้อง", on_click=save_clicked)
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            modal=True
        )

        self.page.show_dialog(dialog)

    def show_settings_dialog(self, current_username, current_password, on_save_callback):
        username_field = ft.TextField(
            label="Username",
            hint_text="เช่น admin",
            value=current_username,
            prefix_icon="person",
            border_color="white24",
            focused_border_color="blue",
            text_style=ft.TextStyle(color="white"),
            label_style=ft.TextStyle(color="white54"),
            hint_style=ft.TextStyle(color="white30"),
            expand=True
        )

        def toggle_password_visibility(e):
            password_field.password = not password_field.password
            password_field.reveal_password = not password_field.reveal_password
            eye_button.icon = "visibility_off" if password_field.password else "visibility"
            self.page.update()

        eye_button = ft.IconButton(
            icon="visibility_off",
            icon_color="white54",
            on_click=toggle_password_visibility
        )

        password_field = ft.TextField(
            label="Password",
            value=current_password,
            prefix_icon="lock",
            password=True,
            can_reveal_password=False,
            border_color="white24",
            focused_border_color="blue",
            text_style=ft.TextStyle(color="white"),
            label_style=ft.TextStyle(color="white54"),
            suffix=eye_button,
            expand=True
        )

        def save_clicked(e):
            user = username_field.value.strip() if username_field.value else ""
            pwd = password_field.value.strip() if password_field.value else ""

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

            on_save_callback(user, pwd)
            
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
                ft.Icon("settings", color="blue", size=28),
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
