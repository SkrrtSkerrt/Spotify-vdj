import unittest

from gui import main_window


class _FakeScrollBar:
    def __init__(self, value=0):
        self._value = value

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = value


class _FakeTrackTable:
    def __init__(self, selected_rows=None, scroll_value=0):
        self._selected_rows = selected_rows or []
        self._scroll_bar = _FakeScrollBar(scroll_value)
        self.selected_row = None

    def selectedItems(self):
        return [type("Item", (), {"row": lambda self, r=row: r})() for row in self._selected_rows]

    def verticalScrollBar(self):
        return self._scroll_bar

    def setCurrentCell(self, row, column):
        self.selected_row = (row, column)

    def clearSelection(self):
        self._selected_rows = []


class TrackViewStateTests(unittest.TestCase):
    def test_capture_track_view_state_tracks_selection_and_scroll(self):
        table = _FakeTrackTable(selected_rows=[2], scroll_value=41)
        tracks = [{"id": "a"}, {"id": "b"}, {"id": "c"}]

        state = main_window._capture_track_view_state(table, tracks)

        self.assertEqual(state, {"selected_track_id": "c", "scroll_value": 41})

    def test_restore_track_view_state_selects_matching_track_and_scroll(self):
        table = _FakeTrackTable(selected_rows=[], scroll_value=0)
        tracks = [{"id": "a"}, {"id": "b"}, {"id": "c"}]

        main_window._apply_track_view_state(table, tracks, {"selected_track_id": "b", "scroll_value": 12})

        self.assertEqual(table.selected_row, (1, 0))
        self.assertEqual(table.verticalScrollBar().value(), 12)

    def test_restore_track_view_state_ignores_missing_track(self):
        table = _FakeTrackTable(selected_rows=[], scroll_value=0)
        tracks = [{"id": "a"}, {"id": "b"}]

        main_window._apply_track_view_state(table, tracks, {"selected_track_id": "z", "scroll_value": 12})

        self.assertIsNone(table.selected_row)
        self.assertEqual(table.verticalScrollBar().value(), 12)
