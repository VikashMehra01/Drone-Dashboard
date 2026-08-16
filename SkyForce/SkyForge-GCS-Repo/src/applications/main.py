"""Launcher for SkyForge GCS - lightweight CLI to start the PyQt app."""
import sys
import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate", action="store_true", help="Auto-start simulation on launch")
    parser.add_argument("--mavlink", action="store_true", help="Auto-connect MAVLink on launch")
    args = parser.parse_args()

    try:
        from PyQt6.QtWidgets import QApplication
    except Exception as e:
        print("PyQt6 not installed. Install requirements.txt first.")
        raise

    app = QApplication(sys.argv)

    try:
        from gcs_app import GCSMainWindow
    except Exception as e:
        print("Failed to import gcs_app. Ensure dependencies and config are present.")
        raise

    win = GCSMainWindow(args)
    win.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
