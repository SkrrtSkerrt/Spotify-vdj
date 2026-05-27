import unittest

from gui import setup_dialog


class SetupDialogHelperTests(unittest.TestCase):
    def test_coerce_spinbox_value_clamps_invalid_values(self):
        self.assertEqual(setup_dialog._coerce_spinbox_value("abc", default=30, minimum=5, maximum=300), 30)
        self.assertEqual(setup_dialog._coerce_spinbox_value(999, default=30, minimum=5, maximum=300), 300)
        self.assertEqual(setup_dialog._coerce_spinbox_value(1, default=30, minimum=5, maximum=300), 5)


if __name__ == "__main__":
    unittest.main()
