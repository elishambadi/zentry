"""
SVG decoration library for generating random, publication-quality decorative elements.
Useful for notebook cover pages, dividers, and background accents.
"""

import random
import math
from typing import Tuple, List


class SVGDecorator:
    """Generate random SVG decorative elements for publication styling."""

    def __init__(self, seed: int = None):
        """Initialize with optional seed for reproducible patterns."""
        if seed is not None:
            random.seed(seed)

    @staticmethod
    def _random_color(palette: str = "neutral") -> str:
        """Return a random color from a palette."""
        palettes = {
            "neutral": ["#1f2937", "#374151", "#4b5563", "#6b7280", "#9ca3af"],
            "warm": ["#92400e", "#b45309", "#d97706", "#f59e0b", "#fbbf24"],
            "cool": ["#082f49", "#0c4a6e", "#0369a1", "#0284c7", "#38bdf8"],
            "accent": ["#4f46e5", "#6366f1", "#8b5cf6", "#a855f7", "#d946ef"],
        }
        return random.choice(palettes.get(palette, palettes["neutral"]))

    @staticmethod
    def geometric_grid(width: int = 400, height: int = 300, pattern: str = "circles") -> str:
        """Generate a geometric grid pattern."""
        svg = f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">'
        svg += f'<rect width="{width}" height="{height}" fill="none"/>'

        if pattern == "circles":
            spacing = 40
            radius = 6
            color = SVGDecorator._random_color("neutral")
            opacity = random.uniform(0.3, 0.6)

            for x in range(0, width + spacing, spacing):
                for y in range(0, height + spacing, spacing):
                    offset_x = random.randint(-10, 10)
                    offset_y = random.randint(-10, 10)
                    svg += f'<circle cx="{x + offset_x}" cy="{y + offset_y}" r="{radius}" fill="{color}" opacity="{opacity}"/>'

        elif pattern == "lines":
            color = SVGDecorator._random_color("cool")
            for i in range(0, width + height, 50):
                angle = random.uniform(-30, 30)
                svg += f'<line x1="0" y1="{i}" x2="{width}" y2="{i + angle * 2}" stroke="{color}" stroke-width="1" opacity="0.4"/>'

        elif pattern == "waves":
            color = SVGDecorator._random_color("accent")
            amplitude = random.randint(10, 30)
            frequency = random.uniform(0.02, 0.05)
            svg += f'<path d="M 0 {height // 2}'
            for x in range(0, width + 10, 10):
                y = height // 2 + amplitude * math.sin(x * frequency)
                svg += f" L {x} {y}"
            svg += f'" stroke="{color}" stroke-width="2" fill="none" opacity="0.5"/>'

        elif pattern == "dots":
            color = SVGDecorator._random_color("warm")
            density = random.randint(80, 150)
            for _ in range(density):
                x = random.randint(0, width)
                y = random.randint(0, height)
                size = random.uniform(1, 3)
                svg += f'<circle cx="{x}" cy="{y}" r="{size}" fill="{color}" opacity="{random.uniform(0.4, 0.8)}"/>'

        svg += "</svg>"
        return svg

    @staticmethod
    def corner_accent(width: int = 150, height: int = 150, corner: str = "top-right") -> str:
        """Generate a corner accent element."""
        svg = f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg" style="overflow: visible;">'

        color = SVGDecorator._random_color("accent")
        opacity = random.uniform(0.15, 0.3)

        # Generate flowing lines
        points = random.randint(5, 10)
        path = "M"
        for i in range(points):
            x = (width / points) * i + random.randint(-20, 20)
            y = (height / points) * i + random.randint(-20, 20)
            if i == 0:
                path += f" {x} {y}"
            else:
                path += f" Q {x - 20} {y - 20}, {x} {y}"

        svg += f'<path d="{path}" stroke="{color}" stroke-width="2" fill="none" opacity="{opacity}"/>'

        # Add decorative circles
        for _ in range(random.randint(3, 6)):
            x = random.randint(0, width)
            y = random.randint(0, height)
            r = random.uniform(1, 5)
            svg += f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}" opacity="{random.uniform(0.2, 0.4)}"/>'

        svg += "</svg>"
        return svg

    @staticmethod
    def border_frame(width: int = 800, height: int = 600, thickness: int = 2) -> str:
        """Generate a decorative border frame."""
        svg = f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">'

        color = SVGDecorator._random_color("neutral")
        inner_margin = 40

        # Outer rectangle
        svg += f'<rect x="{inner_margin}" y="{inner_margin}" width="{width - 2 * inner_margin}" height="{height - 2 * inner_margin}" stroke="{color}" stroke-width="{thickness}" fill="none" opacity="0.5"/>'

        # Inner accent line
        svg += f'<rect x="{inner_margin + thickness + 5}" y="{inner_margin + thickness + 5}" width="{width - 2 * (inner_margin + thickness + 5)}" height="{height - 2 * (inner_margin + thickness + 5)}" stroke="{color}" stroke-width="1" fill="none" opacity="0.2"/>'

        # Corner flourishes
        flourish_size = 15
        corners = [
            (inner_margin, inner_margin),  # top-left
            (width - inner_margin, inner_margin),  # top-right
            (inner_margin, height - inner_margin),  # bottom-left
            (width - inner_margin, height - inner_margin),  # bottom-right
        ]

        for x, y in corners:
            svg += f'<circle cx="{x}" cy="{y}" r="{flourish_size // 2}" fill="none" stroke="{color}" stroke-width="1" opacity="0.3"/>'

        svg += "</svg>"
        return svg

    @staticmethod
    def abstract_blob(width: int = 300, height: int = 300) -> str:
        """Generate an abstract blob shape."""
        svg = f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">'

        color = SVGDecorator._random_color("cool")
        cx, cy = width // 2, height // 2
        base_radius = min(width, height) // 3

        # Create irregular blob path
        points = []
        num_points = random.randint(6, 12)
        for i in range(num_points):
            angle = (360 / num_points) * i
            radius = base_radius * random.uniform(0.7, 1.2)
            rad = math.radians(angle)
            x = cx + radius * math.cos(rad)
            y = cy + radius * math.sin(rad)
            points.append((x, y))

        # Generate Bezier curve path
        path = f"M {points[0][0]} {points[0][1]}"
        for i, (x, y) in enumerate(points[1:]):
            next_point = points[(i + 2) % len(points)]
            path += f" Q {x} {y} {next_point[0]} {next_point[1]}"

        svg += f'<path d="{path}" fill="{color}" opacity="0.15" stroke="{color}" stroke-width="1" stroke-opacity="0.3"/>'
        svg += "</svg>"
        return svg
