import flet as ft
import os

class MainView:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "AI Security Center"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.window.maximized = True
        self.page.bgcolor = "black"

        # Title
        self.header = ft.Text("AI Security Center", size=30, weight=ft.FontWeight.BOLD, color="white")
        
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
                ft.Container(content=self.header, padding=10),
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
