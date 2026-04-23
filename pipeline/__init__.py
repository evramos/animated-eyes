"""
pipeline/__init__.py

Public surface of the pipeline package. Import everything you need from here:

    from pipeline import FrameState, AHRSState, FramePipeline
"""

from pipeline.state import AHRSState, FrameState, InputState, LidChannels
from pipeline.pipeline import FramePipeline

__all__ = [
    "AHRSState", "FrameState", "FramePipeline", "InputState", "LidChannels",
]
