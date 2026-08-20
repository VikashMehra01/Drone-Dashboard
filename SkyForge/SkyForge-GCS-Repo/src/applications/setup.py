"""
Setup configuration for SkyForge GCS
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read version
version_file = Path("version.txt")
version = version_file.read_text().strip() if version_file.exists() else "0.1.0"

# Read long description
readme_file = Path("README.md")
long_description = readme_file.read_text() if readme_file.exists() else ""

setup(
    name="skyforge-gcs",
    version=version,
    description="SkyForge GCS - Real-time field orthomosaic mapping application",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="SkyForge",
    author_email="ops@skyforge.local",
    url="https://github.com/SkyForge/gcs",
    license="Proprietary",
    
    packages=find_packages(),
    package_data={
        "": ["*.json", "*.md", "*.txt"],
    },
    
    install_requires=[
        "PyQt6>=6.2",
        "opencv-python>=4.5",
        "numpy>=1.23",
        "Pillow>=8.3",
        "scipy>=1.7",
        "pymavlink>=2.4",
        "requests>=2.28",
        "pyproj>=3.3",
        "matplotlib>=3.5",
    ],
    
    extras_require={
        "dev": [
            "pyinstaller>=6.0",
            "pytest>=7.0",
        ],
    },
    
    python_requires=">=3.10",
    
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "License :: Other/Proprietary License",
        "Operating System :: Microsoft :: Windows",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Scientific/Engineering :: Image Processing",
    ],
    
    entry_points={
        "console_scripts": [
            "skyforge-gcs=main:main",
        ],
    },
)
