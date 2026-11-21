"""Independent acceptance conditions for the reference coding task."""

import unittest

from calculator import invoice_total


class InvoiceTests(unittest.TestCase):
    def test_discount_reduces_total(self) -> None:
        self.assertEqual(invoice_total([100], 0.1), 90)

    def test_multiple_items(self) -> None:
        self.assertEqual(invoice_total([20, 30], 0.2), 40)

    def test_no_discount(self) -> None:
        self.assertEqual(invoice_total([10, 25]), 35)

    def test_full_discount(self) -> None:
        self.assertEqual(invoice_total([100], 1), 0)

    def test_invalid_discount(self) -> None:
        with self.assertRaises(ValueError):
            invoice_total([100], -0.1)


if __name__ == "__main__":
    unittest.main()
