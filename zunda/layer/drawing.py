import sys
from typing import Callable, Hashable, NamedTuple, Optional, Sequence, Union

import numpy as np
from PySide6.QtCore import QCoreApplication, QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QFontMetrics,
                           QImage, QPainter, QPainterPath, QPen)
from PySide6.QtWidgets import QApplication

from zunda.attribute import Attribute, AttributesMixin, AttributeType
from zunda.imgproc import qimage_to_numpy
from zunda.layer.mixin import TimelineMixin


class FillProperty(NamedTuple):

    color: tuple[int, int, int] = (0, 0, 0)
    opacity: float = 1.


class StrokeProperty(NamedTuple):

    color: tuple[int, int, int] = (255, 255, 255)
    width: float = 1.
    opacity: float = 1.


def _get_max_stroke(contents: Sequence[Union[FillProperty, StrokeProperty]]) -> float:
    strokes = [c.width for c in contents if isinstance(c, StrokeProperty)]
    return float(max(strokes)) if 0 < len(strokes) else 0.


class Rectangle(AttributesMixin):

    def __init__(
            self,
            size: tuple[float, float] = (100., 100.),
            radius: float = 0.,
            color: Optional[tuple[int, int, int]] = None,
            contents: Sequence[Union[FillProperty, StrokeProperty]] = (),
            duration: float = 1.):
        self.size = Attribute(size, value_type=AttributeType.VECTOR2D)
        self.radius = Attribute(radius, value_type=AttributeType.SCALAR)
        if color is None:
            self.contents = contents
        else:
            self.contents = (FillProperty(color=color),)
        self.duration = duration

    def __call__(self, time: float) -> Optional[np.ndarray]:
        if len(self.contents) == 0:
            return None
        size = [float(x) for x in self.size(time)]
        w, h = float(size[0]), float(size[1])
        radius = float(self.radius(time))

        eps = 1.
        max_stroke = _get_max_stroke(self.contents)
        W = np.floor(w + max_stroke + 2 * eps)
        H = np.floor(h + max_stroke + 2 * eps)
        image = QImage(W, H, QImage.Format.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(eps + max_stroke / 2, eps + max_stroke / 2, w, h)
        for c in self.contents:
            if isinstance(c, FillProperty):
                r, g, b = c.color
                a = round(255 * c.opacity)
                brush = QBrush(QColor(b, g, r, a))
                painter.setBrush(brush)
                painter.drawRoundedRect(rect, radius, radius, mode=Qt.SizeMode.AbsoluteSize)
            elif isinstance(c, StrokeProperty):
                r, g, b = c.color
                a = round(255 * c.opacity)
                painter_path = QPainterPath()
                painter_path.addRoundedRect(rect, radius, radius, mode=Qt.SizeMode.AbsoluteSize)
                painter.setPen(QPen(QColor(b, g, r, a), c.width))
                painter.drawPath(painter_path)
            else:
                raise ValueError(f"Invalid content type: {type(c)}")
        painter.end()
        return qimage_to_numpy(image)


class Text(AttributesMixin):

    @classmethod
    def from_timeline(cls, start_times: Sequence[float], end_times: Sequence[float], texts: Sequence[str], **kwargs):
        assert len(start_times) == len(texts)

        class TextWithTime(TimelineMixin):
            def __init__(self):
                super().__init__(start_times, end_times)
                self.texts = texts

            def __call__(self, time: float) -> str:
                idx = self.get_state(time)
                if idx >= 0:
                    return texts[idx]
                else:
                    return ''

        kwargs['duration'] = max(end_times)
        return cls(text=TextWithTime(), **kwargs)

    def __init__(
            self,
            text: Union[str, Callable[[float], str]],
            font: str,
            font_size: float,
            color: Optional[tuple[int, int, int]] = None,
            contents: Sequence[Union[FillProperty, StrokeProperty]] = (),
            line_spacing: Optional[int] = None,
            duration: float = 1.):
        self.text = text
        self.font = font
        self.font_size = Attribute(font_size, value_type=AttributeType.SCALAR)
        if color is None:
            self.contents = contents
        else:
            self.contents = (FillProperty(color=color),)
        self.line_spacing = line_spacing
        self.duration = duration
        if QCoreApplication.instance() is None:
            self._app = QApplication(sys.argv[:1])
        self._fontid = QFontDatabase.addApplicationFont(self.font)
        self._font_family = QFontDatabase.applicationFontFamilies(self._fontid)

    def get_text(self, time: float = 0.) -> str:
        if isinstance(self.text, str):
            return self.text
        elif callable(self.text):
            return self.text(time)
        else:
            raise ValueError(f"Invalid text type: {type(self.text)}")

    def get_size(self, time: float = 0.) -> tuple[int, int]:
        qfont = QFont(self._font_family, round(float(self.font_size(time))))
        metrics = QFontMetrics(qfont)
        text = self.get_text(time)
        lines = text.split('\n')
        W, H = 0, 0
        for i, line in enumerate(lines):
            rect = metrics.boundingRect(line)
            W = max(W, rect.width() - rect.x())
            if self.line_spacing is None or i == len(lines) - 1:
                H += (rect.height() - rect.y())
            else:
                H += self.line_spacing
        return (W, H)

    def get_key(self, time: float) -> tuple[str, Hashable]:
        key = super().get_key(time)
        return (self.get_text(time), key)

    def __call__(self, time: float) -> Optional[np.ndarray]:
        if len(self.contents) == 0:
            return None
        text = self.get_text(time)
        if text is None or text == '':
            return None
        size = self.get_size(time)
        w, h = float(size[0]), float(size[1])

        eps = 1.
        max_stroke = _get_max_stroke(self.contents)
        W = np.floor(w + max_stroke + 2 * eps)
        H = np.floor(h + max_stroke + 2 * eps)
        image = QImage(W, H, QImage.Format.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        qfont = QFont(self._font_family, round(float(self.font_size(time))))
        metrics = QFontMetrics(qfont)
        painter.setFont(qfont)
        lines = text.split('\n')
        for c in self.contents:
            if isinstance(c, FillProperty):
                r, g, b = c.color
                a = round(255 * c.opacity)
                painter.setPen(QColor(b, g, r, a))
                cursor_y = eps
                for i, line in enumerate(lines):
                    rect = metrics.boundingRect(line)
                    if i == 0:
                        cursor_y += rect.height()
                    elif self.line_spacing is None:
                        cursor_y += (rect.height() - rect.y())
                    else:
                        cursor_y += self.line_spacing
                    painter.drawText(QPointF(0, cursor_y), line)
            elif isinstance(c, StrokeProperty):
                r, g, b = c.color
                a = round(255 * c.opacity)
                painter.setPen(QPen(QColor(b, g, r, a), c.width))
                painter_path = QPainterPath()
                cursor_y = eps
                for i, line in enumerate(lines):
                    rect = metrics.boundingRect(line)
                    if i == 0:
                        cursor_y += rect.height()
                    elif self.line_spacing is None:
                        cursor_y += (rect.height() - rect.y())
                    else:
                        cursor_y += self.line_spacing
                    painter_path.addText(QPointF(0, cursor_y), qfont, line)
                painter.drawPath(painter_path)
        painter.end()
        return qimage_to_numpy(image)
