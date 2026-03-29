from estate_scraper.cli import _parse_selection


class TestParseSelection:
    def test_single_number(self):
        assert _parse_selection("1", 20) == [1]

    def test_multiple_numbers(self):
        assert _parse_selection("1,3,5", 20) == [1, 3, 5]

    def test_range(self):
        assert _parse_selection("5-10", 20) == [5, 6, 7, 8, 9, 10]

    def test_mixed(self):
        assert _parse_selection("1,3-5,10", 20) == [1, 3, 4, 5, 10]

    def test_all_keyword(self):
        result = _parse_selection("all", 20)
        assert result == list(range(1, 11))  # Top 10

    def test_all_with_small_list(self):
        result = _parse_selection("all", 5)
        assert result == [1, 2, 3, 4, 5]

    def test_out_of_bounds(self):
        assert _parse_selection("99", 10) == []

    def test_deduplication(self):
        result = _parse_selection("1,1,2,2", 10)
        assert result == [1, 2]

    def test_empty_string(self):
        assert _parse_selection("", 10) == []

    def test_whitespace_handling(self):
        assert _parse_selection(" 1 , 3 , 5 ", 20) == [1, 3, 5]
