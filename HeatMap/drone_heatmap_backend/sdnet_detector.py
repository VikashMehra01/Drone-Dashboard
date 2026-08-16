"""
SDNet Detector: Wraps the MovingDroneCrowd Video_Counter (SDNet) model
for density-map-based crowd counting from drone video frames.
"""
import sys
import os
import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import cv2
from PIL import Image
import torchvision.transforms as standard_transforms

# Add MovingDroneCrowd to sys.path so we can import its modules
MDC_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'MovingDroneCrowd')
sys.path.insert(0, os.path.abspath(MDC_ROOT))

from config import cfg
from model.VIC import Video_Counter
from easydict import EasyDict as edict

# ---------- Configuration matching MovingDroneCrowd settings ----------
MEAN_STD = ([117/255., 110/255., 105/255.], [67.10/255., 65.45/255., 66.23/255.])
DEN_FACTOR = 200.0

# Minimal cfg_data needed for model init
_cfg_data = edict()
_cfg_data.DEN_FACTOR = DEN_FACTOR
_cfg_data.MEAN_STD = MEAN_STD
_cfg_data.TRAIN_SIZE = (768, 1024)

class SDNetDetector:
    """
    Wraps SDNet (Video_Counter) for inference on arbitrary drone video frames.
    
    It maintains a frame buffer so that consecutive frames can be fed as pairs
    to the model, enabling temporal cross-attention (shared/inflow/outflow estimation).
    """

    def __init__(self, weights_path: str, device: str = None):
        """
        Args:
            weights_path: Path to the pre-trained .pth file.
            device: 'cuda' or 'cpu'. Auto-detected if None.
        """
        if device is None:
            self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        else:
            self.device = device

        print(f"[SDNet] Loading model on {self.device}...")
        self.model = Video_Counter(cfg, _cfg_data)
        
        # Load weights
        state_dict = torch.load(weights_path, map_location='cpu', weights_only=False)
        # Strip "module." prefix if present (from DataParallel training)
        clean_state = {}
        for k, v in state_dict.items():
            key = k
            while key.startswith("module."):
                key = key[7:]
            clean_state[key] = v
        self.model.load_state_dict(clean_state, strict=True)
        self.model.to(self.device)
        self.model.eval()
        print("[SDNet] Model loaded successfully.")

        # Image preprocessing (same as MovingDroneCrowd test pipeline)
        self.img_transform = standard_transforms.Compose([
            standard_transforms.ToTensor(),
            standard_transforms.Normalize(*MEAN_STD)
        ])

        # Frame buffer for temporal pairing
        self.prev_tensor = None

    def _preprocess_frame(self, frame_bgr: np.ndarray) -> torch.Tensor:
        """Convert an OpenCV BGR frame to a normalized tensor."""
        h, w = frame_bgr.shape[:2]
        
        # Aggressive downscaling to speed up CPU inference (targeting ~200ms)
        target_w = 480
        if w > target_w:
            target_h = int(h * (target_w / w))
            frame_resized = cv2.resize(frame_bgr, (target_w, target_h))
        else:
            frame_resized = frame_bgr

        frame_rgb = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(frame_rgb)
        tensor = self.img_transform(pil_img)
        return tensor

    def _pad_to_multiple(self, tensor: torch.Tensor, multiple: int = 32):
        """Pad H and W to be divisible by `multiple`."""
        _, _, h, w = tensor.shape
        pad_h = (multiple - h % multiple) % multiple
        pad_w = (multiple - w % multiple) % multiple
        if pad_h > 0 or pad_w > 0:
            tensor = F.pad(tensor, (0, pad_w, 0, pad_h), "constant", 0)
        return tensor

    @torch.no_grad()
    def detect(self, frame_bgr: np.ndarray):
        """
        Run SDNet on the given frame (paired with the previous frame).
        
        Returns:
            headcount (float): Estimated number of people in this frame.
            density_map (np.ndarray): 2D density map (H x W), values represent person density.
            points (list of (x, y)): Estimated head locations extracted from density map peaks.
        """
        cur_tensor = self._preprocess_frame(frame_bgr)

        # If this is the first frame, duplicate it as the "previous" frame
        if self.prev_tensor is None:
            self.prev_tensor = cur_tensor.clone()

        # Stack as a batch of 2 (frame pair: [prev, current])
        batch = torch.stack([self.prev_tensor, cur_tensor], dim=0).to(self.device)
        batch = self._pad_to_multiple(batch)

        # Run inference using test_forward (no labels needed)
        pre_global_den, pre_share_den, pre_in_out_den = self.model.test_forward(batch)

        # Extract the density map for the CURRENT frame (index 1)
        density_map = pre_global_den[1, 0].cpu().numpy()
        
        # Headcount = sum of density values
        headcount = max(0.0, density_map.sum())

        # Extract peak points from density map using local maxima
        points = self._extract_points(density_map, frame_bgr.shape[1], frame_bgr.shape[0])

        # Update the frame buffer
        self.prev_tensor = cur_tensor.clone()

        return headcount, density_map, points

    def detect_people(self, frame_bgr: np.ndarray):
        """Backwards-compatible entrypoint for map-based crowd detector."""
        headcount, _, points = self.detect(frame_bgr)
        return points, headcount

    def _extract_points(self, density_map: np.ndarray, orig_w: int, orig_h: int):
        """
        Extract (x, y) coordinates of people from the density map using local maxima.
        Returns coordinates scaled back to the original frame dimensions.
        """
        den_h, den_w = density_map.shape
        scale_x = orig_w / den_w
        scale_y = orig_h / den_h

        # Smooth and find local maxima
        smoothed = cv2.GaussianBlur(density_map.astype(np.float32), (5, 5), 0)
        
        # Threshold: keep only significant density
        threshold = max(smoothed.max() * 0.15, 0.001)
        mask = smoothed > threshold

        # Dilate to find local maxima
        kernel = np.ones((5, 5), np.uint8)
        dilated = cv2.dilate(smoothed, kernel)
        local_max = (smoothed == dilated) & mask

        # Get coordinates
        ys, xs = np.where(local_max)
        
        # Scale back to original frame coordinates
        points = []
        for x, y in zip(xs, ys):
            orig_x = int(x * scale_x)
            orig_y = int(y * scale_y)
            points.append((orig_x, orig_y))

        return points

    def reset(self):
        """Reset the frame buffer (e.g., when switching to a new video)."""
        self.prev_tensor = None
