from __future__ import annotations

import difflib
import hashlib
from os import PathLike
from pathlib import Path
from typing import Hashable

import librosa

try:
    from pandas import DataFrame
    pandas_available = True
except ImportError:
    pandas_available = False


def make_voicevox_dataframe(audio_dir: str | PathLike) -> "DataFrame":
    """Create a ``pandas.DataFrame`` representing the timeline of audio files generated by Voicevox.

    This function takes a directory containing `.wav` files generated by Voicevox (https://voicevox.hiroshiba.jp/),
    and returns a DataFrame where each row represents an audio file, sorted by the filename.
    The DataFrame will have columns ``start_time``, ``end_time``, and ``audio_file``.

    Args:
        audio_dir:
            The directory containing `.wav` files generated by Voicevox.

    Returns:
        A DataFrame with columns `start_time`, `end_time`, and `audio_file`.

        - ``start_time``: The start time of the audio clip in seconds.
        - ``end_time``: The end time of the audio clip in seconds.
        - ``audio_file``: The path to the audio file.
    """
    if not pandas_available:
        raise ImportError("pandas is not installed")

    def get_audio_length(filename: str | PathLike) -> float:
        return librosa.get_duration(path=filename)

    wav_files = sorted(f for f in Path(audio_dir).iterdir() if f.suffix == ".wav")
    rows = []
    start_time = 0.0
    for wav_file in wav_files:
        duration = get_audio_length(wav_file)
        end_time = start_time + duration
        dic = {
            "start_time": start_time,
            "end_time": end_time,
        }
        rows.append(dic)
        start_time = end_time
    frame = DataFrame(rows)
    frame["audio_file"] = [str(p) for p in wav_files]
    return frame


def make_timeline_from_voicevox(
    audio_dir: str | PathLike,
    max_text_length: int = 25,
    extra_columns: tuple[tuple[str, Hashable], ...] = (
        ("slide", 0), ("status", "n")),
) -> "DataFrame":
    """Create a Pandas DataFrame based on text files generated by Voicevox.

    This function reads ``.txt`` files from a directory generated by Voicevox and constructs a DataFrame.
    Each row of the DataFrame corresponds to a text file and includes columns such as ``'character'``,
    ``'hash'``, and ``'text'``, as well as any additional columns specified in ``extra_columns``.

    Args:
        audio_dir:
            The directory containing ``.txt`` files generated by Voicevox.
        max_text_length:
            The maximum length of text for each entry in the ``'text'`` column.
            Strings longer than ``max_text_length`` are automatically line-breaked
            for subtitling convenience. Defaults to 25.
        extra_columns:
            Additional columns to be added to the DataFrame. Each inner tuple should contain a
            column name and a default value. Defaults to ``(("slide", 0), ("status", "n"))``.
            For example, ``extra_columns=(("slide", 0), ("status", "n"))`` will add two columns
            named ``'slide'`` and ``'status'`` with default values ``0`` and ``'n'``, respectively.

    .. note::
        The ``'character'`` column is automatically added to the DataFrame based on the filename.
        For example, if the filename is ``'001_ずんだもん（ノーマル）.txt'``, the ``'character'`` column
        will be set to ``'zunda'``.

    .. note::
        The ``'hash'`` column is automatically added to the DataFrame based on the content of the text file.
        This is used in ``merget_timeline`` to detect changes in the text file.

    Returns:
        A DataFrame with columns that may include 'character', 'hash', 'text', and any additional columns.

        - ``character``: The identifier for the Voicevox character.
        - ``hash``: A hash prefix based on the content of the text file.
        - ``text``: The text content, potentially divided into multiple parts if it exceeds ``max_text_length``.
        - Any additional columns specified in ``extra_columns``.
    """
    if not pandas_available:
        raise ImportError("pandas is not installed")

    def get_paths(src_dir: Path, ext: str) -> list[Path]:
        src_dir = Path(src_dir)
        return sorted(f for f in src_dir.iterdir() if f.suffix == ext)

    def get_hash_prefix(text):
        text_bytes = text.encode("utf-8")
        sha1_hash = hashlib.sha1(text_bytes)
        hashed_text = sha1_hash.hexdigest()
        prefix = hashed_text[:6]
        return prefix

    txt_files = get_paths(Path(audio_dir), ".txt")
    lines = []
    for txt_file in txt_files:
        raw_text = open(txt_file, "r", encoding="utf-8-sig").read()
        if raw_text == "":
            raise RuntimeError(
                f"Empty text file: {txt_file}. Please remove it and try again."
            )
        character_dict = {
            "ずんだもん": "zunda",
            "四国めたん": "metan",
            "春日部つむぎ": "tsumugi",
        }
        character = txt_file.stem.split("_")[1].split("（")[0]
        text = "\\n".join([
            raw_text[i: i + max_text_length]
            for i in range(0, len(raw_text), max_text_length)]
        )
        dic = {
            "character": character_dict[character],
            "hash": get_hash_prefix(raw_text),
            "text": text,
        }
        for column_name, default_value in extra_columns:
            dic[column_name] = default_value
        lines.append(dic)
    return DataFrame(lines)


def merge_timeline(
    old_timeline: "DataFrame",
    new_timeline: "DataFrame",
    key="hash",
    description="text",
) -> "DataFrame":
    """Merge an old DataFrame with a new DataFrame to update its timeline information.

    This function takes an old DataFrame and a new DataFrame, both generated by `make_timeline_from_voicevox`,
    and merges them to create an updated DataFrame. Rows in both DataFrames are compared based on the
    specified key column. Any discrepancies between the old and new DataFrames are flagged in the
    specified description column with ``">>>>>"`` for added rows and ``"<<<<<"`` for removed rows.

    Args:
        old_timeline:
            The old DataFrame to be updated.
        new_timeline:
            The new DataFrame to update the old one.
        key:
            The column used for comparison. Defaults to "hash".
        description:
            The column where discrepancies will be flagged. Defaults to "text".

    Returns:
        An updated DataFrame that merges the old and new timelines.

    Example:
        >>> old_timeline = pd.DataFrame({'hash': [1, 2], 'text': ['a', 'b']})
        >>> new_timeline = pd.DataFrame({'hash': [2, 3], 'text': ['b', 'c']})
        >>> merge_timeline(old_timeline, new_timeline)
    """
    if not pandas_available:
        raise ImportError("pandas is not installed")

    differ = difflib.Differ()
    diff = differ.compare(old_timeline[key].to_list(), new_timeline[key].tolist())
    result = []
    old_indices = old_timeline.index.tolist()
    new_indices = new_timeline.index.tolist()
    old_idx, new_idx = 0, 0
    for d in diff:
        if d.startswith("-"):
            row = old_timeline.iloc[old_indices[old_idx]].copy()
            row[description] = f"<<<<< {row[description]}"
            result.append(row)
            old_idx += 1
        elif d.startswith("+"):
            row = new_timeline.iloc[new_indices[new_idx]].copy()
            row[description] = f">>>>> {row[description]}"
            result.append(row)
            new_idx += 1
        else:
            result.append(old_timeline.iloc[old_indices[old_idx]])
            old_idx += 1
            new_idx += 1
    return DataFrame(result)
