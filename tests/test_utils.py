from estate_scraper.utils import slugify, extract_store_slug


class TestSlugify:
    def test_basic(self):
        assert slugify("Hello World") == "hello-world"

    def test_special_chars(self):
        assert slugify("Price: $1,234!") == "price-1234"

    def test_multiple_spaces(self):
        assert slugify("too   many   spaces") == "too-many-spaces"

    def test_max_length(self):
        result = slugify("a" * 100, max_length=10)
        assert len(result) == 10

    def test_trailing_dash_after_truncation(self):
        result = slugify("hello world foo", max_length=6)
        assert not result.endswith("-")

    def test_empty_string(self):
        assert slugify("") == ""

    def test_already_slug(self):
        assert slugify("already-a-slug") == "already-a-slug"


class TestExtractStoreSlug:
    def test_with_store_slug_param(self):
        url = "https://www.bidmaxpro.com/index.php?module=listings&store_slug=my-auction-sale"
        assert extract_store_slug(url) == "my-auction-sale"

    def test_without_store_slug_param(self):
        url = "https://www.bidmaxpro.com/index.php?module=listings"
        result = extract_store_slug(url)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_complex_slug(self):
        url = "https://www.bidmaxpro.com/index.php?store_slug=british-jetsetter-collector-of-miscellany-auction-in-walnut-creek-ca-3-28-3-29"
        assert extract_store_slug(url) == "british-jetsetter-collector-of-miscellany-auction-in-walnut-creek-ca-3-28-3-29"
