"""Run once while building the image, so the worker never needs the network for its models."""

from fastembed import ImageEmbedding, TextEmbedding
from faster_whisper.utils import download_model

from . import config, tagging

download_model(config.WHISPER_MODEL, cache_dir=config.MODELS_DIR)
ImageEmbedding(tagging.VISION_MODEL, cache_dir=config.MODELS_DIR)
TextEmbedding(tagging.TEXT_MODEL, cache_dir=config.MODELS_DIR)
