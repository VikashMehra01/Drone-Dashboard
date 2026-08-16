"""
Simulated RTSP Feed
Uses FFmpeg to stream a local video file as an RTSP source for testing.

Usage:
    python simulate_feed.py --video sample_crowd.mp4 --port 8554
"""

import argparse
import subprocess
import sys


def start_rtsp_server(video_path: str, port: int = 8554):
    """Start an RTSP stream from a local video file using FFmpeg."""
    # TODO: Implement FFmpeg-based RTSP streaming
    # Example FFmpeg command:
    # ffmpeg -re -stream_loop -1 -i {video_path} \
    #   -c:v libx264 -f rtsp rtsp://0.0.0.0:{port}/live
    print(f"[STUB] Would stream {video_path} on rtsp://0.0.0.0:{port}/live")
    print("Video stream simulator not yet implemented.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulate RTSP drone feed")
    parser.add_argument("--video", type=str, default="sample_crowd.mp4")
    parser.add_argument("--port", type=int, default=8554)
    args = parser.parse_args()

    start_rtsp_server(args.video, args.port)
