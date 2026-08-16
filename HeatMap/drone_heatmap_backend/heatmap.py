import cv2
import numpy as np
from typing import List, Tuple

class HeatmapGenerator:
    def __init__(self, width: int, height: int, accumulation_decay: float = 0.95):
        """
        Initialize the heatmap generator for image-space heatmaps.
        
        Args:
            width: Width of the base heatmap.
            height: Height of the base heatmap.
            accumulation_decay: How much historic heat is retained over time (0.0=none, 1.0=all).
        """
        self.width = width
        self.height = height
        self.decay = accumulation_decay
        
        # Store accumulated heat as float32
        self.heat_map_acc = np.zeros((height, width), dtype=np.float32)
        
    def add_points(self, points: List[Tuple[int, int]], point_radius: int = 15, intensity: float = 1.0):
        """
        Add detected points to the heatmap accumulation.
        """
        # Apply decay to existing heatmap
        self.heat_map_acc *= self.decay
        
        # Create a temporary frame for the new points
        current_heat = np.zeros((self.height, self.width), dtype=np.float32)
        
        for x, y in points:
            if 0 <= x < self.width and 0 <= y < self.height:
                # Add a Gaussian blob or simple circle for each person
                cv2.circle(current_heat, (x, y), point_radius, intensity, -1)
                
        # Blur the point to make it a soft "blob"
        current_heat = cv2.GaussianBlur(current_heat, (point_radius*4+1, point_radius*4+1), 0)
        
        # Accumulate
        self.heat_map_acc += current_heat
        
    def get_heatmap_overlay(self, original_frame: cv2.typing.MatLike, alpha: float = 0.5) -> cv2.typing.MatLike:
        """
        Convert the accumulated heat into a colored heatmap and overlay onto the frame.
        """
        # Normalize the heat map to 0-255
        max_heat = np.max(self.heat_map_acc)
        if max_heat > 0:
            norm_heat = (self.heat_map_acc / max_heat * 255.0).astype(np.uint8)
        else:
            norm_heat = np.zeros_like(self.heat_map_acc, dtype=np.uint8)
            
        # Apply colormap (JET goes from blue to red)
        color_map = cv2.applyColorMap(norm_heat, cv2.COLORMAP_JET)
        
        # Create a mask where heat is near zero to make it transparent
        mask = norm_heat > 5 
        
        # Overlay
        overlay = original_frame.copy()
        
        # Apply overlay only to areas with heat
        for c in range(3):
            overlay[:,:,c] = np.where(mask, 
                                      overlay[:,:,c] * (1 - alpha) + color_map[:,:,c] * alpha, 
                                      overlay[:,:,c])
                                      
        return overlay
