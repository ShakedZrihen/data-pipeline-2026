"""ChainId -> display name, seeded into ``chains`` at startup (insert-if-missing).

Values are the ``ChainId`` each chain writes into its price-transparency
files. Victory publishes under two ids. A chain missing here still loads
fine (``provider`` is not a foreign key); it just has no name until a row is
added.
"""

CHAINS: dict[str, str] = {
    "7290027600007": "שופרסל",
    "7290058140886": "רמי לוי",
    "7290803800003": "יוחננוף",
    "7290696200003": "ויקטורי",
    "7290058103393": "ויקטורי",
    "7290700100008": "חצי חינם",
    "7290873255550": "טיב טעם",
    "7290172900007": "סופר פארם",
}
