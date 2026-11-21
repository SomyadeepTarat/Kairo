"""Small command-line invoice calculator."""


def invoice_total(prices: list[float], discount: float = 0) -> float:
    if not 0 <= discount <= 1:
        raise ValueError("discount must be between zero and one")
    return round(sum(prices) * (1 + discount), 2)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Calculate a discounted invoice total")
    parser.add_argument("prices", nargs="+", type=float)
    parser.add_argument("--discount", type=float, default=0)
    args = parser.parse_args()
    print(f"{invoice_total(args.prices, args.discount):.2f}")
