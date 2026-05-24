import flet as ft
from src.mvc.controllers.main_controller import MainController

def main(page: ft.Page):
    controller = MainController(page)
    controller.start()

if __name__ == "__main__":
    import multiprocessing
    # Required for Windows multiprocessing
    multiprocessing.freeze_support()
    ft.app(target=main)
