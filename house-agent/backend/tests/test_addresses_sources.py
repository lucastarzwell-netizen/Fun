from house_agent.addresses import address_key
from house_agent.agent.sources import redfin_county_url, redfin_filter
from house_agent.schemas import Criteria, Region


def test_address_key_matches_common_variants():
    a = address_key("17902 State Route 2", "Wauseon", "OH")
    b = address_key("17902 State Rte. 2", "wauseon", "oh")
    assert a == b
    assert address_key("825 East River Road", "Flushing", "MI") == address_key(
        "825 E River Rd", "Flushing", "MI"
    )
    assert address_key("3300 Mackin Rd Unit G", "Flint", "MI") == address_key(
        "3300 Mackin Rd #G", "Flint", "MI"
    )


def test_address_key_distinguishes_cities():
    assert address_key("1 Main St", "Adrian", "MI") != address_key("1 Main St", "Monroe", "MI")


def test_redfin_county_url_matches_routine_pattern():
    c = Criteria(min_price=100_000, max_price=175_000, min_acres=1)
    region = Region(name="Lenawee County", state="MI", anchor="DTW", redfin_county_id=1393)
    assert redfin_county_url(region, c) == (
        "https://www.redfin.com/county/1393/MI/Lenawee-County/filter/"
        "property-type=house,min-price=100k,max-price=175k,min-lot-size=1-acre"
    )


def test_redfin_filter_rounds_lot_down_and_handles_odd_prices():
    c = Criteria(min_price=162_500, max_price=None, min_acres=1.5, min_beds=3)
    assert redfin_filter(c) == "property-type=house,min-price=162.5k,min-beds=3,min-lot-size=1-acre"


def test_region_without_id_has_no_url():
    region = Region(name="St. Clair County", state="MI", anchor="DTW")
    assert redfin_county_url(region, Criteria()) is None
